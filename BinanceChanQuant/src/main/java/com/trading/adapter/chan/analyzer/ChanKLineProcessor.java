package com.trading.adapter.chan.analyzer;

import com.trading.domain.market.model.MarketData;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ConcurrentLinkedQueue;

/**
 * Chan K-Line Processor
 * Processes raw K-lines into Chan theory components:
 * - 分型 (Fenxing): Top/Bottom patterns
 * - 笔 (Bi): Trend lines with strength
 * - 线段 (Xianduan): Segments
 * - 中枢 (Zhongshu): Consolidation zones
 * - 背驰 (Beichi): Divergence
 */
public class ChanKLineProcessor {

    // Configuration
    private final int windowSize;
    private final double biStrengthThreshold;
    private final double fenxingThreshold;

    // Rolling window of processed K-lines
    private final ConcurrentLinkedQueue<KLine> klineWindow = new ConcurrentLinkedQueue<>();

    // Detected patterns
    private volatile List<Fenxing> fenxingList = new ArrayList<>();
    private volatile List<Bi> biList = new ArrayList<>();
    private volatile Zhongshu currentZhongshu = null;
    private volatile List<Zhongshu> zhongshuHistory = new ArrayList<>();

    public ChanKLineProcessor() {
        this(120, 0.7, 0.001);
    }

    public ChanKLineProcessor(int windowSize, double biStrengthThreshold, double fenxingThreshold) {
        this.windowSize = windowSize;
        this.biStrengthThreshold = biStrengthThreshold;
        this.fenxingThreshold = fenxingThreshold;
    }

    /**
     * Process new market data and update Chan analysis
     */
    public void processMarketData(MarketData data) {
        KLine kline = fromMarketData(data);
        addKLine(kline);
    }

    /**
     * Add K-line to window and update all Chan components
     */
    public void addKLine(KLine kline) {
        // Validate K-line data - reject obviously corrupted data
        if (kline == null || kline.high < kline.low ||
            kline.high > kline.close * 1.1 || kline.low < kline.close * 0.9 ||
            (kline.high - kline.low) > kline.close * 0.05) {
            // Range > 5% of price is suspicious for 1m candle - skip
            return;
        }

        klineWindow.add(kline);

        // Maintain window size
        while (klineWindow.size() > windowSize) {
            klineWindow.poll();
        }

        // Update analysis
        detectFenxing();
        if (fenxingList.size() >= 3) {
            detectBi();
        }
        if (biList.size() >= 2) {
            detectZhongshu();
        }
    }

    /**
     * Detect 顶分型 (Top Fenxing) and 底分型 (Bottom Fenxing)
     * Pattern: 5 consecutive K-lines where middle is highest/lowest
     */
    private void detectFenxing() {
        List<KLine> kl = new ArrayList<>(klineWindow);
        if (kl.size() < 5) return;

        fenxingList.clear();

        for (int i = 2; i < kl.size() - 2; i++) {
            KLine prev2 = kl.get(i - 2);
            KLine prev1 = kl.get(i - 1);
            KLine curr = kl.get(i);
            KLine next1 = kl.get(i + 1);
            KLine next2 = kl.get(i + 2);

            // 顶分型: current is highest
            if (isTopFenxing(prev2, prev1, curr, next1, next2)) {
                fenxingList.add(new Fenxing(Fenxing.Type.TOP, curr.timestamp, curr.high));
            }
            // 底分型: current is lowest
            else if (isBottomFenxing(prev2, prev1, curr, next1, next2)) {
                fenxingList.add(new Fenxing(Fenxing.Type.BOTTOM, curr.timestamp, curr.low));
            }
        }
    }

    private boolean isTopFenxing(KLine p2, KLine p1, KLine c, KLine n1, KLine n2) {
        return c.high > p2.high && c.high > p1.high && c.high > n1.high && c.high > n2.high
            && Math.abs(c.high - p2.high) > fenxingThreshold * p2.high;
    }

    private boolean isBottomFenxing(KLine p2, KLine p1, KLine c, KLine n1, KLine n2) {
        return c.low < p2.low && c.low < p1.low && c.low < n1.low && c.low < n2.low
            && Math.abs(c.low - p2.low) > fenxingThreshold * p2.low;
    }

