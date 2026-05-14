package com.trading.domain.alpha;

import com.trading.domain.market.model.MarketRegime;
import com.trading.domain.signal.AlphaType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Consumer;

/**
 * AlphaTrajectoryAnalyzer - Computes temporal dynamics from closed trajectories
 *
 * Independent component (not part of AlphaPool) for computing:
 * 1. Edge Half-Life per AlphaType
 * 2. MFE/MAE Distribution per AlphaType
 * 3. Decay Regime Sensitivity (half-life varies by regime)
 *
 * Only analyzes CLOSED trajectories (not active ones).
 * Active trajectories feed live data to AlphaTrajectoryTracker.
 */
public final class AlphaTrajectoryAnalyzer {

    private static final Logger log = LoggerFactory.getLogger(AlphaTrajectoryAnalyzer.class);

    // Closed trajectories pending analysis (ArrayList for iterator access)
    private final List<TrajectoryMetrics> closedMetrics = new ArrayList<>();

    // Per-AlphaType accumulated statistics
    private final Map<AlphaType, TypeStatistics> typeStats = new ConcurrentHashMap<>();

    // Per-regime accumulated statistics
    private final Map<MarketRegime, RegimeStatistics> regimeStats = new ConcurrentHashMap<>();

    // On metrics computed callback
    private Consumer<TrajectoryMetrics> onMetricsComputed;

    private AlphaTrajectoryAnalyzer() {}

    public static AlphaTrajectoryAnalyzer create() {
        return new AlphaTrajectoryAnalyzer();
    }

    /**
     * Analyze a closed trajectory and compute metrics
     */
    public TrajectoryMetrics analyze(AlphaTrajectoryRuntime runtime, AlphaHypothesis hypothesis) {
        if (runtime.status() != AlphaTrajectoryRuntime.TrajectoryStatus.CLOSED_PROFIT &&
            runtime.status() != AlphaTrajectoryRuntime.TrajectoryStatus.CLOSED_LOSS) {
            log.debug("[Analyzer] Trajectory {} not closed yet, status={}", runtime.trajectoryId(), runtime.status());
            return null;
        }

        List<PnlSnapshot> snapshots = runtime.getSnapshots();
        if (snapshots.isEmpty()) {
            log.warn("[Analyzer] Trajectory {} has no snapshots", runtime.trajectoryId());
            return null;
        }

        // Compute metrics
        TrajectoryMetrics metrics = computeMetrics(runtime, hypothesis, snapshots);
        if (metrics == null) return null;

        // Store for aggregation
        closedMetrics.add(metrics);
        aggregateByType(metrics, hypothesis.getAlphaType());
        aggregateByRegime(metrics);

        if (onMetricsComputed != null) {
            onMetricsComputed.accept(metrics);
        }

        log.info("[Analyzer] Computed metrics for {}: MFE={}R MAE={}R halfLife={}ms realized={}R",
            metrics.alphaId(), metrics.mfe(), metrics.mae(), metrics.halfLifeMs(), metrics.realizedPnl());

        return metrics;
    }

