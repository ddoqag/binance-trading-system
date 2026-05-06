package com.trading.execution.v6;

/**
 * Position - 统一仓位结构
 *
 * Binance 真实仓位（带符号）
 * 正数 = LONG, 负数 = SHORT, 0 = 平仓
 */
public class Position {

    private String symbol;
    private double quantity;      // 正=LONG，负=SHORT
    private double entryPrice;
    private double unrealizedPnL;
    private double leverage;
    private long lastUpdate;

    public Position() {}

    public Position(String symbol, double quantity, double entryPrice, double unrealizedPnL, double leverage) {
        this.symbol = symbol;
        this.quantity = quantity;
        this.entryPrice = entryPrice;
        this.unrealizedPnL = unrealizedPnL;
        this.leverage = leverage;
        this.lastUpdate = System.currentTimeMillis();
    }

    public boolean isLong() { return quantity > 0; }
    public boolean isShort() { return quantity < 0; }
    public boolean isFlat() { return Math.abs(quantity) < 1e-8; }

    public String getSymbol() { return symbol; }
    public void setSymbol(String symbol) { this.symbol = symbol; }

    public double getQuantity() { return quantity; }
    public void setQuantity(double quantity) { this.quantity = quantity; }

    public double getEntryPrice() { return entryPrice; }
    public void setEntryPrice(double entryPrice) { this.entryPrice = entryPrice; }

    public double getUnrealizedPnL() { return unrealizedPnL; }
    public void setUnrealizedPnL(double unrealizedPnL) { this.unrealizedPnL = unrealizedPnL; }

    public double getLeverage() { return leverage; }
    public void setLeverage(double leverage) { this.leverage = leverage; }

    public long getLastUpdate() { return lastUpdate; }
    public void setLastUpdate(long lastUpdate) { this.lastUpdate = lastUpdate; }

    @Override
    public String toString() {
        return String.format("Position{symbol=%s, qty=%.4f, entry=%.2f, unrealizedPnL=%.2f, leverage=%.0fx}",
            symbol, quantity, entryPrice, unrealizedPnL, leverage);
    }
}