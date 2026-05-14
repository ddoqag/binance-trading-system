package com.trading.domain.trading.risk;

import com.trading.domain.trading.projection.PositionProjection;

/**
 * Risk Evaluator - derived, not persisted.
 *
 * Computed on-demand from:
 * - PositionProjection (current position state)
 * - MarketSnapshot (current market conditions)
 *
 * NOT stored - avoids stale cache issues.
 * Replay/Reconciliation complexity stays bounded.
 *
 * Java 11 compatible class.
 */
public class RiskEvaluator {

    // Circuit breaker thresholds
    private final double maxDrawdownPercent;
    private final double maxPositionRatio;
    private final long atrStaleThresholdMs;
    private final double wsLagThresholdMs;
    private final double volatilitySpikeThreshold;

    public RiskEvaluator() {
        this.maxDrawdownPercent = 0.05;  // 5%
        this.maxPositionRatio = 0.3;     // 30% of equity
        this.atrStaleThresholdMs = 60_000; // 60 seconds
        this.wsLagThresholdMs = 500;      // 500ms
        this.volatilitySpikeThreshold = 3.0; // 3x normal volatility
    }

    /**
     * Market data snapshot for risk evaluation.
     */
    public static final class MarketSnapshot {
        private final String symbol;
        private final double lastPrice;
        private final double atr;
        private final long atrTimestamp;
        private final double normalVolatility;
        private final double currentVolatility;
        private final double adverseSelectionProb;
        private final double wsLagMs;
        private final int missingCandleCount;

        public MarketSnapshot(
            String symbol,
            double lastPrice,
            double atr,
            long atrTimestamp,
            double normalVolatility,
            double currentVolatility,
            double adverseSelectionProb,
            double wsLagMs,
            int missingCandleCount
        ) {
            this.symbol = symbol;
            this.lastPrice = lastPrice;
            this.atr = atr;
            this.atrTimestamp = atrTimestamp;
            this.normalVolatility = normalVolatility;
            this.currentVolatility = currentVolatility;
            this.adverseSelectionProb = adverseSelectionProb;
            this.wsLagMs = wsLagMs;
            this.missingCandleCount = missingCandleCount;
        }

        public double atrAgeSeconds() {
            return (System.currentTimeMillis() - atrTimestamp) / 1000.0;
        }

        public boolean isAtrStale() {
            return atrAgeSeconds() > 60;
        }

        public boolean isWsLagging() {
            return wsLagMs > 500; // 500ms threshold
        }

        public double volatilityRatio() {
            return normalVolatility > 0 ? currentVolatility / normalVolatility : 1.0;
        }

        public String symbol() { return symbol; }
        public double lastPrice() { return lastPrice; }
        public double atr() { return atr; }
        public long atrTimestamp() { return atrTimestamp; }
        public double normalVolatility() { return normalVolatility; }
        public double currentVolatility() { return currentVolatility; }
        public double adverseSelectionProb() { return adverseSelectionProb; }
        public double wsLagMs() { return wsLagMs; }
        public int missingCandleCount() { return missingCandleCount; }
    }

    /**
     * Evaluate risk and return validation result with confidence.
     *
     * Correct链路: market confidence → signal confidence → risk confidence → execution confidence
     */
    public RiskValidationResult evaluate(
        double requestedSize,
        PositionProjection.PositionSnapshot position,
        MarketSnapshot market
    ) {
        // === HARD REJECTIONS ===

        // Circuit breaker
        if (isCircuitBreakerTriggered(position)) {
            return RiskValidationResult.Invalid.circuitBreakerTriggered();
        }

        // Max drawdown exceeded
        double drawdown = calculateDrawdown(position);
        if (drawdown < -maxDrawdownPercent) {
            return RiskValidationResult.Invalid.maxDrawdownExceeded(
                drawdown, maxDrawdownPercent);
        }

        // Missing critical data
        if (market.missingCandleCount() > 3) {
            return RiskValidationResult.Invalid.missingCandles(
                market.symbol(), market.missingCandleCount());
        }

        // === DEGRADATION FACTORS ===

        double baseConfidence = 1.0;
        java.util.List<String> degradedFactors = new java.util.ArrayList<>();

        // ATR staleness
        if (market.isAtrStale()) {
            baseConfidence *= 0.7;
            degradedFactors.add("ATR_STALE");
        }

        // WebSocket lag
        if (market.isWsLagging()) {
            baseConfidence *= 0.8;
            degradedFactors.add("WS_LAGGING");
        }

        // Volatility spike
        if (market.volatilityRatio() > volatilitySpikeThreshold) {
            baseConfidence *= 0.5;
            degradedFactors.add("VOLATILITY_EXPLOSION");
        }

        // Adverse selection
        if (market.adverseSelectionProb() > 0.3) {
            baseConfidence *= 0.7;
            degradedFactors.add("ADVERSE_SELECTION");
        }

        // Calculate max position size
        double maxByRisk = calculateMaxPositionSize(position, market);

        // === DETERMINE STATE ===

        if (baseConfidence >= 0.8) {
            // Valid state
            return new RiskValidationResult.Valid(maxByRisk, baseConfidence);
        } else if (baseConfidence >= 0.3) {
            // Degraded state - reduce size
            String reason = degradedFactors.isEmpty()
                ? "Reduced confidence"
                : "Data quality degraded: " + String.join(", ", degradedFactors);
            return new RiskValidationResult.Degraded(
                baseConfidence, // Use confidence as size multiplier
                baseConfidence,
                reason,
                degradedFactors
            );
        } else {
            // Invalid state - block
            String reason = degradedFactors.isEmpty()
                ? "Very low confidence"
                : "Critical data issues: " + String.join(", ", degradedFactors);
            return new RiskValidationResult.Invalid(reason, baseConfidence);
        }
    }

    /**
     * Calculate max position size based on risk parameters.
     */
    private double calculateMaxPositionSize(PositionProjection.PositionSnapshot position, MarketSnapshot market) {
        double peakEquity = position.peakEquity() > 0 ? position.peakEquity() : 10000.0;
        double maxExposure = peakEquity * maxPositionRatio;
        return maxExposure / market.lastPrice();
    }

    /**
     * Calculate current drawdown.
     */
    private double calculateDrawdown(PositionProjection.PositionSnapshot position) {
        if (position.peakEquity() <= 0) {
            return 0.0;
        }
        return position.unrealizedPnl() / position.peakEquity();
    }

    /**
     * Check if circuit breaker is triggered.
     */
    private boolean isCircuitBreakerTriggered(PositionProjection.PositionSnapshot position) {
        return calculateDrawdown(position) < -0.10; // 10% drawdown triggers circuit breaker
    }
}