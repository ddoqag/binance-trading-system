package com.trading.adapter.chan.wrapper;

import com.trading.adapter.chan.analyzer.ChanKLineProcessor;
import com.trading.adapter.chan.analyzer.ChanKLineProcessor.*;
import com.trading.adapter.chan.config.ChanFeatureToggle;
import com.trading.adapter.chan.detector.ChanPatternDetector.*;
import com.trading.domain.market.model.MarketRegime;

/**
 * Chan Trend Continuation Strategy Adapter (缠论二买/三买/二卖/三卖)
 */
public class ChanTrendStrategyAdapter extends ChanStrategyAdapter {

    public static final String SOURCE = "CHAN_TREND";

    public ChanTrendStrategyAdapter(ChanFeatureToggle toggle, ChanKLineProcessor processor) {
        super(toggle, processor);
    }

    @Override
    public SignalType getSignalType() {
        return SignalType.BUY_2;
    }

    @Override
    public double getMinConfidence() {
        return 0.35;  // Lower for provisional signals
    }

    @Override
    public boolean isApplicable(MarketRegime regime) {
        return regime == MarketRegime.TREND_UP || regime == MarketRegime.TREND_DOWN;
    }

    @Override
    protected boolean isEnabled() {
        return toggle.isTrendActive();
    }

    @Override
    public PatternSignal detect(KlineContext ctx, MarketRegime regime) {
        if (ctx == null || !isApplicable(regime)) {
            return PatternSignal.none();
        }

        Zhongshu zhongshu = ctx.zhongshu;
        Bi lastBi = ctx.lastBi;
        Fenxing lastFenxing = ctx.lastFenxing;

        // 中枢未形成时，使用笔分型生成临时信号
        if (zhongshu == null) {
            return detectPreZhongshu(ctx, regime, lastBi, lastFenxing);
        }

        if (lastBi == null) {
            return PatternSignal.none();
        }

        // Detect 二买 (Buy 2)
        if (regime == MarketRegime.TREND_UP && lastBi.direction == Bi.Direction.UP) {
            double pullbackLevel = zhongshu.zd;
            if (lastBi.low <= pullbackLevel * 1.02 && lastBi.low >= pullbackLevel * 0.98) {
                return new PatternSignal(
                    SignalType.BUY_2,
                    calculateBuy2Confidence(ctx),
                    lastBi.low,
                    System.currentTimeMillis(),
                    "二买回调中枢下沿"
                );
            }
        }

        // Detect 三买 (Buy 3)
        if (regime == MarketRegime.TREND_UP && lastBi.direction == Bi.Direction.UP) {
            double testLevel = zhongshu.zg;
            if (lastBi.low > testLevel) {
                return new PatternSignal(
                    SignalType.BUY_3,
                    calculateBuy3Confidence(ctx),
                    testLevel,
                    System.currentTimeMillis(),
                    "三买突破中枢上沿"
                );
            }
        }

        // Detect 二卖 (Sell 2)
        if (regime == MarketRegime.TREND_DOWN && lastBi.direction == Bi.Direction.DOWN) {
            double pullbackLevel = zhongshu.zg;
            if (lastBi.high >= pullbackLevel * 0.98 && lastBi.high <= pullbackLevel * 1.02) {
                return new PatternSignal(
                    SignalType.SELL_2,
                    calculateSell2Confidence(ctx),
                    lastBi.high,
                    System.currentTimeMillis(),
                    "二卖反弹中枢上沿"
                );
            }
        }

        // Detect 三卖 (Sell 3)
        if (regime == MarketRegime.TREND_DOWN && lastBi.direction == Bi.Direction.DOWN) {
            double testLevel = zhongshu.zd;
            if (lastBi.high < testLevel) {
                return new PatternSignal(
                    SignalType.SELL_3,
                    calculateSell3Confidence(ctx),
                    testLevel,
                    System.currentTimeMillis(),
                    "三卖跌破中枢下沿"
                );
            }
        }

        return PatternSignal.none();
    }