    private TrajectoryMetrics computeMetrics(AlphaTrajectoryRuntime runtime,
                                              AlphaHypothesis hypothesis,
                                              List<PnlSnapshot> snapshots) {
        try {
            double mfe = runtime.currentMfe();
            double mae = runtime.currentMae();
            double realizedPnl = runtime.exitRMultiple();
            long totalDuration = snapshots.get(snapshots.size() - 1).timestamp() - snapshots.get(0).timestamp();

            // Find time to MFE (when did we hit the best point?)
            long timeToMfe = findTimeToMfe(snapshots, mfe);

            // Estimate half-life and confidence intervals
            HalfLifeEstimate halfLifeEst = estimateHalfLifeWithConfidence(snapshots, totalDuration);

            // Decay rate: R per millisecond
            double decayRate = (totalDuration > 0) ? (mfe / totalDuration) : 0;

            // MFE/MAE ratio
            double mfeMaeRatio = (mae < 0) ? Math.abs(mfe / mae) : 0;

            // Classify decay cause
            TrajectoryMetrics.DecayCause decayCause = classifyDecayCause(snapshots, mfe, totalDuration);

            // Compute probabilistic attribution
            DecayAttribution attribution = computeDecayAttribution(runtime.trajectoryId(), snapshots, mfe, totalDuration);

            // Compute volatility statistics
            double avgVol = computeAvgVolatility(snapshots);
            double peakVol = computePeakVolatility(snapshots);

            // Find dominant regime
            MarketRegime dominantRegime = computeDominantRegime(snapshots);

            return TrajectoryMetrics.builder()
                .alphaId(runtime.trajectoryId())
                .mfe(mfe)
                .mae(mae)
                .realizedPnl(realizedPnl)
                .halfLifeMs(halfLifeEst.medianMs)
                .halfLifeStdDevMs(halfLifeEst.stdDevMs)
                .halfLifeP50Ms(halfLifeEst.p50Ms)
                .halfLifeP90Ms(halfLifeEst.p90Ms)
                .timeToMfeMs(timeToMfe)
                .totalDurationMs(totalDuration)
                .decayRate(decayRate)
                .mfeMaeRatio(mfeMaeRatio)
                .snapshotCount(snapshots.size())
                .decayCause(decayCause)
                .attribution(attribution)
                .dominantRegime(dominantRegime)
                .avgVolatility(avgVol)
                .peakVolatility(peakVol)
                .build();

        } catch (Exception e) {
            log.error("[Analyzer] Error computing metrics for {}", runtime.trajectoryId(), e);
            return null;
        }
    }

    /**
     * Half-life estimate with confidence intervals
     */
    private static class HalfLifeEstimate {
        final long medianMs;
        final long stdDevMs;
        final long p50Ms;
        final long p90Ms;

        HalfLifeEstimate(long medianMs, long stdDevMs, long p50Ms, long p90Ms) {
            this.medianMs = medianMs;
            this.stdDevMs = stdDevMs;
            this.p50Ms = p50Ms;
            this.p90Ms = p90Ms;
        }
    }

    private HalfLifeEstimate estimateHalfLifeWithConfidence(List<PnlSnapshot> snapshots, long totalDuration) {
        if (snapshots.size() < 3) {
            long hl = estimateHalfLife(snapshots, totalDuration);
            return new HalfLifeEstimate(hl, hl / 2, hl, hl * 2);
        }

        // Bootstrap-style estimation from sub-windows
        // Use different starting points to estimate variance
        long entryTime = snapshots.get(0).timestamp();
        int size = snapshots.size();
        long[] halfLifeSamples = new long[size - 1];

        for (int i = 1; i < size; i++) {
            // Estimate half-life from first i snapshots
            List<PnlSnapshot> subList = snapshots.subList(0, i + 1);
            halfLifeSamples[i - 1] = estimateHalfLife(subList, snapshots.get(i).timestamp() - entryTime);
        }

        // Calculate statistics
        long sum = 0;
        for (long hl : halfLifeSamples) sum += hl;
        long median = halfLifeSamples[halfLifeSamples.length / 2];

        // Standard deviation
        double sumSq = 0;
        for (long hl : halfLifeSamples) {
            double diff = hl - median;
            sumSq += diff * diff;
        }
        long stdDev = (long) Math.sqrt(sumSq / halfLifeSamples.length);

        // P50 and P90 (simplified using sorted samples)
        long p50 = halfLifeSamples[halfLifeSamples.length * 50 / 100];
        long p90 = halfLifeSamples[Math.min(halfLifeSamples.length - 1, halfLifeSamples.length * 90 / 100)];

        return new HalfLifeEstimate(median, stdDev, p50, p90);
    }

    private long findTimeToMfe(List<PnlSnapshot> snapshots, double mfe) {
        long entryTime = snapshots.get(0).timestamp();
        for (PnlSnapshot snap : snapshots) {
            if (Math.abs(snap.rMultiple() - mfe) < 0.01) {
                return snap.timestamp() - entryTime;
            }
        }
        return 0;
    }

