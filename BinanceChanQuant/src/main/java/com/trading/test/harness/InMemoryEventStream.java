package com.trading.test.harness;

import com.trading.domain.trading.event.JournalEvent;
import com.trading.domain.trading.eventstream.EventStream;

import java.util.ArrayList;
import java.util.List;
import java.util.stream.Stream;

/**
 * In-memory EventStream for testing.
 * Does not persist - used for offline deterministic replay verification.
 */
public class InMemoryEventStream implements EventStream {

    private final List<JournalEvent> events = new ArrayList<>();
    private long currentSeq = -1;

    @Override
    public Stream<JournalEvent> events() {
        return events.stream();
    }

    @Override
    public Stream<JournalEvent> events(long startSeq, long endSeq) {
        return events.stream()
            .filter(e -> {
                long seq = parseFullSeq(e.fullSequence());
                return seq >= startSeq && seq <= endSeq;
            });
    }

    @Override
    public Stream<JournalEvent> eventsForAggregate(String aggregateId) {
        return events.stream()
            .filter(e -> aggregateId.equals(e.aggregateId()));
    }

    @Override
    public long currentSequence() {
        return currentSeq;
    }

    @Override
    public long eventCount() {
        return events.size();
    }

    /**
     * Add event to in-memory store.
     */
    public void add(JournalEvent event) {
        events.add(event);
        currentSeq = parseFullSeq(event.fullSequence());
    }

    /**
     * Add all events from list.
     */
    public void addAll(List<JournalEvent> events) {
        this.events.addAll(events);
        if (!events.isEmpty()) {
            currentSeq = parseFullSeq(events.get(events.size() - 1).fullSequence());
        }
    }

    /**
     * Clear all events.
     */
    public void clear() {
        events.clear();
        currentSeq = -1;
    }

    private long parseFullSeq(String fullSeq) {
        try {
            String[] parts = fullSeq.split(":");
            return (Long.parseLong(parts[0]) << 32) | Long.parseLong(parts[1]);
        } catch (Exception ex) {
            return -1;
        }
    }
}