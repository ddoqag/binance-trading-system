package com.trading.domain.trading.model;

/**
 * Order Status
 */
public enum OrderStatus {
    NEW,
    PENDING_NEW,
    SENT,
    PARTIALLY_FILLED,
    FILLED,
    CANCELLED,
    REJECTED,
    PENDING_CANCEL,
    EXPIRED
}
