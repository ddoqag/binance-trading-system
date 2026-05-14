package com.trading.infrastructure.execution.state;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Consumer;

/**
 * Atomic state store for exchange state.
 *
 * <p>Provides:
 * <ul>
 *   <li>Atomic snapshot updates</li>
 *   <li>Optimistic read without locking</li>
 *   <li>Change callbacks</li>
 *   <li>Update validation via CAS</li>
 * </ul>
 */
public class StateStore {

    private static final Logger log = LoggerFactory.getLogger(StateStore.class);

    private final AtomicReference<ExchangeStateSnapshot> state;
    private final AtomicReference<TradingState> tradingState;

    // Subscribers
    private volatile Consumer<ExchangeStateSnapshot> onSnapshotChange;
    private volatile Consumer<TradingState> onTradingStateChange;

    public StateStore() {
        this.state = new AtomicReference<>(ExchangeStateSnapshot.empty());
        this.tradingState = new AtomicReference<>(TradingState.STARTUP_RECOVERY);
    }

    // ========== State Access ==========

    public ExchangeStateSnapshot getSnapshot() {
        return state.get();
    }

    public TradingState getTradingState() {
        return tradingState.get();
    }

    /**
     * Update state atomically.
     * @return true if update was applied
     */
    public boolean updateSnapshot(ExchangeStateSnapshot newSnapshot) {
        if (newSnapshot == null) return false;

        ExchangeStateSnapshot current = state.get();
        if (newSnapshot.sequence() < current.sequence()) {
            log.warn("[StateStore] Rejected stale snapshot: seq={} < current seq={}",
                    newSnapshot.sequence(), current.sequence());
            return false;
        }

        if (!state.compareAndSet(current, newSnapshot)) {
            log.warn("[StateStore] CAS failed, will retry on next update");
            return false;
        }

        log.debug("[StateStore] Snapshot updated: seq={}", newSnapshot.sequence());
        notifySnapshotChange(newSnapshot);
        return true;
    }

    /**
     * CAS-based conditional update.
     * Only applies if current snapshot matches expected.
     */
    public boolean compareAndUpdate(ExchangeStateSnapshot expected,
                                    ExchangeStateSnapshot newSnapshot) {
        if (!state.compareAndSet(expected, newSnapshot)) {
            log.debug("[StateStore] CAS compare failed");
            return false;
        }
        notifySnapshotChange(newSnapshot);
        return true;
    }

    // ========== Trading State ==========

    public void setTradingState(TradingState newState) {
        TradingState current = tradingState.get();
        if (current == newState) return;

        if (!tradingState.compareAndSet(current, newState)) {
            log.warn("[StateStore] Trading state CAS failed, will retry");
            return;
        }

        log.info("[StateStore] TradingState: {} → {}", current, newState);
        notifyTradingStateChange(newState);
    }

    public boolean canTrade() {
        return tradingState.get() == TradingState.NORMAL;
    }

    // ========== Subscribers ==========

    public void setOnSnapshotChange(Consumer<ExchangeStateSnapshot> callback) {
        this.onSnapshotChange = callback;
    }

    public void setOnTradingStateChange(Consumer<TradingState> callback) {
        this.onTradingStateChange = callback;
    }

    private void notifySnapshotChange(ExchangeStateSnapshot snapshot) {
        if (onSnapshotChange != null) {
            try {
                onSnapshotChange.accept(snapshot);
            } catch (Exception e) {
                log.error("[StateStore] Snapshot change callback failed: {}", e.getMessage());
            }
        }
    }

    private void notifyTradingStateChange(TradingState state) {
        if (onTradingStateChange != null) {
            try {
                onTradingStateChange.accept(state);
            } catch (Exception e) {
                log.error("[StateStore] Trading state change callback failed: {}", e.getMessage());
            }
        }
    }

    // ========== Trading State Enum ==========

    /**
     * Trading lifecycle states.
     *
     * <p>State transitions:</p>
     * <pre>
     * STARTUP_RECOVERY → NORMAL (after first successful sync)
     * NORMAL → DEGRADED (on snapshot instability)
     * DEGRADED → NORMAL (after recovery)
     * ANY → SAFE_MODE (on critical failure)
     * </pre>
     */
    public enum TradingState {
        /** Initial boot - full recovery in progress, no trading */
        STARTUP_RECOVERY,

        /** Reconnecting - buffering WS events, snapshot authoritative, no trading */
        RECONNECT_SYNC,

        /** Normal operation - full trading enabled */
        NORMAL,

        /** Snapshot unstable/listenKey fail - buffering WS, no trading */
        DEGRADED,

        /** Critical failure - manual intervention required */
        SAFE_MODE
    }
}