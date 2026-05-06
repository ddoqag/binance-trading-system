package com.trading.infrastructure.observability;

import com.trading.domain.market.model.MarketRegime;

/**
 * SignalScenarioTracker
 * 跟踪测试场景中的关键指标
 */
public class SignalScenarioTracker {

    // Scenario 1: 快速趋势行情
    private volatile double lastPrice = 0;
    private volatile long lastPriceTime = 0;
    private volatile double maxPriceVelocity = 0;  // 价格变化最大速度 (price/sec)
    private int trendUpCount = 0;
    private int trendDownCount = 0;

    // Scenario 2: 横盘震荡
    private final double[] recentPrices = new double[30];
    private int priceIndex = 0;
    private volatile double avgVolatility = 0;

    // Scenario 3: 数据断线重连
    private volatile boolean connectionLost = false;
    private volatile long lastMessageTime = 0;
    private volatile long reconnectCount = 0;
    private long lastReconnectTime = 0;

    public void recordPrice(double price) {
        long now = System.currentTimeMillis();

        // Track price velocity
        if (lastPrice > 0 && lastPriceTime > 0) {
            double delta = price - lastPrice;
            double dt = (now - lastPriceTime) / 1000.0;
            if (dt > 0) {
                double velocity = Math.abs(delta) / dt;
                if (velocity > maxPriceVelocity) {
                    maxPriceVelocity = velocity;
                }
            }
        }

        lastPrice = price;
        lastPriceTime = now;

        // Track recent prices for volatility calculation
        recentPrices[priceIndex % 30] = price;
        priceIndex++;

        // Calculate average volatility
        double sum = 0;
        for (int i = 0; i < 30; i++) {
            sum += recentPrices[i];
        }
        double avg = sum / 30;
        double variance = 0;
        for (int i = 0; i < 30; i++) {
            double diff = recentPrices[i] - avg;
            variance += diff * diff;
        }
        avgVolatility = Math.sqrt(variance / 30) / avg;

        // Update message time
        lastMessageTime = now;

        // Connection is healthy if message within 3 seconds
        if (connectionLost && (now - lastMessageTime) < 3000) {
            // Reconnected
            lastReconnectTime = now;
            reconnectCount++;
            connectionLost = false;
        }
    }

    public void markConnectionLost() {
        connectionLost = true;
    }

    public void markConnected() {
        connectionLost = false;
        lastReconnectTime = System.currentTimeMillis();
        reconnectCount++;
    }

    /**
     * Detect if current market is in fast trend
     */
    public boolean isFastTrend() {
        return maxPriceVelocity > 1.0;  // > 1 price unit per second
    }

    /**
     * Detect if current market is in range/consolidation
     */
    public boolean isRangeBound() {
        return avgVolatility < 0.001;  // < 0.1% volatility
    }

    /**
     * Check if connection is healthy
     */
    public boolean isConnectionHealthy() {
        return !connectionLost && (System.currentTimeMillis() - lastMessageTime) < 3000;
    }

    public double getMaxPriceVelocity() {
        return maxPriceVelocity;
    }

    public double getAvgVolatility() {
        return avgVolatility;
    }

    public long getReconnectCount() {
        return reconnectCount;
    }

    public boolean wasConnectionLost() {
        return connectionLost;
    }

    /**
     * Print scenario status report
     */
    public void printScenarioReport() {
        System.out.println("\n========== Scenario Test Report ==========");
        System.out.printf("Current Price: %.2f%n", lastPrice);
        System.out.printf("Max Price Velocity: %.4f (price/sec)%n", maxPriceVelocity);
        System.out.printf("Avg Volatility (30 samples): %.4f%%%n", avgVolatility * 100);
        System.out.printf("Connection Status: %s%n", isConnectionHealthy() ? "HEALTHY" : "LOST");
        System.out.printf("Reconnect Count: %d%n", reconnectCount);
        System.out.println("-----------------------------------------");
        System.out.printf("Fast Trend: %s%n", isFastTrend() ? "YES (velocity > 1.0)" : "NO");
        System.out.printf("Range Bound: %s%n", isRangeBound() ? "YES (vol < 0.1%)" : "NO");
        System.out.printf("Connection Lost: %s%n", wasConnectionLost() ? "YES" : "NO");
        System.out.println("=========================================\n");
    }

    /**
     * Reset velocity tracking (call after trend ends)
     */
    public void resetVelocityTracking() {
        maxPriceVelocity = 0;
    }

    public void reset() {
        lastPrice = 0;
        lastPriceTime = 0;
        maxPriceVelocity = 0;
        avgVolatility = 0;
        connectionLost = false;
        lastMessageTime = 0;
        reconnectCount = 0;
        priceIndex = 0;
        for (int i = 0; i < 30; i++) recentPrices[i] = 0;
    }
}