    /**
     * Detect 笔 (Bi) - Basic trend lines
     */
    private void detectBi() {
        if (fenxingList.size() < 2) return;

        biList.clear();

        for (int i = 1; i < fenxingList.size(); i++) {
            Fenxing prev = fenxingList.get(i - 1);
            Fenxing curr = fenxingList.get(i);

            // Only process alternating fenxing (top-bottom or bottom-top)
            if (prev.type != curr.type) {
                double strength = calculateBiStrength(prev, curr);
                Bi.Direction dir = curr.type == Fenxing.Type.TOP ? Bi.Direction.DOWN : Bi.Direction.UP;

                biList.add(new Bi(prev.timestamp, curr.timestamp,
                    Math.min(prev.price, curr.price),
                    Math.max(prev.price, curr.price),
                    dir, strength));
            }
        }
    }

    private double calculateBiStrength(Fenxing a, Fenxing b) {
        double priceChange = Math.abs(a.price - b.price);
        double timeSpan = b.timestamp - a.timestamp;
        if (timeSpan == 0) return 0;
        return priceChange / timeSpan;
    }

    /**
     * Detect 中枢 (Zhongshu) - Consolidation zones
     * 中枢 = 3段以上的重叠区域
     */
    private void detectZhongshu() {
        if (biList.size() < 3) return;

        // Simple Zhongshu detection: find overlap of 3 consecutive Bi
        for (int i = 0; i <= biList.size() - 3; i++) {
            Bi b1 = biList.get(i);
            Bi b2 = biList.get(i + 1);
            Bi b3 = biList.get(i + 2);

            // Check if b1 and b3 overlap (same direction)
            if (b1.direction == b3.direction) {
                double overlapHigh = Math.max(b1.high, b3.high);
                double overlapLow = Math.min(b1.low, b3.low);

                // Valid overlap exists
                if (overlapHigh > overlapLow) {
                    double zg = overlapHigh;
                    double zd = overlapLow;
                    double gg = Math.max(b1.high, b3.high);
                    double dd = Math.min(b1.low, b3.low);

                    currentZhongshu = new Zhongshu(zg, zd, gg, dd, b1.startTime, b3.endTime);
                    // FIX: Limit zhongshuHistory size to prevent memory growth
                    if (zhongshuHistory.size() >= 10) {
                        zhongshuHistory.remove(0);
                    }
                    zhongshuHistory.add(currentZhongshu);
                }
            }
        }
    }

    /**
     * Check for 背驰 (Beichi/Divergence)
     */
    public BeichiResult checkBeichi() {
        if (biList.size() < 4) return BeichiResult.none();

        // Compare last two downward segments (下跌段)
        List<Bi> downSegments = new ArrayList<>();
        for (Bi bi : biList) {
            if (bi.direction == Bi.Direction.DOWN) {
                downSegments.add(bi);
            }
        }

        if (downSegments.size() < 2) return BeichiResult.none();

        Bi last = downSegments.get(downSegments.size() - 1);
        Bi prev = downSegments.get(downSegments.size() - 2);

        // Beichi: last segment makes new low but with less momentum
        if (last.low < prev.low && last.strength < prev.strength * biStrengthThreshold) {
            return new BeichiResult(true, BeichiResult.Type.BOTTOM, last.low, prev.strength - last.strength);
        }

        // Compare last two upward segments (上涨段)
        List<Bi> upSegments = new ArrayList<>();
        for (Bi bi : biList) {
            if (bi.direction == Bi.Direction.UP) {
                upSegments.add(bi);
            }
        }

        if (upSegments.size() < 2) return BeichiResult.none();

        Bi lastUp = upSegments.get(upSegments.size() - 1);
        Bi prevUp = upSegments.get(upSegments.size() - 2);

        // Top divergence: last segment makes new high but with less momentum
        if (lastUp.high > prevUp.high && lastUp.strength < prevUp.strength * biStrengthThreshold) {
            return new BeichiResult(true, BeichiResult.Type.TOP, lastUp.high, prevUp.strength - lastUp.strength);
        }

        return BeichiResult.none();
    }

