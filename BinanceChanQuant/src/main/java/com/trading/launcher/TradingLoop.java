package com.trading.launcher;

import com.trading.adapter.pool.AlphaPool;
import com.trading.adapter.risk.PreTradeRiskChecker;
import com.trading.adapter.execution.ExecutionEngine;
import com.trading.adapter.attribution.AttributionTracker;
import com.trading.domain.market.model.MarketData;
import com.trading.domain.signal.CompositeAlphaSignal;
import com.trading.domain.signal.MarketContext;

/**
 * Trading Loop - encapsulates single iteration logic
 * Extracted from TradingSystemLauncher to improve testability
 */
public class TradingLoop {

    private final AlphaPool alphaPool;
    private final PreTradeRiskChecker riskChecker;
    private final ExecutionEngine executionEngine;
    private final AttributionTracker attributionTracker;
    private final long heartbeatMs;

    public TradingLoop(AlphaPool alphaPool, PreTradeRiskChecker riskChecker,
                       ExecutionEngine executionEngine, AttributionTracker attributionTracker,
                       long heartbeatMs) {
        this.alphaPool = alphaPool;
        this.riskChecker = riskChecker;
        this.executionEngine = executionEngine;
        this.attributionTracker = attributionTracker;
        this.heartbeatMs = heartbeatMs;
    }

    public void runIteration(int iteration, MarketData marketData, MarketContext context) {
        // Update risk checker with market data (for adaptive risk)
        riskChecker.updateMarketData(
            marketData.getLastPrice(),
            marketData.getVolatility(),
            marketData.getVolume()
        );

        // Generate composite signal via AlphaPool
        if (alphaPool != null) {
            CompositeAlphaSignal compositeSignal = alphaPool.generateCompositeSignal(context);
            if (compositeSignal != null) {
                processAlphaPoolSignal(compositeSignal, iteration);
            }
        }
    }

    private void processAlphaPoolSignal(CompositeAlphaSignal signal, int iteration) {
        double score = signal.getScore(null);
        if (score < 0.3) {
            return;
        }

        double confidence = signal.getConfidence();
        if (confidence > 0.6) {
            // Signal processing logic would go here
            // In real system, this creates and submits orders
        }
    }

    public long getHeartbeatMs() {
        return heartbeatMs;
    }
}
