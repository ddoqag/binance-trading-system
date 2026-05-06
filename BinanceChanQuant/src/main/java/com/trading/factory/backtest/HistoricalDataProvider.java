package com.trading.factory.backtest;

import java.util.List;

/**
 * Historical Data Provider - Interface for market data
 */
public interface HistoricalDataProvider {

    /**
     * Get all historical bars
     */
    List<OHLCV> getBars();

    /**
     * Get bars within time range
     */
    List<OHLCV> getBars(long startTime, long endTime);

    /**
     * Split data into train/test sets
     */
    default DataSplit splitData(double trainRatio) {
        List<OHLCV> all = getBars();
        int splitIdx = (int) (all.size() * trainRatio);
        return new DataSplit(
                all.subList(0, splitIdx),
                all.subList(splitIdx, all.size())
        );
    }

    static double calculateATR(List<OHLCV> bars, int period) {
        if (bars.size() < period) return 0;
        double sum = 0;
        for (int i = bars.size() - period; i < bars.size(); i++) {
            double tr = Math.max(
                    bars.get(i).high - bars.get(i).low,
                    Math.max(
                            Math.abs(bars.get(i).high - bars.get(i - 1).close),
                            Math.abs(bars.get(i).low - bars.get(i - 1).close)
                    )
            );
            sum += tr;
        }
        return sum / period;
    }

    /**
     * OHLCV bar data
     */
    class OHLCV {
        private final long timestamp;
        private final double open;
        private final double high;
        private final double low;
        private final double close;
        private final double volume;

        public OHLCV(long timestamp, double open, double high, double low, double close, double volume) {
            this.timestamp = timestamp;
            this.open = open;
            this.high = high;
            this.low = low;
            this.close = close;
            this.volume = volume;
        }

        public long timestamp() { return timestamp; }
        public double open() { return open; }
        public double high() { return high; }
        public double low() { return low; }
        public double close() { return close; }
        public double volume() { return volume; }

        public double getTypicalPrice() { return (high + low + close) / 3.0; }
        public double getReturn() {
            if (volume == 0) return 0;
            return (close - open) / open;
        }
    }

    /**
     * Train/Test split container
     */
    class DataSplit {
        private final List<OHLCV> train;
        private final List<OHLCV> test;

        public DataSplit(List<OHLCV> train, List<OHLCV> test) {
            this.train = train;
            this.test = test;
        }

        public List<OHLCV> train() { return train; }
        public List<OHLCV> test() { return test; }
        public int totalSize() { return train.size() + test.size(); }
        public double trainRatio() { return (double) train.size() / totalSize(); }
    }
}