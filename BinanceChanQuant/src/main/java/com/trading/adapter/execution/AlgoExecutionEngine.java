package com.trading.adapter.execution;

import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.OrderStatus;
import com.trading.domain.market.model.MarketData;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.List;

/**
 * Algo Execution Engine
 * Implements TWAP, VWAP algorithms for order execution
 */
public class AlgoExecutionEngine {

    private final ConcurrentHashMap<String, AlgoExecution> activeAlgos = new ConcurrentHashMap<>();
    private final ScheduledExecutorService scheduler = Executors.newScheduledThreadPool(2, r -> {
        Thread t = new Thread(r);
        t.setDaemon(true);
        return t;
    });
    private final AtomicBoolean isRunning = new AtomicBoolean(false);
    private final List<AlgoExecutionListener> listeners = new CopyOnWriteArrayList<>();
    private BinanceExchangeAdapter exchangeAdapter;

    public AlgoExecutionEngine() {
    }

    /**
     * Set exchange adapter for live trading
     */
    public void setExchangeAdapter(BinanceExchangeAdapter adapter) {
        this.exchangeAdapter = adapter;
    }

    /**
     * Start algo execution for an order
     */
    public void startAlgo(Order order, MarketData marketData) {
        if (!isRunning.get()) {
            return;
        }

        String algoType = order.getStrategy(); // Using strategy field as algo type for simplicity
        AlgoStrategy algo = createAlgoStrategy(algoType, order);

        if (algo == null) {
            return;
        }

        AlgoExecution execution = new AlgoExecution(order, algo, marketData);
        activeAlgos.put(order.getOrderId(), execution);

        // Send first slice immediately, then schedule subsequent slices
        scheduler.submit(() -> {
            execution.executeSlice(); // First slice immediate
        });

        // Schedule periodic checks for subsequent slices
        scheduler.scheduleAtFixedRate(() -> {
            AlgoExecution exec = activeAlgos.get(order.getOrderId());
            if (exec != null && !exec.isDone() && exec.shouldExecute()) {
                exec.executeSlice();
            }
        }, 1, 1, TimeUnit.SECONDS);

        System.out.printf("[AlgoExecutionEngine] Started %s algo for order %s%n",
            algoType, order.getOrderId());
    }

    /**
     * Stop algo execution
     */
    public void stopAlgo(String orderId) {
        AlgoExecution execution = activeAlgos.remove(orderId);
        if (execution != null) {
            execution.stop();
        }
    }

    /**
     * Update fill status
     */
    public void updateFill(String orderId, double fillQty, double fillPrice) {
        AlgoExecution execution = activeAlgos.get(orderId);
        if (execution != null) {
            execution.updateFill(fillQty, fillPrice);
        }
    }

    /**
     * Start the engine
     */
    public void start() {
        if (isRunning.compareAndSet(false, true)) {
            scheduler.scheduleAtFixedRate(this::checkAlgos, 1, 1, TimeUnit.SECONDS);
            System.out.println("[AlgoExecutionEngine] Started");
        }
    }

    /**
     * Stop the engine
     */
    public void stop() {
        if (isRunning.compareAndSet(true, false)) {
            scheduler.shutdownNow();
            activeAlgos.clear();
            System.out.println("[AlgoExecutionEngine] Stopped");
        }
    }

    /**
     * Add a listener for algo completion events
     */
    public void addListener(AlgoExecutionListener listener) {
        if (listener != null) {
            listeners.add(listener);
        }
    }

    /**
     * Remove a listener
     */
    public void removeListener(AlgoExecutionListener listener) {
        listeners.remove(listener);
    }

    /**
     * Notify all listeners of algo completion
     */
    private void notifyCompletion(String orderId, String symbol, AlgoCompletionReason reason) {
        for (AlgoExecutionListener listener : listeners) {
            try {
                listener.onAlgoCompleted(orderId, symbol, reason);
            } catch (Exception e) {
                System.err.printf("[AlgoExecutionEngine] Listener notification error: %s%n", e.getMessage());
            }
        }
    }

    private AlgoStrategy createAlgoStrategy(String algoType, Order order) {
        if (algoType == null || algoType.isEmpty()) {
            return null;
        }

        switch (algoType.toUpperCase()) {
            case "TWAP":
            case "PASSIVE_TWAP":
                return new TWAPAlgo(order);
            case "VWAP":
                return new VWAPAlgo(order);
            default:
                return null;
        }
    }

    private void checkAlgos() {
        for (AlgoExecution execution : activeAlgos.values()) {
            if (!execution.isDone() && execution.shouldExecute()) {
                execution.executeSlice();
            }
        }
    }

    // Algo Strategy Interface
    public interface AlgoStrategy {
        Slice calculateNextSlice(MarketData marketData);
        boolean isDone();
        AlgoStatus getStatus();
    }

    // TWAP Algorithm
    public static class TWAPAlgo implements AlgoStrategy {
        private final Order order;
        private final double totalQuantity;
        private double sliceQuantity;
        private final int numSlices;
        private int currentSlice = 0;
        private final long startTime;
        private final long sliceInterval;

