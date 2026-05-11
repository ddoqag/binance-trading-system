package com.trading.domain.trading.model;

import java.math.BigDecimal;

/**
 * Native TWAP Order Request for Binance Futures Algo API
 *
 * Submits a TWAP (Time-Weighted Average Price) order to Binance's native
 * algorithm engine, offloading slice management and timing to the exchange.
 *
 * Key benefits:
 * - Single API call vs. multiple local TWAP slices
 * - Exchange-side state management (resilient to client restarts)
 * - Better rate limit treatment (official algo, not multiple small orders)
 * - Lower network latency for execution
 */
public final class TwapOrderRequest {

    private final String symbol;
    private final TradeDirection side;
    private final BigDecimal totalQuantity;
    private final long durationSeconds;  // 300s to 86400s per Binance docs
    private final String clientAlgoId;  // For correlation with ExecutionEvent
    private final String strategy;      // Source strategy for attribution

    public TwapOrderRequest(String symbol, TradeDirection side, BigDecimal totalQuantity,
                           long durationSeconds, String clientAlgoId, String strategy) {
        this.symbol = symbol;
        this.side = side;
        this.totalQuantity = totalQuantity;
        this.durationSeconds = durationSeconds;
        this.clientAlgoId = clientAlgoId;
        this.strategy = strategy;
    }

    public String symbol() { return symbol; }
    public TradeDirection side() { return side; }
    public BigDecimal totalQuantity() { return totalQuantity; }
    public long durationSeconds() { return durationSeconds; }
    public String clientAlgoId() { return clientAlgoId; }
    public String strategy() { return strategy; }

    // Builder for convenience
    public static Builder builder() { return new Builder(); }

    public static final class Builder {
        private String symbol;
        private TradeDirection side;
        private BigDecimal totalQuantity;
        private long durationSeconds = 300;  // Default 5 minutes
        private String clientAlgoId;
        private String strategy;

        public Builder symbol(String v) { symbol = v; return this; }
        public Builder side(TradeDirection v) { side = v; return this; }
        public Builder totalQuantity(BigDecimal v) { totalQuantity = v; return this; }
        public Builder totalQuantity(double v) { totalQuantity = BigDecimal.valueOf(v); return this; }
        public Builder durationSeconds(long v) { durationSeconds = v; return this; }
        public Builder clientAlgoId(String v) { clientAlgoId = v; return this; }
        public Builder strategy(String v) { strategy = v; return this; }

        public TwapOrderRequest build() {
            if (durationSeconds < 300) durationSeconds = 300;
            if (durationSeconds > 86400) durationSeconds = 86400;
            return new TwapOrderRequest(symbol, side, totalQuantity, durationSeconds, clientAlgoId, strategy);
        }
    }

    @Override
    public String toString() {
        return String.format("TwapOrderRequest{symbol=%s, side=%s, qty=%s, duration=%ds, algoId=%s}",
            symbol, side, totalQuantity, durationSeconds, clientAlgoId);
    }
}