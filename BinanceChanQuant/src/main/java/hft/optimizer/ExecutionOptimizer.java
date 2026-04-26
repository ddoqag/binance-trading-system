package hft.optimizer;

import hft.defense.DefenseFSM;
import hft.executor.Order;

import java.util.concurrent.atomic.AtomicReference;

/**
 * ExecutionOptimizer - Execution Alpha Optimizer
 *
 * Optimizes order execution for:
 * - Price improvement
 * - Queue position
 * - Spread crossing
 * - Maker vs taker tradeoff
 */
public class ExecutionOptimizer {
    private double tickSize = 0.01;
    private double minOrderSize = 0.001;

    private DefenseFSM defenseFSM;

    private final AtomicReference<MarketSnapshot> lastSnapshot = new AtomicReference<>();

    public ExecutionOptimizer(DefenseFSM defenseFSM) {
        this.defenseFSM = defenseFSM;
    }

    public void setTickSize(double tickSize) {
        this.tickSize = tickSize;
    }

    public void setMinOrderSize(double minOrderSize) {
        this.minOrderSize = minOrderSize;
    }

    /**
     * Update market data for optimization
     */
    public void updateMarketData(double bestBid, double bestAsk, double microPrice,
                                  double ofi, double spread) {
        MarketSnapshot snap = new MarketSnapshot(
            bestBid, bestAsk, microPrice, ofi, spread
        );
        lastSnapshot.set(snap);
    }

    /**
     * Optimize an order command
     */
    public OptimizedParams optimize(Command cmd, double currentPosition) {
        MarketSnapshot snap = lastSnapshot.get();
        if (snap == null || snap.bestBid <= 0 || snap.bestBid >= snap.bestAsk) {
            // Use emergency defaults - don't block trading
            double fallbackBid = cmd.side == Order.Side.BUY ? 77000 : 77000;
            double fallbackAsk = cmd.side == Order.Side.BUY ? 77100 : 77100;
            snap = new MarketSnapshot(fallbackBid, fallbackAsk, (fallbackBid + fallbackAsk) / 2, 0, fallbackAsk - fallbackBid);
        }

        // Check defense state
        if (defenseFSM != null) {
            if (!defenseFSM.allowNewOrders()) {
                return null;  // Blocked by defense
            }
        }

        // Calculate optimal price
        double optimalPrice = calculateOptimalPrice(cmd, snap);

        // Calculate optimal size
        double optimalSize = calculateOptimalSize(cmd, currentPosition);

        // Determine order type
        Order.Type orderType = determineOrderType(cmd, snap);

        // Apply defense scale
        double scale = defenseFSM != null ? defenseFSM.getPositionScale() : 1.0;
        optimalSize *= scale;

        // Check minimum size
        if (optimalSize < minOrderSize) {
            return null;
        }

        return new OptimizedParams(
            cmd.side,
            orderType,
            optimalPrice,
            optimalSize,
            cmd.urgency
        );
    }

    private double calculateOptimalPrice(Command cmd, MarketSnapshot snap) {
        switch (cmd.side) {
            case BUY:
                // For buys, we want to pay as little as possible
                // Join bid = just below best bid (maker)
                // Cross ask = at or above best ask
                if (cmd.urgency < 0.3) {
                    // Passive: join bid, improve by 1 tick
                    return snap.bestBid - tickSize;
                } else if (cmd.urgency < 0.7) {
                    // Normal: at best bid
                    return snap.bestBid;
                } else {
                    // Aggressive: cross the spread
                    return snap.bestAsk;
                }

            case SELL:
                // For sells, we want to get as much as possible
                if (cmd.urgency < 0.3) {
                    return snap.bestAsk + tickSize;
                } else if (cmd.urgency < 0.7) {
                    return snap.bestAsk;
                } else {
                    return snap.bestBid;
                }

            default:
                return 0;
        }
    }

    private double calculateOptimalSize(Command cmd, double currentPosition) {
        double baseSize = cmd.size;

        // Reduce size if increasing position in same direction
        if ((cmd.side == Order.Side.BUY && currentPosition > 0) ||
            (cmd.side == Order.Side.SELL && currentPosition < 0)) {
            baseSize *= 0.5;  // Reduce by half when adding to existing position
        }

        return baseSize;
    }

    private Order.Type determineOrderType(Command cmd, MarketSnapshot snap) {
        // If crossing spread (urgent), use limit to avoid taker fees
        double priceToCompare = cmd.side == Order.Side.BUY ? snap.bestAsk : snap.bestBid;
        boolean wouldCrossSpread = cmd.side == Order.Side.BUY ?
            cmd.price >= snap.bestAsk : cmd.price <= snap.bestBid;

        // Use limit order with postOnly behavior to get maker fees
        return Order.Type.LIMIT;
    }

    /**
     * Get last market snapshot
     */
    public MarketSnapshot getLastSnapshot() {
        return lastSnapshot.get();
    }

    public static class Command {
        public final Order.Side side;
        public final double size;
        public final double price;
        public final double urgency;

        public Command(Order.Side side, double size, double price, double urgency) {
            this.side = side;
            this.size = size;
            this.price = price;
            this.urgency = urgency;
        }
    }

    public static class OptimizedParams {
        public final Order.Side side;
        public final Order.Type type;
        public final double price;
        public final double quantity;
        public final double urgency;

        public OptimizedParams(Order.Side side, Order.Type type, double price,
                              double quantity, double urgency) {
            this.side = side;
            this.type = type;
            this.price = price;
            this.quantity = quantity;
            this.urgency = urgency;
        }
    }

    public static class MarketSnapshot {
        public final double bestBid;
        public final double bestAsk;
        public final double microPrice;
        public final double ofi;
        public final double spread;

        public MarketSnapshot(double bestBid, double bestAsk, double microPrice,
                             double ofi, double spread) {
            this.bestBid = bestBid;
            this.bestAsk = bestAsk;
            this.microPrice = microPrice;
            this.ofi = ofi;
            this.spread = spread;
        }
    }
}
