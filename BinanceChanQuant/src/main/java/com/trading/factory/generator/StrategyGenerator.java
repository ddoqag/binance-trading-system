package com.trading.factory.generator;

import com.trading.factory.backtest.BacktestEngine;
import com.trading.factory.model.BacktestResult;
import com.trading.factory.model.StrategyGenome;
import com.trading.factory.template.StrategyTemplate;
import com.trading.factory.validator.StrategyValidator;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.*;
import java.util.function.Consumer;

/**
 * Strategy Generator - Batch generation + parallel backtesting
 */
public class StrategyGenerator {

    private final StrategyTemplate template;
    private final BacktestEngine backtestEngine;
    private final StrategyValidator validator;
    private final int parallelism;

    public StrategyGenerator(StrategyTemplate template,
                            BacktestEngine backtestEngine,
                            StrategyValidator validator) {
        this(template, backtestEngine, validator, 4);
    }

    public StrategyGenerator(StrategyTemplate template,
                            BacktestEngine backtestEngine,
                            StrategyValidator validator,
                            int parallelism) {
        this.template = template;
        this.backtestEngine = backtestEngine;
        this.validator = validator;
        this.parallelism = parallelism;
    }

    /**
     * Generate and backtest N strategies
     */
    public List<BacktestResult> generateAndBacktest(
            int count,
            Consumer<GenerationProgress> callback) {

        ExecutorService pool = Executors.newFixedThreadPool(parallelism);
        List<Future<BacktestResult>> futures = new ArrayList<>();

        // Generate genomes
        List<StrategyGenome> genomes = new ArrayList<>();
        for (int i = 0; i < count; i++) {
            StrategyGenome genome = template.generateRandom();
            genomes.add(genome);
        }

        // Submit backtest tasks
        final int total = genomes.size();
        for (int i = 0; i < genomes.size(); i++) {
            final int idx = i;
            final StrategyGenome genome = genomes.get(i);

            futures.add(pool.submit(() -> {
                BacktestResult result = backtestEngine.backtest(genome);

                // Report progress
                if (callback != null) {
                    int progress = (idx * 100) / total;
                    callback.accept(new GenerationProgress(idx + 1, total, progress, genome.getId()));
                }

                return result;
            }));
        }

        // Collect results
        List<BacktestResult> results = new ArrayList<>();
        for (Future<BacktestResult> future : futures) {
            try {
                BacktestResult result = future.get(30, TimeUnit.SECONDS);
                if (result != null && validator.validate(result) == null) {
                    results.add(result);
                }
            } catch (Exception e) {
                // Skip failed backtests
            }
        }

        pool.shutdown();

        return results;
    }

    /**
     * Simple version without callback
     */
    public List<BacktestResult> generateAndBacktest(int count) {
        return generateAndBacktest(count, null);
    }

    /**
     * Generate single genome without backtest
     */
    public StrategyGenome generateRandom() {
        return template.generateRandom();
    }

    /**
     * Progress callback data
     */
    public static class GenerationProgress {
        private final int current;
        private final int total;
        private final int percentComplete;
        private final String genomeId;

        public GenerationProgress(int current, int total, int percentComplete, String genomeId) {
            this.current = current;
            this.total = total;
            this.percentComplete = percentComplete;
            this.genomeId = genomeId;
        }

        public int current() { return current; }
        public int total() { return total; }
        public int percentComplete() { return percentComplete; }
        public String genomeId() { return genomeId; }

        public String toString() {
            return String.format("Progress: %d/%d (%d%%) - %s",
                    current, total, percentComplete, genomeId);
        }
    }

    /**
     * Filter results by validator
     */
    public List<BacktestResult> filterValid(List<BacktestResult> results) {
        return validator.filterValid(results);
    }

    /**
     * Rank by composite score
     */
    public List<BacktestResult> rank(List<BacktestResult> results) {
        return results.stream()
                .sorted((a, b) -> {
                    double scoreA = a.getTestMetrics() != null ?
                            a.getTestMetrics().getCompositeScore() : 0;
                    double scoreB = b.getTestMetrics() != null ?
                            b.getTestMetrics().getCompositeScore() : 0;
                    return Double.compare(scoreB, scoreA);
                })
                .toList();
    }
}