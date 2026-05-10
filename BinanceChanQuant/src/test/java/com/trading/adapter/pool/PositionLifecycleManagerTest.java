package com.trading.adapter.pool;

import com.trading.domain.signal.MarketContext;
import com.trading.domain.signal.TrendStrength;
import com.trading.domain.market.model.MarketRegime;
import com.trading.domain.trading.model.PositionState;
import com.trading.domain.trading.model.RiskModel;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.TradeIntent;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import static org.junit.jupiter.api.Assertions.*;

/**
 * PositionLifecycleManager TDD Tests
 */
class PositionLifecycleManagerTest {

    private PositionLifecycleManager lifecycleManager;
    private MarketContext marketContext;

    @BeforeEach
    void setUp() {
        lifecycleManager = PositionLifecycleManager.defaults();
        marketContext = createContext(MarketRegime.RANGE, 50000, 1000);
    }

    @Test
    @DisplayName("HOLD when no position")
    void holdWhenNoPosition() {
        PositionState position = PositionState.empty();
        TradeIntent intent = lifecycleManager.determineIntent(
            position, 0.7, marketContext, TradeDirection.LONG
        );
        assertEquals(TradeIntent.HOLD, intent);
    }

    @Test
    @DisplayName("EXIT_LONG when ATR stop hit")
    void exitLongWhenAtrStopHit() {
        RiskModel riskModel = RiskModel.builder()
            .atr(1000)
            .atrPercent(0.02)
            .entryPrice(50000)
            .positionSize(1.0)
            .direction("LONG")
            .atrStopPercent(2.0)
            .build();

        PositionState position = new PositionState(
            1.0, 50000, 0, 0,
            System.currentTimeMillis() - 10 * 60 * 1000,
            50000, 50000, "order1", riskModel,
            51000, 50000
        );

        MarketContext ctx = createContext(MarketRegime.RANGE, 47900, 1000);
        TradeIntent intent = lifecycleManager.determineIntent(position, 0.7, ctx, null);
        assertEquals(TradeIntent.EXIT_LONG, intent);
    }

    @Test
    @DisplayName("EXIT_SHORT when ATR stop hit")
    void exitShortWhenAtrStopHit() {
        RiskModel riskModel = RiskModel.builder()
            .atr(1000)
            .atrPercent(0.02)
            .entryPrice(50000)
            .positionSize(1.0)
            .direction("SHORT")
            .atrStopPercent(2.0)
            .build();

        PositionState position = new PositionState(
            -1.0, 50000, 0, 0,
            System.currentTimeMillis() - 10 * 60 * 1000,
            50000, 50000, "order1", riskModel,
            50000, 49000
        );

        MarketContext ctx = createContext(MarketRegime.RANGE, 52100, 1000);
        TradeIntent intent = lifecycleManager.determineIntent(position, 0.7, ctx, null);
        assertEquals(TradeIntent.EXIT_SHORT, intent);
    }

    @Test
    @DisplayName("HOLD when price above stops")
    void holdWhenPriceAboveStops() {
        RiskModel riskModel = RiskModel.builder()
            .atr(1000)
            .atrPercent(0.02)
            .entryPrice(50000)
            .positionSize(1.0)
            .direction("LONG")
            .atrStopPercent(2.0)
            .build();

        PositionState position = new PositionState(
            1.0, 50000, 0, 0,
            System.currentTimeMillis() - 10 * 60 * 1000,
            50000, 50000, "order1", riskModel,
            50500, 50000
        );

        MarketContext ctx = createContext(MarketRegime.RANGE, 49000, 1000);
        TradeIntent intent = lifecycleManager.determineIntent(position, 0.6, ctx, TradeDirection.LONG);
        assertEquals(TradeIntent.HOLD, intent);
    }

