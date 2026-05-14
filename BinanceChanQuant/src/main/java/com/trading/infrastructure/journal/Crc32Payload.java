package com.trading.infrastructure.journal;

import java.nio.ByteBuffer;
import java.util.zip.CRC32;

/**
 * WAL entry format: [4 bytes length][4 bytes crc32][N bytes payload]
 *
 * Design:
 * - length: unsigned int (4 bytes) - payload size
 * - crc32: checksum (4 bytes) - corruption detection
 * - payload: raw bytes - serialized JournalEvent
 *
 * This framing enables:
 * - Crash protection (partial writes detectable)
 * - Corruption truncation (tail truncation recovery)
 * - Replay verification (crc validation)
 *
 * Java 11 compatible class (not record).
 */
public final class Crc32Payload {

    private final byte[] payload;

    private static final int LENGTH_BYTES = 4;
    private static final int CRC_BYTES = 4;
    public static final int OVERHEAD_BYTES = LENGTH_BYTES + CRC_BYTES; // 8 bytes total

    public Crc32Payload(byte[] payload) {
        this.payload = payload;
    }

    /**
     * Create Crc32Payload from raw payload bytes.
     */
    public static Crc32Payload of(byte[] payload) {
        return new Crc32Payload(payload);
    }

    /**
     * Serialize to bytes with length prefix and crc suffix.
     * Format: [length(4)][crc(4)][payload(N)]
     */
    public byte[] toBytes() {
        byte[] result = new byte[OVERHEAD_BYTES + payload.length];
        ByteBuffer bb = ByteBuffer.wrap(result);

        // Write length (big endian)
        bb.putInt(payload.length);

        // Write CRC32
        bb.putInt(crc32());

        // Write payload
        bb.put(payload);

        return result;
    }

    /**
     * Deserialize from bytes with validation.
     * @throws CorruptedJournalException if length or crc invalid
     */
    public static Crc32Payload fromBytes(byte[] data) {
        if (data.length < OVERHEAD_BYTES) {
            throw new CorruptedJournalException(
                "Data too short: " + data.length + " < " + OVERHEAD_BYTES);
        }

        ByteBuffer bb = ByteBuffer.wrap(data);

        // Read length
        int length = bb.getInt();
        if (length < 0 || length > 10_000_000) {
            throw new CorruptedJournalException("Invalid length: " + length);
        }

        // Read CRC
        int storedCrc = bb.getInt();

        // Read payload
        byte[] payloadBytes = new byte[length];
        bb.get(payloadBytes);

        // Validate CRC
        Crc32Payload result = new Crc32Payload(payloadBytes);
        if (result.crc32() != storedCrc) {
            throw new CorruptedJournalException(
                "CRC mismatch: expected " + result.crc32() + ", got " + storedCrc);
        }

        return result;
    }

    /**
     * Calculate CRC32 of payload.
     */
    public int crc32() {
        CRC32 crc = new CRC32();
        crc.update(payload);
        return (int) crc.getValue();
    }

    /**
     * Payload length in bytes.
     */
    public int length() {
        return payload.length;
    }

    /**
     * Total serialized size (length + crc + payload).
     */
    public int totalSize() {
        return OVERHEAD_BYTES + payload.length;
    }

    public byte[] payload() {
        return payload;
    }

    /**
     * Exception for corrupted journal entries.
     */
    public static class CorruptedJournalException extends RuntimeException {
        public CorruptedJournalException(String message) {
            super(message);
        }

        public CorruptedJournalException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}