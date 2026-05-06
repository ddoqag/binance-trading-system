package com.trading.adapter.execution;

import com.binance.connector.futures.client.impl.UMFuturesClientImpl;
import com.binance.connector.futures.client.utils.ProxyAuth;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.trading.config.ConfigUtil;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.OrderStatus;
import com.trading.domain.trading.model.TradeDirection;

import java.net.InetSocketAddress;
import java.net.Proxy;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Binance Exchange Adapter
 *
 * Bridges the Clean Architecture trading system to Binance Futures API.
 * Supports both paper trading (simulated fills) and live trading.
 *
 * Reuses patterns from HFT OrderExecutor for API integration.
 */
public class BinanceExchangeAdapter {

    private final String symbol;
    private final boolean paperTrading;
    private final UMFuturesClientImpl client;
    private final ObjectMapper objectMapper = new ObjectMapper();

    // Position tracking (synced from exchange)
    private volatile double currentPosition = 0.0;
    private volatile double avgEntryPrice = 0.0;
    private volatile double unrealizedPnl = 0.0;
    private volatile double realizedPnl = 0.0;
    private volatile double totalRealizedPnl = 0.0;

    // Balance tracking
    private volatile double walletBalance = 0.0;
    private volatile double availableBalance = 0.0;

    // Order update callback for ProductionExchangeAdapter
    private java.util.function.Consumer<OrderUpdate> orderUpdateCallback;

    // Statistics
    private final AtomicLong totalOrders = new AtomicLong(0);
    private final AtomicLong totalFills = new AtomicLong(0);

    public BinanceExchangeAdapter(String symbol, boolean paperTrading, String apiKey, String apiSecret) {
        this.symbol = symbol;
        this.paperTrading = paperTrading;

        if (paperTrading) {
            this.client = null;
            System.out.println("[BinanceAdapter] Paper trading mode");
        } else {
            this.client = new UMFuturesClientImpl(apiKey, apiSecret, ConfigUtil.isTestNet());
            setProxy();
            System.out.println("[BinanceAdapter] Live trading mode (testnet=" + ConfigUtil.isTestNet() + ")");
        }
    }

    private void setProxy() {
        try {
            // In WSL2, 127.0.0.1 refers to WSL2 itself, so use Windows gateway IP
            String proxyHost = "192.168.16.1";
            int proxyPort = 7897;

            Proxy proxy = new Proxy(Proxy.Type.HTTP, new InetSocketAddress(proxyHost, proxyPort));
            ProxyAuth proxyAuth = new ProxyAuth(proxy, null);
            client.setProxy(proxyAuth);
            System.out.println("[BinanceAdapter] Proxy set: " + proxyHost + ":" + proxyPort + " (Windows host)");
        } catch (Exception e) {
            System.out.println("[BinanceAdapter] Proxy not configured: " + e.getMessage());
        }
    }

    /**
     * Send an order to Binance (or simulate in paper mode)
     * @return ExecutionReport with the result
     */
    public ExecutionReport sendOrder(Order order) {
        totalOrders.incrementAndGet();

        if (paperTrading) {
            return simulateFill(order);
        }

        return sendLiveOrder(order);
    }

