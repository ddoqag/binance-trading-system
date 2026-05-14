package com.trading.domain.trading.model;

/**
 * Protection reconciliation state for startup recovery.
 * Classifies stop orders found on exchange during recovery.
 */
public enum ProtectionState {
    /** Owned by this system, valid for current position → adopt */
    VALID_ADOPTED,

    /** Owned by this system but invalid (wrong price/qty) → cancel + recreate */
    INVALID_RECREATED,

    /** Not owned by this system → warn only, never cancel/adopt */
    FOREIGN_IGNORED,

    /** Owned but stale (old entry price, etc.) → cancel if safe */
    STALE_CANCELLED,

    /** No protection exists → create new */
    MISSING_CREATED
}