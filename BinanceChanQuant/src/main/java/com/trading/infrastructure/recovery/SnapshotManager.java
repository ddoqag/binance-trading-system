package com.trading.infrastructure.recovery;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.trading.domain.trading.event.JournalEvent;
import com.trading.domain.trading.projection.ExecutionStateProjection;
import com.trading.domain.trading.projection.PositionProjection;

import java.io.*;
import java.nio.file.*;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;
import java.util.stream.Stream;

/**
 * Snapshot Manager - manages periodic snapshots for fast recovery.
 *
 * Snapshot contains:
 * - projectionVersion (schema version for compatibility)
 * - stateHash (SHA-256 of final state for verification)
 * - fromSequence (replay from this sequence)
 * - toSequence (last sequence in snapshot)
 * - snapshotTime
 * - executionState
 * - positionState
 *
 * Design:
 * - Snapshot is recovery aid, does NOT replace journal
 * - On recovery: load latest snapshot + replay delta from toSequence+1
 * - Checkpoint-based recovery prevents O(n) replay as events grow
 */
public class SnapshotManager {

    private static final org.slf4j.Logger log =
        org.slf4j.LoggerFactory.getLogger(SnapshotManager.class);

    private static final String SNAPSHOT_DIR = "data/snapshots";
    private static final String SNAPSHOT_PATTERN = "snapshot-%010d-%016d.json";
    private static final int SNAPSHOT_INTERVAL_EVENTS = 1000;
    private static final long SNAPSHOT_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes

    private final Path snapshotDir;
    private final ObjectMapper mapper;
    private final Path latestSymlink;
    private final Path baseDir;

    // Cached latest snapshot
    private final AtomicReference<SnapshotMetadata> latestSnapshot = new AtomicReference<>();
    private long lastSnapshotTime = 0;

    public SnapshotManager(Path baseDir) throws IOException {
        this.baseDir = baseDir;
        this.snapshotDir = baseDir.resolve(SNAPSHOT_DIR);
        this.mapper = new ObjectMapper();
        this.mapper.registerModule(new JavaTimeModule());
        this.mapper.disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

        this.latestSymlink = baseDir.resolve("latest-snapshot.json");

        Files.createDirectories(snapshotDir);
        loadLatestSnapshot();
    }

    /**
     * Snapshot metadata (excluding full state for quick loading).
     */
    public static final class SnapshotMetadata implements Comparable<SnapshotMetadata> {
        private final long segmentId;
        private final long lastSequence;
        private final int projectionVersion;
        private final String stateHash;
        private final Instant snapshotTime;
        private final long eventCount;

        public SnapshotMetadata(
            long segmentId,
            long lastSequence,
            int projectionVersion,
            String stateHash,
            Instant snapshotTime,
            long eventCount
        ) {
            this.segmentId = segmentId;
            this.lastSequence = lastSequence;
            this.projectionVersion = projectionVersion;
            this.stateHash = stateHash;
            this.snapshotTime = snapshotTime;
            this.eventCount = eventCount;
        }

        public String fullSequence() {
            return segmentId + ":" + lastSequence;
        }

        public long segmentId() { return segmentId; }
        public long lastSequence() { return lastSequence; }
        public int projectionVersion() { return projectionVersion; }
        public String stateHash() { return stateHash; }
        public Instant snapshotTime() { return snapshotTime; }
        public long eventCount() { return eventCount; }

        @Override
        public int compareTo(SnapshotMetadata other) {
            return Long.compare(this.lastSequence, other.lastSequence);
        }
    }

    /**
     * Full snapshot data for persistence.
     */
    public static final class Snapshot {
        private long segmentId;
        private long lastSequence;
        private int projectionVersion;
        private String stateHash;
        private Instant snapshotTime;
        private long eventCount;
        private ExecutionStateProjection.ExecutionStateSnapshot executionState;
        private PositionProjection.PositionSnapshot positionState;

        public Snapshot() {} // Jackson default constructor

        public Snapshot(
            long segmentId,
            long lastSequence,
            int projectionVersion,
            String stateHash,
            Instant snapshotTime,
            long eventCount,
            ExecutionStateProjection.ExecutionStateSnapshot executionState,
            PositionProjection.PositionSnapshot positionState
        ) {
            this.segmentId = segmentId;
            this.lastSequence = lastSequence;
            this.projectionVersion = projectionVersion;
            this.stateHash = stateHash;
            this.snapshotTime = snapshotTime;
            this.eventCount = eventCount;
            this.executionState = executionState;
            this.positionState = positionState;
        }

        // Getters and setters for Jackson
        public long segmentId() { return segmentId; }
        public void segmentId(long v) { this.segmentId = v; }
        public long lastSequence() { return lastSequence; }
        public void lastSequence(long v) { this.lastSequence = v; }
        public int projectionVersion() { return projectionVersion; }
        public void projectionVersion(int v) { this.projectionVersion = v; }
        public String stateHash() { return stateHash; }
        public void stateHash(String v) { this.stateHash = v; }
        public Instant snapshotTime() { return snapshotTime; }
        public void snapshotTime(Instant v) { this.snapshotTime = v; }
        public long eventCount() { return eventCount; }
        public void eventCount(long v) { this.eventCount = v; }
        public ExecutionStateProjection.ExecutionStateSnapshot executionState() { return executionState; }
        public void executionState(ExecutionStateProjection.ExecutionStateSnapshot v) { this.executionState = v; }
        public PositionProjection.PositionSnapshot positionState() { return positionState; }
        public void positionState(PositionProjection.PositionSnapshot v) { this.positionState = v; }
    }

