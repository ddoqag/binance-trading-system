package com.trading.domain.trading.event;

import com.fasterxml.jackson.annotation.JsonAutoDetect;
import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.JsonNode;

import java.time.Instant;

/**
 * JournalEvent - The immutable fact of the event sourcing ledger.
 *
 * Design principles:
 * 1. sequence is persistent monotonic (segmentId:localSequence) across restarts
 * 2. payload is versioned schema (schemaVersion + JsonNode) for replay safety
 * 3. causationId/correlationId enable full causal tracing
 * 4. idempotencyKey prevents duplicate replay
 *
 * Java 11 compatible class (not record).
 */
@JsonAutoDetect(getterVisibility = JsonAutoDetect.Visibility.PUBLIC_ONLY)
public final class JournalEvent implements Comparable<JournalEvent> {

    private final long segmentId;
    private final long localSequence;
    private final Instant timestamp;
    private final String aggregateId;
    private final EventType type;
    private final VersionedPayload payload;
    private final String causationId;
    private final String correlationId;
    private final String idempotencyKey;

    @JsonCreator
    public JournalEvent(
        @JsonProperty("segmentId") long segmentId,
        @JsonProperty("localSequence") long localSequence,
        @JsonProperty("timestamp") Instant timestamp,
        @JsonProperty("aggregateId") String aggregateId,
        @JsonProperty("type") EventType type,
        @JsonProperty("payload") VersionedPayload payload,
        @JsonProperty("causationId") String causationId,
        @JsonProperty("correlationId") String correlationId,
        @JsonProperty("idempotencyKey") String idempotencyKey
    ) {
        this.segmentId = segmentId;
        this.localSequence = localSequence;
        this.timestamp = timestamp;
        this.aggregateId = aggregateId;
        this.type = type;
        this.payload = payload;
        this.causationId = causationId;
        this.correlationId = correlationId;
        this.idempotencyKey = idempotencyKey;
    }

    /**
     * Full persistent sequence identifier.
     * Format: segmentId:localSequence
     * Example: "1234:567890"
     */
    public String fullSequence() {
        return segmentId + ":" + localSequence;
    }

    /**
     * Parse full sequence string back to segmentId:localSequence
     */
    public static long[] parseSequence(String fullSeq) {
        String[] parts = fullSeq.split(":");
        return new long[]{Long.parseLong(parts[0]), Long.parseLong(parts[1])};
    }

    /**
     * Create a new event with generated idempotency key.
     */
    public static String generateIdempotencyKey(String aggregateId, EventType type, JsonNode payload) {
        int hash = (aggregateId + type.name() + payload.toString()).hashCode();
        return type.name() + "-" + aggregateId + "-" + Math.abs(hash);
    }

    @Override
    public int compareTo(JournalEvent other) {
        if (this.segmentId != other.segmentId) {
            return Long.compare(this.segmentId, other.segmentId);
        }
        return Long.compare(this.localSequence, other.localSequence);
    }

    // Getters
    public long segmentId() { return segmentId; }
    public long localSequence() { return localSequence; }
    public Instant timestamp() { return timestamp; }
    public String aggregateId() { return aggregateId; }
    public EventType type() { return type; }
    public VersionedPayload payload() { return payload; }
    public String causationId() { return causationId; }
    public String correlationId() { return correlationId; }
    public String idempotencyKey() { return idempotencyKey; }

    /**
     * Versioned payload for schema evolution safety.
     */
    @JsonAutoDetect(getterVisibility = JsonAutoDetect.Visibility.PUBLIC_ONLY)
    public static final class VersionedPayload {
        private final int schemaVersion;
        private final JsonNode data;

        @JsonCreator
        public VersionedPayload(
            @JsonProperty("schemaVersion") int schemaVersion,
            @JsonProperty("data") JsonNode data
        ) {
            this.schemaVersion = schemaVersion;
            this.data = data;
        }

        public static VersionedPayload of(JsonNode data) {
            return new VersionedPayload(1, data);
        }

        public int schemaVersion() { return schemaVersion; }
        public JsonNode data() { return data; }

        public JsonNode get(String fieldName) {
            return data.get(fieldName);
        }

        public double getDouble(String fieldName) {
            return data.get(fieldName).asDouble();
        }

        public String getString(String fieldName) {
            return data.get(fieldName).asText();
        }

        public long getLong(String fieldName) {
            return data.get(fieldName).asLong();
        }
    }
}