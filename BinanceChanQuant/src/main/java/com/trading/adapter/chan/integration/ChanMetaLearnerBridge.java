package com.trading.adapter.chan.integration;

import com.trading.adapter.chan.analyzer.ChanKLineProcessor;
import com.trading.adapter.chan.analyzer.ChanKLineProcessor.Bi;
import com.trading.adapter.chan.analyzer.ChanKLineProcessor.Fenxing;
import com.trading.adapter.chan.analyzer.ChanKLineProcessor.KlineContext;
import com.trading.adapter.chan.config.ChanFeatureToggle;
import com.trading.adapter.chan.detector.ChanPatternDetector.SignalType;
import com.trading.adapter.chan.detector.ChanPatternDetector.PatternSignal;
import com.trading.adapter.chan.wrapper.ChanResonanceFilterAdapter;
import com.trading.adapter.chan.wrapper.ChanResonanceFilterAdapter.ResonanceResult;
import com.trading.adapter.chan.wrapper.ChanStrategyAdapter;
import com.trading.adapter.chan.wrapper.ChanReverseStrategyAdapter;
import com.trading.adapter.chan.wrapper.ChanTrendStrategyAdapter;
import com.trading.adapter.chan.wrapper.ChanGridStrategyAdapter;
import com.trading.domain.market.model.MarketData;
import com.trading.domain.market.model.MarketRegime;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Optional;

/**
 * Chan Meta-Learner Bridge
 * Integrates Chan strategies into MetaLearner as Expert 4
 */
public class ChanMetaLearnerBridge {

    private static final Logger log = LoggerFactory.getLogger(ChanMetaLearnerBridge.class);

    private final ChanFeatureToggle featureToggle;
    private final ChanReverseStrategyAdapter reverseAdapter;
    private final ChanTrendStrategyAdapter trendAdapter;
    private final ChanGridStrategyAdapter gridAdapter;
    private final ChanResonanceFilterAdapter resonanceAdapter;

    private final ChanKLineProcessor[] multiTimeframeProcessors;

    // Base weights (均衡分配)
    private double chanBaseWeight = 0.25;

    // Regime-specific weight adjustments
    private static final double[] REGIME_WEIGHTS = {
        0.0,   // UNKNOWN
        0.25,  // RANGE
        0.40,  // TREND_UP (raised for trend signals)
        0.40,  // TREND_DOWN (raised for trend signals)
        0.20,  // HIGH_VOL
        0.20   // LOW_VOL
    };

    public ChanMetaLearnerBridge(ChanFeatureToggle toggle, int windowSize) {
        this.featureToggle = toggle;
        ChanKLineProcessor processor = new ChanKLineProcessor(windowSize, 0.7, 0.001);

        this.reverseAdapter = new ChanReverseStrategyAdapter(toggle, processor);
        this.trendAdapter = new ChanTrendStrategyAdapter(toggle, processor);
        this.gridAdapter = new ChanGridStrategyAdapter(toggle, processor);

        this.multiTimeframeProcessors = new ChanKLineProcessor[3];
        this.multiTimeframeProcessors[0] = processor;
        this.multiTimeframeProcessors[1] = new ChanKLineProcessor(windowSize, 0.7, 0.001);
        this.multiTimeframeProcessors[2] = new ChanKLineProcessor(windowSize, 0.7, 0.001);

        this.resonanceAdapter = new ChanResonanceFilterAdapter(toggle, multiTimeframeProcessors);
    }

