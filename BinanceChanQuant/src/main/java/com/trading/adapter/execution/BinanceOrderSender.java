package com.trading.adapter.execution;

import com.binance.connector.futures.client.impl.UMFuturesClientImpl;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.trading.config.ConfigUtil;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.OrderStatus;
import com.trading.domain.trading.model.TradeDirection;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.net.InetSocketAddress;
import java.net.Proxy;
import java.util.LinkedHashMap;

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

    // Position mode detection
    private volatile BinanceExchangeAdapter.PositionMode positionMode =
            BinanceExchangeAdapter.PositionMode.ONE_WAY;

    // Current position (for close order detection)
    private volatile double currentPosition = 0.0;

    public BinanceOrderSender(String symbol, boolean paperTrading,
                              String apiKey, String apiSecret,
                              UMFuturesClientImpl client) {
        this.symbol = symbol;
        this.paperTrading = paperTrading;
        this.apiKey = apiKey;
        this.apiSecret = apiSecret;
        this.client = client;
    }

    public void setPositionMode(BinanceExchangeAdapter.PositionMode mode) {
        this.positionMode = mode;
    }

    public void setCurrentPosition(double position) {
        this.currentPosition = position;
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
            0.0
        );
    }

    private ExecutionReport sendLiveOrder(Order order) {
        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", order.getSymbol());
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
                if (currentPosition < 0) {
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

                if (positionSide != null) {
                    params.put("positionSide", positionSide);
                }
            }

            // Order type mapping
            String binanceType = mapOrderType(order.getOrderType());
            params.put("type", binanceType);
            params.put("quantity", formatQuantity(orderQty));

            // Type-specific parameters
            if (order.getOrderType() == com.trading.domain.trading.model.OrderType.LIMIT ||
                order.getOrderType() == com.trading.domain.trading.model.OrderType.STOP_LIMIT) {
                params.put("price", formatPrice(order.getPrice()));
                params.put("timeInForce", "GTC");
            } else if (order.getOrderType() == com.trading.domain.trading.model.OrderType.IOC) {
                params.put("price", formatPrice(order.getPrice()));
                params.put("timeInForce", "IOC");
            } else if (order.getOrderType() == com.trading.domain.trading.model.OrderType.FOK) {
                params.put("price", formatPrice(order.getPrice()));
                params.put("timeInForce", "FOK");
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
                0.0
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
                0.0
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
            reason
        );
    }

    private String mapOrderType(com.trading.domain.trading.model.OrderType type) {
        // Java 11 compatible
        if (type == com.trading.domain.trading.model.OrderType.MARKET) {
            return "MARKET";
        } else if (type == com.trading.domain.trading.model.OrderType.STOP) {
            return "STOP";
        } else if (type == com.trading.domain.trading.model.OrderType.STOP_LIMIT) {
            return "STOP_MARKET";
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