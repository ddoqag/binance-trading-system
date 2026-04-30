package com.trading.adapter.chan.optimization;

import com.trading.adapter.chan.analyzer.ChanKLineProcessor;
import com.trading.adapter.chan.config.ChanFeatureToggle;
import com.trading.adapter.chan.validation.ChanSignalValidator;
import com.trading.domain.market.model.MarketRegime;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Chan Strategy Auto-Optimizer
 *
 * Automatically tunes Chan parameters based on shadow/paper trading performance.
 * Uses evolutionary algorithm with the following tunable parameters:
 *
 * 1. FengxiangThreshold (0.5-0.9): Determines fenxing (turning point) sensitivity
 * 2. ZhongshuMinKlines (0.0005-0.005): Min K-lines for zhongshu (center) formation
 * 3. MinConfidence (0.4-0.7): Minimum signal confidence threshold
 * 4. MinWinRate (0.35-0.55): Minimum historical win rate to accept signals
 *
 * Evolution Strategy:
 * - Maintain population of parameter sets (genetic algorithm)
 * - Score each set by Sharpe-like ratio: winRate / drawdown
 * - Mutate best performers, cull worst
 * - Adapt every N trades
 */
public class ChanAutoOptimizer {

    private static final Logger log = LoggerFactory.getLogger(ChanAutoOptimizer.class);

    // Tunable parameter ranges
    public static final double MIN_FX_THRESHOLD = 0.5;
    public static final double MAX_FX_THRESHOLD = 0.9;
    public static final double MIN_ZHONG_THRESHOLD = 0.0005;
    public static final double MAX_ZHONG_THRESHOLD = 0.005;
    public static final double MIN_CONFIDENCE = 0.4;
    public static final double MAX_CONFIDENCE = 0.7;
    public static final double MIN_WINRATE = 0.35;
    public static final double MAX_WINRATE = 0.55;

    // Evolution settings
    private static final int POPULATION_SIZE = 8;
    private static final int TRADES_PER_EVAL = 20;
    private static final double MUTATION_RATE = 0.2;
    private static final double CROSSOVER_RATE = 0.3;

    // State
    private final List<ParameterSet> population;
    private final Map<ParameterSet, TradeHistory> tradeHistories;
    private final AtomicInteger currentGeneration;
    private final AtomicLong totalTrades;
    private final AtomicReference<ParameterSet> bestSet;

    // Current active parameters
    private final AtomicReference<Double> currentFxThreshold = new AtomicReference<>(0.7);
    private final AtomicReference<Double> currentZhongThreshold = new AtomicReference<>(0.001);
    private final AtomicReference<Double> currentMinConfidence = new AtomicReference<>(0.5);
    private final AtomicReference<Double> currentMinWinRate = new AtomicReference<>(0.45);

    // Reference to components being tuned
    private ChanKLineProcessor processor;
    private ChanSignalValidator validator;
    private ChanFeatureToggle toggle;

    public ChanAutoOptimizer() {
        this.population = Collections.synchronizedList(new ArrayList<>());
        this.tradeHistories = new ConcurrentHashMap<>();
        this.currentGeneration = new AtomicInteger(0);
        this.totalTrades = new AtomicLong(0);
        this.bestSet = new AtomicReference<>();
        initializePopulation();
    }

    /**
     * Initialize with reference to components
     */
    public void setComponents(ChanKLineProcessor processor, ChanSignalValidator validator, ChanFeatureToggle toggle) {
        this.processor = processor;
        this.validator = validator;
        this.toggle = toggle;
    }

    /**
     * Initialize genetic algorithm population with diverse parameter sets
     */
    private void initializePopulation() {
        // Seed with default and variations
        population.add(new ParameterSet(0.7, 0.001, 0.5, 0.45)); // Default

        // Diverse exploration
        population.add(new ParameterSet(0.6, 0.001, 0.45, 0.40));
        population.add(new ParameterSet(0.8, 0.001, 0.55, 0.50));
        population.add(new ParameterSet(0.65, 0.0008, 0.48, 0.42));
        population.add(new ParameterSet(0.75, 0.0015, 0.52, 0.48));
        population.add(new ParameterSet(0.55, 0.0006, 0.42, 0.38));
        population.add(new ParameterSet(0.85, 0.002, 0.60, 0.52));
        population.add(new ParameterSet(0.70, 0.0005, 0.50, 0.44));

        for (ParameterSet ps : population) {
            tradeHistories.put(ps, new TradeHistory());
        }

        bestSet.set(population.get(0));
        applyParameters(population.get(0));
    }

    /**
     * Record a trade outcome for the current parameter set
     */
    public void recordTrade(TradeOutcome outcome) {
        ParameterSet current = bestSet.get();
        TradeHistory history = tradeHistories.get(current);
        if (history != null) {
            history.addTrade(outcome);
            totalTrades.incrementAndGet();

            // Check if we should evolve
            if (history.size() >= TRADES_PER_EVAL) {
                evaluateAndEvolve();
            }
        }
    }

