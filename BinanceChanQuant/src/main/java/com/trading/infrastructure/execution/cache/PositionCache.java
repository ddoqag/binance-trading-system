package com.trading.infrastructure.execution.cache;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * WebSocket 事件驱动的仓位缓存
 *
 * <p>替代 REST 轮询，通过 USER_DATA WebSocket 事件更新仓位：
 * <ul>
 *   <li>ORDER_TRADE_UPDATE → 更新持仓和盈亏</li>
 *   <li>ACCOUNT_UPDATE → 更新余额/保证金</li>
 *   <li>自动过期：60秒无事件则标记为 stale</li>
 * </ul>
 *
 * <p>重要：此组件是 event-driven 架构的核心，避免轮询带来的延迟和不一致。
 */
public class PositionCache {

    private static final Logger log = LoggerFactory.getLogger(PositionCache.class);

    // 仓位数据
    private final Map<String, CachedPosition> positions = new ConcurrentHashMap<>();

    // 账户数据
    private volatile CachedAccount account;

    // 最后更新时间（用于 stale 检测）
    private final AtomicLong lastUpdateTime = new AtomicLong(System.currentTimeMillis());

    // Stale 阈值：60秒无更新则认为数据过期
    private static final long STALE_THRESHOLD_MS = 60_000;

    public PositionCache() {
    }

    /**
     * 更新持仓（ORDER_TRADE_UPDATE 事件触发）
     */
    public void updatePosition(String symbol, PositionUpdate update) {
        CachedPosition cached = positions.compute(symbol, (k, existing) -> {
            if (existing == null) {
                return new CachedPosition(symbol, update);
            }
            return existing.apply(update);
        });

        lastUpdateTime.set(System.currentTimeMillis());
        log.debug("[PositionCache] Position updated: {} size={} avgPx={}",
                symbol, cached.size, cached.avgEntryPrice);
    }

    /**
     * 更新账户（ACCOUNT_UPDATE 事件触发）
     */
    public void updateAccount(AccountUpdate update) {
        if (account == null) {
            account = new CachedAccount(update);
        } else {
            account = account.apply(update);
        }
        lastUpdateTime.set(System.currentTimeMillis());
        log.debug("[PositionCache] Account updated: balance={} margin={}",
                account.walletBalance, account.availableBalance);
    }

    /**
     * 全量同步（从 REST 查询）
     */
    public void syncPositions(Map<String, PositionData> positionsData) {
        positions.clear();
        positionsData.forEach((symbol, data) -> {
            positions.put(symbol, new CachedPosition(symbol, data));
        });
        lastUpdateTime.set(System.currentTimeMillis());
        log.info("[PositionCache] Positions synced: {} symbols", positions.size());
    }

    /**
     * 获取持仓
     */
    public CachedPosition getPosition(String symbol) {
        return positions.get(symbol);
    }

    /**
     * 获取账户
     */
    public CachedAccount getAccount() {
        return account;
    }

    /**
     * 获取所有持仓
     */
    public Map<String, CachedPosition> getAllPositions() {
        return Map.copyOf(positions);
    }

    /**
     * 获取总持仓（所有symbol）
     */
    public double getTotalPosition() {
        return positions.values().stream()
                .mapToDouble(pos -> pos.size)
                .sum();
    }

    /**
     * 数据是否过期
     */
    public boolean isStale() {
        return System.currentTimeMillis() - lastUpdateTime.get() > STALE_THRESHOLD_MS;
    }

    /**
     * 获取最后更新时间
     */
    public long getLastUpdateTime() {
        return lastUpdateTime.get();
    }

    /**
     * 清理所有缓存
     */
    public void clear() {
        positions.clear();
        account = null;
        log.info("[PositionCache] Cleared");
    }

    // ========== 内部类 ==========

    /**
     * 缓存的持仓
     */
    public static class CachedPosition {
        public final String symbol;
        public final double size;
        public final double avgEntryPrice;
        public final double unrealizedPnl;
        public final double realizedPnl;
        public final double liquidationPrice;
        public final long updateTime;

