package com.trading.adapter.shadow;

import com.trading.domain.market.model.MarketData;
import state.TradeDirection;
import state.TradeSignal;

import java.util.ArrayList;
import java.util.List;

/**
 * 影子交易账本 - 模拟订单执行和盈亏计算
 */
public class ShadowExecutionBook {
    private double currentPosition = 0;
    private double avgEntryPrice = 0;
    private TradeDirection currentDirection = null;
    private final List<ShadowTrade> trades = new ArrayList<>();

    public ShadowOrder executeShadowOrder(TradeSignal signal, MarketData data) {
        if (signal == null || signal.direction == TradeDirection.WAIT) {
            return ShadowOrder.notFilled();
        }

        TradeDirection dir = signal.direction;
        double price = data.getLastPrice();

        if (currentPosition == 0 && dir != TradeDirection.CLOSE) {
            return openPosition(dir, price);
        }

        if (currentPosition != 0 && dir == TradeDirection.CLOSE) {
            return closePosition(price);
        }

        if (currentPosition != 0 && dir != TradeDirection.CLOSE && dir != currentDirection) {
            ShadowOrder closeOrder = closePosition(price);
            ShadowOrder openOrder = openPosition(dir, price);
            return combineOrders(closeOrder, openOrder);
        }

        if (currentPosition != 0 && dir == currentDirection) {
            return updatePosition(price);
        }

        return ShadowOrder.notFilled();
    }

    private ShadowOrder openPosition(TradeDirection dir, double price) {
        currentPosition = 1.0;
        avgEntryPrice = price;
        currentDirection = dir;

        return new ShadowOrder(true, dir, price, price, currentPosition, 0, 0, 0, false, System.currentTimeMillis(), 0);
    }

    private ShadowOrder closePosition(double price) {
        double pnl = calculatePnl(price);
        double returnPct = (price - avgEntryPrice) / avgEntryPrice * 100;
        if (currentDirection == TradeDirection.SHORT) {
            pnl = -pnl;
            returnPct = -returnPct;
        }

        ShadowTrade trade = new ShadowTrade(currentDirection, avgEntryPrice, price, pnl, returnPct, System.currentTimeMillis());
        trades.add(trade);

        double realizedPnl = pnl;
        double closedPosition = currentPosition;

        currentPosition = 0;
        avgEntryPrice = 0;
        currentDirection = null;

        return new ShadowOrder(true, TradeDirection.CLOSE, avgEntryPrice, price, closedPosition, 0, realizedPnl, returnPct, pnl > 0, trade.getTimestamp(), 0);
    }

    private ShadowOrder updatePosition(double price) {
        double pnl = calculatePnl(price);
        if (currentDirection == TradeDirection.SHORT) {
            pnl = -pnl;
        }

        return new ShadowOrder(false, currentDirection, avgEntryPrice, price, currentPosition, pnl, 0, 0, false, System.currentTimeMillis(), 0);
    }

    private ShadowOrder combineOrders(ShadowOrder closeOrder, ShadowOrder openOrder) {
        return new ShadowOrder(
            closeOrder.isFilled() && openOrder.isFilled(),
            openOrder.getDirection(),
            openOrder.getEntryPrice(),
            openOrder.getExitPrice(),
            openOrder.getPosition(),
            openOrder.getUnrealizedPnl(),
            closeOrder.getRealizedPnl(),
            0,
            closeOrder.isWin(),
            openOrder.getTimestamp(),
            0
        );
    }

    private double calculatePnl(double currentPrice) {
        if (currentDirection == TradeDirection.LONG) {
            return (currentPrice - avgEntryPrice) * currentPosition;
        } else if (currentDirection == TradeDirection.SHORT) {
            return (avgEntryPrice - currentPrice) * currentPosition;
        }
        return 0;
    }

    public double getCurrentPosition() { return currentPosition; }
    public double getAvgEntryPrice() { return avgEntryPrice; }
    public TradeDirection getCurrentDirection() { return currentDirection; }
    public List<ShadowTrade> getTrades() { return new ArrayList<>(trades); }

    // ========== 内部类 ==========

    public static class ShadowOrder {
        private final boolean isFilled;
        private final TradeDirection direction;
        private final double entryPrice;
        private final double exitPrice;
        private final double position;
        private final double unrealizedPnl;
        private final double realizedPnl;
        private final double returnPercent;
        private final boolean isWin;
        private final long timestamp;
        private final int holdingBars;

        public ShadowOrder(boolean isFilled, TradeDirection direction, double entryPrice,
                           double exitPrice, double position, double unrealizedPnl,
                           double realizedPnl, double returnPercent, boolean isWin,
                           long timestamp, int holdingBars) {
            this.isFilled = isFilled;
            this.direction = direction;
            this.entryPrice = entryPrice;
            this.exitPrice = exitPrice;
            this.position = position;
            this.unrealizedPnl = unrealizedPnl;
            this.realizedPnl = realizedPnl;
            this.returnPercent = returnPercent;
            this.isWin = isWin;
            this.timestamp = timestamp;
            this.holdingBars = holdingBars;
        }

        public static ShadowOrder notFilled() {
            return new ShadowOrder(false, TradeDirection.WAIT, 0, 0, 0, 0, 0, 0, false, 0, 0);
        }

        public boolean isFilled() { return isFilled; }
        public TradeDirection getDirection() { return direction; }
        public double getEntryPrice() { return entryPrice; }
        public double getExitPrice() { return exitPrice; }
        public double getPosition() { return position; }
        public double getUnrealizedPnl() { return unrealizedPnl; }
        public double getRealizedPnl() { return realizedPnl; }
        public double getReturnPercent() { return returnPercent; }
        public boolean isWin() { return isWin; }
        public long getTimestamp() { return timestamp; }
        public int getHoldingBars() { return holdingBars; }
        public double getPnl() { return realizedPnl + unrealizedPnl; }
    }

    public static class ShadowTrade {
        private final TradeDirection direction;
        private final double entryPrice;
        private final double exitPrice;
        private final double pnl;
        private final double returnPercent;
        private final long timestamp;

        public ShadowTrade(TradeDirection direction, double entryPrice, double exitPrice,
                          double pnl, double returnPercent, long timestamp) {
            this.direction = direction;
            this.entryPrice = entryPrice;
            this.exitPrice = exitPrice;
            this.pnl = pnl;
            this.returnPercent = returnPercent;
            this.timestamp = timestamp;
        }

        public TradeDirection getDirection() { return direction; }
        public double getEntryPrice() { return entryPrice; }
        public double getExitPrice() { return exitPrice; }
        public double getPnl() { return pnl; }
        public double getReturnPercent() { return returnPercent; }
        public long getTimestamp() { return timestamp; }
    }
}
