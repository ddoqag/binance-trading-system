package com.trading.domain.market;

import com.trading.adapter.chan.analyzer.ChanKLineProcessor.Bi;
import com.trading.adapter.chan.analyzer.ChanKLineProcessor.Fenxing;
import com.trading.adapter.chan.analyzer.ChanKLineProcessor.KlineContext;
import com.trading.domain.market.model.MarketRegime;

/**
 * Regime Calculator - Single Source of Truth for Market Regime determination
 *
 * Pure function that computes MarketRegime from Chan theory components.
 * Used by both AlphaPool (via MarketContext) and ChanMetaLearnerBridge.
 *
 * Logic hierarchy:
 * 1. If Zhongshu exists → use lastBi.direction (trend)
 * 2. If no Zhongshu but has Fenxing → use lastFenxing.type (direction)
 * 3. Otherwise → RANGE (no clear structure)
 *
 * This ensures tick-level consistency: all components see the same regime
 * computed from the same K-line snapshot.
 */
public final class RegimeCalculator {

    private RegimeCalculator() {} // Utility class

    /**
     * Calculate regime from KlineContext (Chan theory components)
     */
    public static MarketRegime calculate(KlineContext ctx) {
        if (ctx == null) {
            return MarketRegime.UNKNOWN;
        }

        // Priority 1: If Zhongshu exists → trend based on Bi direction
        if (ctx.zhongshu != null) {
            if (ctx.lastBi != null) {
                return ctx.lastBi.direction == Bi.Direction.UP
                    ? MarketRegime.TREND_UP
                    : MarketRegime.TREND_DOWN;
            }
            return MarketRegime.RANGE;
        }

        // Priority 2: No Zhongshu but has Fenxing → direction based on Fenxing type
        if (ctx.lastFenxing != null) {
            return ctx.lastFenxing.type == Fenxing.Type.TOP
                ? MarketRegime.TREND_DOWN
                : MarketRegime.TREND_UP;
        }

        // Priority 3: No structure → RANGE
        return MarketRegime.RANGE;
    }

    /**
     * Calculate regime from individual components (for cases where ctx is not available)
     */
    public static MarketRegime calculate(boolean hasZhongshu, Bi lastBi, Fenxing lastFenxing) {
        if (hasZhongshu && lastBi != null) {
            return lastBi.direction == Bi.Direction.UP
                ? MarketRegime.TREND_UP
                : MarketRegime.TREND_DOWN;
        }

        if (lastFenxing != null) {
            return lastFenxing.type == Fenxing.Type.TOP
                ? MarketRegime.TREND_DOWN
                : MarketRegime.TREND_UP;
        }

        return MarketRegime.RANGE;
    }
}