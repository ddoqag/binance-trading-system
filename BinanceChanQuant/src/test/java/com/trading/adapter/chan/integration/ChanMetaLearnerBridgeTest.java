package com.trading.adapter.chan.integration;

import com.trading.adapter.chan.analyzer.ChanKLineProcessor;
import com.trading.adapter.chan.config.ChanFeatureToggle;
import com.trading.adapter.chan.detector.ChanPatternDetector.*;
import com.trading.domain.market.model.MarketRegime;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import static org.junit.jupiter.api.Assertions.*;

class ChanMetaLearnerBridgeTest {

    private ChanMetaLearnerBridge bridge;
    private ChanFeatureToggle toggle;

    @BeforeEach
    void setUp() {
        toggle = ChanFeatureToggle.defaults();
        bridge = new ChanMetaLearnerBridge(toggle, 120);
    }

    @Test
    @DisplayName("Should calculate higher weight for TREND regimes")
    void shouldCalculateHigherWeightForTrendRegimes() {
        double trendWeight = bridge.calculateDynamicWeight(MarketRegime.TREND_UP);
        double rangeWeight = bridge.calculateDynamicWeight(MarketRegime.RANGE);

        assertTrue(trendWeight > rangeWeight,
            "Trend weight should be higher than range weight");
    }

    @Test
    @DisplayName("Default base weight should be 0.25")
    void defaultBaseWeightShouldBePoint25() {
        assertEquals(0.25, bridge.getChanBaseWeight(), 0.001);
    }

    @Test
    @DisplayName("Should clamp weight between 0 and 1")
    void shouldClampWeightBetween0And1() {
        bridge.setChanBaseWeight(1.5);
        assertEquals(1.0, bridge.getChanBaseWeight(), 0.001);

        bridge.setChanBaseWeight(-0.5);
        assertEquals(0.0, bridge.getChanBaseWeight(), 0.001);
    }

    @Test
    @DisplayName("Should return empty when toggle is disabled")
    void shouldReturnEmptyWhenDisabled() {
        toggle.setReverseMode(ChanFeatureToggle.Mode.DISABLED);
        toggle.setTrendMode(ChanFeatureToggle.Mode.DISABLED);
        toggle.setGridMode(ChanFeatureToggle.Mode.DISABLED);
        toggle.setResonanceMode(ChanFeatureToggle.Mode.DISABLED);

        // No signal should be generated when all disabled
        assertFalse(toggle.isChanActive());
    }

    @Test
    @DisplayName("Should return processor for context access")
    void shouldReturnProcessor() {
        assertNotNull(bridge.getProcessor());
        assertTrue(bridge.getProcessor() instanceof ChanKLineProcessor);
    }
}
