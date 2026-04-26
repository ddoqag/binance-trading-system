package hft.shm;

import java.io.*;
import java.nio.MappedByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileChannel.MapMode;
import java.nio.ByteOrder;
import java.nio.ByteBuffer;
import java.util.concurrent.atomic.AtomicLong;

/**
 * SharedMemoryManager - Zero-Copy Shared Memory for HFT System
 *
 * Uses memory-mapped files for lock-free synchronization between
 * Java (execution engine) and Python (AI brain).
 *
 * Windows implementation using RandomAccessFile + FileChannel.
 */
public class SharedMemoryManager implements AutoCloseable {
    private static final int STATE_SIZE = 144;  // Must match TradingSharedState

    private final String path;
    private RandomAccessFile file;
    private FileChannel channel;
    private MappedByteBuffer buffer;
    private TradingSharedState state;

    private volatile boolean connected = false;

    public SharedMemoryManager(String path) throws IOException {
        this.path = path;
        initialize();
    }

    private void initialize() throws IOException {
        // Ensure parent directory exists
        File parent = new File(path).getParentFile();
        if (parent != null && !parent.exists()) {
            parent.mkdirs();
        }

        // Create or open file
        file = new RandomAccessFile(path, "rw");

        // Ensure file is large enough
        if (file.length() < STATE_SIZE) {
            file.setLength(STATE_SIZE);
        }

        // Map the file to memory
        channel = file.getChannel();
        buffer = channel.map(MapMode.READ_WRITE, 0, STATE_SIZE);
        buffer.order(ByteOrder.LITTLE_ENDIAN);

        state = new TradingSharedState();
        connected = true;

        System.out.println("[SHM] Initialized: path=" + path + ", size=" + STATE_SIZE);
    }

    /**
     * Write market data with sequence lock
     */
    public void writeMarketData(double bestBid, double bestAsk, double microPrice,
                                double ofi, float tradeImb, float bidQueue, float askQueue) {
        if (!connected) return;

        // Increment sequence to indicate write in progress
        long seq = state.incrementSeq();

        // Write all fields
        state.setTimestamp(System.nanoTime());
        state.setBestBid(bestBid);
        state.setBestAsk(bestAsk);
        state.setMicroPrice(microPrice);
        state.setOfiSignal(ofi);
        state.setTradeImbalance(tradeImb);
        state.setBidQueuePos(bidQueue);
        state.setAskQueuePos(askQueue);

        // Commit by writing seqEnd
        state.commitSeq(seq);

        // Force write to disk
        buffer.force();
    }

    /**
     * Read AI decision with validation
     */
    public TradingSharedState.AIDecision readDecision() {
        if (!connected) return null;
        return state.readDecision();
    }

    /**
     * Acknowledge that decision has been processed
     */
    public void acknowledgeDecision() {
        if (!connected) return;
        state.acknowledgeDecision();
        buffer.force();
    }

    /**
     * Check if market data is stale (> 1 second old)
     */
    public boolean isStale() {
        long lastTs = state.getTimestamp();
        if (lastTs == 0) return true;
        long elapsed = System.nanoTime() - lastTs;
        return elapsed > 1_000_000_000L;  // 1 second in nanoseconds
    }

    /**
     * Get last market data timestamp
     */
    public long getLastTimestamp() {
        return state.getTimestamp();
    }

    /**
     * Check if connected
     */
    public boolean isConnected() {
        return connected;
    }

    /**
     * Get the TradingSharedState instance
     */
    public TradingSharedState getState() {
        return state;
    }

    /**
     * Close the shared memory
     */
    @Override
    public void close() {
        if (!connected) return;

        connected = false;

        try {
            if (buffer != null) {
                buffer.force();
            }
            if (channel != null) {
                channel.close();
            }
            if (file != null) {
                file.close();
            }
            System.out.println("[SHM] Closed: " + path);
        } catch (IOException e) {
            System.err.println("[SHM] Close error: " + e.getMessage());
        }
    }
}
