package hft.shm;

import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReferenceArray;

/**
 * TradingSharedState - Shared Memory Structure for HFT System
 *
 * Layout (144 bytes total):
 * - Cache Line 0: Market Data (Written by Java Engine) - 64 bytes
 * - Cache Line 1: AI Decision (Written by Python/AI, Read by Java) - 64 bytes
 * - Padding: 16 bytes
 *
 * Matches Go's TradingSharedState in shm_manager.go
 */
public class TradingSharedState {
    // Cache Line 0: Market Data (64 bytes)
    private final AtomicLong seq = new AtomicLong(0);
    private final AtomicLong seqEnd = new AtomicLong(0);
    private volatile long timestamp;  // Unix nanoseconds
    private volatile double bestBid;
    private volatile double bestAsk;
    private volatile double microPrice;
    private volatile double ofiSignal;
    private volatile float tradeImbalance;
    private volatile float bidQueuePos;
    private volatile float askQueuePos;

    // Cache Line 1: AI Decision (64 bytes)
    private final AtomicLong decisionSeq = new AtomicLong(0);
    private final AtomicLong decisionAck = new AtomicLong(0);
    private volatile long decisionTime;
    private volatile double targetPosition;
    private volatile double targetSize;
    private volatile double limitPrice;
    private volatile float confidence;
    private volatile float volForecast;
    private volatile int action;
    private volatile int regime;

    // Sequence lock helpers
    public long incrementSeq() {
        return seq.incrementAndGet();
    }

    public void commitSeq(long seqValue) {
        seqEnd.set(seqValue);
    }

    public boolean isSeqConsistent() {
        return seq.get() == seqEnd.get();
    }

    public long getSeq() {
        return seq.get();
    }

    public long getTimestamp() {
        return timestamp;
    }

    public void setTimestamp(long timestamp) {
        this.timestamp = timestamp;
    }

    public double getBestBid() {
        return bestBid;
    }

    public void setBestBid(double bestBid) {
        this.bestBid = bestBid;
    }

    public double getBestAsk() {
        return bestAsk;
    }

    public void setBestAsk(double bestAsk) {
        this.bestAsk = bestAsk;
    }

    public double getMicroPrice() {
        return microPrice;
    }

    public void setMicroPrice(double microPrice) {
        this.microPrice = microPrice;
    }

    public double getOfiSignal() {
        return ofiSignal;
    }

    public void setOfiSignal(double ofiSignal) {
        this.ofiSignal = ofiSignal;
    }

    public float getTradeImbalance() {
        return tradeImbalance;
    }

    public void setTradeImbalance(float tradeImbalance) {
        this.tradeImbalance = tradeImbalance;
    }

    public float getBidQueuePos() {
        return bidQueuePos;
    }

    public void setBidQueuePos(float bidQueuePos) {
        this.bidQueuePos = bidQueuePos;
    }

    public float getAskQueuePos() {
        return askQueuePos;
    }

    public void setAskQueuePos(float askQueuePos) {
        this.askQueuePos = askQueuePos;
    }

    public long getDecisionSeq() {
        return decisionSeq.get();
    }

    public long getDecisionAck() {
        return decisionAck.get();
    }

    public boolean hasNewDecision() {
        return decisionSeq.get() > 0 && decisionSeq.get() != decisionAck.get();
    }

    public void acknowledgeDecision() {
        decisionAck.set(decisionSeq.get());
    }

    public void setDecisionSeq(long seq) {
        decisionSeq.set(seq);
    }

    public long getDecisionTime() {
        return decisionTime;
    }

    public void setDecisionTime(long decisionTime) {
        this.decisionTime = decisionTime;
    }

    public double getTargetPosition() {
        return targetPosition;
    }

    public void setTargetPosition(double targetPosition) {
        this.targetPosition = targetPosition;
    }

    public double getTargetSize() {
        return targetSize;
    }

    public void setTargetSize(double targetSize) {
        this.targetSize = targetSize;
    }

    public double getLimitPrice() {
        return limitPrice;
    }

    public void setLimitPrice(double limitPrice) {
        this.limitPrice = limitPrice;
    }

    public float getConfidence() {
        return confidence;
    }

    public void setConfidence(float confidence) {
        this.confidence = confidence;
    }

    public float getVolForecast() {
        return volForecast;
    }

    public void setVolForecast(float volForecast) {
        this.volForecast = volForecast;
    }

    public int getAction() {
        return action;
    }

    public void setAction(int action) {
        this.action = action;
    }

    public int getRegime() {
        return regime;
    }

    public void setRegime(int regime) {
        this.regime = regime;
    }

    /**
     * Read decision from shared memory with validation
     */
    public AIDecision readDecision() {
        long seq = decisionSeq.get();
        long ack = decisionAck.get();

        if (seq == 0 || seq == ack) {
            return null;  // No new decision
        }

        AIDecision decision = new AIDecision();
        decision.action = this.action;
        decision.targetPosition = this.targetPosition;
        decision.targetSize = this.targetSize;
        decision.limitPrice = this.limitPrice;
        decision.confidence = this.confidence;
        decision.regime = this.regime;
        decision.volForecast = this.volForecast;

        // Re-check sequence for consistency
        if (decisionSeq.get() != seq) {
            return null;
        }

        return decision;
    }

    /**
     * AI Decision data class
     */
    public static class AIDecision {
        public int action;
        public double targetPosition;
        public double targetSize;
        public double limitPrice;
        public float confidence;
        public int regime;
        public float volForecast;
    }

    /**
     * Trading action constants
     */
    public static final int ACTION_WAIT = 0;
    public static final int ACTION_JOIN_BID = 1;
    public static final int ACTION_JOIN_ASK = 2;
    public static final int ACTION_CROSS_BUY = 3;
    public static final int ACTION_CROSS_SELL = 4;
    public static final int ACTION_CANCEL = 5;
    public static final int ACTION_PARTIAL_EXIT = 6;

    /**
     * Market regime constants
     */
    public static final int REGIME_UNKNOWN = 0;
    public static final int REGIME_TREND_UP = 1;
    public static final int REGIME_TREND_DOWN = 2;
    public static final int REGIME_RANGE = 3;
    public static final int REGIME_HIGH_VOL = 4;
    public static final int REGIME_LOW_VOL = 5;
}
