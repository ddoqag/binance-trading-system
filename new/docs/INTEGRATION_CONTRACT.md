# HFT 系统集成契约 (Integration Contract)

> Go 执行引擎 <-> Python AI 大脑 共享内存接口规范
> 版本: 1.0
> 最后更新: 2026-04-07

## 1. 概述

本文档定义了 HFT 系统中 Go 执行引擎与 Python AI 大脑之间的所有集成点契约，包括共享内存协议、消息格式、版本控制和兼容性检查机制。

## 2. 共享内存布局

### 2.1 内存映射总览

```
+----------------------------------------------------------+
| 地址偏移 | 区域名称          | 大小      | 描述          |
+----------------------------------------------------------+
| 0x0000   | SharedMemoryHeader | 动态计算  | 协议头部      |
| 0x1000   | AIContext         | 64 bytes  | AI决策上下文  |
| 0x2000   | Go -> Python Ring | ~32KB     | 市场数据环    |
| 0xA000   | Python -> Go Ring | ~32KB     | 订单命令环    |
| 0x12000  | AccountInfo Cache | 56 bytes  | 账户信息缓存  |
| 0x13000  | Features Output   | 640 bytes | 特征工程输出  |
| 0x13280  | Signal Input      | 256 bytes | 模型信号输入  |
| 0x4000   | ReversalFeatures  | 640 bytes | 反转特征      |
| 0x4280   | ReversalSignal    | 256 bytes | 反转信号      |
| 0x4364   | Verification      | 288 bytes | 真实性检验    |
+----------------------------------------------------------+
总大小: 64MB (HFT_SHM_SIZE_DEFAULT)
```

### 2.2 固定偏移量定义

| 常量名 | 值 | 说明 |
|--------|-----|------|
| HFT_HEADER_OFFSET | 0 | 头部起始偏移 |
| HFT_AI_CONTEXT_OFFSET | 4096 (0x1000) | AIContext 偏移 |
| HFT_FEATURES_OFFSET | 16384 (0x4000) | 特征输出偏移 |
| HFT_SIGNAL_OFFSET | 17024 (0x4280) | 信号输入偏移 |
| REVERSAL_FEATURES_OFFSET | 16384 (0x4000) | 反转特征偏移 |
| REVERSAL_SIGNAL_OFFSET | 17024 (0x4280) | 反转信号偏移 |
| VERIFICATION_METRICS_OFFSET | 17252 (0x4364) | 真实性检验偏移 |
| HFT_BUFFER_START | sizeof(SharedMemoryHeader) | 环形缓冲区起始 |

## 3. 协议头部 (SharedMemoryHeader)

### 3.1 C 结构定义 (protocol.h)

```c
typedef struct {
    uint32_t magic;               // 0x48465453 "HFTS"
    uint32_t version;             // 协议版本 (当前=1)
    uint64_t size_bytes;         // 总共享内存大小

    // 环形缓冲区索引
    volatile uint64_t go_write_index;   // Go写入位置
    volatile uint64_t go_read_index;    // Go读取位置
    volatile uint64_t ai_write_index;   // AI写入位置
    volatile uint64_t ai_read_index;    // AI读取位置

    // 统计信息
    uint64_t messages_sent_go;    // Go发送消息数
    uint64_t messages_sent_ai;    // AI发送消息数
    uint64_t messages_lost;       // 丢失消息数

    // 心跳时间戳
    uint64_t last_heartbeat_go_ns;
    uint64_t last_heartbeat_ai_ns;

    // 当前状态
    Heartbeat last_heartbeat;
    AccountInfo account_info;
    MarketSnapshot last_market_snapshot;
} SharedMemoryHeader;
```

### 3.2 字段对齐要求

- 所有 uint64_t 字段必须 8 字节对齐
- 所有 double 字段必须 8 字节对齐
- 结构体总大小必须是 8 的倍数
- 使用 `#pragma pack(push, 1)` 确保紧凑布局

## 4. 消息类型定义

