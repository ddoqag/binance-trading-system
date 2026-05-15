package com.trading.domain.trading.model;

import com.trading.domain.signal.DirectionalBelief;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.PositionViability;
import com.trading.domain.trading.model.PositionHealth.HealthGrade;

/**
 * Canonical Trading State - Single source of truth for all trading decisions
 *
 * <p>This is the core of the "Meta-State Architecture".
 * Instead of subsystems calling each other in a spider web,
 * ALL engines read from this single TradingState.
 *
 * <p>Key principle: "Data flows to code, not code to data"
 *
 * <pre>
 * Structure:
 * TradingState
 *   ├── MarketState     - Price, volatility, regime
 *   ├── BeliefState     - Directional belief (Bayesian)
 *   ├── PositionSnapshot - Entry, size, PnL
 *   ├── HealthState     - Health grade, conviction, drift
 *   ├── RiskState       - Risk metrics, limits
 *   └── ExecutionSnapshot - Order status, fills
 * </pre>
 */
public final class TradingState {

    // ===== Sub-state classes =====

    public static final class MarketState {
        private final double currentPrice;
        private final double atr;
        private final double atrPercent;
        private final com.trading.domain.market.model.MarketRegime regime;
        private final com.trading.chan.regime.MarketPosition position;
        private final com.trading.chan.regime.TrendDirection trend;
        private final com.trading.chan.regime.BreakoutState breakout;
        private final boolean highVolatility;
        private final boolean isTrendMarket;
        private final boolean isRangeMarket;
        private final long timestamp;

        public MarketState(double currentPrice, double atr, double atrPercent,
                          com.trading.domain.market.model.MarketRegime regime,
                          com.trading.chan.regime.MarketPosition position,
                          com.trading.chan.regime.TrendDirection trend,
                          com.trading.chan.regime.BreakoutState breakout,
                          boolean highVolatility, boolean isTrendMarket, boolean isRangeMarket,
                          long timestamp) {
            this.currentPrice = currentPrice;
            this.atr = atr;
            this.atrPercent = atrPercent;
            this.regime = regime;
            this.position = position;
            this.trend = trend;
            this.breakout = breakout;
            this.highVolatility = highVolatility;
            this.isTrendMarket = isTrendMarket;
            this.isRangeMarket = isRangeMarket;
            this.timestamp = timestamp;
        }

        public double currentPrice() { return currentPrice; }
        public double atr() { return atr; }
        public double atrPercent() { return atrPercent; }
        public com.trading.domain.market.model.MarketRegime regime() { return regime; }
        public com.trading.chan.regime.MarketPosition position() { return position; }
        public com.trading.chan.regime.TrendDirection trend() { return trend; }
        public com.trading.chan.regime.BreakoutState breakout() { return breakout; }
        public boolean highVolatility() { return highVolatility; }
        public boolean isTrendMarket() { return isTrendMarket; }
        public boolean isRangeMarket() { return isRangeMarket; }
        public long timestamp() { return timestamp; }

        public static MarketState empty() {
            return new MarketState(0, 0, 0,
                com.trading.domain.market.model.MarketRegime.UNKNOWN,
                com.trading.chan.regime.MarketPosition.RANGE_MID,
                com.trading.chan.regime.TrendDirection.UNKNOWN,
                com.trading.chan.regime.BreakoutState.NONE,
                false, false, false, 0);
        }
    }

    public static final class BeliefState {
        private final double longProb;
        private final double shortProb;
        private final double neutralProb;
        private final double entropy;
        private final TradeDirection dominantDirection;
        private final DirectionalBelief entryBelief;
        private final DirectionalBelief currentBelief;
        private final long timestamp;

        public BeliefState(double longProb, double shortProb, double neutralProb,
                          double entropy, TradeDirection dominantDirection,
                          DirectionalBelief entryBelief, DirectionalBelief currentBelief,
                          long timestamp) {
            this.longProb = longProb;
            this.shortProb = shortProb;
            this.neutralProb = neutralProb;
            this.entropy = entropy;
            this.dominantDirection = dominantDirection;
            this.entryBelief = entryBelief;
            this.currentBelief = currentBelief;
            this.timestamp = timestamp;
        }

        public double longProb() { return longProb; }
        public double shortProb() { return shortProb; }
        public double neutralProb() { return neutralProb; }
        public double entropy() { return entropy; }
        public TradeDirection dominantDirection() { return dominantDirection; }
        public DirectionalBelief entryBelief() { return entryBelief; }
        public DirectionalBelief currentBelief() { return currentBelief; }
        public long timestamp() { return timestamp; }

        public static BeliefState neutral() {
            return new BeliefState(0.33, 0.33, 0.34, 1.0, TradeDirection.NEUTRAL, null, null, 0);
        }
    }

    public static final class PositionSnapshot {
        private final double size;
        private final double entryPrice;
        private final double currentPrice;
        private final double unrealizedPnl;
        private final double realizedPnl;
        private final double exposureRatio;
        private final long holdingTimeMinutes;
        private final long entryTimestamp;
        private final boolean hasPosition;

