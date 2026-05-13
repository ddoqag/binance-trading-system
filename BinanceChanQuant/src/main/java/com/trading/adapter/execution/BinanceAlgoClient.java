package com.trading.adapter.execution;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderStatus;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.TradeDirection;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.Proxy;
import java.nio.charset.StandardCharsets;
import java.security.InvalidKeyException;
import java.security.NoSuchAlgorithmException;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.TreeMap;

/**
 * Binance Algo Orders Client
 *
 * <p>Direct access to Binance Futures Algo API for protection orders.
 * This bypasses connector limitations for P0 survival layer orders.
 *
 * <p>Algo API required for:
 * - STOP_MARKET orders with closePosition
 * - Guaranteed execution protection
 *
 * <p>API Endpoint: POST /fapi/v1/algoOrder
 */
public class BinanceAlgoClient {

    private static final Logger log = LoggerFactory.getLogger(BinanceAlgoClient.class);

    private final String apiKey;
    private final String apiSecret;
    private final String baseUrl;
    private final Proxy proxy;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public BinanceAlgoClient(String apiKey, String apiSecret, String baseUrl, Proxy proxy) {
        this.apiKey = apiKey;
        this.apiSecret = apiSecret;
        this.baseUrl = baseUrl;
        this.proxy = proxy;
    }

    /**
     * Send STOP_MARKET order with closePosition=true for emergency protection.
     *
     * <p>This is the P0 survival layer order - must succeed.
     *
     * @param order Order with side, quantity, stopPrice set
     * @param closePosition true to close entire position
     * @return ExecutionReport with status
     */
    public ExecutionReport sendStopOrder(Order order, boolean closePosition) {
        try {
            long timestamp = System.currentTimeMillis();

            // Use Algo API with CONDITIONAL type
            // NOTE: closePosition=true closes entire position - quantity must NOT be sent
            // For closePosition: side determines which position to close
            //   - SELL closes LONG position (we sell to close long)
            //   - BUY closes SHORT position (we buy to close short)
            // Our order.getSide() = close direction (to close a SHORT position, we use LONG because we buy)
            // But Binance side needs to match what action we take:
            //   - To close SHORT position: BUY
            //   - To close LONG position: SELL
            // So order.getSide()=LONG (buy to close SHORT) → side="BUY"
            //    order.getSide()=SHORT (sell to close LONG) → side="SELL"
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", order.getSymbol());
            // Map our close direction to Binance side
            // To close SHORT position: BUY (we buy to close short)
            // To close LONG position: SELL (we sell to close long)
            params.put("side", order.getSide() == TradeDirection.LONG ? "BUY" : "SELL");
            params.put("type", "STOP_MARKET");
            params.put("algoType", "CONDITIONAL");
            // triggerPrice must be sent as a number string for STOP_MARKET
            params.put("triggerPrice", String.format("%.0f", order.getStopPrice()));
            // P0 FIX: For closePosition=true in hedge mode, positionSide must be the ACTUAL position side
            // We want to close a SHORT position, so positionSide=SHORT
            // order.getSide() = close direction (LONG means buy to close short, so actual position is SHORT)
            params.put("positionSide", order.getSide() == TradeDirection.LONG ? "SHORT" : "LONG");
            params.put("closePosition", "true");
            params.put("clientAlgoId", order.getOrderId());
            params.put("timestamp", timestamp);
            params.put("recvWindow", 60000);

            String signature = signParams(params);

            String resp = executePost("/fapi/v1/algoOrder", params, signature, timestamp);

            if (resp.startsWith("{")) {
                // Check for error codes
                if (resp.contains("\"code\":")) {
                    // Reject on unrecoverable error codes (signature issues, auth, etc)
                    if (resp.contains("-4500") || resp.contains("-1022") || resp.contains("-1021") || resp.contains("-2013")) {
                        log.warn("[BinanceAlgo] Algo API failed: {}", resp);
                        return createRejectedReport(order, resp);
                    }
                    // These error codes indicate parameter issues - fall back to regular API
                    // -4061: position side mismatch (try without positionSide)
                    // -1128: invalid parameter combination (try different params)
                    // -4509: time in force error (try without positionSide)
                    if (resp.contains("-4061") || resp.contains("-1128") || resp.contains("-4509")) {
                        log.warn("[BinanceAlgo] Algo API parameter issue: {}, signaling fallback", resp);
                        return null;
                    }
                }
                return parseAlgoResponse(order, resp);
            } else {
                log.warn("[BinanceAlgo] Algo API returned non-JSON: {}", resp);
                return createRejectedReport(order, resp);
            }

        } catch (Exception e) {
            log.error("[BinanceAlgo] Stop order failed: {}", e.getMessage());
            return createRejectedReport(order, e.getMessage());
        }
    }