        public TWAPAlgo(Order order) {
            this.order = order;
            this.totalQuantity = order.getQuantity();
            this.numSlices = 10;
            this.sliceQuantity = totalQuantity / numSlices;
            this.startTime = System.currentTimeMillis();
            this.sliceInterval = 10000; // 10 seconds for live trading (reduced from 60s)
        }

        @Override
        public Slice calculateNextSlice(MarketData marketData) {
            if (currentSlice >= numSlices) {
                return null;
            }

            long sliceTime = startTime + (currentSlice * sliceInterval);
            long now = System.currentTimeMillis();

            // For live trading, reduce first-slice delay to 5 seconds for faster execution
            if (currentSlice == 0 && (now - startTime) < 6000) {
                // Allow immediate first slice for live trading
            } else if (now < sliceTime) {
                return null;
            }

            Slice slice = new Slice();
            slice.orderId = order.getOrderId() + "_twap_" + currentSlice;
            slice.quantity = sliceQuantity;
            slice.orderType = OrderType.LIMIT;
            slice.timeInForce = 300; // GTC-like behavior with timeInForce

            // Use order's original price as fallback when marketData is null
            double referencePrice = order.getPrice();
            if (marketData != null && marketData.getLastPrice() > 0) {
                referencePrice = marketData.getLastPrice();
            }

            // Calculate price: use opponent price for immediate fill (Taker strategy)
            // LONG (开多): use ask to take from seller immediately
            // SHORT (开空): use bid to take from buyer immediately
            // This ensures fill despite network delay
            if (order.getSide() == TradeDirection.LONG) {
                // 开多：追卖一价(ask)，立即吃单成交
                slice.price = (marketData != null && marketData.getAskPrice() > 0)
                    ? marketData.getAskPrice() : referencePrice;
            } else {
                // 开空：追买一价(bid)，立即吃单成交
                slice.price = (marketData != null && marketData.getBidPrice() > 0)
                    ? marketData.getBidPrice() : referencePrice;
            }

            currentSlice++;
            return slice;
        }

        @Override
        public boolean isDone() {
            return currentSlice >= numSlices;
        }

        @Override
        public AlgoStatus getStatus() {
            AlgoStatus status = new AlgoStatus();
            status.algoType = "TWAP";
            status.progress = (double) currentSlice / numSlices;
            status.slicesCompleted = currentSlice;
            status.totalSlices = numSlices;
            return status;
        }
    }

    // VWAP Algorithm
    public static class VWAPAlgo implements AlgoStrategy {
        private final Order order;
        private final double totalQuantity;
        private int currentPeriod = 0;
        private final int totalPeriods = 288; // 24 hours * 12 (5-min periods)

        public VWAPAlgo(Order order) {
            this.order = order;
            this.totalQuantity = order.getQuantity();
        }

        @Override
        public Slice calculateNextSlice(MarketData marketData) {
            int nowPeriod = getCurrentPeriod();

            if (nowPeriod <= currentPeriod || nowPeriod >= totalPeriods) {
                return null;
            }

            // Simplified: equal distribution
            double remainingQty = totalQuantity * (1.0 - (double) currentPeriod / totalPeriods);
            double sliceQty = Math.min(remainingQty, totalQuantity * 0.1);

            Slice slice = new Slice();
            slice.orderId = order.getOrderId() + "_vwap_" + currentPeriod;
            slice.quantity = sliceQty;
            slice.orderType = OrderType.IOC;

            if (marketData != null) {
                slice.price = marketData.getMidPrice();
            }

            currentPeriod++;
            return slice;
        }

        private int getCurrentPeriod() {
            long seconds = (System.currentTimeMillis() / 1000) % 86400;
            return (int) (seconds / 300);
        }

        @Override
        public boolean isDone() {
            return currentPeriod >= totalPeriods;
        }

        @Override
        public AlgoStatus getStatus() {
            AlgoStatus status = new AlgoStatus();
            status.algoType = "VWAP";
            status.progress = (double) currentPeriod / totalPeriods;
            status.slicesCompleted = currentPeriod;
            status.totalSlices = totalPeriods;
            return status;
        }
    }

    // Algo Execution Instance
    private class AlgoExecution {
        private final Order order;
        private final AlgoStrategy algo;
        private final MarketData marketData;
        private double filledQuantity = 0.0;
        private long lastExecuteTime = 0;
        private final AtomicBoolean running = new AtomicBoolean(true);
        private final AtomicBoolean completionNotified = new AtomicBoolean(false);
        private int consecutiveFailures = 0;
        private static final int MAX_CONSECUTIVE_FAILURES = 3;

        public AlgoExecution(Order order, AlgoStrategy algo, MarketData marketData) {
            this.order = order;
            this.algo = algo;
            this.marketData = marketData;
        }