        public PositionSnapshot(double size, double entryPrice, double currentPrice,
                                double unrealizedPnl, double realizedPnl, double exposureRatio,
                                long holdingTimeMinutes, long entryTimestamp, boolean hasPosition) {
            this.size = size;
            this.entryPrice = entryPrice;
            this.currentPrice = currentPrice;
            this.unrealizedPnl = unrealizedPnl;
            this.realizedPnl = realizedPnl;
            this.exposureRatio = exposureRatio;
            this.holdingTimeMinutes = holdingTimeMinutes;
            this.entryTimestamp = entryTimestamp;
            this.hasPosition = hasPosition;
        }

        public double size() { return size; }
        public double entryPrice() { return entryPrice; }
        public double currentPrice() { return currentPrice; }
        public double unrealizedPnl() { return unrealizedPnl; }
        public double realizedPnl() { return realizedPnl; }
        public double exposureRatio() { return exposureRatio; }
        public long holdingTimeMinutes() { return holdingTimeMinutes; }
        public long entryTimestamp() { return entryTimestamp; }
        public boolean hasPosition() { return hasPosition; }

        public static PositionSnapshot flat() {
            return new PositionSnapshot(0, 0, 0, 0, 0, 0, 0, 0, false);
        }
    }

    public static final class HealthState {
        private final HealthGrade grade;
        private final double convictionScore;
        private final double driftScore;
        private final double recoveryScore;
        private final PositionViability viabilityState;
        private final int decayPersistenceBars;
        private final int weakEdgeBars;
        private final boolean regimeAligned;
        private final boolean structureValid;
        private final long timestamp;

        public HealthState(HealthGrade grade, double convictionScore, double driftScore,
                          double recoveryScore, PositionViability viabilityState,
                          int decayPersistenceBars, int weakEdgeBars,
                          boolean regimeAligned, boolean structureValid, long timestamp) {
            this.grade = grade;
            this.convictionScore = convictionScore;
            this.driftScore = driftScore;
            this.recoveryScore = recoveryScore;
            this.viabilityState = viabilityState;
            this.decayPersistenceBars = decayPersistenceBars;
            this.weakEdgeBars = weakEdgeBars;
            this.regimeAligned = regimeAligned;
            this.structureValid = structureValid;
            this.timestamp = timestamp;
        }

        public HealthGrade grade() { return grade; }
        public double convictionScore() { return convictionScore; }
        public double driftScore() { return driftScore; }
        public double recoveryScore() { return recoveryScore; }
        public PositionViability viabilityState() { return viabilityState; }
        public int decayPersistenceBars() { return decayPersistenceBars; }
        public int weakEdgeBars() { return weakEdgeBars; }
        public boolean regimeAligned() { return regimeAligned; }
        public boolean structureValid() { return structureValid; }
        public long timestamp() { return timestamp; }

        public static HealthState unknown() {
            return new HealthState(HealthGrade.UNKNOWN, 0, 0, 0,
                PositionViability.UNKNOWN, 0, 0, false, false, 0);
        }
    }

    public static final class RiskState {
        private final double dailyPnl;
        private final double peakEquity;
        private final double currentEquity;
        private final double drawdown;
        private final double maxDrawdownLimit;
        private final int ordersThisMinute;
        private final int maxOrdersPerMinute;
        private final boolean killSwitchTriggered;
        private final boolean circuitBreakerTriggered;
        private final long timestamp;

        public RiskState(double dailyPnl, double peakEquity, double currentEquity,
                         double drawdown, double maxDrawdownLimit,
                         int ordersThisMinute, int maxOrdersPerMinute,
                         boolean killSwitchTriggered, boolean circuitBreakerTriggered,
                         long timestamp) {
            this.dailyPnl = dailyPnl;
            this.peakEquity = peakEquity;
            this.currentEquity = currentEquity;
            this.drawdown = drawdown;
            this.maxDrawdownLimit = maxDrawdownLimit;
            this.ordersThisMinute = ordersThisMinute;
            this.maxOrdersPerMinute = maxOrdersPerMinute;
            this.killSwitchTriggered = killSwitchTriggered;
            this.circuitBreakerTriggered = circuitBreakerTriggered;
            this.timestamp = timestamp;
        }

        public double dailyPnl() { return dailyPnl; }
        public double peakEquity() { return peakEquity; }
        public double currentEquity() { return currentEquity; }
        public double drawdown() { return drawdown; }
        public double maxDrawdownLimit() { return maxDrawdownLimit; }
        public int ordersThisMinute() { return ordersThisMinute; }
        public int maxOrdersPerMinute() { return maxOrdersPerMinute; }
        public boolean killSwitchTriggered() { return killSwitchTriggered; }
        public boolean circuitBreakerTriggered() { return circuitBreakerTriggered; }
        public long timestamp() { return timestamp; }

        public static RiskState clean() {
            return new RiskState(0, 0, 0, 0, 0.05, 0, 60, false, false, 0);
        }
    }

