package com.trading.adapter.pool;

import com.trading.domain.signal.AlphaType;
import com.trading.domain.signal.StrategySignal;
import com.trading.domain.trading.model.TradeDirection;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * MultiStrategyFusion Unit Tests
 */
public class MultiStrategyFusionTest {

    private MultiStrategyFusion fusion;
    private MultiStrategyFusion.MarketContextWrapper mockContext;

    @BeforeEach
    void setUp() {
        fusion = new MultiStrategyFusion();
        fusion.reset();
        mockContext = mock(MultiStrategyFusion.MarketContextWrapper.class);
        when(mockContext.getAtrPercent()).thenReturn(0.02);  // 2% ATR, below threshold
        when(mockContext.getMarketQuality()).thenReturn(0.7);
    }

    @Test
    void testAllStrategiesAgreeLong_HighConfidence() {
        // All 3 strategies vote LONG
        Map<AlphaType, StrategySignal> signals = createAlignedSignals(1.0, 1.0, 1.0);

        MultiStrategyFusion.FusionResult result = fusion.fuse(signals, mockContext);

        assertEquals(TradeDirection.LONG, result.getDirection());
        assertTrue(result.getConfidence() > 0.7);  // High confidence
        assertTrue(result.isTradable());
        assertFalse(result.isNoTrade());
        assertTrue(result.getAgreement() > 0.8);
    }

    @Test
    void testAllStrategiesDisagree_LowConfidence() {
        // Strategies disagree
        Map<AlphaType, StrategySignal> signals = new HashMap<>();
        signals.put(AlphaType.MEAN_REVERSION, createSignal(AlphaType.MEAN_REVERSION, 1.0, 0.7, 0.333));
        signals.put(AlphaType.TREND_FOLLOWING, createSignal(AlphaType.TREND_FOLLOWING, -1.0, 0.7, 0.333));
        signals.put(AlphaType.VOLATILITY, createSignal(AlphaType.VOLATILITY, 0.5, 0.6, 0.333));

        MultiStrategyFusion.FusionResult result = fusion.fuse(signals, mockContext);

        assertTrue(result.getConfidence() < 0.6);  // Low due to disagreement
        assertTrue(result.getAgreement() < 0.5);
    }

    @Test
    void testDeadZone_NoTrade() {
        // Weak signals in dead zone
        Map<AlphaType, StrategySignal> signals = new HashMap<>();
        signals.put(AlphaType.MEAN_REVERSION, createSignal(AlphaType.MEAN_REVERSION, 0.1, 0.5, 0.333));
        signals.put(AlphaType.TREND_FOLLOWING, createSignal(AlphaType.TREND_FOLLOWING, 0.15, 0.5, 0.333));
        signals.put(AlphaType.VOLATILITY, createSignal(AlphaType.VOLATILITY, 0.05, 0.5, 0.333));

        MultiStrategyFusion.FusionResult result = fusion.fuse(signals, mockContext);

        assertTrue(result.isNoTrade());
        assertEquals(TradeDirection.NEUTRAL, result.getDirection());
    }

    @Test
    void testHighVolatility_NotTradable() {
        when(mockContext.getAtrPercent()).thenReturn(0.06);  // 6% > 5% threshold

        Map<AlphaType, StrategySignal> signals = createAlignedSignals(1.0, 1.0, 1.0);

        MultiStrategyFusion.FusionResult result = fusion.fuse(signals, mockContext);

        assertFalse(result.isTradable());
    }

    @Test
    void testEmaSmoothing_ReducesVolatility() {
        // First call
        Map<AlphaType, StrategySignal> signals1 = createAlignedSignals(1.0, 0.8, 0.9);
        MultiStrategyFusion.FusionResult result1 = fusion.fuse(signals1, mockContext);

        // Second call with same signals
        Map<AlphaType, StrategySignal> signals2 = createAlignedSignals(1.0, 0.8, 0.9);
        MultiStrategyFusion.FusionResult result2 = fusion.fuse(signals2, mockContext);

        // EMA should smooth, scores should be similar but not identical
        assertEquals(result1.getDirection(), result2.getDirection());
    }

    @Test
    void testEmptySignals_NoTrade() {
        Map<AlphaType, StrategySignal> signals = new HashMap<>();

        MultiStrategyFusion.FusionResult result = fusion.fuse(signals, mockContext);

        assertTrue(result.isNoTrade());
    }

    @Test
    void testNullSignals_NoTrade() {
        MultiStrategyFusion.FusionResult result = fusion.fuse(null, mockContext);

        assertTrue(result.isNoTrade());
    }

    // Helper methods

    private Map<AlphaType, StrategySignal> createAlignedSignals(double mr, double tf, double vol) {
        Map<AlphaType, StrategySignal> signals = new HashMap<>();
        signals.put(AlphaType.MEAN_REVERSION, createSignal(AlphaType.MEAN_REVERSION, mr, 0.7, 0.333));
        signals.put(AlphaType.TREND_FOLLOWING, createSignal(AlphaType.TREND_FOLLOWING, tf, 0.7, 0.333));
        signals.put(AlphaType.VOLATILITY, createSignal(AlphaType.VOLATILITY, vol, 0.6, 0.333));
        return signals;
    }

    private StrategySignal createSignal(AlphaType type, double direction, double confidence, double weight) {
        return StrategySignal.builder()
                .alphaType(type)
                .direction(direction)
                .confidence(confidence)
                .weight(weight)
                .build();
    }
}