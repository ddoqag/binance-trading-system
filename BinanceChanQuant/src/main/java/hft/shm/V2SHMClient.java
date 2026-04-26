package hft.shm;

import java.io.*;
import java.nio.MappedByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileChannel.MapMode;
import java.nio.ByteOrder;
import java.nio.ByteBuffer;

/**
 * V2SHMClient - V2 Shared Memory Client for HFT System
 *
 * Layout (1040 bytes total):
 *   Header       @ 0   size 16
 *   MarketState  @ 16  size 120
 *   PositionState@ 136 size 64
 *   RiskState    @ 200 size 48
 *   ExecutionState@248 size 64
 *   AIState      @ 312 size 40
 *   Total        = 1040 bytes
 *
 * This is the Python-side interface compatible version.
 * Java Engine writes GlobalState, Python reads and writes AIState.
 */
public class V2SHMClient implements AutoCloseable {
    private static final int GLOBAL_STATE_SIZE = 1040;
    private static final int CONTROL_PLANE_OFFSET = 1040;
    private static final int CONTROL_PLANE_SIZE = 192;
    private static final int SHM_TOTAL_SIZE = 1296;
    private static final int AI_OFFSET = 312;

    private final String shmPath;
    private RandomAccessFile file;
    private FileChannel channel;
    private MappedByteBuffer buffer;
    private boolean connected = false;

    public String getPath() { return shmPath; }

    public V2SHMClient(String path) throws IOException {
        this.shmPath = path;
        connect();
    }

    private void connect() throws IOException {
        // Ensure parent directory exists
        File parent = new File(shmPath).getParentFile();
        if (parent != null && !parent.exists()) {
            parent.mkdirs();
        }

        // Create or open file
        file = new RandomAccessFile(shmPath, "rw");

        // Auto-migrate from old 1040-byte file to 1296-byte
        if (file.length() < SHM_TOTAL_SIZE) {
            file.setLength(SHM_TOTAL_SIZE);
        }

        channel = file.getChannel();
        buffer = channel.map(MapMode.READ_WRITE, 0, SHM_TOTAL_SIZE);
        buffer.order(ByteOrder.LITTLE_ENDIAN);

        connected = true;
        System.out.println("[V2SHM] Connected: " + shmPath);
    }

    /**
     * Read GlobalState from shared memory
     */
    public GlobalState readGlobalState() {
        if (!connected) return null;

        buffer.position(0);
        ByteBuffer raw = buffer.slice();
        raw.order(ByteOrder.LITTLE_ENDIAN);

        GlobalState gs = new GlobalState();

        // Header: 16 bytes @ offset 0
        gs.timestamp = raw.getLong();
        gs.seq = raw.getLong();

        // MarketState: 120 bytes @ offset 16
        MarketState market = new MarketState();
        market.bestBid = raw.getDouble();
        market.bestAsk = raw.getDouble();
        market.lastPrice = raw.getDouble();
        market.microPrice = raw.getDouble();
        market.spread = raw.getDouble();
        market.ofiSignal = raw.getDouble();
        market.tradeImbalance = raw.getDouble();
        market.bidQueueRatio = raw.getDouble();
        market.askQueueRatio = raw.getDouble();
        market.volatilityEst = raw.getDouble();
        market.adverseScore = raw.getDouble();
        market.toxicProbability = raw.getDouble();
        market.tradeIntensity = raw.getDouble();
        gs.market = market;

        // PositionState: 64 bytes @ offset 136
        PositionState position = new PositionState();
        byte[] symbolBytes = new byte[16];
        raw.get(symbolBytes);
        position.symbol = new String(symbolBytes).trim();
        position.size = raw.getDouble();
        position.avgPrice = raw.getDouble();
        position.unrealizedPnl = raw.getDouble();
        position.realizedPnl = raw.getDouble();
        position.exposureRatio = raw.getDouble();
        gs.position = position;

        // RiskState: 48 bytes @ offset 200
        RiskState risk = new RiskState();
        risk.dailyPnl = raw.getDouble();
        risk.peakEquity = raw.getDouble();
        risk.currentEquity = raw.getDouble();
        risk.drawdown = raw.getDouble();
        risk.killSwitch = raw.get() != 0;
        raw.get(); raw.get(); raw.get(); // 3 bytes padding
        risk.ordersThisMin = raw.getInt();
        risk.maxOrdersPerMin = raw.getInt();
        gs.risk = risk;

        // ExecutionState: 64 bytes @ offset 248
        ExecutionState execution = new ExecutionState();
        execution.lastOrderId = raw.getLong();
        execution.pendingOrders = raw.getInt();
        execution.filledOrders = raw.getInt();
        execution.cancelledOrders = raw.getInt();
        raw.getInt(); raw.getInt(); // padding
        execution.lastFillPrice = raw.getDouble();
        execution.lastFillSize = raw.getDouble();
        execution.lastFillTime = raw.getLong();
        gs.execution = execution;

        // AIState: 40 bytes @ offset 312
        AIState ai = new AIState();
        ai.direction = raw.getDouble();
        ai.confidence = raw.getDouble();
        ai.urgency = raw.getDouble();
        ai.sizeScale = raw.getDouble();
        ai.lastUpdateTs = raw.getLong();
        gs.ai = ai;

        return gs;
    }

