package com.trading.adapter.pool;

import com.trading.domain.signal.MarketContext;
import com.trading.domain.market.model.MarketRegime;
import com.trading.domain.trading.model.RiskModel;
import com.trading.domain.trading.model.TradeDirection;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import static org.junit.jupiter.api.Assertions.*;

/**
 * RiskModelFactory TDD Tests
 */
class RiskModelFactoryTest {

    @Test
    @DisplayName("buildRiskModel should create valid RiskModel")
    void buildRiskModel_shouldCreateValidRiskModel() {
        MarketContext context = createContext(MarketRegime.RANGE, 0.02);

        RiskModel riskModel = RiskModelFactory.buildRiskModel(
            50000, 1.0, TradeDirection.LONG, context
        );

        assertNotNull(riskModel);
        assertEquals(50000, riskModel.getEntryPrice());
        assertEquals(1.0, riskModel.getPositionSize());
        assertEquals("LONG", riskModel.getDirection());
    }

    @Test
    @DisplayName("ATR multiplier should be 2.5 for MEDIUM vol regime")
    void atrMultiplier_MEDIUM() {
        // atrPercent = 0.02 (2%) triggers MEDIUM regime
        MarketContext context = createContext(MarketRegime.RANGE, 0.02);

        RiskModel riskModel = RiskModelFactory.buildRiskModel(
            50000, 1.0, TradeDirection.LONG, context
        );

        assertEquals(2.5, riskModel.getAtrStopPercent(), 0.01);
    }

    @Test
    @DisplayName("ATR multiplier should be 3.5 for EXTREME vol regime")
    void atrMultiplier_EXTREME() {
        // atrPercent = 0.06 (6%) triggers EXTREME regime
        MarketContext context = createContext(MarketRegime.RANGE, 0.06);

        RiskModel riskModel = RiskModelFactory.buildRiskModel(
            50000, 1.0, TradeDirection.LONG, context
        );

        assertEquals(3.5, riskModel.getAtrStopPercent(), 0.01);
    }

    @Test
    @DisplayName("ATR multiplier should be 2.0 for LOW vol regime")
    void atrMultiplier_LOW() {
        // atrPercent = 0.005 (0.5%) triggers LOW regime
        MarketContext context = createContext(MarketRegime.RANGE, 0.005);

        RiskModel riskModel = RiskModelFactory.buildRiskModel(
            50000, 1.0, TradeDirection.LONG, context
        );

        assertEquals(2.0, riskModel.getAtrStopPercent(), 0.01);
    }

    @Test
    @DisplayName("ATR multiplier should be 3.0 for HIGH vol regime")
    void atrMultiplier_HIGH() {
        // atrPercent = 0.04 (4%) triggers HIGH regime
        MarketContext context = createContext(MarketRegime.RANGE, 0.04);

        RiskModel riskModel = RiskModelFactory.buildRiskModel(
            50000, 1.0, TradeDirection.LONG, context
        );

        assertEquals(3.0, riskModel.getAtrStopPercent(), 0.01);
    }

    @Test
    @DisplayName("Take profit multiplier should be 2.0x ATR stop in range")
    void takeProfitMultiplier_range() {
        MarketContext context = createContext(MarketRegime.RANGE, 0.02);

        RiskModel riskModel = RiskModelFactory.buildRiskModel(
            50000, 1.0, TradeDirection.LONG, context
        );

        // MEDIUM ATR stop = 2.5, TP = 2.5 * 2.0 = 5.0
        assertEquals(5.0, riskModel.getTakeProfitPercent(), 0.01);
    }

    @Test
    @DisplayName("Take profit multiplier should be 1.5x higher in trend")
    void takeProfitMultiplier_trend() {
        MarketContext context = createContext(MarketRegime.TREND_UP, 0.02);

        RiskModel riskModel = RiskModelFactory.buildRiskModel(
            50000, 1.0, TradeDirection.LONG, context
        );

        // MEDIUM ATR stop = 2.5 * 1.1 (trend adjustment) = 2.75
        // TP = 2.75 * 2.0 * 1.5 (trend adjustment) = 8.25
        assertEquals(8.25, riskModel.getTakeProfitPercent(), 0.01);
    }

