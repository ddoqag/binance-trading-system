package com.trading.adapter.execution;

import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.risk.CircuitBreaker;
import com.trading.infrastructure.execution.ws.BinanceWsApiClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;

/**
 * WebSocket Order Router
 *
 * <p>Integrates BinanceWsApiClient with existing execution flow:
 * <ul>
 *   <li>Circuit breaker integration</li>
 *   <li>Fallback to REST on WS failure</li>
 *   <li>Statistics tracking</li>
 * </ul>
 *
 * <p>Flow:
 * <pre>
 * sendOrder() -> [CircuitBreaker.allowRequest?] -> WS client -> success?
 *                                                      |              |
 *                                                    false        true
 *                                                      |              |
 *                                                  REST fallback   return
 * </pre>
 */
public class WsOrderRouter {

    private static final Logger log = LoggerFactory.getLogger(WsOrderRouter.class);

    // Circuit breaker: 5 failures -> open, 3 successes -> close
    private static final CircuitBreaker circuitBreaker = new CircuitBreaker(5, 3, 30_000, 3);

    private final BinanceWsApiClient wsClient;
    private final Executor callbackExecutor;

    // Statistics
    private final AtomicStats wsRequests = new AtomicStats();
    private final AtomicStats restRequests = new AtomicStats();
    private volatile boolean enabled = true;

    public WsOrderRouter(String apiKey, String apiSecret, boolean testnet) {
        this.wsClient = new BinanceWsApiClient(apiKey, apiSecret, testnet);
        this.callbackExecutor = Executors.newSingleThreadExecutor(r -> {
            Thread t = new Thread(r, "WsOrderRouter-callback");
            t.setDaemon(true);
            return t;
        });
    }

    // ========== Configuration ==========

    public void setProxy(String host, int port) {
        wsClient.setProxy(host, port);
    }

    public void setTimeout(int connectTimeoutMs, int readTimeoutMs) {
        wsClient.setTimeout(connectTimeoutMs, readTimeoutMs);
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public boolean isEnabled() {
        return enabled;
    }

    public boolean isWsConnected() {
        return wsClient.isConnected();
    }

    // ========== Connection ==========

    public void connect() {
        wsClient.connect();
    }

    public void disconnect() {
        wsClient.disconnect();
    }

    // ========== Order Operations ==========

    /**
     * Send order via WebSocket with REST fallback
     *
     * @return ExecutionReport if WS succeeded, null if should fallback to REST
     */
    public ExecutionReport sendOrder(Order order) {
        if (!enabled) {
            log.debug("[WsOrderRouter] WS disabled, fallback to REST");
            return null;
        }

        if (!circuitBreaker.allowRequest()) {
            log.debug("[WsOrderRouter] Circuit breaker open, fallback to REST");
            return null;
        }

        if (!wsClient.isConnected()) {
            log.debug("[WsOrderRouter] WS not connected, fallback to REST");
            return null;
        }

        try {
            CompletableFuture<ExecutionReport> future = wsClient.placeOrder(order);
            ExecutionReport report = future.get();

            if (report != null && isTerminalStatus(report.getStatus())) {
                circuitBreaker.recordSuccess();
                wsRequests.recordSuccess();
                return report;
            } else if (report != null && report.getRejectReason() != null) {
                // WS returned error, don't fallback to REST for rejection
                circuitBreaker.recordFailure();
                wsRequests.recordFailure();
                return report;
            } else {
                return report;
            }

        } catch (Exception e) {
            log.warn("[WsOrderRouter] WS failed: {}, fallback to REST", e.getMessage());
            circuitBreaker.recordFailure();
            wsRequests.recordFailure();
            return null;
        }
    }

    private boolean isTerminalStatus(com.trading.domain.trading.model.OrderStatus status) {
        return status == com.trading.domain.trading.model.OrderStatus.FILLED ||
               status == com.trading.domain.trading.model.OrderStatus.CANCELLED ||
               status == com.trading.domain.trading.model.OrderStatus.REJECTED ||
               status == com.trading.domain.trading.model.OrderStatus.EXPIRED;
    }

    /**
     * Cancel order via WebSocket with REST fallback
     */
    public boolean cancelOrder(String clientOrderId, long binanceOrderId, String symbol) {
        if (!enabled || !wsClient.isConnected()) {
            return false;
        }

        try {
            CompletableFuture<ExecutionReport> future =
                    wsClient.cancelOrder(clientOrderId, binanceOrderId, symbol);
            ExecutionReport report = future.get();
            return report != null && report.getStatus() == com.trading.domain.trading.model.OrderStatus.CANCELLED;
        } catch (Exception e) {
            log.warn("[WsOrderRouter] Cancel via WS failed: {}", e.getMessage());
            return false;
        }
    }

    // ========== Circuit Breaker ==========

    public boolean isCircuitOpen() {
        return circuitBreaker.isOpen();
    }

    public void resetCircuitBreaker() {
        circuitBreaker.forceState(CircuitBreaker.State.CLOSED);
        log.info("[WsOrderRouter] Circuit breaker reset");
    }

    // ========== Statistics ==========

    public String getStats() {
        return String.format("WS: sent=%d success=%d failure=%d | REST fallback: %d",
                wsRequests.sent, wsRequests.success, wsRequests.failure, restRequests.sent);
    }

    private static class AtomicStats {
        java.util.concurrent.atomic.AtomicInteger sent = new java.util.concurrent.atomic.AtomicInteger(0);
        java.util.concurrent.atomic.AtomicInteger success = new java.util.concurrent.atomic.AtomicInteger(0);
        java.util.concurrent.atomic.AtomicInteger failure = new java.util.concurrent.atomic.AtomicInteger(0);

        void recordSuccess() {
            sent.incrementAndGet();
            success.incrementAndGet();
        }

        void recordFailure() {
            sent.incrementAndGet();
            failure.incrementAndGet();
        }
    }
}