package com.trading.adapter.chan.wrapper;

import com.trading.adapter.chan.analyzer.ChanKLineProcessor;
import com.trading.adapter.chan.analyzer.ChanKLineProcessor.*;
import com.trading.adapter.chan.config.ChanFeatureToggle;
import com.trading.adapter.chan.detector.ChanPatternDetector.*;
import com.trading.domain.market.model.MarketRegime;

/**
 * Chan Range-bound Strategy Adapter (缠论中枢震荡)
 */
public class ChanGridStrategyAdapter extends ChanStrategyAdapter {

    public static final String SOURCE = "CHAN_GRID";
    private static final double BREAKOUT_THRESHOLD = 0.005;

    public ChanGridStrategyAdapter(ChanFeatureToggle toggle, ChanKLineProcessor processor) {
        super(toggle, processor);
    }

    @Override
    public SignalType getSignalType() {
        return SignalType.RANGE_BOUND;
    }

    @Override
    public double getMinConfidence() {
        return 0.35;  // Lower for provisional signals
    }

    @Override
    public boolean isApplicable(MarketRegime regime) {
        return regime == MarketRegime.RANGE;
    }

    @Override
    protected boolean isEnabled() {
        return toggle.isGridActive();
    }

    @Override
    public PatternSignal detect(KlineContext ctx, MarketRegime regime) {
        if (ctx == null || !isApplicable(regime)) {
            return PatternSignal.none();
        }

        Fenxing lastFenxing = ctx.lastFenxing;
        Zhongshu zhongshu = ctx.zhongshu;
        Bi lastBi = ctx.lastBi;

        // 中枢未形成时，使用分型生成临时信号（不依赖lastBi）
        if (zhongshu == null) {
            return detectPreZhongshu(ctx, lastFenxing);
        }

        if (lastBi == null) {
            return PatternSignal.none();
        }

        double zg = zhongshu.zg;
        double zd = zhongshu.zd;

        // 做空信号
        if (lastBi.high >= zg * (1 - BREAKOUT_THRESHOLD)) {
            if (lastFenxing != null && lastFenxing.type == Fenxing.Type.TOP) {
                return new PatternSignal(
                    SignalType.RANGE_BOUND,
                    calculateRangeBoundConfidence(ctx, true),
                    zg,
                    System.currentTimeMillis(),
                    "中枢上沿顶分型做空"
                );
            }
        }

        // 做多信号
        if (lastBi.low <= zd * (1 + BREAKOUT_THRESHOLD)) {
            if (lastFenxing != null && lastFenxing.type == Fenxing.Type.BOTTOM) {
                return new PatternSignal(
                    SignalType.RANGE_BOUND,
                    calculateRangeBoundConfidence(ctx, false),
                    zd,
                    System.currentTimeMillis(),
                    "中枢下沿底分型做多"
                );
            }
        }

        return PatternSignal.none();
    }

    /**
     * 中枢未形成时的分型信号检测
     */
    private PatternSignal detectPreZhongshu(KlineContext ctx, Fenxing lastFenxing) {
        int klineCount = ctx.recentKlines != null ? ctx.recentKlines.size() : 0;

        // 基于分型方向生成信号
        if (lastFenxing != null) {
            if (lastFenxing.type == Fenxing.Type.TOP) {
                // 顶分型：可能做空
                double confidence = 0.40 + Math.min(0.10, klineCount * 0.002);
                return new PatternSignal(
                    SignalType.RANGE_BOUND,
                    confidence,
                    lastFenxing.price,
                    System.currentTimeMillis(),
                    "前中枢顶分型做空( provisional, klines=" + klineCount + ")"
                );
            } else if (lastFenxing.type == Fenxing.Type.BOTTOM) {
                // 底分型：可能做多
                double confidence = 0.40 + Math.min(0.10, klineCount * 0.002);
                return new PatternSignal(
                    SignalType.RANGE_BOUND,
                    confidence,
                    lastFenxing.price,
                    System.currentTimeMillis(),
                    "前中枢底分型做多( provisional, klines=" + klineCount + ")"
                );
            }
        }

        // 没有分型但有足够K线时，使用简单的趋势判断
        if (klineCount >= 5) {
            return detectTrendBasedSignal(ctx, klineCount);
        }

        return PatternSignal.none();
    }

    /**
     * 基于K线趋势的简单信号检测（当没有分型时使用）
     */
    private PatternSignal detectTrendBasedSignal(KlineContext ctx, int klineCount) {
        if (ctx.recentKlines == null || ctx.recentKlines.size() < 5) {
            return PatternSignal.none();
        }

        // 获取最近的几根K线分析趋势
        java.util.List<KLine> recent = ctx.recentKlines;
        int len = recent.size();

        double lastHigh = recent.get(len - 1).high;
        double lastLow = recent.get(len - 1).low;
        double prevHigh = recent.get(len - 2).high;
        double prevLow = recent.get(len - 2).low;

        // 简单趋势判断：连续上升
        if (lastHigh > prevHigh && lastLow > prevLow) {
            // 上升趋势中的回调可能做多
            double confidence = 0.35 + Math.min(0.10, klineCount * 0.002);
            return new PatternSignal(
                SignalType.RANGE_BOUND,
                confidence,
                lastLow,
                System.currentTimeMillis(),
                "前中枢上升K线( provisional, klines=" + klineCount + ")"
            );
        }

        // 连续下降
        if (lastHigh < prevHigh && lastLow < prevLow) {
            // 下降趋势中的反弹可能做空
            double confidence = 0.35 + Math.min(0.10, klineCount * 0.002);
            return new PatternSignal(
                SignalType.RANGE_BOUND,
                confidence,
                lastHigh,
                System.currentTimeMillis(),
                "前中枢下降K线( provisional, klines=" + klineCount + ")"
            );
        }

        return PatternSignal.none();
    }

    private double calculateRangeBoundConfidence(KlineContext ctx, boolean isTop) {
        double base = 0.55;

        if (ctx.recentKlines != null && ctx.recentKlines.size() >= 20) {
            base += 0.15;
        }

        Fenxing fx = ctx.lastFenxing;
        if (fx != null) {
            if (isTop && fx.type == Fenxing.Type.TOP) base += 0.10;
            if (!isTop && fx.type == Fenxing.Type.BOTTOM) base += 0.10;
        }

        if (ctx.beichi != null && !ctx.beichi.hasBeichi) {
            base += 0.05;
        }

        return Math.min(base, 0.85);
    }

    public String getSignalSource() {
        return SOURCE;
    }
}
