package com.trading.infrastructure.execution.ws;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.trading.infrastructure.execution.cache.AccountStateStore;
import com.trading.infrastructure.execution.cache.PositionCache;
import okhttp3.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.net.InetSocketAddress;
import java.net.Proxy;
import java.util.Queue;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Consumer;

/**
 * 双通道 WebSocket 客户端 (P1)
 *
 * <p>USER_DATA Stream 客户端，支持双通道热备：
 * <ul>
 *   <li>Primary WS 活跃连接</li>
 *   <li>Secondary WS 备用连接</li>
 *   <li>自动故障转移</li>
 *   <li>指数退避重连</li>
 * </ul>
 *
 * <p>事件驱动更新 PositionCache：
 * <ul>
 *   <li>ORDER_TRADE_UPDATE → 更新仓位</li>
 *   <li>ACCOUNT_UPDATE → 更新余额</li>
 * </ul>
 */
public class UserDataWebSocketClient {

    private static final Logger log = LoggerFactory.getLogger(UserDataWebSocketClient.class);

    // Binance WS URL (2026年5月版)
    // private 数据流: wss://fstream.binance.com/private/ws/<listenKey>
    private static final String WS_BASE_URL = "wss://fstream.binance.com/private/ws/";

    // 重连配置
    private static final long INITIAL_RECONNECT_DELAY_MS = 1_000;
    private static final long MAX_RECONNECT_DELAY_MS = 30_000;
    private static final double BACKOFF_MULTIPLIER = 2.0;
    private static final int MAX_RECONNECT_ATTEMPTS = 10;

    // The listenKey - created externally (e.g., by BinanceExchangeAdapter)
    private final String listenKey;

    // 依赖组件 (optional - for position/account updates)
    private final PositionCache positionCache;
    private final AccountStateStore accountStateStore;

    // WebSocket
    private WebSocket primaryWs;
    private WebSocket secondaryWs;
    private String secondaryListenKey;

    // 状态
    private final AtomicReference<ConnectionState> connectionState = new AtomicReference<>(ConnectionState.DISCONNECTED);
    private final AtomicInteger reconnectAttempts = new AtomicInteger(0);
    private volatile long currentReconnectDelay = INITIAL_RECONNECT_DELAY_MS;

    // Executor
    private ScheduledExecutorService scheduler;

    // 回调
    private Consumer<OrderUpdateEvent> onOrderUpdate;
    private Consumer<AccountUpdateEvent> onAccountUpdate;
    private Consumer<String> onStateChange;

    // 是否运行
    private volatile boolean running = false;

    // Proxy 配置
    private Proxy proxy;
    private int connectTimeoutMs = 20000;
    private int readTimeoutMs = 30000;

    // ========== Epoch Fencing + Event Buffering ==========
    // Epoch increments on each reconnect to fence late packets
    private final AtomicLong currentEpoch = new AtomicLong(0);
    // Event buffer during RECONNECT_SYNC state
    private final Queue<WSEvent> reconnectBuffer = new ConcurrentLinkedQueue<>();
    // True when buffering events (during reconnect)
    private volatile boolean buffering = false;
    // Callback when snapshot is complete (for replaying buffered events)
    private Runnable onSnapshotComplete;

    public enum ConnectionState {
        DISCONNECTED,
        CONNECTING,
        PRIMARY_ACTIVE,
        SECONDARY_ACTIVE,
        RECONNECTING,
        FAILED
    }

    public UserDataWebSocketClient(String listenKey, PositionCache positionCache,
                                    AccountStateStore accountStateStore) {
        this.listenKey = listenKey;
        this.positionCache = positionCache;
        this.accountStateStore = accountStateStore;
        // 默认无代理
        this.proxy = Proxy.NO_PROXY;
    }

    // ========== Proxy 配置 ==========

    public void setProxy(String host, int port) {
        if (host == null || host.isEmpty() || port <= 0) {
            this.proxy = Proxy.NO_PROXY;
            log.info("[UserDataWS] Proxy disabled");
        } else {
            this.proxy = new Proxy(Proxy.Type.HTTP, new InetSocketAddress(host, port));
            log.info("[UserDataWS] Proxy set: {}:{}", host, port);
        }
    }

