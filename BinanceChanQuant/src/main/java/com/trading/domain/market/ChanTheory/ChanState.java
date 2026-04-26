package com.trading.domain.market.ChanTheory;

/**
 * Chan Market State - Four states classification
 * Based on 缠论 (Chan Theory) market analysis
 */
public enum ChanState {
    /** Consolidation: range < 1.5% */
    CONSOLIDATION,

    /** Up Trend: price in top 40% of range */
    UP_TREND,

    /** Down Trend: price in bottom 40% of range */
    DOWN_TREND,

    /** Divergence Turn: mid-range transition */
    DIVERGENCE_TURN
}
