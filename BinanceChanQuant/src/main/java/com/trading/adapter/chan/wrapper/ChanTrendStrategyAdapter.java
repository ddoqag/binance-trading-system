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
        return 0.55;
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
        if (zhongshu == null) {
            return PatternSignal.none();
        }

        Bi lastBi = ctx.lastBi;
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
