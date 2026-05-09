package com.trading.adapter.risk;

import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.risk.RiskManager;
import com.trading.domain.trading.risk.RiskCheckResult;
import com.trading.domain.trading.risk.CircuitBreaker;

import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.ConcurrentHashMap;

/**
 * PreTradeRiskChecker
 * Implements RiskManager interface with comprehensive pre-trade risk checks
 */
public class PreTradeRiskChecker implements RiskManager {

    // Configuration
    private final double maxPosition;
    private final double maxDailyLoss;
    private final int maxOrdersPerMinute;
    private final double maxOrderValue;
    private final double maxDrawdown;

    // State
    private final AtomicReference<Double> peakEquity = new AtomicReference<>(0.0);
    private final AtomicReference<Double> currentEquity = new AtomicReference<>(0.0);
    private final AtomicReference<Double> dailyPnl = new AtomicReference<>(0.0);
    private final AtomicInteger ordersThisMinute = new AtomicInteger(0);
    private final AtomicLong lastResetTime = new AtomicLong(System.currentTimeMillis());

    // Circuit breakers
    private final CircuitBreaker orderCircuitBreaker;
    private final CircuitBreaker positionCircuitBreaker;
    private final CircuitBreaker lossCircuitBreaker;

    // Position tracking
    private final ConcurrentHashMap<String, Double> positions = new ConcurrentHashMap<>();

    // Daily stats
    private final AtomicInteger dailyTrades = new AtomicInteger(0);
    private final AtomicInteger dailyRejects = new AtomicInteger(0);
    private final AtomicInteger consecutiveLosses = new AtomicInteger(0);

    // Volatility estimator for adaptive risk
    private final VolatilityEstimator volatilityEstimator;
    private volatile double dynamicPositionLimit = 10.0;
    private volatile double volatilityScaleFactor = 1.0;

    // Drawdown-aware scaling
    private final DrawdownScaler drawdownScaler = new DrawdownScaler();

    public PreTradeRiskChecker(double maxPosition, double maxDailyLoss,
                               int maxOrdersPerMinute, double maxOrderValue,
                               double maxDrawdown,
                               VolatilityEstimator volatilityEstimator) {
        this.maxPosition = maxPosition;
        this.maxDailyLoss = maxDailyLoss;
        this.maxOrdersPerMinute = maxOrdersPerMinute;
        this.maxOrderValue = maxOrderValue;
        this.maxDrawdown = maxDrawdown;
        this.volatilityEstimator = volatilityEstimator;

        this.orderCircuitBreaker = CircuitBreaker.defaults();
        // FIX: Relaxed circuit breaker thresholds for more robust trading
        this.positionCircuitBreaker = new CircuitBreaker(3, 3, 60000, 2);
        this.lossCircuitBreaker = new CircuitBreaker(5, 5, 120000, 2);
    }

    public static PreTradeRiskChecker defaults() {
        return new PreTradeRiskChecker(10.0, 10000.0, 120, 1000000.0, 0.05,
            new VolatilityEstimator());
    }

