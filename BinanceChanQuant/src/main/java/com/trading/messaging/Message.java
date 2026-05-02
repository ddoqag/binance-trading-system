package com.trading.messaging;

/**
 * Base marker interface for all messages in the trading system.
 * Messages fall into two categories:
 * - Commands: Requests for action (e.g., SubmitOrder)
 * - DomainEvents: Facts that have occurred (e.g., OrderFilled)
 */
public interface Message {
    String getMessageId();
    long getTimestamp();
}
