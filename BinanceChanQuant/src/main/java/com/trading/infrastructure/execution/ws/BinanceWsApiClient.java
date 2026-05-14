package com.trading.infrastructure.execution.ws;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.Order;
import okhttp3.*;
import okio.ByteString;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.net.InetSocketAddress;
import java.net.Proxy;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Consumer;

/**
 * Binance WebSocket API Client (WS-API v3)
 *
 * <p>Provides low-latency order execution via Binance WS-API v3:
 * <ul>
 *   <li>order.place</li>
 *   <li>order.cancel</li>
 *   <li>order.modify</li>
 * </ul>
 *
 * <p>Features:
 * <ul>
 *   <li>Ping/pong handling (every 20s, reply within 1min)</li>
 *   <li>Exponential backoff reconnection (1s→30s, 10 attempts)</li>
 *   <li>Request/response correlation via UUID</li>
 *   <li>serverShutdown event handling</li>
 * </ul>
 */
public class BinanceWsApiClient {

    private static final Logger log = LoggerFactory.getLogger(BinanceWsApiClient.class);

    // WS-API endpoints (2026年5月版)
    // Mainnet: ws-api.binance.com (NOT fapi.binance.com)
    private static final String MAINNET_URL = "wss://ws-api.binance.com/ws-api/v3";
    private static final String TESTNET_URL = "wss://testnet.binanceops.com/ws-api/v3";

    // Reconnection config
    private static final long INITIAL_RECONNECT_DELAY_MS = 1_000;
    private static final long MAX_RECONNECT_DELAY_MS = 30_000;
    private static final double BACKOFF_MULTIPLIER = 2.0;
    private static final int MAX_RECONNECT_ATTEMPTS = 10;

    // Request timeout
    private static final long REQUEST_TIMEOUT_MS = 10_000;

    // Connection lifetime (24h max per Binance)
    private static final long CONNECTION_LIFETIME_MS = 23 * 60 * 60 * 1000; // 23h
    private static final long MESSAGE_TIMEOUT_MS = 120_000; // 2min before warning
    private long lastMessageWarningTime = 0; // Throttle warnings

    // Dependencies
    private final WsApiRequestBuilder requestBuilder;
    private final WsApiResponseParser responseParser;
    private final ObjectMapper objectMapper;
    private final boolean testnet;

    // Proxy
    private Proxy proxy;
    private int connectTimeoutMs = 60_000;
    private int readTimeoutMs = 90_000;

    // WebSocket
    private WebSocket webSocket;
    private String wsUrl;

    // State
    private final AtomicReference<ConnectionState> connectionState =
            new AtomicReference<>(ConnectionState.DISCONNECTED);
    private final AtomicInteger reconnectAttempts = new AtomicInteger(0);
    private volatile long currentReconnectDelay = INITIAL_RECONNECT_DELAY_MS;
    private volatile long connectionStartTime = 0;
    private volatile long lastMessageTime = 0;

    // Executor
    private ScheduledExecutorService scheduler;

    // Pending requests (id -> CompletableFuture)
    private final ConcurrentHashMap<String, CompletableFuture<JsonNode>> pendingRequests =
            new ConcurrentHashMap<>();

    // Callbacks
    private Consumer<ExecutionReport> onOrderUpdate;
    private Consumer<String> onStateChange;

    // Running flag
    private volatile boolean running = false;

    public enum ConnectionState {
        DISCONNECTED,
        CONNECTING,
        CONNECTED,
        RECONNECTING,
        FAILED
    }

    public BinanceWsApiClient(String apiKey, String apiSecret, boolean testnet) {
        this.requestBuilder = new WsApiRequestBuilder(apiKey, apiSecret, testnet);
        this.responseParser = new WsApiResponseParser();
        this.objectMapper = new ObjectMapper();
        this.testnet = testnet;
        this.wsUrl = testnet ? TESTNET_URL : MAINNET_URL;
        this.proxy = Proxy.NO_PROXY;
    }

