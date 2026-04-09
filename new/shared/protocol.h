/*
 * protocol.h
 *
 * HFT System Shared Memory Protocol
 * Go Engine <-> Python AI Engine IPC
 *
 * 共享内存协议定义
 * 结构必须严格对齐，大小固定，便于 Go 和 Python 解析
 */

#ifndef HFT_PROTOCOL_H
#define HFT_PROTOCOL_H

#include <stdint.h>

#pragma pack(push, 1)

// ============================================================================
// 协议版本和魔数
// ============================================================================

#define HFT_PROTOCOL_MAGIC       0x48465453  // "HFTS" - HFT System
#define HFT_PROTOCOL_VERSION     1
#define HFT_MAX_ORDER_BOOK_DEPTH 20
#define HFT_MAX_ORDERS          64

// 共享内存布局偏移量
#define HFT_HEADER_OFFSET        0
#define HFT_AI_CONTEXT_OFFSET    4096        // AIContext 固定偏移
#define HFT_FEATURES_OFFSET      16384       // 特征工程输出偏移
#define HFT_SIGNAL_OFFSET        17024       // 模型信号输入偏移 (16384 + 640)
#define HFT_SHM_SIZE_DEFAULT     (64 * 1024 * 1024)  // 64MB

// ============================================================================
// 消息类型
// ============================================================================

typedef enum {
    MSG_TYPE_HEARTBEAT       = 0,
    MSG_TYPE_MARKET_SNAPSHOT = 1,
    MSG_TYPE_ORDER_COMMAND   = 2,
    MSG_TYPE_ORDER_STATUS    = 3,
    MSG_TYPE_TRADE_EXECUTION = 4,
    MSG_TYPE_SYNC_REQUEST    = 5,
    MSG_TYPE_SYNC_RESPONSE   = 6,
} MessageType;

// ============================================================================
// 订单方向
// ============================================================================

typedef enum {
    SIDE_BUY  = 1,
    SIDE_SELL = 2,
} OrderSide;

// ============================================================================
// 订单类型
// ============================================================================

typedef enum {
    ORDER_TYPE_LIMIT   = 1,
    ORDER_TYPE_MARKET  = 2,
    ORDER_TYPE_CANCEL  = 3,
} OrderType;

// ============================================================================
// 订单状态
// ============================================================================

typedef enum {
    STATUS_NEW          = 0,
    STATUS_PENDING      = 1,
    STATUS_PARTIAL     = 2,
    STATUS_FILLED      = 3,
    STATUS_CANCELED    = 4,
    STATUS_REJECTED    = 5,
    STATUS_EXPIRED     = 6,
} OrderStatus;

// ============================================================================
// 订单簿档位
// ============================================================================

typedef struct {
    double price;
    double quantity;
    uint32_t orders;      // 该价位订单数
} PriceLevel;

// ============================================================================
// 市场快照 (Go -> Python)
// 包含当前订单簿、最新成交、微观结构特征
// ============================================================================

typedef struct {
    uint64_t timestamp_ns;         // 时间戳 (纳秒)
    uint64_t sequence;             // 序列号

    // 订单簿
    uint32_t num_bids;            // 买盘档位
    uint32_t num_asks;            // 卖盘档位
    PriceLevel bids[HFT_MAX_ORDER_BOOK_DEPTH];
    PriceLevel asks[HFT_MAX_ORDER_BOOK_DEPTH];

    // 最新价格
    double best_bid;
    double best_ask;
    double last_price;
    double micro_price;           // 微观价格

    // 订单流不平衡 (OFI)
    double order_flow_imbalance;
    double trade_imbalance;       // 成交不平衡

    // 队列位置信息
    double bid_queue_position;    // 当前买单队列位置比率 [0, 1]
    double ask_queue_position;    // 当前卖单队列位置比率 [0, 1]

    // 市场微观结构特征
    double spread;                // 买卖价差
    double volatility_estimate;   // 波动率估计
    double trade_intensity;       // 交易强度

    // 毒流检测
    double adverse_score;         // 逆向选择分数
    double toxic_probability;     // 毒流概率

} MarketSnapshot;

