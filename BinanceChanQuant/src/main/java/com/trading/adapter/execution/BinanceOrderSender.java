package com.trading.adapter.execution;

import com.binance.connector.futures.client.impl.UMFuturesClientImpl;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.trading.config.ConfigUtil;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.OrderIntent;
import com.trading.domain.trading.model.BinanceExecutionSpec;
import com.trading.domain.trading.model.OrderStatus;
import com.trading.domain.trading.model.TradeDirection;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.net.InetSocketAddress;
import java.net.Proxy;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Binance Order Sender
 *
 * <p>Handles all order operations to Binance:
 * <ul>
 *   <li>sendOrder - Place new orders</li>
 *   <li>cancelOrder - Cancel existing orders</li>
 *   <li>queryOrder - Query order status</li>
 * </ul>
 *
 * <p>Supports both One-Way and Hedge position modes.
 */
public class BinanceOrderSender {

    private static final Logger log = LoggerFactory.getLogger(BinanceOrderSender.class);

    private final String symbol;
    private final boolean paperTrading;
    private final UMFuturesClientImpl client;
    private final ObjectMapper objectMapper = new ObjectMapper();
    private final String apiKey;
    private final String apiSecret;
    private final Proxy proxy; // For algo order queries

    // Position mode detection
    private volatile BinanceExchangeAdapter.PositionMode positionMode =
            BinanceExchangeAdapter.PositionMode.ONE_WAY;

    // Current position snapshot (immutable, set at construction time)
    private final double currentPosition;

    public BinanceOrderSender(String symbol, boolean paperTrading,
                              String apiKey, String apiSecret,
                              UMFuturesClientImpl client) {
        this(symbol, paperTrading, apiKey, apiSecret, client, Proxy.NO_PROXY);
    }

    public BinanceOrderSender(String symbol, boolean paperTrading,
                              String apiKey, String apiSecret,
                              UMFuturesClientImpl client,
                              Proxy proxy) {
        this.symbol = symbol;
        this.paperTrading = paperTrading;
        this.apiKey = apiKey;
        this.apiSecret = apiSecret;
        this.client = client;
        this.proxy = proxy;
        this.currentPosition = 0.0; // Default
    }

    public BinanceOrderSender(String symbol, boolean paperTrading,
                              String apiKey, String apiSecret,
                              UMFuturesClientImpl client,
                              PositionSnapshot positionSnapshot,
                              Proxy proxy) {
        this.symbol = symbol;
        this.paperTrading = paperTrading;
        this.apiKey = apiKey;
        this.apiSecret = apiSecret;
        this.client = client;
        this.proxy = proxy;
        this.currentPosition = positionSnapshot != null ? positionSnapshot.getPosition() : 0.0;
    }

    public BinanceOrderSender(String symbol, boolean paperTrading,
                              String apiKey, String apiSecret,
                              UMFuturesClientImpl client,
                              PositionSnapshot positionSnapshot) {
        this(symbol, paperTrading, apiKey, apiSecret, client, positionSnapshot, Proxy.NO_PROXY);
    }

    public void setPositionMode(BinanceExchangeAdapter.PositionMode mode) {
        this.positionMode = mode;
    }

    @Deprecated
    public void setCurrentPosition(double position) {
        // Deprecated: position is now set via constructor with PositionSnapshot
    }

    public void setPositionSnapshot(PositionSnapshot snapshot) {
        // Deprecated: position is now set via constructor
    }

    // ========== Order Operations ==========

    /**
     * Send order to Binance (or simulate in paper mode)
     */
    public ExecutionReport sendOrder(Order order) {
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
            log.info("[OrderSender] Cancel (paper): {}", orderId);
            return true;
        }

        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", symbol);
            params.put("orderId", binanceOrderId);

