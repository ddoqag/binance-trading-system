package com.trading.adapter.shadow;

/**
 * 适应度结果 - 评估策略Performance的综合评分
 *
 * 评分公式:
 * score = 0.4 * Sharpe + 0.3 * (1 - MaxDrawdown) + 0.2 * WinRate + 0.1 * ProfitFactor
 */
public class FitnessResult {
    private final double score;
    private final double sharpe;
    private final double maxDrawdown;
    private final double winRate;
    private final double profitFactor;
    private final double totalReturn;

    public FitnessResult(double score, double sharpe, double maxDrawdown,
                         double winRate, double profitFactor, double totalReturn) {
        this.score = score;
        this.sharpe = sharpe;
        this.maxDrawdown = maxDrawdown;
        this.winRate = winRate;
        this.profitFactor = profitFactor;
        this.totalReturn = totalReturn;
    }

    public static FitnessResult zero() {
        return new FitnessResult(0, 0, 0, 0, 0, 0);
    }

    public double getScore() { return score; }
    public double getSharpe() { return sharpe; }
    public double getMaxDrawdown() { return maxDrawdown; }
    public double getWinRate() { return winRate; }
    public double getProfitFactor() { return profitFactor; }
    public double getTotalReturn() { return totalReturn; }

    public boolean isBetterThan(FitnessResult other) {
        return this.score > other.score;
    }

    @Override
    public String toString() {
        return String.format(
            "Fitness(score=%.3f, sharpe=%.2f, maxDD=%.2f%%, winRate=%.1f%%, PF=%.2f, return=%.2f)",
            score, sharpe, maxDrawdown, winRate * 100, profitFactor, totalReturn
        );
    }
}