        public CachedPosition(String symbol, PositionData data) {
            this.symbol = symbol;
            this.size = data.size;
            this.avgEntryPrice = data.avgEntryPrice;
            this.unrealizedPnl = data.unrealizedPnl;
            this.realizedPnl = data.realizedPnl;
            this.liquidationPrice = data.liquidationPrice;
            this.updateTime = System.currentTimeMillis();
        }

        public CachedPosition(String symbol, PositionUpdate update) {
            this.symbol = symbol;
            this.size = update.size;
            this.avgEntryPrice = update.avgEntryPrice;
            this.unrealizedPnl = update.unrealizedPnl;
            this.realizedPnl = update.realizedPnl;
            this.liquidationPrice = update.liquidationPrice;
            this.updateTime = System.currentTimeMillis();
        }

        public CachedPosition apply(PositionUpdate update) {
            return new CachedPosition(symbol, update);
        }

        public boolean isFlat() {
            return Math.abs(size) < 0.001;
        }

        @Override
        public String toString() {
            return String.format("CachedPosition{symbol=%s size=%.4f avgPx=%.2f pnl=%.2f}",
                    symbol, size, avgEntryPrice, unrealizedPnl);
        }
    }

    /**
     * 缓存的账户
     */
    public static class CachedAccount {
        public final double walletBalance;
        public final double availableBalance;
        public final double totalMargin;
        public final double unrealizedPnl;
        public final long updateTime;

        public CachedAccount(AccountUpdate update) {
            this.walletBalance = update.walletBalance;
            this.availableBalance = update.availableBalance;
            this.totalMargin = update.totalMargin;
            this.unrealizedPnl = update.unrealizedPnl;
            this.updateTime = System.currentTimeMillis();
        }

        public CachedAccount apply(AccountUpdate update) {
            return new CachedAccount(update);
        }

        @Override
        public String toString() {
            return String.format("CachedAccount{balance=%.2f avail=%.2f margin=%.2f}",
                    walletBalance, availableBalance, totalMargin);
        }
    }

    /**
     * 仓位数据（来自 REST）
     */
    public static class PositionData {
        public final double size;
        public final double avgEntryPrice;
        public final double unrealizedPnl;
        public final double realizedPnl;
        public final double liquidationPrice;

        public PositionData(double size, double avgEntryPrice, double unrealizedPnl,
                           double realizedPnl, double liquidationPrice) {
            this.size = size;
            this.avgEntryPrice = avgEntryPrice;
            this.unrealizedPnl = unrealizedPnl;
            this.realizedPnl = realizedPnl;
            this.liquidationPrice = liquidationPrice;
        }
    }

    /**
     * 仓位更新（来自 WebSocket）
     */
    public static class PositionUpdate {
        public final double size;
        public final double avgEntryPrice;
        public final double unrealizedPnl;
        public final double realizedPnl;
        public final double liquidationPrice;

        public PositionUpdate(double size, double avgEntryPrice, double unrealizedPnl,
                             double realizedPnl, double liquidationPrice) {
            this.size = size;
            this.avgEntryPrice = avgEntryPrice;
            this.unrealizedPnl = unrealizedPnl;
            this.realizedPnl = realizedPnl;
            this.liquidationPrice = liquidationPrice;
        }
    }

    /**
     * 账户更新（来自 WebSocket）
     */
    public static class AccountUpdate {
        public final double walletBalance;
        public final double availableBalance;
        public final double totalMargin;
        public final double unrealizedPnl;

        public AccountUpdate(double walletBalance, double availableBalance,
                            double totalMargin, double unrealizedPnl) {
            this.walletBalance = walletBalance;
            this.availableBalance = availableBalance;
            this.totalMargin = totalMargin;
            this.unrealizedPnl = unrealizedPnl;
        }
    }
}