### 4.1 消息类型枚举

```c
typedef enum {
    MSG_TYPE_HEARTBEAT       = 0,   // 心跳
    MSG_TYPE_MARKET_SNAPSHOT = 1,   // 市场快照 (Go -> Python)
    MSG_TYPE_ORDER_COMMAND   = 2,   // 订单命令 (Python -> Go)
    MSG_TYPE_ORDER_STATUS    = 3,   // 订单状态 (Go -> Python)
    MSG_TYPE_TRADE_EXECUTION = 4,   // 成交执行 (Go -> Python)
    MSG_TYPE_SYNC_REQUEST    = 5,   // 同步请求
    MSG_TYPE_SYNC_RESPONSE   = 6,   // 同步响应
} MessageType;
```

### 4.2 订单方向

```c
typedef enum {
    SIDE_BUY  = 1,
    SIDE_SELL = 2,
} OrderSide;
```

### 4.3 订单类型

```c
typedef enum {
    ORDER_TYPE_LIMIT   = 1,
    ORDER_TYPE_MARKET  = 2,
    ORDER_TYPE_CANCEL  = 3,
} OrderType;
```

### 4.4 订单状态

```c
typedef enum {
    STATUS_NEW       = 0,
    STATUS_PENDING   = 1,
    STATUS_PARTIAL   = 2,
    STATUS_FILLED    = 3,
    STATUS_CANCELED  = 4,
    STATUS_REJECTED  = 5,
    STATUS_EXPIRED   = 6,
} OrderStatus;
```

## 5. 数据结构定义

### 5.1 PriceLevel (订单簿档位)

```c
typedef struct {
    double price;        // 8 bytes
    double quantity;     // 8 bytes
    uint32_t orders;     // 4 bytes
} PriceLevel;            // 总计: 20 bytes
```

### 5.2 MarketSnapshot (市场快照)

**Go -> Python 方向，包含完整市场状态**

```c
typedef struct {
    uint64_t timestamp_ns;              // 时间戳 (纳秒)
    uint64_t sequence;                  // 序列号

    uint32_t num_bids;                  // 实际买盘档位数
    uint32_t num_asks;                  // 实际卖盘档位数
    PriceLevel bids[20];                // 买盘档位 (固定20档)
    PriceLevel asks[20];                // 卖盘档位 (固定20档)

    double best_bid;
    double best_ask;
    double last_price;
    double micro_price;                 // 微观价格

    double order_flow_imbalance;        // OFI
    double trade_imbalance;             // 成交不平衡

    double bid_queue_position;          // 买单队列位置 [0,1]
    double ask_queue_position;          // 卖单队列位置 [0,1]

    double spread;                      // 价差
    double volatility_estimate;         // 波动率估计
    double trade_intensity;             // 交易强度

    double adverse_score;               // 逆向选择分数
    double toxic_probability;           // 毒流概率
} MarketSnapshot;
```

**大小计算:**
- 基础字段: 8 + 8 + 4 + 4 = 24 bytes
- 订单簿: 20 * 20 + 20 * 20 = 800 bytes
- 价格字段: 8 * 4 = 32 bytes
- 特征字段: 8 * 10 = 80 bytes
- **总计: ~936 bytes** (实际以编译器为准)

### 5.3 OrderCommand (订单命令)

**Python -> Go 方向**

```c
typedef struct {
    uint64_t command_id;          // 命令ID (唯一)
    uint64_t timestamp_ns;        // 时间戳
    OrderType order_type;         // 订单类型
    OrderSide side;               // 买卖方向
    double price;                 // 价格
    double quantity;              // 数量
    double max_slippage;          // 最大滑点 (bps)
    uint32_t expires_after_ms;    // 过期时间 (毫秒)
    uint8_t dry_run;              // 模拟执行标志
} OrderCommand;
```

**大小: 49 bytes** (需填充到 56 bytes 以 8 字节对齐)

### 5.4 OrderStatusUpdate (订单状态更新)

