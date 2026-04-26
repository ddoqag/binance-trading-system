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

    public PreTradeRiskChecker(double maxPosition, double maxDailyLoss,
                               int maxOrdersPerMinute, double maxOrderValue,
                               double maxDrawdown) {
        this.maxPosition = maxPosition;
        this.maxDailyLoss = maxDailyLoss;
        this.maxOrdersPerMinute = maxOrdersPerMinute;
        this.maxOrderValue = maxOrderValue;
        this.maxDrawdown = maxDrawdown;

        this.orderCircuitBreaker = CircuitBreaker.defaults();
        this.positionCircuitBreaker = new CircuitBreaker(3, 2, 60000, 2);
        this.lossCircuitBreaker = new CircuitBreaker(5, 3, 120000, 2);
    }

    public static PreTradeRiskChecker defaults() {
        return new PreTradeRiskChecker(10.0, 10000.0, 120, 1000000.0, 0.05);
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

        // Position limit check
        String symbol = order.getSymbol();
        double currentPosition = positions.getOrDefault(symbol, 0.0);
        double newPosition = calculateNewPosition(symbol, order);

        if (Math.abs(newPosition) > maxPosition) {
            dailyRejects.incrementAndGet();
            return RiskCheckResult.reject("Position limit exceeded: " + newPosition + " > " + maxPosition, "POSITION_LIMIT_EXCEEDED");
        }

        // Position circuit breaker
        if (!positionCircuitBreaker.allowRequest()) {
            dailyRejects.incrementAndGet();
            return RiskCheckResult.reject("Position circuit breaker is open", "POSITION_CIRCUIT_OPEN");
        }

        // Drawdown check
        Double equity = currentEquity.get();
        if (equity > 0 && peakEquity.get() > 0) {
            double drawdown = (peakEquity.get() - equity) / peakEquity.get();
            if (drawdown > maxDrawdown) {
                dailyRejects.incrementAndGet();
                return RiskCheckResult.reject("Drawdown limit exceeded: " + (drawdown * 100) + "% > " + (maxDrawdown * 100) + "%", "DRAWDOWN_LIMIT_EXCEEDED");
            }
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
        risk.maxPosition = maxPosition;
        risk.positionUtilization = Math.abs(totalPosition) / maxPosition;

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
        // Would update risk model with current market conditions
    }

    private boolean checkRateLimit() {
        resetOrderCountIfNeeded();
        return ordersThisMinute.get() < maxOrdersPerMinute;
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

    private void updateEquity(double currentPrice) {
        currentEquity.updateAndGet(v -> {
            if (v == 0) {
                return currentPrice;
            }
            return v;
        });

        peakEquity.updateAndGet(v -> {
            Double current = currentEquity.get();
            return (v == 0 || current > v) ? current : v;
        });
    }

    // Getters for testing
    public CircuitBreaker getOrderCircuitBreaker() { return orderCircuitBreaker; }
    public CircuitBreaker getLossCircuitBreaker() { return lossCircuitBreaker; }
    public int getOrdersThisMinute() { return ordersThisMinute.get(); }
}
