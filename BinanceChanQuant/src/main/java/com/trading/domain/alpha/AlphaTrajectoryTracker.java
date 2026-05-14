package com.trading.domain.alpha;

import com.trading.domain.market.model.MarketRegime;
import com.trading.domain.trading.model.TradeDirection;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Consumer;

/**
 * AlphaTrajectoryTracker - Independent service for trajectory lifecycle management
 *
 * Manages the complete lifecycle of AlphaTrajectories from creation to closure.
 * Provides query methods for MetaLearner to assess signal quality and execution.
 *
 * Key responsibilities:
 * - Track active trajectories (ConcurrentHashMap for thread safety)
 * - Enforce TTL (maxObservationWindowMs) via periodic cleanup
 * - Provide statistical queries for MetaLearner
 * - Emit lifecycle events for observability
 */
public final class AlphaTrajectoryTracker {

    private static final Logger log = LoggerFactory.getLogger(AlphaTrajectoryTracker.class);

    private final Map<String, AlphaTrajectoryRuntime> activeTrajectories = new ConcurrentHashMap<>();
    private final Map<String, AlphaHypothesis> hypotheses = new ConcurrentHashMap<>();

    // Observability callbacks
    private Consumer<PnlSnapshot> onSnapshot;
    private Consumer<String> onTrajectoryClosed;
    private Consumer<String> onTrajectoryExpired;

    private AlphaTrajectoryTracker() {}

    public static AlphaTrajectoryTracker create() {
        return new AlphaTrajectoryTracker();
    }

    /**
     * Start tracking a new alpha hypothesis.
     * Creates both the hypothesis and its runtime.
     */
    public AlphaTrajectoryRuntime track(AlphaHypothesis hypothesis, double entryPrice, double riskAmount) {
        String id = hypothesis.getAlphaId();

        if (activeTrajectories.containsKey(id)) {
            log.warn("[AlphaTrajectoryTracker] Trajectory {} already exists, skipping", id);
            return activeTrajectories.get(id);
        }

        AlphaTrajectoryRuntime runtime = new AlphaTrajectoryRuntime(
            id,
            hypothesis.getDirection(),
            entryPrice,
            riskAmount
        );

        activeTrajectories.put(id, runtime);
        hypotheses.put(id, hypothesis);

        log.info("[AlphaTrajectoryTracker] Started tracking trajectory {} direction={} entry={} risk={}",
            id, hypothesis.getDirection(), entryPrice, riskAmount);

        return runtime;
    }

    /**
     * Update trajectory with current market price.
     * Creates snapshots based on event-sampling rules.
     */
    public void updatePrice(String alphaId, double currentPrice, MarketRegime regime, double unrealizedPnl) {
        AlphaTrajectoryRuntime runtime = activeTrajectories.get(alphaId);
        if (runtime == null) {
            log.debug("[AlphaTrajectoryTracker] No active trajectory for {}", alphaId);
            return;
        }

        PnlSnapshot snapshot = runtime.updatePrice(currentPrice, regime, unrealizedPnl);
        if (snapshot != null && onSnapshot != null) {
            onSnapshot.accept(snapshot);
        }
    }

    /**
     * Close a trajectory with realized PnL.
     */
    public void close(String alphaId, double currentPrice, MarketRegime regime, double realizedPnl) {
        AlphaTrajectoryRuntime runtime = activeTrajectories.get(alphaId);
        if (runtime == null) {
            log.warn("[AlphaTrajectoryTracker] Cannot close non-existent trajectory {}", alphaId);
            return;
        }

        PnlSnapshot snapshot = runtime.close(currentPrice, regime, realizedPnl);
        activeTrajectories.remove(alphaId);

        if (onTrajectoryClosed != null) {
            onTrajectoryClosed.accept(alphaId);
        }

        log.info("[AlphaTrajectoryTracker] Closed trajectory {} with realizedPnl={} exitR={}",
            alphaId, realizedPnl, runtime.exitRMultiple());
    }

    /**
     * Mark trajectory as abandoned (signal generated but never executed).
     */
    public void abandon(String alphaId) {
        AlphaTrajectoryRuntime runtime = activeTrajectories.get(alphaId);
        if (runtime != null) {
            runtime.abandon();
            activeTrajectories.remove(alphaId);
            log.info("[AlphaTrajectoryTracker] Abandoned trajectory {}", alphaId);
        }
    }

