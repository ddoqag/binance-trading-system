package hft.ws;

import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.atomic.AtomicLong;

/**
 * OFICalculator - Order Flow Imbalance Calculator
 *
 * Calculates OFI based on order book changes and trade flow.
 * OFI = Σ(sign * qty) for each price level change
 *
 * Thread-safe using atomic operations.
 */
public class OFICalculator {
    private double lastBidPrice = 0;
    private double lastBidQty = 0;
    private double lastAskPrice = 0;
    private double lastAskQty = 0;

    private final AtomicReference<Double> ofi = new AtomicReference<>(0.0);
    private final AtomicReference<Double> tradeFlow = new AtomicReference<>(0.0);

    private final Object lock = new Object();

    /**
     * Update OFI from depth change
     */
    public void updateDepth(double bestBid, double bestAsk, double bidQty, double askQty) {
        synchronized (lock) {
            // Bid side OFI
            if (bestBid > lastBidPrice) {
                // Bid price increased: bullish
                ofi.updateAndGet(v -> v + bidQty);
            } else if (bestBid < lastBidPrice) {
                // Bid price decreased: bearish
                ofi.updateAndGet(v -> v - lastBidQty);
            }

            // Ask side OFI
            if (bestAsk < lastAskPrice) {
                // Ask price decreased: bullish
                ofi.updateAndGet(v -> v - askQty);
            } else if (bestAsk > lastAskPrice) {
                // Ask price increased: bearish
                ofi.updateAndGet(v -> v + lastAskQty);
            }

            lastBidPrice = bestBid;
            lastBidQty = bidQty;
            lastAskPrice = bestAsk;
            lastAskQty = askQty;
        }
    }

    /**
     * Update trade flow from trade event
     *
     * @param price trade price
     * @param qty trade quantity
     * @param isBuyerMaker true if buyer was the maker (seller initiated)
     */
    public void updateTrade(double price, double qty, boolean isBuyerMaker) {
        if (isBuyerMaker) {
            // Seller initiated: price likely to go down
            tradeFlow.updateAndGet(v -> v - qty);
        } else {
            // Buyer initiated: price likely to go up
            tradeFlow.updateAndGet(v -> v + qty);
        }
    }

    /**
     * Get current OFI value
     */
    public double getOFI() {
        return ofi.get();
    }

    /**
     * Get current trade flow value
     */
    public double getTradeFlow() {
        return tradeFlow.get();
    }

    /**
     * Get combined signal (OFI + trade flow)
     */
    public double getSignal() {
        return ofi.get() + tradeFlow.get();
    }

    /**
     * Reset OFI calculation
     */
    public void reset() {
        synchronized (lock) {
            ofi.set(0.0);
            tradeFlow.set(0.0);
            lastBidPrice = 0;
            lastBidQty = 0;
            lastAskPrice = 0;
            lastAskQty = 0;
        }
    }

    /**
     * Get micro-price: volume-weighted mid
     *
     * @param bestBid current best bid
     * @param bestAsk current best ask
     * @param bidVol bid side volume at best
     * @param askVol ask side volume at best
     */
    public static double calculateMicroPrice(double bestBid, double bestAsk, double bidVol, double askVol) {
        double totalVol = bidVol + askVol;
        if (totalVol == 0) return (bestBid + bestAsk) / 2;

        // Volume-weighted mid price
        double weight = bidVol / totalVol;
        return bestBid * weight + bestAsk * (1 - weight);
    }
}
