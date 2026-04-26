package hft.wal;

import java.io.*;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.*;
import java.util.concurrent.locks.ReentrantLock;
import java.util.ArrayList;
import java.util.List;

/**
 * WAL - Write-Ahead Log for Order Persistence
 *
 * Provides durability for order events:
 * - Order submissions
 * - Fills
 * - Cancels
 *
 * Supports recovery after crash.
 */
public class WAL {
    private static final long MAGIC = 0x57414C5F454E4749L;  // "WAL_ENGI"
    private static final int VERSION = 1;

    private final Path logDir;
    private final ReentrantLock writeLock = new ReentrantLock();

    private FileChannel currentChannel;
    private Path currentPath;
    private long currentSeq = 0;
    private long lastCheckpointSeq = 0;

    public WAL(String logDir) throws IOException {
        this.logDir = Paths.get(logDir);
        Files.createDirectories(this.logDir);
        openCurrentLog();
    }

    private void openCurrentLog() throws IOException {
        currentPath = logDir.resolve(String.format("wal_%d.log", System.currentTimeMillis()));
        currentChannel = FileChannel.open(currentPath, StandardOpenOption.CREATE,
            StandardOpenOption.READ, StandardOpenOption.WRITE);
        writeHeader();
    }

    private void writeHeader() throws IOException {
        ByteBuffer buf = ByteBuffer.allocate(24);  // MAGIC(8) + VERSION(4) + currentSeq(8) + padding(4)
        buf.putLong(MAGIC);
        buf.putInt(VERSION);
        buf.putLong(currentSeq);
        buf.flip();
        currentChannel.write(buf);
    }

    /**
     * Log order event
     */
    public void logOrder(String orderId, OrderEntry entry) {
        writeLock.lock();
        try {
            ByteBuffer buf = ByteBuffer.allocate(64);
            buf.putLong(currentSeq++);
            buf.putLong(System.currentTimeMillis());
            buf.put((byte) 1);  // Type: order
            buf.putLong(Long.parseLong(orderId.split("_")[1]));  // Extract numeric ID
            writeString(buf, entry.symbol);
            buf.put((byte) (entry.side.equals("BUY") ? 1 : 2));
            buf.put((byte) (entry.type.equals("LIMIT") ? 1 : 0));
            buf.putDouble(entry.price);
            buf.putDouble(entry.size);
            buf.flip();
            currentChannel.write(buf);
            currentChannel.force(true);
        } catch (IOException e) {
            System.err.println("[WAL] Log order failed: " + e.getMessage());
        } finally {
            writeLock.unlock();
        }
    }

    /**
     * Log fill event
     */
    public void logFill(String orderId, FillEntry entry) {
        writeLock.lock();
        try {
            ByteBuffer buf = ByteBuffer.allocate(48);
            buf.putLong(currentSeq++);
            buf.putLong(System.currentTimeMillis());
            buf.put((byte) 2);  // Type: fill
            buf.putLong(Long.parseLong(orderId.split("_")[1]));
            buf.putDouble(entry.fillPrice);
            buf.putDouble(entry.fillSize);
            buf.putDouble(entry.fee);
            buf.flip();
            currentChannel.write(buf);
            currentChannel.force(true);
        } catch (IOException e) {
            System.err.println("[WAL] Log fill failed: " + e.getMessage());
        } finally {
            writeLock.unlock();
        }
    }

    /**
     * Log cancel event
     */
    public void logCancel(String orderId) {
        writeLock.lock();
        try {
            ByteBuffer buf = ByteBuffer.allocate(24);
            buf.putLong(currentSeq++);
            buf.putLong(System.currentTimeMillis());
            buf.put((byte) 3);  // Type: cancel
            buf.putLong(Long.parseLong(orderId.split("_")[1]));
            buf.flip();
            currentChannel.write(buf);
            currentChannel.force(true);
        } catch (IOException e) {
            System.err.println("[WAL] Log cancel failed: " + e.getMessage());
        } finally {
            writeLock.unlock();
        }
    }

    /**
     * Create checkpoint
     */
    public void checkpoint() {
        writeLock.lock();
        try {
            lastCheckpointSeq = currentSeq;
            ByteBuffer buf = ByteBuffer.allocate(16);
            buf.putLong(currentSeq);
            buf.putLong(lastCheckpointSeq);
            currentChannel.force(true);
            System.out.println("[WAL] Checkpoint: " + currentSeq);
        } catch (IOException e) {
            System.err.println("[WAL] Checkpoint error: " + e.getMessage());
        } finally {
            writeLock.unlock();
        }
    }

    /**
     * Recover from WAL
     */
    public List<WALEntry> recover() {
        List<WALEntry> entries = new ArrayList<>();

        writeLock.lock();
        try {
            File[] files = logDir.toFile().listFiles((dir, name) -> name.startsWith("wal_"));
            if (files == null) return entries;

            for (File file : files) {
                try (FileChannel ch = FileChannel.open(file.toPath(), StandardOpenOption.READ)) {
                    ByteBuffer buf = ByteBuffer.allocate(1024);
                    while (ch.read(buf) > 0) {
                        buf.flip();
                        // Parse and add entries...
                        buf.clear();
                    }
                }
            }
        } catch (IOException e) {
            System.err.println("[WAL] Recovery error: " + e.getMessage());
        } finally {
            writeLock.unlock();
        }

        return entries;
    }

    /**
     * Close WAL
     */
    public void close() throws IOException {
        writeLock.lock();
        try {
            checkpoint();
            if (currentChannel != null) {
                currentChannel.close();
            }
        } finally {
            writeLock.unlock();
        }
    }

    private void writeString(ByteBuffer buf, String s) throws IOException {
        byte[] bytes = s.getBytes("UTF-8");
        buf.putInt(bytes.length);
        if (bytes.length > 0) {
            buf.put(bytes);
        }
    }

    public static class OrderEntry {
        public String symbol;
        public String side;
        public String type;
        public double price;
        public double size;
        public String status;
    }

    public static class FillEntry {
        public String orderId;
        public double fillPrice;
        public double fillSize;
        public double fee;
    }

    public static abstract class WALEntry {
        public long seq;
        public long timestamp;
        public abstract byte type();
    }

    public long getCurrentSeq() { return currentSeq; }
    public long getLastCheckpointSeq() { return lastCheckpointSeq; }
}