    /**
     * Enforce TTL - expire trajectories that exceeded max observation window.
     * Called periodically by the tracking service.
     */
    public int enforceTtl() {
        long now = System.currentTimeMillis();
        int expired = 0;

        List<String> toExpire = new ArrayList<>();

        for (Map.Entry<String, AlphaTrajectoryRuntime> entry : activeTrajectories.entrySet()) {
            String id = entry.getKey();
            AlphaTrajectoryRuntime runtime = entry.getValue();
            AlphaHypothesis hypothesis = hypotheses.get(id);

            if (hypothesis == null) continue;

            long age = now - hypothesis.getGenerationTime();

            // Check hard TTL: maxObservationWindowMs
            if (age > hypothesis.getMaxObservationWindowMs()) {
                toExpire.add(id);
            }
            // Check soft TTL: expectedHalfLifeMs * 4 (approx 4 half-lives)
            else if (age > hypothesis.getExpectedHalfLifeMs() * 4 && runtime.isActive()) {
                runtime.expire();
                toExpire.add(id);
            }
        }

        for (String id : toExpire) {
            activeTrajectories.remove(id);
            if (onTrajectoryExpired != null) {
                onTrajectoryExpired.accept(id);
            }
            log.info("[AlphaTrajectoryTracker] Expired trajectory {} (age > max window)", id);
            expired++;
        }

        return expired;
    }

    /**
     * Get all active trajectory IDs
     */
    public Set<String> activeIds() {
        return Collections.unmodifiableSet(activeTrajectories.keySet());
    }

    /**
     * Get active trajectory count
     */
    public int activeCount() {
        return activeTrajectories.size();
    }

    /**
     * Get trajectory runtime if exists
     */
    public Optional<AlphaTrajectoryRuntime> get(String alphaId) {
        return Optional.ofNullable(activeTrajectories.get(alphaId));
    }

    /**
     * Get hypothesis if exists
     */
    public Optional<AlphaHypothesis> getHypothesis(String alphaId) {
        return Optional.ofNullable(hypotheses.get(alphaId));
    }

    /**
     * Get all active trajectories for statistical queries
     */
    public Collection<AlphaTrajectoryRuntime> getActiveTrajectories() {
        return Collections.unmodifiableCollection(activeTrajectories.values());
    }

    /**
     * Calculate aggregate statistics across all active trajectories
     */
    public TrajectoryStatistics getStatistics() {
        if (activeTrajectories.isEmpty()) {
            return TrajectoryStatistics.EMPTY;
        }

        double totalMfe = 0;
        double totalMae = 0;
        double totalMfeMae = 0;
        int count = 0;

        for (AlphaTrajectoryRuntime rt : activeTrajectories.values()) {
            totalMfe += rt.currentMfe();
            totalMfeMae += rt.mfeMaeRatio();
            if (rt.currentMae() < 0) {
                totalMae += Math.abs(rt.currentMae());
            }
            count++;
        }

        return new TrajectoryStatistics(
            count,
            totalMfe / count,
            totalMae / count,
            totalMfeMae / count
        );
    }

    /**
     * Get trajectories filtered by direction
     */
    public List<AlphaTrajectoryRuntime> getByDirection(TradeDirection direction) {
        List<AlphaTrajectoryRuntime> result = new ArrayList<>();
        for (AlphaTrajectoryRuntime rt : activeTrajectories.values()) {
            if (rt.direction() == direction) {
                result.add(rt);
            }
        }
        return result;
    }

    // Callback setters

    public AlphaTrajectoryTracker onSnapshot(Consumer<PnlSnapshot> callback) {
        this.onSnapshot = callback;
        return this;
    }

    public AlphaTrajectoryTracker onTrajectoryClosed(Consumer<String> callback) {
        this.onTrajectoryClosed = callback;
        return this;
    }

    public AlphaTrajectoryTracker onTrajectoryExpired(Consumer<String> callback) {
        this.onTrajectoryExpired = callback;
        return this;
    }

    /**
     * Statistics container for aggregate queries
     */
    public static final class TrajectoryStatistics {
        public static final TrajectoryStatistics EMPTY = new TrajectoryStatistics(0, 0, 0, 0);

        public final int activeCount;
        public final double avgMfe;
        public final double avgMae;
        public final double avgMfeMaeRatio;

        public TrajectoryStatistics(int activeCount, double avgMfe, double avgMae, double avgMfeMaeRatio) {
            this.activeCount = activeCount;
            this.avgMfe = avgMfe;
            this.avgMae = avgMae;
            this.avgMfeMaeRatio = avgMfeMaeRatio;
        }
    }
}