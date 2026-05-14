package com.trading.infrastructure.execution.ws;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.OrderStatus;
import com.trading.domain.trading.model.TradeDirection;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.List;

/**
 * WebSocket API Response Parser (WS-API v3)
 *
 * <p>Parses responses from Binance WS-API v3:
 * <ul>
 *   <li>order.place response</li>
 *   <li>order.cancel response</li>
 *   <li>order.modify response</li>
 *   <li>Error responses</li>
 * </ul>
 *
 * <p>Response format:
 * <pre>
 * {
 *   "id": "uuid",
 *   "status": 200,
 *   "result": {...},
 *   "rateLimits": [...]
 * }
 * </pre>
 */
public class WsApiResponseParser {

    private static final Logger log = LoggerFactory.getLogger(WsApiResponseParser.class);

    private final ObjectMapper objectMapper;

    public WsApiResponseParser() {
        this.objectMapper = new ObjectMapper();
    }

    /**
     * Parse order.place response
     */
    public ExecutionReport parsePlaceOrderResponse(String clientOrderId, JsonNode response) {
        try {
            int status = response.has("status") ? response.get("status").asInt() : 0;

            if (status != 200) {
                return createErrorReport(clientOrderId, extractErrorMessage(response));
            }

            JsonNode result = response.get("result");
            if (result == null) {
                return createErrorReport(clientOrderId, "No result in response");
            }

            String symbol = getText(result, "symbol");
            String binanceOrderId = result.has("orderId") ?
                    String.valueOf(result.get("orderId").asLong()) : "";
            String orderId = clientOrderId;
            OrderStatus orderStatus = parseOrderStatus(getText(result, "status"));
            TradeDirection side = parseSide(getText(result, "side"));
            double executedQty = getDouble(result, "executedQty");
            double avgPrice = getDouble(result, "avgPrice");
            long transactTime = result.has("transactTime") ?
                    result.get("transactTime").asLong() : System.currentTimeMillis();
            String rejectReason = null;

            return new ExecutionReport(
                    orderId,
                    symbol,
                    side,
                    com.trading.domain.trading.model.OrderType.LIMIT,
                    executedQty, avgPrice, executedQty, avgPrice,
                    orderStatus,
                    transactTime,
                    0.0, 0.0,
                    0.0, 0L,
                    null,
                    (String) null
            );

        } catch (Exception e) {
            log.error("[WsApi] Failed to parse place order response: {}", e.getMessage());
            return createErrorReport(clientOrderId, e.getMessage());
        }
    }

    /**
     * Parse order.cancel response
     */
    public ExecutionReport parseCancelOrderResponse(String clientOrderId, JsonNode response) {
        try {
            int status = response.has("status") ? response.get("status").asInt() : 0;

            if (status != 200) {
                return createErrorReport(clientOrderId, extractErrorMessage(response));
            }

            JsonNode result = response.get("result");
            if (result == null) {
                return createErrorReport(clientOrderId, "No result in cancel response");
            }

            String symbol = getText(result, "symbol");
            OrderStatus orderStatus = parseOrderStatus(getText(result, "status"));
            double executedQty = getDouble(result, "executedQty");
            long transactTime = result.has("transactTime") ?
                    result.get("transactTime").asLong() : System.currentTimeMillis();

            return new ExecutionReport(
                    clientOrderId,
                    symbol,
                    parseSide(getText(result, "side")),
                    com.trading.domain.trading.model.OrderType.LIMIT,
                    0, 0, executedQty, 0,
                    orderStatus,
                    transactTime,
                    0.0, 0.0,
                    0.0, 0L,
                    null,
                    (String) null
            );

        } catch (Exception e) {
            log.error("[WsApi] Failed to parse cancel order response: {}", e.getMessage());
            return createErrorReport(clientOrderId, e.getMessage());
        }
    }

