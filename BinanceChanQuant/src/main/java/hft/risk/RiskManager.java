package hft.risk;

import hft.executor.Position;

/**
 * RiskManager - Risk Management for HFT System
 *
 * Handles:
 * - Position size limits
 * - Daily PnL limits
 * - Drawdown limits
 * - Order rate limits
 * - Kill switch
 */
public class RiskManager {
    private final double maxPosition;
    private final double maxDailyLoss;
    private final int maxOrdersPerMinute;

    private volatile double peakEquity = 0;
    private volatile double dailyPnl = 0;
    private volatile int ordersThisMinute = 0;
    private volatile boolean killSwitch = false;

    private long lastResetTime = System.currentTimeMillis();

    public RiskManager(double maxPosition, double maxDailyLoss, int maxOrdersPerMinute) {
        this.maxPosition = maxPosition;
        this.maxDailyLoss = maxDailyLoss;
        this.maxOrdersPerMinute = maxOrdersPerMinute;
    }

    public static RiskManager defaults() {
        return new RiskManager(10.0, 10000.0, 120);
    }

    /**
     * Check if trading is allowed
     */
    public boolean canTrade(TradeAction action, double size, double currentPosition) {
        if (killSwitch) {
            return false;
        }

        // Check order rate
        resetOrderCountIfNeeded();
        if (ordersThisMinute >= maxOrdersPerMinute) {
            return false;
        }

        // Check position limits
        if (action == TradeAction.BUY || action == TradeAction.COVER) {
            if (currentPosition + size > maxPosition) {
                return false;
            }
        } else if (action == TradeAction.SELL || action == TradeAction.SHORT) {
            if (currentPosition - size < -maxPosition) {
                return false;
            }
        }

        // Check daily loss
        if (dailyPnl < -maxDailyLoss) {
            return false;
        }

        return true;
    }

    /**
     * Record order
     */
    public void recordOrder() {
        resetOrderCountIfNeeded();
        ordersThisMinute++;
    }

    /**
     * Update equity and PnL
     */
    public void updateEquity(double currentEquity) {
        if (peakEquity == 0) {
            peakEquity = currentEquity;
        }

        dailyPnl = currentEquity - peakEquity;

        if (currentEquity > peakEquity) {
            peakEquity = currentEquity;
        }
    }

    /**
     * Record daily PnL
     */
    public void recordDailyPnl(double pnl) {
        this.dailyPnl += pnl;
    }

    /**
     * Activate kill switch
     */
    public void activateKillSwitch() {
        this.killSwitch = true;
        System.out.println("[RISK] KILL SWITCH ACTIVATED");
    }

    /**
     * Check if kill switch is active
     */
    public boolean isKillSwitchActive() {
        return killSwitch;
    }

    /**
     * Reset order count if minute has passed
     */
    private void resetOrderCountIfNeeded() {
        long now = System.currentTimeMillis();
        if (now - lastResetTime > 60_000) {
            ordersThisMinute = 0;
            lastResetTime = now;
        }
    }

    /**
     * Get current risk status
     */
    public RiskStatus getStatus() {
        return new RiskStatus(
            peakEquity,
            dailyPnl,
            ordersThisMinute,
            maxOrdersPerMinute,
            killSwitch
        );
    }

    /**
     * Get max position allowed
     */
    public double getMaxPosition() {
        return maxPosition;
    }

    /**
     * Get max order size
     */
    public double getMaxOrderSize() {
        return maxPosition * 0.1;  // 10% of max position
    }

    public double getPeakEquity() { return peakEquity; }
    public double getDailyPnl() { return dailyPnl; }
    public int getOrdersThisMinute() { return ordersThisMinute; }

    public enum TradeAction { BUY, SELL, SHORT, COVER }

    public static class RiskStatus {
        public final double peakEquity;
        public final double dailyPnl;
        public final int ordersThisMinute;
        public final int maxOrdersPerMinute;
        public final boolean killSwitch;

        public RiskStatus(double peakEquity, double dailyPnl, int ordersThisMinute,
                         int maxOrdersPerMinute, boolean killSwitch) {
            this.peakEquity = peakEquity;
            this.dailyPnl = dailyPnl;
            this.ordersThisMinute = ordersThisMinute;
            this.maxOrdersPerMinute = maxOrdersPerMinute;
            this.killSwitch = killSwitch;
        }
    }
}