    private long estimateHalfLife(List<PnlSnapshot> snapshots, long totalDuration) {
        if (snapshots.size() < 2) return totalDuration;

        // Find peak R and when it decayed to 50%
        double peakR = Double.MIN_VALUE;
        long peakTime = 0;

        for (PnlSnapshot snap : snapshots) {
            if (snap.rMultiple() > peakR) {
                peakR = snap.rMultiple();
                peakTime = snap.timestamp();
            }
        }

        double halfPeak = peakR * 0.5;
        long entryTime = snapshots.get(0).timestamp();
        long halfLifeTime = totalDuration; // default: didn't decay to 50%

        for (PnlSnapshot snap : snapshots) {
            if (snap.timestamp() > peakTime && snap.rMultiple() <= halfPeak) {
                halfLifeTime = snap.timestamp() - entryTime;
                break;
            }
        }

        return halfLifeTime;
    }

    /**
     * Classify the primary cause of alpha decay
     * Critical for learning - distinguishes natural decay from external disruption
     */
    private TrajectoryMetrics.DecayCause classifyDecayCause(List<PnlSnapshot> snapshots, double mfe, long totalDuration) {
        if (snapshots.isEmpty()) return TrajectoryMetrics.DecayCause.UNKNOWN;

        // Check if this was a successful trade (target hit)
        PnlSnapshot last = snapshots.get(snapshots.size() - 1);
        if (last.rMultiple() >= 2.0) {
            return TrajectoryMetrics.DecayCause.TARGET_HIT;
        }

        // Check if stopped out
        if (last.rMultiple() <= -1.0) {
            return TrajectoryMetrics.DecayCause.STOP_HIT;
        }

        // Check for regime changes during trajectory
        boolean hasRegimeChange = false;
        MarketRegime firstRegime = snapshots.get(0).regime();
        for (PnlSnapshot snap : snapshots) {
            if (snap.regime() != firstRegime) {
                hasRegimeChange = true;
                break;
            }
        }

        if (hasRegimeChange) {
            return TrajectoryMetrics.DecayCause.REGIME_SHIFT;
        }

        // Check for volatility explosion
        double volPeak = computePeakVolatility(snapshots);
        double volStart = snapshots.get(0).regime().ordinal(); // simplified
        if (volPeak > volStart * 2) {
            return TrajectoryMetrics.DecayCause.VOLATILITY_EXPLOSION;
        }

        // Check if timed out (held too long without decaying)
        if (totalDuration > 30 * 60 * 1000 && last.rMultiple() < mfe * 0.5) {
            return TrajectoryMetrics.DecayCause.TIMEOUT;
        }

        // Default: natural decay
        return TrajectoryMetrics.DecayCause.NATURAL_DECAY;
    }

    /**
     * Compute probabilistic decay attribution
     * Returns a distribution over causes rather than single label
     */
    private DecayAttribution computeDecayAttribution(String alphaId,
                                                       List<PnlSnapshot> snapshots,
                                                       double mfe,
                                                       long totalDuration) {
        if (snapshots.size() < 2) {
            return DecayAttribution.fromFactors(alphaId, Map.of(), snapshots.size());
        }

        // Compute contributing factors based on observed signals
        Map<TrajectoryMetrics.DecayCause, Double> factors = new java.util.EnumMap<>(TrajectoryMetrics.DecayCause.class);

        // Factor 1: Regime change contribution
        double regimeContribution = computeRegimeChangeContribution(snapshots);
        if (regimeContribution > 0) {
            factors.put(TrajectoryMetrics.DecayCause.REGIME_SHIFT, regimeContribution);
        }

        // Factor 2: Volatility explosion contribution
        double volContribution = computeVolatilityContribution(snapshots);
        if (volContribution > 0) {
            factors.put(TrajectoryMetrics.DecayCause.VOLATILITY_EXPLOSION, volContribution);
        }

        // Factor 3: Trend break contribution
        double trendContribution = computeTrendBreakContribution(snapshots);
        if (trendContribution > 0) {
            factors.put(TrajectoryMetrics.DecayCause.TREND_BREAK, trendContribution);
        }

        // Factor 4: Natural decay (time-based)
        double naturalContribution = computeNaturalDecayContribution(snapshots, totalDuration);
        factors.put(TrajectoryMetrics.DecayCause.NATURAL_DECAY, naturalContribution);

        // Factor 5: Timeout contribution
        if (totalDuration > 30 * 60 * 1000) {
            double timeoutContribution = Math.min(0.3, (totalDuration - 30 * 60 * 1000.0) / (60 * 60 * 1000));
            factors.put(TrajectoryMetrics.DecayCause.TIMEOUT, timeoutContribution);
        }

        // Normalize to probability distribution
        double sum = factors.values().stream().mapToDouble(Double::doubleValue).sum();
        if (sum > 0) {
            factors.replaceAll((k, v) -> v / sum);
        }

        return DecayAttribution.fromFactors(alphaId, factors, snapshots.size());
    }

