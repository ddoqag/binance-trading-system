package com.trading.adapter.pool;

import com.trading.adapter.chan.analyzer.ChanKLineProcessor;
import com.trading.adapter.chan.analyzer.ChanKLineProcessor.KlineContext;
import com.trading.adapter.chan.config.ChanFeatureToggle;
import com.trading.adapter.chan.detector.ChanPatternDetector.SignalType;
import com.trading.adapter.chan.integration.ChanMetaLearnerBridge;
import com.trading.adapter.chan.integration.ChanMetaLearnerBridge.ChanSignalResult;
import com.trading.adapter.chan.validation.ChanSignalValidator;
import com.trading.adapter.chan.validation.ChanSignalValidator.ValidationResult;
import com.trading.domain.market.model.MarketData;
import com.trading.domain.market.model.MarketRegime;
import com.trading.domain.signal.AlphaSignal;
import com.trading.domain.signal.AlphaType;
import com.trading.domain.signal.MarketContext;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * ChanExpert TDD Tests
 */
class ChanExpertTest {

    private ChanExpert chanExpert;
    private ChanMetaLearnerBridge bridge;
    private ChanSignalValidator validator;
    private ChanKLineProcessor processor;
    private ChanFeatureToggle toggle;
    private MarketContext marketContext;
    private MarketData marketData;

    @BeforeEach
    void setUp() {
        bridge = mock(ChanMetaLearnerBridge.class);
        validator = mock(ChanSignalValidator.class);
        processor = mock(ChanKLineProcessor.class);
        toggle = mock(ChanFeatureToggle.class);

        chanExpert = new ChanExpert(bridge, validator, processor, toggle);

        marketData = new MarketData();
        marketData.setSymbol("BTCUSDT");
        marketData.setLastPrice(50000);
        marketData.setBidPrice(49990);
        marketData.setAskPrice(50010);
        marketData.setVolume(1.0);
        marketContext = MarketContext.builder()
            .regime(MarketRegime.TREND_UP)
            .currentPrice(50000)
            .atr(1000)
            .atrPercent(0.02)
            .volumeRatio(1.0)
            .timestamp(System.currentTimeMillis())
            .build();
        marketContext.setMarketData(marketData);
    }

    @Test
    @DisplayName("Should return correct type CHAN_TREND")
    void shouldReturnCorrectType() {
        assertEquals(AlphaType.CHAN_TREND, chanExpert.getType());
    }

    @Test
    @DisplayName("Should return correct id and name")
    void shouldReturnCorrectIdAndName() {
        assertEquals("chan", chanExpert.getId());
        assertEquals("Chan Theory Expert", chanExpert.getName());
    }

    @Test
    @DisplayName("Should be active by default")
    void shouldBeActiveByDefault() {
        assertTrue(chanExpert.isActive());
    }

    @Test
    @DisplayName("Should return null when context is null")
    void shouldReturnNullWhenContextIsNull() {
        AlphaSignal signal = chanExpert.generate(null);
        assertNull(signal);
    }

    @Test
    @DisplayName("Should return null when market data is null")
    void shouldReturnNullWhenMarketDataIsNull() {
        when(bridge.generateSignal(any(), any())).thenReturn(Optional.empty());

        AlphaSignal signal = chanExpert.generate(marketContext);
        assertNull(signal);
    }

    @Test
    @DisplayName("Should return null when bridge returns empty")
    void shouldReturnNullWhenBridgeReturnsEmpty() {
        when(bridge.generateSignal(any(), any())).thenReturn(Optional.empty());

        AlphaSignal signal = chanExpert.generate(marketContext);
        assertNull(signal);
    }

    @Test
    @DisplayName("Should return null when validation fails")
    void shouldReturnNullWhenValidationFails() {
        ChanSignalResult mockResult = new ChanSignalResult(
            null, SignalType.BUY_1, 0.7, "test"
        );
        when(bridge.generateSignal(any(), any())).thenReturn(Optional.of(mockResult));

        ValidationResult failedValidation = new ValidationResult(false, "LOW_CONFIDENCE", "Confidence too low", 0.3);
        when(validator.validate(any(), any(), anyDouble())).thenReturn(failedValidation);

        AlphaSignal signal = chanExpert.generate(marketContext);
        assertNull(signal);
    }

