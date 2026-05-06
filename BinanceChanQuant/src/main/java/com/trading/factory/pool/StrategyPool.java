package com.trading.factory.pool;

import com.trading.adapter.pool.AlphaPool;
import com.trading.factory.model.BacktestResult;
import com.trading.factory.model.StrategyGenome;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Collectors;

/**
 * Strategy Pool - Top N candidates with continuous update and elimination
 */
public class StrategyPool {

    private static final int DEFAULT_POOL_SIZE = 10;
    private static final double EVICTION_THRESHOLD = 0.5;  // 50% worse than best

    private final int maxSize;
    private final Map<String, PooledStrategy> strategies;
    private final StrategyRanking ranking;
    private final AlphaPool alphaPool;

    public StrategyPool() {
        this(DEFAULT_POOL_SIZE, null);
    }

    public StrategyPool(int maxSize) {
        this(maxSize, null);
    }

    public StrategyPool(int maxSize, AlphaPool alphaPool) {
        this.maxSize = maxSize;
        this.strategies = new ConcurrentHashMap<>();
        this.ranking = new StrategyRanking();
        this.alphaPool = alphaPool;
    }

    /**
     * Add strategy after validation
     */
    public boolean addStrategy(BacktestResult result) {
        if (result == null || result.getGenome() == null) return false;

        StrategyGenome genome = result.getGenome();
        double score = result.getTestMetrics() != null ?
                result.getTestMetrics().getCompositeScore() :
                result.getTrainMetrics().getCompositeScore();

        PooledStrategy pooled = new PooledStrategy(genome, score, System.currentTimeMillis());

        strategies.put(genome.getId(), pooled);

        // Trim if over size
        trimToSize();

        // Update AlphaPool if connected
        if (alphaPool != null) {
            registerToAlphaPool();
        }

        return true;
    }

    /**
     * Get top N strategies
     */
    public List<StrategyGenome> getTopStrategies(int n) {
        return strategies.values().stream()
                .sorted((a, b) -> Double.compare(b.score, a.score))
                .limit(n)
                .map(ps -> ps.genome)
                .collect(Collectors.toList());
    }

    /**
     * Get all strategies
     */
    public List<StrategyGenome> getAllStrategies() {
        return getTopStrategies(maxSize);
    }

    /**
     * Eliminate poor performers
     */
    public void eliminatePoorPerformers() {
        if (strategies.isEmpty()) return;

        double bestScore = strategies.values().stream()
                .mapToDouble(ps -> ps.score)
                .max()
                .orElse(0);

        strategies.entrySet().removeIf(entry -> {
            PooledStrategy ps = entry.getValue();
            return ps.score < bestScore * EVICTION_THRESHOLD;
        });
    }

    /**
     * Update pool with new results (continuous evolution)
     */
    public void updatePool(List<BacktestResult> newResults) {
        for (BacktestResult result : newResults) {
            addStrategy(result);
        }
        eliminatePoorPerformers();
    }

    /**
     * Register strategies to AlphaPool
     */
    public void registerToAlphaPool() {
        if (alphaPool == null) return;

        for (StrategyGenome genome : getTopStrategies(maxSize)) {
            // Create expert wrapper for each genome
            // This would integrate with existing AlphaExpert mechanism
        }
    }

    /**
     * Get pool statistics
     */
    public PoolStats getStats() {
        if (strategies.isEmpty()) {
            return new PoolStats(0, 0, 0, Collections.emptyList());
        }

        double avgScore = strategies.values().stream()
                .mapToDouble(ps -> ps.score)
                .average()
                .orElse(0);

        double bestScore = strategies.values().stream()
                .mapToDouble(ps -> ps.score)
                .max()
                .orElse(0);

        return new PoolStats(
                strategies.size(),
                avgScore,
                bestScore,
                getTopStrategies(3).stream()
                        .map(g -> g.getId())
                        .collect(Collectors.toList())
        );
    }

    private void trimToSize() {
        if (strategies.size() <= maxSize) return;

        List<Map.Entry<String, PooledStrategy>> sorted = strategies.entrySet().stream()
                .sorted((a, b) -> Double.compare(b.getValue().score, a.getValue().score))
                .toList();

        strategies.clear();
        for (int i = 0; i < Math.min(sorted.size(), maxSize); i++) {
            strategies.put(sorted.get(i).getKey(), sorted.get(i).getValue());
        }
    }

    /**
     * Pooled strategy wrapper
     */
    private static class PooledStrategy {
        final StrategyGenome genome;
        final double score;
        final long addedAt;

        PooledStrategy(StrategyGenome genome, double score, long addedAt) {
            this.genome = genome;
            this.score = score;
            this.addedAt = addedAt;
        }
    }

    /**
     * Pool statistics
     */
    public static class PoolStats {
        private final int size;
        private final double avgScore;
        private final double bestScore;
        private final List<String> topIds;

        public PoolStats(int size, double avgScore, double bestScore, List<String> topIds) {
            this.size = size;
            this.avgScore = avgScore;
            this.bestScore = bestScore;
            this.topIds = topIds;
        }

        public int size() { return size; }
        public double avgScore() { return avgScore; }
        public double bestScore() { return bestScore; }
        public List<String> topIds() { return topIds; }
    }

    /**
     * Simple ranking helper
     */
    private static class StrategyRanking {
        // Future: implement more sophisticated ranking
    }
}