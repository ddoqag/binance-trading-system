package com.trading.adapter.chan.integration;

import com.trading.adapter.chan.detector.ChanPatternDetector.PatternSignal;
import com.trading.adapter.chan.detector.ChanPatternDetector.SignalType;
import com.trading.domain.market.model.MarketRegime;
import com.trading.domain.signal.StructuralBias;

/**
 * Translates Chan PatternSignal into StructuralBias
 *
 * Key principle: Chan provides STRUCTURE, not signals.
 * The actual trading signals come from AI timing.
 */
public class ChanBiasTranslator {

    /**
     * Translate PatternSignal to StructuralBias
     */
    public StructuralBias translate(PatternSignal signal, MarketRegime regime, double confidence) {
        if (signal == null || !signal.hasSignal()) {
            return StructuralBias.NEUTRAL;
        }

        SignalType type = signal.type;  // PatternSignal.type is public
        double effectiveConfidence = Math.min(confidence, 1.0);

        // Strong signals with high confidence → strong bias
        // Weak signals or low confidence → weak bias

        switch (type) {
            // Strong bullish
            case BUY_1:
            case RESONANCE_BUY:
                return effectiveConfidence > 0.7
                    ? StructuralBias.STRONG_LONG
                    : StructuralBias.WEAK_LONG;

            // Moderate bullish
            case BUY_2:
            case BUY_3:
                if (regime == MarketRegime.TREND_UP && effectiveConfidence > 0.6) {
                    return StructuralBias.STRONG_LONG;
                }
                return StructuralBias.WEAK_LONG;

            // Strong bearish
            case SELL_1:
            case RESONANCE_SELL:
                return effectiveConfidence > 0.7
                    ? StructuralBias.STRONG_SHORT
                    : StructuralBias.WEAK_SHORT;

            // Moderate bearish
            case SELL_2:
            case SELL_3:
                if (regime == MarketRegime.TREND_DOWN && effectiveConfidence > 0.6) {
                    return StructuralBias.STRONG_SHORT;
                }
                return StructuralBias.WEAK_SHORT;

            // Neutral/unclear
            default:
                return StructuralBias.NEUTRAL;
        }
    }

    /**
     * Get bias description for logging
     */
    public String describe(StructuralBias bias) {
        return String.format("%s (%.2f) - %s",
            bias.name(), bias.getBiasScore(), bias.getDescription());
    }
}