    @Test
    @DisplayName("Should generate signal when all checks pass")
    void shouldGenerateSignalWhenAllChecksPass() {
        ChanSignalResult mockResult = new ChanSignalResult(
            null, SignalType.BUY_1, 0.7, "test"
        );
        when(bridge.generateSignal(any(), any())).thenReturn(Optional.of(mockResult));

        ValidationResult passValidation = new ValidationResult(true, "OK", "Valid", 0.7);
        when(validator.validate(any(), any(), anyDouble())).thenReturn(passValidation);

        KlineContext mockCtx = mock(KlineContext.class);
        when(processor.getCurrentContext()).thenReturn(mockCtx);

        AlphaSignal signal = chanExpert.generate(marketContext);
        assertNotNull(signal);
        assertEquals(com.trading.domain.trading.model.TradeDirection.LONG, signal.getDirection());
    }

    @Test
    @DisplayName("Should generate SELL signal for SELL signal types")
    void shouldGenerateSellSignalForSellTypes() {
        ChanSignalResult mockResult = new ChanSignalResult(
            null, SignalType.SELL_1, 0.7, "test"
        );
        when(bridge.generateSignal(any(), any())).thenReturn(Optional.of(mockResult));

        ValidationResult passValidation = new ValidationResult(true, "OK", "Valid", 0.7);
        when(validator.validate(any(), any(), anyDouble())).thenReturn(passValidation);

        KlineContext mockCtx = mock(KlineContext.class);
        when(processor.getCurrentContext()).thenReturn(mockCtx);

        AlphaSignal signal = chanExpert.generate(marketContext);
        assertNotNull(signal);
        assertEquals(com.trading.domain.trading.model.TradeDirection.SHORT, signal.getDirection());
    }

    @Test
    @DisplayName("Should generate NEUTRAL signal for RANGE_BOUND")
    void shouldGenerateNeutralSignalForRangeBound() {
        ChanSignalResult mockResult = new ChanSignalResult(
            null, SignalType.RANGE_BOUND, 0.6, "test"
        );
        when(bridge.generateSignal(any(), any())).thenReturn(Optional.of(mockResult));

        ValidationResult passValidation = new ValidationResult(true, "OK", "Valid", 0.6);
        when(validator.validate(any(), any(), anyDouble())).thenReturn(passValidation);

        KlineContext mockCtx = mock(KlineContext.class);
        when(processor.getCurrentContext()).thenReturn(mockCtx);

        AlphaSignal signal = chanExpert.generate(marketContext);
        assertNotNull(signal);
        assertEquals(com.trading.domain.trading.model.TradeDirection.NEUTRAL, signal.getDirection());
    }

    @Test
    @DisplayName("Should update and retrieve weight")
    void shouldUpdateAndRetrieveWeight() {
        chanExpert.updateWeight(0.8);
        assertEquals(0.8, chanExpert.getWeight(), 0.001);
    }

    @Test
    @DisplayName("Should clamp weight between 0 and 1")
    void shouldClampWeightBetweenZeroAndOne() {
        chanExpert.updateWeight(1.5);
        assertEquals(1.0, chanExpert.getWeight(), 0.001);

        chanExpert.updateWeight(-0.5);
        assertEquals(0.0, chanExpert.getWeight(), 0.001);
    }

    @Test
    @DisplayName("Should record execution outcome")
    void shouldRecordExecutionOutcome() {
        com.trading.domain.signal.AlphaExpert.ExecutionResult result =
            new com.trading.domain.signal.AlphaExpert.ExecutionResult("chan_123", 100.0, true);
        chanExpert.recordOutcome(result);

        var stats = chanExpert.getStatistics();
        assertNotNull(stats);
        assertEquals(1, stats.getTotalSignals());
        assertEquals(1, stats.getProfitableSignals());
    }

    @Test
    @DisplayName("Should get expert statistics")
    void shouldGetExpertStatistics() {
        var stats = chanExpert.getStatistics();

        assertNotNull(stats);
        assertEquals("chan", stats.getExpertId());
        assertEquals(AlphaType.CHAN_TREND, stats.getType());
        assertEquals(0.0, stats.getTotalProfit(), 0.001);
    }

    @Test
    @DisplayName("Should return null signal when expert is inactive")
    void shouldReturnNullWhenExpertIsInactive() {
        chanExpert.updateWeight(0); // effectively inactive

        AlphaSignal signal = chanExpert.generate(marketContext);
        assertNull(signal);
    }
}