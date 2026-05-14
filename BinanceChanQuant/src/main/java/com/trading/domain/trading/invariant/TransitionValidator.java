package com.trading.domain.trading.invariant;

import com.trading.domain.trading.event.EventType;
import com.trading.domain.trading.event.JournalEvent;
import com.trading.domain.trading.projection.ExecutionStateProjection;

import java.util.ArrayList;
import java.util.List;

/**
 * Transition Validator with HARD vs SOFT invariant distinction.
 *
 * HARD invariants: Violation = corruption, halt recovery
 * SOFT invariants: Violation = warning only, continue processing
 *
 * This distinction is critical: exchange noise should not cause false panic.
 *
 * Java 11 compatible class.
 */
public class TransitionValidator {

    /**
     * Invariant violation result.
     */
    public static final class ValidationResult {
        private final boolean valid;
        private final Severity severity;
        private final String errorMessage;

        public ValidationResult(boolean valid, Severity severity, String errorMessage) {
            this.valid = valid;
            this.severity = severity;
            this.errorMessage = errorMessage;
        }

        public static ValidationResult ok() {
            return new ValidationResult(true, Severity.NONE, null);
        }

        public static ValidationResult hardError(String message) {
            return new ValidationResult(false, Severity.HARD, message);
        }

        public static ValidationResult softWarning(String message) {
            return new ValidationResult(false, Severity.SOFT, message);
        }

        public boolean isValid() { return valid; }
        public boolean isHardViolation() { return !valid && severity == Severity.HARD; }
        public boolean isSoftViolation() { return !valid && severity == Severity.SOFT; }
        public Severity severity() { return severity; }
        public String errorMessage() { return errorMessage; }
    }

    public enum Severity {
        NONE,   // Valid
        SOFT,   // Warning only
        HARD    // Corruption - halt
    }

    /**
     * Validate a single event transition.
     * Returns ok, hard error, or soft warning.
     */
    public ValidationResult validate(JournalEvent event, ExecutionStateProjection.ExecutionStateSnapshot state) {
        EventType type = event.type();

        if (type == null) {
            return ValidationResult.ok();
        }

        switch (type) {
            // === HARD INVARIANTS (halt recovery) ===
            case ORDER_FILLED:
                return validateFilledState(event, state);
            case ORDER_CANCELLED:
                return validateCancelledState(event, state);
            case ORDER_PARTIALLY_FILLED:
                return validatePartiallyFilledState(event, state);

            // === SOFT INVARIANTS (warning only) ===
            case ORDER_ACK_TIMEOUT:
                return validateAckTimeout(event, state);
            case REST_CONFIRMED_NEW:
                return validateRestConfirmed(event, state);

            default:
                return ValidationResult.ok();
        }
    }

    /**
     * Validate FILLED event:
     * HARD: FILLED without prior SENT = corruption
     * HARD: Negative fill quantity = corruption
     * HARD: Fill price <= 0 = corruption
     */
    private ValidationResult validateFilledState(JournalEvent event,
                                                  ExecutionStateProjection.ExecutionStateSnapshot state) {
        String orderId = event.payload().getString("orderId");
        ExecutionStateProjection.OrderState orderState = state.getOrder(orderId);

        // HARD: Order must exist
        if (orderState == null) {
            return ValidationResult.hardError(
                "FILLED before SENT: order " + orderId + " not found in state");
        }

        // HARD: Order must be in a valid pre-fill state
        if (orderState.status() == ExecutionStateProjection.OrderStatus.UNKNOWN) {
            return ValidationResult.hardError(
                "FILLED in UNKNOWN state: " + orderId);
        }

        // HARD: Quantity must be positive
        double qty = event.payload().getDouble("filledQty");
        if (qty <= 0) {
            return ValidationResult.hardError(
                "FILLED with non-positive quantity: " + qty);
        }

        // HARD: Price must be positive
        double price = event.payload().getDouble("avgFillPrice");
        if (price <= 0) {
            return ValidationResult.hardError(
                "FILLED with non-positive price: " + price);
        }

        return ValidationResult.ok();
    }