    /**
     * Evaluate performance and evolve population
     */
    private synchronized void evaluateAndEvolve() {
        if (population.isEmpty()) return;

        // Score all parameter sets
        for (ParameterSet ps : population) {
            TradeHistory history = tradeHistories.get(ps);
            if (history != null && history.size() >= 5) {
                ps.score = calculateScore(history);
            }
        }

        // Sort by score
        population.sort((a, b) -> Double.compare(b.score, a.score));

        ParameterSet best = population.get(0);
        bestSet.set(best);
        applyParameters(best);

        log.info("[AutoOptimizer] Gen {} | Best score: {} | params: fx={}, zh={}, conf={}, win={}",
            currentGeneration.get(), String.format("%.3f", best.score),
            String.format("%.3f", best.fxThreshold), String.format("%.4f", best.zhongThreshold),
            String.format("%.2f", best.minConfidence), String.format("%.2f", best.minWinRate));

        // Create next generation
        if (shouldEvolve()) {
            evolve();
        }

        // Clear histories for next evaluation period
        for (TradeHistory h : tradeHistories.values()) {
            h.clear();
        }
    }

    /**
     * Calculate fitness score: Sharpe-like ratio using win rate and consistency
     */
    private double calculateScore(TradeHistory history) {
        if (history.size() < 3) return 0.0;

        double winRate = history.getWinRate();
        double avgReturn = history.getAverageReturn();
        double stdDev = history.getStdDevReturn();

        // Sharpe-like ratio: avgReturn / (stdDev + epsilon)
        double sharpe = stdDev > 0 ? avgReturn / stdDev : avgReturn * 2;

        // Combine win rate and sharpe
        // Win rate component (0.5-0.7 weight)
        double winRateScore = (winRate - 0.3) / 0.4; // Normalize to 0-1 range roughly

        // Consistency bonus (lower variance = better)
        double consistencyBonus = 1.0 / (1.0 + stdDev);

        return 0.5 * winRateScore + 0.3 * sharpe + 0.2 * consistencyBonus;
    }

    /**
     * Determine if we should continue evolving
     */
    private boolean shouldEvolve() {
        return totalTrades.get() < 1000; // Evolve for first 1000 trades
    }

    /**
     * Create next generation through crossover and mutation
     */
    private void evolve() {
        List<ParameterSet> newGeneration = new ArrayList<>();

        // Elitism: keep top 2
        newGeneration.add(population.get(0).clone());
        newGeneration.add(population.get(1).clone());

        // Fill rest with crossover and mutation
        while (newGeneration.size() < POPULATION_SIZE) {
            ParameterSet child;

            if (Math.random() < CROSSOVER_RATE && population.size() >= 2) {
                // Crossover
                ParameterSet parent1 = tournamentSelect();
                ParameterSet parent2 = tournamentSelect();
                child = crossover(parent1, parent2);
            } else {
                // Mutation from random parent
                child = tournamentSelect().clone();
            }

            // Apply mutation
            if (Math.random() < MUTATION_RATE) {
                mutate(child);
            }

            // Ensure valid bounds
            child.clamp();

            newGeneration.add(child);
        }

        population.clear();
        population.addAll(newGeneration);

        // Reset trade histories for new population
        tradeHistories.clear();
        for (ParameterSet ps : population) {
            tradeHistories.put(ps, new TradeHistory());
        }

        currentGeneration.incrementAndGet();
    }

    /**
     * Tournament selection
     */
    private ParameterSet tournamentSelect() {
        Random rand = new Random();
        ParameterSet best = null;
        for (int i = 0; i < 3; i++) {
            ParameterSet candidate = population.get(rand.nextInt(population.size()));
            if (best == null || candidate.score > best.score) {
                best = candidate;
            }
        }
        return best;
    }

    /**
     * Crossover two parameter sets
     */
    private ParameterSet crossover(ParameterSet p1, ParameterSet p2) {
        ParameterSet child = new ParameterSet();
        Random rand = new Random();

        child.fxThreshold = rand.nextBoolean() ? p1.fxThreshold : p2.fxThreshold;
        child.zhongThreshold = rand.nextBoolean() ? p1.zhongThreshold : p2.zhongThreshold;
        child.minConfidence = rand.nextBoolean() ? p1.minConfidence : p2.minConfidence;
        child.minWinRate = rand.nextBoolean() ? p1.minWinRate : p2.minWinRate;

        return child;
    }

    /**
     * Mutate a parameter set
     */
    private void mutate(ParameterSet ps) {
        Random rand = new Random();
        double mutationAmount = 0.1; // 10% mutation

        if (rand.nextDouble() < 0.3) {
            ps.fxThreshold *= (1 + (rand.nextDouble() - 0.5) * mutationAmount);
        }
        if (rand.nextDouble() < 0.3) {
            ps.zhongThreshold *= (1 + (rand.nextDouble() - 0.5) * mutationAmount);
        }
        if (rand.nextDouble() < 0.3) {
            ps.minConfidence *= (1 + (rand.nextDouble() - 0.5) * mutationAmount);
        }
        if (rand.nextDouble() < 0.3) {
            ps.minWinRate *= (1 + (rand.nextDouble() - 0.5) * mutationAmount);
        }
    }

