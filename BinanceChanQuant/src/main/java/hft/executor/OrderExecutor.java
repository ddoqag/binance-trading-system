package hft.executor;

import com.binance.connector.futures.client.impl.UMFuturesClientImpl;
import com.binance.connector.futures.client.utils.ProxyAuth;
import config.ConfigUtil;

import java.net.InetSocketAddress;
import java.net.Proxy;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Consumer;

/**
 * OrderExecutor - Order Execution Engine for HFT System
 *
 * Handles:
 * - Paper trading (simulated fills)
 * - Live trading (Binance API)
 * - Order state tracking
 * - Position management
 */
public class OrderExecutor {
    private final String symbol;
    private final boolean paperTrading;
    private final UMFuturesClientImpl client;

    private final Position position;
    private final Map<String, Order> orders = new ConcurrentHashMap<>();
    private final List<Order> history = new ArrayList<>();

    private final ScheduledExecutorService syncExecutor = Executors.newScheduledThreadPool(1);

    // Event callbacks
    private Consumer<Order> onOrderFilled;
    private Consumer<Order> onOrderCancelled;

    public OrderExecutor(String symbol, boolean paperTrading, String apiKey, String secret) {
        this.symbol = symbol;
        this.paperTrading = paperTrading;

        if (paperTrading) {
            this.client = null;
        } else {
            this.client = new UMFuturesClientImpl(apiKey, secret, ConfigUtil.isTestNet());
            setProxy();
            startOrderSync();
        }

        this.position = new Position(symbol);
    }

    private void setProxy() {
        try {
            String proxyHost = "127.0.0.1";
            int proxyPort = 7897;

            Proxy proxy = new Proxy(Proxy.Type.HTTP, new InetSocketAddress(proxyHost, proxyPort));
            ProxyAuth proxyAuth = new ProxyAuth(proxy, null);
            client.setProxy(proxyAuth);
            System.out.println("[EXEC] Proxy set: " + proxyHost + ":" + proxyPort);
        } catch (Exception e) {
            System.out.println("[EXEC] Proxy not configured: " + e.getMessage());
        }
    }

    private void startOrderSync() {
        syncExecutor.scheduleAtFixedRate(this::syncOpenOrders, 5, 5, TimeUnit.SECONDS);
    }

    /**
     * Place limit buy order
     */
    public Order placeLimitBuy(double price, double size, boolean postOnly) {
        if (paperTrading) {
            return simulateLimitOrder(Order.Side.BUY, price, size);
        }
        return placeLiveLimitOrder(Order.Side.BUY, price, size, postOnly);
    }

    /**
     * Place limit sell order
     */
    public Order placeLimitSell(double price, double size, boolean postOnly) {
        if (paperTrading) {
            return simulateLimitOrder(Order.Side.SELL, price, size);
        }
        return placeLiveLimitOrder(Order.Side.SELL, price, size, postOnly);
    }

    /**
     * Place market buy order
     */
    public Order placeMarketBuy(double size) {
        if (paperTrading) {
            return simulateMarketOrder(Order.Side.BUY, size);
        }
        return placeLiveMarketOrder(Order.Side.BUY, size);
    }

    /**
     * Place market sell order
     */
    public Order placeMarketSell(double size) {
        if (paperTrading) {
            return simulateMarketOrder(Order.Side.SELL, size);
        }
        return placeLiveMarketOrder(Order.Side.SELL, size);
    }

    /**
     * Cancel all open orders
     */
    public void cancelAll() {
        for (Order order : orders.values()) {
            if (order.isOpen()) {
                cancelOrder(order.id);
            }
        }
    }