    /**
     * Cancel an order
     */
    public boolean cancelOrder(String orderId, long binanceOrderId) {
        if (paperTrading) {
            System.out.println("[BinanceAdapter] Cancel (paper): " + orderId);
            return true;
        }

        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", symbol);
            params.put("orderId", binanceOrderId);

            Object resp = client.account().cancelOrder(params);
            System.out.println("[BinanceAdapter] Cancel: " + orderId + " -> " + resp);
            return true;
        } catch (Exception e) {
            System.err.println("[BinanceAdapter] Cancel failed: " + e.getMessage());
            return false;
        }
    }

    /**
     * Query order status from Binance
     */
    public ExecutionReport queryOrder(String orderId, long binanceOrderId) {
        if (paperTrading) {
            return null;
        }

        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", symbol);
            params.put("orderId", binanceOrderId);

            Object resp = client.account().queryOrder(params);
            System.out.println("[BinanceAdapter] QueryOrder: " + orderId + " -> " + resp);

            // Parse response and return ExecutionReport
            return parseQueryResponse(orderId, resp);
        } catch (Exception e) {
            System.err.println("[BinanceAdapter] Query failed: " + e.getMessage());
            return null;
        }
    }

    /**
     * Get current positions from Binance
     */
    public PositionInfo[] getPositions() {
        if (paperTrading) {
            return new PositionInfo[0];
        }

        try {
            // Position sync would query account here
            // For now, return empty - positions are tracked locally
            return new PositionInfo[0];
        } catch (Exception e) {
            System.err.println("[BinanceAdapter] Get positions failed: " + e.getMessage());
            return new PositionInfo[0];
        }
    }

    // ==================== Private Methods ====================

    private ExecutionReport simulateFill(Order order) {
        System.out.printf("[BinanceAdapter] Paper fill: %s %s %.4f @ %.2f%n",
            order.getSide(), order.getOrderType(), order.getQuantity(), order.getPrice());

        totalFills.incrementAndGet();

        // Update local position for paper trading
        updateLocalPosition(order, order.getQuantity(), order.getPrice());

        return new ExecutionReport(
            order.getOrderId(),
            order.getSymbol(),
            order.getSide(),
            order.getOrderType(),
            order.getQuantity(),
            order.getPrice(),
            order.getQuantity(),
            order.getPrice(),
            OrderStatus.FILLED,
            System.currentTimeMillis(),
            0.0,
            0.0
        );
    }

    private ExecutionReport sendLiveOrder(Order order) {
        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", order.getSymbol());
            params.put("side", order.getSide() == TradeDirection.LONG ? "BUY" : "SELL");

            // Map our OrderType to Binance order type
            String binanceType = mapOrderType(order.getOrderType());
            params.put("type", binanceType);
            params.put("quantity", formatQuantity(order.getQuantity()));

            // Add type-specific parameters
            if (order.getOrderType() == com.trading.domain.trading.model.OrderType.LIMIT ||
                order.getOrderType() == com.trading.domain.trading.model.OrderType.STOP_LIMIT) {
                params.put("price", formatPrice(order.getPrice()));
                params.put("timeInForce", "GTC");
            }

            // Add reduceOnly for close orders
            if (order.getSide() == TradeDirection.CLOSE) {
                params.put("reduceOnly", true);
            }

            // Add client order ID for idempotency
            params.put("newClientOrderId", order.getOrderId());

            Object resp = client.account().newOrder(params);

            // Parse JSON response properly
            long binanceOrderId = 0;
            double filledQty = 0;
            double fillPrice = order.getPrice();
            OrderStatus status = OrderStatus.NEW;

            try {
                String respStr = resp instanceof String ? (String) resp : resp.toString();
                JsonNode node = objectMapper.readTree(respStr);

                binanceOrderId = node.has("orderId") ? node.get("orderId").asLong() : 0;
                String ordStatus = node.has("status") ? node.get("status").asText() : "NEW";

                switch (ordStatus) {
                    case "FILLED": status = OrderStatus.FILLED; break;
                    case "PARTIALLY_FILLED": status = OrderStatus.PARTIALLY_FILLED; break;
                    case "REJECTED": status = OrderStatus.REJECTED; break;
                    case "CANCELED": status = OrderStatus.CANCELLED; break;
                    default: status = OrderStatus.NEW;
                }

                // Parse fill details if available
                if (node.has("executedQty")) {
                    filledQty = Double.parseDouble(node.get("executedQty").asText());
                }
                if (node.has("avgPrice") && !node.get("avgPrice").isNull()) {
                    fillPrice = Double.parseDouble(node.get("avgPrice").asText());
                }

                System.out.printf("[BinanceAdapter] Live order: clientId=%s, binanceId=%d, status=%s, filledQty=%.4f, avgPrice=%.2f%n",
                    order.getOrderId(), binanceOrderId, ordStatus, filledQty, fillPrice);

            } catch (Exception e) {
                System.err.println("[BinanceAdapter] JSON parse warning: " + e.getMessage() + " | resp=" + resp);
                binanceOrderId = System.currentTimeMillis();
                filledQty = order.getQuantity();
                fillPrice = order.getPrice();
                status = OrderStatus.FILLED;
            }

            totalFills.incrementAndGet();

            // Update position tracking
            updateLocalPosition(order, filledQty, fillPrice);

            return new ExecutionReport(
                order.getOrderId(),
                order.getSymbol(),
                order.getSide(),
                order.getOrderType(),
                order.getQuantity(),
                order.getPrice(),
                filledQty,
                fillPrice,
                status,
                System.currentTimeMillis(),
                0.0, // pnl - calculated by risk manager
                0.0  // fee
            );
        } catch (Exception e) {
            System.err.println("[BinanceAdapter] Order failed: " + e.getMessage());
            return new ExecutionReport(
                order.getOrderId(),
                order.getSymbol(),
                order.getSide(),
                order.getOrderType(),
                order.getQuantity(),
                order.getPrice(),
                0,
                0,
                OrderStatus.REJECTED,
                System.currentTimeMillis(),
                0.0,
                0.0
            );
        }
    }

    private String mapOrderType(com.trading.domain.trading.model.OrderType orderType) {
        if (orderType == com.trading.domain.trading.model.OrderType.MARKET) return "MARKET";
        if (orderType == com.trading.domain.trading.model.OrderType.STOP) return "STOP";
        if (orderType == com.trading.domain.trading.model.OrderType.STOP_LIMIT) return "STOP";
        if (orderType == com.trading.domain.trading.model.OrderType.IOC) return "IOC";
        if (orderType == com.trading.domain.trading.model.OrderType.FOK) return "FOK";
        return "LIMIT";
    }

    private String formatQuantity(double qty) {
        // Binance requires precision no more than 8 decimals for BTC
        return String.format("%.4f", qty);
    }

    private String formatPrice(double price) {
        // Binance requires price precision appropriate for BTC (2 decimals)
        return String.format("%.2f", price);
    }

    private void updateLocalPosition(Order order, double filledQty, double fillPrice) {
        if (filledQty <= 0) return;

        switch (order.getSide()) {
            case LONG: {
                double totalCost = currentPosition * avgEntryPrice + filledQty * fillPrice;
                currentPosition += filledQty;
                if (currentPosition > 0) {
                    avgEntryPrice = totalCost / currentPosition;
                }
                break;
            }
            case SHORT: {
                currentPosition -= filledQty;
                // For shorts, entry price tracking is similar
                if (currentPosition < 0) {
                    double totalCost = Math.abs(currentPosition) * avgEntryPrice + filledQty * fillPrice;
                    currentPosition = -(Math.abs(currentPosition) + filledQty);
                    avgEntryPrice = totalCost / Math.abs(currentPosition);
                }
                break;
            }
            case CLOSE: {
                // Reduce position
                if (currentPosition > 0) {
                    realizedPnl = filledQty * (avgEntryPrice - fillPrice);
                    currentPosition -= filledQty;
                } else if (currentPosition < 0) {
                    realizedPnl = filledQty * (fillPrice - avgEntryPrice);
                    currentPosition += filledQty;
                }
                totalRealizedPnl += realizedPnl;
                if (Math.abs(currentPosition) < 0.0001) {
                    currentPosition = 0;
                    avgEntryPrice = 0;
                }
                break;
            }
            default: break;
        }
    }

    /**
     * Sync positions from Binance exchange
     */
    public void syncPositionsFromExchange() {
        if (paperTrading || client == null) return;

        try {
            // Use empty params to get full account info
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();

            Object resp = client.account().accountInformation(params);
            String respStr = resp instanceof String ? (String) resp : resp.toString();
            JsonNode node = objectMapper.readTree(respStr);

            if (node.has("positions")) {
                for (JsonNode pos : node.get("positions")) {
                    String posSymbol = pos.has("symbol") ? pos.get("symbol").asText() : "";
                    if (!posSymbol.equalsIgnoreCase(symbol)) continue;

                    double posAmt = pos.has("positionAmt") ? pos.get("positionAmt").asDouble() : 0;
                    double entryPrice = pos.has("entryPrice") ? pos.get("entryPrice").asDouble() : 0;
                    double unrealizedPnL = pos.has("unrealizedProfit") ? pos.get("unrealizedProfit").asDouble() : 0;

                    // Only update if position exists
                    if (Math.abs(posAmt) > 0.0001) {
                        this.currentPosition = posAmt;
                        this.avgEntryPrice = entryPrice;
                        this.unrealizedPnl = unrealizedPnL;
                        System.out.printf("[BinanceAdapter] Position synced: pos=%.4f, entry=%.2f, unrealizedPnl=%.2f%n",
                            currentPosition, avgEntryPrice, unrealizedPnl);
                    }
                }
            }
        } catch (Exception e) {
            System.err.println("[BinanceAdapter] Position sync failed: " + e.getMessage());
        }
    }

    private long parseOrderId(Object response) {
        try {
            String respStr = response instanceof String ? (String) response : response.toString();
            JsonNode node = objectMapper.readTree(respStr);
            return node.has("orderId") ? node.get("orderId").asLong() : System.currentTimeMillis();
        } catch (Exception e) {
            return System.currentTimeMillis();
        }
    }

    private ExecutionReport parseQueryResponse(String orderId, Object response) {
        // Parse query order response
        // This is a simplified implementation
        return null;
    }

    private PositionInfo[] parsePositions(Object response) {
        // Parse account response for positions
        // This is a simplified implementation
        return new PositionInfo[0];
    }

    /**
     * Sync balance from Binance exchange
     */
    public double syncBalanceFromExchange() {
        if (paperTrading || client == null) return 0.0;

        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            Object resp = client.account().accountInformation(params);
            String respStr = resp instanceof String ? (String) resp : resp.toString();
            JsonNode node = objectMapper.readTree(respStr);

            if (node.has("availableBalance")) {
                availableBalance = node.get("availableBalance").asDouble();
            }
            if (node.has("walletBalance")) {
                walletBalance = node.get("walletBalance").asDouble();
            }

            System.out.printf("[BinanceAdapter] Balance synced: available=%.2f USDT%n", availableBalance);
            return availableBalance;
        } catch (Exception e) {
            System.err.println("[BinanceAdapter] Balance sync failed: " + e.getMessage());
            return 0.0;
        }
    }

    /**
     * Get available balance
     */
    public double getAvailableBalance() {
        return availableBalance;
    }

    /**
     * Set leverage for the symbol
     */
    public void setLeverage(int leverage) {
        if (paperTrading || client == null) return;

        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", symbol);
            params.put("leverage", leverage);

            Object resp = client.account().changeInitialLeverage(params);
            System.out.printf("[BinanceAdapter] Leverage set: %dx for %s%n", leverage, symbol);
        } catch (Exception e) {
            System.err.println("[BinanceAdapter] Failed to set leverage: " + e.getMessage());
        }
    }

    /**
     * Set order update callback for ProductionExchangeAdapter
     */
    public void setOrderUpdateCallback(java.util.function.Consumer<OrderUpdate> callback) {
        this.orderUpdateCallback = callback;
    }

    /**
     * Trigger order update callback (called from WebSocket handler)
     */
    public void onOrderUpdate(String clientOrderId, String status, double filledQty, double avgFillPrice) {
        if (orderUpdateCallback != null) {
            OrderUpdate update = new OrderUpdate(clientOrderId, status, filledQty, avgFillPrice);
            orderUpdateCallback.accept(update);
        }
    }

    /**
     * Order update event for callback
     */
    public static class OrderUpdate {
        public final String clientOrderId;
        public final String status;
        public final double filledQty;
        public final double avgFillPrice;

        public OrderUpdate(String clientOrderId, String status, double filledQty, double avgFillPrice) {
            this.clientOrderId = clientOrderId;
            this.status = status;
            this.filledQty = filledQty;
            this.avgFillPrice = avgFillPrice;
        }
    }

    // ==================== Getters ====================

    public long getTotalOrders() { return totalOrders.get(); }
    public long getTotalFills() { return totalFills.get(); }
    public boolean isPaperTrading() { return paperTrading; }

    public double getCurrentPosition() { return currentPosition; }
    public double getAvgEntryPrice() { return avgEntryPrice; }
    public double getUnrealizedPnl() { return unrealizedPnl; }
    public double getTotalRealizedPnl() { return totalRealizedPnl; }

    /**
     * Position information from exchange
     */
    public static class PositionInfo {
        public final String symbol;
        public final double size;
        public final double entryPrice;
        public final double unrealizedPnl;
        public final double leverage;

        public PositionInfo(String symbol, double size, double entryPrice, double unrealizedPnl, double leverage) {
            this.symbol = symbol;
            this.size = size;
            this.entryPrice = entryPrice;
            this.unrealizedPnl = unrealizedPnl;
            this.leverage = leverage;
        }
    }
}
