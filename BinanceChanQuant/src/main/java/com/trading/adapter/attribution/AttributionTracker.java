package com.trading.adapter.attribution;

import com.trading.domain.signal.AlphaSignal;
import com.trading.domain.trading.ExecutionAttribution;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Attribution Tracker - Maps orderId to signal, computes attribution on fill
 */
public class AttributionTracker {

    private final Map<String, SignalReference> orderSignalMap = new ConcurrentHashMap<>();
    private final Map<String, ExecutionAttribution> attributionResults = new ConcurrentHashMap<>();

    public static class SignalReference {
        private final String orderId;
        private final AlphaSignal signal;
        private final long timestamp;
        private final double signalPrice;

        public SignalReference(String orderId, AlphaSignal signal, long timestamp, double signalPrice) {
            this.orderId = orderId;
            this.signal = signal;
            this.timestamp = timestamp;
            this.signalPrice = signalPrice;
        }

        public String getOrderId() { return orderId; }
        public AlphaSignal getSignal() { return signal; }
        public long getTimestamp() { return timestamp; }
        public double getSignalPrice() { return signalPrice; }
    }

    /**
     * Track signal for an order
     */
    public void trackOrder(String orderId, AlphaSignal signal) {
        if (orderId == null || signal == null) return;

        orderSignalMap.put(orderId, new SignalReference(
            orderId,
            signal,
            System.currentTimeMillis(),
            signal.getEntryPrice()
        ));
    }

    /**
     * Compute attribution when order fills
     */
    public ExecutionAttribution computeAttribution(String orderId, double executionPrice,
                                                    double currentPrice, double pnl) {
        SignalReference ref = orderSignalMap.get(orderId);
        if (ref == null) {
            return null;
        }

        long now = System.currentTimeMillis();

        // Calculate components
        double signalAlpha = calculateSignalAlpha(ref.getSignalPrice(), currentPrice, ref.getSignal().getDirection());
        double executionAlpha = calculateExecutionAlpha(ref.getSignalPrice(), executionPrice, ref.getSignal().getDirection());
        double slippage = calculateSlippage(ref.getSignalPrice(), executionPrice, ref.getSignal().getDirection());
        double delayCost = calculateDelayCost(ref.getTimestamp(), now, ref.getSignal());
        double marketImpact = estimateMarketImpact(ref.getSignal(), executionPrice);

        ExecutionAttribution attribution = new ExecutionAttribution.Builder()
            .orderId(orderId)
            .signalId(ref.getSignal().getAlphaId())
            .totalPnl(pnl)
            .signalAlpha(signalAlpha)
            .executionAlpha(executionAlpha)
            .slippage(slippage)
            .delayCost(delayCost)
            .marketImpact(marketImpact)
            .signalPrice(ref.getSignalPrice())
            .benchmarkPrice(executionPrice) // Fair price = execution price for filled orders
            .executionPrice(executionPrice)
            .currentPrice(currentPrice)
            .signalTimestamp(ref.getTimestamp())
            .orderTimestamp(ref.getTimestamp())
            .fillTimestamp(now)
            .build();

        attributionResults.put(orderId, attribution);
        return attribution;
    }

    private double calculateSignalAlpha(double signalPrice, double currentPrice,
            com.trading.domain.trading.model.TradeDirection direction) {
        double priceChange = currentPrice - signalPrice;
        if (direction == com.trading.domain.trading.model.TradeDirection.SHORT) {
            priceChange = -priceChange;
        }
        return priceChange;
    }

    private double calculateExecutionAlpha(double signalPrice, double executionPrice,
            com.trading.domain.trading.model.TradeDirection direction) {
        // Execution alpha: did we execute better or worse than the signal price?
        double diff = executionPrice - signalPrice;
        if (direction == com.trading.domain.trading.model.TradeDirection.SHORT) {
            diff = -diff;
        }
        // Positive means we executed better than signal price
        return -diff;
    }

    private double calculateSlippage(double signalPrice, double executionPrice,
            com.trading.domain.trading.model.TradeDirection direction) {
        double diff = executionPrice - signalPrice;
        if (direction == com.trading.domain.trading.model.TradeDirection.SHORT) {
            diff = -diff;
        }
        // Slippage is the unexpected part (positive = cost)
        return Math.abs(diff) * 0.5;
    }

    private double calculateDelayCost(long signalTime, long executionTime, AlphaSignal signal) {
        long delayMs = executionTime - signalTime;
        double delaySeconds = delayMs / 1000.0;

        // Cost per second of delay (simplified)
        // In practice, this would be based on volatility and liquidity
        double costPerSecond = signal.getExpectedVolatility() * 0.001;

        return delaySeconds * costPerSecond;
    }

    private double estimateMarketImpact(AlphaSignal signal, double executionPrice) {
        // Market impact based on signal urgency and order size
        double baseImpact = signal.getUrgency() * 0.5; // Base impact from urgency
        double sizeImpact = signal.getExpectedReturn() * 0.1; // Impact from expected return

        return baseImpact + sizeImpact;
    }

    /**
     * Get attribution result for an order
     */
    public ExecutionAttribution getAttribution(String orderId) {
        return attributionResults.get(orderId);
    }

    /**
     * Remove tracking for completed order
     */
    public void forgetOrder(String orderId) {
        // Keep attribution for historical analysis
        // orderSignalMap.remove(orderId);
    }

    /**
     * Get tracker statistics
     */
    public TrackerStats getStats() {
        return new TrackerStats(
            orderSignalMap.size(),
            attributionResults.size()
        );
    }

    public static class TrackerStats {
        public final int pendingOrders;
        public final int completedAttributions;

        public TrackerStats(int pendingOrders, int completedAttributions) {
            this.pendingOrders = pendingOrders;
            this.completedAttributions = completedAttributions;
        }
    }
}