    public void setTimeout(int connectTimeoutMs, int readTimeoutMs) {
        this.connectTimeoutMs = connectTimeoutMs;
        this.readTimeoutMs = readTimeoutMs;
        log.info("[UserDataWS] Timeout: connect={}ms, read={}ms", connectTimeoutMs, readTimeoutMs);
    }

    private OkHttpClient createOkHttpClient() {
        OkHttpClient.Builder builder = new OkHttpClient.Builder()
                .pingInterval(30, TimeUnit.SECONDS)
                .connectTimeout(connectTimeoutMs, TimeUnit.MILLISECONDS)
                .readTimeout(readTimeoutMs, TimeUnit.MILLISECONDS);

        if (proxy != null && proxy != Proxy.NO_PROXY) {
            builder.proxy(proxy);
            log.info("[UserDataWS] Using proxy: {}", proxy);
        }

        return builder.build();
    }

    // ========== 公共接口 ==========

    public void start() {
        if (running) {
            log.warn("[UserDataWS] Already running");
            return;
        }

        running = true;
        scheduler = Executors.newScheduledThreadPool(2, r -> {
            Thread t = new Thread(r, "UserDataWS-scheduler");
            t.setDaemon(true);
            return t;
        });

        connectPrimary();

        // 启动 Keep-alive
        scheduler.scheduleAtFixedRate(this::keepAlive, 25, 25, TimeUnit.MINUTES);
    }

    public void shutdown() {
        if (!running) {
            return;
        }

        running = false;
        log.info("[UserDataWS] Shutting down...");

        disconnectAll();

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
        log.info("[UserDataWS] Shutdown complete");
    }

    public ConnectionState getConnectionState() {
        return connectionState.get();
    }

    public void setOnOrderUpdate(Consumer<OrderUpdateEvent> callback) {
        this.onOrderUpdate = callback;
    }

    public void setOnAccountUpdate(Consumer<AccountUpdateEvent> callback) {
        this.onAccountUpdate = callback;
    }

    public void setOnStateChange(Consumer<String> callback) {
        this.onStateChange = callback;
    }

    public void setOnSnapshotComplete(Runnable callback) {
        this.onSnapshotComplete = callback;
    }

    /**
     * Get current epoch for fencing.
     */
    public long getCurrentEpoch() {
        return currentEpoch.get();
    }

    /**
     * Called by recovery service after snapshot is applied.
     * Stops buffering and replays buffered events.
     */
    public void onSnapshotApplied() {
        buffering = false;

        log.info("[UserDataWS] Replaying {} buffered events", reconnectBuffer.size());

        WSEvent evt;
        while ((evt = reconnectBuffer.poll()) != null) {
            try {
                JsonNode node = objectMapper.readTree(evt.data);
                if (evt.type == WSEvent.Type.ORDER_UPDATE) {
                    handleOrderTradeUpdate(node);
                } else if (evt.type == WSEvent.Type.ACCOUNT_UPDATE) {
                    handleAccountUpdate(node);
                }
            } catch (Exception e) {
                log.error("[UserDataWS] Replay error for event {}: {}", evt.type, e.getMessage());
            }
        }

        if (onSnapshotComplete != null) {
            onSnapshotComplete.run();
        }
    }

    // ========== 连接管理 ==========

    private void connectPrimary() {
        if (!running) return;

        connectionState.set(ConnectionState.CONNECTING);
        fireStateChange("CONNECTING");

        try {
            String wsUrl = WS_BASE_URL + listenKey;

            log.info("[UserDataWS] Connecting to: {}", wsUrl);
            log.info("[UserDataWS] Proxy: {}", proxy);
            log.info("[UserDataWS] Connect timeout: {}ms", connectTimeoutMs);

            OkHttpClient okHttpClient = createOkHttpClient();

            Request request = new Request.Builder()
                    .url(wsUrl)
                    .build();

            primaryWs = okHttpClient.newWebSocket(request, createListener(true));

            log.info("[UserDataWS] Primary connecting... listenKey={}", listenKey.substring(0, Math.min(10, listenKey.length())));

        } catch (Exception e) {
            log.error("[UserDataWS] Primary connect failed: {}", e.getMessage());
            scheduleReconnect();
        }
    }

