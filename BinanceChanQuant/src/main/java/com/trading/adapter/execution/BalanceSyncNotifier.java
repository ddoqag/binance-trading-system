package com.trading.adapter.execution;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Callback interface for balance synchronization events.
 * Allows BinancePositionTracker to notify other components (e.g., PreTradeRiskChecker)
 * when balance is updated.
 */
public interface BalanceSyncNotifier {

    void onBalanceUpdated(double availableBalance, double walletBalance);

    /**
     * Simple adapter that logs balance updates for debugging.
     */
    class LoggingNotifier implements BalanceSyncNotifier {
        private static final Logger log = LoggerFactory.getLogger(LoggingNotifier.class);

        @Override
        public void onBalanceUpdated(double availableBalance, double walletBalance) {
            log.debug("[BalanceNotifier] balance updated: available={}, wallet={}",
                    availableBalance, walletBalance);
        }
    }
}