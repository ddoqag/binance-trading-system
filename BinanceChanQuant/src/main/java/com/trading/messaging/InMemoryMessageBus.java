package com.trading.messaging;

import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;

/**
 * In-memory implementation of MessageBus using concurrent hash maps and queues.
 * Thread-safe and suitable for single-JVM trading systems.
 */
public final class InMemoryMessageBus implements MessageBus {

    private final Map<Class<?>, CopyOnWriteArrayList<String>> subscribers = new ConcurrentHashMap<>();
    private final Map<String, Actor> actors = new ConcurrentHashMap<>();
    private final Map<String, BlockingQueue<Command>> actorMailboxes = new ConcurrentHashMap<>();
    private final Map<String, CompletableFuture<?>> pendingRequests = new ConcurrentHashMap<>();
    private final ExecutorService dispatcher;
    private final AtomicLong messageCounter = new AtomicLong(0);
    private volatile boolean shutdown = false;

    public InMemoryMessageBus() {
        this.dispatcher = Executors.newCachedThreadPool(r -> {
            Thread t = new Thread(r, "MessageBus-Dispatcher");
            t.setDaemon(true);
            return t;
        });
    }

    @Override
    public void tell(String targetActor, Command command) {
        if (shutdown) {
            throw new IllegalStateException("MessageBus is shutdown");
        }
        BlockingQueue<Command> mailbox = actorMailboxes.get(targetActor);
        if (mailbox == null) {
            System.err.println("[MessageBus] No such actor: " + targetActor);
            return;
        }
        if (!mailbox.offer(command)) {
            System.err.println("[MessageBus] Mailbox full for actor: " + targetActor);
        }
    }

    @Override
    public <T extends Command> CompletableFuture<T> ask(String targetActor, Command command) {
        CompletableFuture<T> future = new CompletableFuture<>();
        String correlationId = UUID.randomUUID().toString();
        pendingRequests.put(correlationId, future);

        // Wrap command with correlation ID
        Command wrapped = new CorrelationIdCommand(command, correlationId);
        tell(targetActor, wrapped);

        // Timeout for response
        CompletableFuture.runAsync(() -> {
            try {
                Thread.sleep(5000);
                future.completeExceptionally(new TimeoutException("Ask timeout: " + command.getMessageId()));
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        });

        return future;
    }

    @Override
    public void publish(DomainEvent event) {
        if (shutdown) {
            throw new IllegalStateException("MessageBus is shutdown");
        }
        List<String> targets = subscribers.get(event.getClass());
        if (targets == null || targets.isEmpty()) {
            return;
        }
        for (String actorId : targets) {
            dispatchToActor(actorId, event);
        }
    }

    @Override
    public <T extends Message> void subscribe(String actor, Class<T> messageType) {
        subscribers.computeIfAbsent(messageType, k -> new CopyOnWriteArrayList<>())
                  .add(actor);
    }

    @Override
    public <T extends Message> void unsubscribe(String actor, Class<T> messageType) {
        List<String> subs = subscribers.get(messageType);
        if (subs != null) {
            subs.remove(actor);
        }
    }

    @Override
    public void shutdown() {
        shutdown = true;
        dispatcher.shutdown();
        try {
            if (!dispatcher.awaitTermination(5, TimeUnit.SECONDS)) {
                dispatcher.shutdownNow();
            }
        } catch (InterruptedException e) {
            dispatcher.shutdownNow();
            Thread.currentThread().interrupt();
        }
    }

    // Internal methods

    public void registerActor(Actor actor) {
        actors.put(actor.getId(), actor);
        actorMailboxes.put(actor.getId(), new LinkedBlockingQueue<>(1000));
        actor.setMessageBus(this);

        // Start actor's message processing loop
        dispatcher.submit(() -> processMailbox(actor));
    }

    private void processMailbox(Actor actor) {
        BlockingQueue<Command> mailbox = actorMailboxes.get(actor.getId());
        while (!shutdown && !Thread.currentThread().isInterrupted()) {
            try {
                Command command = mailbox.poll(100, TimeUnit.MILLISECONDS);
                if (command != null) {
                    actor.receive(command);
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            }
        }
    }

    private void dispatchToActor(String actorId, DomainEvent event) {
        Actor actor = actors.get(actorId);
        if (actor == null) {
            System.err.println("[MessageBus] No such actor: " + actorId);
            return;
        }
        dispatcher.submit(() -> actor.receive(event));
    }

    public long nextMessageId() {
        return messageCounter.incrementAndGet();
    }

    // Helper for correlation
    private static class CorrelationIdCommand implements Command {
        private final Command inner;
        private final String correlationId;

        CorrelationIdCommand(Command inner, String correlationId) {
            this.inner = inner;
            this.correlationId = correlationId;
        }

        @Override public String getMessageId() { return inner.getMessageId(); }
        @Override public long getTimestamp() { return inner.getTimestamp(); }
        @Override public String getTargetActor() { return inner.getTargetActor(); }
    }
}