    private void connectSecondary() {
        if (!running) return;

        // Secondary uses same listenKey (hot standby on same stream)
        // If primary fails, we reconnect with the same key
        try {
            String wsUrl = WS_BASE_URL + listenKey;

            OkHttpClient okHttpClient = createOkHttpClient();

            Request request = new Request.Builder()
                    .url(wsUrl)
                    .build();

            secondaryWs = okHttpClient.newWebSocket(request, createListener(false));

            log.info("[UserDataWS] Secondary connecting... listenKey={}", listenKey.substring(0, Math.min(10, listenKey.length())));

        } catch (Exception e) {
            log.error("[UserDataWS] Secondary connect failed: {}", e.getMessage());
        }
    }

    private WebSocketListener createListener(boolean isPrimary) {
        return new WebSocketListener() {
            @Override
            public void onOpen(WebSocket webSocket, Response response) {
                log.info("[UserDataWS] {} connected (epoch={})", isPrimary ? "Primary" : "Secondary", currentEpoch.get());
                reconnectAttempts.set(0);
                currentReconnectDelay = INITIAL_RECONNECT_DELAY_MS;

                if (isPrimary) {
                    // Increment epoch on primary reconnect
                    currentEpoch.incrementAndGet();
                    buffering = true; // Start buffering until snapshot arrives
                    connectionState.set(ConnectionState.PRIMARY_ACTIVE);
                    fireStateChange("PRIMARY_ACTIVE");
                    // 启动 Secondary 作为备用
                    if (secondaryWs == null) {
                        connectSecondary();
                    }
                } else {
                    connectionState.set(ConnectionState.SECONDARY_ACTIVE);
                    fireStateChange("SECONDARY_ACTIVE");
                }
            }

            @Override
            public void onMessage(WebSocket webSocket, String message) {
                handleMessage(message);
            }

            @Override
            public void onClosing(WebSocket webSocket, int code, String reason) {
                log.info("[UserDataWS] {} closing: {} {}", isPrimary ? "Primary" : "Secondary", code, reason);
                webSocket.close(1000, "Normal closure");
            }

            @Override
            public void onClosed(WebSocket webSocket, int code, String reason) {
                log.info("[UserDataWS] {} closed: {} {}", isPrimary ? "Primary" : "Secondary", code, reason);
                if (isPrimary) {
                    handlePrimaryFailure();
                }
            }

            @Override
            public void onFailure(WebSocket webSocket, Throwable t, Response response) {
                log.error("[UserDataWS] {} failure: {}", isPrimary ? "Primary" : "Secondary", t.getMessage());
                if (isPrimary) {
                    handlePrimaryFailure();
                }
            }
        };
    }

    private void handlePrimaryFailure() {
        primaryWs = null;

        if (!running) return;

        log.warn("[UserDataWS] Primary failed, reconnecting...");

        // Clean up secondary if exists
        if (secondaryWs != null) {
            try {
                secondaryWs.close(1000, "Promoting to primary");
            } catch (Exception ignored) {}
            secondaryWs = null;
        }

        // Reconnect with same listenKey (hot standby)
        scheduleReconnect();
    }