    /**
     * Parse order.modify response
     */
    public ExecutionReport parseModifyOrderResponse(String clientOrderId, JsonNode response) {
        try {
            int status = response.has("status") ? response.get("status").asInt() : 0;

            if (status != 200) {
                return createErrorReport(clientOrderId, extractErrorMessage(response));
            }

            JsonNode result = response.get("result");
            if (result == null) {
                return createErrorReport(clientOrderId, "No result in modify response");
            }

            String symbol = getText(result, "symbol");
            OrderStatus orderStatus = parseOrderStatus(getText(result, "status"));
            double newQty = getDouble(result, "origQty");
            double newPrice = getDouble(result, "price");
            long transactTime = result.has("transactTime") ?
                    result.get("transactTime").asLong() : System.currentTimeMillis();

            return new ExecutionReport(
                    clientOrderId,
                    symbol,
                    parseSide(getText(result, "side")),
                    com.trading.domain.trading.model.OrderType.LIMIT,
                    newQty, newPrice, 0, newPrice,
                    orderStatus,
                    transactTime,
                    0.0, 0.0,
                    0.0, 0L,
                    null,
                    (String) null
            );

        } catch (Exception e) {
            log.error("[WsApi] Failed to parse modify order response: {}", e.getMessage());
            return createErrorReport(clientOrderId, e.getMessage());
        }
    }

    /**
     * Extract error message from response
     */
    public String extractErrorMessage(JsonNode response) {
        if (response.has("error")) {
            JsonNode error = response.get("error");
            int code = error.has("code") ? error.get("code").asInt() : 0;
            String msg = error.has("msg") ? error.get("msg").asText() : "Unknown error";
            return code + ": " + msg;
        }
        return "Unknown error";
    }

    /**
     * Check if response indicates rate limit error
     */
    public boolean isRateLimitError(JsonNode response) {
        if (response.has("status")) {
            int status = response.get("status").asInt();
            return status == 429 || status == 418;
        }
        return false;
    }

    /**
     * Parse rate limits from response
     */
    public List<RateLimitInfo> parseRateLimits(JsonNode response) {
        List<RateLimitInfo> limits = new ArrayList<>();
        if (!response.has("rateLimits")) return limits;

        JsonNode rateLimits = response.get("rateLimits");
        for (JsonNode limit : rateLimits) {
            String type = getText(limit, "rateLimitType");
            String interval = getText(limit, "interval");
            int intervalNum = limit.has("intervalNum") ? limit.get("intervalNum").asInt() : 1;
            int limitCount = limit.has("limit") ? limit.get("limit").asInt() : 0;
            int currentCount = limit.has("count") ? limit.get("count").asInt() : 0;

            limits.add(new RateLimitInfo(type, interval, intervalNum, limitCount, currentCount));
        }
        return limits;
    }

    // ========== Helpers ==========

    private OrderStatus parseOrderStatus(String status) {
        if (status == null) return OrderStatus.NEW;

        switch (status.toUpperCase()) {
            case "NEW": return OrderStatus.NEW;
            case "PARTIALLY_FILLED": return OrderStatus.PARTIALLY_FILLED;
            case "FILLED": return OrderStatus.FILLED;
            case "CANCELLED": return OrderStatus.CANCELLED;
            case "REJECTED": return OrderStatus.REJECTED;
            case "EXPIRED": return OrderStatus.EXPIRED;
            default: return OrderStatus.NEW;
        }
    }

    private TradeDirection parseSide(String side) {
        if (side == null) return TradeDirection.LONG;
        return "SELL".equalsIgnoreCase(side) ? TradeDirection.SHORT : TradeDirection.LONG;
    }

    private String getText(JsonNode node, String field) {
        return node.has(field) ? node.get(field).asText() : "";
    }

    private double getDouble(JsonNode node, String field) {
        return node.has(field) ? node.get(field).asDouble() : 0.0;
    }

    private ExecutionReport createErrorReport(String orderId, String errorMsg) {
        return new ExecutionReport(
                orderId,
                "",
                TradeDirection.LONG,
                com.trading.domain.trading.model.OrderType.LIMIT,
                0, 0, 0, 0,
                OrderStatus.REJECTED,
                System.currentTimeMillis(),
                0.0, 0.0,
                0.0, 0L,
                errorMsg,
                (String) null
        );
    }

    // ========== Rate Limit Info ==========

    public static class RateLimitInfo {
        public final String type;
        public final String interval;
        public final int intervalNum;
        public final int limit;
        public final int currentCount;

        public RateLimitInfo(String type, String interval, int intervalNum,
                            int limit, int currentCount) {
            this.type = type;
            this.interval = interval;
            this.intervalNum = intervalNum;
            this.limit = limit;
            this.currentCount = currentCount;
        }

        public double getUsageRatio() {
            return limit > 0 ? (double) currentCount / limit : 0;
        }

        public boolean isNearLimit() {
            return getUsageRatio() > 0.8;
        }

        @Override
        public String toString() {
            return String.format("%s %s %d/%d (%.1f%%)",
                    type, interval, currentCount, limit, getUsageRatio() * 100);
        }
    }
}