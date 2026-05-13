package com.trading.infrastructure.execution;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.atomic.AtomicBoolean;

/**
 * TradingGuard - 交易熔断保护器
 *
 * <p>Simple global trading guard that disables new position entries during
 * critical operations like startup recovery, orphan position detection, etc.
 *
 * <p>This is NOT a state machine - just a simple AtomicBoolean guard.
 * Using simple boolean to avoid over-engineering at P0 stage.
 *
 * <p>Usage:
 * <pre>
 * if (!tradingGuard.canTrade()) {
 *     reject new order
 * }
 * </pre>
 */
public class TradingGuard {

    private static final Logger log = LoggerFactory.getLogger(TradingGuard.class);

    private final AtomicBoolean tradingDisabled = new AtomicBoolean(false);
    private final AtomicBoolean safeMode = new AtomicBoolean(false);

    private volatile String disableReason = "";
    private volatile long disableTimestamp = 0;

    /**
     * Enter safe mode - disables all new position entries
     */
    public void enterSafeMode(String reason) {
        tradingDisabled.set(true);
        safeMode.set(true);
        disableReason = reason;
        disableTimestamp = System.currentTimeMillis();
        log.warn("[TradingGuard] SAFE_MODE ENTERED: {}", reason);
    }

    /**
     * Exit safe mode - re-enables trading
     */
    public void exitSafeMode() {
        if (tradingDisabled.compareAndSet(true, false)) {
            long duration = System.currentTimeMillis() - disableTimestamp;
            log.info("[TradingGuard] SAFE_MODE EXITED: was disabled for {}ms - {}",
                    duration, disableReason);
            safeMode.set(false);
        }
    }

    /**
     * Check if trading is allowed
     */
    public boolean canTrade() {
        return !tradingDisabled.get();
    }

    /**
     * Check if in safe mode
     */
    public boolean isSafeMode() {
        return safeMode.get();
    }

    /**
     * Check if trading is currently disabled
     */
    public boolean isDisabled() {
        return tradingDisabled.get();
    }

    /**
     * Get current disable reason
     */
    public String getDisableReason() {
        return disableReason;
    }

    /**
     * Get duration since trading was disabled (ms)
     */
    public long getDisableDurationMs() {
        if (disableTimestamp == 0) {
            return 0;
        }
        return System.currentTimeMillis() - disableTimestamp;
    }
}
