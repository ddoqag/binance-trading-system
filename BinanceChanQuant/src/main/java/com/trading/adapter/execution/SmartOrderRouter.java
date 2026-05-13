package com.trading.adapter.execution;

import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.market.model.MarketData;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Smart Order Router
 * Routes orders based on size, urgency, and market conditions
 */
public class SmartOrderRouter {

    private static final Logger log = LoggerFactory.getLogger(SmartOrderRouter.class);

    // Exchange status
    private final Map<String, ExchangeStatus> exchanges = new ConcurrentHashMap<>();
    private final List<RoutingRule> routingRules = new ArrayList<>();
    private final AtomicInteger routingCounter = new AtomicInteger(0);

    // Configuration
    private double largeOrderThreshold = 1000.0;
    private int maxSlices = 5;

    public SmartOrderRouter() {
        initializeExchanges();
        initializeRoutingRules();
    }

    private void initializeExchanges() {
        exchanges.put("binance", new ExchangeStatus("binance", 0.001, -0.0005));
    }

    private void initializeRoutingRules() {
        // Rule 1: Large order split
        routingRules.add(new RoutingRule("Large Order Split", 1, (order, context) -> {
            if (order.getQuantity() > largeOrderThreshold) {
                return splitLargeOrder(order, context);
            }
            return null;
        }));

        // Rule 2: TWAP algorithm
        routingRules.add(new RoutingRule("TWAP Algorithm", 2, (order, context) -> {
            if (order.getUrgency() < 0.7 && order.getQuantity() > 100) {
                return createTWAPSlices(order, context);
            }
            return null;
        }));

        // Rule 3: Cost optimal routing
        routingRules.add(new RoutingRule("Lowest Cost", 3, (order, context) -> {
            return findLowestCostExchange(order, context);
        }));
    }

    /**
     * Route an order
     */
    public List<RoutedOrder> routeOrder(Order order, MarketData marketData) {
        routingCounter.incrementAndGet();

        RoutingContext context = createRoutingContext(marketData);

        routingRules.sort(Comparator.comparingInt(RoutingRule::getPriority));

        for (RoutingRule rule : routingRules) {
            List<RoutedOrder> result = rule.apply(order, context);
            if (result != null && !result.isEmpty()) {
                log.info("[SmartOrderRouter] Applied rule: {}, generated {} slices", rule.getName(), result.size());
                return result;
            }
        }

        return defaultRouting(order, context);
    }

    private List<RoutedOrder> splitLargeOrder(Order order, RoutingContext context) {
        List<RoutedOrder> slices = new ArrayList<>();
        double sliceQty = order.getQuantity() / maxSlices;

        for (int i = 0; i < maxSlices; i++) {
            Order slice = createSliceOrder(order, i, sliceQty, 0.8);
            String exchange = selectExchangeForSlice(i, order.getSymbol());

            slices.add(new RoutedOrder(slice, exchange, 1.0 / maxSlices));
        }

        return slices;
    }

    private List<RoutedOrder> createTWAPSlices(Order order, RoutingContext context) {
        List<RoutedOrder> slices = new ArrayList<>();
        int numSlices = 10;
        double sliceQty = order.getQuantity() / numSlices;

        for (int i = 0; i < numSlices; i++) {
            Order slice = createSliceOrder(order, i, sliceQty, 0.6);
            // TWAP slices would be time-distributed in real implementation

            slices.add(new RoutedOrder(slice, "binance", 1.0 / numSlices));
        }

        return slices;
    }

    private List<RoutedOrder> findLowestCostExchange(Order order, RoutingContext context) {
        String bestExchange = exchanges.values().stream()
            .filter(ExchangeStatus::isConnected)
            .min(Comparator.comparingDouble(e -> e.getCostScore(order)))
            .map(ExchangeStatus::getName)
            .orElse("binance");

        return List.of(new RoutedOrder(order, bestExchange, 1.0));
    }

    private List<RoutedOrder> defaultRouting(Order order, RoutingContext context) {
        return List.of(new RoutedOrder(order, "binance", 1.0));
    }

    private Order createSliceOrder(Order original, int sliceIndex, double quantity, double urgencyFactor) {
        Order slice = new Order(
            original.getOrderId() + "_slice_" + sliceIndex,
            original.getSymbol(),
            original.getSide(),
            original.getOrderType(),
            quantity,
            original.getPrice(),
            original.getStrategy(),
            original.getUrgency() * urgencyFactor
        );

        // P1: CRITICAL - Preserve intent across all slices
        // Slices MUST NOT lose semantic intent
        // Parent CLOSE_SHORT → all children CLOSE_SHORT
        if (original.hasIntent()) {
            slice.setIntent(original.getIntent());
        }

        return slice;
    }

    private String selectExchangeForSlice(int sliceIndex, String symbol) {
        String[] exchangeList = exchanges.keySet().toArray(new String[0]);
        return exchangeList[sliceIndex % Math.max(1, exchangeList.length)];
    }

    private RoutingContext createRoutingContext(MarketData marketData) {
        RoutingContext context = new RoutingContext();
        context.setTimestamp(System.currentTimeMillis());
        if (marketData != null) {
            context.setSpread(marketData.getSpread());
            context.setVolatility(marketData.getVolatility());
            context.setVolume(marketData.getVolume());
        }
        return context;
    }

    // Inner classes

    public static class ExchangeStatus {
        private final String name;
        private double takerFee;
        private double makerFee;
        private boolean connected = true;
        private double latency = 0.0;
        private double fillRate = 1.0;

        public ExchangeStatus(String name, double takerFee, double makerFee) {
            this.name = name;
            this.takerFee = takerFee;
            this.makerFee = makerFee;
        }

        public double getCostScore(Order order) {
            double score = 0.0;
            score -= takerFee * 10000;

            if (!connected) {
                score -= 1000.0;
            }

            score -= latency * 0.1;
            score *= fillRate;

            return score;
        }

        public String getName() { return name; }
        public boolean isConnected() { return connected; }
    }

    public static class RoutingRule {
        private final String name;
        private final int priority;
        private final RoutingFunction function;

        public RoutingRule(String name, int priority, RoutingFunction function) {
            this.name = name;
            this.priority = priority;
            this.function = function;
        }

        public List<RoutedOrder> apply(Order order, RoutingContext context) {
            return function.apply(order, context);
        }

        public String getName() { return name; }
        public int getPriority() { return priority; }
    }

    @FunctionalInterface
    public interface RoutingFunction {
        List<RoutedOrder> apply(Order order, RoutingContext context);
    }

    public static class RoutingContext {
        private long timestamp;
        private double spread;
        private double volatility;
        private double volume;

        public long getTimestamp() { return timestamp; }
        public void setTimestamp(long timestamp) { this.timestamp = timestamp; }
        public double getSpread() { return spread; }
        public void setSpread(double spread) { this.spread = spread; }
        public double getVolatility() { return volatility; }
        public void setVolatility(double volatility) { this.volatility = volatility; }
        public double getVolume() { return volume; }
        public void setVolume(double volume) { this.volume = volume; }
    }

    public static class RoutedOrder {
        private final Order order;
        private final String exchange;
        private final double allocation;

        public RoutedOrder(Order order, String exchange, double allocation) {
            this.order = order;
            this.exchange = exchange;
            this.allocation = allocation;
        }

        public Order getOrder() { return order; }
        public String getExchange() { return exchange; }
        public double getAllocation() { return allocation; }
    }
}