    // ========== Configuration ==========

    public void setProxy(String host, int port) {
        if (host == null || host.isEmpty() || port <= 0) {
            this.proxy = Proxy.NO_PROXY;
            log.info("[WsApi] Proxy disabled");
        } else {
            this.proxy = new Proxy(Proxy.Type.HTTP, new InetSocketAddress(host, port));
            log.info("[WsApi] Proxy set: {}:{}", host, port);
        }
    }

    public void setTimeout(int connectTimeoutMs, int readTimeoutMs) {
        this.connectTimeoutMs = connectTimeoutMs;
        this.readTimeoutMs = readTimeoutMs;
    }

    public void setOnOrderUpdate(Consumer<ExecutionReport> callback) {
        this.onOrderUpdate = callback;
    }

    public void setOnStateChange(Consumer<String> callback) {
        this.onStateChange = callback;
    }

    // ========== Connection ==========

    public void connect() {
        if (running) {
            log.warn("[WsApi] Already running");
            return;
        }

        running = true;
        scheduler = Executors.newScheduledThreadPool(2, r -> {
            Thread t = new Thread(r, "WsApi-scheduler");
            t.setDaemon(true);
            return t;
        });

        connectWebSocket();

        // Periodic connection health check
        scheduler.scheduleAtFixedRate(this::checkConnectionHealth, 30, 30, TimeUnit.SECONDS);
    }

    public void disconnect() {
        if (!running) return;

        running = false;
        log.info("[WsApi] Disconnecting...");

        if (webSocket != null) {
            try {
                webSocket.close(1000, "Normal closure");
            } catch (Exception ignored) {}
            webSocket = null;
        }

        // Cancel all pending requests
        pendingRequests.values().forEach(future -> future.cancel(false));
        pendingRequests.clear();

        if (scheduler != null) {
            scheduler.shutdown();
            try {
                if (!scheduler.awaitTermination(5, TimeUnit.SECONDS)) {
                    scheduler.shutdownNow();
                }
            } catch (InterruptedException e) {
                scheduler.shutdownNow();
                Thread.currentThread().interrupt();
            }
        }

        connectionState.set(ConnectionState.DISCONNECTED);
        log.info("[WsApi] Disconnected");
    }

    public ConnectionState getConnectionState() {
        return connectionState.get();
    }

    public boolean isConnected() {
        return connectionState.get() == ConnectionState.CONNECTED && webSocket != null;
    }

    private void connectWebSocket() {
        connectionState.set(ConnectionState.CONNECTING);
        fireStateChange("CONNECTING");

        try {
            OkHttpClient client = createOkHttpClient();

            Request request = new Request.Builder()
                    .url(wsUrl)
                    .addHeader("Origin", "https://www.binance.com")
                    .addHeader("Host", "fapi.binance.com")
                    .build();

            webSocket = client.newWebSocket(request, createListener());

            log.info("[WsApi] Connecting to: {}", wsUrl);

        } catch (Exception e) {
            log.error("[WsApi] Connection failed: {}", e.getMessage());
            scheduleReconnect();
        }
    }

    private OkHttpClient createOkHttpClient() {
        OkHttpClient.Builder builder = new OkHttpClient.Builder()
                .pingInterval(20, TimeUnit.SECONDS) // Binance pings every 20s
                .connectTimeout(connectTimeoutMs, TimeUnit.MILLISECONDS)
                .readTimeout(readTimeoutMs, TimeUnit.MILLISECONDS);

        if (proxy != null && proxy != Proxy.NO_PROXY) {
            builder.proxy(proxy);
        }

        return builder.build();
    }

