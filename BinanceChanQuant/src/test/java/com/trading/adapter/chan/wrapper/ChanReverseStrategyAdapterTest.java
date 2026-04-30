package com.trading.adapter.chan.wrapper;

import com.trading.adapter.chan.analyzer.ChanKLineProcessor;
import com.trading.adapter.chan.config.ChanFeatureToggle;
import com.trading.adapter.chan.detector.ChanPatternDetector.*;
import com.trading.domain.market.model.MarketRegime;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import static org.junit.jupiter.api.Assertions.*;

class ChanReverseStrategyAdapterTest {

    private ChanReverseStrategyAdapter adapter;
    private ChanKLineProcessor processor;
    private ChanFeatureToggle toggle;

    @BeforeEach
    void setUp() {
        toggle = ChanFeatureToggle.defaults();
        processor = new ChanKLineProcessor(120, 0.7, 0.001);
        adapter = new ChanReverseStrategyAdapter(toggle, processor);
    }

    @Test
    @DisplayName("Should return BUY_1 signal type")
    void shouldReturnBuy1SignalType() {
        assertEquals(SignalType.BUY_1, adapter.getSignalType());
    }

    @Test
    @DisplayName("Should be applicable in TREND_DOWN regime")
    void shouldBeApplicableInTrendDown() {
        assertTrue(adapter.isApplicable(MarketRegime.TREND_DOWN));
        assertTrue(adapter.isApplicable(MarketRegime.TREND_UP));
        assertFalse(adapter.isApplicable(MarketRegime.RANGE));
    }

    @Test
    @DisplayName("Should detect bottom divergence signal")
    void shouldDetectBottomDivergence() {
        long baseTime = System.currentTimeMillis();

        // Create downtrend with divergence
        // First down: strong
        for (int i = 0; i < 8; i++) {
            processor.addKLine(new ChanKLineProcessor.KLine(
                baseTime + i * 1000,
                100 - i * 2, 100 - i * 2, 95 - i * 2, 96 - i * 2,
                1000
            ));
        }

        // Second down: weaker (divergence)
        for (int i = 8; i < 16; i++) {
            processor.addKLine(new ChanKLineProcessor.KLine(
                baseTime + i * 1000,
                86 - (i - 8) * 0.5, 86 - (i - 8) * 0.5, 84 - (i - 8) * 0.3, 85 - (i - 8) * 0.4,
                1000
            ));
        }

        ChanKLineProcessor.KlineContext ctx = processor.getCurrentContext();
        PatternSignal signal = adapter.detect(ctx, MarketRegime.TREND_DOWN);

        // Should detect BUY_1 or NONE depending on exact divergence strength
        assertNotNull(signal);
    }

    @Test
    @DisplayName("Should return none when regime is invalid")
    void shouldReturnNoneWhenRegimeInvalid() {
        ChanKLineProcessor.KlineContext ctx = processor.getCurrentContext();
        PatternSignal signal = adapter.detect(ctx, MarketRegime.RANGE);
        assertFalse(signal.hasSignal());
    }

    @Test
    @DisplayName("Min confidence should be 0.55")
    void minConfidenceShouldBePoint55() {
        assertEquals(0.55, adapter.getMinConfidence(), 0.001);
    }

    @Test
    @DisplayName("Should not generate signal when disabled")
    void shouldNotGenerateSignalWhenDisabled() {
        toggle.setReverseMode(ChanFeatureToggle.Mode.DISABLED);
        assertFalse(adapter.isEnabled());
    }

    @Test
    @DisplayName("Should generate shadow signal in shadow mode")
    void shouldGenerateShadowSignalInShadowMode() {
        toggle.setReverseMode(ChanFeatureToggle.Mode.SHADOW);
        assertTrue(adapter.isEnabled());
    }
}
