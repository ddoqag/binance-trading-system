package com.trading.adapter.shadow;

import com.trading.domain.market.model.MarketData;
import plugin.StrategyPlugin;
import state.ChanMarketState;
import state.TradeDirection;
import state.TradeSignal;
import chan.ChanPricePoint;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.atomic.AtomicBoolean;
import java.util.stream.DoubleStream;

/**
 * 影子回测运行器 - 在实时行情上进行零影响的回测
 */
public class ShadowRunner implements Runnable {

    private static final Logger log = LoggerFactory.getLogger(ShadowRunner.class);
    private final String id;
    private final StrategyPlugin plugin;
    private final ShadowExecutionBook book;
    private final RingBuffer<PerformanceSnapshot> snapshots;
    private final AtomicBoolean running = new AtomicBoolean(false);
    private final int windowSize;

    private volatile double lastPrice = 0;
    private volatile ChanMarketState currentState = ChanMarketState.CONSOLIDATION;
    private volatile ChanPricePoint currentPoint;

    public ShadowRunner(String id, StrategyPlugin plugin, int windowSize) {
        this.id = id;
        this.plugin = plugin;
        this.windowSize = windowSize;
        this.book = new ShadowExecutionBook();
        this.snapshots = new RingBuffer<>(windowSize);
    }

    @Override
    public void run() {
        running.set(true);
        plugin.init();
        log.info("[ShadowRunner:{}] Started with windowSize={}", id, windowSize);
    }

    public void stop() {
        running.set(false);
        plugin.stop();
        log.info("[ShadowRunner:{}] Stopped - Fitness={}", id, getFitness());
    }

    public void onMarketData(MarketData data) {
        if (!running.get()) return;

        lastPrice = data.getLastPrice();

        // Create price point from market data
        this.currentPoint = createPricePoint(data.getLastPrice());

        state.TradeSignal signal = generateSignal(data);

        ShadowExecutionBook.ShadowOrder order = book.executeShadowOrder(signal, data);

        if (order.isFilled()) {
            PerformanceSnapshot snap = createSnapshot(order, data);
            snapshots.add(snap);
        }
    }

    private chan.ChanPricePoint createPricePoint(double price) {
        chan.ChanPricePoint pt = new chan.ChanPricePoint();
        pt.centerUp = price;
        pt.centerDown = price;
        pt.centerMid = price;
        pt.curPenHigh = price;
        pt.curPenLow = price;
        pt.divergencePrice = price;
        return pt;
    }

    public void onStateChange(ChanMarketState state) {
        this.currentState = state;
        if (running.get()) {
            plugin.onActive(state);
        }
    }

    private state.TradeSignal generateSignal(MarketData data) {
        ShadowMarketData smd = new ShadowMarketData(data);
        plugin.onTick(smd.getPrice(), smd.getMa20(), smd.getRsi(), currentPoint);
        state.TradeSignal signal = plugin.getTradeSignal(currentState, currentPoint);
        // Debug: log first 10 signals
        if (snapshots.size() < 10) {
            String dir = (signal == null) ? "NULL" : signal.direction.name();
            log.debug("[ShadowRunner:{}] state={} signal={} price={}", id, currentState, dir, smd.getPrice());
        }
        return signal;
    }

    private PerformanceSnapshot createSnapshot(ShadowExecutionBook.ShadowOrder order, MarketData data) {
        return new PerformanceSnapshot(
            System.currentTimeMillis(),
            order.getEntryPrice(),
            order.getExitPrice(),
            data.getLastPrice(),
            order.getPnl(),
            order.getReturnPercent(),
            order.getDirection(),
            order.isWin() ? 1 : 0
        );
    }

    public FitnessResult getFitness() {
        if (snapshots.isEmpty()) {
            return FitnessResult.zero();
        }

        double sharpe = calculateSharpe();
        double maxDD = calculateMaxDrawdown();
        double winRate = calculateWinRate();
        double profitFactor = calculateProfitFactor();
        double totalReturn = calculateTotalReturn();

        double score = 0.4 * Math.max(0, sharpe) +
                      0.3 * (1 - Math.min(1, maxDD)) +
                      0.2 * winRate +
                      0.1 * Math.min(1, profitFactor / 2.0);

        return new FitnessResult(score, sharpe, maxDD, winRate, profitFactor, totalReturn);
    }

