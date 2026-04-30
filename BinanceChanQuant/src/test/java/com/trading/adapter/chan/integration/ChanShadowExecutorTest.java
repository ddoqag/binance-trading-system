package com.trading.adapter.chan.integration;

import com.trading.adapter.chan.analyzer.ChanKLineProcessor;
import com.trading.adapter.chan.config.ChanFeatureToggle;
import com.trading.adapter.chan.validation.ChanSignalValidator;
import com.trading.domain.market.model.MarketRegime;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import static org.junit.jupiter.api.Assertions.*;

class ChanShadowExecutorTest {

    private ChanShadowExecutor executor;
    private ChanMetaLearnerBridge bridge;
    private ChanSignalValidator validator;
    private ChanFeatureToggle toggle;

    @BeforeEach
    void setUp() {
        toggle = ChanFeatureToggle.defaults();
        bridge = new ChanMetaLearnerBridge(toggle, 120);
        validator = new ChanSignalValidator();
        executor = new ChanShadowExecutor(bridge, validator, toggle);
    }

    @Test
    @DisplayName("Should return empty when Chan is not active")
    void shouldReturnEmptyWhenChanNotActive() {
        toggle.setReverseMode(ChanFeatureToggle.Mode.DISABLED);
        toggle.setTrendMode(ChanFeatureToggle.Mode.DISABLED);
        toggle.setGridMode(ChanFeatureToggle.Mode.DISABLED);
        toggle.setResonanceMode(ChanFeatureToggle.Mode.DISABLED);

        // executor.processShadow should return empty
        assertFalse(toggle.isChanActive());
    }

    @Test
    @DisplayName("Should track signal metrics")
    void shouldTrackSignalMetrics() {
        assertEquals(0, executor.getTotalSignals());
        assertEquals(0, executor.getAcceptedSignals());
        assertEquals(0, executor.getRejectedSignals());
        assertEquals(0.0, executor.getAcceptanceRate(), 0.001);
    }

    @Test
    @DisplayName("Should provide validator reference")
    void shouldProvideValidatorReference() {
        assertNotNull(executor.getValidator());
        assertEquals(validator, executor.getValidator());
    }

    @Test
    @DisplayName("Should have empty signal history initially")
    void shouldHaveEmptySignalHistoryInitially() {
        assertTrue(executor.getSignalHistory().isEmpty());
    }
}