    private double computeRegimeChangeContribution(List<PnlSnapshot> snapshots) {
        if (snapshots.size() < 2) return 0;
        MarketRegime firstRegime = snapshots.get(0).regime();
        int regimeChanges = 0;
        for (PnlSnapshot snap : snapshots) {
            if (snap.regime() != firstRegime) regimeChanges++;
        }
        // Contribution scales with number of regime changes
        return Math.min(1.0, regimeChanges / (double) snapshots.size() * 2);
    }

    private double computeVolatilityContribution(List<PnlSnapshot> snapshots) {
        if (snapshots.size() < 2) return 0;
        double volStart = snapshots.get(0).regime().ordinal();
        double volPeak = computePeakVolatility(snapshots);
        if (volStart <= 0) return 0;
        double ratio = volPeak / volStart;
        // Contribution if volatility more than doubled
        return ratio > 2.0 ? Math.min(1.0, (ratio - 2.0) / 2.0) : 0;
    }

    private double computeTrendBreakContribution(List<PnlSnapshot> snapshots) {
        if (snapshots.size() < 3) return 0;
        // Check for directional consistency break
        int directionChanges = 0;
        for (int i = 1; i < snapshots.size(); i++) {
            double r1 = snapshots.get(i - 1).rMultiple();
            double r2 = snapshots.get(i).rMultiple();
            if ((r1 > 0 && r2 < 0) || (r1 < 0 && r2 > 0)) {
                directionChanges++;
            }
        }
        return Math.min(1.0, directionChanges / (double) snapshots.size());
    }

    private double computeNaturalDecayContribution(List<PnlSnapshot> snapshots, long totalDuration) {
        // Natural decay is baseline - always has some contribution
        // More weight if no other clear factors
        double baseWeight = 0.2;
        // Increase if held for a long time
        if (totalDuration > 10 * 60 * 1000) {
            return Math.min(0.5, baseWeight + totalDuration / (60.0 * 60 * 1000 * 10));
        }
        return baseWeight;
    }

    private double computeAvgVolatility(List<PnlSnapshot> snapshots) {
        if (snapshots.isEmpty()) return 0;
        double sum = 0;
        for (PnlSnapshot snap : snapshots) {
            sum += snap.regime().ordinal(); // simplified - should use actual volatility metric
        }
        return sum / snapshots.size();
    }

    private double computePeakVolatility(List<PnlSnapshot> snapshots) {
        if (snapshots.isEmpty()) return 0;
        double peak = 0;
        for (PnlSnapshot snap : snapshots) {
            double vol = snap.regime().ordinal();
            if (vol > peak) peak = vol;
        }
        return peak;
    }

    private MarketRegime computeDominantRegime(List<PnlSnapshot> snapshots) {
        if (snapshots.isEmpty()) return MarketRegime.UNKNOWN;

        Map<MarketRegime, Integer> regimeCounts = new EnumMap<>(MarketRegime.class);
        for (PnlSnapshot snap : snapshots) {
            regimeCounts.merge(snap.regime(), 1, Integer::sum);
        }

        return regimeCounts.entrySet().stream()
            .max(Map.Entry.comparingByValue())
            .map(Map.Entry::getKey)
            .orElse(MarketRegime.UNKNOWN);
    }

