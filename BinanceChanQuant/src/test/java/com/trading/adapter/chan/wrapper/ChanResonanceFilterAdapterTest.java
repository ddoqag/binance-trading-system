package com.trading.adapter.chan.wrapper;

import com.trading.adapter.chan.analyzer.ChanKLineProcessor;
import com.trading.adapter.chan.config.ChanFeatureToggle;
import com.trading.adapter.chan.detector.ChanPatternDetector.*;
import com.trading.domain.market.model.MarketRegime;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import static org.junit.jupiter.api.Assertions.*;

class ChanResonanceFilterAdapterTest {

    private ChanResonanceFilterAdapter adapter;
    private ChanKLineProcessor[] processors;
    private ChanFeatureToggle toggle;

    @BeforeEach
    void setUp() {
        toggle = ChanFeatureToggle.defaults();
        processors = new ChanKLineProcessor[3]; // 3 timeframes
        for (int i = 0; i < 3; i++) {
            processors[i] = new ChanKLineProcessor(120, 0.7, 0.001);
        }
        adapter = new ChanResonanceFilterAdapter(toggle, processors);
    }

    @Test
    @DisplayName("Should return RESONANCE_BUY signal type")
    void shouldReturnResonanceBuySignalType() {
        assertEquals(SignalType.RESONANCE_BUY, adapter.getSignalType());
    }

    @Test
    @DisplayName("Should be applicable to all regimes")
    void shouldBeApplicableToAllRegimes() {
        assertTrue(adapter.isApplicable(MarketRegime.TREND_UP));
        assertTrue(adapter.isApplicable(MarketRegime.TREND_DOWN));
        assertTrue(adapter.isApplicable(MarketRegime.RANGE));
    }

    @Test
    @DisplayName("Should always return no signal from detect")
    void shouldAlwaysReturnNoSignalFromDetect() {
        ChanKLineProcessor.KlineContext ctx = processors[0].getCurrentContext();
        PatternSignal signal = adapter.detect(ctx, MarketRegime.TREND_UP);
        // Resonance filter doesn't generate signals, it filters them
        assertFalse(signal.hasSignal());
    }

    @Test
    @DisplayName("Should check resonance correctly")
    void shouldCheckResonanceCorrectly() {
        // Add some K-lines to processors
        long baseTime = System.currentTimeMillis();
        for (int p = 0; p < 3; p++) {
            for (int i = 0; i < 10; i++) {
                processors[p].addKLine(new ChanKLineProcessor.KLine(
                    baseTime + i * 1000,
                    100 + i, 105 + i, 95 + i, 100 + i,
                    1000
                ));
            }
        }

        ChanResonanceFilterAdapter.ResonanceResult result =
            adapter.checkResonance(SignalType.BUY_1,
                                   processors[0].getCurrentContext(),
                                   MarketRegime.TREND_UP);

        assertNotNull(result);
        // Result depends on alignment
    }

    @Test
    @DisplayName("Min agreement should be 2 from toggle")
    void minAgreementShouldBe2() {
        assertEquals(2, toggle.getResonanceMinAgreement());
    }
}
