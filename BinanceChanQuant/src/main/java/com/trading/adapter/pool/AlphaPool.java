package com.trading.adapter.pool;

import com.trading.adapter.chan.validation.ChanSignalValidator;
import com.trading.domain.signal.AIAlphaSignal;
import com.trading.domain.signal.AlphaExpert;
import com.trading.domain.signal.AlphaSignal;
import com.trading.domain.signal.AlphaType;
import com.trading.domain.signal.ChanAlphaSignal;
import com.trading.domain.signal.CompositeAlphaSignal;
import com.trading.domain.signal.ExecutionEvent;
import com.trading.domain.signal.MarketContext;
import com.trading.domain.signal.StructuralBias;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.market.model.MarketRegime;
import com.trading.adapter.execution.ExecutionEngine;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

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

    private static final Logger log = LoggerFactory.getLogger(AlphaPool.class);

    private final Map<String, AlphaExpert> experts = new ConcurrentHashMap<>();
    private final List<AlphaSignal> recentSignals = new CopyOnWriteArrayList<>();

    private final AtomicInteger totalSignalsGenerated = new AtomicInteger(0);
    private final AtomicInteger totalSignalsExecuted = new AtomicInteger(0);

    // Temperature for softmax
    private double temperature = 1.0;

    // V6: ExpertTelemetry - tracks expert participation and blocking stats
    private final ConcurrentHashMap<String, ExpertTelemetry> expertTelemetry = new ConcurrentHashMap<>();

    // V6: Sliding window size (only track recent N events for灵敏度)
    private static final int SLIDING_WINDOW_SIZE = 100;

    // V6: Event listener for ExecutionFeedbackBus
    private ExecutionEngine.ExecutionEventListener eventListener;

    public void registerExpert(AlphaExpert expert) {
        if (expert != null) {
            experts.put(expert.getId(), expert);
            log.info("[AlphaPool] Registered expert: {} ({})", expert.getId(), expert.getType());
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

        // P1-2: First pass - collect Chan signals to extract bias for AI expert
        StructuralBias chanBias = StructuralBias.NEUTRAL;
        AlphaSignal chanSignalForBias = null;
        for (Map.Entry<String, AlphaExpert> entry : experts.entrySet()) {
            AlphaExpert expert = entry.getValue();
            if (expert.isActive() && expert.getType() == AlphaType.CHAN_TREND) {
                try {
                    AlphaSignal sig = expert.generate(context);
                    if (sig != null && sig.getConfidence() > 0 && sig instanceof ChanAlphaSignal) {
                        chanSignalForBias = sig;
                        chanBias = extractChanBias((ChanAlphaSignal) sig);
                        log.debug("[AlphaPool] Chan bias extracted: {} (conf={})", chanBias, sig.getConfidence());
                    }
                } catch (Exception e) {
                    // Ignore
                }
            }
        }

        // P1-2: Set Chan bias on AI expert before signal generation
        AlphaExpert aiExpert = experts.get("ai");
        if (aiExpert instanceof AIExpert) {
            ((AIExpert) aiExpert).setChanBias(chanBias);
        }

        // Second pass - collect all signals with updated bias
        List<AlphaSignal> signals = experts.values().stream()
            .filter(AlphaExpert::isActive)
            .map(expert -> {
                try {
                    AlphaSignal sig = expert.generate(context);
                    if (sig == null) {
                        log.warn("[AlphaPool] Expert {} returned null", expert.getId());
                    } else if (sig.getConfidence() <= 0) {
                        log.debug("[AlphaPool] Expert {} confidence={}", expert.getId(), sig.getConfidence());
                    } else {
                        log.debug("[AlphaPool] Expert {} sig conf={} dir={}", expert.getId(), sig.getConfidence(), sig.getDirection());
                    }
                    return sig;
                } catch (Exception e) {
                    log.error("[AlphaPool] Expert {} failed: {}", expert.getId(), e.getMessage());
                    return null;
                }
            })
            .filter(signal -> signal != null && signal.getConfidence() > 0)
            .collect(Collectors.toList());

        log.debug("[AlphaPool] Collected {} signals from experts", signals.size());

        if (signals.isEmpty()) {
            return null;
        }

        totalSignalsGenerated.addAndGet(signals.size());

        // Fuse signals
        CompositeAlphaSignal result = fuseSignals(signals, context);
        log.debug("[AlphaPool] fuseSignals returned {} totalSignalsGenerated={}",
            result != null ? "signal" : "null", totalSignalsGenerated.get());
        return result;
    }

    /**
     * P1-2: Extract StructuralBias from ChanAlphaSignal
     */
    private StructuralBias extractChanBias(ChanAlphaSignal chanSignal) {
        TradeDirection dir = chanSignal.getDirection();
        double conf = chanSignal.getConfidence();

        if (dir == TradeDirection.LONG) {
            return conf > 0.7 ? StructuralBias.STRONG_LONG : StructuralBias.WEAK_LONG;
        } else if (dir == TradeDirection.SHORT) {
            return conf > 0.7 ? StructuralBias.STRONG_SHORT : StructuralBias.WEAK_SHORT;
        }
        return StructuralBias.NEUTRAL;
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

        // P2-1: "弃权" - detect opposing signals with low confidence diff
        if (signals.size() >= 2) {
            AlphaSignal aiSignal = signals.stream()
                .filter(s -> s instanceof AIAlphaSignal)
                .findFirst().orElse(null);
            AlphaSignal chanSignal = signals.stream()
                .filter(s -> s instanceof ChanAlphaSignal)
                .findFirst().orElse(null);

            if (aiSignal != null && chanSignal != null) {
                boolean directionsOppose = aiSignal.getDirection() != chanSignal.getDirection()
                    && aiSignal.getDirection() != TradeDirection.NEUTRAL
                    && chanSignal.getDirection() != TradeDirection.NEUTRAL;
                double confDiff = Math.abs(aiSignal.getConfidence() - chanSignal.getConfidence());

                if (directionsOppose && confDiff < 0.2) {
                    log.info("[AlphaPool] Abstention: AI({}) vs Chan({}), diff={}",
                        aiSignal.getDirection(), chanSignal.getDirection(), String.format("%.2f", confDiff));
                    return createNeutralSignal(signals);
                }
            }
        }

        if (signals.size() == 1) {
            // Only one expert provided a signal
            int activeExperts = (int) experts.values().stream().filter(AlphaExpert::isActive).count();
            if (activeExperts >= 2) {
                AlphaSignal singleSignal = signals.get(0);
                log.info("[AlphaPool] Single-signal: expert={}, conf={}, expected={} experts",
                    singleSignal.getSource(), singleSignal.getConfidence(), activeExperts);

                // V6: Check if other experts were blocked by cooldown - if so, no penalty
                boolean hasCooldownBlock = expertTelemetry.values().stream()
                    .filter(t -> !t.expertId.equals(singleSignal.getSource()))
                    .anyMatch(ExpertTelemetry::hasRecentCooldownBlock);

                if (hasCooldownBlock) {
                    log.info("[AlphaPool] Cooldown block detected, skipping penalty for expert={}",
                        singleSignal.getSource());
                    CompositeAlphaSignal composite = CompositeAlphaSignal.builder()
                        .direction(singleSignal.getDirection())
                        .entryPrice(singleSignal.getEntryPrice())
                        .stopLossPrice(singleSignal.getStopLossPrice())
                        .takeProfitPrice(singleSignal.getTakeProfitPrice())
                        .confidence(singleSignal.getConfidence())  // No penalty
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

                // Original: 10% penalty applied
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
                    // P2优化：逆势信号校验
                    // 如果Chan信号方向与大级别趋势相反，需要额外确认
                    if (conflict.getType() == AlphaType.CHAN_TREND) {
                        boolean counterTrend = isCounterTrendDirection(conflict.getDirection(), context);
                        if (counterTrend && !hasSufficientConfidence(conflict, best)) {
                            // 逆势但置信度不够高，继续检查其他选项
                            continue;
                        }
                    }
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
     * Check if signal direction is counter to the primary trend
     */
    private static boolean isCounterTrendDirection(TradeDirection signalDir, MarketContext context) {
        if (context == null) return false;

        // TREND_DOWN市场中，方向LONG是逆势
        if (context.getRegime() == com.trading.domain.market.model.MarketRegime.TREND_DOWN) {
            return signalDir == TradeDirection.LONG;
        }
        // TREND_UP市场中，方向SHORT是逆势
        if (context.getRegime() == com.trading.domain.market.model.MarketRegime.TREND_UP) {
            return signalDir == TradeDirection.SHORT;
        }
        return false;
    }

    /**
     * Check if Chan signal has sufficient confidence to override counter-trend filter
     * Chan信号需要显著高于AI信号才能逆势入场
     */
    private static boolean hasSufficientConfidence(AlphaSignal chanSignal, AlphaSignal aiSignal) {
        double confGap = chanSignal.getConfidence() - aiSignal.getConfidence();
        // Chan需要比AI高至少0.25才能逆势入场（从0.6到0.85差距=0.25）
        return confGap >= 0.25;
    }

    /**
     * P2-1: Create a neutral/abstention signal when AI and Chan conflict with low confidence diff
     */
    private CompositeAlphaSignal createNeutralSignal(List<AlphaSignal> signals) {
        CompositeAlphaSignal neutral = CompositeAlphaSignal.builder()
            .direction(TradeDirection.NEUTRAL)
            .confidence(0.0)
            .urgency(0.0)
            .horizonMinutes(5) // Short horizon for neutral
            .source("AlphaPool:ABSTENTION")
            .type(AlphaType.COMPOSITE)
            .build();
        // Add all component signals for record
        for (AlphaSignal sig : signals) {
            neutral.addComponentSignal(sig);
        }
        return neutral;
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

    // V6: ExpertTelemetry - tracks per-expert participation with sliding window
    public static class ExpertTelemetry {
        private final String expertId;
        private final AtomicInteger signalsGenerated = new AtomicInteger(0);
        private final AtomicInteger signalsBlockedByCooldown = new AtomicInteger(0);
        private final AtomicInteger signalsBlockedByRisk = new AtomicInteger(0);
        private final AtomicInteger signalsBlockedBySize = new AtomicInteger(0);
        private final AtomicInteger signalsBlockedByToxicity = new AtomicInteger(0);
        private final AtomicInteger signalsBlockedByLatency = new AtomicInteger(0);
        private final AtomicInteger signalsAbstained = new AtomicInteger(0);
        private final AtomicInteger signalsShadowTracked = new AtomicInteger(0);
        private final AtomicInteger signalsProfitable = new AtomicInteger(0);
        private final AtomicInteger signalsLoss = new AtomicInteger(0);
        private final long windowStartTime = System.currentTimeMillis();

        // P2 FIX: Sliding window - track cooldown blocks with timestamps
        private volatile long lastCooldownBlockTime = 0;
        private static final long COOLDOWN_BLOCK_WINDOW_MS = 60_000; // 60 seconds sliding window

        // P0: Theoretical vs Realized PnL separation
        // This is the KEY semantic split: what SHOULD have happened vs what ACTUALLY happened
        private double theoreticalPnl = 0.0;
        private double realizedPnl = 0.0;

        public ExpertTelemetry(String expertId) {
            this.expertId = expertId;
        }

        // ===== Blocked event recorders =====
        public void recordGenerated() { signalsGenerated.incrementAndGet(); }
        public void recordBlockedByCooldown() {
            signalsBlockedByCooldown.incrementAndGet();
            lastCooldownBlockTime = System.currentTimeMillis();
        }
        public void recordBlockedByRisk() { signalsBlockedByRisk.incrementAndGet(); }
        public void recordBlockedBySize() { signalsBlockedBySize.incrementAndGet(); }
        public void recordBlockedByToxicity() { signalsBlockedByToxicity.incrementAndGet(); }
        public void recordBlockedByLatency() { signalsBlockedByLatency.incrementAndGet(); }
        public void recordAbstained() { signalsAbstained.incrementAndGet(); }
        public void recordShadowTracked() { signalsShadowTracked.incrementAndGet(); }
        public void recordProfitable() { signalsProfitable.incrementAndGet(); }
        public void recordLoss() { signalsLoss.incrementAndGet(); }

        // ===== P0: PnL tracking - THEORETICAL vs REALIZED =====
        public void recordTheoreticalPnl(double pnl) { this.theoreticalPnl += pnl; }
        public void recordRealizedPnl(double pnl) { this.realizedPnl += pnl; }

        // ===== Getters =====
        public int getSignalsGenerated() { return signalsGenerated.get(); }
        public int getSignalsBlockedByCooldown() { return signalsBlockedByCooldown.get(); }
        public int getSignalsBlockedByRisk() { return signalsBlockedByRisk.get(); }
        public int getSignalsBlockedBySize() { return signalsBlockedBySize.get(); }
        public int getSignalsBlockedByToxicity() { return signalsBlockedByToxicity.get(); }
        public int getSignalsBlockedByLatency() { return signalsBlockedByLatency.get(); }
        public int getSignalsAbstained() { return signalsAbstained.get(); }
        public int getSignalsShadowTracked() { return signalsShadowTracked.get(); }
        public double getTheoreticalPnl() { return theoreticalPnl; }
        public double getRealizedPnl() { return realizedPnl; }

        // V6: Participation rate - signals generated / (generated + blocked)
        // EXPANDED to include all block types
        public double getParticipationRate() {
            int total = signalsGenerated.get()
                + signalsBlockedByCooldown.get()
                + signalsBlockedByRisk.get()
                + signalsBlockedBySize.get()
                + signalsBlockedByToxicity.get()
                + signalsBlockedByLatency.get();
            return total > 0 ? (double) signalsGenerated.get() / total : 1.0;
        }

        // P0: Alpha Quality = Theoretical PnL / Signals Generated
        // Represents: "Did this expert's signals have merit, regardless of execution?"
        public double getAlphaQuality() {
            int total = signalsGenerated.get() + signalsShadowTracked.get();
            return total > 0 ? theoreticalPnl / total : 0.0;
        }

        // P0: Execution Feasibility = Realized PnL / Theoretical PnL
        // Represents: "What fraction of theoretical alpha was actually captured?"
        // Low value = expert generates good signals but can't execute them (capacity issue)
        public double getExecutionFeasibility() {
            return Math.abs(theoreticalPnl) > 0.0001 ? realizedPnl / theoreticalPnl : 0.0;
        }

        // P0: Block rate breakdown - total blocked / (generated + blocked)
        public double getBlockRate() {
            int total = signalsGenerated.get()
                + signalsBlockedByCooldown.get()
                + signalsBlockedByRisk.get()
                + signalsBlockedBySize.get()
                + signalsBlockedByToxicity.get()
                + signalsBlockedByLatency.get()
                + signalsAbstained.get();
            int blocked = signalsBlockedByCooldown.get()
                + signalsBlockedByRisk.get()
                + signalsBlockedBySize.get()
                + signalsBlockedByToxicity.get()
                + signalsBlockedByLatency.get()
                + signalsAbstained.get();
            return total > 0 ? (double) blocked / total : 0.0;
        }

        // P2 FIX: Has cooldown block within sliding window? Used for single-signal penalty exemption
        public boolean hasRecentCooldownBlock() {
            if (lastCooldownBlockTime == 0) return false;
            long elapsed = System.currentTimeMillis() - lastCooldownBlockTime;
            return elapsed < COOLDOWN_BLOCK_WINDOW_MS;
        }
    }

    /**
     * V6: Set execution event listener to receive ExecutionFeedbackBus events
     */
    public void setEventListener(ExecutionEngine.ExecutionEventListener listener) {
        this.eventListener = listener;
    }

    /**
     * V6: Handle execution event from ExecutionEngine
     * Routes events to appropriate ExpertTelemetry buckets
     */
    public void onExecutionEvent(ExecutionEvent event) {
        if (event == null || event.expertId() == null) return;

        String expertId = event.expertId();
        ExpertTelemetry tel = expertTelemetry.computeIfAbsent(expertId, ExpertTelemetry::new);

        // Extract PnL from metadata if present
        double pnl = 0.0;
        if (event.metadata() != null && event.metadata().containsKey("pnl")) {
            Object pnlObj = event.metadata().get("pnl");
            if (pnlObj instanceof Number) {
                pnl = ((Number) pnlObj).doubleValue();
            }
        }

        switch (event.type()) {
            // Signal generation
            case SIGNAL_GENERATED:
                tel.recordGenerated();
                break;
            // Blocked events - separate by ROOT CAUSE (critical for learning semantics)
            case SIGNAL_BLOCKED_BY_COOLDOWN:
                tel.recordBlockedByCooldown();
                break;
            case SIGNAL_BLOCKED_BY_RISK:
                tel.recordBlockedByRisk();
                break;
            case SIGNAL_BLOCKED_BY_SIZE:
                tel.recordBlockedBySize();
                // SIZE blocked signals still carry theoretical PnL - record it
                if (pnl != 0.0) tel.recordTheoreticalPnl(pnl);
                break;
            case SIGNAL_BLOCKED_BY_TOXICITY:
                tel.recordBlockedByToxicity();
                if (pnl != 0.0) tel.recordTheoreticalPnl(pnl);
                break;
            case SIGNAL_BLOCKED_BY_LATENCY:
                tel.recordBlockedByLatency();
                if (pnl != 0.0) tel.recordTheoreticalPnl(pnl);
                break;
            case SIGNAL_ABSTAINED:
                tel.recordAbstained();
                // Abstained signals may still have theoretical value
                if (pnl != 0.0) tel.recordTheoreticalPnl(pnl);
                break;
            // Shadow tracking - THEORETICAL alpha (not yet realized)
            case SHADOW_TRACKED:
                tel.recordShadowTracked();
                if (pnl != 0.0) tel.recordTheoreticalPnl(pnl);
                break;
            case SHADOW_PROFITABLE:
                tel.recordShadowTracked();
                if (pnl != 0.0) tel.recordTheoreticalPnl(pnl);
                break;
            case SHADOW_LOSS:
                tel.recordShadowTracked();
                if (pnl != 0.0) tel.recordTheoreticalPnl(pnl);
                break;
            // Realized PnL events
            case SIGNAL_PROFITABLE:
                tel.recordProfitable();
                if (pnl != 0.0) {
                    tel.recordRealizedPnl(pnl);
                    tel.recordTheoreticalPnl(pnl); // Also record as theoretical for comparison
                }
                break;
            case SIGNAL_LOSS:
                tel.recordLoss();
                if (pnl != 0.0) {
                    tel.recordRealizedPnl(pnl);
                    tel.recordTheoreticalPnl(pnl);
                }
                break;
            default:
                // Other event types - ignore for telemetry
                break;
        }
    }

    /**
     * V6: Check if any expert was recently blocked by cooldown
     */
    private boolean hasCooldownBlockInRecentSignals() {
        return expertTelemetry.values().stream()
            .anyMatch(ExpertTelemetry::hasRecentCooldownBlock);
    }

    /**
     * V6: Get telemetry for an expert
     */
    public ExpertTelemetry getExpertTelemetry(String expertId) {
        return expertTelemetry.get(expertId);
    }

    /**
     * V6: Get all telemetry data
     */
    public Map<String, ExpertTelemetry> getAllTelemetry() {
        return new ConcurrentHashMap<>(expertTelemetry);
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