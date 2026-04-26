package state;

public class TradeSignal {
    public TradeDirection direction;
    public double entryPrice;
    public double stopLossPrice;
    public double takeProfitPrice;

    public TradeSignal(TradeDirection dir, double entry, double sl, double tp) {
        direction = dir;
        entryPrice = entry;
        stopLossPrice = sl;
        takeProfitPrice = tp;
    }

    public static TradeSignal waitSignal() {
        return new TradeSignal(TradeDirection.WAIT,0,0,0);
    }
}
