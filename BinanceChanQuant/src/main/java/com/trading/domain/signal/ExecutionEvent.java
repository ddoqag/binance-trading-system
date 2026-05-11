package com.trading.domain.signal;

import com.trading.domain.trading.model.TradeDirection;

import java.util.Map;

/**
 * ExecutionFeedbackBus 核心事件结构
 * 记录信号从生成到执行的完整生命周期
 *
 * 用于 V6 架构的"闭环控制":
 * - Signal → AlphaPool → Order → ExecutionEngine → Feedback → AlphaPool/Telemetry
 *
 * 通过 correlationId (对应 AlphaSignal.alphaId) 追踪每个信号的完整生命周期
 */
public final class ExecutionEvent {

    public enum ExecutionEventType {
        // ===== 信号级事件 =====
        SIGNAL_GENERATED("信号已生成"),
        SIGNAL_BLOCKED_BY_COOLDOWN("信号被冷却拦截"),
        SIGNAL_BLOCKED_BY_RISK("信号被风控拦截"),
        SIGNAL_BLOCKED_BY_DIRECTION("信号被方向过滤器拦截"),
        SIGNAL_ABSTAINED("信号主动弃权"),
        SIGNAL_LOW_CONFIDENCE("信号置信度不足"),

        // ===== 订单级事件 =====
        ORDER_SUBMITTED("订单已提交到交易所"),
        ORDER_REJECTED_BY_EXCHANGE("订单被交易所拒绝"),
        ORDER_PARTIALLY_FILLED("订单部分成交"),
        ORDER_FILLED("订单完全成交"),
        ORDER_CANCELLED("订单已取消"),

        // ===== 盈亏反馈事件 =====
        SIGNAL_PROFITABLE("信号产生盈利"),
        SIGNAL_LOSS("信号产生亏损"),

        // ===== 元学习事件 =====
        EXPERT_PARTICIPATION_UPDATED("专家参与度更新"),
        COOLDOWN_STATUS_UPDATED("冷却状态更新");

        private final String description;

        ExecutionEventType(String description) {
            this.description = description;
        }

        public String getDescription() { return description; }
    }

    private final String correlationId;   // 对应 AlphaSignal.alphaId，追踪ID
    private final String expertId;        // 信号来源 expert (e.g., "ai", "chan")
    private final ExecutionEventType type;
    private final String symbol;
    private final TradeDirection direction;
    private final Map<String, Object> metadata;  // 扩展信息
    private final long timestamp;

    private ExecutionEvent(String correlationId, String expertId, ExecutionEventType type,
                          String symbol, TradeDirection direction, Map<String, Object> metadata,
                          long timestamp) {
        this.correlationId = correlationId;
        this.expertId = expertId;
        this.type = type;
        this.symbol = symbol;
        this.direction = direction;
        this.metadata = metadata;
        this.timestamp = timestamp;
    }

    public String correlationId() { return correlationId; }
    public String expertId() { return expertId; }
    public ExecutionEventType type() { return type; }
    public String symbol() { return symbol; }
    public TradeDirection direction() { return direction; }
    public Map<String, Object> metadata() { return metadata; }
    public long timestamp() { return timestamp; }

    public static Builder builder() { return new Builder(); }

    @Override
    public String toString() {
        return String.format("[ExecutionEvent] %s | expert=%s | symbol=%s | dir=%s | ts=%d",
            type.name(), expertId, symbol, direction, timestamp);
    }

    public static final class Builder {
        private String correlationId;
        private String expertId;
        private ExecutionEventType type;
        private String symbol;
        private TradeDirection direction;
        private Map<String, Object> metadata;
        private long timestamp = System.currentTimeMillis();

        public Builder correlationId(String v) { correlationId = v; return this; }
        public Builder expertId(String v) { expertId = v; return this; }
        public Builder type(ExecutionEventType v) { type = v; return this; }
        public Builder symbol(String v) { symbol = v; return this; }
        public Builder direction(TradeDirection v) { direction = v; return this; }
        public Builder metadata(Map<String, Object> v) { metadata = v; return this; }
        public Builder putMeta(String key, Object value) {
            if (metadata == null) metadata = new java.util.HashMap<>();
            metadata.put(key, value);
            return this;
        }

        public ExecutionEvent build() {
            return new ExecutionEvent(correlationId, expertId, type, symbol, direction, metadata, timestamp);
        }
    }
}