package com.trading.execution.v6;

/**
 * AccountState - 账户状态（V6核心依赖）
 *
 * 从 Binance USER_DATA Stream 实时同步
 */
public class AccountState {

    private double walletBalance;
    private double availableBalance;
    private double unrealizedPnL;
    private double totalEquity;
    private long lastUpdate;

    public AccountState() {
        this.lastUpdate = System.currentTimeMillis();
    }

    public AccountState(double walletBalance, double unrealizedPnL) {
        this.walletBalance = walletBalance;
        this.unrealizedPnL = unrealizedPnL;
        this.totalEquity = walletBalance + unrealizedPnL;
        this.lastUpdate = System.currentTimeMillis();
    }

    /**
     * 总权益 = 钱包余额 + 未实现盈亏
     */
    public double getEquity() {
        return totalEquity;
    }

    /**
     * 可用保证金（考虑未实现盈亏）
     */
    public double getAvailableMargin() {
        return availableBalance;
    }

    public double getWalletBalance() { return walletBalance; }
    public void setWalletBalance(double walletBalance) {
        this.walletBalance = walletBalance;
        this.totalEquity = walletBalance + unrealizedPnL;
    }

    public double getAvailableBalance() { return availableBalance; }
    public void setAvailableBalance(double availableBalance) { this.availableBalance = availableBalance; }

    public double getUnrealizedPnL() { return unrealizedPnL; }
    public void setUnrealizedPnL(double unrealizedPnL) {
        this.unrealizedPnL = unrealizedPnL;
        this.totalEquity = walletBalance + unrealizedPnL;
    }

    public long getLastUpdate() { return lastUpdate; }
    public void setLastUpdate(long lastUpdate) { this.lastUpdate = lastUpdate; }

    /**
     * 更新所有字段
     */
    public void update(double walletBalance, double availableBalance, double unrealizedPnL) {
        this.walletBalance = walletBalance;
        this.availableBalance = availableBalance;
        this.unrealizedPnL = unrealizedPnL;
        this.totalEquity = walletBalance + unrealizedPnL;
        this.lastUpdate = System.currentTimeMillis();
    }

    @Override
    public String toString() {
        return String.format("AccountState{wb=%.2f, avail=%.2f, unrealized=%.2f, equity=%.2f}",
            walletBalance, availableBalance, unrealizedPnL, totalEquity);
    }
}