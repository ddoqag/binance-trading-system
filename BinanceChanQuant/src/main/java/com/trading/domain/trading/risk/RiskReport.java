package com.trading.domain.trading.risk;

import java.time.Instant;

/**
 * RiskReport - 完整风险报告
 * 用于监控面板和运维告警
 */
public class RiskReport {

    private final Instant timestamp;
    private final RiskState riskState;
    private final PositionMetrics positionMetrics;
    private final ExposureMetrics exposureMetrics;
    private final DrawdownMetrics drawdownMetrics;
    private final StreakMetrics streakMetrics;
    private final FrequencyMetrics frequencyMetrics;
    private final CheckStats checkStats;

    public RiskReport(Instant timestamp, RiskState riskState,
                      PositionMetrics positionMetrics,
                      ExposureMetrics exposureMetrics,
                      DrawdownMetrics drawdownMetrics,
                      StreakMetrics streakMetrics,
                      FrequencyMetrics frequencyMetrics,
                      CheckStats checkStats) {
        this.timestamp = timestamp;
        this.riskState = riskState;
        this.positionMetrics = positionMetrics;
        this.exposureMetrics = exposureMetrics;
        this.drawdownMetrics = drawdownMetrics;
        this.streakMetrics = streakMetrics;
        this.frequencyMetrics = frequencyMetrics;
        this.checkStats = checkStats;
    }

    public Instant getTimestamp() { return timestamp; }
    public RiskState getRiskState() { return riskState; }
    public PositionMetrics getPositionMetrics() { return positionMetrics; }
    public ExposureMetrics getExposureMetrics() { return exposureMetrics; }
    public DrawdownMetrics getDrawdownMetrics() { return drawdownMetrics; }
    public StreakMetrics getStreakMetrics() { return streakMetrics; }
    public FrequencyMetrics getFrequencyMetrics() { return frequencyMetrics; }
    public CheckStats getCheckStats() { return checkStats; }

    public String toSummaryString() {
        return String.format(
            "RiskReport[state=%s] pos=%.4f(%.2f%%) dd=%.2f%% loss=%d freq=%d/%d rejectRate=%.2f%%",
            riskState,
            positionMetrics.currentPosition,
            positionMetrics.positionUtilization * 100,
            drawdownMetrics.currentDrawdown * 100,
            streakMetrics.consecutiveLosses,
            frequencyMetrics.ordersThisMinute,
            frequencyMetrics.maxOrdersPerMinute,
            checkStats.rejectRate * 100
        );
    }

    // ========== 内部类 ==========

    public static class PositionMetrics {
        public double currentPosition;
        public double avgPrice;
        public double unrealizedPnl;
        public double realizedPnl;
        public double exposure;
        public double positionUtilization;

        public PositionMetrics() {}

        public double getCurrentPosition() { return currentPosition; }
        public double getAvgPrice() { return avgPrice; }
        public double getUnrealizedPnl() { return unrealizedPnl; }
        public double getRealizedPnl() { return realizedPnl; }
        public double getExposure() { return exposure; }
        public double getPositionUtilization() { return positionUtilization; }
    }

    public static class ExposureMetrics {
        public double exposureRatio;
        public double leverage;
        public double maxExposure;

        public ExposureMetrics() {}

        public double getExposureRatio() { return exposureRatio; }
        public double getLeverage() { return leverage; }
        public double getMaxExposure() { return maxExposure; }
    }

    public static class DrawdownMetrics {
        public double currentDrawdown;
        public double maxDrawdown;
        public double peakEquity;
        public double currentEquity;

        public DrawdownMetrics() {}

        public double getCurrentDrawdown() { return currentDrawdown; }
        public double getMaxDrawdown() { return maxDrawdown; }
        public double getPeakEquity() { return peakEquity; }
        public double getCurrentEquity() { return currentEquity; }
    }

    public static class StreakMetrics {
        public int consecutiveLosses;
        public int maxConsecutiveLosses;
        public double winRate;
        public int recentTradeCount;

        public StreakMetrics() {}

        public int getConsecutiveLosses() { return consecutiveLosses; }
        public int getMaxConsecutiveLosses() { return maxConsecutiveLosses; }
        public double getWinRate() { return winRate; }
        public int getRecentTradeCount() { return recentTradeCount; }
    }

    public static class FrequencyMetrics {
        public int ordersThisMinute;
        public int maxOrdersPerMinute;
        public int dailyTrades;
        public int dailyRejects;

        public FrequencyMetrics() {}

        public int getOrdersThisMinute() { return ordersThisMinute; }
        public int getMaxOrdersPerMinute() { return maxOrdersPerMinute; }
        public int getDailyTrades() { return dailyTrades; }
        public int getDailyRejects() { return dailyRejects; }
    }

    public static class CheckStats {
        public int totalChecks;
        public int totalRejects;
        public double rejectRate;
        public double blockedPnL;

        public CheckStats() {}

        public int getTotalChecks() { return totalChecks; }
        public int getTotalRejects() { return totalRejects; }
        public double getRejectRate() { return rejectRate; }
        public double getBlockedPnL() { return blockedPnL; }
    }

    // ========== Builder ==========

    public static Builder builder() { return new Builder(); }

    public static class Builder {
        private Instant timestamp;
        private RiskState riskState;
        private PositionMetrics positionMetrics = new PositionMetrics();
        private ExposureMetrics exposureMetrics = new ExposureMetrics();
        private DrawdownMetrics drawdownMetrics = new DrawdownMetrics();
        private StreakMetrics streakMetrics = new StreakMetrics();
        private FrequencyMetrics frequencyMetrics = new FrequencyMetrics();
        private CheckStats checkStats = new CheckStats();

        public Builder timestamp(Instant timestamp) { this.timestamp = timestamp; return this; }
        public Builder riskState(RiskState riskState) { this.riskState = riskState; return this; }
        public Builder positionMetrics(PositionMetrics m) { this.positionMetrics = m; return this; }
        public Builder exposureMetrics(ExposureMetrics m) { this.exposureMetrics = m; return this; }
        public Builder drawdownMetrics(DrawdownMetrics m) { this.drawdownMetrics = m; return this; }
        public Builder streakMetrics(StreakMetrics m) { this.streakMetrics = m; return this; }
        public Builder frequencyMetrics(FrequencyMetrics m) { this.frequencyMetrics = m; return this; }
        public Builder checkStats(CheckStats m) { this.checkStats = m; return this; }

        public RiskReport build() {
            return new RiskReport(timestamp, riskState, positionMetrics,
                exposureMetrics, drawdownMetrics, streakMetrics,
                frequencyMetrics, checkStats);
        }
    }
}