    private String executePostNoProxy(String endpoint, LinkedHashMap<String, Object> params,
                                      String signature, long timestamp) throws IOException {
        // Build query string in sorted order (same as signing)
        TreeMap<String, Object> sorted = new TreeMap<>(params);
        StringBuilder query = new StringBuilder();
        for (Map.Entry<String, Object> entry : sorted.entrySet()) {
            if (query.length() > 0) query.append("&");
            query.append(entry.getKey()).append("=").append(entry.getValue());
        }
        query.append("&signature=").append(signature);

        String url = baseUrl + endpoint + "?" + query.toString();
        log.info("[BinanceAlgo] Attempting direct connection (NO_PROXY) to: {}", endpoint);

        java.net.HttpURLConnection conn = (java.net.HttpURLConnection)
                new java.net.URL(url).openConnection(Proxy.NO_PROXY);

        conn.setConnectTimeout(20000);  // 20s for direct connection
        conn.setReadTimeout(20000);
        conn.setRequestMethod("POST");
        conn.setRequestProperty("X-MBX-APIKEY", apiKey);
        conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded");
        conn.setRequestProperty("Accept", "application/json");
        conn.setDoOutput(true);

        try (java.io.OutputStream os = conn.getOutputStream()) {
        }

        int responseCode = conn.getResponseCode();
        log.info("[BinanceAlgo] Direct response code: {}", responseCode);

        java.io.BufferedReader reader = new java.io.BufferedReader(
                new java.io.InputStreamReader(
                        responseCode >= 400 ? conn.getErrorStream() : conn.getInputStream(),
                        StandardCharsets.UTF_8));

        StringBuilder response = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            response.append(line);
        }
        reader.close();