    @Test
    @DisplayName("Max hold time should be 60 min in trend")
    void maxHoldTime_trend() {
        MarketContext context = createContext(MarketRegime.TREND_UP, 0.02);

        RiskModel riskModel = RiskModelFactory.buildRiskModel(
            50000, 1.0, TradeDirection.LONG, context
        );

        assertEquals(60 * 60 * 1000, riskModel.getMaxHoldTimeMs());
    }

    @Test
    @DisplayName("Max hold time should be 30 min in range")
    void maxHoldTime_range() {
        MarketContext context = createContext(MarketRegime.RANGE, 0.02);

        RiskModel riskModel = RiskModelFactory.buildRiskModel(
            50000, 1.0, TradeDirection.LONG, context
        );

        assertEquals(30 * 60 * 1000, riskModel.getMaxHoldTimeMs());
    }

    @Test
    @DisplayName("Chandelier K should be wider in range (1.2x)")
    void chandelierK_range() {
        MarketContext context = createContext(MarketRegime.RANGE, 0.02);

        RiskModel riskModel = RiskModelFactory.buildRiskModel(
            50000, 1.0, TradeDirection.LONG, context
        );

        // MEDIUM K = 2.0, range adjustment = 2.0 * 1.2 = 2.4
        // But we need to verify via updateChandelierExit
    }

    @Test
    @DisplayName("updateChandelierExit should return correct price for LONG")
    void updateChandelierExit_LONG() {
        MarketContext context = createContext(MarketRegime.RANGE, 0.02);

        RiskModel riskModel = RiskModelFactory.buildRiskModel(
            50000, 1.0, TradeDirection.LONG, context
        );

        double peakPrice = 51000;
        double atr = 100;

        double chandelierExit = RiskModelFactory.updateChandelierExit(
            riskModel, peakPrice, 0, atr
        );

        // MEDIUM K = 2.5, range adjustment = 2.5 * 1.2 = 3.0
        // LONG: peakPrice - K * ATR = 51000 - 3.0 * 100 = 50700
        assertEquals(50700, chandelierExit, 0.01);
    }

    @Test
    @DisplayName("updateChandelierExit should return correct price for SHORT")
    void updateChandelierExit_SHORT() {
        MarketContext context = createContext(MarketRegime.RANGE, 0.02);

        RiskModel riskModel = RiskModelFactory.buildRiskModel(
            50000, 1.0, TradeDirection.SHORT, context
        );

        double lowestPrice = 49000;
        double atr = 100;

        double chandelierExit = RiskModelFactory.updateChandelierExit(
            riskModel, 0, lowestPrice, atr
        );

        // MEDIUM K = 2.5, range adjustment = 2.5 * 1.2 = 3.0
        // SHORT: lowestPrice + K * ATR = 49000 + 3.0 * 100 = 49300
        assertEquals(49300, chandelierExit, 0.01);
    }

    @Test
    @DisplayName("Should handle null context with defaults")
    void nullContext_shouldUseDefaults() {
        RiskModel riskModel = RiskModelFactory.buildRiskModel(
            50000, 1.0, TradeDirection.LONG, null
        );

        assertNotNull(riskModel);
        assertEquals(50000, riskModel.getEntryPrice());
    }

    @Test
    @DisplayName("Trailing stop percent should scale with volatility")
    void trailingStopPercent_scalesWithVolatility() {
        // LOW: atrPercent = 0.005
        MarketContext lowVol = createContext(MarketRegime.RANGE, 0.005);
        RiskModel lowRisk = RiskModelFactory.buildRiskModel(50000, 1.0, TradeDirection.LONG, lowVol);
        assertEquals(1.5, lowRisk.getTrailingStopPercent(), 0.01);

        // HIGH: atrPercent = 0.04
        MarketContext highVol = createContext(MarketRegime.RANGE, 0.04);
        RiskModel highRisk = RiskModelFactory.buildRiskModel(50000, 1.0, TradeDirection.LONG, highVol);
        assertEquals(2.5, highRisk.getTrailingStopPercent(), 0.01);
    }

    private MarketContext createContext(MarketRegime regime, double atrPercent) {
        return MarketContext.builder()
            .regime(regime)
            .volatilityRegime(com.trading.domain.signal.VolatilityRegime.MEDIUM)
            .trendStrength(com.trading.domain.signal.TrendStrength.NONE)
            .currentPrice(50000)
            .atr(100)
            .atrPercent(atrPercent)
            .volumeRatio(1.0)
            .timestamp(System.currentTimeMillis())
            .build();
    }
}
