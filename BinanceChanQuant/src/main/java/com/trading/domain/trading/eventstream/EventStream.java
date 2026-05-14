package com.trading.domain.trading.eventstream;

import com.trading.domain.trading.event.JournalEvent;

import java.util.stream.Stream;

/**
 * EventStream abstraction for replay engine.
 *
 * Enables swap implementations (File, Kafka, Chronicle Queue, S3, etc.)
 * without affecting replay logic.
 *
 * NOT: Direct file access (would couple replay to file format)
 */
public interface EventStream {

    /**
     * Stream all events from current head.
     */
    Stream<JournalEvent> events();

    /**
     * Stream events in range [startSeq, endSeq] inclusive.
     * @param startSeq segmentId:localSequence composite
     * @param endSeq segmentId:localSequence composite
     */
    Stream<JournalEvent> events(long startSeq, long endSeq);

    /**
     * Stream events for specific aggregate (e.g., "order-123", "position-BTCUSDT").
     */
    Stream<JournalEvent> eventsForAggregate(String aggregateId);

    /**
     * Get current head sequence.
     * Returns -1 if no events.
     */
    long currentSequence();

    /**
     * Get total event count.
     */
    long eventCount();
}