**Go -> Python 方向**

```c
typedef struct {
    uint64_t order_id;            // 订单ID
    uint64_t command_id;          // 对应命令ID
    uint64_t timestamp_ns;        // 时间戳
    OrderSide side;
    OrderType type;
    OrderStatus status;           // 当前状态
    double price;                 // 订单价格
    double original_quantity;     // 原始数量
    double filled_quantity;       // 已成交数量
    double remaining_quantity;    // 剩余数量
    double average_fill_price;    // 平均成交价格
    double latency_us;            // 延迟 (微秒)
    uint8_t is_maker;             // 是否 maker
} OrderStatusUpdate;
```

### 5.5 TradeExecution (成交执行)

**Go -> Python 方向，用于奖励计算**

```c
typedef struct {
    uint64_t trade_id;            // 成交ID
    uint64_t order_id;            // 订单ID
    uint64_t timestamp_ns;        // 时间戳
    OrderSide side;
    double price;                 // 成交价格
    double quantity;              // 成交数量
    double commission;            // 手续费
    double realized_pnl;          // 已实现盈亏
    double adverse_selection;     // 逆向选择成本
    uint8_t is_maker;             // 是否 maker
} TradeExecution;
```

### 5.6 Heartbeat (心跳)

```c
typedef struct {
    uint32_t magic;               // 魔数验证
    uint32_t version;             // 版本
    uint64_t timestamp_ns;        // 时间戳
    uint32_t sequence;            // 序列号
    uint8_t go_running;           // Go引擎状态
    uint8_t ai_running;           // AI引擎状态
} Heartbeat;                      // 大小: 20 bytes
```

### 5.7 AccountInfo (账户信息)

```c
typedef struct {
    double total_balance;         // 总余额
    double available_balance;     // 可用余额
    double position_size;         // 仓位 (正=多, 负=空)
    double entry_price;           // 入场价格
    double unrealized_pnl;        // 未实现盈亏
    double realized_pnl_today;    // 今日已实现盈亏
    uint32_t trades_today;        // 今日成交次数
} AccountInfo;                    // 大小: 52 bytes
```

### 5.8 AIContext (AI 决策上下文)

**Python -> Go 方向，位于固定偏移 4096**

```c
typedef struct {
    double ai_position;           // AI推荐仓位 [-1, +1]
    double ai_confidence;         // AI置信度 [0, 1]
    double moe_weight_0;          // 专家0权重
    double moe_weight_1;          // 专家1权重
    double moe_weight_2;          // 专家2权重
    double moe_weight_3;          // 专家3权重
    uint32_t regime_code;         // 市场状态编码
    uint32_t num_active_experts;  // 激活专家数
    uint32_t reserved[2];         // 保留对齐 (8 bytes)
} AIContext;                      // 大小: 64 bytes
```

## 6. 特征工程输出格式

### 6.1 特征向量布局 (偏移 0x4000)

```
+--------------------------------------------------+
| 字段              | 偏移   | 类型    | 大小     |
+--------------------------------------------------+
| ofi               | 0x00   | float64 | 8 bytes  |
| queue_ratio       | 0x08   | float64 | 8 bytes  |
| hazard_rate       | 0x10   | float64 | 8 bytes  |
| adverse_score     | 0x18   | float64 | 8 bytes  |
| toxic_prob        | 0x20   | float64 | 8 bytes  |
| spread            | 0x28   | float64 | 8 bytes  |
| micro_momentum    | 0x30   | float64 | 8 bytes  |
| volatility        | 0x38   | float64 | 8 bytes  |
| trade_flow        | 0x40   | float64 | 8 bytes  |
| inventory         | 0x48   | float64 | 8 bytes  |
| reserved[...]     | 0x50   | -       | 592 bytes|
+--------------------------------------------------+
总大小: 640 bytes
```

### 6.2 特征说明

