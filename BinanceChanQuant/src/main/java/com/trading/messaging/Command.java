package com.trading.messaging;

/**
 * Marker interface for commands - messages that request an action.
 * Commands are sent to a specific actor and expect a response.
 */
public interface Command extends Message {
    String getTargetActor();
}
