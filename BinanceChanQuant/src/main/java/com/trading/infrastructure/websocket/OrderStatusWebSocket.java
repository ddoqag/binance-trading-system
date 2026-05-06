package com.trading.infrastructure.websocket;

import com.binance.connector.futures.client.impl.UMFuturesClientImpl;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import okhttp3.*;
import java.net.URI;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;

/**
 * Order Status WebSocket - Real-time order execution updates
 *
 * Uses Binance User Data Stream WebSocket to receive order updates in real-time.
 * Eliminates the need for TTL-based polling.
 *
 * Flow:
 * 1. Start user data stream (listenKey)
 * 2. Connect to WebSocket stream
 * 3. Receive real-time ORDER_TRADE_UPDATE events
 * 4. Push to registered callbacks
 */
public class OrderStatusWebSocket {

    private final UMFuturesClientImpl client;
    private final ObjectMapper objectMapper = new ObjectMapper();
    private final Map<String, Consumer<OrderUpdate>> listeners = new ConcurrentHashMap<>();
    private final Map<String, String> listenKeyToSymbol = new ConcurrentHashMap<>();

    private WebSocket webSocket;
    private String currentListenKey;
    private ScheduledExecutorService scheduler;
    private boolean connected = false;

    /**
     * Order update event
     */
    public static class OrderUpdate {
        public final String symbol;
        public final String clientOrderId;
        public final String binanceOrderId;
        public final String status;  // NEW, FILLED, PARTIALLY_FILLED, CANCELLED, REJECTED
        public final double filledQty;
        public final double avgFillPrice;
        public final long transactTime;

        public OrderUpdate(String symbol, String clientOrderId, String binanceOrderId,
                          String status, double filledQty, double avgFillPrice, long transactTime) {
            this.symbol = symbol;
            this.clientOrderId = clientOrderId;
            this.binanceOrderId = binanceOrderId;
            this.status = status;
            this.filledQty = filledQty;
            this.avgFillPrice = avgFillPrice;
            this.transactTime = transactTime;
        }

        public boolean isFilled() {
            return "FILLED".equals(status);
        }

        public boolean isPartiallyFilled() {
            return "PARTIALLY_FILLED".equals(status);
        }

        public boolean isCancelled() {
            return "CANCELLED".equals(status);
        }

        public boolean isRejected() {
            return "REJECTED".equals(status);
        }
    }

    public OrderStatusWebSocket(UMFuturesClientImpl client) {
        this.client = client;
    }

    /**
     * Register a listener for order updates
     */
    public void registerListener(String symbol, Consumer<OrderUpdate> listener) {
        listeners.put(symbol, listener);
    }

    /**
     * Unregister listener
     */
    public void unregisterListener(String symbol) {
        listeners.remove(symbol);
    }

    /**
     * Start WebSocket connection
     */
    public void start() {
        if (client == null) {
            System.out.println("[OrderStatusWS] Paper trading - no WebSocket needed");
            return;
        }

        try {
            // 1. Start user data stream
            String listenKey = startUserDataStream();
            if (listenKey == null) {
                System.err.println("[OrderStatusWS] Failed to start user data stream");
                return;
            }

            currentListenKey = listenKey;

            // 2. Connect to WebSocket
            String wsUrl = "wss://fstream.binance.com/ws/" + listenKey;
            connectWebSocket(wsUrl);

            // 3. Schedule keep-alive (listenKey expires after 60 minutes)
            scheduler = Executors.newSingleThreadScheduledExecutor();
            scheduler.scheduleAtFixedRate(this::keepAliveStream, 30, 30, TimeUnit.MINUTES);

            System.out.println("[OrderStatusWS] Started - listenKey=" + listenKey.substring(0, 10) + "...");
            connected = true;

        } catch (Exception e) {
            System.err.println("[OrderStatusWS] Failed to start: " + e.getMessage());
        }
    }

    private String startUserDataStream() {
        try {
            String listenKey = client.userData().createListenKey();
            return listenKey;
        } catch (Exception e) {
            System.err.println("[OrderStatusWS] Start stream failed: " + e.getMessage());
            return null;
        }
    }

    private void keepAliveStream() {
        if (currentListenKey == null || client == null) return;

        try {
            client.userData().extendListenKey();
            System.out.println("[OrderStatusWS] Keep-alive sent");
        } catch (Exception e) {
            System.err.println("[OrderStatusWS] Keep-alive failed: " + e.getMessage());
            // Reconnect if keep-alive fails
            restart();
        }
    }