| 特征名 | 范围 | 说明 |
|--------|------|------|
| ofi | [-1, +1] | 订单流不平衡 |
| queue_ratio | [0, 1] | 队列位置比率 |
| hazard_rate | [0, ∞) | 成交危险率 λ |
| adverse_score | [-1, +1] | 逆向选择分数 |
| toxic_prob | [0, 1] | 毒流概率 |
| spread | [0, ∞) | 买卖价差 (tick数) |
| micro_momentum | [-1, +1] | 微观动量 |
| volatility | [0, ∞) | 实现波动率 |
| trade_flow | [-1, +1] | 交易流方向 |
| inventory | [-1, +1] | 当前持仓压力 |

## 7. 模型预测输入/输出规范

### 7.1 输入 (Signal @ 0x4264)

```
+--------------------------------------------------+
| 字段              | 偏移   | 类型    | 大小     |
+--------------------------------------------------+
| action_direction  | 0x00   | float64 | 8 bytes  |
| action_aggression | 0x08   | float64 | 8 bytes  |
| action_size_scale | 0x10   | float64 | 8 bytes  |
| position_target   | 0x18   | float64 | 8 bytes  |
| confidence        | 0x20   | float64 | 8 bytes  |
| regime_code       | 0x28   | uint32  | 4 bytes  |
| expert_id         | 0x2C   | uint32  | 4 bytes  |
| reserved[...]     | 0x30   | -       | 224 bytes|
+--------------------------------------------------+
总大小: 256 bytes
```

### 7.2 动作空间定义

```python
action = [direction, aggression, size_scale]
# direction: -1.0 = 卖出, +1.0 = 买入
# aggression: 0.0 = 被动限价单, 1.0 = 激进市价单
# size_scale: 仓位缩放因子 [0, 1]
```

## 8. 执行优化器参数

### 8.1 SAC 执行智能体配置

```python
class SACConfig:
    state_dim: int = 10          # 状态维度
    action_dim: int = 3          # 动作维度
    hidden_dim: int = 256        # 隐藏层大小
    gamma: float = 0.99          # 折扣因子
    tau: float = 0.005           # 软更新系数
    alpha: float = 0.2           # 温度参数
    lr_actor: float = 3e-4       # Actor学习率
    lr_critic: float = 3e-4      # Critic学习率
    buffer_size: int = 1000000   # 经验回放缓冲区
    batch_size: int = 256        # 批次大小
```

### 8.2 队列优化参数

```python
class QueueOptimizerConfig:
    queue_target_ratio: float = 0.2    # 目标队列位置
    toxic_threshold: float = 0.35      # 毒流阈值
    min_spread_ticks: int = 3          # 最小价差 (tick)
    max_queue_depth: int = 100         # 最大队列深度
    hazard_alpha: float = 0.5          # 危险率衰减系数
```

## 9. 版本控制与兼容性

### 9.1 版本检查机制

```c
// 魔数验证
#define HFT_PROTOCOL_MAGIC  0x48465453  // "HFTS"

// 版本兼容性规则
// - 主版本号变化: 不兼容，必须同时升级
// - 次版本号变化: 向后兼容，新字段可忽略
// - 修订号变化: 完全兼容，仅 bug 修复
```

### 9.2 运行时版本检查

```go
// Go 端检查
func (h *SharedMemoryHeader) Verify() error {
    if h.Magic != HFTProtocolMagic {
        return fmt.Errorf("magic mismatch: expected 0x%08X, got 0x%08X",
            HFTProtocolMagic, h.Magic)
    }
    if h.Version != HFTProtocolVersion {
        return fmt.Errorf("version mismatch: expected %d, got %d",
            HFTProtocolVersion, h.Version)
    }
    return nil
}
```

```python
# Python 端检查
def verify_header(header: SharedMemoryHeader) -> bool:
    if header.magic != HFT_PROTOCOL_MAGIC:
        raise ProtocolError(f"Magic mismatch: {header.magic:08X}")
    if header.version != HFT_PROTOCOL_VERSION:
        raise ProtocolError(f"Version mismatch: {header.version}")
    return True
```

