package hft.ws;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.locks.ReadWriteLock;
import java.util.concurrent.locks.ReentrantReadWriteLock;

/**
 * OrderBook - High-Performance Order Book
 *
 * Maintains bid/ask price levels with quantities.
 * Thread-safe for concurrent reads/writes.
 */
public class OrderBook {
    private final Map<Double, Double> bids = new ConcurrentHashMap<>();
    private final Map<Double, Double> asks = new ConcurrentHashMap<>();
    private volatile double bestBid = 0;
    private volatile double bestAsk = 0;

    private final ReadWriteLock lock = new ReentrantReadWriteLock();

    /**
     * Update bid levels
     */
    public void updateBids(List<PriceLevel> newBids) {
        lock.writeLock().lock();
        try {
            for (PriceLevel b : newBids) {
                if (b.quantity == 0) {
                    bids.remove(b.price);
                } else {
                    bids.put(b.price, b.quantity);
                }
            }
            updateBestBid();
        } finally {
            lock.writeLock().unlock();
        }
    }

    /**
     * Update ask levels
     */
    public void updateAsks(List<PriceLevel> newAsks) {
        lock.writeLock().lock();
        try {
            for (PriceLevel a : newAsks) {
                if (a.quantity == 0) {
                    asks.remove(a.price);
                } else {
                    asks.put(a.price, a.quantity);
                }
            }
            updateBestAsk();
        } finally {
            lock.writeLock().unlock();
        }
    }

    /**
     * Replace entire bid side (for snapshot streams)
     */
    public void replaceBids(List<PriceLevel> newBids) {
        lock.writeLock().lock();
        try {
            bids.clear();
            double maxBid = 0;
            for (PriceLevel b : newBids) {
                if (b.quantity > 0) {
                    bids.put(b.price, b.quantity);
                    if (b.price > maxBid) {
                        maxBid = b.price;
                    }
                }
            }
            bestBid = maxBid;
        } finally {
            lock.writeLock().unlock();
        }
    }

    /**
     * Replace entire ask side (for snapshot streams)
     */
    public void replaceAsks(List<PriceLevel> newAsks) {
        lock.writeLock().lock();
        try {
            asks.clear();
            double minAsk = 0;
            for (PriceLevel a : newAsks) {
                if (a.quantity > 0) {
                    asks.put(a.price, a.quantity);
                    if (minAsk == 0 || a.price < minAsk) {
                        minAsk = a.price;
                    }
                }
            }
            bestAsk = minAsk;
        } finally {
            lock.writeLock().unlock();
        }
    }

    private void updateBestBid() {
        bestBid = 0;
        for (Double price : bids.keySet()) {
            if (price > bestBid) {
                bestBid = price;
            }
        }
    }

    private void updateBestAsk() {
        bestAsk = 0;
        for (Double price : asks.keySet()) {
            if (bestAsk == 0 || price < bestAsk) {
                bestAsk = price;
            }
        }
    }

    /**
     * Get snapshot of best bid/ask with volumes
     */
    public Snapshot getSnapshot() {
        lock.readLock().lock();
        try {
            return new Snapshot(
                bestBid,
                bestAsk,
                bids.getOrDefault(bestBid, 0.0),
                asks.getOrDefault(bestAsk, 0.0)
            );
        } finally {
            lock.readLock().unlock();
        }
    }

    /**
     * Get depth (sorted)
     */
    public Depth getDepth(int limit) {
        lock.readLock().lock();
        try {
            List<PriceLevel> bidList = new ArrayList<>();
            List<PriceLevel> askList = new ArrayList<>();

            for (Map.Entry<Double, Double> e : bids.entrySet()) {
                bidList.add(new PriceLevel(e.getKey(), e.getValue()));
            }
            for (Map.Entry<Double, Double> e : asks.entrySet()) {
                askList.add(new PriceLevel(e.getKey(), e.getValue()));
            }

            // Sort: bids descending, asks ascending
            bidList.sort((a, b) -> Double.compare(b.price, a.price));
            askList.sort(Comparator.comparingDouble(a -> a.price));

            if (bidList.size() > limit) bidList = bidList.subList(0, limit);
            if (askList.size() > limit) askList = askList.subList(0, limit);

            return new Depth(bidList, askList);
        } finally {
            lock.readLock().unlock();
        }
    }

    /**
     * Clear the order book
     */
    public void clear() {
        lock.writeLock().lock();
        try {
            bids.clear();
            asks.clear();
            bestBid = 0;
            bestAsk = 0;
        } finally {
            lock.writeLock().unlock();
        }
    }

    public double getBestBid() { return bestBid; }
    public double getBestAsk() { return bestAsk; }

    /**
     * Price level with quantity
     */
    public static class PriceLevel {
        public final double price;
        public final double quantity;

        public PriceLevel(double price, double quantity) {
            this.price = price;
            this.quantity = quantity;
        }
    }

    /**
     * Snapshot of best bid/ask
     */
    public static class Snapshot {
        public final double bestBid;
        public final double bestAsk;
        public final double bidVolume;
        public final double askVolume;

        public Snapshot(double bestBid, double bestAsk, double bidVolume, double askVolume) {
            this.bestBid = bestBid;
            this.bestAsk = bestAsk;
            this.bidVolume = bidVolume;
            this.askVolume = askVolume;
        }
    }

    /**
     * Depth result with sorted levels
     */
    public static class Depth {
        public final List<PriceLevel> bids;
        public final List<PriceLevel> asks;

        public Depth(List<PriceLevel> bids, List<PriceLevel> asks) {
            this.bids = bids;
            this.asks = asks;
        }
    }
}
