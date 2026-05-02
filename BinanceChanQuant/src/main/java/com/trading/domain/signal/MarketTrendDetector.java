package com.trading.domain.signal;

import com.trading.domain.market.model.MarketRegime;

import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Market Trend Detector - 轻量级趋势检测器
 *
 * 使用多个维度检测市场趋势：
 * 1. 价格动量 (Price Momentum)
 * 2. 均线排列 (MA Alignment)
 * 3. OFI (Order Flow Imbalance)
 * 4. 波动率 (Volatility)
 * 5. 成交量确认 (Volume Confirmation)
 *
 * 相比原来的 signal.getConfidence() > 0.6 方案，这个更准确
 */
public class MarketTrendDetector {

    // 趋势检测阈值
    private static final double STRONG_TREND_THRESHOLD = 0.5;
    private static final double MODERATE_TREND_THRESHOLD = 0.3;
    private static final double WEAK_TREND_THRESHOLD = 0.15;

    // 均线周期 - 缩短以加速预热
    private static final int MA_SHORT = 3;
    private static final int MA_MEDIUM = 10;
    private static final int MA_LONG = 20;

    // 价格历史缓存
    private final ConcurrentLinkedQueue<Double> priceHistory = new ConcurrentLinkedQueue<>();
    private static final int MAX_HISTORY_SIZE = 100;

    // OFI 值
    private final AtomicReference<Double> ofiValue = new AtomicReference<>(0.0);
    private final AtomicReference<Double> tradeFlowValue = new AtomicReference<>(0.0);

    // 最新计算结果缓存
    private final AtomicReference<TrendDetectionResult> cachedResult = new AtomicReference<>();
    private volatile long lastUpdateTime = 0;
    private static final long CACHE_TTL_MS = 1000; // 1秒缓存

    /**
     * 更新市场数据
     */
    public void update(double price, double atr, double atrPercent, double bidSize, double askSize) {
        // 更新价格历史
        priceHistory.add(price);
        while (priceHistory.size() > MAX_HISTORY_SIZE) {
            priceHistory.poll();
        }

        // 简单 OFI 计算: 买卖量差 / 总量的比例
        double totalSize = bidSize + askSize;
        if (totalSize > 0) {
            double ofi = (bidSize - askSize) / totalSize; // -1 到 1
            ofiValue.set(ofi);
        }

        lastUpdateTime = System.currentTimeMillis();
    }

    /**
     * 更新 OFI 值
     */
    public void updateOFI(double ofi, double tradeFlow) {
        ofiValue.set(ofi);
        tradeFlowValue.set(tradeFlow);
        lastUpdateTime = System.currentTimeMillis();
    }

    /**
     * 检测趋势 - 主要方法
     */
    public TrendDetectionResult detect() {
        // 检查缓存
        TrendDetectionResult cached = cachedResult.get();
        if (cached != null && (System.currentTimeMillis() - lastUpdateTime) < CACHE_TTL_MS) {
            return cached;
        }

        // 计算各维度分数
        double momentumScore = calculateMomentumScore();
        double maScore = calculateMAScore();
        double ofiScore = calculateOFIScore();
        double volScore = calculateVolatilityScore();

        // 加权综合
        double trendScore = momentumScore * 0.35 + maScore * 0.30 + ofiScore * 0.25 + volScore * 0.10;

        // 判断方向和强度
        TrendDirection direction = determineDirection(trendScore, maScore, ofiScore);
        TrendIntensity intensity = determineIntensity(Math.abs(trendScore));
        MarketRegime regime = determineRegime(direction, intensity, volScore);

        TrendDetectionResult result = new TrendDetectionResult(
            trendScore,
            direction,
            intensity,
            regime,
            calculateConfidence(momentumScore, maScore, ofiScore)
        );

        cachedResult.set(result);
        return result;
    }

