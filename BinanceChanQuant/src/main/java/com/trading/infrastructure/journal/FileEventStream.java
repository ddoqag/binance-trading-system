package com.trading.infrastructure.journal;

import com.trading.domain.trading.event.JournalEvent;
import com.trading.domain.trading.eventstream.EventStream;

import java.io.IOException;
import java.nio.file.Path;
import java.util.stream.Stream;

/**
 * File-based EventStream implementation.
 * Reads from FileJournalReader with segment indexing.
 */
public class FileEventStream implements EventStream {

    private static final org.slf4j.Logger log =
        org.slf4j.LoggerFactory.getLogger(FileEventStream.class);

    private final FileJournalReader reader;
    private long cachedEventCount = -1;

    public FileEventStream(Path journalDir) throws IOException {
        this.reader = new FileJournalReader(journalDir);
    }

    @Override
    public Stream<JournalEvent> events() {
        try {
            return reader.readAll().stream();
        } catch (IOException e) {
            log.error("[FileEventStream] Failed to read events", e);
            return Stream.empty();
        }
    }

    @Override
    public Stream<JournalEvent> events(long startSeq, long endSeq) {
        try {
            return reader.readRange(startSeq, endSeq);
        } catch (IOException e) {
            log.error("[FileEventStream] Failed to read range {} to {}", startSeq, endSeq, e);
            return Stream.empty();
        }
    }

    @Override
    public Stream<JournalEvent> eventsForAggregate(String aggregateId) {
        // Filter by aggregateId after reading
        return events().filter(e -> aggregateId.equals(e.aggregateId()));
    }

    @Override
    public long currentSequence() {
        return reader.getLastValidSequence();
    }

    @Override
    public long eventCount() {
        if (cachedEventCount < 0) {
            cachedEventCount = reader.getSegmentIndex().values().stream()
                .count();
        }
        return cachedEventCount;
    }

    public void close() throws IOException {
        reader.close();
    }
}