### 9.3 版本兼容性矩阵

| Go 版本 | Python 版本 | 兼容性 | 说明 |
|---------|-------------|--------|------|
| 1.0.x | 1.0.x | ✅ 完全兼容 | 基准版本 |
| 1.1.x | 1.0.x | ⚠️ 向后兼容 | Go新增字段，Python可忽略 |
| 1.0.x | 1.1.x | ❌ 不兼容 | Python使用新字段，Go不支持 |
| 2.0.x | 1.x.x | ❌ 不兼容 | 主版本变化，需同时升级 |

## 10. 错误处理与恢复

### 10.1 协议错误类型

```python
class ProtocolError(Exception):
    """协议基础错误"""
    pass

class MagicMismatchError(ProtocolError):
    """魔数不匹配"""
    pass

class VersionMismatchError(ProtocolError):
    """版本不匹配"""
    pass

class BufferOverflowError(ProtocolError):
    """缓冲区溢出"""
    pass

class ChecksumError(ProtocolError):
    """校验和错误"""
    pass
```

### 10.2 恢复策略

1. **魔数不匹配**: 立即断开连接，重新初始化共享内存
2. **版本不匹配**: 记录日志，尝试降级到兼容版本
3. **缓冲区溢出**: 丢弃旧消息，重置读写索引
4. **心跳超时**: 触发熔断，进入安全模式

## 11. 性能要求

### 11.1 延迟预算

| 操作 | 最大延迟 | 目标延迟 |
|------|----------|----------|
| 共享内存写入 | 2μs | 0.5μs |
| 共享内存读取 | 2μs | 0.5μs |
| 序列化/反序列化 | 5μs | 2μs |
| 端到端 (Go->Python) | 100μs | 50μs |

### 11.2 吞吐量要求

- 市场数据: 支持 10,000+ ticks/秒
- 订单命令: 支持 1,000+ 订单/秒
- 状态更新: 支持 5,000+ 更新/秒

## 12. 调试与监控

### 12.1 协议统计指标

```
hft_protocol_messages_sent_total{direction="go_to_python"}
hft_protocol_messages_sent_total{direction="python_to_go"}
hft_protocol_messages_lost_total
hft_protocol_buffer_utilization_percent
hft_protocol_latency_microseconds{quantile="0.99"}
hft_protocol_version_mismatch_total
```

### 12.2 调试接口

```go
// 导出协议状态
func (s *SharedMemory) DumpState() ProtocolState {
    return ProtocolState{
        Header: s.header,
        AIContext: s.ReadAIContext(),
        Stats: s.stats,
    }
}
```

## 10. Reversal Detection SHM Protocol

### 10.1 协议概述

Reversal Detection SHM 协议用于反转信号的高速传输，从 Python AI 模型传输到 Go 执行引擎。

### 10.2 内存布局

| 常量名 | 值 | 说明 |
|--------|-----|------|
| REVERSAL_FEATURES_OFFSET | 16384 (0x4000) | 反转特征偏移 |
| REVERSAL_FEATURES_SIZE | 640 bytes | 反转特征大小 |
| REVERSAL_SIGNAL_OFFSET | 17024 (0x4280) | 反转信号偏移 |
| REVERSAL_SIGNAL_SIZE | 256 bytes | 反转信号大小 |
| REVERSAL_SHM_MAGIC | 0x52455653 ("REVS") | 魔数 |
| REVERSAL_SHM_VERSION | 1 | 版本 |

### 10.3 ReversalFeaturesSHM (640 bytes)

