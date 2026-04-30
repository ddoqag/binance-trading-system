package com.trading.adapter.pool;

import com.trading.domain.signal.AlphaExpert;
import com.trading.domain.signal.AlphaSignal;
import com.trading.domain.signal.AlphaType;
import com.trading.domain.signal.CompositeAlphaSignal;
import com.trading.domain.signal.MarketContext;
import com.trading.domain.market.model.MarketRegime;
import com.trading.domain.trading.model.TradeDirection;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import static org.junit.jupiter.api.Assertions.*;

/**
 * AlphaPool TDD Tests
 */
class AlphaPoolTest {

    private AlphaPool alphaPool;

    @BeforeEach
    void setUp() {
        alphaPool = new AlphaPool();
    }

    // ========== Single Expert Tests ==========

    @Test
    @DisplayName("Single expert should return signal from that expert")
    void singleExpertShouldReturnSignal() {
        // Create mock expert with LONG signal
        MockAlphaExpert expert = new MockAlphaExpert(createSignal(
            TradeDirection.LONG, 0.7, AlphaType.MEAN_REVERSION, "mock1"
        ));
        alphaPool.registerExpert(expert);

        MarketContext context = createContext(MarketRegime.RANGE);

        CompositeAlphaSignal result = alphaPool.generateCompositeSignal(context);

        assertNotNull(result, "Should return composite signal");
        assertEquals(TradeDirection.LONG, result.getDirection(), "Direction should be LONG");
    }

    @Test
    @DisplayName("Single expert with low confidence should return null when filtered")
    void lowConfidenceShouldReturnNull() {
        MockAlphaExpert expert = new MockAlphaExpert(createSignal(
            TradeDirection.LONG, 0.0, AlphaType.MEAN_REVERSION, "mock1"
        ));
        alphaPool.registerExpert(expert);

        MarketContext context = createContext(MarketRegime.RANGE);

        CompositeAlphaSignal result = alphaPool.generateCompositeSignal(context);

        assertNull(result, "Should return null for zero confidence signal");
    }

    // ========== Conflict Resolution Tests ==========

    @Test
    @DisplayName("Opposite direction signals should trigger conflict resolution")
    void oppositeDirectionSignalsShouldTriggerConflictResolution() {
        // Register two experts with opposite directions
        MockAlphaExpert longExpert = new MockAlphaExpert(createSignal(
            TradeDirection.LONG, 0.8, AlphaType.TREND_FOLLOWING, "trend"
        ));
        MockAlphaExpert shortExpert = new MockAlphaExpert(createSignal(
            TradeDirection.SHORT, 0.8, AlphaType.MEAN_REVERSION, "mean_rev"
        ));
        alphaPool.registerExpert(longExpert);
        alphaPool.registerExpert(shortExpert);

        MarketContext context = createContext(MarketRegime.RANGE);

        CompositeAlphaSignal result = alphaPool.generateCompositeSignal(context);

        assertNotNull(result, "Should resolve conflict and return signal");
    }

    @Test
    @DisplayName("Conflict resolution in range market should prefer MEAN_REVERSION")
    void rangeMarketConflictShouldPreferMeanReversion() {
        MockAlphaExpert trendExpert = new MockAlphaExpert(createSignal(
            TradeDirection.LONG, 0.7, AlphaType.TREND_FOLLOWING, "trend"
        ));
        MockAlphaExpert meanRevExpert = new MockAlphaExpert(createSignal(
            TradeDirection.SHORT, 0.7, AlphaType.MEAN_REVERSION, "mean_rev"
        ));
        alphaPool.registerExpert(trendExpert);
        alphaPool.registerExpert(meanRevExpert);

        MarketContext context = createContext(MarketRegime.RANGE);

        CompositeAlphaSignal result = alphaPool.generateCompositeSignal(context);

        assertNotNull(result, "Should resolve and return a signal");
        assertEquals(AlphaType.MEAN_REVERSION, result.getType(),
            "In range market, MEAN_REVERSION should be preferred");
    }

    @Test
    @DisplayName("Conflict resolution in trend market should prefer TREND_FOLLOWING")
    void trendMarketConflictShouldPreferTrendFollowing() {
        MockAlphaExpert meanRevExpert = new MockAlphaExpert(createSignal(
            TradeDirection.SHORT, 0.7, AlphaType.MEAN_REVERSION, "mean_rev"
        ));
        MockAlphaExpert trendExpert = new MockAlphaExpert(createSignal(
            TradeDirection.LONG, 0.7, AlphaType.TREND_FOLLOWING, "trend"
        ));
        alphaPool.registerExpert(meanRevExpert);
        alphaPool.registerExpert(trendExpert);

        MarketContext context = createContext(MarketRegime.TREND_UP);

        CompositeAlphaSignal result = alphaPool.generateCompositeSignal(context);

        assertNotNull(result, "Should resolve and return a signal");
        assertEquals(AlphaType.TREND_FOLLOWING, result.getType(),
            "In TREND_UP market, TREND_FOLLOWING should be preferred");
    }