// ============================================================================
// 订单命令 (Python -> Go)
// AI 引擎发出的下单/撤单命令
// ============================================================================

typedef struct {
    uint64_t command_id;          // 命令ID
    uint64_t timestamp_ns;
    OrderType order_type;
    OrderSide side;
    double price;
    double quantity;
    double max_slippage;          // 最大滑点 (bps)
    uint32_t expires_after_ms;    // 过期时间
    uint8_t dry_run;              // 1=模拟执行, 0=真实执行
} OrderCommand;

// ============================================================================
// 订单状态更新 (Go -> Python)
// ============================================================================

typedef struct {
    uint64_t order_id;            // 订单ID
    uint64_t command_id;          // 对应命令ID
    uint64_t timestamp_ns;
    OrderSide side;
    OrderType type;
    OrderStatus status;
    double price;
    double original_quantity;
    double filled_quantity;
    double remaining_quantity;
    double average_fill_price;
    double latency_us;            // 延迟 (微秒)
    uint8_t is_maker;             // 是否是maker
} OrderStatusUpdate;

// ============================================================================
// 成交执行 (Go -> Python)
// 完整成交信息，用于训练和奖励计算
// ============================================================================

typedef struct {
    uint64_t trade_id;
    uint64_t order_id;
    uint64_t timestamp_ns;
    OrderSide side;
    double price;
    double quantity;
    double commission;
    double realized_pnl;          // 已实现盈亏（如果平仓）
    double adverse_selection;     // 逆向选择成本
    uint8_t is_maker;
} TradeExecution;

// ============================================================================
// 心跳和状态同步
// ============================================================================

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint64_t timestamp_ns;
    uint32_t sequence;
    uint8_t go_running;           // Go引擎是否运行
    uint8_t ai_running;           // AI引擎是否运行
} Heartbeat;

// ============================================================================
// 账户和仓位信息
// ============================================================================

typedef struct {
    double total_balance;         // 总余额
    double available_balance;     // 可用余额
    double position_size;         // 当前仓位 (正=多，负=空)
    double entry_price;           // 平均入场价格
    double unrealized_pnl;        // 未实现盈亏
    double realized_pnl_today;    // 今日已实现盈亏
    uint32_t trades_today;        // 今日成交次数
} AccountInfo;

// ============================================================================
// 共享内存头部
// 位于共享内存起始位置，描述整个布局
// ============================================================================

typedef struct {
    uint32_t magic;               // 魔数，验证有效性
    uint32_t version;             // 协议版本
    uint64_t size_bytes;         // 总大小

    // 读写索引，用于环形缓冲区
    volatile uint64_t go_write_index;
    volatile uint64_t go_read_index;
    volatile uint64_t ai_write_index;
    volatile uint64_t ai_read_index;

    // 统计信息
    uint64_t messages_sent_go;
    uint64_t messages_sent_ai;
    uint64_t messages_lost;

    // 时间同步
    uint64_t last_heartbeat_go_ns;
    uint64_t last_heartbeat_ai_ns;

    // 当前状态
    Heartbeat last_heartbeat;
    AccountInfo account_info;
    MarketSnapshot last_market_snapshot;

} SharedMemoryHeader;

// ============================================================================
// 消息缓冲区结构
// 每个方向一个环形缓冲区
// ============================================================================

typedef struct {
    MessageType type;
    uint32_t size;
    uint8_t  data[];  // 柔性数组
} MessageBuffer;

// ============================================================================
// AI 决策上下文 (Python -> Go)
// 用于让 Go 引擎感知当前 AI 的决策依据
// ============================================================================