```c
typedef struct {
    // Header (24 bytes)
    uint32_t magic;              // 0x52455653 "REVS"
    uint32_t version;            // 1
    uint64_t timestamp_ns;
    uint64_t sequence;

    // Price features (64 bytes)
    double price_momentum_1m;
    double price_momentum_5m;
    double price_momentum_15m;
    double price_zscore;
    double price_percentile;
    double price_velocity;
    double price_acceleration;
    double price_mean_reversion;

    // Volume features (32 bytes)
    double volume_surge;
    double volume_momentum;
    double volume_zscore;
    double relative_volume;

    // Volatility features (32 bytes)
    double volatility_current;
    double volatility_regime;
    double atr_ratio;
    double bollinger_position;

    // Order flow features (40 bytes)
    double ofi_signal;
    double trade_imbalance;
    double bid_ask_pressure;
    double order_book_slope;
    double micro_price_drift;

    // Microstructure (32 bytes)
    double spread_percentile;
    double tick_pressure;
    double queue_imbalance;
    double trade_intensity;

    // Time features (16 bytes)
    double time_of_day;
    uint32_t day_of_week;
    uint32_t is_market_open;
    uint32_t session_type;
    uint32_t _padding1;

    // Metadata (16 bytes)
    uint32_t symbol_id;
    uint32_t timeframe;
    uint32_t reserved;
    uint32_t _padding2;

    // Reason field (128 bytes)
    char reason[128];

    // Padding to 640 bytes
    uint8_t _padding3[248];
} ReversalFeaturesSHM;
```

### 10.4 ReversalSignalSHM (256 bytes)

```c
typedef struct {
    // Header (24 bytes)
    uint32_t magic;
    uint32_t version;
    uint64_t timestamp_ns;
    uint64_t sequence;

    // Signal data (40 bytes)
    double signal_strength;      // -1.0 to 1.0
    double confidence;           // 0.0 to 1.0
    double probability;          // 0.0 to 1.0
    double expected_return;
    uint32_t time_horizon_ms;
    uint32_t _padding1;

    // Model info (24 bytes)
    uint32_t model_version;      // 0=LightGBM, 1=NN, 2=Ensemble
    uint32_t model_type;
    uint32_t inference_latency_us;
    uint32_t _padding2;
    uint64_t feature_timestamp_ns;

    // Feature importance (64 bytes)
    double top_feature_1;
    double top_feature_2;
    double top_feature_3;
    double top_feature_4;
    double top_feature_5;
    double top_feature_6;
    double top_feature_7;
    double top_feature_8;

    // Risk metrics (32 bytes)
    double prediction_uncertainty;
    uint32_t market_regime;
    uint32_t _padding3;
    double risk_score;
    double max_adverse_excursion;

    // Execution advice (24 bytes)
    double suggested_urgency;
    uint32_t suggested_ttl_ms;
    uint32_t execution_priority;
    uint32_t reason_code;
    uint32_t _padding4;

    // Reason details (48 bytes)
    char reason_details[48];
} ReversalSignalSHM;
```

### 10.5 Reason Codes

| Code | Description |
|------|-------------|
| 1 | price_momentum |
| 2 | volume_surge |
| 3 | ofi_signal |
| 4 | volatility_spike |
| 5 | support_resistance |
| 6 | pattern_completion |
| 7 | composite |

## 11. Verification Metrics SHM Protocol

### 11.1 协议概述

Verification Metrics SHM 用于执行层真实性检验，记录延迟、滑点、一致性等指标。

### 11.2 内存布局

| 常量名 | 值 | 说明 |
|--------|-----|------|
| VERIFICATION_METRICS_OFFSET | 17252 (0x4364) | 偏移量 |
| VERIFICATION_METRICS_SIZE | 288 bytes | 结构体大小 |
| VERIFICATION_SHM_MAGIC | 0x54525554 ("TRUT") | 魔数 |
| VERIFICATION_SHM_VERSION | 1 | 版本 |

### 11.3 VerificationMetricsSHM (288 bytes)