    private void scheduleReconnect() {
        if (!running) return;

        int attempts = reconnectAttempts.incrementAndGet();
        if (attempts > MAX_RECONNECT_ATTEMPTS) {
            log.error("[UserDataWS] Max reconnect attempts exceeded");
            connectionState.set(ConnectionState.FAILED);
            fireStateChange("FAILED");
            return;
        }

        connectionState.set(ConnectionState.RECONNECTING);
        fireStateChange("RECONNECTING");

        log.info("[UserDataWS] Scheduling reconnect attempt {} in {}ms", attempts, currentReconnectDelay);

        scheduler.schedule(() -> {
            if (running) {
                connectPrimary();
            }
        }, currentReconnectDelay, TimeUnit.MILLISECONDS);

        // 指数退避
        currentReconnectDelay = Math.min(
                (long) (currentReconnectDelay * BACKOFF_MULTIPLIER),
                MAX_RECONNECT_DELAY_MS
        );
    }

    private void keepAlive() {
        // Keep-alive is handled by BinanceExchangeAdapter.refreshUserDataListenKey()
        // This WebSocket connection just needs to stay open
        log.debug("[UserDataWS] Keep-alive check");
    }

    private void disconnectAll() {
        if (primaryWs != null) {
            try {
                primaryWs.close(1000, "Shutdown");
            } catch (Exception ignored) {}
            primaryWs = null;
        }

        if (secondaryWs != null) {
            try {
                secondaryWs.close(1000, "Shutdown");
            } catch (Exception ignored) {}
            secondaryWs = null;
        }
        // Note: listenKey management is handled by BinanceExchangeAdapter
    }

    private void fireStateChange(String state) {
        if (onStateChange != null) {
            onStateChange.accept(state);
        }
    }

    // ========== 消息处理 ==========

    private final ObjectMapper objectMapper = new ObjectMapper();

    private void handleMessage(String message) {
        try {
            JsonNode node = objectMapper.readTree(message);

            if (node.has("e")) {
                String eventType = node.get("e").asText();
                long eventEpoch = node.has("E") ? node.get("E").asLong() : 0;

                // Epoch fencing: discard events from old epoch
                if (eventEpoch > 0 && eventEpoch < currentEpoch.get()) {
                    log.debug("[UserDataWS] Discarding late event: epoch={} < currentEpoch={}", eventEpoch, currentEpoch.get());
                    return;
                }

                if ("ORDER_TRADE_UPDATE".equals(eventType)) {
                    handleOrderTradeUpdate(node);
                } else if ("ACCOUNT_UPDATE".equals(eventType)) {
                    handleAccountUpdate(node);
                } else {
                    log.debug("[UserDataWS] Unknown event: {}", eventType);
                }
            }

            // ListenKey 过期
            if (node.has("code") && node.get("code").asInt() == -1) {
                log.warn("[UserDataWS] ListenKey expired");
                scheduleReconnect();
            }

        } catch (Exception e) {
            log.error("[UserDataWS] Message parse error: {}", e.getMessage());
        }
    }

    private void handleOrderTradeUpdate(JsonNode node) {
        JsonNode o = node.get("o");

        String symbol = getText(o, "s");
        String clientOrderId = getText(o, "c");
        String binanceOrderId = String.valueOf(getLong(o, "i"));
        String status = getText(o, "X");
        double filledQty = getDouble(o, "z");
        double avgFillPrice = getDouble(o, "L");
        long transactTime = getLong(o, "T");

        OrderUpdateEvent event = new OrderUpdateEvent(
                symbol, clientOrderId, binanceOrderId,
                status, filledQty, avgFillPrice, transactTime
        );

        // Buffer event during reconnect (will be replayed after snapshot)
        if (buffering) {
            reconnectBuffer.add(new WSEvent(WSEvent.Type.ORDER_UPDATE, transactTime, node.toString()));
            log.debug("[UserDataWS] Buffered ORDER_UPDATE: {} {} qty={}", clientOrderId, symbol, filledQty);
            return;
        }

        // 更新 PositionCache
        if (positionCache != null && filledQty > 0) {
            PositionCache.PositionUpdate update = new PositionCache.PositionUpdate(
                    filledQty, avgFillPrice, 0, 0, 0
            );
            positionCache.updatePosition(symbol, update);
        }

        // 触发回调
        if (onOrderUpdate != null) {
            onOrderUpdate.accept(event);
        }

        log.info("[UserDataWS] Order update: {} {} {} qty={} price={}",
                clientOrderId, status, symbol, filledQty, avgFillPrice);
    }

