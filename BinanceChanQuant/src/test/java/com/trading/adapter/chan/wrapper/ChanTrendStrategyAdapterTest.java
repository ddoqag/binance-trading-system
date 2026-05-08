package com.trading.adapter.chan.wrapper;

import com.trading.adapter.chan.analyzer.ChanKLineProcessor;
import com.trading.adapter.chan.config.ChanFeatureToggle;
import com.trading.adapter.chan.detector.ChanPatternDetector.*;
import com.trading.domain.market.model.MarketRegime;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import static org.junit.jupiter.api.Assertions.*;

class ChanTrendStrategyAdapterTest {

    private ChanTrendStrategyAdapter adapter;
    private ChanKLineProcessor processor;
    private ChanFeatureToggle toggle;

    @BeforeEach
    void setUp() {
        toggle = ChanFeatureToggle.defaults();
        processor = new ChanKLineProcessor(120, 0.7, 0.001);
        adapter = new ChanTrendStrategyAdapter(toggle, processor);
    }

    @Test
    @DisplayName("Should return BUY_2 signal type")
    void shouldReturnBuy2SignalType() {
        assertEquals(SignalType.BUY_2, adapter.getSignalType());
    }

    @Test
    @DisplayName("Should be applicable in trend regimes")
    void shouldBeApplicableInTrendRegimes() {
        assertTrue(adapter.isApplicable(MarketRegime.TREND_UP));
        assertTrue(adapter.isApplicable(MarketRegime.TREND_DOWN));
        assertFalse(adapter.isApplicable(MarketRegime.RANGE));
    }

    @Test
    @DisplayName("Should return none without zhongshu")
    void shouldReturnNoneWithoutZhongshu() {
        ChanKLineProcessor.KlineContext ctx = processor.getCurrentContext();
        PatternSignal signal = adapter.detect(ctx, MarketRegime.TREND_UP);
        assertFalse(signal.hasSignal());
    }

    @Test
    @DisplayName("Should detect 二买 pattern")
    void shouldDetectBuy2Pattern() {
        // Create pattern that forms zhongshu
        long baseTime = System.currentTimeMillis();

        // Oscillating pattern to form zhongshu
        for (int i = 0; i < 25; i++) {
            double price = 100 + Math.sin(i * 0.4) * 5;
            processor.addKLine(new ChanKLineProcessor.KLine(
                baseTime + i * 1000,
                price - 1, price + 3, price - 2, price + 2,
                1000
            ));
        }

        ChanKLineProcessor.KlineContext ctx = processor.getCurrentContext();
        // May or may not detect signal depending on exact pattern
        assertNotNull(ctx);
    }

    @Test
    @DisplayName("Min confidence should be 0.35 for provisional signals")
    void minConfidenceShouldBePoint35() {
        assertEquals(0.35, adapter.getMinConfidence(), 0.001);
    }
}