    /**
     * Validate CANCELLED event:
     * HARD: CANCELLED without prior SENT = corruption
     * HARD: CANCELLED after already FILLED = corruption
     */
    private ValidationResult validateCancelledState(JournalEvent event,
                                                     ExecutionStateProjection.ExecutionStateSnapshot state) {
        String orderId = event.payload().getString("orderId");
        ExecutionStateProjection.OrderState orderState = state.getOrder(orderId);

        // HARD: Order must exist
        if (orderState == null) {
            return ValidationResult.hardError(
                "CANCELLED before SENT: order " + orderId + " not found");
        }

        // HARD: Cannot cancel already filled order
        if (orderState.status() == ExecutionStateProjection.OrderStatus.FILLED) {
            return ValidationResult.hardError(
                "CANCELLED after FILLED: " + orderId);
        }

        return ValidationResult.ok();
    }

    /**
     * Validate PARTIALLY_FILLED:
     * HARD: Same rules as FILLED
     */
    private ValidationResult validatePartiallyFilledState(JournalEvent event,
                                                           ExecutionStateProjection.ExecutionStateSnapshot state) {
        String orderId = event.payload().getString("orderId");
        ExecutionStateProjection.OrderState orderState = state.getOrder(orderId);

        if (orderState == null) {
            return ValidationResult.hardError(
                "PARTIAL_FILL before SENT: order " + orderId + " not found");
        }

        double qty = event.payload().getDouble("filledQty");
        if (qty <= 0) {
            return ValidationResult.hardError(
                "PARTIAL_FILL with non-positive quantity: " + qty);
        }

        return ValidationResult.ok();
    }

    /**
     * Validate ACK_TIMEOUT:
     * SOFT: Timeout is uncertainty, not failure - just warning
     */
    private ValidationResult validateAckTimeout(JournalEvent event,
                                                ExecutionStateProjection.ExecutionStateSnapshot state) {
        String orderId = event.payload().getString("orderId");
        ExecutionStateProjection.OrderState orderState = state.getOrder(orderId);

        if (orderState == null) {
            return ValidationResult.softWarning(
                "ACK_TIMEOUT for unknown order: " + orderId);
        }

        return ValidationResult.ok();
    }

    /**
     * Validate REST_CONFIRMED:
     * SOFT: Late confirmation is normal in high-latency environments
     */
    private ValidationResult validateRestConfirmed(JournalEvent event,
                                                  ExecutionStateProjection.ExecutionStateSnapshot state) {
        String orderId = event.payload().getString("orderId");
        ExecutionStateProjection.OrderState orderState = state.getOrder(orderId);

        if (orderState == null) {
            return ValidationResult.softWarning(
                "REST_CONFIRMED for unknown order: " + orderId);
        }

        return ValidationResult.ok();
    }

    /**
     * Validate causal chain in event sequence.
     */
    public List<ValidationResult> validateCausalChain(List<JournalEvent> events) {
        List<ValidationResult> violations = new ArrayList<>();
        String lastIdempotencyKey = null;

        for (JournalEvent event : events) {
            // Check for duplicate sequence
            if (lastIdempotencyKey != null && lastIdempotencyKey.equals(event.idempotencyKey())) {
                violations.add(ValidationResult.hardError(
                    "Duplicate sequence detected: " + event.idempotencyKey()));
            }

            // Validate causation chain
            String causationId = event.causationId();
            if (causationId != null && !causationId.isEmpty()) {
                boolean found = false;
                for (JournalEvent prior : events) {
                    if (causationId.equals(prior.idempotencyKey())) {
                        found = true;
                        break;
                    }
                }
                if (!found) {
                    violations.add(ValidationResult.softWarning(
                        "Causation references unknown event: " + causationId));
                }
            }

            lastIdempotencyKey = event.idempotencyKey();
        }

        return violations;
    }
}