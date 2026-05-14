package com.trading.infrastructure.journal;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.trading.domain.trading.event.EventType;
import com.trading.domain.trading.event.JournalEvent;

import java.io.Closeable;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.ByteBuffer;
import java.nio.file.*;
import java.util.*;
import java.util.stream.Stream;

/**
 * File-based Journal Reader with corruption truncation recovery.
 *
 * Design:
 * - Reads segments in sequence order
 * - Validates each entry (length + CRC)
 * - On corruption: truncates to last valid entry (not entire journal unusable)
 * - Supports range queries (startSeq to endSeq)
 */
public class FileJournalReader implements Closeable {

    private static final org.slf4j.Logger log =
        org.slf4j.LoggerFactory.getLogger(FileJournalReader.class);

    private static final String SEGMENT_PATTERN = "journal-%010d.log";

    private final Path journalDir;
    private final ObjectMapper mapper;
    private final NavigableMap<Long, Path> segmentIndex; // segmentId → file

    // Recovery state
    private long lastValidSequence = -1;
    private int corruptedEntriesSkipped = 0;

    public FileJournalReader(Path journalDir) throws IOException {
        this.journalDir = journalDir;
        this.mapper = new ObjectMapper();
        this.mapper.registerModule(new JavaTimeModule());
        this.mapper.disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

        // Build segment index
        this.segmentIndex = new TreeMap<>();
        buildSegmentIndex();
    }

    private void buildSegmentIndex() throws IOException {
        if (!journalDir.toFile().exists()) {
            return;
        }

        try (Stream<Path> stream = Files.list(journalDir)) {
            stream.filter(p -> p.getFileName().toString().startsWith("journal-"))
                  .filter(p -> !p.getFileName().toString().endsWith(".idx"))
                  .sorted()
                  .forEach(p -> {
                      long segmentId = extractSegmentId(p);
                      segmentIndex.put(segmentId, p);
                  });
        }

        log.info("[Reader] Indexed {} segments", segmentIndex.size());
    }

    private long extractSegmentId(Path segmentPath) {
        String name = segmentPath.getFileName().toString();
        String numStr = name.replace("journal-", "").replace(".log", "");
        return Long.parseLong(numStr);
    }

    /**
     * Read all events from startSeq to endSeq (inclusive).
     * Skips corrupted entries and continues from next valid entry.
     *
     * @return Stream of JournalEvents in order
     */
    public Stream<JournalEvent> readRange(long startSeq, long endSeq) throws IOException {
        List<JournalEvent> events = new ArrayList<>();

        // Parse sequence range
        long[] startParts = parseSequence(startSeq);
        long[] endParts = parseSequence(endSeq);

        // Iterate segments
        for (Map.Entry<Long, Path> entry : segmentIndex.subMap(startParts[0], true, endParts[0], true).entrySet()) {
            long segmentId = entry.getKey();
            Path segmentPath = entry.getValue();

            long localStart = (segmentId == startParts[0]) ? startParts[1] : 0;
            long localEnd = (segmentId == endParts[0]) ? endParts[1] : Long.MAX_VALUE;

            List<JournalEvent> segmentEvents = readSegment(segmentPath, localStart, localEnd);
            events.addAll(segmentEvents);
        }

        return events.stream();
    }

    /**
     * Read all events from current head.
     */
    public List<JournalEvent> readAll() throws IOException {
        if (segmentIndex.isEmpty()) {
            return List.of();
        }

        long lastSegmentId = segmentIndex.lastKey();
        Path lastPath = segmentIndex.get(lastSegmentId);

        return readSegment(lastPath, 0, Long.MAX_VALUE);
    }

    /**
     * Read a specific segment with local sequence range.
     */
    private List<JournalEvent> readSegment(Path segmentPath, long fromLocalSeq, long toLocalSeq)
            throws IOException {

        List<JournalEvent> events = new ArrayList<>();
        long localSeq = 0;

        try (RandomAccessFile raf = new RandomAccessFile(segmentPath.toFile(), "r")) {
            long fileSize = raf.length();
            long pos = 0;

            while (pos < fileSize) {
                try {
                    // Read length (4 bytes)
                    raf.seek(pos);
                    int length = raf.readInt();
                    pos += 4;

                    // Sanity check on length
                    if (length < 0 || length > 10_000_000) {
                        log.warn("[Reader] Invalid length {} at pos {}, truncating", length, pos - 4);
                        break; // Corrupted - truncate here
                    }

                    // Check bounds
                    if (pos + 4 + length > fileSize) {
                        log.warn("[Reader] Truncated entry at pos {}, file ends", pos);
                        break; // Corrupted - truncate here
                    }

                    // Read CRC (4 bytes)
                    int storedCrc = raf.readInt();
                    pos += 4;

                    // Read payload
                    byte[] payloadBytes = new byte[length];
                    raf.readFully(payloadBytes);
                    pos += length;

                    // Validate CRC
                    Crc32Payload payload = new Crc32Payload(payloadBytes);
                    if (payload.crc32() != storedCrc) {
                        log.warn("[Reader] CRC mismatch at localSeq {}, truncating", localSeq);
                        break; // Corrupted - truncate here
                    }

                    // Deserialize event
                    JournalEvent event = mapper.readValue(payloadBytes, JournalEvent.class);

                    // Filter by local sequence range
                    if (localSeq >= fromLocalSeq && localSeq <= toLocalSeq) {
                        events.add(event);
                    }

                    lastValidSequence = event.segmentId() + event.localSequence();
                    localSeq++;

                } catch (Exception e) {
                    log.warn("[Reader] Corrupted entry at localSeq {}, truncating: {}",
                        localSeq, e.getMessage());
                    corruptedEntriesSkipped++;
                    break; // Stop at first corruption (tail truncation)
                }
            }
        }

        return events;
    }

    /**
     * Get last valid sequence after reading.
     */
    public long getLastValidSequence() {
        return lastValidSequence;
    }

    /**
     * Get count of corrupted entries skipped.
     */
    public int getCorruptedEntriesSkipped() {
        return corruptedEntriesSkipped;
    }

    /**
     * Parse full sequence string (segmentId:localSequence) to array.
     */
    public static long[] parseSequence(String fullSeq) {
        String[] parts = fullSeq.split(":");
        return new long[]{Long.parseLong(parts[0]), Long.parseLong(parts[1])};
    }

    public static long[] parseSequence(long compositeSeq) {
        // For composite format where high bits = segmentId, low bits = localSequence
        long segmentId = compositeSeq >> 32;
        long localSeq = compositeSeq & 0xFFFFFFFFL;
        return new long[]{segmentId, localSeq};
    }

    /**
     * Get segment files in order.
     */
    public NavigableMap<Long, Path> getSegmentIndex() {
        return Collections.unmodifiableNavigableMap(segmentIndex);
    }

    @Override
    public void close() throws IOException {
        log.info("[Reader] Read {} events, skipped {} corrupted entries",
            lastValidSequence + 1, corruptedEntriesSkipped);
    }
}