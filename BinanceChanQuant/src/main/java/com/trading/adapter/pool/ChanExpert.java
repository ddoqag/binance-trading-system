package com.trading.adapter.pool;

import com.trading.adapter.chan.analyzer.ChanKLineProcessor;
import com.trading.adapter.chan.analyzer.ChanKLineProcessor.KlineContext;
import com.trading.adapter.chan.detector.ChanPatternDetector.SignalType;
import com.trading.adapter.chan.integration.ChanMetaLearnerBridge;
import com.trading.adapter.chan.integration.ChanMetaLearnerBridge.ChanSignalResult;
import com.trading.adapter.chan.validation.ChanSignalValidator;
import com.trading.adapter.chan.validation.ChanSignalValidator.ValidationResult;
import com.trading.adapter.chan.config.ChanFeatureToggle;
import com.trading.domain.market.model.MarketData;
import com.trading.domain.market.model.MarketRegime;
import com.trading.domain.signal.AlphaExpert;
import com.trading.domain.signal.AlphaSignal;
import com.trading.domain.signal.AlphaType;
import com.trading.domain.signal.ChanAlphaSignal;
import com.trading.domain.signal.MarketContext;

import java.util.Optional;

/**
 * Chan Expert - wraps Chan analysis as AlphaExpert
 */
public class ChanExpert extends AlphaExpert.BaseAlphaExpert {

    private final ChanMetaLearnerBridge bridge;
    private final ChanSignalValidator validator;
    private final ChanKLineProcessor processor;
    private final ChanFeatureToggle toggle;

    public ChanExpert(ChanMetaLearnerBridge bridge, ChanSignalValidator validator,
                      ChanKLineProcessor processor, ChanFeatureToggle toggle) {
        super("chan", "Chan Theory Expert", AlphaType.CHAN_TREND);
        this.bridge = bridge;
        this.validator = validator;
        this.processor = processor;
        this.toggle = toggle;
    }

    @Override
    public AlphaSignal generate(MarketContext context) {
        if (!active || context == null) {
            System.out.println("[ChanExpert] generate: inactive or null context");
            return null;
        }

        MarketData data = context.getMarketData();
        if (data == null) {
            System.out.println("[ChanExpert] generate: null market data");
            return null;
        }

        try {
            MarketRegime regime = context.getRegime();

            // Process through Chan bridge
            Optional<ChanSignalResult> optResult = bridge.generateSignal(data, regime);
            if (optResult.isEmpty()) {
                System.out.println("[ChanExpert] generate: bridge returned empty");
                return null;
            }

            ChanSignalResult result = optResult.get();

            // Validate signal using the processor's KlineContext
            KlineContext klineCtx = processor.getCurrentContext();
            ValidationResult validation = validator.validate(klineCtx, regime, result.confidence);
            if (!validation.isValid) {
                System.out.printf("[ChanExpert] generate: validation failed: %s (%s)%n",
                    validation.code, validation.reason);
                return null;
            }

            // Build ChanAlphaSignal from result
            return buildChanSignal(result, context);

        } catch (Exception e) {
            System.err.println("[ChanExpert] Signal generation failed: " + e.getMessage());
            e.printStackTrace();
            return null;
        }
    }

    private AlphaSignal buildChanSignal(ChanSignalResult result, MarketContext context) {
        ChanAlphaSignal.Builder builder = ChanAlphaSignal.builder()
            .direction(extractDirection(result))
            .confidence(result.confidence)
            .urgency(0.5)
            .horizonMinutes(60)
            .expectedReturn(0.02)
            .expectedVolatility(context.getAtrPercent())
            .entryPrice(context.getCurrentPrice())
            .stopLossPrice(context.getCurrentPrice() * 0.98)
            .takeProfitPrice(context.getCurrentPrice() * 1.03)
            .chanSignalType(result.chanSignalType.name())
            .pattern(result.signal != null ? result.signal.description : "")
            .strengthLevel(3)
            .timeframes("1m", "5m")
            .multiTimeframeResonance(false)
            .hasDivergence(false)
            .volumeConfirmation(false);

        recordSignal();
        return builder.build();
    }

    private com.trading.domain.trading.model.TradeDirection extractDirection(ChanSignalResult result) {
        // BUY signals → LONG, SELL signals → SHORT, RANGE_BOUND/NONE → NEUTRAL
        switch (result.chanSignalType) {
            case BUY_1: case BUY_2: case BUY_3: case RESONANCE_BUY:
                return com.trading.domain.trading.model.TradeDirection.LONG;
            case SELL_1: case SELL_2: case SELL_3: case RESONANCE_SELL:
                return com.trading.domain.trading.model.TradeDirection.SHORT;
            case RANGE_BOUND:
                return com.trading.domain.trading.model.TradeDirection.NEUTRAL;
            case NONE:
            default:
                return com.trading.domain.trading.model.TradeDirection.NEUTRAL;
        }
    }

    @Override
    public AlphaType getType() {
        return AlphaType.CHAN_TREND;
    }
}