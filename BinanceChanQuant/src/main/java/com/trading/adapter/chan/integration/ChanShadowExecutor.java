package com.trading.adapter.chan.integration;

import com.trading.adapter.chan.analyzer.ChanKLineProcessor;
import com.trading.adapter.chan.config.ChanFeatureToggle;
import com.trading.adapter.chan.detector.ChanPatternDetector.SignalType;
import com.trading.adapter.chan.detector.ChanPatternDetector.PatternSignal;
import com.trading.adapter.chan.validation.ChanSignalValidator;
import com.trading.domain.market.model.MarketData;
import com.trading.domain.market.model.MarketRegime;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Chan Shadow Executor
 * Executes Chan signals in shadow mode (signals only, no trading)
 */
public class ChanShadowExecutor {

    private static final Logger log = LoggerFactory.getLogger(ChanShadowExecutor.class);

    private final ChanMetaLearnerBridge metaLearnerBridge;
    private final ChanSignalValidator validator;
    private final ChanFeatureToggle featureToggle;

    private final AtomicInteger totalSignals = new AtomicInteger(0);
    private final AtomicInteger acceptedSignals = new AtomicInteger(0);
    private final AtomicInteger rejectedSignals = new AtomicInteger(0);
    private final AtomicLong lastSignalTime = new AtomicLong(0);

    private final List<ShadowSignalRecord> signalHistory = new ArrayList<>();
    private static final int MAX_HISTORY = 500;

    public ChanShadowExecutor(ChanMetaLearnerBridge bridge, ChanSignalValidator validator,
                             ChanFeatureToggle toggle) {
        this.metaLearnerBridge = bridge;
        this.validator = validator;
        this.featureToggle = toggle;
    }

    /**
     * Process market data and generate shadow signals
     */
    public Optional<ShadowSignalResult> processShadow(MarketData data, MarketRegime regime) {
        if (!featureToggle.isChanActive()) {
            log.info("Shadow signal skipped: isChanActive=false");
            return Optional.empty();
        }

        totalSignals.incrementAndGet();

        // Get current context for regime consistency check
        ChanKLineProcessor.KlineContext ctx = metaLearnerBridge.getProcessor().getCurrentContext();

        // Verify regime consistency between caller and context
        if (ctx != null && ctx.zhongshu != null) {
            MarketRegime contextRegime = metaLearnerBridge.determineRegimeFromContext(ctx);
            if (contextRegime != regime) {
                System.out.printf("[ChanShadow] Regime mismatch: passed=%s, context=%s%n", regime, contextRegime);
            }
        }

        Optional<ChanMetaLearnerBridge.ChanSignalResult> chanResult =
            metaLearnerBridge.generateSignal(data, regime);

        if (chanResult.isEmpty()) {
            log.info("Shadow signal empty: generateSignal returned empty for regime={}", regime);
            return Optional.empty();
        }

        ChanMetaLearnerBridge.ChanSignalResult result = chanResult.get();

        // Validate signal (shadow mode - separate cooldown tracking)
        ChanSignalValidator.ValidationResult validation =
            validator.validate(ctx, regime, result.confidence, true);

        ShadowSignalRecord record = new ShadowSignalRecord(
            data.getSymbol(),
            result.chanSignalType.name(),
            result.confidence,
            regime,
            validation.isValid,
            validation.reason,
            System.currentTimeMillis()
        );

        addToHistory(record);

        if (!validation.isValid) {
            rejectedSignals.incrementAndGet();
            log.debug("Shadow signal rejected: {} - {} - confidence={}", result.chanSignalType, validation.reason, result.confidence);
            return Optional.empty();
        }

        acceptedSignals.incrementAndGet();
        lastSignalTime.set(System.currentTimeMillis());

        log.info("CHAN_SHADOW_SIGNAL: symbol={}, type={}, confidence={}, weight={}",
                data.getSymbol(), result.chanSignalType, result.confidence, result.confidence);

        return Optional.of(new ShadowSignalResult(
            result.signal,
            result.chanSignalType,
            result.confidence,
            result.source,
            validation
        ));
    }

    private synchronized void addToHistory(ShadowSignalRecord record) {
        signalHistory.add(record);
        if (signalHistory.size() > MAX_HISTORY) {
            signalHistory.remove(0);
        }
    }

    // Getters
    public int getTotalSignals() { return totalSignals.get(); }
    public int getAcceptedSignals() { return acceptedSignals.get(); }
    public int getRejectedSignals() { return rejectedSignals.get(); }

    public double getAcceptanceRate() {
        int total = totalSignals.get();
        return total > 0 ? (double) acceptedSignals.get() / total : 0;
    }

    public List<ShadowSignalRecord> getSignalHistory() {
        return new ArrayList<>(signalHistory);
    }

    public ChanSignalValidator getValidator() {
        return validator;
    }

    // ========== Inner Classes ==========

    public static class ShadowSignalResult {
        public final PatternSignal signal;
        public final SignalType chanType;
        public final double confidence;
        public final String source;
        public final ChanSignalValidator.ValidationResult validation;

        public ShadowSignalResult(PatternSignal signal, SignalType chanType,
                                 double confidence, String source,
                                 ChanSignalValidator.ValidationResult validation) {
            this.signal = signal;
            this.chanType = chanType;
            this.confidence = confidence;
            this.source = source;
            this.validation = validation;
        }
    }

    public static class ShadowSignalRecord {
        public final String symbol;
        public final String signalType;
        public final double confidence;
        public final MarketRegime regime;
        public final boolean accepted;
        public final String rejectReason;
        public final long timestamp;

        public ShadowSignalRecord(String symbol, String signalType, double confidence,
                                 MarketRegime regime, boolean accepted, String rejectReason,
                                 long timestamp) {
            this.symbol = symbol;
            this.signalType = signalType;
            this.confidence = confidence;
            this.regime = regime;
            this.accepted = accepted;
            this.rejectReason = rejectReason;
            this.timestamp = timestamp;
        }
    }
}