    /**
     * Apply parameter set to actual components
     */
    private void applyParameters(ParameterSet ps) {
        currentFxThreshold.set(ps.fxThreshold);
        currentZhongThreshold.set(ps.zhongThreshold);
        currentMinConfidence.set(ps.minConfidence);
        currentMinWinRate.set(ps.minWinRate);

        if (processor != null) {
            // Note: ChanKLineProcessor doesn't have setter methods for thresholds
            // In a real implementation, you'd recreate the processor or add setters
            // For now, we track the values and log them for manual tuning
            log.debug("[AutoOptimizer] Target params: fx={}, zh={}",
                String.format("%.3f", ps.fxThreshold), String.format("%.4f", ps.zhongThreshold));
        }

        if (validator != null) {
            validator.setMinWinRate(ps.minWinRate);
        }
    }

    // ========== Getters ==========

    public double getCurrentFxThreshold() { return currentFxThreshold.get(); }
    public double getCurrentZhongThreshold() { return currentZhongThreshold.get(); }
    public double getCurrentMinConfidence() { return currentMinConfidence.get(); }
    public double getCurrentMinWinRate() { return currentMinWinRate.get(); }
    public ParameterSet getBestParameters() { return bestSet.get(); }
    public int getGeneration() { return currentGeneration.get(); }
    public long getTotalTrades() { return totalTrades.get(); }

    public String getStatusString() {
        ParameterSet best = bestSet.get();
        if (best == null) return "Not initialized";
        return String.format("Gen=%d, Trades=%d, BestScore=%.3f, fx=%.3f, zh=%.4f, conf=%.2f, win=%.2f",
            currentGeneration.get(), totalTrades.get(), best.score,
            best.fxThreshold, best.zhongThreshold,
            best.minConfidence, best.minWinRate);
    }

    // ========== Inner Classes ==========

    public static class ParameterSet {
        public double fxThreshold;
        public double zhongThreshold;
        public double minConfidence;
        public double minWinRate;
        public double score = 0.0;

        public ParameterSet() {}

        public ParameterSet(double fx, double zh, double conf, double win) {
            this.fxThreshold = fx;
            this.zhongThreshold = zh;
            this.minConfidence = conf;
            this.minWinRate = win;
        }

        public void clamp() {
            fxThreshold = Math.max(MIN_FX_THRESHOLD, Math.min(MAX_FX_THRESHOLD, fxThreshold));
            zhongThreshold = Math.max(MIN_ZHONG_THRESHOLD, Math.min(MAX_ZHONG_THRESHOLD, zhongThreshold));
            minConfidence = Math.max(MIN_CONFIDENCE, Math.min(MAX_CONFIDENCE, minConfidence));
            minWinRate = Math.max(MIN_WINRATE, Math.min(MAX_WINRATE, minWinRate));
        }

        public ParameterSet clone() {
            ParameterSet copy = new ParameterSet();
            copy.fxThreshold = this.fxThreshold;
            copy.zhongThreshold = this.zhongThreshold;
            copy.minConfidence = this.minConfidence;
            copy.minWinRate = this.minWinRate;
            copy.score = this.score;
            return copy;
        }

        @Override
        public String toString() {
            return String.format("ParamSet(fx=%.3f, zh=%.4f, conf=%.2f, win=%.2f, score=%.3f)",
                fxThreshold, zhongThreshold, minConfidence, minWinRate, score);
        }
    }

    public static class TradeOutcome {
        public final boolean isWin;
        public final double pnl;
        public final double returnPct;
        public final MarketRegime regime;
        public final long timestamp;

        public TradeOutcome(boolean isWin, double pnl, double returnPct, MarketRegime regime) {
            this.isWin = isWin;
            this.pnl = pnl;
            this.returnPct = returnPct;
            this.regime = regime;
            this.timestamp = System.currentTimeMillis();
        }
    }

    public static class TradeHistory {
        private final List<TradeOutcome> trades = Collections.synchronizedList(new ArrayList<>());

        public void addTrade(TradeOutcome trade) {
            trades.add(trade);
        }

        public int size() { return trades.size(); }
        public void clear() { trades.clear(); }

        public double getWinRate() {
            if (trades.isEmpty()) return 0.0;
            long wins = trades.stream().filter(t -> t.isWin).count();
            return (double) wins / trades.size();
        }

        public double getAverageReturn() {
            if (trades.isEmpty()) return 0.0;
            return trades.stream().mapToDouble(t -> t.returnPct).average().orElse(0.0);
        }

        public double getStdDevReturn() {
            if (trades.size() < 2) return 0.0;
            double mean = getAverageReturn();
            double variance = trades.stream()
                .mapToDouble(t -> Math.pow(t.returnPct - mean, 2))
                .average().orElse(0.0);
            return Math.sqrt(variance);
        }
    }
}
