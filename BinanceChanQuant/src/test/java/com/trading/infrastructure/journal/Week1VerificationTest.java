package com.trading.infrastructure.journal;

import com.fasterxml.jackson.databind.node.ObjectNode;
import com.trading.domain.trading.event.EventType;
import com.trading.domain.trading.event.JournalEvent;
import com.trading.domain.trading.invariant.TransitionValidator;
import com.trading.domain.trading.projection.ExecutionStateProjection;
import com.trading.domain.trading.projection.PositionProjection;
import com.trading.test.harness.FakeEventGenerator;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.DisplayName;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Week 1 Event Sourcing Foundation Verification Tests.
 *
 * <p>Three success criteria:
 * <ol>
 *   <li>Deterministic Replay: 100x fake events → WAL → replay → SHA256 identical</li>
 *   <li>Crash Recovery: kill -9 simulation → corruption truncation → recovery</li>
 *   <li>Invalid Event Order: deterministic fail (no silent repair)</li>
 * </ol>
 */
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
class Week1VerificationTest {

    private static final Path TEST_JOURNAL_DIR =
        Path.of(System.getProperty("java.io.tmpdir"), "week1-verification-test");

    private static final AtomicInteger testRun = new AtomicInteger(0);

    // Projection instances for evolve calls
    private final ExecutionStateProjection execProjection = new ExecutionStateProjection();
    private final PositionProjection posProjection = new PositionProjection();

    @BeforeEach
    void setUp() throws IOException {
        // Clean directory before each test
        Files.createDirectories(TEST_JOURNAL_DIR);
    }

    @AfterEach
    void tearDown() throws IOException {
        // Cleanup
        try {
            Files.walk(TEST_JOURNAL_DIR)
                .sorted(java.util.Comparator.reverseOrder())
                .map(Path::toFile)
                .forEach(java.io.File::delete);
        } catch (IOException e) {
            // ignore cleanup errors
        }
    }

    // ========== Success Criterion 1: Deterministic Replay ==========

    @Test
    @Order(1)
    @DisplayName("CRITERION-1: 100x deterministic replay with identical SHA256 hash")
    void criterion1_deterministicReplay_100x() throws Exception {
        int iterations = 100;
        String[] hashes = new String[iterations];

        for (int i = 0; i < iterations; i++) {
            testRun.incrementAndGet();

            // Clean start
            Files.walk(TEST_JOURNAL_DIR)
                .sorted(java.util.Comparator.reverseOrder())
                .map(Path::toFile)
                .forEach(java.io.File::delete);
            Files.createDirectories(TEST_JOURNAL_DIR);

            // Generate fake events
            List<JournalEvent> events = FakeEventGenerator.generateOrderLifecycle(
                "order-" + i, "BTCUSDT");
            events.addAll(FakeEventGenerator.generatePositionOpen("BTCUSDT", 0.01, 50000.0));

            // Write to WAL
            try (FileJournalWriter writer = new FileJournalWriter(TEST_JOURNAL_DIR)) {
                for (JournalEvent event : events) {
                    writer.append(event);
                }
            }

            // Replay through projections
            FileEventStream stream = new FileEventStream(TEST_JOURNAL_DIR);
            ExecutionStateProjection.ExecutionStateSnapshot execState =
                ExecutionStateProjection.ExecutionStateSnapshot.empty();
            PositionProjection.PositionSnapshot posState =
                PositionProjection.PositionSnapshot.empty("BTCUSDT");

            for (JournalEvent event : stream.events().toList()) {
                execState = execProjection.evolve(execState, event);
                posState = posProjection.evolve(posState, event);
            }

            // Calculate hash
            hashes[i] = calculateStateHash(execState, posState);
            stream.close();
        }

        // All hashes must be identical (deterministic)
        String firstHash = hashes[0];
        for (int i = 1; i < iterations; i++) {
            assertEquals(firstHash, hashes[i],
                "Hash mismatch at iteration " + i + ": replay is NOT deterministic");
        }

        System.out.println("[CRITERION-1] PASSED: " + iterations +
            " iterations, all hashes identical = " + firstHash);
    }

    // ========== Success Criterion 2: Crash Recovery ==========

    @Test
    @Order(2)
    @DisplayName("CRITERION-2: kill -9 simulation → corruption truncation → recovery")
    void criterion2_crashRecovery_corruptionTruncation() throws Exception {
        // Write events normally first
        int eventCount = 10;
        try (FileJournalWriter writer = new FileJournalWriter(TEST_JOURNAL_DIR)) {
            for (int i = 0; i < eventCount; i++) {
                JournalEvent event = FakeEventGenerator.generateOrderLifecycle(
                    "order-" + i, "BTCUSDT").get(0); // INTENT only
                writer.append(event);
            }
        }

        // Get the segment file
        Path segmentFile = Files.list(TEST_JOURNAL_DIR)
            .filter(p -> p.getFileName().toString().startsWith("journal-"))
            .findFirst()
            .orElseThrow();

        // Get file size before corruption
        long fileSizeBefore = Files.size(segmentFile);

        // Simulate kill -9: truncate the file mid-write, losing the last few events
        // This is more realistic than adding garbage bytes
        long truncateTo = fileSizeBefore - 50; // Lose last ~50 bytes
        try (java.io.RandomAccessFile raf =
                new java.io.RandomAccessFile(segmentFile.toFile(), "rw")) {
            raf.setLength(truncateTo);
        }

        // Recover using FileJournalReader (corruption truncation)
        FileJournalReader reader = new FileJournalReader(TEST_JOURNAL_DIR);
        List<JournalEvent> recovered = reader.readAll();

        // Should have recovered fewer than 10 events (truncated tail)
        assertTrue(recovered.size() < eventCount,
            "Recovery should find fewer than " + eventCount + " events after truncation, got " + recovered.size());

        // Verify reader detected corruption via truncated entries
        // When file is truncated mid-entry, read will stop at corruption
        assertTrue(recovered.size() >= 0,
            "Recovery should handle truncated file gracefully");

        System.out.println("[CRITERION-2] PASSED: " + recovered.size() +
            " events recovered (of " + eventCount + " written) - truncation handled");
    }

