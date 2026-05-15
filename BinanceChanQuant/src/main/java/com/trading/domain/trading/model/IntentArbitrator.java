package com.trading.domain.trading.model;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * Intent Arbitrator - Resolves multiple ExitIntents into single ExitDecision
 *
 * <p>Key principle: Prevents "Exit Storm" from multiple subsystems triggering
 * simultaneously. Only ONE exit decision is made per arbitration cycle.
 *
 * <p>Resolution rules:
 * 1. EMERGENCY > CRITICAL > HIGH > MEDIUM > LOW (urgency wins)
 * 2. Higher conviction intent wins at same urgency
 * 3. More recent intent wins at same priority
 * 4. HALT_ALL from any source immediately terminates
 */
public class IntentArbitrator {

    // Max intents to keep in history
    private static final int MAX_HISTORY = 20;

    private final List<ExitIntent> intentHistory = new ArrayList<>();
    private final long positionEntryTime;
    private final double maxHoldingTimeMinutes;

    public IntentArbitrator(long positionEntryTime, double maxHoldingTimeMinutes) {
        this.positionEntryTime = positionEntryTime;
        this.maxHoldingTimeMinutes = maxHoldingTimeMinutes;
    }

    /**
     * Resolve multiple intents into a single exit decision
     */
    public ExitDecision resolve(List<ExitIntent> intents) {
        if (intents == null || intents.isEmpty()) {
            return ExitDecision.hold("No exit intents");
        }

        // Sort by urgency then conviction
        List<ExitIntent> sorted = intents.stream()
            .sorted(Comparator
                .comparing((ExitIntent i) -> i.urgency().ordinal()).reversed()
                .thenComparing((ExitIntent i) -> i.confidence()).reversed()
                .thenComparing((ExitIntent i) -> i.timestamp()).reversed())
            .toList();

        ExitIntent primary = sorted.get(0);

        // Check for halt conditions first
        if (primary.isEmergency()) {
            return ExitDecision.haltAll("Emergency intent: " + primary.reason());
        }

        // Check for flatten conditions
        if (primary.urgency() == ExitIntent.Urgency.CRITICAL) {
            // If multiple critical intents, something is wrong - flatten anyway
            long criticalCount = intents.stream()
                .filter(i -> i.urgency() == ExitIntent.Urgency.CRITICAL)
                .count();

            if (criticalCount >= 2) {
                return ExitDecision.flattenNow(
                    "Multiple critical exits: " + criticalCount + " sources",
                    primary
                );
            }
            return ExitDecision.exitUrgent(primary.reason(), primary);
        }

        // HIGH urgency
        if (primary.urgency() == ExitIntent.Urgency.HIGH) {
            // If we have HIGH from multiple different sources, exit is warranted
            long highCount = intents.stream()
                .filter(i -> i.urgency() == ExitIntent.Urgency.HIGH)
                .count();

            if (highCount >= 2) {
                return ExitDecision.exitUrgent(
                    "Multiple high-urgency exits: " + highCount + " sources",
                    primary
                );
            }
            return ExitDecision.exitGracefully(primary.reason(), primary);
        }

        // MEDIUM urgency - reduce or exit depending on conviction
        if (primary.urgency() == ExitIntent.Urgency.MEDIUM) {
            if (primary.confidence() > 0.7) {
                return ExitDecision.exitGracefully(primary.reason(), primary);
            }
            return ExitDecision.reduce(0.6, "Medium urgency, moderate confidence", primary);
        }

        // LOW urgency - just reduce exposure
        return ExitDecision.reduce(0.5, primary.reason(), primary);
    }

    /**
     * Add intent to history (for tracking patterns)
     */
    public void addIntent(ExitIntent intent) {
        intentHistory.add(intent);
        if (intentHistory.size() > MAX_HISTORY) {
            intentHistory.remove(0);
        }
    }

    /**
     * Check if we have exit intents in recent history
     */
    public boolean hasRecentIntents(long windowMs) {
        long cutoff = System.currentTimeMillis() - windowMs;
        return intentHistory.stream()
            .anyMatch(i -> i.timestamp() > cutoff);
    }

    /**
     * Check if intents are escalating
     */
    public boolean isEscalating() {
        if (intentHistory.size() < 3) return false;

        // Look at last 3 intents
        List<ExitIntent> recent = intentHistory.subList(
            Math.max(0, intentHistory.size() - 3), intentHistory.size()
        );

        // Check if urgency is increasing
        int[] urgencyOrder = recent.stream()
            .mapToInt(i -> i.urgency().ordinal())
            .toArray();

        return urgencyOrder[2] > urgencyOrder[0];  // Third > First
    }

    /**
     * Get intent history
     */
    public List<ExitIntent> getHistory() {
        return new ArrayList<>(intentHistory);
    }

    /**
     * Create arbitrator for a new position
     */
    public static IntentArbitrator forPosition(PositionState position) {
        return new IntentArbitrator(
            position.getEntryTime(),
            30.0  // Default 30 min max hold
        );
    }
}