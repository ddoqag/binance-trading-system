package com.trading.messaging;

import java.util.concurrent.CompletableFuture;

/**
 * Message bus interface for dispatching messages between actors.
 * Supports both point-to-point messaging (tell) and pub/sub (publish).
 */
public interface MessageBus {

    /**
     * Send a command to a specific actor (point-to-point).
     */
    void tell(String targetActor, Command command);

    /**
     * Send a command and expect a response (async).
     */
    <T extends Command> CompletableFuture<T> ask(String targetActor, Command command);

    /**
     * Publish an event to all subscribers (pub-sub).
     */
    void publish(DomainEvent event);

    /**
     * Subscribe an actor to a specific message type.
     */
    <T extends Message> void subscribe(String actor, Class<T> messageType);

    /**
     * Unsubscribe an actor from a specific message type.
     */
    <T extends Message> void unsubscribe(String actor, Class<T> messageType);

    /**
     * Shutdown the message bus gracefully.
     */
    void shutdown();
}