    // Getters for current state
    public List<Fenxing> getFenxingList() { return new ArrayList<>(fenxingList); }
    public List<Bi> getBiList() { return new ArrayList<>(biList); }
    public Zhongshu getCurrentZhongshu() { return currentZhongshu; }
    public List<Zhongshu> getZhongshuHistory() { return new ArrayList<>(zhongshuHistory); }

    /**
     * Get current market context for strategy adapters
     */
    public KlineContext getCurrentContext() {
        return new KlineContext(
            fenxingList.isEmpty() ? null : fenxingList.get(fenxingList.size() - 1),
            biList.isEmpty() ? null : biList.get(biList.size() - 1),
            currentZhongshu,
            checkBeichi(),
            new ArrayList<>(klineWindow)
        );
    }

    // ========== Inner Classes ==========

    public static class KLine {
        public final long timestamp;
        public final double open;
        public final double high;
        public final double low;
        public final double close;
        public final double volume;

        public KLine(long timestamp, double open, double high, double low, double close, double volume) {
            this.timestamp = timestamp;
            this.open = open;
            this.high = high;
            this.low = low;
            this.close = close;
            this.volume = volume;
        }
    }

    public static class Fenxing {
        public enum Type { TOP, BOTTOM }
        public final Type type;
        public final long timestamp;
        public final double price;

        public Fenxing(Type type, long timestamp, double price) {
            this.type = type;
            this.timestamp = timestamp;
            this.price = price;
        }
    }

    public static class Bi {
        public enum Direction { UP, DOWN }
        public final long startTime;
        public final long endTime;
        public final double low;
        public final double high;
        public final Direction direction;
        public final double strength;

        public Bi(long startTime, long endTime, double low, double high, Direction direction, double strength) {
            this.startTime = startTime;
            this.endTime = endTime;
            this.low = low;
            this.high = high;
            this.direction = direction;
            this.strength = strength;
        }
    }

    public static class Zhongshu {
        public final double zg;  // 中枢上沿
        public final double zd;  // 中枢下沿
        public final double gg;  // 波动高点
        public final double dd;  // 波动低点
        public final long startTime;
        public final long endTime;

        public Zhongshu(double zg, double zd, double gg, double dd, long startTime, long endTime) {
            this.zg = zg;
            this.zd = zd;
            this.gg = gg;
            this.dd = dd;
            this.startTime = startTime;
            this.endTime = endTime;
        }

        public double getRange() { return zg - zd; }
    }

    public static class BeichiResult {
        public enum Type { TOP, BOTTOM, NONE }

        public final boolean hasBeichi;
        public final Type type;
        public final double price;
        public final double divergenceStrength;

        public BeichiResult(boolean hasBeichi, Type type, double price, double divergenceStrength) {
            this.hasBeichi = hasBeichi;
            this.type = type;
            this.price = price;
            this.divergenceStrength = divergenceStrength;
        }

        public static BeichiResult none() {
            return new BeichiResult(false, Type.NONE, 0, 0);
        }
    }

    public static class KlineContext {
        public final Fenxing lastFenxing;
        public final Bi lastBi;
        public final Zhongshu zhongshu;
        public final BeichiResult beichi;
        public final List<KLine> recentKlines;

        public KlineContext(Fenxing lastFenxing, Bi lastBi, Zhongshu zhongshu,
                          BeichiResult beichi, List<KLine> recentKlines) {
            this.lastFenxing = lastFenxing;
            this.lastBi = lastBi;
            this.zhongshu = zhongshu;
            this.beichi = beichi;
            this.recentKlines = recentKlines;
        }
    }

    // ========== Helper Methods ==========

    private KLine fromMarketData(MarketData data) {
        // FIX: Use lastPrice as a single price point for simplicity
        // Note: For proper K-line synthesis, would need actual OHLC data from exchange
        // This simplified version preserves lastPrice for fenxing detection
        double price = data.getLastPrice();
        double spread = data.getSpread();
        double halfSpread = spread / 2;
        return new KLine(
            System.currentTimeMillis(),
            price - halfSpread,  // open
            price + halfSpread,  // high
            price - halfSpread,  // low
            price,               // close
            data.getVolume()
        );
    }
}
