package com.trading.adapter.chan.wrapper;

import com.trading.adapter.chan.analyzer.ChanKLineProcessor;
import com.trading.adapter.chan.analyzer.ChanKLineProcessor.*;
import com.trading.adapter.chan.config.ChanFeatureToggle;
import com.trading.adapter.chan.detector.ChanPatternDetector.*;
import com.trading.domain.market.model.MarketRegime;

/**
 * Chan Multi-timeframe Resonance Filter (缠论多级别共振)
 */
public class ChanResonanceFilterAdapter extends ChanStrategyAdapter {

    public static final String SOURCE = "CHAN_RESONANCE";

    private final ChanKLineProcessor[] multiTimeframeProcessors;
    private final int minAgreement;

    public ChanResonanceFilterAdapter(ChanFeatureToggle toggle,
                                       ChanKLineProcessor[] multiTimeframeProcessors) {
        super(toggle, multiTimeframeProcessors[0]);
        this.multiTimeframeProcessors = multiTimeframeProcessors;
        this.minAgreement = toggle.getResonanceMinAgreement();
    }

    @Override
    public SignalType getSignalType() {
        return SignalType.RESONANCE_BUY;
    }

    @Override
    public double getMinConfidence() {
        return 0.50;
    }

    @Override
    public boolean isApplicable(MarketRegime regime) {
        return true;
    }

    @Override
    protected boolean isEnabled() {
        return toggle.isResonanceActive();
    }

    @Override
    public PatternSignal detect(KlineContext ctx, MarketRegime regime) {
        // This is a filter, not standalone generator
        return PatternSignal.none();
    }

    /**
     * Check if a signal has multi-timeframe resonance
     */
    public ResonanceResult checkResonance(SignalType primarySignal,
                                           KlineContext primaryCtx,
                                           MarketRegime regime) {
        if (!isEnabled() || multiTimeframeProcessors.length < 2) {
            return ResonanceResult.noResonance();
        }

        int agreementCount = 1;
        SignalType dominantDirection = primarySignal;

        for (int i = 1; i < multiTimeframeProcessors.length; i++) {
            ChanKLineProcessor processor = multiTimeframeProcessors[i];
            KlineContext tfCtx = processor.getCurrentContext();

            if (tfCtx == null || tfCtx.lastFenxing == null) {
                continue;
            }

            if (doesTimeframeAgree(primarySignal, tfCtx)) {
                agreementCount++;
            }
        }

        double resonanceStrength = (double) agreementCount / multiTimeframeProcessors.length;

        return new ResonanceResult(
            agreementCount >= minAgreement,
            resonanceStrength,
            agreementCount,
            dominantDirection,
            agreementCount >= 3 ? "STRONG" : "STANDARD"
        );
    }

    private boolean doesTimeframeAgree(SignalType primary, KlineContext ctx) {
        if (ctx.lastFenxing == null) return false;
        Fenxing.Type fenxingType = ctx.lastFenxing.type;

        switch (primary) {
            case BUY_1: case BUY_2: case BUY_3:
                return fenxingType == Fenxing.Type.BOTTOM;
            case SELL_1: case SELL_2: case SELL_3:
                return fenxingType == Fenxing.Type.TOP;
            default:
                return false;
        }
    }

    public String getSignalSource() {
        return SOURCE;
    }

    // ========== Inner Classes ==========

    public static class ResonanceResult {
        public final boolean hasResonance;
        public final double strength;
        public final int agreementCount;
        public final SignalType direction;
        public final String level;

        public ResonanceResult(boolean hasResonance, double strength,
                              int agreementCount, SignalType direction, String level) {
            this.hasResonance = hasResonance;
            this.strength = strength;
            this.agreementCount = agreementCount;
            this.direction = direction;
            this.level = level;
        }

        public static ResonanceResult noResonance() {
            return new ResonanceResult(false, 0, 0, SignalType.NONE, "NONE");
        }
    }
}
