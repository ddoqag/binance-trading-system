package com.trading.domain.trading.model;

/**
 * Binance Execution Specification
 *
 * SINGLE SOURCE OF TRUTH for Binance API parameters.
 * All order-to-Binance mapping MUST go through this class.
 *
 * This encapsulates the exact parameters needed for Binance:
 * - side: BUY or SELL
 * - positionSide: LONG or SHORT (hedge mode)
 * - reduceOnly: true for closing orders
 *
 * Key principle: No code should manually set positionSide or reduceOnly.
 * The only entry point is BinanceExecutionSpec.from(OrderIntent).
 *
 * Architecture: OrderIntent → BinanceExecutionSpec → Binance API
 */
public final class BinanceExecutionSpec {

    private final String side;           // BUY or SELL
    private final String positionSide;    // LONG or SHORT (null for closePosition=true)
    private final boolean reduceOnly;     // true = closing order

    public BinanceExecutionSpec(String side, String positionSide, boolean reduceOnly) {
        this.side = side;
        this.positionSide = positionSide;
        this.reduceOnly = reduceOnly;
    }

    public String side() { return side; }
    public String positionSide() { return positionSide; }
    public boolean reduceOnly() { return reduceOnly; }

    /**
     * Map OrderIntent to BinanceExecutionSpec.
     * This is the ONLY permitted entry point for Binance parameter generation.
     *
     * Mapping table (immutable):
     * | Intent        | side | positionSide | reduceOnly |
     * |---------------|------|--------------|------------|
     * | OPEN_LONG     | BUY  | LONG         | false      |
     * | CLOSE_LONG    | SELL | LONG         | true       |
     * | OPEN_SHORT    | SELL | SHORT        | false      |
     * | CLOSE_SHORT   | BUY  | SHORT        | true       |
     */
    public static BinanceExecutionSpec from(OrderIntent intent) {
        if (intent == null) {
            throw new IllegalArgumentException("OrderIntent cannot be null");
        }

        switch (intent) {
            case OPEN_LONG:
                return new BinanceExecutionSpec("BUY", "LONG", false);
            case CLOSE_LONG:
                return new BinanceExecutionSpec("SELL", "LONG", true);
            case OPEN_SHORT:
                return new BinanceExecutionSpec("SELL", "SHORT", false);
            case CLOSE_SHORT:
                return new BinanceExecutionSpec("BUY", "SHORT", true);
            default:
                throw new IllegalArgumentException("Unknown OrderIntent: " + intent);
        }
    }

    /**
     * Validate this execution spec is internally consistent.
     * Used by ExecutionSemanticValidator as a final check before sending.
     */
    public boolean isValid() {
        // reduceOnly must be true when closing, false when opening
        String openSide = getOpenSideForPosition(positionSide);
        if (reduceOnly && side.equals(openSide)) {
            return false; // Conflicting: reduceOnly with opening side
        }
        return true;
    }

    private String getOpenSideForPosition(String posSide) {
        if ("LONG".equals(posSide)) {
            return "BUY";
        } else if ("SHORT".equals(posSide)) {
            return "SELL";
        }
        return null;
    }

    @Override
    public String toString() {
        return String.format("BinanceExecutionSpec{side=%s, posSide=%s, reduceOnly=%s}",
                side, positionSide, reduceOnly);
    }
}