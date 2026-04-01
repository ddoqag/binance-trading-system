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

#pragma pack(pop)

// ============================================================================
// 计算偏移量，方便Go和Python访问
// ============================================================================

#define HFT_HEADER_OFFSET     0
#define HFT_HEADER_SIZE       sizeof(SharedMemoryHeader)
#define HFT_BUFFER_START      HFT_HEADER_SIZE

// 总共享内存大小建议: 64MB
#define HFT_SHM_SIZE_DEFAULT  (64 * 1024 * 1024)

#endif // HFT_PROTOCOL_H