        log.info("[BinanceAlgo] POST (no proxy) {} -> {}", endpoint, responseCode);
        return response.toString();
    }

    /**
     * Send STOP order with reduceOnly for position protection.
     *
     * @param order Order with side, quantity, stopPrice set
     * @param reduceOnly true to ensure only reduce/close
     * @return ExecutionReport with status
     */
    public ExecutionReport sendStopWithReduceOnly(Order order, boolean reduceOnly) {
        try {
            long timestamp = System.currentTimeMillis();

            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", order.getSymbol());
            // For non-closePosition: side/positionSide = actual direction
            params.put("side", order.getSide() == TradeDirection.LONG ? "BUY" : "SELL");
            params.put("positionSide", order.getSide() == TradeDirection.LONG ? "LONG" : "SHORT");
            params.put("type", "STOP_MARKET");
            params.put("algoType", "CONDITIONAL");
            params.put("quantity", formatQuantity(order.getQuantity()));
            params.put("triggerPrice", formatPrice(order.getStopPrice()));
            if (reduceOnly) {
                params.put("reduceOnly", "true");
            }
            params.put("clientAlgoId", order.getOrderId());
            params.put("timestamp", timestamp);

            String signature = signParams(params);

            String resp = executePost("/fapi/v1/algoOrder",
                    params, signature, timestamp);

            return parseAlgoResponse(order, resp);

        } catch (Exception e) {
            log.error("[BinanceAlgo] Stop with reduceOnly failed: {}", e.getMessage());
            return createRejectedReport(order, e.getMessage());
        }
    }

    /**
     * Query algo order status.
     */
    public ExecutionReport queryAlgoOrder(String algoId) {
        try {
            long timestamp = System.currentTimeMillis();

            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", "BTCUSDT");  // TODO: pass symbol
            params.put("orderId", algoId);
            params.put("timestamp", timestamp);

            String signature = signParams(params);

            String resp = executeGet("/fapi/v1/algo/query",
                    params, signature, timestamp);

            return parseAlgoQueryResponse(resp);

        } catch (Exception e) {
            log.error("[BinanceAlgo] Query algo order failed: {}", e.getMessage());
            return null;
        }
    }

    // ========== HTTP Execution ==========

    private String executePost(String endpoint, LinkedHashMap<String, Object> params,
                              String signature, long timestamp) throws IOException {
        // Build query string in sorted order (same as signing) to ensure signature matches
        TreeMap<String, Object> sorted = new TreeMap<>(params);
        StringBuilder query = new StringBuilder();
        for (Map.Entry<String, Object> entry : sorted.entrySet()) {
            if (query.length() > 0) query.append("&");
            query.append(entry.getKey()).append("=").append(entry.getValue());
        }
        query.append("&signature=").append(signature);

        String url = baseUrl + endpoint + "?" + query.toString();
        log.info("[BinanceAlgo] URL: {}", url);
        log.info("[BinanceAlgo] Using proxy: {}", proxy);

        // Use the actual proxy for fallback
        java.net.HttpURLConnection conn = (java.net.HttpURLConnection)
                new java.net.URL(url).openConnection(proxy);

        conn.setConnectTimeout(20000);
        conn.setReadTimeout(20000);
        conn.setRequestMethod("POST");
        conn.setRequestProperty("X-MBX-APIKEY", apiKey);
        conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded");
        conn.setRequestProperty("Accept", "application/json");
        conn.setDoOutput(true);

        try (java.io.OutputStream os = conn.getOutputStream()) {
            // Write body (empty for this endpoint)
        }

        int responseCode = conn.getResponseCode();
        java.io.BufferedReader reader = new java.io.BufferedReader(
                new java.io.InputStreamReader(
                        responseCode >= 400 ? conn.getErrorStream() : conn.getInputStream(),
                        StandardCharsets.UTF_8));

        StringBuilder response = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            response.append(line);
        }
        reader.close();

        log.info("[BinanceAlgo] POST {} -> {} | body: {}", endpoint, responseCode, response);
        return response.toString();
    }

    private String executeGet(String endpoint, LinkedHashMap<String, Object> params,
                              String signature, long timestamp) throws IOException {
        // Build query string with signature
        StringBuilder query = new StringBuilder();
        for (Map.Entry<String, Object> entry : params.entrySet()) {
            if (query.length() > 0) query.append("&");
            query.append(entry.getKey()).append("=").append(entry.getValue());
        }
        query.append("&signature=").append(signature);

        String url = baseUrl + endpoint + "?" + query.toString();

        java.net.HttpURLConnection conn = (java.net.HttpURLConnection)
                new java.net.URL(url).openConnection(proxy);

        conn.setRequestMethod("GET");
        conn.setRequestProperty("X-MBX-APIKEY", apiKey);

        int responseCode = conn.getResponseCode();
        java.io.BufferedReader reader = new java.io.BufferedReader(
                new java.io.InputStreamReader(
                        responseCode >= 400 ? conn.getErrorStream() : conn.getInputStream(),
                        StandardCharsets.UTF_8));

        StringBuilder response = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            response.append(line);
        }
        reader.close();

        log.info("[BinanceAlgo] GET {} -> {}", endpoint, responseCode);
        return response.toString();
    }

    // ========== Signature ==========

    private String signParams(LinkedHashMap<String, Object> params) {
        // Build query string in sorted order (TreeMap sorts alphabetically)
        TreeMap<String, Object> sorted = new TreeMap<>(params);
        StringBuilder sb = new StringBuilder();
        for (Map.Entry<String, Object> entry : sorted.entrySet()) {
            if (sb.length() > 0) sb.append("&");
            sb.append(entry.getKey()).append("=").append(entry.getValue());
        }

        log.info("[BinanceAlgo] Signing string (sorted): {}", sb);

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
            String signature = hex.toString();
            log.info("[BinanceAlgo] Generated signature: {}", signature);
            return signature;
        } catch (NoSuchAlgorithmException | InvalidKeyException e) {
            throw new RuntimeException("Failed to sign request", e);
        }
    }

    // ========== Response Parsing ==========

    private ExecutionReport parseAlgoResponse(Order order, String respStr) {
        try {
            JsonNode node = objectMapper.readTree(respStr);

            long algoId = node.has("algoId") ? node.get("algoId").asLong() : 0;
            String status = node.has("status") ? node.get("status").asText() : "NEW";

            return new ExecutionReport(
                order.getOrderId(),
                order.getSymbol(),
                order.getSide(),
                order.getOrderType(),
                order.getQuantity(),
                order.getPrice(),
                0, 0,
                parseStatus(status),
                System.currentTimeMillis(),
                algoId,
                0.0
            );
        } catch (Exception e) {
            log.error("[BinanceAlgo] Parse response failed: {}", e.getMessage());
            return createRejectedReport(order, respStr);
        }
    }

    private ExecutionReport parseAlgoQueryResponse(String respStr) {
        try {
            JsonNode node = objectMapper.readTree(respStr);

            long algoId = node.has("algoId") ? node.get("algoId").asLong() : 0;
            String status = node.has("status") ? node.get("status").asText() : "UNKNOWN";
            double filledQty = node.has("executedQty") ? node.get("executedQty").asDouble() : 0;

            return new ExecutionReport(
                "query",
                "BTCUSDT",
                TradeDirection.NEUTRAL,
                OrderType.STOP_MARKET,
                0, 0, filledQty, 0,
                parseStatus(status),
                System.currentTimeMillis(),
                algoId,
                0.0
            );
        } catch (Exception e) {
            log.error("[BinanceAlgo] Parse query response failed: {}", e.getMessage());
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

    private OrderStatus parseStatus(String binanceStatus) {
        if ("NEW".equals(binanceStatus)) return OrderStatus.NEW;
        if ("FILLED".equals(binanceStatus)) return OrderStatus.FILLED;
        if ("PARTIALLY_FILLED".equals(binanceStatus)) return OrderStatus.PARTIALLY_FILLED;
        if ("CANCELED".equals(binanceStatus)) return OrderStatus.CANCELLED;
        if ("REJECTED".equals(binanceStatus)) return OrderStatus.REJECTED;
        if ("EXPIRED".equals(binanceStatus)) return OrderStatus.EXPIRED;
        if ("TRAILING".equals(binanceStatus)) return OrderStatus.NEW;
        if ("HALT".equals(binanceStatus)) return OrderStatus.NEW;
        if ("LIQUIDATION".equals(binanceStatus)) return OrderStatus.FILLED;
        return OrderStatus.NEW;
    }

    // ========== Formatting ==========

    private String formatQuantity(double qty) {
        if (qty >= 1) {
            return String.format("%.0f", qty);
        } else if (qty >= 0.01) {
            return String.format("%.2f", qty);
        } else {
            return String.format("%.3f", qty);
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
}
