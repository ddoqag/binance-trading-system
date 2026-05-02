package com.trading.messaging;

/**
 * Marker interface for domain events - facts that have occurred.
 * Events are published to all subscribed actors.
 */
public interface DomainEvent extends Message {
    String getEventType();
}
