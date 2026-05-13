package com.trading.infrastructure.execution.ws;

import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.TradeDirection;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.InvalidKeyException;
import java.security.NoSuchAlgorithmException;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.TreeMap;
import java.util.UUID;

/**
 * WebSocket API Request Builder (WS-API v3)
 *
 * <p>Builds signed requests for Binance WS-API v3:
 * <ul>
 *   <li>order.place</li>
 *   <li>order.cancel</li>
 *   <li>order.modify</li>
 * </ul>
 *
 * <p>Reuses HMAC-SHA256 signing from BinanceAlgoClient pattern.
 */
public class WsApiRequestBuilder {

    private static final Logger log = LoggerFactory.getLogger(WsApiRequestBuilder.class);

    private final String apiKey;
    private final String apiSecret;
    private final boolean testnet;

    public WsApiRequestBuilder(String apiKey, String apiSecret, boolean testnet) {
        this.apiKey = apiKey;
        this.apiSecret = apiSecret;
        this.testnet = testnet;
    }

    // ========== Order Place ==========

    /**
     * Build order.place request JSON
     */
    public String buildPlaceOrderRequest(Order order, long timestamp) {
        LinkedHashMap<String, Object> params = new LinkedHashMap<>();
        params.put("symbol", order.getSymbol());
        params.put("side", toBinanceSide(order.getSide()));
        params.put("type", toBinanceOrderType(order));
        params.put("quantity", formatQuantity(order.getQuantity()));

        // Optional params based on order type
        if (order.getOrderType() == com.trading.domain.trading.model.OrderType.LIMIT ||
            order.getOrderType() == com.trading.domain.trading.model.OrderType.STOP_LIMIT) {
            params.put("timeInForce", "GTC");
        }

        if (order.getPrice() > 0) {
            params.put("price", formatPrice(order.getPrice()));
        }

        if (order.getStopPrice() > 0) {
            params.put("stopPrice", formatPrice(order.getStopPrice()));
        }

        if (order.isReduceOnly()) {
            params.put("reduceOnly", true);
        }

        if (order.isClosePosition()) {
            params.put("closePosition", true);
        }

        // Mandatory fields
        params.put("timestamp", timestamp);
        params.put("apiKey", apiKey);

        // Sign and build final request
        String signature = signParams(params);
        params.put("signature", signature);

        return buildRequest(UUID.randomUUID().toString(), "order.place", params);
    }

    /**
     * Build order.cancel request JSON
     */
    public String buildCancelOrderRequest(String clientOrderId, long binanceOrderId,
                                          String symbol, long timestamp) {
        LinkedHashMap<String, Object> params = new LinkedHashMap<>();
        params.put("symbol", symbol);
        params.put("orderId", binanceOrderId);
        params.put("timestamp", timestamp);
        params.put("apiKey", apiKey);

        String signature = signParams(params);
        params.put("signature", signature);

        return buildRequest(UUID.randomUUID().toString(), "order.cancel", params);
    }

    /**
     * Build order.modify request JSON
     */
    public String buildModifyOrderRequest(String clientOrderId, long binanceOrderId,
                                         String symbol, double newPrice, double newQty,
                                         long timestamp) {
        LinkedHashMap<String, Object> params = new LinkedHashMap<>();
        params.put("symbol", symbol);
        params.put("orderId", binanceOrderId);
        params.put("price", formatPrice(newPrice));
        params.put("quantity", formatQuantity(newQty));
        params.put("timestamp", timestamp);
        params.put("apiKey", apiKey);

        String signature = signParams(params);
        params.put("signature", signature);

        return buildRequest(UUID.randomUUID().toString(), "order.modify", params);
    }

    /**
     * Build ping request (for connectivity test)
     */
    public String buildPingRequest() {
        return buildRequest(UUID.randomUUID().toString(), "ping", null);
    }

    /**
     * Build request JSON from method and params
     */
    private String buildRequest(String id, String method, LinkedHashMap<String, Object> params) {
        StringBuilder json = new StringBuilder();
        json.append("{\"id\":\"").append(id).append("\",\"method\":\"").append(method).append("\"");

        if (params != null && !params.isEmpty()) {
            json.append(",\"params\":{");
            boolean first = true;
            for (Map.Entry<String, Object> entry : params.entrySet()) {
                if (!first) json.append(",");
                json.append("\"").append(entry.getKey()).append("\":");

                Object value = entry.getValue();
                if (value instanceof Boolean) {
                    json.append(value.toString());
                } else if (value instanceof Number) {
                    json.append(value);
                } else {
                    json.append("\"").append(value).append("\"");
                }
                first = false;
            }
            json.append("}");
        } else {
            json.append(",\"params\":{}");
        }

        json.append("}");
        return json.toString();
    }

    // ========== Signature ==========

    /**
     * Sign params with HMAC-SHA256 (same as BinanceAlgoClient)
     */
    public String signParams(Map<String, Object> params) {
        // Build query string in sorted order
        TreeMap<String, Object> sorted = new TreeMap<>(params);
        StringBuilder sb = new StringBuilder();
        for (Map.Entry<String, Object> entry : sorted.entrySet()) {
            if (sb.length() > 0) sb.append("&");
            sb.append(entry.getKey()).append("=").append(entry.getValue());
        }

        log.debug("[WsApi] Signing string (sorted): {}", sb);

        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            SecretKeySpec secretKey = new SecretKeySpec(
                    apiSecret.getBytes(StandardCharsets.UTF_8), "HmacSHA256");
            mac.init(secretKey);
            byte[] hmac = mac.doFinal(sb.toString().getBytes(StandardCharsets.UTF_8));

            StringBuilder hex = new StringBuilder();
            for (byte b : hmac) {
                hex.append(String.format("%02x", b));
            }
            return hex.toString();
        } catch (NoSuchAlgorithmException | InvalidKeyException e) {
            throw new RuntimeException("Failed to sign WS-API request", e);
        }
    }

    // ========== Helpers ==========

    private String toBinanceSide(TradeDirection side) {
        return side == TradeDirection.LONG ? "BUY" : "SELL";
    }

    private String toBinanceOrderType(Order order) {
        switch (order.getOrderType()) {
            case MARKET: return "MARKET";
            case LIMIT: return "LIMIT";
            case STOP_MARKET: return "STOP_MARKET";
            case STOP_LIMIT: return "STOP_LIMIT";
            case STOP: return "STOP_MARKET";
            case IOC: return "IOC";
            case FOK: return "FOK";
            default: return "LIMIT";
        }
    }

    private String formatQuantity(double qty) {
        // Format with appropriate precision
        if (qty >= 1) {
            return String.format("%.4f", qty);
        } else if (qty >= 0.01) {
            return String.format("%.4f", qty);
        } else {
            return String.format("%.6f", qty);
        }
    }

    private String formatPrice(double price) {
        if (price >= 10000) {
            return String.format("%.2f", price);
        } else if (price >= 100) {
            return String.format("%.4f", price);
        } else {
            return String.format("%.6f", price);
        }
    }

    public String getApiKey() {
        return apiKey;
    }

    public boolean isTestnet() {
        return testnet;
    }
}