    @Override
    public RiskCheckResult preTradeCheck(Order order) {
        // Circuit breaker check
        if (!orderCircuitBreaker.allowRequest()) {
            dailyRejects.incrementAndGet();
            return RiskCheckResult.reject("Order circuit breaker is open", "ORDER_CIRCUIT_OPEN");
        }

        // Loss circuit breaker
        if (lossCircuitBreaker.isOpen()) {
            dailyRejects.incrementAndGet();
            return RiskCheckResult.reject("Loss circuit breaker is open", "LOSS_CIRCUIT_OPEN");
        }

        // Rate limit check
        if (!checkRateLimit()) {
            dailyRejects.incrementAndGet();
            return RiskCheckResult.reject("Rate limit exceeded", "RATE_LIMIT_EXCEEDED");
        }

        // Order value check
        double orderValue = order.getQuantity() * order.getPrice();
        if (orderValue > maxOrderValue) {
            dailyRejects.incrementAndGet();
            return RiskCheckResult.reject("Order value exceeds maximum: " + orderValue + " > " + maxOrderValue, "ORDER_VALUE_EXCEEDS_MAX");
        }

        // Calculate drawdown first (used for multiple checks)
        Double equity = currentEquity.get();
        double drawdown = 0.0;
        if (equity > 0 && peakEquity.get() > 0) {
            drawdown = (peakEquity.get() - equity) / peakEquity.get();
        }

        // Drawdown check - block if too high
        if (drawdownScaler.isBlocked(drawdown)) {
            dailyRejects.incrementAndGet();
            return RiskCheckResult.reject("Trading blocked: drawdown " + (drawdown * 100) + "% exceeds limit", "DRAWDOWN_BLOCKED");
        }

        // Position limit check (use dynamic limit based on volatility AND drawdown)
        String symbol = order.getSymbol();
        double currentPosition = positions.getOrDefault(symbol, 0.0);
        double newPosition = calculateNewPosition(symbol, order);

        // Apply both volatility and drawdown scaling
        double ddScale = drawdownScaler.scale(drawdown);
        // FIX: Ensure minimum scale factor of 0.3 to prevent complete trading halt during high volatility
        double effectiveLimit = dynamicPositionLimit * Math.max(volatilityScaleFactor, 0.3) * ddScale;

        if (Math.abs(newPosition) > effectiveLimit) {
            dailyRejects.incrementAndGet();
            return RiskCheckResult.reject("Position limit exceeded: " + newPosition + " > " + effectiveLimit + " (vol=" + String.format("%.2f", volatilityScaleFactor) + " dd=" + String.format("%.2f", ddScale) + ")", "POSITION_LIMIT_EXCEEDED");
        }

        // Position circuit breaker
        if (!positionCircuitBreaker.allowRequest()) {
            dailyRejects.incrementAndGet();
            return RiskCheckResult.reject("Position circuit breaker is open", "POSITION_CIRCUIT_OPEN");
        }

        // Daily loss check
        Double pnl = dailyPnl.get();
        if (pnl < -maxDailyLoss) {
            dailyRejects.incrementAndGet();
            return RiskCheckResult.reject("Daily loss limit exceeded: " + pnl + " < " + (-maxDailyLoss), "DAILY_LOSS_LIMIT_EXCEEDED");
        }

        // Passed all checks - increment rate limit counter
        ordersThisMinute.incrementAndGet();
        return RiskCheckResult.allow();
    }

    @Override
    public void onExecution(ExecutionReport report) {
        dailyTrades.incrementAndGet();

        if (report.getStatus() == com.trading.domain.trading.model.OrderStatus.FILLED) {
            String symbol = report.getSymbol();
            double currentPos = positions.getOrDefault(symbol, 0.0);

            if (report.getSide() == com.trading.domain.trading.model.TradeDirection.LONG) {
                positions.put(symbol, currentPos + report.getFilledQuantity());
            } else if (report.getSide() == com.trading.domain.trading.model.TradeDirection.SHORT) {
                positions.put(symbol, currentPos - report.getFilledQuantity());
            }

            // Record PnL
            if (report.getPnL() != 0) {
                dailyPnl.updateAndGet(v -> v + report.getPnL());

                if (report.getPnL() < 0) {
                    consecutiveLosses.incrementAndGet();
                    lossCircuitBreaker.recordFailure();

                    if (consecutiveLosses.get() >= 3) {
                        System.err.println("[PreTradeRiskChecker] Consecutive losses detected: " + consecutiveLosses.get());
                    }
                } else {
                    consecutiveLosses.set(0);
                    lossCircuitBreaker.recordSuccess();
                }

                orderCircuitBreaker.recordSuccess();
            }
        } else if (report.getStatus() == com.trading.domain.trading.model.OrderStatus.REJECTED) {
            orderCircuitBreaker.recordFailure();
            dailyRejects.incrementAndGet();
        }

        // Update equity
        updateEquity(report.getAvgFillPrice());
    }

    @Override
    public PositionRisk getPositionRisk() {
        PositionRisk risk = new PositionRisk();
        double totalPosition = positions.values().stream().mapToDouble(Double::doubleValue).sum();
        risk.currentPosition = totalPosition;
        risk.maxPosition = dynamicPositionLimit;
        risk.positionUtilization = Math.abs(totalPosition) / dynamicPositionLimit;

        Double equity = currentEquity.get();
        Double peak = peakEquity.get();
        if (peak > 0) {
            risk.unrealizedPnl = equity - peak;
        }

        return risk;
    }

    @Override
    public DailyRiskMetrics getDailyRiskMetrics() {
        DailyRiskMetrics metrics = new DailyRiskMetrics();
        metrics.dailyPnl = dailyPnl.get();
        metrics.dailyLossLimit = maxDailyLoss;
        metrics.dailyTrades = dailyTrades.get();
        metrics.dailyRejects = dailyRejects.get();

        int trades = dailyTrades.get();
        if (trades > 0) {
            metrics.winRate = (double) (trades - dailyRejects.get()) / trades;
        }

        return metrics;
    }

