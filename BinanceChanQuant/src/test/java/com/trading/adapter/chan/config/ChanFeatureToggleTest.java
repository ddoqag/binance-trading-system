package com.trading.adapter.chan.config;

import com.trading.adapter.chan.config.ChanFeatureToggle;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import static org.junit.jupiter.api.Assertions.*;

/**
 * ChanFeatureToggle TDD Tests
 */
class ChanFeatureToggleTest {

    private ChanFeatureToggle toggle;

    @BeforeEach
    void setUp() {
        toggle = ChanFeatureToggle.defaults();
    }

    @Test
    @DisplayName("Default modes should be SHADOW")
    void defaultModesShouldBeShadow() {
        assertEquals(ChanFeatureToggle.Mode.SHADOW, toggle.getReverseMode());
        assertEquals(ChanFeatureToggle.Mode.SHADOW, toggle.getTrendMode());
        assertEquals(ChanFeatureToggle.Mode.SHADOW, toggle.getGridMode());
        assertEquals(ChanFeatureToggle.Mode.SHADOW, toggle.getResonanceMode());
    }

    @Test
    @DisplayName("Default shadow traffic ratio should be 1.0")
    void defaultShadowTrafficRatioShouldBeOne() {
        assertEquals(1.0, toggle.getShadowTrafficRatio(), 0.001);
    }

    @Test
    @DisplayName("isReverseActive should return true when not DISABLED")
    void isReverseActiveShouldReturnTrueWhenNotDisabled() {
        toggle.setReverseMode(ChanFeatureToggle.Mode.SHADOW);
        assertTrue(toggle.isReverseActive());

        toggle.setReverseMode(ChanFeatureToggle.Mode.ENABLED);
        assertTrue(toggle.isReverseActive());

        toggle.setReverseMode(ChanFeatureToggle.Mode.DISABLED);
        assertFalse(toggle.isReverseActive());
    }

    @Test
    @DisplayName("shouldTrade should only return true when ENABLED with traffic 1.0")
    void shouldTradeShouldReturnTrueOnlyWhenEnabledFullTraffic() {
        toggle.setReverseMode(ChanFeatureToggle.Mode.SHADOW);
        toggle.setShadowTrafficRatio(1.0);
        assertFalse(toggle.shouldTrade(toggle.getReverseMode()));

        toggle.setReverseMode(ChanFeatureToggle.Mode.ENABLED);
        toggle.setShadowTrafficRatio(0.5);
        assertFalse(toggle.shouldTrade(toggle.getReverseMode()));

        toggle.setReverseMode(ChanFeatureToggle.Mode.ENABLED);
        toggle.setShadowTrafficRatio(1.0);
        assertTrue(toggle.shouldTrade(toggle.getReverseMode()));
    }

    @Test
    @DisplayName("shouldGenerateShadow should return true for SHADOW and ENABLED")
    void shouldGenerateShadowShouldReturnTrueForShadowAndEnabled() {
        toggle.setReverseMode(ChanFeatureToggle.Mode.SHADOW);
        assertTrue(toggle.shouldGenerateShadow(toggle.getReverseMode()));

        toggle.setReverseMode(ChanFeatureToggle.Mode.ENABLED);
        assertTrue(toggle.shouldGenerateShadow(toggle.getReverseMode()));

        toggle.setReverseMode(ChanFeatureToggle.Mode.DISABLED);
        assertFalse(toggle.shouldGenerateShadow(toggle.getReverseMode()));
    }

    @Test
    @DisplayName("resonanceMinAgreement should default to 2")
    void resonanceMinAgreementShouldDefaultTo2() {
        assertEquals(2, toggle.getResonanceMinAgreement());
    }

    @Test
    @DisplayName("setMode should update mode correctly")
    void setModeShouldUpdateMode() {
        toggle.setReverseMode(ChanFeatureToggle.Mode.DISABLED);
        assertEquals(ChanFeatureToggle.Mode.DISABLED, toggle.getReverseMode());

        toggle.setTrendMode(ChanFeatureToggle.Mode.ENABLED);
        assertEquals(ChanFeatureToggle.Mode.ENABLED, toggle.getTrendMode());
    }

    @Test
    @DisplayName("setShadowTrafficRatio should update ratio correctly")
    void setShadowTrafficRatioShouldUpdate() {
        toggle.setShadowTrafficRatio(0.5);
        assertEquals(0.5, toggle.getShadowTrafficRatio(), 0.001);

        toggle.setShadowTrafficRatio(0.0);
        assertEquals(0.0, toggle.getShadowTrafficRatio(), 0.001);
    }
}