    private WebSocketListener createListener() {
        return new WebSocketListener() {
            @Override
            public void onOpen(WebSocket webSocket, Response response) {
                log.info("[WsApi] Connected");
                connectionState.set(ConnectionState.CONNECTED);
                connectionStartTime = System.currentTimeMillis();
                lastMessageTime = System.currentTimeMillis();
                reconnectAttempts.set(0);
                currentReconnectDelay = INITIAL_RECONNECT_DELAY_MS;
                fireStateChange("CONNECTED");
            }

            @Override
            public void onMessage(WebSocket webSocket, String message) {
                lastMessageTime = System.currentTimeMillis();
                handleMessage(message);
            }

            @Override
            public void onClosing(WebSocket webSocket, int code, String reason) {
                log.info("[WsApi] Closing: {} {}", code, reason);
                webSocket.close(1000, "Normal closure");
            }

            @Override
            public void onClosed(WebSocket webSocket, int code, String reason) {
                log.info("[WsApi] Closed: {} {}", code, reason);
                connectionState.set(ConnectionState.DISCONNECTED);
                fireStateChange("CLOSED");
                if (running) {
                    scheduleReconnect();
                }
            }

            @Override
            public void onFailure(WebSocket webSocket, Throwable t, Response response) {
                log.error("[WsApi] Failure: {}", t.getMessage());
                connectionState.set(ConnectionState.DISCONNECTED);
                fireStateChange("FAILED");
                if (running) {
                    scheduleReconnect();
                }
            }
        };
    }

    // ========== Message Handling ==========

    private void handleMessage(String message) {
        try {
            JsonNode node = objectMapper.readTree(message);

            // Check for event types (serverShutdown, etc.)
            if (node.has("event")) {
                handleEvent(node);
                return;
            }

            // Check for response id
            if (node.has("id")) {
                String id = node.get("id").asText();
                CompletableFuture<JsonNode> future = pendingRequests.remove(id);

                if (future != null) {
                    future.complete(node);
                } else {
                    log.warn("[WsApi] No pending request for id: {}", id);
                }
                return;
            }

            log.debug("[WsApi] Unknown message type: {}", message.substring(0, Math.min(100, message.length())));

        } catch (Exception e) {
            log.error("[WsApi] Message parse error: {}", e.getMessage());
        }
    }

    private void handleEvent(JsonNode node) {
        String eventType = node.get("event").asText();

        if ("serverShutdown".equals(eventType)) {
            log.warn("[WsApi] Received serverShutdown event, will reconnect...");
            if (webSocket != null) {
                try {
                    webSocket.close(1000, "Server shutdown");
                } catch (Exception ignored) {}
            }
            scheduleReconnect();
        }
    }

    private void checkConnectionHealth() {
        long now = System.currentTimeMillis();

        // Check connection lifetime (24h max)
        if (connectionStartTime > 0 && (now - connectionStartTime) > CONNECTION_LIFETIME_MS) {
            log.info("[WsApi] Connection lifetime exceeded, refreshing...");
            reconnect();
            return;
        }

        // Check message timeout (throttled to every 60s)
        if (lastMessageTime > 0 && (now - lastMessageTime) > MESSAGE_TIMEOUT_MS) {
            if (now - lastMessageWarningTime > 60_000) {
                log.warn("[WsApi] No messages for {}s, checking...", (now - lastMessageTime) / 1000);
                lastMessageWarningTime = now;
            }
            lastMessageTime = now;
        }
    }

    // ========== Order Operations ==========

    /**
     * Place order via WS-API
     */
    public CompletableFuture<ExecutionReport> placeOrder(Order order) {
        return sendRequest(() -> {
            long timestamp = System.currentTimeMillis();
            String request = requestBuilder.buildPlaceOrderRequest(order, timestamp);
            return request;
        }, response -> {
            String clientOrderId = order.getOrderId();
            return responseParser.parsePlaceOrderResponse(clientOrderId, response);
        });
    }

    /**
     * Cancel order via WS-API
     */
    public CompletableFuture<ExecutionReport> cancelOrder(String clientOrderId, long binanceOrderId, String symbol) {
        return sendRequest(() -> {
            long timestamp = System.currentTimeMillis();
            String request = requestBuilder.buildCancelOrderRequest(
                    clientOrderId, binanceOrderId, symbol, timestamp);
            return request;
        }, response -> {
            return responseParser.parseCancelOrderResponse(clientOrderId, response);
        });
    }