    /**
     * 计算价格动量分数
     */
    private double calculateMomentumScore() {
        Double[] prices = priceHistory.toArray(new Double[0]);
        if (prices.length < MA_SHORT * 2) {
            return 0.0;
        }

        int len = prices.length;

        // 计算短期动量: 最近MA_SHORT平均 vs 之前MA_SHORT平均
        double shortMA1 = calculateSMA(prices, len - MA_SHORT, len);
        double shortMA2 = calculateSMA(prices, len - MA_SHORT * 2, len - MA_SHORT);

        // 计算中期动量: MA_SHORT vs MA_MEDIUM
        double mediumMA = calculateSMA(prices, len - MA_MEDIUM, len);

        // 动量分数
        double momentum = (shortMA1 - shortMA2) / shortMA2; // 变化率
        double priceVsMA = (shortMA1 - mediumMA) / mediumMA;

        // 合并: 动量方向 + 相对位置
        double score = momentum * 10 + priceVsMA * 2;
        return clamp(score, -1.0, 1.0);
    }

    /**
     * 计算均线排列分数
     */
    private double calculateMAScore() {
        Double[] prices = priceHistory.toArray(new Double[0]);
        if (prices.length < MA_LONG) {
            return 0.0;
        }

        int len = prices.length;
        double ma5 = calculateSMA(prices, len - MA_SHORT, len);
        double ma20 = calculateSMA(prices, len - MA_MEDIUM, len);
        double ma50 = calculateSMA(prices, len - MA_LONG, len);

        double score = 0.0;

        // 均线多头排列 (上升趋势)
        if (ma5 > ma20 && ma20 > ma50) {
            score += 0.4;
            // 价格在均线上方
            double currentPrice = prices[len - 1];
            if (currentPrice > ma5) score += 0.2;
            if (currentPrice > ma20) score += 0.2;
            if (currentPrice > ma50) score += 0.2;
        }
        // 均线空头排列 (下降趋势)
        else if (ma5 < ma20 && ma20 < ma50) {
            score -= 0.4;
            double currentPrice = prices[len - 1];
            if (currentPrice < ma5) score -= 0.2;
            if (currentPrice < ma20) score -= 0.2;
            if (currentPrice < ma50) score -= 0.2;
        }
        // 纠缠 (震荡)
        else {
            score = 0.0;
        }

        return clamp(score, -1.0, 1.0);
    }

    /**
     * 计算 OFI 分数
     */
    private double calculateOFIScore() {
        double ofi = ofiValue.get();
        double tradeFlow = tradeFlowValue.get();

        // OFI > 0.3: 强势买入; OFI < -0.3: 强势卖出
        double score = ofi * 0.7 + tradeFlow * 0.3;
        return clamp(score, -1.0, 1.0);
    }

    /**
     * 计算波动率分数
     */
    private double calculateVolatilityScore() {
        // 这个在外部通过 atrPercent 计算，这里返回0
        // 如果ATR在扩张，给正向分数
        return 0.0;
    }

    /**
     * 判断趋势方向
     */
    private TrendDirection determineDirection(double trendScore, double maScore, double ofiScore) {
        // 需要多个指标一致才确认方向
        int bullishSignals = 0;
        int bearishSignals = 0;

        if (trendScore > 0.2) bullishSignals++;
        if (trendScore < -0.2) bearishSignals++;
        if (maScore > 0.2) bullishSignals++;
        if (maScore < -0.2) bearishSignals++;
        if (ofiScore > 0.3) bullishSignals++;
        if (ofiScore < -0.3) bearishSignals++;

        if (bullishSignals >= 2) return TrendDirection.UP;
        if (bearishSignals >= 2) return TrendDirection.DOWN;
        if (trendScore > 0.15) return TrendDirection.UP;
        if (trendScore < -0.15) return TrendDirection.DOWN;
        return TrendDirection.NEUTRAL;
    }