    /**
     * 中枢未形成时的分型信号检测
     */
    private PatternSignal detectPreZhongshu(KlineContext ctx, MarketRegime regime, Bi lastBi, Fenxing lastFenxing) {
        int klineCount = ctx.recentKlines != null ? ctx.recentKlines.size() : 0;

        // 基于笔的方向和分型生成趋势信号
        if (lastFenxing != null) {
            if (regime == MarketRegime.TREND_UP && lastFenxing.type == Fenxing.Type.BOTTOM) {
                // 上升趋势中的底分型可能是买入机会
                double confidence = 0.45 + Math.min(0.10, klineCount * 0.002);
                return new PatternSignal(
                    SignalType.BUY_2,
                    confidence,
                    lastFenxing.price,
                    System.currentTimeMillis(),
                    "前中枢底分型( provisional, klines=" + klineCount + ")"
                );
            }
            if (regime == MarketRegime.TREND_DOWN && lastFenxing.type == Fenxing.Type.TOP) {
                // 下降趋势中的顶分型可能是卖出机会
                double confidence = 0.45 + Math.min(0.10, klineCount * 0.002);
                return new PatternSignal(
                    SignalType.SELL_2,
                    confidence,
                    lastFenxing.price,
                    System.currentTimeMillis(),
                    "前中枢顶分型( provisional, klines=" + klineCount + ")"
                );
            }
        }

        // 基于笔的方向
        if (lastBi != null) {
            if (regime == MarketRegime.TREND_UP && lastBi.direction == Bi.Direction.UP) {
                double confidence = 0.40 + Math.min(0.10, klineCount * 0.002);
                return new PatternSignal(
                    SignalType.BUY_2,
                    confidence,
                    lastBi.low,
                    System.currentTimeMillis(),
                    "前中枢上升笔( provisional, klines=" + klineCount + ")"
                );
            }
            if (regime == MarketRegime.TREND_DOWN && lastBi.direction == Bi.Direction.DOWN) {
                double confidence = 0.40 + Math.min(0.10, klineCount * 0.002);
                return new PatternSignal(
                    SignalType.SELL_2,
                    confidence,
                    lastBi.high,
                    System.currentTimeMillis(),
                    "前中枢下降笔( provisional, klines=" + klineCount + ")"
                );
            }
        }

        // 没有分型和笔时，使用简单的K线趋势判断
        if (klineCount >= 5) {
            return detectTrendBasedSignal(ctx, regime, klineCount);
        }

        return PatternSignal.none();
    }

    /**
     * 基于K线趋势的简单信号检测（当没有笔/分型时使用）
     */
    private PatternSignal detectTrendBasedSignal(KlineContext ctx, MarketRegime regime, int klineCount) {
        if (ctx.recentKlines == null || ctx.recentKlines.size() < 5) {
            return PatternSignal.none();
        }

        java.util.List<KLine> recent = ctx.recentKlines;
        int len = recent.size();

        double lastHigh = recent.get(len - 1).high;
        double lastLow = recent.get(len - 1).low;
        double prevHigh = recent.get(len - 2).high;
        double prevLow = recent.get(len - 2).low;

        if (regime == MarketRegime.TREND_UP && lastLow > prevLow) {
            // 上升趋势中的低点抬升可能是买入机会
            double confidence = 0.35 + Math.min(0.10, klineCount * 0.002);
            return new PatternSignal(
                SignalType.BUY_2,
                confidence,
                lastLow,
                System.currentTimeMillis(),
                "前中枢上升K线( provisional, klines=" + klineCount + ")"
            );
        }

        if (regime == MarketRegime.TREND_DOWN && lastHigh < prevHigh) {
            // 下降趋势中的高点降低可能是卖出机会
            double confidence = 0.35 + Math.min(0.10, klineCount * 0.002);
            return new PatternSignal(
                SignalType.SELL_2,
                confidence,
                lastHigh,
                System.currentTimeMillis(),
                "前中枢下降K线( provisional, klines=" + klineCount + ")"
            );
        }

        return PatternSignal.none();
    }

    private double calculateBuy2Confidence(KlineContext ctx) {
        double base = 0.60;
        if (ctx.beichi != null && ctx.beichi.hasBeichi) base += 0.15;
        if (ctx.lastFenxing != null && ctx.lastFenxing.type == Fenxing.Type.BOTTOM) base += 0.10;
        return Math.min(base, 0.90);
    }

    private double calculateBuy3Confidence(KlineContext ctx) {
        double base = 0.65;
        if (ctx.lastFenxing != null && ctx.lastFenxing.type == Fenxing.Type.BOTTOM) base += 0.10;
        return Math.min(base, 0.90);
    }

    private double calculateSell2Confidence(KlineContext ctx) {
        double base = 0.60;
        if (ctx.beichi != null && ctx.beichi.hasBeichi) base += 0.15;
        if (ctx.lastFenxing != null && ctx.lastFenxing.type == Fenxing.Type.TOP) base += 0.10;
        return Math.min(base, 0.90);
    }

    private double calculateSell3Confidence(KlineContext ctx) {
        double base = 0.65;
        if (ctx.lastFenxing != null && ctx.lastFenxing.type == Fenxing.Type.TOP) base += 0.10;
        return Math.min(base, 0.90);
    }

    public String getSignalSource() {
        return SOURCE;
    }
}