typedef struct {
    double ai_position;        // AI 推荐仓位 [-1, +1]
    double ai_confidence;      // AI 置信度 [0, 1]
    double moe_weight_0;       // 专家0权重
    double moe_weight_1;       // 专家1权重
    double moe_weight_2;       // 专家2权重
    double moe_weight_3;       // 专家3权重
    uint32_t regime_code;      // 市场状态编码
    uint32_t num_active_experts; // 实际激活的专家数量
    uint32_t reserved[2];      // 保留对齐到64字节
} AIContext;

// 结构体大小常量 (用于跨语言对齐验证)
#define HFT_PRICE_LEVEL_SIZE    20
#define HFT_HEARTBEAT_SIZE      24
#define HFT_ACCOUNT_INFO_SIZE   56
#define HFT_AI_CONTEXT_SIZE     64
#define HFT_HEADER_SIZE         1024  // 预留1KB给头部

// 版本兼容性检查
#define HFT_MIN_COMPATIBLE_VERSION  1
#define HFT_MAX_COMPATIBLE_VERSION  1

// 特征工程输出格式 (偏移 HFT_FEATURES_OFFSET)
typedef struct {
    double ofi;                   // 订单流不平衡 [-1, +1]
    double queue_ratio;           // 队列位置 [0, 1]
    double hazard_rate;           // 危险率 [0, inf)
    double adverse_score;         // 逆向选择分数 [-1, +1]
    double toxic_prob;            // 毒流概率 [0, 1]
    double spread;                // 价差
    double micro_momentum;        // 微观动量 [-1, +1]
    double volatility;            // 波动率
    double trade_flow;            // 交易流 [-1, +1]
    double inventory;             // 持仓压力 [-1, +1]
    double reserved[70];          // 填充到640 bytes
} FeatureVector;                 // 总计: 640 bytes

// 模型预测信号格式 (偏移 HFT_SIGNAL_OFFSET)
typedef struct {
    double action_direction;      // 动作方向 [-1, +1]
    double action_aggression;     // 激进度 [0, 1]
    double action_size_scale;     // 大小缩放 [0, 1]
    double position_target;       // 目标仓位 [-1, +1]
    double confidence;            // 置信度 [0, 1]
    uint32_t regime_code;         // 市场状态编码
    uint32_t expert_id;           // 专家ID
    double reserved[26];          // 填充到256 bytes
} SignalVector;                  // 总计: 256 bytes

// ============================================================================
// Reversal Detection SHM Protocol (扩展协议)
// ============================================================================

// Reversal SHM 魔数和版本
#define REVERSAL_SHM_MAGIC       0x52455653  // "REVS"
#define REVERSAL_SHM_VERSION     1

// Reversal SHM 布局 (从偏移 16384 开始)
#define REVERSAL_FEATURES_OFFSET 16384
#define REVERSAL_FEATURES_SIZE   640   // 512 + 128 reason
#define REVERSAL_SIGNAL_OFFSET   17024 // 16384 + 640
#define REVERSAL_SIGNAL_SIZE     256

// Reversal 特征结构 (640 bytes)
typedef struct {
    // Header (24 bytes)
    uint32_t magic;
    uint32_t version;
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
    uint8_t _padding3[120];
} ReversalFeaturesSHM;

// Reversal 信号结构 (256 bytes)
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
    uint32_t market_regime;      // 0=unknown, 1=trend_up, 2=trend_down, 3=range, 4=high_vol
    uint32_t _padding3;
    double risk_score;
    double max_adverse_excursion;

    // Execution advice (24 bytes)
    double suggested_urgency;
    uint32_t suggested_ttl_ms;
    uint32_t execution_priority; // 0=normal, 1=high, 2=critical
    uint32_t reason_code;
    uint32_t _padding4;

    // Reason details (48 bytes)
    char reason_details[48];
} ReversalSignalSHM;

// ============================================================================
// Verification Metrics SHM (真实性检验)
// Offset 17252 (17024 + 256)
// ============================================================================

#define VERIFICATION_SHM_MAGIC    0x54525554  // "TRUT"
#define VERIFICATION_SHM_VERSION  1
#define VERIFICATION_METRICS_OFFSET 17252     // REVERSAL_SIGNAL_OFFSET + REVERSAL_SIGNAL_SIZE
#define VERIFICATION_METRICS_SIZE   288

