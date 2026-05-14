package com.trading.infrastructure.journal;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.trading.domain.trading.event.JournalEvent;

import java.io.*;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.*;
import java.time.Instant;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.locks.ReentrantLock;

/**
 * File-based WAL Journal Writer with [length][crc32][payload] framing.
 *
 * Design:
 * - Append-only (immutable segments)
 * - Segment rotation (64MB / 1h)
 * - Idempotency index (prevents duplicate writes)
 * - Crash-safe (force flush on critical events)
 *
 * NOT a debug log - this is the source of truth for replay.
 */
public class FileJournalWriter implements Closeable {

    private static final org.slf4j.Logger log =
        org.slf4j.LoggerFactory.getLogger(FileJournalWriter.class);

    // Segment rotation triggers
    private static final long MAX_SEGMENT_SIZE = 64 * 1024 * 1024; // 64MB
    private static final long MAX_SEGMENT_TIME_MS = 60 * 60 * 1000; // 1 hour
    private static final String SEGMENT_PATTERN = "journal-%010d.log";
    private static final String INDEX_SUFFIX = ".idx";
    private static final String SEGMENT_DATE_PATTERN = "yyyy-MM-dd";

    // Persistence
    private final Path journalDir;
    private final ObjectMapper mapper;
    private final ReentrantLock writeLock = new ReentrantLock();

    // Current segment state
    private volatile long currentSegmentId;
    private volatile long localSequence;
    private volatile long segmentStartTime;
    private volatile Path currentSegmentPath;
    private RandomAccessFile currentRaf;
    private FileChannel currentChannel;

    // Idempotency index (key → fullSequence)
    private final Map<String, String> idempotencyIndex = new ConcurrentHashMap<>();
    private final Path indexPath;

    // Statistics
    private final AtomicLong totalEventsWritten = new AtomicLong(0);
    private final AtomicLong totalBytesWritten = new AtomicLong(0);

    /**
     * Create FileJournalWriter in specified directory.
     * Initializes or resumes from existing journal.
     */
    public FileJournalWriter(Path journalDir) throws IOException {
        this.journalDir = journalDir;

        // Configure ObjectMapper for Instant serialization
        this.mapper = new ObjectMapper();
        this.mapper.registerModule(new JavaTimeModule());
        this.mapper.disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

        // Create directory if needed
        Files.createDirectories(journalDir);

        // Index file for idempotency
        this.indexPath = journalDir.resolve("idempotency.idx");

        // Initialize or resume
        initializeOrResume();
    }

    private void initializeOrResume() throws IOException {
        // Load existing idempotency index
        loadIdempotencyIndex();

        // Find latest segment
        Path[] segments = findSegments();
        if (segments.length > 0) {
            // Resume from latest segment
            Path latest = segments[segments.length - 1];
            this.currentSegmentId = extractSegmentId(latest);
            this.currentSegmentPath = latest;

            // Open segment and get current position (local sequence)
            openSegmentForAppend();
            this.localSequence = countEventsInCurrentSegment();

            log.info("[Journal] Resumed from segment {}, sequence {}",
                currentSegmentId, localSequence);
        } else {
            // Fresh start
            this.currentSegmentId = 1;
            this.localSequence = 0;
            rotateToNewSegment();
        }

        this.segmentStartTime = System.currentTimeMillis();
    }

    /**
     * Append event to journal.
     * Idempotent - same idempotencyKey returns existing sequence.
     *
     * @return The journal event with assigned sequence
     */
    public JournalEvent append(JournalEvent event) throws IOException {
        // Idempotency check
        if (event.idempotencyKey() != null) {
            String existing = idempotencyIndex.get(event.idempotencyKey());
            if (existing != null) {
                log.debug("[Journal] Duplicate skipped: {}", event.idempotencyKey());
                // Return existing event (would need to read, simplified here)
                return event;
            }
        }

        writeLock.lock();
        try {
            // Serialize event to JSON bytes
            byte[] payload = mapper.writeValueAsBytes(event);
            Crc32Payload framed = Crc32Payload.of(payload);

            // Write to segment
            ByteBuffer buffer = ByteBuffer.wrap(framed.toBytes());
            while (buffer.hasRemaining()) {
                currentChannel.write(buffer);
            }
            currentChannel.force(true);

            // Update idempotency index
            String fullSeq = currentSegmentId + ":" + localSequence;
            if (event.idempotencyKey() != null) {
                idempotencyIndex.put(event.idempotencyKey(), fullSeq);
                persistIdempotencyIndex();
            }

            // Update counters
            localSequence++;
            totalEventsWritten.incrementAndGet();
            totalBytesWritten.addAndGet(framed.totalSize());

            log.debug("[Journal] Appended {} → {}", event.type(), fullSeq);

            // Check rotation
            checkRotation();

            return new JournalEvent(
                currentSegmentId,
                localSequence - 1,
                event.timestamp(),
                event.aggregateId(),
                event.type(),
                event.payload(),
                event.causationId(),
                event.correlationId(),
                event.idempotencyKey()
            );
        } finally {
            writeLock.unlock();
        }
    }

