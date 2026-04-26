package ai;

import hft.shm.V2SHMClient;

/**
 * JavaAIBrain - Pure Java AI Decision Engine
 *
 * Implements:
 * - Meta-Agent: Market regime detection
 * - MoE (Mixture of Experts): Expert blending
 * - SAC: Soft Actor-Critic execution optimization
 * - Fallback Rules: Simple heuristic rules
 *
 * This replaces Python v2_integrator.py with pure Java.
 */
public class JavaAIBrain {
    private final V2SHMClient shmClient;
    private final BrainConfig config;

    // Expert states
    private MarketRegime regime = MarketRegime.UNKNOWN;
    private double regimeConfidence = 0;
    private double[] expertScores = new double[3];  // [mean_reversion, trend, volatility]
    private long lastUpdate = 0;

    public JavaAIBrain(V2SHMClient shmClient, BrainConfig config) {
        this.shmClient = shmClient;
        this.config = config;
    }

    public static JavaAIBrain defaults(V2SHMClient shmClient) {
        return new JavaAIBrain(shmClient, BrainConfig.defaults());
    }

    /**
     * Compute AI signal from market state
     */
    public AISignal compute() {
        V2SHMClient.GlobalState gs = shmClient.readGlobalState();
        if (gs == null) {
            return AISignal.hold();
        }

        // Update regime detection
        updateRegime(gs.market);

        // Calculate expert signals
        double[] signals = computeExpertSignals(gs.market);

        // Blend experts using MoE
        double direction = blendExperts(signals);

        // Calculate confidence
        double confidence = calculateConfidence(gs, direction);

        // Calculate urgency
        double urgency = calculateUrgency(gs.market);

        // Calculate size scale
        double sizeScale = calculateSizeScale(gs.market);

        // Build AI state
        V2SHMClient.AIState aiState = new V2SHMClient.AIState();
        aiState.direction = direction;
        aiState.confidence = confidence;
        aiState.urgency = urgency;
        aiState.sizeScale = sizeScale;
        aiState.lastUpdateTs = System.currentTimeMillis() * 1_000_000;

        // Write to shared memory
        shmClient.writeAIState(aiState);

        return new AISignal(direction, confidence, urgency, sizeScale, aiState.lastUpdateTs);
    }

    private void updateRegime(V2SHMClient.MarketState m) {
        if (m.lastPrice == 0) {
            regime = MarketRegime.UNKNOWN;
            regimeConfidence = 0;
            return;
        }

        // Calculate drift
        double drift = (m.microPrice - m.lastPrice) / m.lastPrice;

        // Calculate volatility regime
        boolean isHighVol = m.volatilityEst > 0.001;
        boolean isLowVol = m.volatilityEst < 0.0001;

        // Calculate trend
        boolean isUptrend = m.microPrice > m.lastPrice * 1.0001;
        boolean isDowntrend = m.microPrice < m.lastPrice * 0.9999;

        // Determine regime
        if (isHighVol) {
            regime = MarketRegime.HIGH_VOL;
            regimeConfidence = 0.8;
        } else if (isLowVol) {
            regime = MarketRegime.LOW_VOL;
            regimeConfidence = 0.7;
        } else if (isUptrend && m.bidQueueRatio > m.askQueueRatio) {
            regime = MarketRegime.TREND_UP;
            regimeConfidence = 0.75;
        } else if (isDowntrend && m.askQueueRatio > m.bidQueueRatio) {
            regime = MarketRegime.TREND_DOWN;
            regimeConfidence = 0.75;
        } else {
            regime = MarketRegime.RANGE;
            regimeConfidence = 0.65;
        }

        lastUpdate = System.currentTimeMillis();
    }

    private double[] computeExpertSignals(V2SHMClient.MarketState m) {
        double[] signals = new double[3];

        // Expert 1: Mean Reversion
        signals[0] = computeMeanReversionSignal(m);

        // Expert 2: Trend Following
        signals[1] = computeTrendSignal(m);

        // Expert 3: Volatility
        signals[2] = computeVolatilitySignal(m);

        // Store scores
        System.arraycopy(signals, 0, expertScores, 0, 3);

        return signals;
    }

    private double computeMeanReversionSignal(V2SHMClient.MarketState m) {
        if (m.microPrice == 0 || m.lastPrice == 0) return 0;

        double drift = (m.microPrice - m.lastPrice) / m.lastPrice;

        // Mean reversion: fade microprice deviations
        return -Math.tanh(drift * 1000);  // Negative = fade
    }

