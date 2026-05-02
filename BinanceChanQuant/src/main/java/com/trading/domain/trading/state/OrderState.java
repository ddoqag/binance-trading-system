package com.trading.domain.trading.state;

/**
 * Order State Machine - lifecycle states for an order.
 *
 * States:
 * - PENDING: Order submitted, waiting for acceptance
 * - ACCEPTED: Order accepted by exchange
 * - FILLED: Order fully executed
 * - PARTIALLY_FILLED: Order partially executed
 * - CANCELLED: Order cancelled by user or system
 * - REJECTED: Order rejected by exchange or risk
 */
public enum OrderState {

    PENDING("Pending", 0),
    ACCEPTED("Accepted", 1),
    FILLED("Filled", 2),
    PARTIALLY_FILLED("PartiallyFilled", 3),
    CANCELLED("Cancelled", 4),
    REJECTED("Rejected", 5);

    private final String displayName;
    private final int order;

    OrderState(String displayName, int order) {
        this.displayName = displayName;
        this.order = order;
    }

    public String getDisplayName() {
        return displayName;
    }

    /**
     * Check if state is terminal (no further transitions possible)
     */
    public boolean isTerminal() {
        return this == FILLED || this == CANCELLED || this == REJECTED;
    }

    /**
     * Check if order is active (not terminal)
     */
    public boolean isActive() {
        return this == PENDING || this == ACCEPTED || this == PARTIALLY_FILLED;
    }

    /**
     * Get next valid states from current state
     */
    public OrderState[] getNextStates() {
        switch (this) {
            case PENDING:
                return new OrderState[]{ACCEPTED, REJECTED, CANCELLED};
            case ACCEPTED:
                return new OrderState[]{FILLED, PARTIALLY_FILLED, CANCELLED};
            case PARTIALLY_FILLED:
                return new OrderState[]{FILLED, CANCELLED};
            default:
                return new OrderState[]{};  // Terminal states have no transitions
        }
    }

    /**
     * Transition to new state, validating the transition is legal.
     */
    public OrderState transition(OrderState newState) {
        for (OrderState valid : getNextStates()) {
            if (valid == newState) {
                return newState;
            }
        }
        throw new IllegalStateException(
            "Invalid transition: " + this + " -> " + newState + " not allowed"
        );
    }
}