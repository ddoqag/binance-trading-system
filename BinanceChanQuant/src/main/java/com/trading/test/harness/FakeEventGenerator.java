package com.trading.test.harness;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.trading.domain.trading.event.EventType;
import com.trading.domain.trading.event.JournalEvent;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/**
 * Fake event generator for offline testing.
 * Generates valid event sequences for deterministic replay verification.
 *
 * NOT a mock - generates real JournalEvents that flow through full system.
 */
public class FakeEventGenerator {

    private static final ObjectMapper mapper = new ObjectMapper()
        .registerModule(new JavaTimeModule());

    /**
     * Generate minimal order lifecycle: INTENT_CREATED → ORDER_SENT → ORDER_FILLED
     */
    public static List<JournalEvent> generateOrderLifecycle(String orderId, String symbol) {
        List<JournalEvent> events = new ArrayList<>();
        String correlationId = UUID.randomUUID().toString();
        long now = System.currentTimeMillis();

        // INTENT_CREATED
        ObjectNode payload1 = mapper.createObjectNode();
        payload1.put("orderId", orderId);
        payload1.put("symbol", symbol);
        payload1.put("direction", "LONG");
        payload1.put("quantity", 0.001);
        payload1.put("price", 50000.0);
        payload1.put("timestamp", now);

        events.add(new JournalEvent(
            1, 0,
            Instant.now(),
            "order-" + orderId,
            EventType.INTENT_CREATED,
            JournalEvent.VersionedPayload.of(payload1),
            null,
            correlationId,
            "INTENT-" + orderId
        ));

        // ORDER_SENT
        ObjectNode payload2 = mapper.createObjectNode();
        payload2.put("orderId", orderId);
        payload2.put("symbol", symbol);
        payload2.put("sentTime", now);

        events.add(new JournalEvent(
            1, 1,
            Instant.now(),
            "order-" + orderId,
            EventType.ORDER_SENT,
            JournalEvent.VersionedPayload.of(payload2),
            "INTENT-" + orderId,
            correlationId,
            "SENT-" + orderId
        ));

        // ORDER_FILLED
        ObjectNode payload3 = mapper.createObjectNode();
        payload3.put("orderId", orderId);
        payload3.put("symbol", symbol);
        payload3.put("filledQty", 0.001);
        payload3.put("avgFillPrice", 50000.0);
        payload3.put("fillTime", now);

        events.add(new JournalEvent(
            1, 2,
            Instant.now(),
            "order-" + orderId,
            EventType.ORDER_FILLED,
            JournalEvent.VersionedPayload.of(payload3),
            "SENT-" + orderId,
            correlationId,
            "FILLED-" + orderId
        ));

        return events;
    }

    /**
     * Generate position lifecycle: POSITION_SYNCED (open)
     */
    public static List<JournalEvent> generatePositionOpen(String symbol, double qty, double entryPrice) {
        List<JournalEvent> events = new ArrayList<>();
        long now = System.currentTimeMillis();

        ObjectNode payload = mapper.createObjectNode();
        payload.put("symbol", symbol);
        payload.put("quantity", qty);
        payload.put("avgEntryPrice", entryPrice);
        payload.put("unrealizedPnl", 0.0);
        payload.put("realizedPnl", 0.0);
        payload.put("entryTime", now);
        payload.put("equity", 10000.0);

        events.add(new JournalEvent(
            1, 10,
            Instant.now(),
            "position-" + symbol,
            EventType.POSITION_SYNCED,
            JournalEvent.VersionedPayload.of(payload),
            null,
            "position-" + System.currentTimeMillis(),
            "POSITION-OPEN-" + symbol
        ));

        return events;
    }

    /**
     * Generate ACK_TIMEOUT → REST_CONFIRMED sequence (uncertainty resolution)
     */
    public static List<JournalEvent> generateUncertaintyResolution(String orderId, String symbol) {
        List<JournalEvent> events = new ArrayList<>();
        String correlationId = UUID.randomUUID().toString();

        // ORDER_SENT
        ObjectNode sent = mapper.createObjectNode();
        sent.put("orderId", orderId);
        sent.put("symbol", symbol);

        events.add(new JournalEvent(
            1, 100,
            Instant.now(),
            "order-" + orderId,
            EventType.ORDER_SENT,
            JournalEvent.VersionedPayload.of(sent),
            null,
            correlationId,
            "SENT-" + orderId
        ));

        // ACK_TIMEOUT (uncertainty, NOT failure)
        ObjectNode timeout = mapper.createObjectNode();
        timeout.put("orderId", orderId);
        timeout.put("timeoutAt", System.currentTimeMillis());
        timeout.put("reason", "No ACK received within timeout window");

        events.add(new JournalEvent(
            1, 101,
            Instant.now(),
            "order-" + orderId,
            EventType.ORDER_ACK_TIMEOUT,
            JournalEvent.VersionedPayload.of(timeout),
            "SENT-" + orderId,
            correlationId,
            "ACK_TIMEOUT-" + orderId
        ));

        // REST_CONFIRMED_NEW (resolution via REST query)
        ObjectNode confirmed = mapper.createObjectNode();
        confirmed.put("orderId", orderId);
        confirmed.put("symbol", symbol);
        confirmed.put("status", "NEW");
        confirmed.put("confirmedAt", System.currentTimeMillis());

        events.add(new JournalEvent(
            1, 102,
            Instant.now(),
            "order-" + orderId,
            EventType.REST_CONFIRMED_NEW,
            JournalEvent.VersionedPayload.of(confirmed),
            "ACK_TIMEOUT-" + orderId,
            correlationId,
            "REST_CONFIRMED-" + orderId
        ));

        return events;
    }

    /**
     * Generate invalid sequence: FILLED before SENT (for invariant testing)
     */
    public static List<JournalEvent> generateInvalidSequence(String orderId) {
        List<JournalEvent> events = new ArrayList<>();
        String correlationId = UUID.randomUUID().toString();

        // FILLED first (violates: FILLED requires SENT first)
        ObjectNode filled = mapper.createObjectNode();
        filled.put("orderId", orderId);
        filled.put("filledQty", 0.001);
        filled.put("fillTime", System.currentTimeMillis());

        events.add(new JournalEvent(
            1, 200,
            Instant.now(),
            "order-" + orderId,
            EventType.ORDER_FILLED,
            JournalEvent.VersionedPayload.of(filled),
            null,  // No causation (invalid!)
            correlationId,
            "FILLED-" + orderId
        ));

        return events;
    }

    /**
     * Generate snapshot events (for recovery testing)
     */
    public static List<JournalEvent> generateSnapshotSequence(long segmentId, long fromSeq) {
        List<JournalEvent> events = new ArrayList<>();

        ObjectNode snapshot = mapper.createObjectNode();
        snapshot.put("segmentId", segmentId);
        snapshot.put("lastSequence", fromSeq);
        snapshot.put("snapshotTime", System.currentTimeMillis());

        events.add(new JournalEvent(
            segmentId, fromSeq,
            Instant.now(),
            "system",
            EventType.SNAPSHOT_CREATED,
            JournalEvent.VersionedPayload.of(snapshot),
            null,
            "snapshot-" + System.currentTimeMillis(),
            "SNAPSHOT-" + segmentId + "-" + fromSeq
        ));

        return events;
    }
}