    public String getId() { return id; }
    public StrategyPlugin getPlugin() { return plugin; }
    public boolean isRunning() { return running.get(); }

    // ========== 绩效计算 ==========

    private double calculateSharpe() {
        if (snapshots.size() < 5) return 0;

        double[] returns = toDoubleArray(snapshots, PerformanceSnapshot::getReturnPercent);
        double meanVal = mean(returns);
        double std = stddev(returns, meanVal);

        if (std == 0) return 0;
        return meanVal / std * Math.sqrt(252);
    }

    private double calculateMaxDrawdown() {
        if (snapshots.isEmpty()) return 0;

        double peak = Double.MIN_VALUE;
        double maxDD = 0;
        double equity = 0;

        for (PerformanceSnapshot snap : snapshots) {
            equity += snap.getPnl();
            if (equity > peak) peak = equity;
            double dd = (peak - equity) / (peak + 100000) * 100;
            if (dd > maxDD) maxDD = dd;
        }

        return maxDD;
    }

    private double calculateWinRate() {
        if (snapshots.isEmpty()) return 0;
        int wins = 0;
        for (PerformanceSnapshot snap : snapshots) {
            if (snap.getIsWin() == 1) wins++;
        }
        return (double) wins / snapshots.size();
    }

    private double calculateProfitFactor() {
        double grossProfit = 0;
        double grossLoss = 0;

        for (PerformanceSnapshot snap : snapshots) {
            if (snap.getPnl() > 0) grossProfit += snap.getPnl();
            else grossLoss += Math.abs(snap.getPnl());
        }

        if (grossLoss == 0) return grossProfit > 0 ? 99.0 : 0;
        return grossProfit / grossLoss;
    }

    private double calculateTotalReturn() {
        double total = 0;
        for (PerformanceSnapshot snap : snapshots) {
            total += snap.getPnl();
        }
        return total;
    }

    private static double[] toDoubleArray(RingBuffer<PerformanceSnapshot> buffer,
                                          java.util.function.ToDoubleFunction<PerformanceSnapshot> extractor) {
        double[] arr = new double[buffer.size()];
        for (int i = 0; i < arr.length; i++) {
            arr[i] = extractor.applyAsDouble(buffer.get(i));
        }
        return arr;
    }

    private static double mean(double[] arr) {
        return DoubleStream.of(arr).average().orElse(0);
    }

    private static double stddev(double[] arr, double meanVal) {
        double variance = DoubleStream.of(arr)
            .map(r -> (r - meanVal) * (r - meanVal))
            .average().orElse(0);
        return Math.sqrt(variance);
    }

    // ========== 内部类 ==========

    public static class PerformanceSnapshot {
        private final long timestamp;
        private final double entryPrice;
        private final double exitPrice;
        private final double currentPrice;
        private final double pnl;
        private final double returnPercent;
        private final TradeDirection direction;
        private final int isWin;

        public PerformanceSnapshot(long timestamp, double entryPrice, double exitPrice,
                                  double currentPrice, double pnl, double returnPercent,
                                  TradeDirection direction, int isWin) {
            this.timestamp = timestamp;
            this.entryPrice = entryPrice;
            this.exitPrice = exitPrice;
            this.currentPrice = currentPrice;
            this.pnl = pnl;
            this.returnPercent = returnPercent;
            this.direction = direction;
            this.isWin = isWin;
        }

        public long getTimestamp() { return timestamp; }
        public double getEntryPrice() { return entryPrice; }
        public double getExitPrice() { return exitPrice; }
        public double getCurrentPrice() { return currentPrice; }
        public double getPnl() { return pnl; }
        public double getReturnPercent() { return returnPercent; }
        public TradeDirection getDirection() { return direction; }
        public int getIsWin() { return isWin; }
    }
}
