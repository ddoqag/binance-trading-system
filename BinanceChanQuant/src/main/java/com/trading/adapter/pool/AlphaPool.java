package com.trading.adapter.pool;

import com.trading.domain.signal.AlphaExpert;
import com.trading.domain.signal.AlphaSignal;
import com.trading.domain.signal.AlphaType;
import com.trading.domain.signal.CompositeAlphaSignal;
import com.trading.domain.signal.MarketContext;
import com.trading.domain.trading.model.TradeDirection;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Collectors;

/**
 * Alpha Pool - Central signal bus managing all AlphaExperts
 * Collects signals from multiple experts, fuses them into composite signal
 */
public class AlphaPool {

    private final Map<String, AlphaExpert> experts = new ConcurrentHashMap<>();
    private final List<AlphaSignal> recentSignals = new CopyOnWriteArrayList<>();

    private final AtomicInteger totalSignalsGenerated = new AtomicInteger(0);
    private final AtomicInteger totalSignalsExecuted = new AtomicInteger(0);

    // Temperature for softmax
    private double temperature = 1.0;

    public void registerExpert(AlphaExpert expert) {
        if (expert != null) {
            experts.put(expert.getId(), expert);
            System.out.println("[AlphaPool] Registered expert: " + expert.getId() + " (" + expert.getType() + ")");
        }
    }

    public void unregisterExpert(String expertId) {
        experts.remove(expertId);
    }

    public AlphaExpert getExpert(String expertId) {
        return experts.get(expertId);
    }

    public Map<String, AlphaExpert> getExperts() {
        return new ConcurrentHashMap<>(experts);
    }

    public int getExpertCount() {
        return experts.size();
    }

    public int getActiveExpertCount() {
        return (int) experts.values().stream().filter(AlphaExpert::isActive).count();
    }

    /**
     * Generate composite signal by fusing all expert signals
     */
    public CompositeAlphaSignal generateCompositeSignal(MarketContext context) {
        if (experts.isEmpty()) {
            return null;
        }

        // Parallel signal collection from all active experts
        List<AlphaSignal> signals = experts.values().stream()
            .filter(AlphaExpert::isActive)
            .map(expert -> {
                try {
                    AlphaSignal sig = expert.generate(context);
                    if (sig == null) {
                        System.out.println("[AlphaPool] Expert " + expert.getId() + " returned null");
                    } else if (sig.getConfidence() <= 0) {
                        System.out.println("[AlphaPool] Expert " + expert.getId() + " confidence=" + sig.getConfidence());
                    } else {
                        System.out.println("[AlphaPool] Expert " + expert.getId() + " sig conf=" + sig.getConfidence() + " dir=" + sig.getDirection());
                    }
                    return sig;
                } catch (Exception e) {
                    System.err.println("[AlphaPool] Expert " + expert.getId() + " failed: " + e.getMessage());
                    return null;
                }
            })
            .filter(signal -> signal != null && signal.getConfidence() > 0)
            .collect(Collectors.toList());

        System.out.println("[AlphaPool] Collected " + signals.size() + " signals from experts");

        if (signals.isEmpty()) {
            return null;
        }

        totalSignalsGenerated.addAndGet(signals.size());

        // Fuse signals
        CompositeAlphaSignal result = fuseSignals(signals, context);
        System.out.println("[AlphaPool] fuseSignals returned " + (result != null ? "signal" : "null") + " totalSignalsGenerated=" + totalSignalsGenerated.get());
        return result;
    }

    /**
     * Get all signals from experts (for analysis)
     */
    public List<AlphaSignal> getAllSignals(MarketContext context) {
        return experts.values().parallelStream()
            .filter(AlphaExpert::isActive)
            .map(expert -> {
                try {
                    return expert.generate(context);
                } catch (Exception e) {
                    return null;
                }
            })
            .filter(signal -> signal != null)
            .collect(Collectors.toList());
    }

