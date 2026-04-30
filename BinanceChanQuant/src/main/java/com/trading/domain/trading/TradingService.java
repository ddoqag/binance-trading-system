package com.trading.domain.trading;

import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.ExecutionReport;
import java.util.List;
import java.util.Optional;

/**
 * 交易服务接口 - 抽象交易执行的核心行为
 *
 * <p>这是Domain层的核心接口，定义了交易系统必须提供的能力：
 * <ul>
 *   <li>订单执行 - 提交和管理订单</li>
 *   <li>持仓查询 - 获取当前持仓状态</li>
 *   <li>订单查询 - 获取挂单和历史</li>
 *   <li>服务状态 - 启动/停止健康检查</li>
 * </ul>
 *
 * <p>实现类：
 * <ul>
 *   <li>LegacyTradingServiceImpl - 包装现有HFTEngine</li>
 *   <li>NewTradingServiceImpl - 使用新的ExecutionEngine</li>
 * </ul>
 */
public interface TradingService {

    /**
     * 提交订单
     *
     * @param order 订单信息
     * @return true=提交成功, false=提交失败或被风控拒绝
     */
    boolean submitOrder(Order order);

    /**
     * 提交订单（带回调）
     *
     * @param order 订单信息
     * @param callback 执行完成回调
     * @return true=提交成功
     */
    boolean submitOrder(Order order, ExecutionCallback callback);

    /**
     * 取消订单
     *
     * @param orderId 订单ID
     * @return true=取消成功
     */
    boolean cancelOrder(String orderId);

    /**
     * 取消所有订单
     */
    int cancelAllOrders();

    /**
     * 获取当前持仓
     *
     * @param symbol 交易品种
     * @return 持仓信息
     */
    PositionInfo getPosition(String symbol);

    /**
     * 获取所有持仓
     */
    List<PositionInfo> getAllPositions();

    /**
     * 获取未成交订单
     */
    List<OrderInfo> getOpenOrders();

    /**
     * 获取订单历史
     *
     * @param limit 返回数量限制
     */
    List<OrderInfo> getOrderHistory(int limit);

    /**
     * 启动交易服务
     */
    void start();

    /**
     * 停止交易服务
     */
    void stop();

    /**
     * 健康检查
     *
     * @return true=服务正常
     */
    boolean isHealthy();

    /**
     * 获取服务名称
     */
    String getServiceName();

    // ========== 回调接口 ==========

    interface ExecutionCallback {
        void onSubmitted(Order order);
        void onFilled(Order order, ExecutionReport report);
        void onCancelled(Order order);
        void onRejected(Order order, String reason);
    }

    // ========== 数据对象 ==========

    /**
     * 持仓信息
     */
    class PositionInfo {
        private final String symbol;
        private final double size;
        private final double avgPrice;
        private final double unrealizedPnl;
        private final double realizedPnl;
        private final long timestamp;

        public PositionInfo(String symbol, double size, double avgPrice,
                           double unrealizedPnl, double realizedPnl, long timestamp) {
            this.symbol = symbol;
            this.size = size;
            this.avgPrice = avgPrice;
            this.unrealizedPnl = unrealizedPnl;
            this.realizedPnl = realizedPnl;
            this.timestamp = timestamp;
        }

        public String getSymbol() { return symbol; }
        public double getSize() { return size; }
        public double getAvgPrice() { return avgPrice; }
        public double getUnrealizedPnl() { return unrealizedPnl; }
        public double getRealizedPnl() { return realizedPnl; }
        public long getTimestamp() { return timestamp; }

        public boolean isLong() { return size > 0; }
        public boolean isShort() { return size < 0; }
        public boolean isFlat() { return size == 0; }
    }

    /**
     * 订单信息
     */
    class OrderInfo {
        private final String orderId;
        private final String symbol;
        private final String side;
        private final String type;
        private final double quantity;
        private final double price;
        private final double filledQuantity;
        private final String status;
        private final long createTime;
        private final long updateTime;

        public OrderInfo(String orderId, String symbol, String side, String type,
                        double quantity, double price, double filledQuantity,
                        String status, long createTime, long updateTime) {
            this.orderId = orderId;
            this.symbol = symbol;
            this.side = side;
            this.type = type;
            this.quantity = quantity;
            this.price = price;
            this.filledQuantity = filledQuantity;
            this.status = status;
            this.createTime = createTime;
            this.updateTime = updateTime;
        }

        public String getOrderId() { return orderId; }
        public String getSymbol() { return symbol; }
        public String getSide() { return side; }
        public String getType() { return type; }
        public double getQuantity() { return quantity; }
        public double getPrice() { return price; }
        public double getFilledQuantity() { return filledQuantity; }
        public String getStatus() { return status; }
        public long getCreateTime() { return createTime; }
        public long getUpdateTime() { return updateTime; }
    }
}