    /**
     * Modify order via WS-API
     */
    public CompletableFuture<ExecutionReport> modifyOrder(String clientOrderId, long binanceOrderId,
                                                           String symbol, double newPrice, double newQty) {
        return sendRequest(() -> {
            long timestamp = System.currentTimeMillis();
            String request = requestBuilder.buildModifyOrderRequest(
                    clientOrderId, binanceOrderId, symbol, newPrice, newQty, timestamp);
            return request;
        }, response -> {
            return responseParser.parseModifyOrderResponse(clientOrderId, response);
        });
    }

    /**
     * Test connectivity
     */
    public CompletableFuture<Boolean> ping() {
        return sendRawRequest(requestBuilder.buildPingRequest())
                .thenApply(response -> {
                    int status = response.has("status") ? response.get("status").asInt() : 0;
                    return status == 200;
                });
    }

    // ========== Request Handling ==========

    private CompletableFuture<ExecutionReport> sendRequest(
            java.util.function.Supplier<String> requestBuilder,
            java.util.function.Function<JsonNode, ExecutionReport> responseParser) {

        String request = requestBuilder.get();

        return sendRawRequest(request).thenApply(responseParser);
    }

    private CompletableFuture<JsonNode> sendRawRequest(String request) {
        CompletableFuture<JsonNode> future = new CompletableFuture<>();

        if (!isConnected()) {
            future.completeExceptionally(new IllegalStateException("Not connected"));
            return future;
        }

        // Extract id from request for correlation
        String id = extractId(request);
        if (id != null) {
            pendingRequests.put(id, future);
        }

        // Set timeout
        scheduler.schedule(() -> {
            CompletableFuture<JsonNode> pending = pendingRequests.remove(id);
            if (pending != null && !pending.isDone()) {
                pending.completeExceptionally(new TimeoutException("Request timeout"));
            }
        }, REQUEST_TIMEOUT_MS, TimeUnit.MILLISECONDS);

        // Send request
        webSocket.send(request);
        log.debug("[WsApi] Sent: {}", request.substring(0, Math.min(100, request.length())));

        return future;
    }

    private String extractId(String request) {
        try {
            JsonNode node = objectMapper.readTree(request);
            return node.has("id") ? node.get("id").asText() : null;
        } catch (Exception e) {
            return null;
        }
    }

    // ========== Reconnection ==========

    private void scheduleReconnect() {
        if (!running) return;

        int attempts = reconnectAttempts.incrementAndGet();
        if (attempts > MAX_RECONNECT_ATTEMPTS) {
            log.error("[WsApi] Max reconnect attempts exceeded");
            connectionState.set(ConnectionState.FAILED);
            fireStateChange("FAILED");
            return;
        }

        connectionState.set(ConnectionState.RECONNECTING);
        fireStateChange("RECONNECTING");

        log.info("[WsApi] Reconnecting attempt {} in {}ms", attempts, currentReconnectDelay);

        scheduler.schedule(() -> {
            if (running) {
                reconnect();
            }
        }, currentReconnectDelay, TimeUnit.MILLISECONDS);

        // Exponential backoff
        currentReconnectDelay = Math.min(
                (long) (currentReconnectDelay * BACKOFF_MULTIPLIER),
                MAX_RECONNECT_DELAY_MS
        );
    }

    private void reconnect() {
        if (webSocket != null) {
            try {
                webSocket.close(1000, "Reconnecting");
            } catch (Exception ignored) {}
            webSocket = null;
        }

        pendingRequests.values().forEach(future -> future.cancel(false));
        pendingRequests.clear();

        connectWebSocket();
    }

    private void fireStateChange(String state) {
        if (onStateChange != null) {
            onStateChange.accept(state);
        }
    }
}