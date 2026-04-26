package com.trading.infrastructure.messaging.shm;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/**
 * SHM Layout Definition - Single Source of Truth for Shared Memory Structure
 * Shared memory is used for communication between Java HFT Engine and Python AI Brain
 */
public class SHMLayout {

    // Total shared memory size
    public static final int TOTAL_SIZE = 1296;

    // Region offsets
    public static final int HEADER_OFFSET = 0;      // 16 bytes
    public static final int MARKET_OFFSET = 16;       // 120 bytes
    public static final int POSITION_OFFSET = 136;    // 64 bytes
    public static final int RISK_OFFSET = 200;       // 48 bytes
    public static final int EXEC_OFFSET = 248;       // 64 bytes
    public static final int AI_OFFSET = 312;         // 40 bytes
    public static final int CONTROL_OFFSET = 1040;    // 192 bytes

    // Header structure (16 bytes)
    public static class Header {
        public long timestamp;   // Unix nanoseconds
        public long seq;        // Sequence number

        public void writeTo(ByteBuffer buffer) {
            buffer.putLong(timestamp);
            buffer.putLong(seq);
        }

        public void readFrom(ByteBuffer buffer) {
            timestamp = buffer.getLong();
            seq = buffer.getLong();
        }
    }

    // Market data structure (120 bytes @ MARKET_OFFSET)
    public static class MarketData {
        public double bestBid;
        public double bestAsk;
        public double lastPrice;
        public double microPrice;
        public double spread;
        public double ofiSignal;         // Order Flow Imbalance
        public double tradeImbalance;
        public double bidQueueRatio;
        public double askQueueRatio;
        public double volatilityEst;       // Volatility estimate
        public double adverseScore;       // Adverse selection score
        public double toxicProbability;   // Probability of toxicity
        public double tradeIntensity;     // Trade intensity

        public void writeTo(ByteBuffer buffer) {
            buffer.position(MARKET_OFFSET);
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
        }

        public void readFrom(ByteBuffer buffer) {
            buffer.position(MARKET_OFFSET);
            bestBid = buffer.getDouble();
            bestAsk = buffer.getDouble();
            lastPrice = buffer.getDouble();
            microPrice = buffer.getDouble();
            spread = buffer.getDouble();
            ofiSignal = buffer.getDouble();
            tradeImbalance = buffer.getDouble();
            bidQueueRatio = buffer.getDouble();
            askQueueRatio = buffer.getDouble();
            volatilityEst = buffer.getDouble();
            adverseScore = buffer.getDouble();
            toxicProbability = buffer.getDouble();
            tradeIntensity = buffer.getDouble();
        }
    }

    // Position data structure (64 bytes @ POSITION_OFFSET)
    public static class PositionData {
        public String symbol;          // 16 bytes
        public double size;
        public double avgPrice;
        public double unrealizedPnl;
        public double realizedPnl;
        public double exposureRatio;

        public void writeTo(ByteBuffer buffer) {
            buffer.position(POSITION_OFFSET);
            byte[] symbolBytes = new byte[16];
            byte[] src = symbol.getBytes();
            System.arraycopy(src, 0, symbolBytes, 0, Math.min(src.length, 16));
            buffer.put(symbolBytes);
            buffer.putDouble(size);
            buffer.putDouble(avgPrice);
            buffer.putDouble(unrealizedPnl);
            buffer.putDouble(realizedPnl);
            buffer.putDouble(exposureRatio);
        }

        public void readFrom(ByteBuffer buffer) {
            buffer.position(POSITION_OFFSET);
            byte[] symbolBytes = new byte[16];
            buffer.get(symbolBytes);
            symbol = new String(symbolBytes).trim();
            size = buffer.getDouble();
            avgPrice = buffer.getDouble();
            unrealizedPnl = buffer.getDouble();
            realizedPnl = buffer.getDouble();
            exposureRatio = buffer.getDouble();
        }
    }

    // Risk data structure (48 bytes @ RISK_OFFSET)
    public static class RiskData {
        public double dailyPnl;
        public double peakEquity;
        public double currentEquity;
        public double drawdown;
        public boolean killSwitch;
        public int ordersThisMin;
        public int maxOrdersPerMin;

        public void writeTo(ByteBuffer buffer) {
            buffer.position(RISK_OFFSET);
            buffer.putDouble(dailyPnl);
            buffer.putDouble(peakEquity);
            buffer.putDouble(currentEquity);
            buffer.putDouble(drawdown);
            buffer.put(killSwitch ? (byte) 1 : (byte) 0);
            buffer.position(buffer.position() + 3); // padding
            buffer.putInt(ordersThisMin);
            buffer.putInt(maxOrdersPerMin);
        }