    /**
     * Cancel specific order
     */
    public boolean cancelOrder(String orderId) {
        Order order = orders.get(orderId);
        if (order == null) return false;

        if (paperTrading) {
            order.updateStatus(Order.Status.CANCELLED);
            orders.remove(orderId);
            if (onOrderCancelled != null) onOrderCancelled.accept(order);
            return true;
        }

        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", symbol);
            params.put("orderId", order.binanceOrderId);
            Object resp = client.account().cancelOrder(params);

            order.updateStatus(Order.Status.CANCELLED);
            orders.remove(orderId);
            if (onOrderCancelled != null) onOrderCancelled.accept(order);
            return true;
        } catch (Exception e) {
            System.err.println("[EXEC] Cancel failed: " + e.getMessage());
            return false;
        }
    }

    // Paper trading simulations

    private Order simulateMarketOrder(Order.Side side, double size) {
        Order order = new Order(symbol, side, Order.Type.MARKET, 0, size);
        order.updateStatus(Order.Status.FILLED);
        order.avgPrice = getCurrentPrice();
        order.filled = size;

        recordOrder(order);
        position.update(order.avgPrice, order.filled, side);

        System.out.println("[PAPER] Market " + side + ": " + size + " @ " + order.avgPrice);
        return order;
    }

    private Order simulateLimitOrder(Order.Side side, double price, double size) {
        Order order = new Order(symbol, side, Order.Type.LIMIT, price, size);
        order.updateStatus(Order.Status.FILLED);
        order.avgPrice = price;
        order.filled = size;

        recordOrder(order);
        position.update(order.avgPrice, order.filled, side);

        System.out.println("[PAPER] Limit " + side + ": " + size + " @ " + price);
        return order;
    }

    // Live trading

    private Order placeLiveMarketOrder(Order.Side side, double size) {
        Order order = new Order(symbol, side, Order.Type.MARKET, 0, size);

        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", symbol);
            params.put("side", side == Order.Side.BUY ? "BUY" : "SELL");
            params.put("type", "MARKET");
            params.put("quantity", size);

            Object resp = client.account().newOrder(params);
            System.out.println("[LIVE] Market " + side + ": " + size + " -> " + resp);

            order.binanceOrderId = System.currentTimeMillis();
            order.updateStatus(Order.Status.OPEN);
            recordOrder(order);

            System.out.println("[LIVE] Market " + side + ": " + size + " (ID: " + order.binanceOrderId + ")");
            return order;
        } catch (Exception e) {
            order.updateStatus(Order.Status.REJECTED);
            System.err.println("[LIVE] Market order failed: " + e.getMessage());
            return order;
        }
    }

    private Order placeLiveLimitOrder(Order.Side side, double price, double size, boolean postOnly) {
        Order order = new Order(symbol, side, Order.Type.LIMIT, price, size);

        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", symbol);
            params.put("side", side == Order.Side.BUY ? "BUY" : "SELL");
            params.put("type", "LIMIT");
            params.put("price", price);
            params.put("quantity", size);
            params.put("timeInForce", postOnly ? "GTX" : "GTC");

            Object resp = client.account().newOrder(params);
            System.out.println("[LIVE] Limit " + side + ": " + size + " @ " + price + " -> " + resp);

            order.binanceOrderId = System.currentTimeMillis();
            order.updateStatus(Order.Status.OPEN);
            recordOrder(order);

            System.out.println("[LIVE] Limit " + side + ": " + size + " @ " + price + (postOnly ? " POST_ONLY" : ""));
            return order;
        } catch (Exception e) {
            order.updateStatus(Order.Status.REJECTED);
            System.err.println("[LIVE] Limit order failed: " + e.getMessage());
            return order;
        }
    }

    // Order sync from Binance - simplified for now

    private void syncOpenOrders() {
        // Simplified - just log that sync would happen
        // In production, implement proper order state sync
    }

    private void syncOrderStatus(Order order) {
        // Simplified
    }

    private void recordOrder(Order order) {
        orders.put(order.id, order);
        history.add(order);
    }

    private double getCurrentPrice() {
        return 50000.0;
    }

    // Getters

    public Position getPosition() { return position; }

    public List<Order> getOpenOrders() {
        List<Order> open = new ArrayList<>();
        for (Order o : orders.values()) {
            if (o.isOpen()) open.add(o);
        }
        return open;
    }

    public Order getOrder(String id) { return orders.get(id); }

    public void setOnOrderFilled(Consumer<Order> callback) { this.onOrderFilled = callback; }
    public void setOnOrderCancelled(Consumer<Order> callback) { this.onOrderCancelled = callback; }

    /**
     * Close executor and cleanup
     */
    public void close() {
        syncExecutor.shutdown();
        try {
            syncExecutor.awaitTermination(5, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
