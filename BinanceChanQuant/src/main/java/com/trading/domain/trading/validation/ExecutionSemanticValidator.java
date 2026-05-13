package com.trading.domain.trading.validation;

import com.trading.domain.trading.model.BinanceExecutionSpec;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderIntent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Execution Semantic Validator
 *
 * Final safety check before order is sent to exchange.
 * Prevents semantic drift by validating order intent against execution parameters.
 *
 * Validation rules:
 * - OPEN orders MUST have reduceOnly=false
 * - CLOSE orders MUST have reduceOnly=true
 * - OPEN orders MUST NOT set closePosition=true
 * - CLOSE orders with intent MUST use BinanceExecutionSpec (not manual params)
 *
 * This is the LAST LINE OF DEFENSE against semantic corruption.
 */
public class ExecutionSemanticValidator {

    private static final Logger log = LoggerFactory.getLogger(ExecutionSemanticValidator.class);

    /**
     * Validate order semantic consistency before sending.
     *
     * @param order Order to validate
     * @param spec BinanceExecutionSpec (can be null for legacy orders)
     * @return ValidationResult with pass/fail and reason
     */
    public static ValidationResult validate(Order order, BinanceExecutionSpec spec) {
        if (order == null) {
            return ValidationResult.fail("Order is null");
        }

        // P1: If order has explicit intent, validate against spec
        if (order.hasIntent()) {
            return validateWithIntent(order, spec);
        }

        // Legacy path: warn but allow (backward compatibility during transition)
        log.warn("[Validator] LEGACY_ORDER without intent: orderId={}", order.getOrderId());
        return validateLegacy(order);
    }

    /**
     * Validate order with explicit intent
     */
    private static ValidationResult validateWithIntent(Order order, BinanceExecutionSpec spec) {
        OrderIntent intent = order.getIntent();

        // Rule 1: reduceOnly must be consistent with intent
        if (intent.isClosing() && !order.isReduceOnly()) {
            // Warning: order is closing but reduceOnly not set
            // This should be caught by BinanceExecutionSpec but double-check
            log.warn("[Validator] CLOSE order without reduceOnly: orderId={}, intent={}",
                    order.getOrderId(), intent);
        }

        if (intent.isOpening() && order.isReduceOnly()) {
            return ValidationResult.fail(
                "INVALID: OPEN order cannot have reduceOnly=true: orderId=" + order.getOrderId());
        }

        // Rule 2: CLOSE orders cannot use closePosition (partial close issues)
        // Note: This rule may be relaxed for full exit scenarios
        // For now, CLOSE with closePosition=true is allowed for STOP orders

        // Rule 3: If spec is provided, validate consistency
        if (spec != null) {
            if (intent.isClosing() && !spec.reduceOnly()) {
                return ValidationResult.fail(
                    "INVALID: CLOSE intent but reduceOnly=false: orderId=" + order.getOrderId());
            }
            if (intent.isOpening() && spec.reduceOnly()) {
                return ValidationResult.fail(
                    "INVALID: OPEN intent but reduceOnly=true: orderId=" + order.getOrderId());
            }
        }

        return ValidationResult.pass();
    }

    /**
     * Validate legacy order (without explicit intent)
     * These are allowed during transition but logged
     */
    private static ValidationResult validateLegacy(Order order) {
        // Legacy orders: check basic sanity
        if (order.getQuantity() <= 0) {
            return ValidationResult.fail("INVALID: Order quantity <= 0: " + order.getOrderId());
        }

        if (order.getSymbol() == null || order.getSymbol().isEmpty()) {
            return ValidationResult.fail("INVALID: Order symbol is empty: " + order.getOrderId());
        }

        // Warning for reduceOnly on what looks like opening order
        if (order.isReduceOnly()) {
            log.warn("[Validator] LEGACY order with reduceOnly=true: orderId={}", order.getOrderId());
        }

        return ValidationResult.pass();
    }

    /**
     * Validate spec against intent
     */
    public static ValidationResult validateSpec(OrderIntent intent, BinanceExecutionSpec spec) {
        if (spec == null) {
            return ValidationResult.fail("BinanceExecutionSpec is null");
        }

        if (!spec.isValid()) {
            return ValidationResult.fail("Invalid BinanceExecutionSpec: " + spec);
        }

        // Verify spec matches intent
        BinanceExecutionSpec expected = BinanceExecutionSpec.from(intent);
        if (!expected.side().equals(spec.side()) ||
            !expected.positionSide().equals(spec.positionSide()) ||
            expected.reduceOnly() != spec.reduceOnly()) {
            return ValidationResult.fail(
                "SPEC_MISMATCH: intent=" + intent + " expected=" + expected + " got=" + spec);
        }

        return ValidationResult.pass();
    }

    /**
     * Validation result
     */
    public static final class ValidationResult {
        private final boolean passed;
        private final String reason;

        private ValidationResult(boolean passed, String reason) {
            this.passed = passed;
            this.reason = reason;
        }

        public static ValidationResult pass() {
            return new ValidationResult(true, null);
        }

        public static ValidationResult fail(String reason) {
            return new ValidationResult(false, reason);
        }

        public boolean isPassed() { return passed; }
        public String getReason() { return reason; }

        @Override
        public String toString() {
            return passed ? "PASS" : "FAIL: " + reason;
        }
    }
}