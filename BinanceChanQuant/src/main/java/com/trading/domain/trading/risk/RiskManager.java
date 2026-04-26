package com.trading.domain.trading.risk;

import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.ExecutionReport;

/**
 * Risk Manager Interface
 * Defines contract for all risk-related operations
 */
public interface RiskManager {

    /**
     * Pre-trade risk check
     */
    RiskCheckResult preTradeCheck(Order order);

    /**
     * Post-trade risk processing
     */
    void onExecution(ExecutionReport report);

    /**
     * Get current position risk
     */
    PositionRisk getPositionRisk();

    /**
     * Get daily risk metrics
     */
    DailyRiskMetrics getDailyRiskMetrics();

    /**
     * Get maximum drawdown
     */
    double getMaxDrawdown();

    /**
     * Get Sharpe ratio
     */
    double getSharpeRatio();

    /**
     * Check if circuit breaker is triggered
     */
    boolean isCircuitBreakerTriggered();

    /**
     * Reset daily counters
     */
    void resetDailyCounters();

    /**
     * Update market data for risk calculations
     */
    void updateMarketData(double price, double volatility, double volume);

    /**
     * Position risk data
     */
    class PositionRisk {
        public double currentPosition;
        public double maxPosition;
        public double positionUtilization;
        public double liquidationPrice;
        public double unrealizedPnl;
    }

    /**
     * Daily risk metrics
     */
    class DailyRiskMetrics {
        public double dailyPnl;
        public double dailyLossLimit;
        public int dailyTrades;
        public int dailyRejects;
        public double winRate;
    }
}
