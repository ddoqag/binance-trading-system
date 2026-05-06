package com.trading.factory.validator;

import com.trading.factory.model.BacktestResult;
import com.trading.factory.model.StrategyMetrics;

import java.util.List;

/**
 * Strategy Validator - Hard filters + overfitting defense
 */
public class StrategyValidator {

    // Hard filters
    private static final int MIN_TRADES = 30;
    private static final double MAX_DRAWDOWN = 0.20;      // 20%
    private static final double MIN_WIN_RATE = 0.40;     // 40%
    private static final double MIN_SHARPE = 0.5;

    // Overfitting defense
    private static final double OVERFIT_THRESHOLD = 0.7;  // test/train >= 0.7
    private static final double MIN_TEST_SHARPE = 0.3;

    // Stability (walk-forward)
    private static final double STABILITY_RATIO = 0.3;   // std/mean <= 0.3

    private final boolean strictMode;

    public StrategyValidator(boolean strictMode) {
        this.strictMode = strictMode;
    }

    public static StrategyValidator defaultValidator() {
        return new StrategyValidator(false);
    }

    public static StrategyValidator strictValidator() {
        return new StrategyValidator(true);
    }

    /**
     * Main validation - returns reason if rejected, null if passed
     */
    public String validate(BacktestResult result) {
        if (result == null || result.getGenome() == null) {
            return "Null result or genome";
        }

        // Hard filters
        if (!passesHardFilters(result)) {
            StrategyMetrics m = result.getTestMetrics() != null ?
                    result.getTestMetrics() : result.getTrainMetrics();
            if (m != null) {
                if (m.getTradesCount() < MIN_TRADES) return "Insufficient trades: " + m.getTradesCount();
                if (m.getMaxDrawdown() > MAX_DRAWDOWN) return "Max drawdown too high: " + m.getMaxDrawdown();
                if (m.getWinRate() < MIN_WIN_RATE) return "Win rate too low: " + m.getWinRate();
            }
            return "Failed hard filters";
        }

        // Overfit check
        if (!passesOverfitCheck(result)) {
            return "Overfitted: overfitRatio=" + String.format("%.2f", result.getOverfitRatio());
        }

        // Test Sharpe check
        if (strictMode && result.getTestMetrics() != null) {
            if (result.getTestMetrics().getSharpe() < MIN_TEST_SHARPE) {
                return "Test Sharpe too low: " + result.getTestMetrics().getSharpe();
            }
        }

        return null;  // Passed
    }

    public boolean passesHardFilters(BacktestResult result) {
        StrategyMetrics m = result.getTestMetrics() != null ?
                result.getTestMetrics() : result.getTrainMetrics();

        if (m == null) return false;

        return m.getTradesCount() >= MIN_TRADES
            && m.getMaxDrawdown() <= MAX_DRAWDOWN
            && m.getWinRate() >= MIN_WIN_RATE;
    }

    public boolean passesOverfitCheck(BacktestResult result) {
        // Must have reasonable overfit ratio
        if (result.getOverfitRatio() < OVERFIT_THRESHOLD) {
            return false;
        }

        // Test Sharpe should be positive
        if (result.getTestMetrics() != null && result.getTestMetrics().getSharpe() <= 0) {
            return false;
        }

        return true;
    }

    /**
     * Validate walk-forward stability
     */
    public boolean passesStability(List<BacktestResult> wfResults) {
        if (wfResults == null || wfResults.size() < 3) {
            return true;  // Not enough data for stability check
        }

        // Calculate coefficient of variation for test Sharpe
        double[] sharpes = wfResults.stream()
                .filter(r -> r.getTestMetrics() != null)
                .mapToDouble(r -> r.getTestMetrics().getSharpe())
                .toArray();

        if (sharpes.length < 3) return true;

        double mean = java.util.Arrays.stream(sharpes).average().orElse(0);
        if (mean == 0) return false;

        double std = Math.sqrt(java.util.Arrays.stream(sharpes)
                .map(s -> Math.pow(s - mean, 2))
                .sum() / sharpes.length);

        double cv = std / Math.abs(mean);
        return cv <= STABILITY_RATIO;
    }

    /**
     * Filter list of results, keeping only valid ones
     */
    public List<BacktestResult> filterValid(List<BacktestResult> results) {
        return results.stream()
                .filter(r -> validate(r) == null)
                .toList();
    }

    // Getters for thresholds (useful for testing)
    public static int getMinTrades() { return MIN_TRADES; }
    public static double getMaxDrawdown() { return MAX_DRAWDOWN; }
    public static double getMinWinRate() { return MIN_WIN_RATE; }
    public static double getOverfitThreshold() { return OVERFIT_THRESHOLD; }
}