    private void aggregateByType(TrajectoryMetrics metrics, AlphaType type) {
        typeStats.computeIfAbsent(type, k -> new TypeStatistics())
            .add(metrics);
    }

    private void aggregateByRegime(TrajectoryMetrics metrics) {
        if (metrics.dominantRegime() == null) return;
        regimeStats.computeIfAbsent(metrics.dominantRegime(), k -> new RegimeStatistics())
            .add(metrics);
    }

    // Query methods for MetaLearner

    public Optional<TypeStatistics> getTypeStatistics(AlphaType type) {
        return Optional.ofNullable(typeStats.get(type));
    }

    public Optional<RegimeStatistics> getRegimeStatistics(MarketRegime regime) {
        return Optional.ofNullable(regimeStats.get(regime));
    }

    public Collection<TypeStatistics> allTypeStatistics() {
        return Collections.unmodifiableCollection(typeStats.values());
    }

    public Collection<RegimeStatistics> allRegimeStatistics() {
        return Collections.unmodifiableCollection(regimeStats.values());
    }

    public List<TrajectoryMetrics> recentClosed(int n) {
        List<TrajectoryMetrics> result = new ArrayList<>();
        int start = Math.max(0, closedMetrics.size() - n);
        for (int i = closedMetrics.size() - 1; i >= start; i--) {
            result.add(closedMetrics.get(i));
        }
        return result;
    }

    public AlphaTrajectoryAnalyzer onMetricsComputed(Consumer<TrajectoryMetrics> callback) {
        this.onMetricsComputed = callback;
        return this;
    }

    /**
     * Per-AlphaType aggregated statistics
     */
    public static final class TypeStatistics {
        private double sumMfe;
        private double sumMae;
        private double sumRealizedPnl;
        private long sumHalfLife;
        private int count;

        public void add(TrajectoryMetrics m) {
            sumMfe += m.mfe();
            sumMae += m.mae();
            sumRealizedPnl += m.realizedPnl();
            sumHalfLife += m.halfLifeMs();
            count++;
        }

        public int count() { return count; }
        public double avgMfe() { return count > 0 ? sumMfe / count : 0; }
        public double avgMae() { return count > 0 ? sumMae / count : 0; }
        public double avgRealizedPnl() { return count > 0 ? sumRealizedPnl / count : 0; }
        public double avgHalfLifeMs() { return count > 0 ? (double) sumHalfLife / count : 0; }
        public double avgMfeMaeRatio() {
            double total = 0;
            int ratioCount = 0;
            // This is a simplified version
            return count > 0 ? (avgMfe() / Math.abs(avgMae())) : 0;
        }

        @Override
        public String toString() {
            return String.format("TypeStat[n=%d MFE=%.2f MAE=%.2f PnL=%.2f halfLife=%dms]",
                count, avgMfe(), avgMae(), avgRealizedPnl(), (long) avgHalfLifeMs());
        }
    }

    /**
     * Per-regime aggregated statistics
     */
    public static final class RegimeStatistics {
        private double sumMfe;
        private double sumMae;
        private long sumHalfLife;
        private int count;

        public void add(TrajectoryMetrics m) {
            sumMfe += m.mfe();
            sumMae += m.mae();
            sumHalfLife += m.halfLifeMs();
            count++;
        }

        public int count() { return count; }
        public double avgMfe() { return count > 0 ? sumMfe / count : 0; }
        public double avgMae() { return count > 0 ? sumMae / count : 0; }
        public double avgHalfLifeMs() { return count > 0 ? (double) sumHalfLife / count : 0; }

        @Override
        public String toString() {
            return String.format("RegimeStat[n=%d MFE=%.2f MAE=%.2f halfLife=%dms]",
                count, avgMfe(), avgMae(), (long) avgHalfLifeMs());
        }
    }
}