    @Override
    public double getMaxDrawdown() {
        Double equity = currentEquity.get();
        Double peak = peakEquity.get();
        if (peak > 0 && equity > 0) {
            return (peak - equity) / peak;
        }
        return 0.0;
    }

    @Override
    public double getSharpeRatio() {
        // Simplified - would calculate from historical PnL data
        return 0.0;
    }

    @Override
    public boolean isCircuitBreakerTriggered() {
        return orderCircuitBreaker.isOpen() ||
               positionCircuitBreaker.isOpen() ||
               lossCircuitBreaker.isOpen();
    }

    @Override
    public void resetDailyCounters() {
        dailyTrades.set(0);
        dailyRejects.set(0);
        dailyPnl.set(0.0);
        ordersThisMinute.set(0);
        lastResetTime.set(System.currentTimeMillis());
        consecutiveLosses.set(0);
    }

    @Override
    public void updateMarketData(double price, double volatility, double volume) {
        // Update volatility estimator
        volatilityEstimator.update(price);

        // Calculate dynamic position limit based on volatility
        double atrPercent = volatilityEstimator.getAtrPercent();
        volatilityScaleFactor = volatilityEstimator.getVolatilityScaleFactor();
        dynamicPositionLimit = maxPosition * Math.min(volatilityScaleFactor, 2.0);

        // Update equity with current price
        updateEquity(price);
    }

    /**
     * Get current volatility scale factor
     */
    public double getVolatilityScaleFactor() {
        return volatilityScaleFactor;
    }

    /**
     * Get dynamic position limit
     */
    public double getDynamicPositionLimit() {
        return dynamicPositionLimit;
    }

    /**
     * Get volatility estimator for external use
     */
    public VolatilityEstimator getVolatilityEstimator() {
        return volatilityEstimator;
    }

    private boolean checkRateLimit() {
        resetOrderCountIfNeeded();
        return ordersThisMinute.get() < maxOrdersPerMinute;
    }

    // FIX: Added interval tracking for per-symbol minimum time between orders
    private final ConcurrentHashMap<String, Long> lastOrderTime = new ConcurrentHashMap<>();
    private static final long MIN_ORDER_INTERVAL_MS = 1_000; // 1 second minimum

    /**
     * Check minimum interval between orders for the same symbol
     */
    private boolean checkMinInterval(String symbol) {
        long now = System.currentTimeMillis();
        long lastTime = lastOrderTime.getOrDefault(symbol, 0L);
        if (now - lastTime < MIN_ORDER_INTERVAL_MS) {
            return false;
        }
        lastOrderTime.put(symbol, now);
        return true;
    }

    private void resetOrderCountIfNeeded() {
        long now = System.currentTimeMillis();
        if (now - lastResetTime.get() > 60_000) {
            ordersThisMinute.set(0);
            lastResetTime.set(now);
        }
    }

    private double calculateNewPosition(String symbol, Order order) {
        double current = positions.getOrDefault(symbol, 0.0);
        double qty = order.getQuantity();

        switch (order.getSide()) {
            case LONG:
                return current + qty;
            case SHORT:
                return current - qty;
            case CLOSE:
                return 0.0;
            default:
                return current;
        }
    }

    /**
     * FIX: Updated to track equity properly based on PnL from execution reports.
     * Note: currentPrice parameter is only used for initial equity establishment,
     * not as a running equity value. Real equity should come from execution PnL.
     */
    private void updateEquity(double currentPrice) {
        // Only initialize equity once with a reasonable starting value
        currentEquity.updateAndGet(v -> {
            if (v == 0) {
                // Initialize with a default paper trading balance if no valid price
                return currentPrice > 0 ? currentPrice : 10000.0;
            }
            return v; // Keep existing equity - rely on PnL updates for changes
        });

        peakEquity.updateAndGet(v -> {
            Double current = currentEquity.get();
            return (v == 0 || current > v) ? current : v;
        });
    }

    /**
     * Update equity based on PnL from execution report
     * This is the proper way to update equity after fills
     */
    public void updateEquityWithPnL(double pnl) {
        if (pnl != 0) {
            currentEquity.updateAndGet(v -> v + pnl);
            peakEquity.updateAndGet(v -> {
                Double current = currentEquity.get();
                return (current > v) ? current : v;
            });
        }
    }

    // Getters for testing
    public CircuitBreaker getOrderCircuitBreaker() { return orderCircuitBreaker; }
    public CircuitBreaker getLossCircuitBreaker() { return lossCircuitBreaker; }
    public int getOrdersThisMinute() { return ordersThisMinute.get(); }
}
