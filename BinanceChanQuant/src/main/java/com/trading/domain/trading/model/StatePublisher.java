package com.trading.domain.trading.model;

import com.trading.domain.signal.DirectionalBelief;
import com.trading.domain.signal.CompositeAlphaSignal;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.PositionViability;
import com.trading.domain.trading.model.PositionHealth.HealthGrade;

import java.time.Instant;
import java.util.function.Consumer;

/**
 * State Publisher - Subsystems publish updates to TradingState
 *
 * <p>Key principle: "Data flows to code, not code to data"
 * Instead of subsystems calling each other:
 *
 * <pre>
 * OLD (spider web):
 *   ViabilityEngine → DriftDetector → HealthTracker → ExecutionEngine
 *
 * NEW (centralized state):
 *   ViabilityEngine publishes ViabilityAssessment
 *   DriftDetector publishes DriftState
 *   HealthTracker reads TradingState, publishes HealthState
 *   ExecutionEngine reads TradingState, publishes ExecutionState
 *
 * All engines read from ONE source, publish to ONE sink.
 * </pre>
 */
public class StatePublisher {

    private TradingState currentState = TradingState.empty();
    private final Consumer<TradingState> stateListener;

    public StatePublisher(Consumer<TradingState> stateListener) {
        this.stateListener = stateListener;
    }

    /**
     * Publish market update
     */
    public void publishMarket(
            double currentPrice,
            double atr,
            double atrPercent,
            com.trading.domain.market.model.MarketRegime regime,
            com.trading.chan.regime.MarketPosition position,
            com.trading.chan.regime.TrendDirection trend,
            com.trading.chan.regime.BreakoutState breakout) {

        TradingState.MarketState marketState = new TradingState.MarketState(
            currentPrice, atr, atrPercent, regime, position, trend, breakout,
            regime.isHighVolatility() || atrPercent > 0.03,
            regime == com.trading.domain.market.model.MarketRegime.TREND_UP
                || regime == com.trading.domain.market.model.MarketRegime.TREND_DOWN,
            regime == com.trading.domain.market.model.MarketRegime.RANGE,
            System.currentTimeMillis()
        );

        currentState = currentState.withMarket(marketState);
        notifyListener();
    }

    /**
     * Publish belief update (from Bayesian fusion)
     */
    public void publishBelief(DirectionalBelief belief, DirectionalBelief entryBelief) {
        TradingState.BeliefState beliefState = new TradingState.BeliefState(
            belief.longProb(),
            belief.shortProb(),
            belief.neutralProb(),
            belief.entropy(),
            belief.dominantDirection(),
            entryBelief,
            belief,
            System.currentTimeMillis()
        );

        currentState = currentState.withBelief(beliefState);
        notifyListener();
    }

    /**
     * Publish position update
     */
    public void publishPosition(
            double size,
            double entryPrice,
            double currentPrice,
            double unrealizedPnl,
            double realizedPnl,
            double exposureRatio,
            long holdingTimeMinutes,
            boolean hasPosition) {

        TradingState.PositionSnapshot posState = new TradingState.PositionSnapshot(
            size, entryPrice, currentPrice, unrealizedPnl, realizedPnl,
            exposureRatio, holdingTimeMinutes,
            hasPosition ? System.currentTimeMillis() - (holdingTimeMinutes * 60000) : 0,
            hasPosition
        );

        currentState = currentState.withPosition(posState);
        notifyListener();
    }

    /**
     * Publish health update
     */
    public void publishHealth(
            HealthGrade grade,
            double convictionScore,
            double driftScore,
            double recoveryScore,
            PositionViability viabilityState,
            int decayPersistenceBars,
            int weakEdgeBars,
            boolean regimeAligned,
            boolean structureValid) {

        TradingState.HealthState healthState = new TradingState.HealthState(
            grade, convictionScore, driftScore, recoveryScore,
            viabilityState, decayPersistenceBars, weakEdgeBars,
            regimeAligned, structureValid,
            System.currentTimeMillis()
        );

        currentState = currentState.withHealth(healthState);
        notifyListener();
    }

    /**
     * Publish risk update
     */
    public void publishRisk(
            double dailyPnl,
            double peakEquity,
            double currentEquity,
            double drawdown,
            int ordersThisMinute,
            boolean killSwitchTriggered,
            boolean circuitBreakerTriggered) {

        TradingState.RiskState riskState = new TradingState.RiskState(
            dailyPnl, peakEquity, currentEquity, drawdown, 0.05,
            ordersThisMinute, 60, killSwitchTriggered, circuitBreakerTriggered,
            System.currentTimeMillis()
        );

        currentState = currentState.withRisk(riskState);
        notifyListener();
    }

    /**
     * Publish execution update
     */
    public void publishExecution(
            int pendingOrders,
            int filledOrders,
            int cancelledOrders,
            double lastFillPrice,
            double lastFillSize) {

        TradingState.ExecutionSnapshot execState = new TradingState.ExecutionSnapshot(
            pendingOrders, filledOrders, cancelledOrders,
            lastFillPrice, lastFillSize,
            lastFillPrice > 0 ? System.currentTimeMillis() : 0,
            System.currentTimeMillis()
        );

        currentState = currentState.withExecution(execState);
        notifyListener();
    }

    /**
     * Get current state (read-only)
     */
    public TradingState getState() {
        return currentState;
    }

    private void notifyListener() {
        if (stateListener != null) {
            stateListener.accept(currentState);
        }
    }
}