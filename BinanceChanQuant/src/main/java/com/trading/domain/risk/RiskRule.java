package com.trading.domain.risk;

import com.trading.domain.trading.model.Order;

/**
 * Risk Rule - single rule that can pass or reject an order.
 * Each rule encapsulates one aspect of risk checking.
 */
public interface RiskRule {

    /**
     * Rule identifier
     */
    String getName();

    /**
     * Check if order passes this rule.
     * @param order Order to check
     * @return CheckResult - pass or reject with reason
     */
    CheckResult check(Order order);

    /**
     * Priority - higher priority rules run first.
     */
    default int getPriority() {
        return 0;
    }

    /**
     * Whether this rule is enabled.
     */
    default boolean isEnabled() {
        return true;
    }

    /**
     * Check result
     */
    final class CheckResult {
        private final boolean passed;
        private final String reason;
        private final String code;

        private CheckResult(boolean passed, String reason, String code) {
            this.passed = passed;
            this.reason = reason;
            this.code = code;
        }

        public static CheckResult pass() {
            return new CheckResult(true, null, null);
        }

        public static CheckResult reject(String reason, String code) {
            return new CheckResult(false, reason, code);
        }

        public boolean isPassed() { return passed; }
        public String getReason() { return reason; }
        public String getCode() { return code; }

        public boolean isRejected() { return !passed; }
    }
}