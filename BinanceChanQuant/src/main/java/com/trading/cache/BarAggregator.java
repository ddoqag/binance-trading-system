package com.trading.cache;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Bar Aggregator - aggregates ticks into time bars.
 * Supports multiple timeframes (1m, 5m, 15m, 1h, etc).
 */
public class BarAggregator {

    private final BarSchema schema;
    private final ConcurrentLinkedQueue<Bar> closedBars = new ConcurrentLinkedQueue<>();
    private final AtomicReference<Bar> currentBar = new AtomicReference<>();

    public BarAggregator(BarSchema schema) {
        this.schema = schema;
    }

    /**
     * Add a tick to the current bar.
     * Returns closed bar if bar was just closed.
     */
    public Bar onTick(double price, double volume, long timestamp) {
        Bar current = currentBar.get();
        Bar newBar;

        if (current == null || isBarClosed(current, timestamp)) {
            // Close current bar and start new one
            if (current != null) {
                closedBars.offer(current);
                trimClosedBars();
            }
            newBar = new Bar(schema, timestamp, price, price, price, price, volume);
            currentBar.set(newBar);
            return current; // Return the just-closed bar
        } else {
            // Update existing bar
            newBar = current.update(price, volume);
            currentBar.set(newBar);
            return null;
        }
    }

    /**
     * Get the current (unclosed) bar.
     */
    public Bar getCurrentBar() {
        return currentBar.get();
    }

    /**
     * Get recently closed bars.
     */
    public List<Bar> getClosedBars(int count) {
        List<Bar> result = new ArrayList<>();
        int i = 0;
        for (Bar bar : closedBars) {
            result.add(0, bar);
            if (++i >= count) break;
        }
        return result;
    }

    private boolean isBarClosed(Bar bar, long currentTimestamp) {
        long barStart = bar.timestamp();
        long barEnd = barStart + schema.intervalMs;
        return currentTimestamp >= barEnd;
    }

    private void trimClosedBars() {
        while (closedBars.size() > 1000) {
            closedBars.poll();
        }
    }

    /**
     * Bar schema (timeframe).
     */
    public static class BarSchema {
        public final String name;
        public final long intervalMs;

        public static final BarSchema M1 = new BarSchema("1m", 60_000);
        public static final BarSchema M5 = new BarSchema("5m", 300_000);
        public static final BarSchema M15 = new BarSchema("15m", 900_000);
        public static final BarSchema H1 = new BarSchema("1h", 3_600_000);
        public static final BarSchema H4 = new BarSchema("4h", 14_400_000);
        public static final BarSchema D1 = new BarSchema("1d", 86_400_000);

        public BarSchema(String name, long intervalMs) {
            this.name = name;
            this.intervalMs = intervalMs;
        }
    }

    /**
     * Immutable Bar record.
     */
    public static class Bar {
        private final BarSchema schema;
        private final long timestamp;
        private final double open;
        private final double high;
        private final double low;
        private final double close;
        private final double volume;

        public Bar(BarSchema schema, long timestamp, double open, double high, double low, double close, double volume) {
            this.schema = schema;
            this.timestamp = timestamp;
            this.open = open;
            this.high = high;
            this.low = low;
            this.close = close;
            this.volume = volume;
        }

        public Bar update(double price, double volume) {
            return new Bar(
                schema,
                timestamp,
                open,
                Math.max(high, price),
                Math.min(low, price),
                price,
                this.volume + volume
            );
        }

        public BarSchema schema() { return schema; }
        public long timestamp() { return timestamp; }
        public double open() { return open; }
        public double high() { return high; }
        public double low() { return low; }
        public double close() { return close; }
        public double volume() { return volume; }

        public double range() { return high - low; }
        public double change() { return close - open; }
        public double changePercent() { return open > 0 ? (close - open) / open * 100 : 0; }
    }
}
