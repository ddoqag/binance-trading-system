package com.trading.domain.trading.model;

/**
 * Position State - tracks lifecycle of a position
 *
 * Immutable - creates new instance on updates
 */
public class PositionState {
    private final double quantity;          // Positive = LONG, Negative = SHORT
    private final double entryPrice;
    private final double unrealizedPnl;
    private final double realizedPnl;
    private final long entryTime;
    private final double peakEquity;
    private final double entryEquity;
    private final String orderId;
    private final RiskModel riskModel;      // Risk parameters (ATR-based stops)
    private final double peakPrice;         // Highest/lowest price since entry (for trailing)
    private final double lowestPrice;       // Lowest price since entry

    public PositionState(double quantity, double entryPrice, double unrealizedPnl,
                        double realizedPnl, long entryTime, double peakEquity,
                        double entryEquity, String orderId, RiskModel riskModel,
                        double peakPrice, double lowestPrice) {
        this.quantity = quantity;
        this.entryPrice = entryPrice;
        this.unrealizedPnl = unrealizedPnl;
        this.realizedPnl = realizedPnl;
        this.entryTime = entryTime;
        this.peakEquity = peakEquity;
        this.entryEquity = entryEquity;
        this.orderId = orderId;
        this.riskModel = riskModel;
        this.peakPrice = peakPrice;
        this.lowestPrice = lowestPrice;
    }

    /** No position */
    public static PositionState empty() {
        return new PositionState(0, 0, 0, 0, 0, 0, 0, "", null, 0, 0);
    }

    /** Create from entry order */
    public static PositionState fromEntry(double quantity, double price, String orderId, double equity, RiskModel riskModel) {
        return new PositionState(
            quantity,
            price,
            0,
            0,
            System.currentTimeMillis(),
            equity,
            equity,
            orderId,
            riskModel,
            price,  // Initial peak/lowest is entry price
            price
        );
    }

    public double getQuantity() { return quantity; }
    public double getEntryPrice() { return entryPrice; }
    public double getUnrealizedPnl() { return unrealizedPnl; }
    public double getRealizedPnl() { return realizedPnl; }
    public long getEntryTime() { return entryTime; }
    public double getPeakEquity() { return peakEquity; }
    public double getEntryEquity() { return entryEquity; }
    public String getOrderId() { return orderId; }
    public RiskModel getRiskModel() { return riskModel; }
    public double getPeakPrice() { return peakPrice; }
    public double getLowestPrice() { return lowestPrice; }

    public boolean hasPosition() { return Math.abs(quantity) > 0.0001; }
    public boolean isLong() { return quantity > 0; }
    public boolean isShort() { return quantity < 0; }
    public TradeDirection getDirection() {
        if (quantity > 0) return TradeDirection.LONG;
        if (quantity < 0) return TradeDirection.SHORT;
        return TradeDirection.NEUTRAL;
    }

    /** Drawdown from peak equity */
    public double getDrawdown() {
        if (peakEquity <= 0) return 0;
        return (peakEquity - unrealizedPnl) / peakEquity;
    }

    /** Price drawdown from peak price */
    public double getPriceDrawdownPercent(double currentPrice) {
        if (peakPrice <= 0 || currentPrice <= 0) return 0;
        if (isLong()) {
            return (peakPrice - currentPrice) / peakPrice * 100;
        } else {
            return (currentPrice - lowestPrice) / lowestPrice * 100;
        }
    }

    /** Holding time in milliseconds */
    public long getHoldingTimeMs() {
        if (entryTime == 0) return 0;
        return System.currentTimeMillis() - entryTime;
    }

    /** Holding time in minutes */
    public long getHoldingTimeMinutes() {
        return getHoldingTimeMs() / 60000;
    }

    /** Update with new PnL and track peak/lowest prices */
    public PositionState withUnrealizedPnl(double newUnrealizedPnl, double currentEquity, double currentPrice) {
        // For LONG: peakPrice=highest, lowestPrice=lowest
        // For SHORT: peakPrice=highest (unfavorable), lowestPrice=lowest (favorable)
        double newPeakPrice = Math.max(peakPrice, currentPrice);
        double newLowestPrice = Math.min(lowestPrice, currentPrice);

        return new PositionState(
            quantity,
            entryPrice,
            newUnrealizedPnl,
            realizedPnl,
            entryTime,
            Math.max(peakEquity, currentEquity),
            entryEquity,
            orderId,
            riskModel,
            newPeakPrice,
            newLowestPrice
        );
    }

    /** Update on partial close */
    public PositionState withQuantity(double newQuantity) {
        return new PositionState(
            newQuantity,
            entryPrice,
            unrealizedPnl,
            realizedPnl + unrealizedPnl, // Lock in PnL
            entryTime,
            peakEquity,
            entryEquity,
            orderId,
            riskModel,
            peakPrice,
            lowestPrice
        );
    }

    /** Update on full close */
    public PositionState closed() {
        return new PositionState(
            0,
            0,
            0,
            realizedPnl + unrealizedPnl,
            0,
            0,
            entryEquity,
            "",
            null,
            0,
            0
        );
    }

    // ========== Ownership DAG Cleanup ==========
    // P1: When position closes, pending orders must be cancelled
    // Protection remains on exchange (exchange-native) - just detach

    /**
     * Cleanup callback interface for cascade cleanup.
     * Called when position enters terminal state.
     */
    @FunctionalInterface
    public interface PositionCleanup {
        void cleanup();
    }

    private static PositionCleanup cleanupHandler;

    /**
     * Register cleanup handler for position closure.
     * Called with the orderId of the entry order.
     */
    public static void setCleanupHandler(PositionCleanup handler) {
        PositionState.cleanupHandler = handler;
    }

    /**
     * Trigger cascade cleanup on position close.
     * Cancels pending entry order if exists.
     */
    public void triggerCleanup() {
        if (cleanupHandler != null && !orderId.isEmpty()) {
            cleanupHandler.cleanup();
        }
    }
}