    /**
     * Save snapshot if conditions are met.
     */
    public synchronized void maybeSaveSnapshot(
        long segmentId,
        long lastSequence,
        ExecutionStateProjection.ExecutionStateSnapshot execState,
        PositionProjection.PositionSnapshot posState,
        long eventCount
    ) throws IOException {
        // Check interval conditions
        if (eventCount > 0 && eventCount % SNAPSHOT_INTERVAL_EVENTS != 0) {
            if (System.currentTimeMillis() - lastSnapshotTime < SNAPSHOT_INTERVAL_MS) {
                return;
            }
        }

        // Calculate state hash
        String stateHash = calculateStateHash(execState, posState);

        Snapshot snapshot = new Snapshot(
            segmentId,
            lastSequence,
            1,
            stateHash,
            Instant.now(),
            eventCount,
            execState,
            posState
        );

        // Write snapshot file
        String filename = String.format(SNAPSHOT_PATTERN, segmentId, lastSequence);
        Path snapshotPath = snapshotDir.resolve(filename);

        mapper.writeValue(snapshotPath.toFile(), snapshot);

        // Update symlink
        Files.writeString(latestSymlink, snapshotPath.toString());

        latestSnapshot.set(new SnapshotMetadata(
            segmentId, lastSequence, 1, stateHash, Instant.now(), eventCount
        ));

        lastSnapshotTime = System.currentTimeMillis();
        log.info("[Snapshot] Saved snapshot at sequence {} ({} events)", lastSequence, eventCount);
    }

    /**
     * Load latest snapshot.
     */
    public void loadLatestSnapshot() {
        if (!latestSymlink.toFile().exists()) {
            log.info("[Snapshot] No latest snapshot found");
            return;
        }

        try {
            String targetPath = Files.readString(latestSymlink).trim();
            Path snapshotPath = Path.of(targetPath);

            if (!snapshotPath.toFile().exists()) {
                log.warn("[Snapshot] Latest symlink points to non-existent file: {}", targetPath);
                return;
            }

            Snapshot snapshot = mapper.readValue(snapshotPath.toFile(), Snapshot.class);

            latestSnapshot.set(new SnapshotMetadata(
                snapshot.segmentId(),
                snapshot.lastSequence(),
                snapshot.projectionVersion(),
                snapshot.stateHash(),
                snapshot.snapshotTime(),
                snapshot.eventCount()
            ));

            log.info("[Snapshot] Loaded latest snapshot at sequence {}", snapshot.lastSequence());

        } catch (Exception e) {
            log.warn("[Snapshot] Failed to load latest snapshot", e);
        }
    }

    /**
     * Get latest snapshot metadata.
     */
    public SnapshotMetadata getLatest() {
        return latestSnapshot.get();
    }

    /**
     * Load full snapshot data.
     */
    public Snapshot loadSnapshot(SnapshotMetadata metadata) throws IOException {
        String filename = String.format(SNAPSHOT_PATTERN, metadata.segmentId(), metadata.lastSequence());
        Path snapshotPath = snapshotDir.resolve(filename);
        return mapper.readValue(snapshotPath.toFile(), Snapshot.class);
    }

    /**
     * Calculate SHA-256 hash of combined state.
     */
    private String calculateStateHash(
        ExecutionStateProjection.ExecutionStateSnapshot execState,
        PositionProjection.PositionSnapshot posState
    ) {
        try {
            String combined = execState.toString() + "|" + posState.toString();
            java.security.MessageDigest md = java.security.MessageDigest.getInstance("SHA-256");
            byte[] hash = md.digest(combined.getBytes());
            StringBuilder sb = new StringBuilder();
            for (byte b : hash) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (Exception e) {
            return "hash-error";
        }
    }

    /**
     * List all snapshots in order.
     */
    public List<SnapshotMetadata> listSnapshots() throws IOException {
        List<SnapshotMetadata> snapshots = new ArrayList<>();

        try (Stream<Path> stream = Files.list(snapshotDir)) {
            stream.filter(p -> p.getFileName().toString().startsWith("snapshot-"))
                  .sorted()
                  .forEach(p -> {
                      try {
                          Snapshot s = mapper.readValue(p.toFile(), Snapshot.class);
                          snapshots.add(new SnapshotMetadata(
                              s.segmentId(), s.lastSequence(), s.projectionVersion(),
                              s.stateHash(), s.snapshotTime(), s.eventCount()
                          ));
                      } catch (Exception e) {
                          log.warn("[Snapshot] Failed to read snapshot: {}", p);
                      }
                  });
        }

        return snapshots;
    }
}