// 版本控制 (主版本.次版本.修订号)
#define PROTOCOL_VERSION_MAJOR    1
#define PROTOCOL_VERSION_MINOR    0
#define PROTOCOL_VERSION_PATCH    0
#define PROTOCOL_VERSION_FULL     ((PROTOCOL_VERSION_MAJOR << 16) | (PROTOCOL_VERSION_MINOR << 8) | PROTOCOL_VERSION_PATCH)

// 版本检查宏
#define CHECK_VERSION_MAJOR(v)    (((v) >> 16) == PROTOCOL_VERSION_MAJOR)
#define CHECK_VERSION_COMPAT(v)   (((v) >> 16) == PROTOCOL_VERSION_MAJOR && (((v) >> 8) & 0xFF) <= PROTOCOL_VERSION_MINOR)

// 验证标志位定义
#define VERIFICATION_FLAG_LATENCY_OK      0x0001
#define VERIFICATION_FLAG_SLIPPAGE_OK     0x0002
#define VERIFICATION_FLAG_CONSISTENCY_OK  0x0004
#define VERIFICATION_FLAG_ANOMALY_FREE    0x0008
#define VERIFICATION_FLAG_ALL_OK          0x000F

// Verification Metrics 结构 (288 bytes)
typedef struct {
    // Header (16 bytes)
    uint32_t magic;              // 0x54525554 "TRUT"
    uint32_t version;            // 1
    uint64_t timestamp_ns;       // 时间戳

    // Latency measurements (32 bytes)
    uint32_t latency_total_us;
    uint32_t latency_feature_us;
    uint32_t latency_inference_us;
    uint32_t latency_decision_us;
    uint32_t latency_transmit_us;
    uint32_t latency_execute_us;
    uint32_t latency_padding[2];

    // Validation status (16 bytes)
    uint32_t validation_flags;   // 位掩码
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
    uint8_t  reserved[128];
} VerificationMetricsSHM;

// ============================================================================
// 版本兼容性检查函数声明
// ============================================================================

#ifdef __cplusplus
extern "C" {
#endif

static inline int hft_check_version(uint32_t version) {
    return (version >= HFT_MIN_COMPATIBLE_VERSION &&
            version <= HFT_MAX_COMPATIBLE_VERSION);
}

static inline int hft_check_magic(uint32_t magic) {
    return magic == HFT_PROTOCOL_MAGIC;
}

static inline uint32_t hft_negotiate_version(uint32_t go_version, uint32_t py_version) {
    return (go_version < py_version) ? go_version : py_version;
}

// Reversal SHM 检查函数
static inline int reversal_check_magic(uint32_t magic) {
    return magic == REVERSAL_SHM_MAGIC;
}

static inline int reversal_check_version(uint32_t version) {
    return version == REVERSAL_SHM_VERSION;
}

// Verification SHM 检查函数
static inline int verification_check_magic(uint32_t magic) {
    return magic == VERIFICATION_SHM_MAGIC;
}

static inline int verification_check_version(uint32_t version) {
    return version == VERIFICATION_SHM_VERSION;
}

static inline int verification_check_latency_ok(uint32_t flags) {
    return (flags & VERIFICATION_FLAG_LATENCY_OK) != 0;
}

static inline int verification_check_slippage_ok(uint32_t flags) {
    return (flags & VERIFICATION_FLAG_SLIPPAGE_OK) != 0;
}

static inline int verification_check_consistency_ok(uint32_t flags) {
    return (flags & VERIFICATION_FLAG_CONSISTENCY_OK) != 0;
}

static inline int verification_check_all_ok(uint32_t flags) {
    return (flags & VERIFICATION_FLAG_ALL_OK) == VERIFICATION_FLAG_ALL_OK;
}

#ifdef __cplusplus
}
#endif

#pragma pack(pop)

#endif // HFT_PROTOCOL_H