    /**
     * Fuse multiple signals into composite
     */
    private CompositeAlphaSignal fuseSignals(List<AlphaSignal> signals, MarketContext context) {
        if (signals.isEmpty()) {
            return null;
        }

        if (signals.size() == 1) {
            // Only one expert provided a signal - reduce confidence due to lack of confirmation
            // But only if we expected multiple experts (at least 2 active experts registered)
            int activeExperts = (int) experts.values().stream().filter(AlphaExpert::isActive).count();
            if (activeExperts >= 2) {
                AlphaSignal singleSignal = signals.get(0);
                // FIX: Reduced penalty from 20% to 10% - was too aggressive
                // Also log which expert provided signal for debugging
                System.out.printf("[AlphaPool] Single-signal (expert=%s, conf=%.2f, expected=%d experts)%n",
                    singleSignal.getSource(), singleSignal.getConfidence(), activeExperts);
                double penalizedConf = singleSignal.getConfidence() * 0.9;
                CompositeAlphaSignal composite = CompositeAlphaSignal.builder()
                    .direction(singleSignal.getDirection())
                    .entryPrice(singleSignal.getEntryPrice())
                    .stopLossPrice(singleSignal.getStopLossPrice())
                    .takeProfitPrice(singleSignal.getTakeProfitPrice())
                    .confidence(penalizedConf)
                    .urgency(singleSignal.getUrgency())
                    .horizonMinutes(singleSignal.getHorizonMinutes())
                    .expectedReturn(singleSignal.getExpectedReturn())
                    .expectedVolatility(singleSignal.getExpectedVolatility())
                    .source("Composite:" + singleSignal.getSource())
                    .build();
                composite.addComponentSignal(singleSignal);
                composite.setType(AlphaType.COMPOSITE);
                return composite;
            }
            return CompositeAlphaSignal.fromSingle(signals.get(0));
        }

        // Score all signals
        List<ScoredSignal> scoredSignals = signals.stream()
            .map(signal -> {
                double weight = getExpertWeight(signal.getSource(), signal.getType());
                double score = signal.getScore(context) * weight;
                return new ScoredSignal(signal, score);
            })
            .sorted(Comparator.comparingDouble(ScoredSignal::getScore).reversed())
            .collect(Collectors.toList());

        // Check for conflicts
        AlphaSignal bestSignal = scoredSignals.get(0).getSignal();
        double bestScore = scoredSignals.get(0).getScore();

        // Detect conflicting signals (opposite direction, similar score)
        AlphaSignal bestDir = bestSignal;
        TradeDirection bestDirEnum = bestDir.getDirection();
        boolean highVol = context != null && context.isHighVolatility();
        List<AlphaSignal> conflicts = scoredSignals.stream()
            .filter(ss -> {
                TradeDirection sd = ss.getSignal().getDirection();
                boolean directionDiffers = sd != bestDirEnum;
                boolean scoreThreshold = highVol
                    ? ss.getScore() > 0.3  // Absolute threshold for high vol conflicts
                    : ss.getScore() > bestScore * 0.8;  // Relative threshold otherwise
                return directionDiffers && scoreThreshold;
            })
            .map(ScoredSignal::getSignal)
            .collect(Collectors.toList());

        if (!conflicts.isEmpty()) {
            // Resolve conflict
            AlphaSignal resolved = resolveConflict(bestSignal, conflicts, context);
            if (resolved == null) {
                return null; // No trade on unresolvable conflict
            }
            bestSignal = resolved;
        }

        // Create composite signal
        CompositeAlphaSignal composite = CompositeAlphaSignal.builder()
            .direction(bestSignal.getDirection())
            .entryPrice(bestSignal.getEntryPrice())
            .stopLossPrice(bestSignal.getStopLossPrice())
            .takeProfitPrice(bestSignal.getTakeProfitPrice())
            .confidence(bestSignal.getConfidence())
            .urgency(bestSignal.getUrgency())
            .horizonMinutes(bestSignal.getHorizonMinutes())
            .expectedReturn(bestSignal.getExpectedReturn())
            .expectedVolatility(bestSignal.getExpectedVolatility())
            .source("AlphaPool:" + bestSignal.getSource())
            .build();

        // Add component signals
        for (AlphaSignal signal : signals) {
            composite.addComponentSignal(signal);
        }

        composite.setSource(bestSignal.getSource());
        composite.setType(bestSignal.getType());

        return composite;
    }