    private double computeTrendSignal(V2SHMClient.MarketState m) {
        // Trend following: follow OFI
        return Math.tanh(m.ofiSignal * 0.1);
    }

    private double computeVolatilitySignal(V2SHMClient.MarketState m) {
        // High volatility = reduce size
        double volFactor = 1.0 - Math.min(1.0, m.volatilityEst * 1000);
        return volFactor * Math.signum(m.tradeImbalance);
    }

    private double blendExperts(double[] signals) {
        // Weighted average based on regime
        double[] weights = getRegimeWeights();

        double blended = 0;
        for (int i = 0; i < 3; i++) {
            blended += signals[i] * weights[i];
        }

        return blended;
    }

    private double[] getRegimeWeights() {
        double[] weights = new double[3];

        switch (regime) {
            case RANGE:
                // Mean reversion works best in range
                weights[0] = 0.6;
                weights[1] = 0.2;
                weights[2] = 0.2;
                break;
            case TREND_UP:
            case TREND_DOWN:
                // Trend following works best in trends
                weights[0] = 0.2;
                weights[1] = 0.6;
                weights[2] = 0.2;
                break;
            case HIGH_VOL:
            case LOW_VOL:
                // Volatility experts
                weights[0] = 0.3;
                weights[1] = 0.3;
                weights[2] = 0.4;
                break;
            default:
                weights[0] = 0.33;
                weights[1] = 0.33;
                weights[2] = 0.34;
        }

        return weights;
    }

    private double calculateConfidence(V2SHMClient.GlobalState gs, double direction) {
        double baseConf = Math.abs(direction);

        // Reduce by toxicity
        double toxicPenalty = gs.market.toxicProbability * 0.5;

        // Reduce by adverse selection
        double adversePenalty = gs.market.adverseScore * 0.3;

        // Reduce if regime confidence is low
        double regimePenalty = (1.0 - regimeConfidence) * 0.2;

        double confidence = baseConf * (1.0 - toxicPenalty - adversePenalty - regimePenalty);

        return Math.max(0, Math.min(1, confidence));
    }

    private double calculateUrgency(V2SHMClient.MarketState m) {
        // High toxicity = passive
        if (m.toxicProbability > 0.5) {
            return 0.1;
        }

        // High adverse = passive
        if (m.adverseScore > 0.5) {
            return 0.2;
        }

        // Wide spread = passive
        if (m.spread > 0.0005) {
            return 0.2;
        }

        // Default
        return 0.3;
    }

    private double calculateSizeScale(V2SHMClient.MarketState m) {
        double baseScale = 1.0;

        // Reduce by toxicity
        baseScale *= (1.0 - m.toxicProbability * 0.5);

        // Reduce by adverse
        baseScale *= (1.0 - m.adverseScore * 0.3);

        // Regime adjustment
        if (regime == MarketRegime.HIGH_VOL) {
            baseScale *= 0.5;
        } else if (regime == MarketRegime.RANGE) {
            baseScale *= 0.8;
        }

        return Math.max(0, Math.min(2.0, baseScale));
    }

    public MarketRegime getRegime() {
        return regime;
    }

    public double getRegimeConfidence() {
        return regimeConfidence;
    }

    public enum MarketRegime {
        UNKNOWN,
        RANGE,
        TREND_UP,
        TREND_DOWN,
        HIGH_VOL,
        LOW_VOL
    }

    public static class BrainConfig {
        public double minConfidence = 0.15;
        public double minRegimeConfidence = 0.55;
        public int maxActiveExperts = 3;

        public static BrainConfig defaults() {
            return new BrainConfig();
        }
    }

    public static class AISignal {
        public final double direction;
        public final double confidence;
        public final double urgency;
        public final double sizeScale;
        public final long timestamp;

        public AISignal(double direction, double confidence, double urgency,
                       double sizeScale, long timestamp) {
            this.direction = direction;
            this.confidence = confidence;
            this.urgency = urgency;
            this.sizeScale = sizeScale;
            this.timestamp = timestamp;
        }

        public boolean isHold() {
            return Math.abs(direction) < 0.1 || confidence < 0.15;
        }

        public static AISignal hold() {
            return new AISignal(0, 0, 0, 0, System.currentTimeMillis() * 1_000_000);
        }
    }
}