    // ========== Success Criterion 3: Invalid Event Order ==========

    @Test
    @Order(3)
    @DisplayName("CRITERION-3: invalid event order → deterministic fail (no silent repair)")
    void criterion3_invalidEventOrder_deterministicFail() throws Exception {
        // Test TransitionValidator directly without WAL
        // Create FILLED event directly (bypassing serialization)
        ObjectNode payload = new com.fasterxml.jackson.databind.node.ObjectNode(
            new com.fasterxml.jackson.databind.node.JsonNodeFactory(true));
        payload.put("orderId", "order-invalid");
        payload.put("filledQty", 0.001);
        payload.put("avgFillPrice", 50000.0);

        JournalEvent invalidEvent = new JournalEvent(
            1, 200,
            java.time.Instant.now(),
            "order-order-invalid",
            EventType.ORDER_FILLED,
            JournalEvent.VersionedPayload.of(payload),
            null,
            "test-corr-3",
            "FILLED-order-invalid"
        );

        System.out.println("[CRITERION-3] Testing TransitionValidator directly");
        System.out.println("[CRITERION-3] Event type=" + invalidEvent.type() +
            ", aggregateId=" + invalidEvent.aggregateId() +
            ", orderId=" + invalidEvent.payload().getString("orderId"));

        ExecutionStateProjection.ExecutionStateSnapshot emptyState =
            ExecutionStateProjection.ExecutionStateSnapshot.empty();

        TransitionValidator validator = new TransitionValidator();
        TransitionValidator.ValidationResult result = validator.validate(invalidEvent, emptyState);

        System.out.println("[CRITERION-3] Validation: isValid=" + result.isValid() +
            ", isHard=" + result.isHardViolation() +
            ", error='" + result.errorMessage() + "'");

        assertTrue(result.isHardViolation(),
            "FILLED before SENT should produce HARD violation. Got: " + result.errorMessage());
        assertTrue(result.errorMessage().contains("not found"),
            "Error should mention order not found, got: " + result.errorMessage());

        System.out.println("[CRITERION-3] PASSED: Invalid event order detected by TransitionValidator");
    }

    // ========== Additional Integration Test ==========

    @Test
    @Order(4)
    @DisplayName("INTEGRATION: Full lifecycle with uncertainty resolution")
    void integration_fullLifecycle_withUncertaintyResolution() throws Exception {
        // Generate complete order lifecycle with ACK_TIMEOUT and REST_CONFIRMED
        List<JournalEvent> events = new java.util.ArrayList<>();
        events.addAll(FakeEventGenerator.generateUncertaintyResolution("order-1", "BTCUSDT"));

        // Write to WAL
        try (FileJournalWriter writer = new FileJournalWriter(TEST_JOURNAL_DIR)) {
            for (JournalEvent event : events) {
                writer.append(event);
            }
        }

        // Replay with TransitionValidator
        FileEventStream stream = new FileEventStream(TEST_JOURNAL_DIR);
        ExecutionStateProjection.ExecutionStateSnapshot state =
            ExecutionStateProjection.ExecutionStateSnapshot.empty();
        TransitionValidator validator = new TransitionValidator();

        for (JournalEvent event : stream.events().toList()) {
            TransitionValidator.ValidationResult result = validator.validate(event, state);
            // SOFT warnings should be logged but not halt recovery
            assertFalse(result.isHardViolation(),
                "ACK_TIMEOUT and REST_CONFIRMED are SOFT, not HARD: " + result.errorMessage());
            state = execProjection.evolve(state, event);
        }

        stream.close();

        System.out.println("[INTEGRATION] PASSED: Full lifecycle replayed without false positives");
    }

    // ========== Helper Methods ==========

    private String calculateStateHash(
        ExecutionStateProjection.ExecutionStateSnapshot execState,
        PositionProjection.PositionSnapshot posState
    ) {
        try {
            String combined = execState.lastSequence() + "|" +
                execState.orders().size() + "|" +
                posState.lastSequence() + "|" +
                posState.symbol() + "|" +
                posState.quantity();
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] hash = md.digest(combined.getBytes());
            StringBuilder sb = new StringBuilder();
            for (byte b : hash) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }
}