package com.trading.adapter.execution;

import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.market.model.MarketData;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Algo Execution Engine
 * Implements TWAP, VWAP algorithms for order execution
 */
public class AlgoExecutionEngine {

    private final ConcurrentHashMap<String, AlgoExecution> activeAlgos = new ConcurrentHashMap<>();
    private final ScheduledExecutorService scheduler = Executors.newScheduledThreadPool(2);
    private final AtomicBoolean isRunning = new AtomicBoolean(false);

    public AlgoExecutionEngine() {
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

        scheduler.submit(() -> {
            execution.executeSlice();
        });

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
            scheduler.shutdown();
            activeAlgos.clear();
            System.out.println("[AlgoExecutionEngine] Stopped");
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
            this.sliceInterval = 60000; // 1 minute
        }

        @Override
        public Slice calculateNextSlice(MarketData marketData) {
            if (currentSlice >= numSlices) {
                return null;
            }

            long sliceTime = startTime + (currentSlice * sliceInterval);
            long now = System.currentTimeMillis();

            if (now < sliceTime) {
                return null;
            }

            Slice slice = new Slice();
            slice.orderId = order.getOrderId() + "_twap_" + currentSlice;
            slice.quantity = sliceQuantity;
            slice.orderType = OrderType.LIMIT;
            slice.timeInForce = 300;

            if (marketData != null) {
                if (order.getSide() == TradeDirection.LONG) {
                    slice.price = marketData.getAskPrice() - marketData.getSpread() * 0.1;
                } else {
                    slice.price = marketData.getBidPrice() + marketData.getSpread() * 0.1;
                }
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
            slice.orderType = OrderType.LIMIT;

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

            Slice slice = algo.calculateNextSlice(marketData);
            if (slice != null) {
                System.out.printf("[AlgoExecution] Sending slice: %s, qty=%.4f, price=%.2f%n",
                    slice.orderId, slice.quantity, slice.price);
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
