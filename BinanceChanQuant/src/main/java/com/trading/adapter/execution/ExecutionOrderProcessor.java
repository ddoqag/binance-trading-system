package com.trading.adapter.execution;

import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.risk.RiskManager;
import com.trading.domain.market.model.MarketData;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.ConcurrentHashMap;

/**
 * ExecutionOrderProcessor - 订单处理逻辑
 *
 * Responsibilities:
 * - Get execution plan from state machine
 * - Create market context
 * - Route order via SmartOrderRouter
 * - Execute via algo engine or direct
 * - Manage active executions
 */
public class ExecutionOrderProcessor {

    private static final Logger log = LoggerFactory.getLogger(ExecutionOrderProcessor.class);

    private final RiskManager riskManager;
    private final BinanceExchangeAdapter exchangeAdapter;
    private final SmartOrderRouter orderRouter;
    private final AlgoExecutionEngine algoEngine;
    private final BlockingQueue<Order> orderQueue;
    private final SignalCooldownManager cooldownManager;

    // Active execution tracking
    private final ConcurrentHashMap<String, ExecutionReporter.ActiveExecutionInfo> activeExecutions = new ConcurrentHashMap<>();
    private final ConcurrentHashMap<String, String> algoOrderToSymbol = new ConcurrentHashMap<>();

    public ExecutionOrderProcessor(RiskManager riskManager, BinanceExchangeAdapter exchangeAdapter,
                                   SmartOrderRouter orderRouter, AlgoExecutionEngine algoEngine,
                                   BlockingQueue<Order> orderQueue, SignalCooldownManager cooldownManager) {
        this.riskManager = riskManager;
        this.exchangeAdapter = exchangeAdapter;
        this.orderRouter = orderRouter;
        this.algoEngine = algoEngine;
        this.orderQueue = orderQueue;
        this.cooldownManager = cooldownManager;
    }

    /**
     * Process order
     */
    public void processOrder(Order order) {
        try {
            // Get execution plan - need reference to state machine
            // For now, create inline
            var executionPlan = getExecutionPlan(order);

            // Create market context
            MarketData marketData = getCurrentMarketData();

            // Route the order
            List<SmartOrderRouter.RoutedOrder> routedOrders = orderRouter.routeOrder(order, marketData);

            // Execute each routed order
            for (SmartOrderRouter.RoutedOrder routed : routedOrders) {
                Order routedOrder = routed.getOrder();

                boolean isExitIntent = isExitIntent(order);

                if (executionPlan.isUseAlgo() && !isExitIntent) {
                    // Check notional for small orders
                    double notional = routedOrder.getQuantity() * routedOrder.getPrice();
                    double availableBalance = exchangeAdapter != null ?
                        exchangeAdapter.getAvailableBalance() : 100.0;
                    double maxNotional = availableBalance * 20 * 0.5;

                    if (notional > 0 && notional < maxNotional) {
                        sendOrderDirect(routedOrder, routed.getExchange());
                        log.info("[ExecutionOrderProcessor] Small order direct: notional={}", notional);
                        continue;
                    }

                    // Start algo
                    routedOrder = withAlgoType(routedOrder, executionPlan.getAlgoType());
                    algoEngine.startAlgo(routedOrder, marketData);
                    activeExecutions.put(routedOrder.getSymbol(),
                        new ExecutionReporter.ActiveExecutionInfo(routedOrder.getOrderId(), routedOrder.getSymbol()));
                    algoOrderToSymbol.put(routedOrder.getOrderId(), routedOrder.getSymbol());
                } else {
                    sendOrderDirect(routedOrder, routed.getExchange());
                }
            }

        } catch (Exception e) {
            log.error("[ExecutionOrderProcessor] Failed to process order: {}", e.getMessage());
        }
    }

    private boolean isExitIntent(Order order) {
        if (exchangeAdapter == null) return false;
        double pos = exchangeAdapter.getCurrentPosition();
        return (order.getSide() == TradeDirection.LONG && pos < 0) ||
               (order.getSide() == TradeDirection.SHORT && pos > 0);
    }

    private Order withAlgoType(Order order, String algoType) {
        return new Order(
            order.getOrderId(),
            order.getSymbol(),
            order.getSide(),
            order.getOrderType(),
            order.getQuantity(),
            order.getPrice(),
            algoType,
            order.getUrgency()
        );
    }

    private MarketData getCurrentMarketData() {
        if (exchangeAdapter == null) return null;
        double lastPrice = exchangeAdapter.getLastPrice();
        double bidPrice = exchangeAdapter.getBidPrice();
        double askPrice = exchangeAdapter.getAskPrice();

        if (lastPrice <= 0 && bidPrice <= 0 && askPrice <= 0) return null;

        MarketData data = new MarketData();
        data.setSymbol(exchangeAdapter.getSymbol());
        data.setLastPrice(lastPrice > 0 ? lastPrice : (bidPrice > 0 ? bidPrice : 0));
        data.setBidPrice(bidPrice);
        data.setAskPrice(askPrice);
        data.setTimestamp(System.currentTimeMillis());
        return data;
    }

    private ExecutionPlan getExecutionPlan(Order order) {
        // Simplified - in real impl would call state machine
        return new ExecutionPlan(false, "MARKET");
    }

    private void sendOrderDirect(Order order, String exchange) {
        log.info("[ExecutionOrderProcessor] Sending order: {} {} {} @ {}", order.getSide(), order.getOrderType(), order.getQuantity(), order.getPrice());

        ExecutionReport report = exchangeAdapter.sendOrder(order);
        if (report != null) {
            // Would add to report queue
        }
    }

    public static class ExecutionPlan {
        private final boolean useAlgo;
        private final String algoType;

        public ExecutionPlan(boolean useAlgo, String algoType) {
            this.useAlgo = useAlgo;
            this.algoType = algoType;
        }

        public boolean isUseAlgo() { return useAlgo; }
        public String getAlgoType() { return algoType; }
    }
}
