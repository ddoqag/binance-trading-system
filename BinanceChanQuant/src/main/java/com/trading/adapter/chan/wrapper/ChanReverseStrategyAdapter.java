package com.trading.adapter.chan.wrapper;

import com.trading.adapter.chan.analyzer.ChanKLineProcessor;
import com.trading.adapter.chan.analyzer.ChanKLineProcessor.*;
import com.trading.adapter.chan.config.ChanFeatureToggle;
import com.trading.adapter.chan.detector.ChanPatternDetector.*;
import com.trading.domain.market.model.MarketRegime;

/**
 * Chan Trend Reversal Strategy Adapter (缠论一买/一卖)
 */
public class ChanReverseStrategyAdapter extends ChanStrategyAdapter {

    public static final String SOURCE = "CHAN_REVERSE";

    public ChanReverseStrategyAdapter(ChanFeatureToggle toggle, ChanKLineProcessor processor) {
        super(toggle, processor);
    }

    @Override
    public SignalType getSignalType() {
        return SignalType.BUY_1;
    }

    @Override
    public double getMinConfidence() {
        return 0.55;
    }

    @Override
    public boolean isApplicable(MarketRegime regime) {
        return regime == MarketRegime.TREND_DOWN || regime == MarketRegime.TREND_UP;
    }

    @Override
    protected boolean isEnabled() {
        return toggle.isReverseActive();
    }

    @Override
    public PatternSignal detect(KlineContext ctx, MarketRegime regime) {
        if (ctx == null || !isApplicable(regime)) {
            return PatternSignal.none();
        }

        // Check for底背驰 (bottom divergence)
        BeichiResult beichi = ctx.beichi;
        if (beichi != null && beichi.hasBeichi && beichi.type == BeichiResult.Type.BOTTOM) {
            double confidence = calculateConfidence(beichi.divergenceStrength, ctx);
            return new PatternSignal(
                SignalType.BUY_1,
                confidence,
                beichi.price,
                System.currentTimeMillis(),
                "底背驰一买信号"
            );
        }

        // Check for顶背驰 (top divergence)
        if (beichi != null && beichi.hasBeichi && beichi.type == BeichiResult.Type.TOP) {
            double confidence = calculateConfidence(beichi.divergenceStrength, ctx);
            return new PatternSignal(
                SignalType.SELL_1,
                confidence,
                beichi.price,
                System.currentTimeMillis(),
                "顶背驰一卖信号"
            );
        }

        return PatternSignal.none();
    }

    private double calculateConfidence(double divergenceStrength, KlineContext ctx) {
        double base = 0.55;

        if (divergenceStrength > 0.5) base += 0.15;
        else if (divergenceStrength > 0.3) base += 0.10;
        else if (divergenceStrength > 0.1) base += 0.05;

        if (ctx.zhongshu != null) base += 0.10;
        if (ctx.lastFenxing != null) base += 0.05;

        return Math.min(base, 0.95);
    }

    public String getSignalSource() {
        return SOURCE;
    }
}