    /**
     * Write AIState to shared memory (offset 312)
     */
    public void writeAIState(AIState ai) {
        if (!connected) return;

        buffer.position(AI_OFFSET);
        buffer.putDouble(ai.direction);
        buffer.putDouble(ai.confidence);
        buffer.putDouble(ai.urgency);
        buffer.putDouble(ai.sizeScale);
        buffer.putLong(System.currentTimeMillis() * 1_000_000); // Unix nanoseconds

        buffer.force();
    }

    /**
     * Write MarketState to shared memory (offset 16, 120 bytes)
     * This allows JavaAIBrain to read market data that was written by HFTEngine
     */
    public void writeMarketState(double bestBid, double bestAsk, double lastPrice,
                                  double microPrice, double spread, double ofiSignal,
                                  double tradeImbalance, double bidQueueRatio,
                                  double askQueueRatio, double volatilityEst,
                                  double adverseScore, double toxicProbability,
                                  double tradeIntensity) {
        if (!connected) return;

        // Update header timestamp
        buffer.position(0);
        buffer.putLong(System.currentTimeMillis() * 1_000_000); // Unix nanoseconds
        buffer.putLong(buffer.getLong(8) + 1); // Increment seq

        // Write MarketState at offset 16
        buffer.position(16);
        buffer.putDouble(bestBid);
        buffer.putDouble(bestAsk);
        buffer.putDouble(lastPrice);
        buffer.putDouble(microPrice);
        buffer.putDouble(spread);
        buffer.putDouble(ofiSignal);
        buffer.putDouble(tradeImbalance);
        buffer.putDouble(bidQueueRatio);
        buffer.putDouble(askQueueRatio);
        buffer.putDouble(volatilityEst);
        buffer.putDouble(adverseScore);
        buffer.putDouble(toxicProbability);
        buffer.putDouble(tradeIntensity);
        // 16 bytes padding already zeroed

        buffer.force();
    }

    /**
     * Check if connected
     */
    public boolean isConnected() {
        return connected;
    }

    @Override
    public void close() {
        if (!connected) return;
        connected = false;

        try {
            buffer.force();
            channel.close();
            file.close();
            System.out.println("[V2SHM] Closed");
        } catch (IOException e) {
            System.err.println("[V2SHM] Close error: " + e.getMessage());
        }
    }

    /**
     * Global State - Complete market + position + risk state
     */
    public static class GlobalState {
        public long timestamp;
        public long seq;
        public MarketState market;
        public PositionState position;
        public RiskState risk;
        public ExecutionState execution;
        public AIState ai;
    }

    /**
     * Market State - 120 bytes
     */
    public static class MarketState {
        public double bestBid;
        public double bestAsk;
        public double lastPrice;
        public double microPrice;
        public double spread;
        public double ofiSignal;
        public double tradeImbalance;
        public double bidQueueRatio;
        public double askQueueRatio;
        public double volatilityEst;
        public double adverseScore;
        public double toxicProbability;
        public double tradeIntensity;
    }

    /**
     * Position State - 64 bytes
     */
    public static class PositionState {
        public String symbol;
        public double size;
        public double avgPrice;
        public double unrealizedPnl;
        public double realizedPnl;
        public double exposureRatio;
    }

    /**
     * Risk State - 48 bytes
     */
    public static class RiskState {
        public double dailyPnl;
        public double peakEquity;
        public double currentEquity;
        public double drawdown;
        public boolean killSwitch;
        public int ordersThisMin;
        public int maxOrdersPerMin;
    }

    /**
     * Execution State - 64 bytes
     */
    public static class ExecutionState {
        public long lastOrderId;
        public int pendingOrders;
        public int filledOrders;
        public int cancelledOrders;
        public double lastFillPrice;
        public double lastFillSize;
        public long lastFillTime;
    }

    /**
     * AI State - 40 bytes @ offset 312 (Python writes this)
     */
    public static class AIState {
        public double direction;   // -1.0=sell, +1.0=buy, 0.0=hold
        public double confidence;  // 0.0~1.0
        public double urgency;    // 0.0=passive, 1.0=aggressive
        public double sizeScale;  // 0.0~2.0
        public long lastUpdateTs; // Unix nanoseconds
    }
}
