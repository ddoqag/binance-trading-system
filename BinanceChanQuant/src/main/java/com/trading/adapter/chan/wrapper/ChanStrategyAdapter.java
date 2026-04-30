package com.trading.adapter.chan.wrapper;

import com.trading.adapter.chan.analyzer.ChanKLineProcessor;
import com.trading.adapter.chan.analyzer.ChanKLineProcessor.KlineContext;
import com.trading.adapter.chan.config.ChanFeatureToggle;
import com.trading.adapter.chan.detector.ChanPatternDetector;
import com.trading.adapter.chan.detector.ChanPatternDetector.PatternSignal;
import com.trading.adapter.chan.detector.ChanPatternDetector.SignalType;
import com.trading.domain.market.model.MarketRegime;

/**
 * Base Adapter for Chan Strategy Wrappers
 * Implements common signal generation flow
 */
public abstract class ChanStrategyAdapter implements ChanPatternDetector {

    protected final ChanFeatureToggle toggle;
    protected final ChanKLineProcessor processor;

    protected ChanStrategyAdapter(ChanFeatureToggle toggle, ChanKLineProcessor processor) {
        this.toggle = toggle;
        this.processor = processor;
    }

    /**
     * Get processor for external access
     */
    public ChanKLineProcessor getProcessor() {
        return processor;
    }

    /**
     * Check if strategy is enabled
     */
    public boolean isStrategyEnabled() {
        return isEnabled();
    }

    protected abstract boolean isEnabled();

    @Override
    public PatternSignal detect(KlineContext ctx, MarketRegime regime) {
        return PatternSignal.none();
    }

    @Override
    public SignalType getSignalType() {
        return SignalType.NONE;
    }

    @Override
    public double getMinConfidence() {
        return 0.5;
    }

    @Override
    public boolean isApplicable(MarketRegime regime) {
        return false;
    }

    public String getSignalSource() {
        return "CHAN_BASE";
    }
}
