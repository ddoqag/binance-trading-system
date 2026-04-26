package com.trading.domain.trading.model;

/**
 * Order Type
 */
public enum OrderType {
    MARKET,
    LIMIT,
    STOP,
    STOP_LIMIT,
    IOC,    // Immediate Or Cancel
    FOK     // Fill Or Kill
}
