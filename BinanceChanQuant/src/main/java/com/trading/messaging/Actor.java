package com.trading.messaging;

import java.util.concurrent.atomic.AtomicLong;

/**
 * Base class for all actors in the trading system.
 * Actors receive messages via their mailbox and process them.
 * Each actor runs in its own thread for isolation.
 */
public abstract class Actor {

    private static final AtomicLong actorCounter = new AtomicLong(0);

    private final String id;
    private final String name;
    private MessageBus bus;

    protected Actor(String name) {
        this.id = name + "-" + actorCounter.incrementAndGet();
        this.name = name;
    }

    public String getId() {
        return id;
    }

    public String getName() {
        return name;
    }

    public void setMessageBus(MessageBus bus) {
        this.bus = bus;
    }

    protected MessageBus getBus() {
        return bus;
    }

    /**
     * Send a command to another actor.
     */
    protected void tell(String targetActor, Command command) {
        bus.tell(targetActor, command);
    }

    /**
     * Publish an event to all subscribers.
     */
    protected void publish(DomainEvent event) {
        bus.publish(event);
    }

    /**
     * Receive and process a command.
     */
    public abstract void receive(Command command);

    /**
     * Receive and process a domain event.
     */
    public abstract void receive(DomainEvent event);

    /**
     * Generate unique message ID.
     */
    protected String newMessageId() {
        return getId() + "-" + System.nanoTime();
    }

    @Override
    public String toString() {
        return getClass().getSimpleName() + "[" + id + "]";
    }
}
