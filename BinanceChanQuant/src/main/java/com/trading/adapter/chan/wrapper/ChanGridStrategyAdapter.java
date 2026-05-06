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
        return 0.50;
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
        Bi lastBi = ctx.lastBi;
        if (lastBi == null) {
            return PatternSignal.none();
        }

        Zhongshu zhongshu = ctx.zhongshu;

        // 中枢未形成时，使用笔分型生成临时信号
        if (zhongshu == null) {
            return detectPreZhongshu(ctx, lastFenxing, lastBi);
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
    private PatternSignal detectPreZhongshu(KlineContext ctx, Fenxing lastFenxing, Bi lastBi) {
        if (lastFenxing == null) {
            return PatternSignal.none();
        }

        int klineCount = ctx.recentKlines != null ? ctx.recentKlines.size() : 0;

        // 基于分型方向生成信号
        if (lastFenxing.type == Fenxing.Type.TOP) {
            // 顶分型：可能做空
            double confidence = 0.40 + Math.min(0.10, klineCount * 0.002);  // 0.40-0.50
            return new PatternSignal(
                SignalType.RANGE_BOUND,
                confidence,
                lastFenxing.price,
                System.currentTimeMillis(),
                "前中枢顶分型做空( provisional, klines=" + klineCount + ")"
            );
        } else if (lastFenxing.type == Fenxing.Type.BOTTOM) {
            // 底分型：可能做多
            double confidence = 0.40 + Math.min(0.10, klineCount * 0.002);  // 0.40-0.50
            return new PatternSignal(
                SignalType.RANGE_BOUND,
                confidence,
                lastFenxing.price,
                System.currentTimeMillis(),
                "前中枢底分型做多( provisional, klines=" + klineCount + ")"
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