    @Test
    @DisplayName("EXIT via Alpha Decay when confidence low")
    void exitViaAlphaDecay() {
        RiskModel riskModel = RiskModel.builder()
            .atr(1000)
            .atrPercent(0.02)
            .entryPrice(50000)
            .positionSize(1.0)
            .direction("LONG")
            .atrStopPercent(2.0)
            .build();

        PositionState position = new PositionState(
            1.0, 50000, 0, 0,
            System.currentTimeMillis() - 10 * 60 * 1000,
            50000, 50000, "order1", riskModel,
            50500, 50000
        );

        // confidence 0.35 is below 0.40 threshold and above 0.30 min
        MarketContext ctx = createContext(MarketRegime.RANGE, 49000, 1000);
        TradeIntent intent = lifecycleManager.determineIntent(position, 0.35, ctx, null);
        assertEquals(TradeIntent.EXIT_LONG, intent);
    }

    @Test
    @DisplayName("EXIT via Reverse Signal")
    void exitViaReverseSignal() {
        RiskModel riskModel = RiskModel.builder()
            .atr(1000)
            .atrPercent(0.02)
            .entryPrice(50000)
            .positionSize(1.0)
            .direction("LONG")
            .atrStopPercent(2.0)
            .build();

        PositionState position = new PositionState(
            1.0, 50000, 0, 0,
            System.currentTimeMillis() - 10 * 60 * 1000,
            50000, 50000, "order1", riskModel,
            50500, 50000
        );

        MarketContext ctx = createContext(MarketRegime.TREND_DOWN, 49000, 1000);
        TradeIntent intent = lifecycleManager.determineIntent(position, 0.7, ctx, TradeDirection.SHORT);
        assertEquals(TradeIntent.EXIT_LONG, intent);
    }

    @Test
    @DisplayName("EXIT via Time Stop")
    void exitViaTimeStop() {
        RiskModel riskModel = RiskModel.builder()
            .atr(1000)
            .atrPercent(0.02)
            .entryPrice(50000)
            .positionSize(1.0)
            .direction("LONG")
            .atrStopPercent(2.0)
            .build();

        PositionState position = new PositionState(
            1.0, 50000, 0, 0,
            System.currentTimeMillis() - 46 * 60 * 1000,  // 46 min > maxHoldMinutes=45
            50000, 50000, "order1", riskModel,
            50500, 50000
        );

        MarketContext ctx = createContext(MarketRegime.RANGE, 49000, 1000);
        TradeIntent intent = lifecycleManager.determineIntent(position, 0.7, ctx, null);
        assertEquals(TradeIntent.EXIT_LONG, intent);
    }

    @Test
    @DisplayName("EXIT via Take Profit")
    void exitViaTakeProfit() {
        RiskModel riskModel = RiskModel.builder()
            .atr(1000)
            .atrPercent(0.02)
            .entryPrice(50000)
            .positionSize(1.0)
            .direction("LONG")
            .atrStopPercent(2.0)
            .takeProfitPercent(2.0)
            .build();

        PositionState position = new PositionState(
            1.0, 50000, 0, 0,
            System.currentTimeMillis() - 10 * 60 * 1000,
            50000, 50000, "order1", riskModel,
            50000, 50000
        );

        // TP = 50000 + 2.0*1000 = 52000, current price 52500 > TP
        MarketContext ctx = createContext(MarketRegime.RANGE, 52500, 1000);
        TradeIntent intent = lifecycleManager.determineIntent(position, 0.7, ctx, null);
        assertEquals(TradeIntent.EXIT_LONG, intent);
    }

    @Test
    @DisplayName("Defaults creates valid manager")
    void defaultsCreatesValidManager() {
        PositionLifecycleManager manager = PositionLifecycleManager.defaults();
        assertNotNull(manager);
        PositionState flat = PositionState.empty();
        TradeIntent intent = manager.determineIntent(flat, 0.5, null, null);
        assertEquals(TradeIntent.HOLD, intent);
    }

    private MarketContext createContext(MarketRegime regime, double price, double atr) {
        double atrPercent = atr / price;
        return MarketContext.builder()
            .regime(regime)
            .volatilityRegime(com.trading.domain.signal.VolatilityRegime.MEDIUM)
            .trendStrength(TrendStrength.NONE)
            .currentPrice(price)
            .atr(atr)
            .atrPercent(atrPercent)
            .volumeRatio(1.0)
            .timestamp(System.currentTimeMillis())
            .build();
    }
}
