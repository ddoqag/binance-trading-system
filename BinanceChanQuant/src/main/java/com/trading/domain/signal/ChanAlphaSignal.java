package com.trading.domain.signal;

import com.trading.domain.trading.model.TradeDirection;

/**
 * Chan Alpha Signal -缠论 expert signal
 */
public class ChanAlphaSignal extends AlphaSignal {

    // Chan-specific fields
    private String chanSignalType = "";  // REVERSE, TREND, GRID
    private boolean multiTimeframeResonance = false;
    private boolean hasDivergence = false;
    private boolean volumeConfirmation = false;
    private String pattern = "";
    private int strengthLevel = 0;
    private String[] timeframes = new String[0];

    public String getChanSignalType() { return chanSignalType; }
    public void setChanSignalType(String chanSignalType) { this.chanSignalType = chanSignalType; }

    public boolean isMultiTimeframeResonance() { return multiTimeframeResonance; }
    public void setMultiTimeframeResonance(boolean multiTimeframeResonance) {
        this.multiTimeframeResonance = multiTimeframeResonance;
    }

    public boolean isHasDivergence() { return hasDivergence; }
    public void setHasDivergence(boolean hasDivergence) { this.hasDivergence = hasDivergence; }

    public boolean isVolumeConfirmation() { return volumeConfirmation; }
    public void setVolumeConfirmation(boolean volumeConfirmation) {
        this.volumeConfirmation = volumeConfirmation;
    }

    public String getPattern() { return pattern; }
    public void setPattern(String pattern) { this.pattern = pattern; }

    public int getStrengthLevel() { return strengthLevel; }
    public void setStrengthLevel(int strengthLevel) { this.strengthLevel = strengthLevel; }

    public String[] getTimeframes() { return timeframes; }
    public void setTimeframes(String[] timeframes) { this.timeframes = timeframes; }

    @Override
    public double calculateScore(MarketContext context) {
        double score = confidence;

        // Multi-timeframe resonance boost
        if (multiTimeframeResonance && timeframes != null && timeframes.length >= 2) {
            score *= (1.0 + 0.1 * timeframes.length);
        }

        // Divergence boost
        if (hasDivergence) {
            score *= 1.15;
        }

        // Volume confirmation boost
        if (volumeConfirmation) {
            score *= 1.1;
        }

        // Regime match boost
        if (context != null) {
            if (type == AlphaType.CHAN_TREND && context.isTrendMarket()) {
                score *= 1.2;
            } else if (type == AlphaType.CHAN_GRID && context.isRangeMarket()) {
                score *= 1.25;
            } else if (type == AlphaType.CHAN_REVERSAL && context.isHighVolatility()) {
                score *= 1.1;
            }
        }

        // Strength level boost
        score *= (0.8 + strengthLevel * 0.05);

        return Math.min(score, 1.0);
    }

    @Override
    public String getContextKey() {
        return "CHAN_" + chanSignalType + "_" + direction.name();
    }

    // Builder
    public static Builder builder() {
        return new Builder();
    }

    public static class Builder extends AlphaSignalBuilder<ChanAlphaSignal, Builder> {
        public Builder() {
            signal = new ChanAlphaSignal();
            initSignal(signal);
        }

        public Builder chanSignalType(String type) {
            signal.chanSignalType = type;
            return this;
        }

        public Builder multiTimeframeResonance(boolean resonance) {
            signal.multiTimeframeResonance = resonance;
            return this;
        }

        public Builder hasDivergence(boolean divergence) {
            signal.hasDivergence = divergence;
            return this;
        }

        public Builder volumeConfirmation(boolean confirm) {
            signal.volumeConfirmation = confirm;
            return this;
        }

        public Builder pattern(String pattern) {
            signal.pattern = pattern;
            return this;
        }

        public Builder strengthLevel(int level) {
            signal.strengthLevel = level;
            return this;
        }

        public Builder timeframes(String... tf) {
            signal.timeframes = tf;
            return this;
        }

        @Override
        public ChanAlphaSignal build() {
            // Chan signals always map to CHAN_TREND type (chanSignalType is used for display only)
            signal.type = AlphaType.CHAN_TREND;
            return super.build();
        }
    }
}