    public static final class ExecutionSnapshot {
        private final int pendingOrders;
        private final int filledOrders;
        private final int cancelledOrders;
        private final double lastFillPrice;
        private final double lastFillSize;
        private final long lastFillTimestamp;
        private final long timestamp;

        public ExecutionSnapshot(int pendingOrders, int filledOrders, int cancelledOrders,
                                double lastFillPrice, double lastFillSize,
                                long lastFillTimestamp, long timestamp) {
            this.pendingOrders = pendingOrders;
            this.filledOrders = filledOrders;
            this.cancelledOrders = cancelledOrders;
            this.lastFillPrice = lastFillPrice;
            this.lastFillSize = lastFillSize;
            this.lastFillTimestamp = lastFillTimestamp;
            this.timestamp = timestamp;
        }

        public int pendingOrders() { return pendingOrders; }
        public int filledOrders() { return filledOrders; }
        public int cancelledOrders() { return cancelledOrders; }
        public double lastFillPrice() { return lastFillPrice; }
        public double lastFillSize() { return lastFillSize; }
        public long lastFillTimestamp() { return lastFillTimestamp; }
        public long timestamp() { return timestamp; }

        public static ExecutionSnapshot idle() {
            return new ExecutionSnapshot(0, 0, 0, 0, 0, 0, 0);
        }
    }

    // ===== Main TradingState =====

    private final MarketState market;
    private final BeliefState belief;
    private final PositionSnapshot position;
    private final HealthState health;
    private final RiskState risk;
    private final ExecutionSnapshot execution;
    private final long version;
    private final long timestamp;

    public TradingState(MarketState market, BeliefState belief, PositionSnapshot position,
                       HealthState health, RiskState risk, ExecutionSnapshot execution) {
        this.market = market != null ? market : MarketState.empty();
        this.belief = belief != null ? belief : BeliefState.neutral();
        this.position = position != null ? position : PositionSnapshot.flat();
        this.health = health != null ? health : HealthState.unknown();
        this.risk = risk != null ? risk : RiskState.clean();
        this.execution = execution != null ? execution : ExecutionSnapshot.idle();
        this.version = System.nanoTime();
        this.timestamp = System.currentTimeMillis();
    }

    // ===== Factory methods =====

    public static TradingState empty() {
        return new TradingState(null, null, null, null, null, null);
    }

    public static TradingState initial(double price) {
        return new TradingState(
            new MarketState(price, price * 0.02, 0.02,
                com.trading.domain.market.model.MarketRegime.UNKNOWN,
                com.trading.chan.regime.MarketPosition.RANGE_MID,
                com.trading.chan.regime.TrendDirection.UNKNOWN,
                com.trading.chan.regime.BreakoutState.NONE,
                false, false, false, System.currentTimeMillis()),
            BeliefState.neutral(),
            PositionSnapshot.flat(),
            HealthState.unknown(),
            RiskState.clean(),
            ExecutionSnapshot.idle()
        );
    }

    // ===== With methods (immutable updates) =====

    public TradingState withMarket(MarketState newMarket) {
        return new TradingState(newMarket, belief, position, health, risk, execution);
    }

    public TradingState withBelief(BeliefState newBelief) {
        return new TradingState(market, newBelief, position, health, risk, execution);
    }

    public TradingState withPosition(PositionSnapshot newPosition) {
        return new TradingState(market, belief, newPosition, health, risk, execution);
    }

    public TradingState withHealth(HealthState newHealth) {
        return new TradingState(market, belief, position, newHealth, risk, execution);
    }

    public TradingState withRisk(RiskState newRisk) {
        return new TradingState(market, belief, position, health, newRisk, execution);
    }

    public TradingState withExecution(ExecutionSnapshot newExecution) {
        return new TradingState(market, belief, position, health, risk, newExecution);
    }

    // ===== Getters =====

    public MarketState market() { return market; }
    public BeliefState belief() { return belief; }
    public PositionSnapshot position() { return position; }
    public HealthState health() { return health; }
    public RiskState risk() { return risk; }
    public ExecutionSnapshot execution() { return execution; }
    public long version() { return version; }
    public long timestamp() { return timestamp; }

    // ===== Convenience queries =====

    public boolean isPositionHealthy() {
        return health.grade() == HealthGrade.HEALTHY || health.grade() == HealthGrade.WATCH;
    }

    public boolean shouldExit() {
        return health.grade() == HealthGrade.CRITICAL
            || health.driftScore() > 0.6
            || !health.structureValid();
    }

    public boolean canTrade() {
        return !risk.killSwitchTriggered()
            && !risk.circuitBreakerTriggered()
            && health.grade() != HealthGrade.UNKNOWN;
    }

    public TradeDirection dominantDirection() {
        return belief.dominantDirection();
    }

    @Override
    public String toString() {
        return String.format(
            "TradingState{v=%d, market=%.0f, belief=%s/%.2f, pos=%s/%.4f, health=%s, risk=drawdown=%.2f}",
            version,
            market.currentPrice(),
            belief.dominantDirection(),
            belief.longProb(),
            position.hasPosition() ? "OPEN" : "FLAT",
            position.size(),
            health.grade(),
            risk.drawdown()
        );
    }
}