package com.trading.domain.trading.model;

/**
 * Order Type
 */
public enum OrderType {
    MARKET,
    LIMIT,
    STOP,       // Conditional stop with price
    STOP_MARKET, // Stop that triggers MARKET order (no price needed)
    STOP_LIMIT, // Conditional stop with limit price
    IOC,        // Immediate Or Cancel
    FOK         // Fill Or Kill
}