    /**
     * 判断趋势强度
     */
    private TrendIntensity determineIntensity(double absScore) {
        if (absScore >= STRONG_TREND_THRESHOLD) return TrendIntensity.STRONG;
        if (absScore >= MODERATE_TREND_THRESHOLD) return TrendIntensity.MODERATE;
        if (absScore >= WEAK_TREND_THRESHOLD) return TrendIntensity.WEAK;
        return TrendIntensity.NONE;
    }

    /**
     * 判断市场状态
     */
    private MarketRegime determineRegime(TrendDirection direction, TrendIntensity intensity, double volScore) {
        if (intensity == TrendIntensity.NONE) {
            return volScore > 0.2 ? MarketRegime.HIGH_VOL : MarketRegime.RANGE;
        }

        if (intensity == TrendIntensity.STRONG) {
            if (direction == TrendDirection.UP) return MarketRegime.TREND_UP;
            if (direction == TrendDirection.DOWN) return MarketRegime.TREND_DOWN;
        }

        if (intensity == TrendIntensity.MODERATE || intensity == TrendIntensity.WEAK) {
            if (direction == TrendDirection.UP) return MarketRegime.TREND_UP;
            if (direction == TrendDirection.DOWN) return MarketRegime.TREND_DOWN;
        }

        return MarketRegime.RANGE;
    }

    /**
     * 计算置信度
     */
    private double calculateConfidence(double momentum, double ma, double ofi) {
        int validSignals = 0;
        if (Math.abs(momentum) > 0.1) validSignals++;
        if (Math.abs(ma) > 0.1) validSignals++;
        if (Math.abs(ofi) > 0.1) validSignals++;

        // 基于有效信号数量
        double baseConfidence = validSignals * 0.25;
        return clamp(baseConfidence + 0.2, 0.3, 0.95);
    }

    /**
     * 计算简单移动平均
     */
    private double calculateSMA(Double[] prices, int start, int end) {
        if (start < 0 || end > prices.length || start >= end) {
            return 0.0;
        }
        double sum = 0.0;
        for (int i = start; i < end; i++) {
            sum += prices[i];
        }
        return sum / (end - start);
    }

    /**
     * 限制范围
     */
    private double clamp(double value, double min, double max) {
        return Math.max(min, Math.min(max, value));
    }

    /**
     * 清除历史
     */
    public void clear() {
        priceHistory.clear();
        ofiValue.set(0.0);
        tradeFlowValue.set(0.0);
        cachedResult.set(null);
        lastUpdateTime = 0;
    }

    /**
     * 获取价格历史大小
     */
    public int getHistorySize() {
        return priceHistory.size();
    }

    // 内部类: 趋势检测结果
    public static class TrendDetectionResult {
        private final double score;
        private final TrendDirection direction;
        private final TrendIntensity intensity;
        private final MarketRegime regime;
        private final double confidence;

        public TrendDetectionResult(double score, TrendDirection direction,
                                   TrendIntensity intensity, MarketRegime regime,
                                   double confidence) {
            this.score = score;
            this.direction = direction;
            this.intensity = intensity;
            this.regime = regime;
            this.confidence = confidence;
        }

        public double getScore() { return score; }
        public TrendDirection getDirection() { return direction; }
        public TrendIntensity getIntensity() { return intensity; }
        public MarketRegime getRegime() { return regime; }
        public double getConfidence() { return confidence; }

        public boolean isBullish() { return direction == TrendDirection.UP; }
        public boolean isBearish() { return direction == TrendDirection.DOWN; }
        public boolean isNeutral() { return direction == TrendDirection.NEUTRAL; }
        public boolean isStrong() { return intensity == TrendIntensity.STRONG; }

        @Override
        public String toString() {
            return String.format("TrendResult{score=%.3f dir=%s intensity=%s regime=%s conf=%.2f}",
                score, direction, intensity, regime, confidence);
        }
    }

    // 趋势方向枚举
    public enum TrendDirection {
        UP, DOWN, NEUTRAL
    }

    // 趋势强度枚举
    public enum TrendIntensity {
        STRONG, MODERATE, WEAK, NONE
    }
}