        public void executeSlice() {
            if (!running.get() || algo.isDone()) {
                stop();
                return;
            }

            // Force sync position before checking
            if (exchangeAdapter != null) {
                // Sync to get fresh position data (silent since sendLiveOrder will also sync)
                exchangeAdapter.syncPositionsFromExchange(true);
                double currentPos = exchangeAdapter.getCurrentPosition();
                TradeDirection desiredDir = order.getSide();

                // If we already have a position in the same direction, stop algo
                if ((currentPos > 0 && desiredDir == TradeDirection.LONG) ||
                    (currentPos < 0 && desiredDir == TradeDirection.SHORT)) {
                    System.out.printf("[AlgoExecution] Stopping %s: already have position %.4f in same direction%n",
                        order.getStrategy(), currentPos);
                    if (completionNotified.compareAndSet(false, true)) {
                        notifyCompletion(order.getOrderId(), order.getSymbol(), AlgoCompletionReason.POSITION_MATCHED);
                    }
                    stop();
                    return;
                }

                // P1 FIX: Check margin sufficiency before sending slice
                // Force sync balance to get fresh data (margin check fails without this)
                exchangeAdapter.syncBalanceFromExchange();
                double availableBalance = exchangeAdapter.getAvailableBalance();
                double leverage = 10.0; // Default from config
                double price = order.getPrice() > 0 ? order.getPrice() : 80000.0;
                double sliceQty = order.getQuantity() / 10.0; // TWAP splits into 10 slices
                double requiredMargin = sliceQty * price / leverage;

                // Only reject if balance is confirmed insufficient (not just un-synced)
                if (availableBalance > 0.01 && availableBalance < requiredMargin * 1.2) { // 20% buffer for margin
                    System.out.printf("[AlgoExecution] Insufficient margin for slice: required=%.4f, available=%.4f%n",
                        requiredMargin, availableBalance);
                    consecutiveFailures++;
                    if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
                        System.out.printf("[AlgoExecution] Stopping TWAP: insufficient margin%n");
                        if (completionNotified.compareAndSet(false, true)) {
                            notifyCompletion(order.getOrderId(), order.getSymbol(), AlgoCompletionReason.FAILED);
                        }
                        stop();
                        return;
                    }
                    // Skip this slice, will retry next interval
                    return;
                }
            }

            Slice slice = algo.calculateNextSlice(marketData);
            if (slice != null) {
                System.out.printf("[AlgoExecution] Sending slice: %s, qty=%.4f, price=%.2f%n",
                    slice.orderId, slice.quantity, slice.price);

                // Send slice order to exchange - use strategy from original order
                Order sliceOrder = new Order(
                    slice.orderId,
                    order.getSymbol(),
                    order.getSide(),
                    slice.orderType,
                    slice.quantity,
                    slice.price,
                    order.getStrategy(),  // Use original order's strategy
                    order.getUrgency()
                );

                if (exchangeAdapter != null) {
                    ExecutionReport report = exchangeAdapter.sendOrder(sliceOrder);
                    if (report != null && report.getStatus() == OrderStatus.REJECTED) {
                        consecutiveFailures++;
                        String reason = report.getAvgFillPrice() > 0 ? "rejected" : "margin insufficient";
                        System.out.printf("[AlgoExecution] Slice %s failed (%s), failures=%d/%d%n",
                            slice.orderId, reason, consecutiveFailures, MAX_CONSECUTIVE_FAILURES);
                        if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
                            System.out.printf("[AlgoExecution] Stopping TWAP: too many failures%n");
                            if (completionNotified.compareAndSet(false, true)) {
                                notifyCompletion(order.getOrderId(), order.getSymbol(), AlgoCompletionReason.FAILED);
                            }
                            stop();
                            return;
                        }
                    } else if (report != null) {
                        consecutiveFailures = 0;
                        // Track fill to determine when TWAP is done
                        if (report.getStatus() == OrderStatus.FILLED) {
                            updateFill(report.getFilledQuantity(), report.getAvgFillPrice());
                        }
                    }
                }

                lastExecuteTime = System.currentTimeMillis();
            }
        }

        public void updateFill(double fillQty, double fillPrice) {
            filledQuantity += fillQty;
        }

        public boolean shouldExecute() {
            return System.currentTimeMillis() - lastExecuteTime > 1000;
        }

        public boolean isDone() {
            return algo.isDone() || filledQuantity >= order.getQuantity() * 0.95;
        }

        public void stop() {
            if (completionNotified.compareAndSet(false, true)) {
                notifyCompletion(order.getOrderId(), order.getSymbol(), AlgoCompletionReason.CANCELLED);
            }
            running.set(false);
            activeAlgos.remove(order.getOrderId());
        }
    }

    // Helper Classes
    public static class Slice {
        public String orderId;
        public double quantity;
        public double price;
        public OrderType orderType;
        public int timeInForce = 300;
    }

    public static class AlgoStatus {
        public String algoType;
        public double progress;
        public int slicesCompleted;
        public int totalSlices;
    }
}
