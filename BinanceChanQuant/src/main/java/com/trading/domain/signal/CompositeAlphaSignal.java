package com.trading.domain.signal;

import java.util.ArrayList;
import java.util.List;

/**
 * Composite Alpha Signal - multi-expert fused signal
 */
public class CompositeAlphaSignal extends AlphaSignal {

    private final List<AlphaSignal> componentSignals = new ArrayList<>();
    private AlphaSignal primarySignal;

    public List<AlphaSignal> getComponentSignals() { return componentSignals; }
    public AlphaSignal getPrimarySignal() { return primarySignal; }

    public void addComponentSignal(AlphaSignal signal) {
        if (signal != null) {
            componentSignals.add(signal);
            if (primarySignal == null || signal.getConfidence() > primarySignal.getConfidence()) {
                primarySignal = signal;
            }
        }
    }

    @Override
    public double calculateScore(MarketContext context) {
        if (componentSignals.isEmpty()) {
            return 0;
        }

        // Weighted average of component scores
        double totalScore = 0;
        double totalWeight = 0;

        for (AlphaSignal signal : componentSignals) {
            double weight = signal.getConfidence();
            totalScore += signal.getScore(context) * weight;
            totalWeight += weight;
        }

        if (totalWeight > 0) {
            return totalScore / totalWeight;
        }

        return 0;
    }

    @Override
    public String getContextKey() {
        return "COMPOSITE_" + direction.name() + "_" + componentSignals.size() + "c";
    }

    /**
     * Create composite from single signal
     */
    public static CompositeAlphaSignal fromSingle(AlphaSignal signal) {
        CompositeAlphaSignal composite = builder()
            .direction(signal.getDirection())
            .entryPrice(signal.getEntryPrice())
            .stopLossPrice(signal.getStopLossPrice())
            .takeProfitPrice(signal.getTakeProfitPrice())
            .confidence(signal.getConfidence())
            .urgency(signal.getUrgency())
            .horizonMinutes(signal.getHorizonMinutes())
            .expectedReturn(signal.getExpectedReturn())
            .expectedVolatility(signal.getExpectedVolatility())
            .source("Composite:" + signal.getSource())
            .build();

        composite.addComponentSignal(signal);
        composite.setType(AlphaType.COMPOSITE);
        return composite;
    }

    // Builder
    public static Builder builder() {
        return new Builder();
    }

    public static class Builder extends AlphaSignalBuilder<CompositeAlphaSignal, Builder> {
        public Builder() {
            signal = new CompositeAlphaSignal();
            initSignal(signal);
        }

        @Override
        public CompositeAlphaSignal build() {
            signal.type = AlphaType.COMPOSITE;
            return super.build();
        }
    }
}