    private void connectWebSocket(String wsUrl) {
        try {
            OkHttpClient okHttpClient = new OkHttpClient.Builder()
                .pingInterval(30, TimeUnit.SECONDS)
                .build();

            Request request = new Request.Builder()
                .url(wsUrl)
                .build();

            webSocket = okHttpClient.newWebSocket(request, new WebSocketListener() {
                @Override
                public void onOpen(WebSocket webSocket, Response response) {
                    System.out.println("[OrderStatusWS] WebSocket connected");
                }

                @Override
                public void onMessage(WebSocket webSocket, String message) {
                    handleMessage(message);
                }

                @Override
                public void onClosing(WebSocket webSocket, int code, String reason) {
                    System.out.println("[OrderStatusWS] WebSocket closing: " + code + " " + reason);
                }

                @Override
                public void onFailure(WebSocket webSocket, Throwable t, Response response) {
                    System.err.println("[OrderStatusWS] WebSocket failure: " + t.getMessage());
                    // Reconnect after failure
                    scheduleReconnect();
                }
            });

        } catch (Exception e) {
            System.err.println("[OrderStatusWS] WebSocket connect failed: " + e.getMessage());
        }
    }

    private void handleMessage(String message) {
        try {
            JsonNode node = objectMapper.readTree(message);

            // Handle different event types
            if (node.has("e")) {
                String eventType = node.get("e").asText();

                if ("ORDER_TRADE_UPDATE".equals(eventType)) {
                    parseOrderUpdate(node);
                }
            }

            // ListenKey expiry notification
            if (node.has("result") && node.has("code") && node.get("code").asInt() == -1) {
                System.err.println("[OrderStatusWS] ListenKey expired, reconnecting...");
                restart();
            }

        } catch (Exception e) {
            System.err.println("[OrderStatusWS] Parse error: " + e.getMessage());
        }
    }

    private void parseOrderUpdate(JsonNode node) {
        try {
            JsonNode o = node.get("o");  // Order data

            String symbol = o.has("s") ? o.get("s").asText() : "";
            String clientOrderId = o.has("c") ? o.get("c").asText() : "";
            String binanceOrderId = o.has("i") ? o.get("i").asText() : "";
            String status = o.has("X") ? o.get("X").asText() : "";
            double filledQty = o.has("z") ? o.get("z").asDouble() : 0;
            double avgFillPrice = o.has("L") ? o.get("L").asDouble() : 0;
            long transactTime = o.has("T") ? o.get("T").asLong() : System.currentTimeMillis();

            OrderUpdate update = new OrderUpdate(symbol, clientOrderId, binanceOrderId,
                status, filledQty, avgFillPrice, transactTime);

            // Notify listener for this symbol
            Consumer<OrderUpdate> listener = listeners.get(symbol);
            if (listener != null) {
                listener.accept(update);
            }

            System.out.printf("[OrderStatusWS] Order update: %s %s %s qty=%.4f price=%.2f%n",
                clientOrderId, status, symbol, filledQty, avgFillPrice);

        } catch (Exception e) {
            System.err.println("[OrderStatusWS] Parse order update failed: " + e.getMessage());
        }
    }

    private void scheduleReconnect() {
        if (scheduler != null) {
            scheduler.schedule(this::restart, 5, TimeUnit.SECONDS);
        }
    }

    private void restart() {
        System.out.println("[OrderStatusWS] Restarting...");
        stop();
        try {
            Thread.sleep(1000);
        } catch (InterruptedException ignored) {}
        start();
    }

    /**
     * Stop WebSocket connection
     */
    public void stop() {
        connected = false;

        if (scheduler != null) {
            scheduler.shutdown();
            scheduler = null;
        }

        if (webSocket != null) {
            try {
                webSocket.close(1000, "Normal closure");
            } catch (Exception ignored) {}
            webSocket = null;
        }

        // Close user data stream
        if (currentListenKey != null && client != null) {
            try {
                client.userData().closeListenKey();
                System.out.println("[OrderStatusWS] Stream closed");
            } catch (Exception ignored) {}
            currentListenKey = null;
        }
    }

    public boolean isConnected() {
        return connected;
    }
}