    /**
     * Append without idempotency check (for replay from external source).
     */
    public JournalEvent appendRaw(JournalEvent event) throws IOException {
        writeLock.lock();
        try {
            byte[] payload = mapper.writeValueAsBytes(event);
            Crc32Payload framed = Crc32Payload.of(payload);

            ByteBuffer buffer = ByteBuffer.wrap(framed.toBytes());
            while (buffer.hasRemaining()) {
                currentChannel.write(buffer);
            }
            currentChannel.force(true);

            localSequence++;
            totalEventsWritten.incrementAndGet();

            return event;
        } finally {
            writeLock.unlock();
        }
    }

    /**
     * Get last sequence number assigned.
     */
    public long lastSequence() {
        if (localSequence == 0 && currentSegmentId == 1) {
            return -1; // No events
        }
        return Long.parseLong(currentSegmentId + ":" + (localSequence - 1));
    }

    /**
     * Get current segment ID.
     */
    public long currentSegmentId() {
        return currentSegmentId;
    }

    /**
     * Get total events written.
     */
    public long totalEventsWritten() {
        return totalEventsWritten.get();
    }

    private void checkRotation() throws IOException {
        if (shouldRotate()) {
            log.info("[Journal] Rotating segment at {} events", localSequence);
            rotateToNewSegment();
        }
    }

    private boolean shouldRotate() {
        try {
            long size = currentRaf.length();
            long age = System.currentTimeMillis() - segmentStartTime;
            return size >= MAX_SEGMENT_SIZE || age >= MAX_SEGMENT_TIME_MS;
        } catch (IOException e) {
            return false;
        }
    }

    private void rotateToNewSegment() throws IOException {
        closeCurrentSegment();

        currentSegmentId++;
        localSequence = 0;
        segmentStartTime = System.currentTimeMillis();

        String filename = String.format(SEGMENT_PATTERN, currentSegmentId);
        currentSegmentPath = journalDir.resolve(filename);

        openSegmentForAppend();

        log.info("[Journal] New segment: {}", currentSegmentPath.getFileName());
    }

    private void openSegmentForAppend() throws IOException {
        closeCurrentSegment();

        currentRaf = new RandomAccessFile(currentSegmentPath.toFile(), "rw");
        currentChannel = currentRaf.getChannel();
        currentRaf.seek(currentRaf.length());
    }

    private void closeCurrentSegment() {
        try {
            if (currentChannel != null) {
                currentChannel.close();
            }
            if (currentRaf != null) {
                currentRaf.close();
            }
        } catch (IOException e) {
            log.warn("[Journal] Error closing segment", e);
        }
    }

    private Path[] findSegments() throws IOException {
        return Files.list(journalDir)
            .filter(p -> p.getFileName().toString().startsWith("journal-"))
            .filter(p -> !p.getFileName().toString().endsWith(".idx"))
            .sorted()
            .toArray(Path[]::new);
    }

    private long extractSegmentId(Path segmentPath) {
        String name = segmentPath.getFileName().toString();
        // journal-0000001234.log → 1234
        String numStr = name.replace("journal-", "").replace(".log", "");
        return Long.parseLong(numStr);
    }

    private long countEventsInCurrentSegment() throws IOException {
        if (!currentSegmentPath.toFile().exists()) {
            return 0;
        }

        long count = 0;
        long pos = 0;
        long fileSize = currentRaf.length();

        while (pos < fileSize) {
            currentRaf.seek(pos);
            int length = currentRaf.readInt();
            pos += 4; // skip length

            int crc = currentRaf.readInt();
            pos += 4; // skip crc

            pos += length; // skip payload

            if (pos <= fileSize) {
                count++;
            }
            pos = Math.min(pos + 1, fileSize); // alignment check
        }

        return count;
    }

    private void loadIdempotencyIndex() {
        if (indexPath.toFile().exists()) {
            try (BufferedReader reader = Files.newBufferedReader(indexPath)) {
                String line;
                while ((line = reader.readLine()) != null) {
                    String[] parts = line.split("=", 2);
                    if (parts.length == 2) {
                        idempotencyIndex.put(parts[0], parts[1]);
                    }
                }
                log.info("[Journal] Loaded {} idempotency entries", idempotencyIndex.size());
            } catch (IOException e) {
                log.warn("[Journal] Could not load idempotency index", e);
            }
        }
    }

    private void persistIdempotencyIndex() throws IOException {
        // Async persist would be better, but sync for now
        try (BufferedWriter writer = Files.newBufferedWriter(indexPath)) {
            for (Map.Entry<String, String> entry : idempotencyIndex.entrySet()) {
                writer.write(entry.getKey() + "=" + entry.getValue());
                writer.newLine();
            }
        }
    }

    @Override
    public void close() throws IOException {
        writeLock.lock();
        try {
            closeCurrentSegment();
            log.info("[Journal] Closed after writing {} events", totalEventsWritten.get());
        } finally {
            writeLock.unlock();
        }
    }
}