    /**
     * Generate Chan signal for market data
     */
    public Optional<ChanSignalResult> generateSignal(MarketData data, MarketRegime regime) {
        // Process K-line data to update Chan analysis
        multiTimeframeProcessors[0].processMarketData(data);

        KlineContext ctx = multiTimeframeProcessors[0].getCurrentContext();

        // Re-determine regime based on current context (since K-line was just added)
        regime = determineRegimeFromContext(ctx);

        ChanStrategyAdapter adapter = selectAdapter(regime);
        if (adapter == null) {
            log.debug("generateSignal: no adapter for regime={}", regime);
            return Optional.empty();
        }

        if (!adapter.isStrategyEnabled()) {
            log.debug("generateSignal: adapter {} not enabled", adapter.getClass().getSimpleName());
            return Optional.empty();
        }

        PatternSignal signal = adapter.detect(ctx, regime);

        if (!signal.hasSignal()) {
            log.debug("generateSignal: no signal hasSignal=false for regime={}", regime);
            return Optional.empty();
        }
        if (signal.confidence < adapter.getMinConfidence()) {
            log.debug("generateSignal: confidence {} < min {} for regime={}",
                signal.confidence, adapter.getMinConfidence(), regime);
            return Optional.empty();
        }

        // Apply resonance filter - only filter in ENABLED mode, not SHADOW
        double resonanceMultiplier = 1.0;
        if (resonanceAdapter.isStrategyEnabled()) {
            ResonanceResult resonance = resonanceAdapter.checkResonance(
                adapter.getSignalType(), ctx, regime
            );

            if (resonance.hasResonance) {
                resonanceMultiplier = resonance.strength;
                log.debug("Resonance: {} level, strength={}", resonance.level, resonance.strength);
            } else if (featureToggle.isResonanceActive() &&
                       featureToggle.getResonanceMode() == ChanFeatureToggle.Mode.ENABLED) {
                // Only filter signals when resonance is in ENABLED mode, not SHADOW
                log.debug("No resonance - signal filtered");
                return Optional.empty();
            }
            // In SHADOW mode, allow signals through even without resonance
        }

        double dynamicWeight = calculateDynamicWeight(regime);

        return Optional.of(new ChanSignalResult(
            signal,
            adapter.getSignalType(),
            dynamicWeight * resonanceMultiplier,
            adapter.getSignalSource()
        ));
    }

    private ChanStrategyAdapter selectAdapter(MarketRegime regime) {
        switch (regime) {
            case RANGE:
                return gridAdapter;
            case TREND_UP:
            case TREND_DOWN:
                if (trendAdapter.isStrategyEnabled()) return trendAdapter;
                if (reverseAdapter.isStrategyEnabled()) return reverseAdapter;
                return null;
            default:
                return null;
        }
    }

    /**
     * Determine regime from current context (after K-line processed)
     */
    private MarketRegime determineRegimeFromContext(KlineContext ctx) {
        if (ctx == null || ctx.zhongshu == null) {
            if (ctx != null && ctx.lastFenxing != null) {
                return ctx.lastFenxing.type == Fenxing.Type.TOP
                    ? MarketRegime.TREND_DOWN : MarketRegime.TREND_UP;
            }
            return MarketRegime.RANGE;
        }

        if (ctx.lastBi != null) {
            return ctx.lastBi.direction == Bi.Direction.UP
                ? MarketRegime.TREND_UP : MarketRegime.TREND_DOWN;
        }
        return MarketRegime.RANGE;
    }

    public double calculateDynamicWeight(MarketRegime regime) {
        int regimeIndex = regime.ordinal();
        if (regimeIndex < REGIME_WEIGHTS.length) {
            return REGIME_WEIGHTS[regimeIndex];
        }
        return chanBaseWeight;
    }

    public void setChanBaseWeight(double weight) {
        this.chanBaseWeight = Math.max(0, Math.min(1.0, weight));
    }

    public double getChanBaseWeight() {
        return chanBaseWeight;
    }

    public ChanKLineProcessor getProcessor() {
        return multiTimeframeProcessors[0];
    }

    // ========== Inner Classes ==========

    public static class ChanSignalResult {
        public final PatternSignal signal;
        public final SignalType chanSignalType;
        public final double confidence;
        public final String source;

        public ChanSignalResult(PatternSignal signal, SignalType chanSignalType,
                               double confidence, String source) {
            this.signal = signal;
            this.chanSignalType = chanSignalType;
            this.confidence = confidence;
            this.source = source;
        }

        public double getWeightedScore() {
            return confidence * 0.8 + 0.2;
        }
    }
}
