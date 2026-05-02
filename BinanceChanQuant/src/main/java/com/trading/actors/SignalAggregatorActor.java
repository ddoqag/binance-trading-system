package com.trading.actors;

import com.trading.domain.signal.AlphaType;
import com.trading.domain.signal.CompositeSignal;
import com.trading.domain.signal.MarketContext;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.messaging.*;
import com.trading.messaging.messages.PriceUpdatedEvent;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicReference;
import java.util.stream.Collectors;

/**
 * Signal Aggregator Actor - combines signals from multiple experts.
 * Replaces AlphaPool with message-driven architecture.
 */
public class SignalAggregatorActor extends Actor {

    // Registered experts
    private final Map<String, SignalExpert> experts = new ConcurrentHashMap<>();

    // Signal history for conflict resolution
    private final Queue<SignalRecord> signalHistory = new LinkedList<>();
    private static final int HISTORY_SIZE = 100;

    // Current market context
    private final AtomicReference<MarketContext> context = new AtomicReference<>();

    // Weights from MetaLearner
    private final AtomicReference<Map<AlphaType, Double>> weights = new AtomicReference<>(
        Map.of(
            AlphaType.MEAN_REVERSION, 0.333,
            AlphaType.TREND_FOLLOWING, 0.333,
            AlphaType.VOLATILITY, 0.334
        )
    );

    public SignalAggregatorActor() {
        super("SignalAggregatorActor");
    }

    @Override
    public void receive(Command command) {
        // Commands handled if needed
    }

    @Override
    public void receive(DomainEvent event) {
        if (event instanceof PriceUpdatedEvent) {
            handlePriceUpdate((PriceUpdatedEvent) event);
        }
    }

    /**
     * Register an expert that generates signals.
     */
    public void registerExpert(String id, SignalExpert expert) {
        experts.put(id, expert);
    }

    /**
     * Unregister an expert.
     */
    public void unregisterExpert(String id) {
        experts.remove(id);
    }

    /**
     * Update weights from MetaLearner.
     */
    public void updateWeights(Map<AlphaType, Double> newWeights) {
        weights.set(newWeights);
    }

    /**
     * Update market context.
     */
    public void updateContext(MarketContext ctx) {
        context.set(ctx);
    }

    /**
     * Generate composite signal from all experts.
     */
    public CompositeSignal generateCompositeSignal() {
        MarketContext ctx = context.get();
        if (ctx == null) {
            ctx = new MarketContext();
        }

        // Collect signals from all experts
        List<ExpertSignal> expertSignals = new ArrayList<>();
        for (Map.Entry<String, SignalExpert> entry : experts.entrySet()) {
            SignalExpert.ExpertSignal signal = entry.getValue().generate(ctx);
            if (signal != null && signal.confidence > 0) {
                expertSignals.add(new ExpertSignal(entry.getKey(), signal.type, signal.direction, signal.confidence));
            }
        }

        if (expertSignals.isEmpty()) {
            return createNeutralSignal(ctx);
        }

        // Weighted combination
        Map<AlphaType, Double> w = weights.get();
        double totalWeight = 0;
        double weightedDirection = 0;
        double weightedConfidence = 0;

        for (ExpertSignal es : expertSignals) {
            Double weight = w.get(es.type);
            if (weight == null) weight = 0.333;
            totalWeight += weight;

            int dirValue = es.direction == TradeDirection.LONG ? 1 : (es.direction == TradeDirection.SHORT ? -1 : 0);
            weightedDirection += weight * dirValue;
            weightedConfidence += weight * es.confidence;
        }

        // Normalize
        if (totalWeight > 0) {
            weightedDirection /= totalWeight;
            weightedConfidence /= totalWeight;
        }

        // Determine direction
        TradeDirection direction;
        if (weightedDirection > 0.3) {
            direction = TradeDirection.LONG;
        } else if (weightedDirection < -0.3) {
            direction = TradeDirection.SHORT;
        } else {
            direction = TradeDirection.NEUTRAL;
        }

        // Add to history
        signalHistory.offer(new SignalRecord(direction, weightedConfidence, System.currentTimeMillis()));
        while (signalHistory.size() > HISTORY_SIZE) {
            signalHistory.poll();
        }

        // Calculate confidence based on agreement
        double agreement = calculateAgreement(expertSignals);
        double finalConfidence = weightedConfidence * agreement;

        // Build composite signal using existing CompositeSignal class
        CompositeSignal signal = new CompositeSignal();
        CompositeSignal.Direction dir = direction == TradeDirection.LONG ? CompositeSignal.Direction.LONG
            : (direction == TradeDirection.SHORT ? CompositeSignal.Direction.SHORT : CompositeSignal.Direction.NEUTRAL);
        signal.setDirection(dir);
        signal.setConfidence(finalConfidence);
        signal.setPrice(ctx.getCurrentPrice());
        signal.setSource("aggregator");

        return signal;
    }

    private CompositeSignal createNeutralSignal(MarketContext ctx) {
        CompositeSignal signal = new CompositeSignal();
        signal.setDirection(CompositeSignal.Direction.NEUTRAL);
        signal.setConfidence(0.0);
        signal.setPrice(ctx != null ? ctx.getCurrentPrice() : 0.0);
        signal.setSource("aggregator");
        return signal;
    }

    private void handlePriceUpdate(PriceUpdatedEvent price) {
        MarketContext ctx = context.get();
        if (ctx != null) {
            ctx.setCurrentPrice(price.lastPrice());
            ctx.setTimestamp(System.currentTimeMillis());
        }
    }

    private double calculateAgreement(List<ExpertSignal> signals) {
        if (signals.size() <= 1) return 1.0;

        int longCount = 0;
        int shortCount = 0;
        for (ExpertSignal s : signals) {
            if (s.direction == TradeDirection.LONG) longCount++;
            else if (s.direction == TradeDirection.SHORT) shortCount++;
        }

        int maxAgree = Math.max(longCount, shortCount);
        return (double) maxAgree / signals.size();
    }

    // Expert signal record
    private static class ExpertSignal {
        final String expertId;
        final AlphaType type;
        final TradeDirection direction;
        final double confidence;

        ExpertSignal(String expertId, AlphaType type, TradeDirection direction, double confidence) {
            this.expertId = expertId;
            this.type = type;
            this.direction = direction;
            this.confidence = confidence;
        }
    }

    // Signal history record
    private static class SignalRecord {
        final TradeDirection direction;
        final double confidence;
        final long timestamp;

        SignalRecord(TradeDirection direction, double confidence, long timestamp) {
            this.direction = direction;
            this.confidence = confidence;
            this.timestamp = timestamp;
        }
    }

    /**
     * Interface for signal experts.
     */
    public interface SignalExpert {
        ExpertSignal generate(MarketContext context);

        class ExpertSignal {
            public final AlphaType type;
            public final TradeDirection direction;
            public final double confidence;

            public ExpertSignal(AlphaType type, TradeDirection direction, double confidence) {
                this.type = type;
                this.direction = direction;
                this.confidence = confidence;
            }
        }
    }
}