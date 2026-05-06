package com.trading.factory.backtest;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;

/**
 * Simulated Historical Data Provider for testing Strategy Factory
 */
public class SimulatedDataProvider implements HistoricalDataProvider {

    private final List<OHLCV> bars;
    private final Random rand = new Random(42);  // Fixed seed for reproducibility

    public SimulatedDataProvider(int barCount) {
        this.bars = generateSimulatedBars(barCount);
    }

    @Override
    public List<OHLCV> getBars() {
        return new ArrayList<>(bars);
    }

    @Override
    public List<OHLCV> getBars(long startTime, long endTime) {
        return bars.stream()
                .filter(b -> b.timestamp() >= startTime && b.timestamp() <= endTime)
                .toList();
    }

    private List<OHLCV> generateSimulatedBars(int count) {
        List<OHLCV> result = new ArrayList<>();
        double price = 2000.0;  // Starting price
        long timestamp = System.currentTimeMillis() - count * 3600000L;

        for (int i = 0; i < count; i++) {
            // Random walk with trend
            double trend = 0.0002;  // Slight upward trend
            double volatility = 0.01;  // 1% volatility
            double change = trend + (rand.nextDouble() - 0.5) * volatility;

            price = price * (1 + change);

            double open = price;
            double high = price * (1 + rand.nextDouble() * 0.005);
            double low = price * (1 - rand.nextDouble() * 0.005);
            double close = price * (1 + (rand.nextDouble() - 0.5) * 0.002);
            double volume = 100 + rand.nextDouble() * 1000;

            result.add(new OHLCV(timestamp, open, high, low, close, volume));

            timestamp += 3600000L;  // 1 hour bars
        }

        return result;
    }

    public static void main(String[] args) {
        // Test the data provider
        SimulatedDataProvider provider = new SimulatedDataProvider(500);

        System.out.println("Generated " + provider.getBars().size() + " bars");
        System.out.println("First bar: " + provider.getBars().get(0));
        System.out.println("Last bar: " + provider.getBars().get(provider.getBars().size() - 1));

        // Test split
        DataSplit split = provider.splitData(0.7);
        System.out.println("Train: " + split.train().size() + ", Test: " + split.test().size());
    }
}