            Object resp = client.account().cancelOrder(params);
            log.info("[OrderSender] Cancel: {} -> {}", orderId, resp);
            return true;
        } catch (Exception e) {
            log.error("[OrderSender] Cancel failed: {}", e.getMessage());
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
            log.info("[OrderSender] QueryOrder: {} -> {}", orderId, resp);

            return parseQueryResponse(orderId, resp);
        } catch (Exception e) {
            log.error("[OrderSender] Query failed: {}", e.getMessage());
            return null;
        }
    }

    /**
     * Query all open orders from Binance
     * Uses accountInformation endpoint which returns openOrders field
     */
    public List<Order> queryAllOpenOrders() {
        if (paperTrading) {
            return new java.util.ArrayList<>();
        }

        try {
            log.info("[OrderSender] Querying open orders from exchange");
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            Object resp = client.account().accountInformation(params);
            String respStr = resp instanceof String ? (String) resp : resp.toString();

            JsonNode root = objectMapper.readTree(respStr);
            List<Order> openOrders = new ArrayList<>();

            // Parse regular open orders
            if (root.has("openOrders") && root.get("openOrders").isArray()) {
                JsonNode ordersNode = root.get("openOrders");
                for (JsonNode node : ordersNode) {
                    try {
                        Order order = parseOpenOrder(node);
                        if (order != null) {
                            openOrders.add(order);
                        }
                    } catch (Exception e) {
                        log.warn("[OrderSender] Failed to parse open order: {}", e.getMessage());
                    }
                }
            }

            // Also query algo orders (STOP_MARKET with closePosition) - they use separate API
            try {
                List<Order> algoOrders = queryAlgoOpenOrders();
                if (algoOrders != null) {
                    openOrders.addAll(algoOrders);
                }
            } catch (Exception e) {
                log.warn("[OrderSender] Failed to query algo orders: {}", e.getMessage());
            }

            log.info("[OrderSender] Found {} total open orders", openOrders.size());
            return openOrders;
        } catch (Exception e) {
            log.error("[OrderSender] Query open orders failed: {}", e.getMessage());
            return new java.util.ArrayList<>();
        }
    }

    private Order parseOpenOrder(JsonNode node) {
        String orderId = node.has("orderId") ? node.get("orderId").asText() : null;
        String symbol = node.has("symbol") ? node.get("symbol").asText() : null;
        if (symbol == null || orderId == null) {
            return null;
        }

        String sideStr = node.has("side") ? node.get("side").asText() : "BUY";
        TradeDirection side = "SELL".equalsIgnoreCase(sideStr) ? TradeDirection.SHORT : TradeDirection.LONG;

        String typeStr = node.has("type") ? node.get("type").asText() : "LIMIT";
        com.trading.domain.trading.model.OrderType type = mapOrderType(typeStr);

        double qty = node.has("origQty") ? node.get("origQty").asDouble() : 0;
        double price = node.has("price") ? node.get("price").asDouble() : 0;
        double stopPrice = node.has("stopPrice") ? node.get("stopPrice").asDouble() : 0;

        // Check if this is our order by newClientOrderId
        String clientOrderId = node.has("newClientOrderId") ? node.get("newClientOrderId").asText() : null;
        String finalOrderId = orderId;
        if (clientOrderId != null && !clientOrderId.isEmpty()) {
            // Use our client order ID for validateOwnership
            finalOrderId = clientOrderId;
        }

        Order order = new Order(
            finalOrderId,  // Use clientOrderId if ours, otherwise use exchange orderId
            symbol,
            side,
            type,
            qty,
            price,
            "recovery",
            1.0
        );
        order.setStopPrice(stopPrice);

        // Set closePosition if it's a closing order
        String reduceOnly = node.has("reduceOnly") ? node.get("reduceOnly").asText() : "false";
        order.setReduceOnly("true".equalsIgnoreCase(reduceOnly));

        return order;
    }

    private com.trading.domain.trading.model.OrderType mapOrderType(String typeStr) {
        switch (typeStr.toUpperCase()) {
            case "LIMIT": return com.trading.domain.trading.model.OrderType.LIMIT;
            case "MARKET": return com.trading.domain.trading.model.OrderType.MARKET;
            case "STOP": return com.trading.domain.trading.model.OrderType.STOP;
            case "STOP_MARKET": return com.trading.domain.trading.model.OrderType.STOP_MARKET;
            case "STOP_LOSS_LIMIT": return com.trading.domain.trading.model.OrderType.STOP_LIMIT;
            default: return com.trading.domain.trading.model.OrderType.LIMIT;
        }
    }

    /**
     * Query open algo orders (conditional orders like STOP_MARKET with closePosition)
     * These are stored separately and not returned by accountInformation
     */
    private List<Order> queryAlgoOpenOrders() {
        List<Order> algoOrders = new ArrayList<>();
        try {
            // Query current algo orders using GET /fapi/v1/algo/orders
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", symbol);
            params.put("timestamp", System.currentTimeMillis());

            String queryStr = "";
            for (Map.Entry<String, Object> e : params.entrySet()) {
                if (!queryStr.isEmpty()) queryStr += "&";
                queryStr += e.getKey() + "=" + e.getValue();
            }

            // Sign the query (hex format to match Binance's expected signature)
            javax.crypto.Mac mac = javax.crypto.Mac.getInstance("HmacSHA256");
            javax.crypto.spec.SecretKeySpec secretKeySpec = new javax.crypto.spec.SecretKeySpec(apiSecret.getBytes(), "HmacSHA256");
            mac.init(secretKeySpec);
            byte[] hmac = mac.doFinal(queryStr.getBytes());
            StringBuilder hex = new StringBuilder();
            for (byte b : hmac) {
                hex.append(String.format("%02x", b));
            }
            String signature = hex.toString();

            String url = (ConfigUtil.isTestNet() ? "https://testnet.binancefuture.com" : "https://fapi.binance.com")
                    + "/fapi/v1/openAlgoOrders?symbol=" + symbol + "&timestamp=" + params.get("timestamp") + "&signature=" + signature;

            java.net.URL urlObj = new java.net.URL(url);
            java.net.HttpURLConnection conn = (java.net.HttpURLConnection) urlObj.openConnection(proxy);
            conn.setRequestMethod("GET");
            conn.setRequestProperty("X-MBX-APIKEY", apiKey);
            conn.setConnectTimeout(10000);
            conn.setReadTimeout(10000);

            StringBuilder response = new StringBuilder();
            try (java.io.BufferedReader br = new java.io.BufferedReader(new java.io.InputStreamReader(conn.getInputStream()))) {
                String line;
                while ((line = br.readLine()) != null) {
                    response.append(line);
                }
            }

            String respStr = response.toString();
            JsonNode root = objectMapper.readTree(respStr);

            if (root.isArray()) {
                for (JsonNode node : root) {
                    try {
                        Order order = parseAlgoOrder(node);
                        if (order != null) {
                            algoOrders.add(order);
                        }
                    } catch (Exception e) {
                        log.warn("[OrderSender] Failed to parse algo order: {}", e.getMessage());
                    }
                }
            }
            log.info("[OrderSender] Found {} algo open orders", algoOrders.size());
        } catch (java.net.SocketTimeoutException e) {
            log.warn("[OrderSender] queryAlgoOpenOrders timed out (proxy may be blocking): {}", e.getMessage());
        } catch (java.io.IOException e) {
            log.warn("[OrderSender] queryAlgoOpenOrders IO error (check proxy): {} - {}", e.getClass().getSimpleName(), e.getMessage());
        } catch (Exception e) {
            log.warn("[OrderSender] queryAlgoOpenOrders failed: {} - {}", e.getClass().getSimpleName(), e.getMessage());
        }
        return algoOrders;
    }

    private Order parseAlgoOrder(JsonNode node) {
        String algoId = node.has("algoId") ? node.get("algoId").asText() : null;
        String symbol = node.has("symbol") ? node.get("symbol").asText() : null;
        if (symbol == null || algoId == null) {
            return null;
        }

        String sideStr = node.has("side") ? node.get("side").asText() : "BUY";
        TradeDirection side = "SELL".equalsIgnoreCase(sideStr) ? TradeDirection.SHORT : TradeDirection.LONG;

        // Algo orders are typically STOP_MARKET or TAKE_PROFIT_MARKET
        com.trading.domain.trading.model.OrderType type = com.trading.domain.trading.model.OrderType.STOP_MARKET;

        double qty = node.has("qty") ? node.get("qty").asDouble() : 0;
        double triggerPrice = node.has("triggerPrice") ? node.get("triggerPrice").asDouble() : 0;

        // Algo orders use clientAlgoId
        String clientOrderId = node.has("clientAlgoId") ? node.get("clientAlgoId").asText() : "algo-" + algoId;

        Order order = new Order(
            clientOrderId,
            symbol,
            side,
            type,
            qty,
            0, // No price for STOP_MARKET
            "algo",
            1.0
        );
        order.setStopPrice(triggerPrice);
        order.setReduceOnly(true); // Algo orders with closePosition are reduceOnly

        return order;
    }

    // ========== Internal Methods ==========

    private ExecutionReport simulateFill(Order order) {
        log.info("[OrderSender] Paper fill: {} {} {} @ {}",
                order.getSide(), order.getOrderType(), order.getQuantity(), order.getPrice());

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
            0.0,
            (String) null
        );
    }

    private ExecutionReport sendLiveOrder(Order order) {
        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", order.getSymbol());

            // P1: Use explicit intent if available (preferred path)
            // Legacy orders without intent will fall back to position inference
            if (order.hasIntent()) {
                return sendOrderWithIntent(order, order.getIntent(), params);
            }

            // Legacy fallback: infer from currentPosition + side
            // WARNING: This path has position synchronization issues
            log.warn("[OrderSender] LEGACY_ORDER_WITHOUT_INTENT: orderId={}, side={}",
                    order.getOrderId(), order.getSide());

            // Fallback logic below...
            params.put("side", order.getSide() == TradeDirection.LONG ? "BUY" : "SELL");

            // Position handling
            String positionSide = null;
            boolean isCloseOrder = false;
            double orderQty = order.getQuantity();

            if (positionMode == BinanceExchangeAdapter.PositionMode.ONE_WAY) {
                // ONE-WAY MODE
                if (currentPosition > 0 && order.getSide() == TradeDirection.SHORT) {
                    isCloseOrder = true;
                    orderQty = Math.min(orderQty, Math.abs(currentPosition));
                } else if (currentPosition < 0 && order.getSide() == TradeDirection.LONG) {
                    isCloseOrder = true;
                    orderQty = Math.min(orderQty, Math.abs(currentPosition));
                }
                if (isCloseOrder) {
                    params.put("reduceOnly", true);
                }
            } else {
                // HEDGE MODE
                // P0 fix: reduceOnly STOP_MARKET - do NOT set positionSide
                // reduceOnly orders only need side + type + stopPrice + reduceOnly
                // P0 FIX: isClosePosition() must be checked BEFORE currentPosition
                // If order is marked as closePosition, derive positionSide from order direction
                // (currentPosition may be 0 due to sync failure, but exchange still has the position)
                if (order.isClosePosition()) {
                    // Close position order: positionSide is OPPOSITE of order side
                    // LONG order closes SHORT position, SHORT order closes LONG position
                    positionSide = order.getSide() == TradeDirection.LONG ? "SHORT" : "LONG";
                    isCloseOrder = true;
                    orderQty = Math.min(orderQty, Math.abs(currentPosition > 0 ? currentPosition : 1)); // Use at least 1 contract if position exists
                    log.info("[OrderSender] closePosition=true: derived positionSide={}", positionSide);
                } else if (order.isReduceOnly()) {
                    // Emergency stop: only side and reduceOnly flag needed
                    log.info("[OrderSender] reduceOnly STOP_MARKET: skipping positionSide");
                } else if (currentPosition < 0) {
                    if (order.getSide() == TradeDirection.LONG) {
                        positionSide = "SHORT";
                        orderQty = Math.min(orderQty, Math.abs(currentPosition));
                        isCloseOrder = true;
                    } else if (order.getSide() == TradeDirection.SHORT) {
                        log.info("[OrderSender] Skipping SHORT: already have SHORT {}", currentPosition);
                        return createRejectedReport(order, "Already have SHORT position");
                    }
                } else if (currentPosition > 0) {
                    if (order.getSide() == TradeDirection.SHORT) {
                        positionSide = "LONG";
                        orderQty = Math.min(orderQty, Math.abs(currentPosition));
                        isCloseOrder = true;
                    } else if (order.getSide() == TradeDirection.LONG) {
                        log.info("[OrderSender] Skipping LONG: already have LONG {}", currentPosition);
                        return createRejectedReport(order, "Already have LONG position");
                    }
                } else {
                    // No position - opening new
                    positionSide = order.getSide() == TradeDirection.LONG ? "LONG" : "SHORT";
                }

                if (positionSide != null && !order.isClosePosition() && !order.isReduceOnly()) {
                    params.put("positionSide", positionSide);
                }
                // P0 FIX: For HEDGE mode close orders, also set reduceOnly=true
                if (isCloseOrder) {
                    params.put("reduceOnly", true);
                }
            }

            // Order type mapping
            String binanceType = mapOrderType(order.getOrderType());
            params.put("type", binanceType);
            params.put("quantity", formatQuantity(orderQty));

            // Type-specific parameters
            if (order.getOrderType() == com.trading.domain.trading.model.OrderType.LIMIT) {
                params.put("price", formatPrice(order.getPrice()));
                params.put("timeInForce", "GTC");
            } else if (order.getOrderType() == com.trading.domain.trading.model.OrderType.STOP_LIMIT) {
                // STOP_LIMIT maps to STOP_MARKET in Binance
                // P0 fix: closePosition=true requires stopPrice and NO positionSide
                double stopPrice = order.getStopPrice();
                if (stopPrice > 0) {
                    params.put("stopPrice", formatPrice(stopPrice));
                }
                // Emergency stop uses closePosition=true to close entire position
                if (order.isClosePosition()) {
                    params.put("closePosition", true);
                    // Do NOT set positionSide with closePosition - it's invalid
                }
            } else if (order.getOrderType() == com.trading.domain.trading.model.OrderType.IOC) {
                params.put("price", formatPrice(order.getPrice()));
                params.put("timeInForce", "IOC");
            } else if (order.getOrderType() == com.trading.domain.trading.model.OrderType.FOK) {
                params.put("price", formatPrice(order.getPrice()));
                params.put("timeInForce", "FOK");
            } else if (order.getOrderType() == com.trading.domain.trading.model.OrderType.STOP_MARKET) {
                // STOP_MARKET: triggers MARKET when stopPrice triggered
                // Used for emergency stop - closePosition=true to close entire position
                double stopPrice = order.getStopPrice();
                if (stopPrice > 0) {
                    params.put("stopPrice", formatPrice(stopPrice));
                }
                if (order.isClosePosition()) {
                    params.put("closePosition", true);
                } else if (order.isReduceOnly()) {
                    params.put("reduceOnly", true);
                }
            } else if (order.getOrderType() == com.trading.domain.trading.model.OrderType.STOP) {
                // STOP order needs stopPrice
                double stopPrice = order.getStopPrice();
                if (stopPrice > 0) {
                    params.put("stopPrice", formatPrice(stopPrice));
                }
                // STOP orders can use closePosition=true to close entire position
                // This is preferred over reduceOnly+qty for survival layer
                // P0 fix: closePosition=true requires NO positionSide in hedge mode
                if (order.isClosePosition()) {
                    params.put("closePosition", true);
                    // In hedge mode, closePosition=true means close entire position
                    // Do NOT set positionSide when closePosition=true - it's invalid
                } else if (order.isReduceOnly()) {
                    params.put("reduceOnly", true);
                }
            }

            params.put("newClientOrderId", order.getOrderId());

            log.info("[OrderSender] Sending: {} {} {} @ {} posMode={} posSide={} reduceOnly={}",
                    order.getSide(), binanceType, formatQuantity(orderQty),
                    formatPrice(order.getPrice()), positionMode, positionSide, isCloseOrder);

            Object resp = client.account().newOrder(params);

            // Parse response
            long binanceOrderId = 0;
            double filledQty = 0;
            double avgFillPrice = 0;
            String status = "NEW";

            String respStr = resp instanceof String ? (String) resp : resp.toString();
            JsonNode respNode = objectMapper.readTree(respStr);

            if (respNode.has("orderId")) {
                binanceOrderId = respNode.get("orderId").asLong();
            }
            if (respNode.has("executedQty")) {
                filledQty = respNode.get("executedQty").asDouble();
            }
            if (respNode.has("avgPrice")) {
                avgFillPrice = respNode.get("avgPrice").asDouble();
            }
            if (respNode.has("status")) {
                status = respNode.get("status").asText();
            }

            String exchangeId = String.valueOf(binanceOrderId);
            return new ExecutionReport(
                order.getOrderId(),
                order.getSymbol(),
                order.getSide(),
                order.getOrderType(),
                order.getQuantity(),
                order.getPrice(),
                filledQty,
                avgFillPrice,
                parseStatus(status),
                System.currentTimeMillis(),
                binanceOrderId,
                0.0,
                exchangeId
            );

        } catch (Exception e) {
            log.error("[OrderSender] Send failed: {}", e.getMessage());
            return createRejectedReport(order, e.getMessage());
        }
    }

    private ExecutionReport parseQueryResponse(String orderId, Object resp) {
        try {
            String respStr = resp instanceof String ? (String) resp : resp.toString();
            JsonNode node = objectMapper.readTree(respStr);

            long binanceOrderId = node.has("orderId") ? node.get("orderId").asLong() : 0;
            double filledQty = node.has("executedQty") ? node.get("executedQty").asDouble() : 0;
            double avgPrice = node.has("avgPrice") ? node.get("avgPrice").asDouble() : 0;
            String status = node.has("status") ? node.get("status").asText() : "UNKNOWN";

            return new ExecutionReport(
                orderId,
                symbol,
                TradeDirection.NEUTRAL,
                com.trading.domain.trading.model.OrderType.LIMIT,
                0, 0, filledQty, avgPrice,
                parseStatus(status),
                System.currentTimeMillis(),
                binanceOrderId,
                0.0,
                String.valueOf(binanceOrderId)
            );
        } catch (Exception e) {
            log.error("[OrderSender] Parse query response failed: {}", e.getMessage());
            return null;
        }
    }

    private ExecutionReport createRejectedReport(Order order, String reason) {
        return new ExecutionReport(
            order.getOrderId(),
            order.getSymbol(),
            order.getSide(),
            order.getOrderType(),
            order.getQuantity(),
            order.getPrice(),
            0, 0,
            OrderStatus.REJECTED,
            System.currentTimeMillis(),
            0, 0,
            0.0, 0L,
            reason,
            (String) null
        );
    }

    /**
     * P1: Send order with explicit OrderIntent.
     * This is the preferred path - no position inference needed.
     *
     * Mapping table (single source of truth):
     * | Intent        | side | positionSide | reduceOnly |
     * |---------------|------|--------------|------------|
     * | OPEN_LONG     | BUY  | LONG         | false      |
     * | CLOSE_LONG    | SELL | LONG         | true       |
     * | OPEN_SHORT    | SELL | SHORT        | false      |
     * | CLOSE_SHORT   | BUY  | SHORT        | true       |
     */
    private ExecutionReport sendOrderWithIntent(Order order, OrderIntent intent,
                                                  LinkedHashMap<String, Object> params) {
        // P1: Use BinanceExecutionSpec as SINGLE source of truth for Binance parameters
        BinanceExecutionSpec spec = BinanceExecutionSpec.from(intent);

        // Set side from spec (not order.getSide())
        params.put("side", spec.side());

        // Set quantity
        double orderQty = order.getQuantity();

        // For closing orders, reduceOnly=true
        if (spec.reduceOnly()) {
            params.put("reduceOnly", true);

            // In hedge mode, set positionSide for reduceOnly to work correctly
            if (positionMode == BinanceExchangeAdapter.PositionMode.HEDGE) {
                params.put("positionSide", spec.positionSide());
            }

            log.info("[OrderSender] INTENT_CLOSE: {} -> spec={}", intent, spec);
        } else {
            // Opening orders - positionSide needed in hedge mode
            if (positionMode == BinanceExchangeAdapter.PositionMode.HEDGE) {
                params.put("positionSide", spec.positionSide());
            }
        }

        // Order type mapping
        String binanceType = mapOrderType(order.getOrderType());
        params.put("type", binanceType);
        params.put("quantity", formatQuantity(orderQty));

        // Handle order-type specific params (same as legacy)
        addOrderTypeParams(order, params);

        params.put("newClientOrderId", order.getOrderId());

        log.info("[OrderSender] Sending with INTENT: {} {} {} @ {} posMode={} {}",
                intent, binanceType, formatQuantity(orderQty),
                formatPrice(order.getPrice()), positionMode, spec);

        try {
            Object resp = client.account().newOrder(params);

            // Parse response (same as legacy path)
            long binanceOrderId = 0;
            double filledQty = 0;
            double avgFillPrice = 0;
            String status = "NEW";

            String respStr = resp instanceof String ? (String) resp : resp.toString();
            JsonNode respNode = objectMapper.readTree(respStr);

            if (respNode.has("orderId")) {
                binanceOrderId = respNode.get("orderId").asLong();
            }
            if (respNode.has("executedQty")) {
                filledQty = respNode.get("executedQty").asDouble();
            }
            if (respNode.has("avgPrice")) {
                avgFillPrice = respNode.get("avgPrice").asDouble();
            }
            if (respNode.has("status")) {
                status = respNode.get("status").asText();
            }

            String exchangeId = String.valueOf(binanceOrderId);
            return new ExecutionReport(
                order.getOrderId(),
                order.getSymbol(),
                order.getSide(),
                order.getOrderType(),
                order.getQuantity(),
                order.getPrice(),
                filledQty,
                avgFillPrice,
                parseStatus(status),
                System.currentTimeMillis(),
                binanceOrderId,
                0.0,
                exchangeId
            );
        } catch (Exception e) {
            log.error("[OrderSender] sendOrderWithIntent failed: {}", e.getMessage());
            return createRejectedReport(order, e.getMessage());
        }
    }

    private void addOrderTypeParams(Order order, LinkedHashMap<String, Object> params) {
        if (order.getOrderType() == com.trading.domain.trading.model.OrderType.LIMIT) {
            params.put("price", formatPrice(order.getPrice()));
            params.put("timeInForce", "GTC");
        } else if (order.getOrderType() == com.trading.domain.trading.model.OrderType.STOP_LIMIT) {
            double stopPrice = order.getStopPrice();
            if (stopPrice > 0) {
                params.put("stopPrice", formatPrice(stopPrice));
            }
            if (order.isClosePosition()) {
                params.put("closePosition", true);
            }
        } else if (order.getOrderType() == com.trading.domain.trading.model.OrderType.STOP_MARKET) {
            double stopPrice = order.getStopPrice();
            if (stopPrice > 0) {
                params.put("stopPrice", formatPrice(stopPrice));
            }
            if (order.isClosePosition()) {
                params.put("closePosition", true);
            } else if (order.isReduceOnly()) {
                params.put("reduceOnly", true);
            }
        } else if (order.getOrderType() == com.trading.domain.trading.model.OrderType.STOP) {
            double stopPrice = order.getStopPrice();
            if (stopPrice > 0) {
                params.put("stopPrice", formatPrice(stopPrice));
            }
            if (order.isClosePosition()) {
                params.put("closePosition", true);
            } else if (order.isReduceOnly()) {
                params.put("reduceOnly", true);
            }
        }
    }

    private String mapOrderType(com.trading.domain.trading.model.OrderType type) {
        // Java 11 compatible
        if (type == com.trading.domain.trading.model.OrderType.MARKET) {
            return "MARKET";
        } else if (type == com.trading.domain.trading.model.OrderType.STOP) {
            return "STOP";
        } else if (type == com.trading.domain.trading.model.OrderType.STOP_MARKET) {
            return "STOP_MARKET";
        } else if (type == com.trading.domain.trading.model.OrderType.STOP_LIMIT) {
            return "STOP_LIMIT";
        } else {
            return "LIMIT";
        }
    }

    private String formatQuantity(double qty) {
        if (qty >= 1) {
            return String.format("%.0f", qty);
        } else if (qty >= 0.01) {
            return String.format("%.2f", qty);
        } else {
            return String.format("%.3f", qty);  // BTCUSDT: 3 decimal precision
        }
    }

    private String formatPrice(double price) {
        if (price >= 10000) {
            return String.format("%.0f", price);
        } else if (price >= 100) {
            return String.format("%.1f", price);
        } else if (price >= 1) {
            return String.format("%.2f", price);
        } else {
            return String.format("%.4f", price);
        }
    }

    private OrderStatus parseStatus(String binanceStatus) {
        // Java 11 compatible
        if ("NEW".equals(binanceStatus)) {
            return OrderStatus.NEW;
        } else if ("FILLED".equals(binanceStatus)) {
            return OrderStatus.FILLED;
        } else if ("PARTIALLY_FILLED".equals(binanceStatus)) {
            return OrderStatus.PARTIALLY_FILLED;
        } else if ("CANCELED".equals(binanceStatus)) {
            return OrderStatus.CANCELLED;
        } else if ("REJECTED".equals(binanceStatus)) {
            return OrderStatus.REJECTED;
        } else if ("EXPIRED".equals(binanceStatus)) {
            return OrderStatus.EXPIRED;
        }
        return OrderStatus.NEW;
    }
}