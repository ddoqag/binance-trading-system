package com.trading.infrastructure.execution.cache;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 账户状态存储
 *
 * <p>存储账户级别的状态：
 * <ul>
 *   <li>钱包余额</li>
 *   <li>可用余额</li>
 *   <li>总保证金</li>
 *   <li>未实现盈亏</li>
 *   <li>持仓数量</li>
 * </ul>
 *
 * <p>由 USER_DATA WebSocket 的 ACCOUNT_UPDATE 事件驱动更新
 */
public class AccountStateStore {

    private static final Logger log = LoggerFactory.getLogger(AccountStateStore.class);

    // 单例
    private static volatile AccountStateStore instance;

    // 账户余额
    private volatile double walletBalance = 0.0;
    private volatile double totalMargin = 0.0;
    private volatile double availableBalance = 0.0;
    private volatile double unrealizedPnl = 0.0;

    // 持仓汇总
    private volatile int positionCount = 0;
    private volatile double totalPositionValue = 0.0;

    // 最后更新
    private volatile long lastUpdateTime = 0;

    // 历史记录（用于分析）
    private final Map<String, BalanceSnapshot> balanceHistory = new ConcurrentHashMap<>();

    private AccountStateStore() {
    }

    public static AccountStateStore getInstance() {
        if (instance == null) {
            synchronized (AccountStateStore.class) {
                if (instance == null) {
                    instance = new AccountStateStore();
                }
            }
        }
        return instance;
    }

    /**
     * 更新账户（从 ACCOUNT_UPDATE 事件）
     */
    public void updateFromAccountUpdate(double walletBalance, double totalMargin,
                                         double availableBalance, double unrealizedPnl) {
        boolean changed = false;

        if (Math.abs(this.walletBalance - walletBalance) > 0.01) {
            changed = true;
        }

        this.walletBalance = walletBalance;
        this.totalMargin = totalMargin;
        this.availableBalance = availableBalance;
        this.unrealizedPnl = unrealizedPnl;
        this.lastUpdateTime = System.currentTimeMillis();

        if (changed) {
            log.info("[AccountStateStore] Account updated: wallet={} margin={} avail={} pnl={}",
                    walletBalance, totalMargin, availableBalance, unrealizedPnl);
        }
    }

    /**
     * 更新持仓汇总
     */
    public void updatePositionSummary(int count, double totalValue) {
        this.positionCount = count;
        this.totalPositionValue = totalValue;
    }

    /**
     * 记录余额快照
     */
    public void recordSnapshot(String reason) {
        long now = System.currentTimeMillis();
        BalanceSnapshot snapshot = new BalanceSnapshot(
                now,
                walletBalance,
                totalMargin,
                availableBalance,
                unrealizedPnl,
                reason
        );
        balanceHistory.put(String.valueOf(now), snapshot);

        // 保留最近 100 条
        if (balanceHistory.size() > 100) {
            balanceHistory.remove(balanceHistory.keySet().iterator().next());
        }
    }

    // Getters
    public double getWalletBalance() {
        return walletBalance;
    }

    public double getTotalMargin() {
        return totalMargin;
    }

    public double getAvailableBalance() {
        return availableBalance;
    }

    public double getUnrealizedPnl() {
        return unrealizedPnl;
    }

    public int getPositionCount() {
        return positionCount;
    }

    public double getTotalPositionValue() {
        return totalPositionValue;
    }

    public long getLastUpdateTime() {
        return lastUpdateTime;
    }

    public Map<String, BalanceSnapshot> getBalanceHistory() {
        return Map.copyOf(balanceHistory);
    }

    public double getTotalBalance() {
        return walletBalance + unrealizedPnl;
    }

    public double getMarginRatio() {
        if (totalPositionValue == 0) {
            return 0;
        }
        return totalMargin / totalPositionValue;
    }

    @Override
    public String toString() {
        return String.format(
                "AccountStateStore{wallet=%.2f margin=%.2f avail=%.2f pnl=%.2f positions=%d}",
                walletBalance, totalMargin, availableBalance, unrealizedPnl, positionCount
        );
    }

    /**
     * 余额快照
     */
    public static class BalanceSnapshot {
        public final long timestamp;
        public final double walletBalance;
        public final double totalMargin;
        public final double availableBalance;
        public final double unrealizedPnl;
        public final String reason;

        public BalanceSnapshot(long timestamp, double walletBalance, double totalMargin,
                               double availableBalance, double unrealizedPnl, String reason) {
            this.timestamp = timestamp;
            this.walletBalance = walletBalance;
            this.totalMargin = totalMargin;
            this.availableBalance = availableBalance;
            this.unrealizedPnl = unrealizedPnl;
            this.reason = reason;
        }
    }
}