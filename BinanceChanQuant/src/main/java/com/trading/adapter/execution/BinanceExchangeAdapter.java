package com.trading.adapter.execution;

import com.binance.connector.futures.client.impl.UMFuturesClientImpl;
import com.binance.connector.futures.client.utils.ProxyAuth;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.trading.config.ConfigUtil;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.OrderStatus;
import com.trading.domain.trading.model.PositionState;
import com.trading.domain.trading.model.RiskModel;
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
            String proxyHost = "127.0.0.1";
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
            // First sync from exchange, then return local position state
            syncPositionsFromExchange();

            // Return local position state as PositionInfo array
            if (Math.abs(currentPosition) > 0.0001) {
                return new PositionInfo[] {
                    new PositionInfo(symbol, currentPosition, avgEntryPrice, unrealizedPnl, 0)
                };
            }
            return new PositionInfo[0];
        } catch (Exception e) {
            System.err.println("[BinanceAdapter] Get positions failed: " + e.getMessage());
            return new PositionInfo[0];
        }
    }

    // ==================== Private Methods ====================

    /**
     * Log current account balance for debugging margin issues
     * 注意：USDT-M futures使用 /fapi/v2/account，字段为 crossWalletBalance, crossUnrealizedPnl
     */
    private void logAccountBalance() {
        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            Object resp = client.account().accountInformation(params);
            String respStr = resp instanceof String ? (String) resp : resp.toString();

            // Parse balance from response
            JsonNode node = objectMapper.readTree(respStr);

            // USDT-M futures字段：crossWalletBalance, crossUnrealizedPnl
            double balance = 0;
            if (node.has("crossWalletBalance")) {
                balance = node.get("crossWalletBalance").asDouble();
            } else if (node.has("crossUnrealizedPnl")) {
                // 可以用 equity - unrealizedPnl 来推算
                double unrealizedPnl = node.has("crossUnrealizedPnl") ? node.get("crossUnrealizedPnl").asDouble() : 0;
                // 如果有totalEquity可以用它减
                if (node.has("totalCrossUnrealizedPnl")) {
                    // nothing
                }
                balance = unrealizedPnl; // 临时
            } else if (node.has("totalMarginBalance")) {
                balance = node.get("totalMarginBalance").asDouble();
            }

            double unrealizedPnl = 0;
            if (node.has("crossUnrealizedPnl")) {
                unrealizedPnl = node.get("crossUnrealizedPnl").asDouble();
            }

            System.out.printf("[BinanceAdapter] Account balance: %.4f USDT (unrealized PnL: %.4f)%n", balance, unrealizedPnl);

            // Also log positions if any
            if (node.has("positions")) {
                for (JsonNode pos : node.get("positions")) {
                    double amt = pos.has("positionAmt") ? pos.get("positionAmt").asDouble() : 0;
                    if (Math.abs(amt) > 0.0001) {
                        String sym = pos.has("symbol") ? pos.get("symbol").asText() : "";
                        double upnl = pos.has("unrealizedProfit") ? pos.get("unrealizedProfit").asDouble() : 0;
                        System.out.printf("[BinanceAdapter] Existing position: %s amt=%.4f pnl=%.4f%n", sym, amt, upnl);
                    }
                }
            }
        } catch (Exception e) {
            System.out.println("[BinanceAdapter] Balance check failed: " + e.getMessage());
        }
    }

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
            // Sync position from exchange before sending order
            syncPositionsFromExchange();

            // Log account balance to diagnose margin issues
            logAccountBalance();

            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", order.getSymbol());
            params.put("side", order.getSide() == TradeDirection.LONG ? "BUY" : "SELL");

            // Account is in hedge mode (dual-side) - positionSide is required
            // Get current position to determine correct positionSide
            double currentPos = this.currentPosition; // Local cache of position
            String positionSide = null;
            boolean isCloseOrder = false;
            double orderQty = order.getQuantity();

            // Check if this order would exceed available position in same direction
            boolean sameDirectionAsPosition = (currentPos > 0 && order.getSide() == TradeDirection.SHORT) ||
                                              (currentPos < 0 && order.getSide() == TradeDirection.LONG);

            if (order.getSide() == TradeDirection.LONG) {
                if (currentPos < 0) {
                    // Has SHORT position, close it with BUY
                    positionSide = "SHORT";
                    isCloseOrder = true;
                    // Quantity should not exceed the short position we're closing
                    orderQty = Math.min(orderQty, Math.abs(currentPos));
                } else {
                    positionSide = "LONG"; // Opening or adding LONG
                }
            } else if (order.getSide() == TradeDirection.SHORT) {
                if (currentPos > 0) {
                    // Has LONG position, close it with SELL
                    positionSide = "LONG";
                    isCloseOrder = true;
                    // Quantity should not exceed the long position we're closing
                    orderQty = Math.min(orderQty, Math.abs(currentPos));
                } else {
                    // currentPos < 0 (already SHORT) - should not add to short in same direction
                    // This would be adding to existing position which uses more margin
                    if (currentPos < 0) {
                        System.out.printf("[BinanceAdapter] Skipping SHORT order: already have SHORT position %.4f, would exceed margin%n", currentPos);
                        return createRejectedReport(order, "Already have SHORT position, cannot add");
                    }
                    positionSide = "SHORT"; // Opening new SHORT (currentPos == 0)
                }
            } else if (order.getSide() == TradeDirection.CLOSE) {
                // Closing position - use opposite of current position
                positionSide = currentPos > 0 ? "SHORT" : "LONG";
                isCloseOrder = true;
                orderQty = Math.min(orderQty, Math.abs(currentPos));
            }

            if (positionSide != null) {
                params.put("positionSide", positionSide);
            }

            // Map our OrderType to Binance order type
            String binanceType = mapOrderType(order.getOrderType());
            params.put("type", binanceType);
            params.put("quantity", formatQuantity(orderQty));

            // Add type-specific parameters
            if (order.getOrderType() == com.trading.domain.trading.model.OrderType.LIMIT ||
                order.getOrderType() == com.trading.domain.trading.model.OrderType.STOP_LIMIT) {
                params.put("price", formatPrice(order.getPrice()));
                params.put("timeInForce", "GTC");
            }

            // Add reduceOnly for close orders (when closing in One-Way Mode, not Hedge Mode)
            // In Hedge Mode with positionSide, reduceOnly is NOT needed
            if (isCloseOrder && positionSide == null) {
                params.put("reduceOnly", true);
            }

            // Add client order ID for idempotency
            params.put("newClientOrderId", order.getOrderId());

            // Debug: log order parameters
            System.out.printf("[BinanceAdapter] Sending order: symbol=%s, side=%s, type=%s, qty=%s, price=%s%n",
                order.getSymbol(),
                order.getSide() == TradeDirection.LONG ? "BUY" : "SELL",
                binanceType,
                formatQuantity(order.getQuantity()),
                formatPrice(order.getPrice()));

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
            return createRejectedReport(order, e.getMessage());
        }
    }

    private ExecutionReport createRejectedReport(Order order, String reason) {
        System.err.printf("[BinanceAdapter] Order rejected: %s%n", reason);
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

    private String mapOrderType(com.trading.domain.trading.model.OrderType orderType) {
        if (orderType == com.trading.domain.trading.model.OrderType.MARKET) return "MARKET";
        if (orderType == com.trading.domain.trading.model.OrderType.STOP) return "STOP";
        if (orderType == com.trading.domain.trading.model.OrderType.STOP_LIMIT) return "STOP";
        if (orderType == com.trading.domain.trading.model.OrderType.IOC) return "IOC";
        if (orderType == com.trading.domain.trading.model.OrderType.FOK) return "FOK";
        return "LIMIT";
    }

    private String formatQuantity(double qty) {
        // Binance requires quantity precision: round to 3 decimal places (0.001 step)
        // Ensure minimum 0.001 and proper rounding
        if (qty < 0.001) {
            return "0.001"; // Enforce minimum order size
        }
        double rounded = Math.floor(qty * 1000) / 1000.0;
        return String.format("%.3f", rounded);
    }

    private String formatPrice(double price) {
        // Binance requires price precision: 2 decimals for BTCUSDT
        return String.format("%.2f", price);
    }

    private void updateLocalPosition(Order order, double filledQty, double fillPrice) {
        if (filledQty <= 0) return;

        // Phase 2: Only update local position for paper trading
        // For live trading, position is synced ONLY from Binance USER_DATA stream
        if (paperTrading) {
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
                    if (currentPosition < 0) {
                        double totalCost = Math.abs(currentPosition) * avgEntryPrice + filledQty * fillPrice;
                        currentPosition = -(Math.abs(currentPosition) + filledQty);
                        avgEntryPrice = totalCost / Math.abs(currentPosition);
                    }
                    break;
                }
                case CLOSE: {
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
        // For live trading: position is only updated via syncPositionsFromExchange() from USER_DATA
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

            boolean positionFound = false;
            if (node.has("positions")) {
                for (JsonNode pos : node.get("positions")) {
                    String posSymbol = pos.has("symbol") ? pos.get("symbol").asText() : "";
                    if (!posSymbol.equalsIgnoreCase(symbol)) continue;

                    positionFound = true;
                    double posAmt = pos.has("positionAmt") ? pos.get("positionAmt").asDouble() : 0;
                    double entryPrice = pos.has("entryPrice") ? pos.get("entryPrice").asDouble() : 0;
                    double unrealizedPnL = pos.has("unrealizedProfit") ? pos.get("unrealizedProfit").asDouble() : 0;

                    // Always update position (including zero) to ensure cache consistency
                    this.currentPosition = posAmt;
                    this.avgEntryPrice = entryPrice;
                    this.unrealizedPnl = unrealizedPnL;
                    if (Math.abs(posAmt) > 0.0001) {
                        System.out.printf("[BinanceAdapter] Position synced: pos=%.4f, entry=%.2f, unrealizedPnl=%.2f%n",
                            currentPosition, avgEntryPrice, unrealizedPnl);
                    } else {
                        System.out.printf("[BinanceAdapter] Position closed: pos=%.4f%n", currentPosition);
                    }
                }
            }

            // If no position found for our symbol, reset to zero
            if (!positionFound && Math.abs(this.currentPosition) > 0.0001) {
                System.out.printf("[BinanceAdapter] Position reset: was %.4f, now 0%n", this.currentPosition);
                this.currentPosition = 0;
                this.avgEntryPrice = 0;
                this.unrealizedPnl = 0;
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
     * 同步账户余额和持仓信息
     */
    public double syncBalanceFromExchange() {
        if (paperTrading || client == null) return 0.0;

        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            Object resp = client.account().accountInformation(params);
            String respStr = resp instanceof String ? (String) resp : resp.toString();
            JsonNode node = objectMapper.readTree(respStr);

            // Debug: print full response structure
            System.out.println("[BinanceAdapter] Account response sample: " + respStr.substring(0, Math.min(500, respStr.length())));

            // USDT-M futures字段：crossWalletBalance, crossUnrealizedPnl
            double walletBal = 0;
            double availBal = 0;
            double unrealizedPnL = 0;

            if (node.has("crossWalletBalance")) {
                walletBal = node.get("crossWalletBalance").asDouble();
                availBal = walletBal; // 可用余额初值
            }
            if (node.has("crossUnrealizedPnl")) {
                unrealizedPnL = node.get("crossUnrealizedPnl").asDouble();
            }

            // 计算availableBalance：walletBalance - 已用保证金
            double totalEquity = walletBal + unrealizedPnL;
            if (node.has("totalCrossUnrealizedPnl")) {
                // totalEquity 可以直接用
            }

            System.out.printf("[BinanceAdapter] USDT Balance: wallet=%.4f, unrealizedPnl=%.4f, equity=%.4f%n",
                walletBal, unrealizedPnL, totalEquity);

            availableBalance = availBal;
            this.walletBalance = walletBal;

            // Parse positions if any
            if (node.has("positions")) {
                for (JsonNode pos : node.get("positions")) {
                    String posSymbol = pos.has("symbol") ? pos.get("symbol").asText() : "";
                    if (!posSymbol.equalsIgnoreCase(symbol)) continue;

                    double posAmt = pos.has("positionAmt") ? pos.get("positionAmt").asDouble() : 0;
                    double entryPrice = pos.has("entryPrice") ? pos.get("entryPrice").asDouble() : 0;
                    double posUnrealizedPnL = pos.has("unrealizedProfit") ? pos.get("unrealizedProfit").asDouble() : 0;
                    String marginType = pos.has("isolatedMargin") ? "isolated" : "cross";

                    if (Math.abs(posAmt) > 0.0001) {
                        System.out.printf("[BinanceAdapter] Position: %s amt=%.4f entry=%.2f pnl=%.2f marginType=%s%n",
                            posSymbol, posAmt, entryPrice, posUnrealizedPnL, marginType);
                        this.currentPosition = posAmt;
                        this.avgEntryPrice = entryPrice;
                        this.unrealizedPnl = posUnrealizedPnL;
                    }
                }
            }

            System.out.printf("[BinanceAdapter] Balance synced: available=%.4f USDT%n", availableBalance);
            return availableBalance;
        } catch (Exception e) {
            System.err.println("[BinanceAdapter] Balance sync failed: " + e.getMessage());
            e.printStackTrace();
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
     * Get current position state for lifecycle management
     *
     * Note: RiskModel is not available here because we don't have ATR.
     * The RiskModel should be set by PositionSignalManager when creating the position.
     */
    public PositionState getPositionState() {
        // Sync position from exchange before returning state
        if (!paperTrading) {
            syncPositionsFromExchange();
        }

        if (Math.abs(currentPosition) < 0.0001) {
            return PositionState.empty();
        }
        return new PositionState(
            currentPosition,
            avgEntryPrice,
            unrealizedPnl,
            realizedPnl,
            System.currentTimeMillis(), // Entry time unknown from adapter
            unrealizedPnl + walletBalance,
            walletBalance,
            "",
            null,  // RiskModel - set externally
            avgEntryPrice,  // peakPrice
            avgEntryPrice   // lowestPrice
        );
    }

    /**
     * Set RiskModel for the current position
     * Called by PositionSignalManager after creating position with ATR context
     */
    private RiskModel currentRiskModel;

    public void setRiskModel(RiskModel riskModel) {
        this.currentRiskModel = riskModel;
    }

    public RiskModel getRiskModel() {
        return currentRiskModel;
    }

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
