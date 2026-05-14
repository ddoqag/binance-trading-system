package com.trading.domain.trading.event;

import com.fasterxml.jackson.annotation.JsonCreator;

/**
 * Minimal event taxonomy for Observation Phase.
 * Expand only when new event semantics are truly necessary.
 *
 * NOT: Every business object change
 * NOT: Every state transition
 * YES: Actual causal milestones in execution lifecycle
 */
public enum EventType {
    // === Order Lifecycle (authority: REST) ===
    INTENT_CREATED,      // Trading intent formed (signal → order decision)
    ORDER_SENT,          // Order transmitted to exchange
    ORDER_ACK_TIMEOUT,   // Uncertainty boundary (NOT failure) - waiting for ACK
    REST_CONFIRMED_NEW,  // REST confirms order is live (resolution of ACK_TIMEOUT)
    ORDER_FILLED,        // Full fill received
    ORDER_PARTIALLY_FILLED,
    ORDER_CANCELLED,
    ORDER_EXPIRED,

    // === Position Lifecycle ===
    POSITION_SYNCED,     // Position state reconciled with exchange

    // === System ===
    SNAPSHOT_CREATED,    // Snapshot taken for recovery
    RECOVERY_STARTED,
    RECOVERY_COMPLETED;

    /**
     * Is this event an uncertainty state?
     * ACK_TIMEOUT means "don't know yet" not "failed"
     */
    public boolean isUncertaintyState() {
        return this == ORDER_ACK_TIMEOUT;
    }

    /**
     * Is this event a terminal state (no further transitions)?
     */
    public boolean isTerminal() {
        return this == ORDER_FILLED ||
               this == ORDER_CANCELLED ||
               this == ORDER_EXPIRED;
    }

    @JsonCreator
    public static EventType fromValue(String value) {
        return valueOf(value);
    }
}