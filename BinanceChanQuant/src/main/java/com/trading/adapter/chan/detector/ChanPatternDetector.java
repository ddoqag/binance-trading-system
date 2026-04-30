package com.trading.adapter.chan.detector;

import com.trading.adapter.chan.analyzer.ChanKLineProcessor.*;
import com.trading.domain.market.model.MarketRegime;

/**
 * Chan Pattern Detector Interface
 * Detects Chan theory patterns from processed K-lines
 */
public interface ChanPatternDetector {

    /**
     * Detect if current pattern matches this detector's signal type
     */
    PatternSignal detect(KlineContext ctx, MarketRegime regime);

    /**
     * Get the signal type this detector produces
     */
    SignalType getSignalType();

    /**
     * Get minimum confidence threshold for this detector
     */
    double getMinConfidence();

    /**
     * Check if detector is applicable for given regime
     */
    boolean isApplicable(MarketRegime regime);

    // ========== Inner Classes ==========

    enum SignalType {
        // Trend Reversal (一买/一卖)
        BUY_1, SELL_1,
        // Trend Continuation (二买/二卖/三买/三卖)
        BUY_2, SELL_2, BUY_3, SELL_3,
        // Range-bound (中枢震荡)
        RANGE_BOUND,
        // Multi-timeframe Resonance
        RESONANCE_BUY, RESONANCE_SELL,
        // No signal
        NONE
    }

    class PatternSignal {
        public final SignalType type;
        public final double confidence;
        public final double price;
        public final Long timestamp;
        public final String description;

        public PatternSignal(SignalType type, double confidence, double price, Long timestamp, String description) {
            this.type = type;
            this.confidence = confidence;
            this.price = price;
            this.timestamp = timestamp;
            this.description = description;
        }

        public static PatternSignal none() {
            return new PatternSignal(SignalType.NONE, 0, 0, null, null);
        }

        public boolean hasSignal() {
            return type != SignalType.NONE && confidence > 0;
        }
    }
}
