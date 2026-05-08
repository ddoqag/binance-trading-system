package com.trading.adapter.chan.wrapper;

import com.trading.adapter.chan.analyzer.ChanKLineProcessor;
import com.trading.adapter.chan.config.ChanFeatureToggle;
import com.trading.adapter.chan.detector.ChanPatternDetector.*;
import com.trading.domain.market.model.MarketRegime;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import static org.junit.jupiter.api.Assertions.*;

class ChanGridStrategyAdapterTest {

    private ChanGridStrategyAdapter adapter;
    private ChanKLineProcessor processor;
    private ChanFeatureToggle toggle;

    @BeforeEach
    void setUp() {
        toggle = ChanFeatureToggle.defaults();
        processor = new ChanKLineProcessor(120, 0.7, 0.001);
        adapter = new ChanGridStrategyAdapter(toggle, processor);
    }

    @Test
    @DisplayName("Should return RANGE_BOUND signal type")
    void shouldReturnRangeBoundSignalType() {
        assertEquals(SignalType.RANGE_BOUND, adapter.getSignalType());
    }

    @Test
    @DisplayName("Should only be applicable in RANGE regime")
    void shouldOnlyBeApplicableInRangeRegime() {
        assertTrue(adapter.isApplicable(MarketRegime.RANGE));
        assertFalse(adapter.isApplicable(MarketRegime.TREND_UP));
        assertFalse(adapter.isApplicable(MarketRegime.TREND_DOWN));
    }

    @Test
    @DisplayName("Should return none without zhongshu")
    void shouldReturnNoneWithoutZhongshu() {
        ChanKLineProcessor.KlineContext ctx = processor.getCurrentContext();
        PatternSignal signal = adapter.detect(ctx, MarketRegime.RANGE);
        assertFalse(signal.hasSignal());
    }

    @Test
    @DisplayName("Min confidence should be 0.35 for provisional signals")
    void minConfidenceShouldBePoint35() {
        assertEquals(0.35, adapter.getMinConfidence(), 0.001);
    }
}
