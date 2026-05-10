package com.trading.execution.v6;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import okhttp3.*;
import java.util.concurrent.TimeUnit;

/**
 * Binance WebSocket Client - User Data Stream (使用OkHttp)
 *
 * 职责：
 * 1. 获取 listenKey
 * 2. 连接 wss://stream.binance.com:9443/ws/<listenKey>
 * 3. 解析 executionReport (成交)
 * 4. 解析 ACCOUNT_UPDATE (账户更新)
 */
public class BinanceWebSocketClient {

    private static final String API_KEY;
    private static final String BINANCE_WS_URL = "wss://stream.binance.com:9443/ws";
    private static final String USER_DATA_STREAM_URL = "https://api.binance.com/api/v3/userDataStream";

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final OkHttpClient httpClient = new OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .pingInterval(30, TimeUnit.SECONDS)
        .build();

    private WebSocket ws;
    private String listenKey;
    private ExecutionEngineV6.ExchangeListener listener;
    private volatile boolean connected = false;

    static {
        String key = "";
        try {
            Class<?> configUtil = Class.forName("com.trading.config.ConfigUtil");
            java.lang.reflect.Method getKey = configUtil.getMethod("get", String.class);
            Object result = getKey.invoke(null, "api.key");
            key = result != null ? (String) result : "";
        } catch (Exception e) {
            // 使用空值
        }
        API_KEY = key;
    }

    public BinanceWebSocketClient() {}

    public void setListener(ExecutionEngineV6.ExchangeListener listener) {
        this.listener = listener;
    }

    /**
     * 启动 User Data Stream
     */
    public boolean start() {
        try {
            // 1. 获取 listenKey
            listenKey = getListenKey();
            if (listenKey == null) {
                System.err.println("[WS] Failed to get listenKey");
                return false;
            }
            System.out.println("[WS] Got listenKey: " + listenKey.substring(0, 10) + "...");

            // 2. 连接 WebSocket
            String wsUrl = BINANCE_WS_URL + "/" + listenKey;
            Request request = new Request.Builder()
                .url(wsUrl)
                .build();

            ws = httpClient.newWebSocket(request, new WebSocketListener() {
                @Override
                public void onOpen(WebSocket webSocket, Response response) {
                    System.out.println("[WS] Connected to User Data Stream");
                    connected = true;
                }

                @Override
                public void onMessage(WebSocket webSocket, String message) {
                    handleMessage(message);
                }

                @Override
                public void onClosing(WebSocket webSocket, int code, String reason) {
                    System.out.println("[WS] Disconnecting: " + reason);
                    webSocket.close(1000, null);
                    connected = false;
                }

                @Override
                public void onFailure(WebSocket webSocket, Throwable t, Response response) {
                    System.err.println("[WS] Error: " + t.getMessage());
                    connected = false;
                    scheduleReconnect();
                }
            });

            return true;

        } catch (Exception e) {
            System.err.println("[WS] Start failed: " + e.getMessage());
            return false;
        }
    }

    /**
     * 获取 listenKey
     */
    private String getListenKey() {
        try {
            Request request = new Request.Builder()
                .url(USER_DATA_STREAM_URL)
                .post(RequestBody.create("", null))
                .addHeader("X-MBX-APIKEY", API_KEY)
                .build();

            try (Response response = httpClient.newCall(request).execute()) {
                if (!response.isSuccessful()) return null;
                String body = response.body().string();
                JsonNode node = objectMapper.readTree(body);
                return node.get("listenKey").asText();
            }
        } catch (Exception e) {
            System.err.println("[WS] getListenKey failed: " + e.getMessage());
            return null;
        }
    }

    /**
     * 定时重连
     */
    private void scheduleReconnect() {
        Thread reconnectThread = new Thread(() -> {
            try {
                Thread.sleep(5000);
                System.out.println("[WS] Attempting reconnect...");
                start();
            } catch (InterruptedException e) {
                // ignore
            }
        });
        reconnectThread.setDaemon(true);
        reconnectThread.start();
    }

    /**
     * 处理 WebSocket 消息
     */
    private void handleMessage(String message) {
        try {
            JsonNode node = objectMapper.readTree(message);

            // executionReport - 成交报告
            if (node.has("e") && "executionReport".equals(node.get("e").asText())) {
                String orderId = node.get("i").asText();
                String symbol = node.get("s").asText();
                String side = node.get("S").asText();
                double qty = Double.parseDouble(node.get("q").asText());
                double price = Double.parseDouble(node.get("L").asText());
                String status = node.get("x").asText();

                System.out.printf("[WS] executionReport: orderId=%s side=%s qty=%.4f price=%.2f status=%s%n",
                    orderId, side, qty, price, status);

                if (listener != null) {
                    switch (status) {
                        case "NEW":
                            // 新订单
                            break;
                        case "TRADE":
                            // 成交
                            listener.onFill(orderId, qty, price);
                            break;
                        case "CANCELED":
                        case "REJECTED":
                        case "EXPIRED":
                            listener.onOrderUpdate(orderId, status);
                            break;
                    }
                }
            }

            // ACCOUNT_UPDATE - 账户更新
            if (node.has("e") && "ACCOUNT_UPDATE".equals(node.get("e").asText())) {
                JsonNode account = node.get("a");
                if (account != null && listener != null) {
                    double balance = 0;
                    double unrealizedPnL = 0;

                    JsonNode balances = account.get("B");
                    if (balances != null) {
                        for (JsonNode b : balances) {
                            if ("USDT".equals(b.get("a").asText())) {
                                balance = Double.parseDouble(b.get("wb").asText());
                                unrealizedPnL = Double.parseDouble(b.get("up").asText());
                            }
                        }
                    }

                    listener.onAccountUpdate(balance, unrealizedPnL);
                }
            }

        } catch (Exception e) {
            System.err.println("[WS] handleMessage failed: " + e.getMessage());
        }
    }

    public void stop() {
        connected = false;
        if (ws != null) {
            ws.close(1000, "User requested");
        }
    }

    public boolean isConnected() {
        return connected;
    }
}
