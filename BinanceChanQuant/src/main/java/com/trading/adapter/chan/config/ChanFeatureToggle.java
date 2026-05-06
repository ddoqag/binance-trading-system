package com.trading.adapter.chan.config;

/**
 * Chan Strategy Feature Toggle
 * Controls enable/shadow/disabled modes for each Chan strategy
 */
public class ChanFeatureToggle {

    public enum Mode {
        DISABLED,  // Strategy not active
        SHADOW,    // Signal output only, no trading
        ENABLED    // Full trading enabled
    }

    // Default modes - ENABLED for active trading, SHADOW for resonance filter
    private Mode reverseMode = Mode.ENABLED;
    private Mode trendMode = Mode.ENABLED;
    private Mode gridMode = Mode.ENABLED;
    private Mode resonanceMode = Mode.SHADOW;

    // Shadow traffic ratio (0.0 - 1.0)
    private double shadowTrafficRatio = 1.0;

    // Feature flags
    private boolean reverseEnabled = true;
    private boolean trendEnabled = true;
    private boolean gridEnabled = true;
    private boolean resonanceEnabled = true;

    // Resonance filter settings
    private int resonanceMinAgreement = 2;  // Minimum 2 timeframes must agree

    public static ChanFeatureToggle defaults() {
        return new ChanFeatureToggle();
    }

    // Getters
    public Mode getReverseMode() { return reverseMode; }
    public Mode getTrendMode() { return trendMode; }
    public Mode getGridMode() { return gridMode; }
    public Mode getResonanceMode() { return resonanceMode; }
    public double getShadowTrafficRatio() { return shadowTrafficRatio; }
    public boolean isReverseEnabled() { return reverseEnabled; }
    public boolean isTrendEnabled() { return trendEnabled; }
    public boolean isGridEnabled() { return gridEnabled; }
    public boolean isResonanceEnabled() { return resonanceEnabled; }
    public int getResonanceMinAgreement() { return resonanceMinAgreement; }

    // Setters for configuration
    public void setReverseMode(Mode mode) { this.reverseMode = mode; }
    public void setTrendMode(Mode mode) { this.trendMode = mode; }
    public void setGridMode(Mode mode) { this.gridMode = mode; }
    public void setResonanceMode(Mode mode) { this.resonanceMode = mode; }
    public void setShadowTrafficRatio(double ratio) { this.shadowTrafficRatio = ratio; }
    public void setResonanceMinAgreement(int min) { this.resonanceMinAgreement = min; }

    // Convenience methods
    public boolean isReverseShadow() { return reverseMode == Mode.SHADOW; }
    public boolean isTrendShadow() { return trendMode == Mode.SHADOW; }
    public boolean isGridShadow() { return gridMode == Mode.SHADOW; }
    public boolean isResonanceShadow() { return resonanceMode == Mode.SHADOW; }

    public boolean isReverseActive() { return reverseMode != Mode.DISABLED && reverseEnabled; }
    public boolean isTrendActive() { return trendMode != Mode.DISABLED && trendEnabled; }
    public boolean isGridActive() { return gridMode != Mode.DISABLED && gridEnabled; }
    public boolean isResonanceActive() { return resonanceMode != Mode.DISABLED && resonanceEnabled; }

    // Check if any Chan strategy is active
    public boolean isChanActive() {
        return isReverseActive() || isTrendActive() || isGridActive() || isResonanceActive();
    }

    // Should trading be enabled for a given mode
    public boolean shouldTrade(Mode mode) {
        return mode == Mode.ENABLED && shadowTrafficRatio >= 1.0;
    }

    // Should shadow signal be generated
    public boolean shouldGenerateShadow(Mode mode) {
        return mode == Mode.SHADOW || mode == Mode.ENABLED;
    }
}