    @Test
    @DisplayName("High volatility conflict should prefer VOLATILITY expert")
    void highVolatilityConflictShouldPreferVolatility() {
        // Both signals have similar weighted scores (~0.51 MR, ~0.51 VL if VL has higher weight)
        // In high volatility, VOLATILITY should be preferred over MEAN_REVERSION
        // Since weights: MR=0.3, VL=0.2, we need MR to score lower
        // MR score = 0.85*0.02*100*0.3 = 0.51, VL score = 0.85*0.02*100*0.2 = 0.34
        // We need both to be similar and pass the 0.8 threshold check
        // Adjust so VOLATILITY has enough score to be considered a conflict
        MockAlphaExpert meanRevExpert = new MockAlphaExpert(createSignal(
            TradeDirection.SHORT, 0.85, AlphaType.MEAN_REVERSION, "mean_rev"
        ));
        MockAlphaExpert volatilityExpert = new MockAlphaExpert(createSignal(
            TradeDirection.LONG, 0.99, AlphaType.VOLATILITY, "volatility"
        ));
        alphaPool.registerExpert(meanRevExpert);
        alphaPool.registerExpert(volatilityExpert);

        MarketContext context = createContext(MarketRegime.RANGE);
        context.setVolatilityRegime(com.trading.domain.signal.VolatilityRegime.HIGH);

        CompositeAlphaSignal result = alphaPool.generateCompositeSignal(context);

        assertNotNull(result, "Should resolve and return a signal");
        assertEquals(AlphaType.VOLATILITY, result.getType(),
            "In high volatility, VOLATILITY expert should be preferred");
    }

    // ========== Empty Experts Tests ==========

    @Test
    @DisplayName("Empty pool should return null")
    void emptyPoolShouldReturnNull() {
        MarketContext context = createContext(MarketRegime.RANGE);

        CompositeAlphaSignal result = alphaPool.generateCompositeSignal(context);

        assertNull(result, "Empty pool should return null");
    }

    @Test
    @DisplayName("Pool with null expert should be handled")
    void nullExpertShouldBeHandled() {
        alphaPool.registerExpert(null);

        MarketContext context = createContext(MarketRegime.RANGE);

        CompositeAlphaSignal result = alphaPool.generateCompositeSignal(context);

        assertNull(result, "Pool with only null experts should return null");
    }

    // ========== Expert Count Tests ==========

    @Test
    @DisplayName("Expert count should be correct")
    void expertCountShouldBeCorrect() {
        alphaPool.registerExpert(new MockAlphaExpert(createSignal(
            TradeDirection.LONG, 0.7, AlphaType.MEAN_REVERSION, "expert1"
        )));
        alphaPool.registerExpert(new MockAlphaExpert(createSignal(
            TradeDirection.SHORT, 0.7, AlphaType.TREND_FOLLOWING, "expert2"
        )));

        assertEquals(2, alphaPool.getExpertCount(), "Should have 2 experts");
    }

    // ========== Helper Methods ==========

    private MarketContext createContext(MarketRegime regime) {
        return MarketContext.builder()
            .regime(regime)
            .volatilityRegime(com.trading.domain.signal.VolatilityRegime.MEDIUM)
            .trendStrength(com.trading.domain.signal.TrendStrength.NONE)
            .currentPrice(50000)
            .atr(100)
            .atrPercent(0.02)
            .volumeRatio(1.0)
            .timestamp(System.currentTimeMillis())
            .build();
    }

    private AlphaSignal createSignal(TradeDirection direction, double confidence,
                                      AlphaType type, String source) {
        return new TestAlphaSignal(direction, confidence, type, source);
    }

    /**
     * Mock AlphaExpert for testing
     */
    static class MockAlphaExpert extends AlphaExpert.BaseAlphaExpert {
        private AlphaSignal fixedSignal;

        public MockAlphaExpert(AlphaSignal signal) {
            super("mock_" + signal.getSource(), "Mock", signal.getType());
            this.fixedSignal = signal;
        }

        @Override
        public AlphaSignal generate(MarketContext context) {
            return fixedSignal;
        }
    }

    /**
     * Simple concrete AlphaSignal for testing
     */
    static class TestAlphaSignal extends AlphaSignal {
        TestAlphaSignal(TradeDirection direction, double confidence, AlphaType type, String source) {
            this.direction = direction;
            this.confidence = confidence;
            this.type = type;
            this.source = source;
            this.entryPrice = 50000;
            this.stopLossPrice = 49000;
            this.takeProfitPrice = 51000;
            this.urgency = 0.5;
            this.horizonMinutes = 60;
            this.expectedReturn = 0.02;
            this.expectedVolatility = 0.01;
        }

        @Override
        public double calculateScore(MarketContext context) {
            return confidence * expectedReturn * 100;
        }
    }
}