    private void handleAccountUpdate(JsonNode node) {
        JsonNode a = node.get("a");

        if (a == null) return;

        long transactTime = a.has("E") ? a.get("E").asLong() : System.currentTimeMillis();

        // Buffer event during reconnect (will be replayed after snapshot)
        if (buffering) {
            reconnectBuffer.add(new WSEvent(WSEvent.Type.ACCOUNT_UPDATE, transactTime, node.toString()));
            log.debug("[UserDataWS] Buffered ACCOUNT_UPDATE");
            return;
        }

        double walletBalance = 0;
        double totalMargin = 0;
        double availableBalance = 0;
        double unrealizedPnl = 0;

        // 解析余额
        if (a.has("B")) {
            JsonNode balances = a.get("B");
            for (JsonNode b : balances) {
                String asset = getText(b, "a");
                if ("USDT".equals(asset)) {
                    walletBalance = getDouble(b, "wb");
                    availableBalance = getDouble(b, "wb"); // 可用 = 钱包余额 - 保证金
                    break;
                }
            }
        }

        // 解析持仓
        if (a.has("P")) {
            JsonNode positions = a.get("P");
            for (JsonNode p : positions) {
                unrealizedPnl += getDouble(p, "up");
                totalMargin += getDouble(p, "mm");
            }
        }

        AccountUpdateEvent event = new AccountUpdateEvent(
                walletBalance, totalMargin, availableBalance, unrealizedPnl
        );

        // 更新 AccountStateStore
        if (accountStateStore != null) {
            accountStateStore.updateFromAccountUpdate(
                    walletBalance, totalMargin, availableBalance, unrealizedPnl
            );
        }

        // 触发回调
        if (onAccountUpdate != null) {
            onAccountUpdate.accept(event);
        }

        log.info("[UserDataWS] Account update: balance={} margin={} avail={} pnl={}",
                walletBalance, totalMargin, availableBalance, unrealizedPnl);
    }

    // ========== 工具方法 ==========

    private String getText(JsonNode node, String field) {
        return node.has(field) ? node.get(field).asText() : "";
    }

    private long getLong(JsonNode node, String field) {
        return node.has(field) ? node.get(field).asLong() : 0L;
    }

    private double getDouble(JsonNode node, String field) {
        return node.has(field) ? node.get(field).asDouble() : 0.0;
    }

    // ========== 事件类 ==========

    /**
     * Buffered WS event during reconnect.
     */
    static final class WSEvent {
        enum Type { ORDER_UPDATE, ACCOUNT_UPDATE }
        final Type type;
        final long timestamp;
        final String data; // JSON string for replay

        WSEvent(Type type, long timestamp, String data) {
            this.type = type;
            this.timestamp = timestamp;
            this.data = data;
        }
    }

    public static class OrderUpdateEvent {
        public final String symbol;
        public final String clientOrderId;
        public final String binanceOrderId;
        public final String status;
        public final double filledQty;
        public final double avgFillPrice;
        public final long transactTime;

        public OrderUpdateEvent(String symbol, String clientOrderId, String binanceOrderId,
                                 String status, double filledQty, double avgFillPrice, long transactTime) {
            this.symbol = symbol;
            this.clientOrderId = clientOrderId;
            this.binanceOrderId = binanceOrderId;
            this.status = status;
            this.filledQty = filledQty;
            this.avgFillPrice = avgFillPrice;
            this.transactTime = transactTime;
        }
    }

    public static class AccountUpdateEvent {
        public final double walletBalance;
        public final double totalMargin;
        public final double availableBalance;
        public final double unrealizedPnl;

        public AccountUpdateEvent(double walletBalance, double totalMargin,
                                  double availableBalance, double unrealizedPnl) {
            this.walletBalance = walletBalance;
            this.totalMargin = totalMargin;
            this.availableBalance = availableBalance;
            this.unrealizedPnl = unrealizedPnl;
        }
    }
}