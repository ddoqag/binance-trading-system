package hft.defense;

/**
 * DefenseFSM - Defense Finite State Machine
 *
 * Protects against toxic flow and adverse selection.
 *
 * States:
 * - NORMAL: Normal trading
 * - GUARDED: Elevated caution
 * - DEFENSIVE: Reducing exposure
 * - PROTECTIVE: All positions closing
 * - KILL: Emergency stop
 */
public class DefenseFSM {
    public enum State {
        NORMAL,
        GUARDED,
        DEFENSIVE,
        PROTECTIVE,
        KILL
    }

    private volatile State currentState = State.NORMAL;
    private volatile long lastStateChange = System.currentTimeMillis();
    private volatile int consecutiveLosses = 0;
    private volatile double toxicityScore = 0;

    private final int maxConsecutiveLosses;
    private final double toxicityThreshold;

    public DefenseFSM(int maxConsecutiveLosses, double toxicityThreshold) {
        this.maxConsecutiveLosses = maxConsecutiveLosses;
        this.toxicityThreshold = toxicityThreshold;
    }

    public static DefenseFSM defaults() {
        return new DefenseFSM(3, 0.7);
    }

    /**
     * Update state based on market conditions
     */
    public void update(double toxicityScore, int consecutiveLosses, boolean hasPosition) {
        this.toxicityScore = toxicityScore;
        this.consecutiveLosses = consecutiveLosses;

        State newState = calculateNextState(hasPosition);
        if (newState != currentState) {
            transitionTo(newState);
        }
    }

    private State calculateNextState(boolean hasPosition) {
        // Kill switch conditions
        if (consecutiveLosses >= maxConsecutiveLosses) {
            return State.KILL;
        }

        // Protective: close all positions
        if (toxicityScore > toxicityThreshold * 1.5) {
            return State.PROTECTIVE;
        }

        // Defensive: reduce exposure
        if (toxicityScore > toxicityThreshold) {
            return hasPosition ? State.DEFENSIVE : State.GUARDED;
        }

        // Guarded: elevated caution
        if (toxicityScore > toxicityThreshold * 0.5 || consecutiveLosses > 0) {
            return State.GUARDED;
        }

        return State.NORMAL;
    }

    private void transitionTo(State newState) {
        long now = System.currentTimeMillis();
        long duration = now - lastStateChange;

        System.out.printf("[DEFENSE] State: %s -> %s (duration: %dms)%n",
            currentState, newState, duration);

        currentState = newState;
        lastStateChange = now;
    }

    /**
     * Check if new orders are allowed
     */
    public boolean allowNewOrders() {
        return currentState == State.NORMAL || currentState == State.GUARDED;
    }

    /**
     * Check if position increase is allowed
     */
    public boolean allowPositionIncrease() {
        return currentState == State.NORMAL;
    }

    /**
     * Check if we should close positions
     */
    public boolean shouldClosePositions() {
        return currentState == State.PROTECTIVE || currentState == State.KILL;
    }

    /**
     * Check if we should reduce positions
     */
    public boolean shouldReducePositions() {
        return currentState == State.DEFENSIVE ||
               currentState == State.PROTECTIVE ||
               currentState == State.KILL;
    }

    /**
     * Get position scale factor based on state
     */
    public double getPositionScale() {
        switch (currentState) {
            case NORMAL: return 1.0;
            case GUARDED: return 0.7;
            case DEFENSIVE: return 0.3;
            case PROTECTIVE: return 0.0;
            case KILL: return 0.0;
            default: return 0.0;
        }
    }

    public State getCurrentState() {
        return currentState;
    }

    public long getLastStateChange() {
        return lastStateChange;
    }

    public int getConsecutiveLosses() {
        return consecutiveLosses;
    }

    public double getToxicityScore() {
        return toxicityScore;
    }

    /**
     * Record a winning trade
     */
    public void recordWin() {
        consecutiveLosses = 0;
    }

    /**
     * Record a losing trade
     */
    public void recordLoss() {
        consecutiveLosses++;
    }

    /**
     * Emergency stop
     */
    public void kill() {
        transitionTo(State.KILL);
    }

    /**
     * Reset to normal
     */
    public void reset() {
        transitionTo(State.NORMAL);
        consecutiveLosses = 0;
        toxicityScore = 0;
    }
}
