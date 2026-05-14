package com.trading.domain.trading.risk;

import java.util.List;

/**
 * Risk Validation Result - three states with confidence score (0.0 - 1.0).
 *
 * NOT binary valid/invalid - supports degraded state for observation phase.
 * Confidence score preserves information for future attribution and analysis.
 *
 * Correct链路:
 * market confidence → signal confidence → risk confidence → execution confidence
 * finally combined into effective size
 *
 * Java 11 compatible - uses abstract class instead of sealed interface.
 */
public abstract class RiskValidationResult {

    /**
     * Get confidence score (0.0 - 1.0).
     */
    public abstract double confidence();

    /**
     * Is this a terminal rejection?
     */
    public boolean isRejected() {
        return this instanceof Invalid;
    }

    /**
     * Is this a degraded (reduced but allowed) state?
     */
    public boolean isDegraded() {
        return this instanceof Degraded;
    }

    /**
     * Is this a fully valid state?
     */
    public boolean isValid() {
        return this instanceof Valid;
    }

    /**
     * Calculate effective size given requested size.
     */
    public double effectiveSize(double requestedSize) {
        if (this instanceof Valid) {
            Valid v = (Valid) this;
            return Math.min(requestedSize * v.confidence(), v.maxSize());
        } else if (this instanceof Degraded) {
            Degraded d = (Degraded) this;
            return requestedSize * d.sizeMultiplier() * d.confidence();
        } else {
            return 0.0; // Block all sizing
        }
    }

    /**
     * Valid state - full sizing allowed.
     */
    public static final class Valid extends RiskValidationResult {
        private final double maxSize;
        private final double confidence;

        public Valid(double maxSize, double confidence) {
            this.maxSize = maxSize;
            this.confidence = Math.max(0.0, Math.min(1.0, confidence));
        }

        public static Valid of(double maxSize) {
            return new Valid(maxSize, 1.0);
        }

        public double maxSize() { return maxSize; }
        @Override public double confidence() { return confidence; }
    }

    /**
     * Degraded state - reduced sizing with explicit reason.
     */
    public static final class Degraded extends RiskValidationResult {
        private final double sizeMultiplier;
        private final double confidence;
        private final String reason;
        private final List<String> factors;

        public Degraded(double sizeMultiplier, double confidence,
                       String reason, List<String> factors) {
            this.sizeMultiplier = Math.max(0.0, Math.min(1.0, sizeMultiplier));
            this.confidence = Math.max(0.0, Math.min(1.0, confidence));
            this.reason = reason;
            this.factors = factors;
        }

        public static Degraded of(String reason, String... factors) {
            return new Degraded(0.25, 0.5, reason, java.util.List.of(factors));
        }

        public static Degraded of(double sizeMultiplier, double confidence,
                                  String reason, String... factors) {
            return new Degraded(sizeMultiplier, confidence, reason, java.util.List.of(factors));
        }

        public double sizeMultiplier() { return sizeMultiplier; }
        public String reason() { return reason; }
        public List<String> factors() { return factors; }
        @Override public double confidence() { return confidence; }
    }

    /**
     * Invalid state - order blocked (confidence = 0.0).
     */
    public static final class Invalid extends RiskValidationResult {
        private final String reason;

        public Invalid(String reason, double confidence) {
            this.reason = reason;
        }

        public static Invalid of(String reason) {
            return new Invalid(reason, 0.0);
        }

        public static Invalid staleATR(double ageSeconds) {
            return new Invalid("ATR data stale for " + ageSeconds + "s", 0.0);
        }

        public static Invalid missingCandles(String symbol, int missingCount) {
            return new Invalid(missingCount + " missing candles for " + symbol, 0.0);
        }

        public static Invalid circuitBreakerTriggered() {
            return new Invalid("Circuit breaker triggered", 0.0);
        }

        public static Invalid maxDrawdownExceeded(double drawdown, double limit) {
            return new Invalid("Max drawdown exceeded: " + (drawdown * 100) + "% > " + (limit * 100) + "%", 0.0);
        }

        public String reason() { return reason; }
        @Override public double confidence() { return 0.0; }
    }
}