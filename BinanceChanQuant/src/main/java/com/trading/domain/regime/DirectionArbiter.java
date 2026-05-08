package com.trading.domain.regime;

import com.trading.domain.trading.model.TradeDirection;

/**
 * DirectionArbiter - "Trading Constitution"
 *
 * Architecture: signal -> arbiter -> intent -> execution
 *
 * Key principle: Chan (structure) > AI (tactical timing)
 * AI cannot reverse a Chan regime. AI can only:
 * - FOLLOW (align with Chan direction)
 * - REDUCE/HOLD (when misaligned)
 * - PROBE (only when no Chan regime exists AND AI confidence > 0.8)
 *
 * NEVER:
 * - AI cannot open position opposite to Chan regime
 * - AI cannot FLIP position when Chan says HOLD
 */
public class DirectionArbiter {

    /**
     * Arbitration result combining regime and intent decision
     */
    public static class ArbiterResult {
        public final TradeDirection regimeDirection;
        public final TradeDirection aiDirection;
        public final TradeDirection finalDirection;
        public final boolean regimeAligned;
        public final String rationale;

        public ArbiterResult(TradeDirection regimeDirection, TradeDirection aiDirection,
                           TradeDirection finalDirection, boolean regimeAligned, String rationale) {
            this.regimeDirection = regimeDirection;
            this.aiDirection = aiDirection;
            this.finalDirection = finalDirection;
            this.regimeAligned = regimeAligned;
            this.rationale = rationale;
        }
    }

    /**
     * Arbitrate between regime (Chan) direction and AI signal direction
     *
     * @param regimeDirection Direction from Chan regime (NONE if no confirmed regime)
     * @param aiDirection Direction from AI expert
     * @param aiConfidence AI signal confidence (used for probe decisions)
     * @return ArbiterResult with final direction and alignment status
     */
    public ArbiterResult arbitrate(TradeDirection regimeDirection, TradeDirection aiDirection, double aiConfidence) {
        // Case 1: Confirmed regime exists
        if (regimeDirection != TradeDirection.NEUTRAL && regimeDirection != TradeDirection.WAIT) {
            return arbitrateWithRegime(regimeDirection, aiDirection);
        }

        // Case 2: No regime - AI can only PROBE with very high confidence
        return arbitrateNoRegime(aiDirection, aiConfidence);
    }

    /**
     * Regime exists - AI cannot reverse regime
     */
    private ArbiterResult arbitrateWithRegime(TradeDirection regimeDirection, TradeDirection aiDirection) {
        if (aiDirection == regimeDirection) {
            // AI aligns with regime - FOLLOW
            return new ArbiterResult(
                regimeDirection, aiDirection, regimeDirection,
                true,
                "AI aligns with Chan regime, FOLLOW"
            );
        } else if (aiDirection == TradeDirection.NEUTRAL) {
            // AI neutral - HOLD with regime direction
            return new ArbiterResult(
                regimeDirection, aiDirection, regimeDirection,
                false,
                "AI NEUTRAL, maintain regime direction"
            );
        } else {
            // AI opposite to regime - REDUCE_OR_HOLD (never FLIP)
            return new ArbiterResult(
                regimeDirection, aiDirection, TradeDirection.NEUTRAL,
                false,
                "AI opposes Chan regime, REDUCE/HOLD only"
            );
        }
    }

    /**
     * No confirmed regime - AI can only PROBE with very high confidence
     */
    private ArbiterResult arbitrateNoRegime(TradeDirection aiDirection, double aiConfidence) {
        if (aiDirection == TradeDirection.NEUTRAL) {
            return new ArbiterResult(
                TradeDirection.WAIT, aiDirection, TradeDirection.NEUTRAL,
                false,
                "No regime, AI neutral - IGNORE"
            );
        }

        // Only allow PROBE if AI confidence is very high (>0.8)
        if (aiConfidence > 0.8) {
            return new ArbiterResult(
                TradeDirection.WAIT, aiDirection, aiDirection,
                false,
                "No regime, AI conf=" + String.format("%.2f", aiConfidence) + " - PROBE allowed"
            );
        }

        // Low confidence without regime - IGNORE
        return new ArbiterResult(
            TradeDirection.WAIT, aiDirection, TradeDirection.NEUTRAL,
            false,
            "No regime, AI conf=" + String.format("%.2f", aiConfidence) + " too low - IGNORE"
        );
    }

    /**
     * Check if AI signal is aligned with regime
     */
    public boolean isAligned(TradeDirection regimeDirection, TradeDirection aiDirection) {
        if (regimeDirection == TradeDirection.WAIT) {
            return false;
        }
        return regimeDirection == aiDirection;
    }
}