    /**
     * Resolve signal conflicts using static helper
     */
    private AlphaSignal resolveConflict(AlphaSignal best, List<AlphaSignal> conflicts, MarketContext context) {
        return resolveSignalConflict(best, conflicts, context);
    }

    /**
     * Static conflict resolution helper - extracted for testability and injection
     */
    static AlphaSignal resolveSignalConflict(AlphaSignal best, List<AlphaSignal> conflicts, MarketContext context) {
        // Strategy 1: High volatility -> prefer VOLATILITY expert
        if (context != null && context.isHighVolatility()) {
            for (AlphaSignal conflict : conflicts) {
                if (conflict.getType() == AlphaType.VOLATILITY) {
                    return conflict;
                }
            }
        }

        // Strategy 2: Trend market -> prefer TREND_FOLLOWING expert
        if (context != null && context.isTrendMarket()) {
            for (AlphaSignal conflict : conflicts) {
                if (conflict.getType() == AlphaType.TREND_FOLLOWING || conflict.getType() == AlphaType.CHAN_TREND) {
                    return conflict;
                }
            }
        }

        // Strategy 3: Range market -> prefer MEAN_REVERSION expert
        if (context != null && context.isRangeMarket()) {
            for (AlphaSignal conflict : conflicts) {
                if (conflict.getType() == AlphaType.MEAN_REVERSION || conflict.getType() == AlphaType.CHAN_GRID) {
                    return conflict;
                }
            }
        }

        // Strategy 4: Return highest confidence signal
        return best.getConfidence() >= conflicts.get(0).getConfidence() ? best : conflicts.get(0);
    }

    /**
     * Get weight for expert
     */
    private double getExpertWeight(String expertId, AlphaType type) {
        AlphaExpert expert = experts.get(expertId);
        if (expert != null) {
            return expert.getWeight();
        }
        // Default weight based on type
        return type.getDefaultWeight();
    }

    /**
     * Record execution result for learning
     */
    public void recordExecutionResult(AlphaExpert.ExecutionResult result) {
        if (result == null || result.getAlphaId() == null) {
            return;
        }

        // Find and notify relevant expert
        experts.values().forEach(expert -> expert.recordOutcome(result));

        totalSignalsExecuted.incrementAndGet();
    }

    /**
     * Get recent signals
     */
    public List<AlphaSignal> getRecentSignals(int limit) {
        int size = recentSignals.size();
        if (size <= limit) {
            return new ArrayList<>(recentSignals);
        }
        return new ArrayList<>(recentSignals.subList(size - limit, size));
    }

    /**
     * Get pool status
     */
    public PoolStatus getStatus() {
        return new PoolStatus(
            experts.size(),
            getActiveExpertCount(),
            totalSignalsGenerated.get(),
            totalSignalsExecuted.get(),
            recentSignals.size()
        );
    }

    // Inner classes
    private static class ScoredSignal {
        private final AlphaSignal signal;
        private final double score;

        ScoredSignal(AlphaSignal signal, double score) {
            this.signal = signal;
            this.score = score;
        }

        AlphaSignal getSignal() { return signal; }
        double getScore() { return score; }
    }

    public static class PoolStatus {
        public final int totalExperts;
        public final int activeExperts;
        public final int totalSignalsGenerated;
        public final int totalSignalsExecuted;
        public final int recentSignalCount;

        public PoolStatus(int totalExperts, int activeExperts, int totalSignalsGenerated,
                         int totalSignalsExecuted, int recentSignalCount) {
            this.totalExperts = totalExperts;
            this.activeExperts = activeExperts;
            this.totalSignalsGenerated = totalSignalsGenerated;
            this.totalSignalsExecuted = totalSignalsExecuted;
            this.recentSignalCount = recentSignalCount;
        }

        public int getTotalExperts() { return totalExperts; }
        public int getActiveExperts() { return activeExperts; }
        public int getTotalSignalsGenerated() { return totalSignalsGenerated; }
        public int getTotalSignalsExecuted() { return totalSignalsExecuted; }
        public int getRecentSignalCount() { return recentSignalCount; }
    }
}