        public void readFrom(ByteBuffer buffer) {
            buffer.position(RISK_OFFSET);
            dailyPnl = buffer.getDouble();
            peakEquity = buffer.getDouble();
            currentEquity = buffer.getDouble();
            drawdown = buffer.getDouble();
            killSwitch = buffer.get() != 0;
            buffer.position(buffer.position() + 3); // padding
            ordersThisMin = buffer.getInt();
            maxOrdersPerMin = buffer.getInt();
        }
    }

    // Execution data structure (64 bytes @ EXEC_OFFSET)
    public static class ExecutionData {
        public long lastOrderId;
        public int pendingOrders;
        public int filledOrders;
        public int cancelledOrders;
        public double lastFillPrice;
        public double lastFillSize;
        public long lastFillTime;

        public void writeTo(ByteBuffer buffer) {
            buffer.position(EXEC_OFFSET);
            buffer.putLong(lastOrderId);
            buffer.putInt(pendingOrders);
            buffer.putInt(filledOrders);
            buffer.putInt(cancelledOrders);
            buffer.position(buffer.position() + 8); // padding
            buffer.putDouble(lastFillPrice);
            buffer.putDouble(lastFillSize);
            buffer.putLong(lastFillTime);
        }

        public void readFrom(ByteBuffer buffer) {
            buffer.position(EXEC_OFFSET);
            lastOrderId = buffer.getLong();
            pendingOrders = buffer.getInt();
            filledOrders = buffer.getInt();
            cancelledOrders = buffer.getInt();
            buffer.position(buffer.position() + 8); // padding
            lastFillPrice = buffer.getDouble();
            lastFillSize = buffer.getDouble();
            lastFillTime = buffer.getLong();
        }
    }

    // AI data structure (40 bytes @ AI_OFFSET)
    public static class AIData {
        public double direction;     // -1.0 to 1.0 (sell to buy)
        public double confidence;   // 0.0 to 1.0
        public double urgency;      // 0.0 to 1.0
        public double sizeScale;    // 0.0 to 2.0
        public long lastUpdateTs;   // Unix nanoseconds

        public void writeTo(ByteBuffer buffer) {
            buffer.position(AI_OFFSET);
            buffer.putDouble(direction);
            buffer.putDouble(confidence);
            buffer.putDouble(urgency);
            buffer.putDouble(sizeScale);
            buffer.putLong(lastUpdateTs);
        }

        public void readFrom(ByteBuffer buffer) {
            buffer.position(AI_OFFSET);
            direction = buffer.getDouble();
            confidence = buffer.getDouble();
            urgency = buffer.getDouble();
            sizeScale = buffer.getDouble();
            lastUpdateTs = buffer.getLong();
        }
    }

    // Control plane structure (192 bytes @ CONTROL_OFFSET)
    public static class ControlData {
        public int killSwitch;        // 0: normal, 1: kill
        public int executionMode;     // 0: passive, 1: smart, 2: aggressive, 3: kill
        public int riskLevel;         // 0: low, 1: medium, 2: high
        public int metaLearningEnabled;
        public double[] strategyWeights = new double[3]; // [trend, mean_reversion, volatility]

        public void writeTo(ByteBuffer buffer) {
            buffer.position(CONTROL_OFFSET);
            buffer.putInt(killSwitch);
            buffer.putInt(executionMode);
            buffer.putInt(riskLevel);
            buffer.putInt(metaLearningEnabled);
            for (double w : strategyWeights) {
                buffer.putDouble(w);
            }
        }

        public void readFrom(ByteBuffer buffer) {
            buffer.position(CONTROL_OFFSET);
            killSwitch = buffer.getInt();
            executionMode = buffer.getInt();
            riskLevel = buffer.getInt();
            metaLearningEnabled = buffer.getInt();
            for (int i = 0; i < 3; i++) {
                strategyWeights[i] = buffer.getDouble();
            }
        }
    }

    // Validation utility
    public static void validateBuffer(ByteBuffer buffer) {
        if (buffer.capacity() < TOTAL_SIZE) {
            throw new IllegalArgumentException(
                "Buffer too small: " + buffer.capacity() + " < " + TOTAL_SIZE);
        }
    }

    // Force write to ensure durability (only works on MappedByteBuffer)
    public static void forceFlush(ByteBuffer buffer) {
        if (buffer instanceof java.nio.MappedByteBuffer) {
            ((java.nio.MappedByteBuffer) buffer).force();
        }
    }
}