```c
typedef struct {
    // Header (16 bytes)
    uint32_t magic;              // 0x54525554 "TRUT"
    uint32_t version;            // 1
    uint64_t timestamp_ns;

    // Latency measurements (32 bytes)
    uint32_t latency_total_us;
    uint32_t latency_feature_us;
    uint32_t latency_inference_us;
    uint32_t latency_decision_us;
    uint32_t latency_transmit_us;
    uint32_t latency_execute_us;
    uint32_t _padding[2];

    // Validation status (16 bytes)
    uint32_t validation_flags;
    uint32_t anomaly_count;
    float    slippage_bps;
    float    consistency_score;

    // Extended metrics (64 bytes)
    double execution_price;
    double predicted_price;
    double price_error;
    double price_error_std;
    double market_impact_bps;
    double timing_score;
    double queue_position_error;
    double fill_rate;

    // Quality metrics (32 bytes)
    float signal_to_noise;
    float prediction_accuracy;
    float model_drift_score;
    float data_freshness_ms;
    uint32_t consecutive_errors;
    uint32_t recovery_count;
    float _padding1;
    float _padding2;

    // Reserved (128 bytes)
    uint8_t reserved[128];
} VerificationMetricsSHM;
```

### 11.4 Validation Flags

| Flag | Value | Description |
|------|-------|-------------|
| VERIFICATION_FLAG_LATENCY_OK | 0x0001 | 延迟正常 |
| VERIFICATION_FLAG_SLIPPAGE_OK | 0x0002 | 滑点正常 |
| VERIFICATION_FLAG_CONSISTENCY_OK | 0x0004 | 一致性正常 |
| VERIFICATION_FLAG_ANOMALY_FREE | 0x0008 | 无异常 |
| VERIFICATION_FLAG_ALL_OK | 0x000F | 全部正常 |

## 12. 版本控制机制

### 12.1 版本号格式

版本号采用三段式: MAJOR.MINOR.PATCH

```c
#define PROTOCOL_VERSION_MAJOR 1
#define PROTOCOL_VERSION_MINOR 0
#define PROTOCOL_VERSION_PATCH 0
#define PROTOCOL_VERSION_FULL ((MAJOR << 16) | (MINOR << 8) | PATCH)
```

### 12.2 版本检查宏

```c
// 检查主版本号
#define CHECK_VERSION_MAJOR(v) (((v) >> 16) == PROTOCOL_VERSION_MAJOR)

// 检查兼容性 (主版本相同，次版本不高于当前)
#define CHECK_VERSION_COMPAT(v) \
    ((((v) >> 16) == PROTOCOL_VERSION_MAJOR) && \
     ((((v) >> 8) & 0xFF) <= PROTOCOL_VERSION_MINOR))
```

### 12.3 兼容性规则

| 变化类型 | 兼容性 | 说明 |
|----------|--------|------|
| MAJOR 变化 | ❌ 不兼容 | 协议重大变更 |
| MINOR 变化 | ⚠️ 向后兼容 | 新增字段，旧版本可忽略 |
| PATCH 变化 | ✅ 完全兼容 | Bug 修复 |

## 13. 附录

### 13.1 相关文件

| 文件 | 说明 |
|------|------|
| `shared/protocol.h` | C 头文件定义 |
| `shared/protocol.py` | Python 实现 |
| `core_go/protocol.go` | Go 实现 |
| `core_go/shm_reversal.go` | Go Reversal SHM 读取器 |
| `brain_py/reversal/shm_bridge.py` | Python Reversal SHM 桥接 |
| `docs/DEPENDENCY_GRAPH.md` | 模块依赖图 |
| `scripts/align_check.py` | 协议对齐验证脚本 |

### 13.2 变更历史

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| 1.0 | 2026-04-07 | 初始版本，定义基础协议 |
| 1.1 | 2026-04-07 | 添加 Reversal SHM 和 Verification Metrics SHM |

### 13.3 术语表

| 术语 | 说明 |
|------|------|
| SHM | Shared Memory，共享内存 |
| OFI | Order Flow Imbalance，订单流不平衡 |
| MoE | Mixture of Experts，混合专家系统 |
| SAC | Soft Actor-Critic，强化学习算法 |
| Hazard Rate | 危险率，成交概率模型参数 |
