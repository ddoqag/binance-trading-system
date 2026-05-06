package com.trading.factory;

import com.trading.adapter.pool.AlphaPool;
import com.trading.factory.backtest.BacktestEngine;
import com.trading.factory.backtest.HistoricalDataProvider;
import com.trading.factory.generator.StrategyGenerator;
import com.trading.factory.model.BacktestResult;
import com.trading.factory.model.StrategyGenome;
import com.trading.factory.pool.StrategyPool;
import com.trading.factory.template.StrategyTemplate;
import com.trading.factory.validator.StrategyValidator;

import java.util.List;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;

/**
 * Strategy Factory - Main entry point for strategy generation pipeline
 *
 * Coordinates: Template -> Generator -> Backtest -> Validator -> Pool -> AlphaPool
 */
public class StrategyFactory {

    private final StrategyTemplate template;
    private final BacktestEngine backtestEngine;
    private final StrategyValidator validator;
    private final StrategyPool pool;
    private final AlphaPool alphaPool;

    private ScheduledExecutorService scheduler;
    private boolean isRunning = false;

    public StrategyFactory(StrategyTemplate template,
                          HistoricalDataProvider dataProvider,
                          AlphaPool alphaPool) {
        this.template = template;
        this.backtestEngine = new BacktestEngine(dataProvider);
        this.validator = StrategyValidator.defaultValidator();
        this.pool = new StrategyPool(10, alphaPool);
        this.alphaPool = alphaPool;
    }

    public StrategyFactory(StrategyTemplate template,
                           HistoricalDataProvider dataProvider) {
        this(template, dataProvider, null);
    }

    /**
     * Generate N strategies through full pipeline
     */
    public GenerationResult generateStrategies(int count, Consumer<GenerationEvent> callback) {
        StrategyGenerator generator = new StrategyGenerator(
                template, backtestEngine, validator, 4
        );

        // Generate and backtest
        List<BacktestResult> results = generator.generateAndBacktest(count, progress -> {
            if (callback != null) {
                callback.accept(new GenerationEvent(GenesisEventType.PROGRESS, progress));
            }
        });

        // Rank valid results
        List<BacktestResult> ranked = generator.rank(results);

        // Add to pool
        int added = 0;
        for (BacktestResult result : ranked) {
            if (pool.addStrategy(result)) {
                added++;
            }
        }

        // Update AlphaPool
        if (alphaPool != null) {
            pool.registerToAlphaPool();
        }

        return new GenerationResult(
                results.size(),
                generator.filterValid(results).size(),
                added,
                pool.getStats()
        );
    }

    /**
     * Simple generation without callback
     */
    public GenerationResult generateStrategies(int count) {
        return generateStrategies(count, null);
    }

    /**
     * Start continuous evolution (periodic regeneration)
     */
    public void startContinuousEvolution(long intervalMinutes) {
        if (isRunning) return;

        scheduler = Executors.newScheduledThreadPool(1);
        isRunning = true;

        scheduler.scheduleAtFixedRate(() -> {
            try {
                // Re-generate 20% of pool
                int regenerateCount = Math.max(5, pool.getStats().size() / 5);
                generateStrategies(regenerateCount);
            } catch (Exception e) {
                System.err.println("[StrategyFactory] Evolution error: " + e.getMessage());
            }
        }, intervalMinutes, intervalMinutes, TimeUnit.MINUTES);

        System.out.println("[StrategyFactory] Continuous evolution started (every " + intervalMinutes + " min)");
    }

    /**
     * Stop continuous evolution
     */
    public void stopContinuousEvolution() {
        if (scheduler != null) {
            scheduler.shutdown();
            isRunning = false;
            System.out.println("[StrategyFactory] Continuous evolution stopped");
        }
    }

    /**
     * Get current pool
     */
    public StrategyPool getPool() {
        return pool;
    }

    /**
     * Get top strategies
     */
    public List<StrategyGenome> getTopStrategies(int n) {
        return pool.getTopStrategies(n);
    }

    /**
     * Get pool statistics
     */
    public StrategyPool.PoolStats getStats() {
        return pool.getStats();
    }

    /**
     * Generation event types
     */
    public enum GenesisEventType {
        STARTED,
        PROGRESS,
        COMPLETED,
        ERROR
    }

    /**
     * Generation event
     */
    public static class GenerationEvent {
        private final GenesisEventType type;
        private final Object data;

        public GenerationEvent(GenesisEventType type, Object data) {
            this.type = type;
            this.data = data;
        }

        public GenesisEventType type() { return type; }
        public Object data() { return data; }

        public static GenerationEvent started() {
            return new GenerationEvent(GenesisEventType.STARTED, null);
        }

        public static GenerationEvent completed(GenerationResult result) {
            return new GenerationEvent(GenesisEventType.COMPLETED, result);
        }

        public static GenerationEvent error(String message) {
            return new GenerationEvent(GenesisEventType.ERROR, message);
        }
    }

    /**
     * Generation result summary
     */
    public static class GenerationResult {
        private final int totalGenerated;
        private final int passedValidation;
        private final int addedToPool;
        private final StrategyPool.PoolStats poolStats;

        public GenerationResult(int totalGenerated, int passedValidation, int addedToPool, StrategyPool.PoolStats poolStats) {
            this.totalGenerated = totalGenerated;
            this.passedValidation = passedValidation;
            this.addedToPool = addedToPool;
            this.poolStats = poolStats;
        }

        public int totalGenerated() { return totalGenerated; }
        public int passedValidation() { return passedValidation; }
        public int addedToPool() { return addedToPool; }
        public StrategyPool.PoolStats poolStats() { return poolStats; }

        public String toString() {
            return String.format("GenResult{total=%d, validated=%d, inPool=%d, poolSize=%d}",
                    totalGenerated, passedValidation, addedToPool, poolStats.size());
        }
    }

    /**
     * Static factory methods for common configurations
     */
    public static StrategyFactory meanReversionFactory(HistoricalDataProvider data) {
        return new StrategyFactory(StrategyTemplate.meanReversion(), data);
    }

    public static StrategyFactory trendFollowingFactory(HistoricalDataProvider data) {
        return new StrategyFactory(StrategyTemplate.trendFollowing(), data);
    }

    public static StrategyFactory volatilityFactory(HistoricalDataProvider data) {
        return new StrategyFactory(StrategyTemplate.volatility(), data);
    }

    public static StrategyFactory allTypesFactory(HistoricalDataProvider data, AlphaPool pool) {
        return new StrategyFactory(StrategyTemplate.meanReversion(), data, pool);
    }
}