package hft.executor;

/**
 * Position - Current position state
 */
public class Position {
    private final String symbol;
    private volatile double size = 0;  // positive for long, negative for short
    private volatile double avgPrice = 0;
    private volatile double realizedPnl = 0;

    public Position(String symbol) {
        this.symbol = symbol;
    }

    public synchronized void update(double fillPrice, double fillSize, Order.Side side) {
        if (side == Order.Side.BUY) {
            if (size >= 0) {
                // Adding to long
                double totalValue = size * avgPrice + fillSize * fillPrice;
                size += fillSize;
                avgPrice = totalValue / size;
            } else {
                // Closing short
                double closed = Math.min(fillSize, -size);
                realizedPnl += closed * (avgPrice - fillPrice);
                size += fillSize;
            }
        } else {
            if (size <= 0) {
                // Adding to short
                double totalValue = (-size) * avgPrice + fillSize * fillPrice;
                size -= fillSize;
                avgPrice = totalValue / (-size);
            } else {
                // Closing long
                double closed = Math.min(fillSize, size);
                realizedPnl += closed * (fillPrice - avgPrice);
                size -= fillSize;
            }
        }
    }

    public String getSymbol() { return symbol; }
    public double getSize() { return size; }
    public double getAvgPrice() { return avgPrice; }
    public double getRealizedPnl() { return realizedPnl; }
    public boolean isLong() { return size > 0; }
    public boolean isShort() { return size < 0; }
    public boolean isFlat() { return size == 0; }
}
