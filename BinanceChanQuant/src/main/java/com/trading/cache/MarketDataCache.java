package com.trading.cache;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Market Data Cache - thread-safe cache for market data.
 * Provides O(1) access to latest price, bar data, and order book.
 */
public class MarketDataCache {

    private final Map<String, CacheEntry> cache = new ConcurrentHashMap<>();

    public MarketDataCache() {
    }

    /**
     * Update price for a symbol.
     */
    public void updatePrice(String symbol, double bid, double ask, double last, long timestamp) {
        cache.put(symbol, new CacheEntry(symbol, bid, ask, last, timestamp));
    }

    /**
     * Get latest price info for a symbol.
     */
    public PriceInfo getPrice(String symbol) {
        CacheEntry entry = cache.get(symbol);
        if (entry == null) return null;
        return new PriceInfo(entry.symbol, entry.bid, entry.ask, entry.last, entry.timestamp);
    }

    /**
     * Get last price for a symbol.
     */
    public double getLastPrice(String symbol) {
        CacheEntry entry = cache.get(symbol);
        return entry != null ? entry.last : 0;
    }

    /**
     * Clear cache for a symbol.
     */
    public void clear(String symbol) {
        cache.remove(symbol);
    }

    /**
     * Clear all cached data.
     */
    public void clearAll() {
        cache.clear();
    }

    /**
     * Get spread for a symbol.
     */
    public double getSpread(String symbol) {
        CacheEntry entry = cache.get(symbol);
        if (entry == null) return 0;
        return entry.ask - entry.bid;
    }

    /**
     * Get mid price for a symbol.
     */
    public double getMidPrice(String symbol) {
        CacheEntry entry = cache.get(symbol);
        if (entry == null) return 0;
        return (entry.bid + entry.ask) / 2;
    }

    // Internal cache entry
    private static class CacheEntry {
        final String symbol;
        final double bid;
        final double ask;
        final double last;
        final long timestamp;

        CacheEntry(String symbol, double bid, double ask, double last, long timestamp) {
            this.symbol = symbol;
            this.bid = bid;
            this.ask = ask;
            this.last = last;
            this.timestamp = timestamp;
        }
    }

    /**
     * Price info.
     */
    public static class PriceInfo {
        private final String symbol;
        private final double bid;
        private final double ask;
        private final double last;
        private final long timestamp;

        public PriceInfo(String symbol, double bid, double ask, double last, long timestamp) {
            this.symbol = symbol;
            this.bid = bid;
            this.ask = ask;
            this.last = last;
            this.timestamp = timestamp;
        }

        public String symbol() { return symbol; }
        public double bid() { return bid; }
        public double ask() { return ask; }
        public double last() { return last; }
        public long timestamp() { return timestamp; }
        public double getSpread() { return ask - bid; }
        public double getMid() { return (bid + ask) / 2; }
        public boolean isStale(long maxAgeMs) {
            return System.currentTimeMillis() - timestamp > maxAgeMs;
        }
    }
}
