/*
 * protocol.h - High-Frequency Trading Shared Memory Protocol
 *
 * This file defines the cross-language memory layout for communication
 * between Go (execution engine) and Python (AI brain).
 *
 * ALIGNMENT NOTE: Go aligns struct fields to their natural boundaries.
 * The actual layout has 4 bytes padding between cache lines, resulting
 * in 144 bytes total (not 128). This is due to decision_seq requiring
 * 8-byte alignment which forces padding after ask_queue_pos.
 */

#ifndef PROTOCOL_H
#define PROTOCOL_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Trading Action Types
 * Action output by AI brain, consumed by Go execution engine
 */
typedef enum {
    ACTION_WAIT = 0,           // Hold position, do nothing
    ACTION_JOIN_BID = 1,       // Place limit buy order at bid
    ACTION_JOIN_ASK = 2,       // Place limit sell order at ask
    ACTION_CROSS_BUY = 3,      // Market buy (cross spread)
    ACTION_CROSS_SELL = 4,     // Market sell (cross spread)
    ACTION_CANCEL = 5,         // Cancel existing orders
    ACTION_PARTIAL_EXIT = 6,   // Take partial profits
} TradingAction;

/*
 * Market Regime Types
 * Used by AI to communicate market state
 */
typedef enum {
    REGIME_UNKNOWN = 0,
    REGIME_TREND_UP = 1,
    REGIME_TREND_DOWN = 2,
    REGIME_RANGE = 3,
    REGIME_HIGH_VOL = 4,
    REGIME_LOW_VOL = 5,
} MarketRegime;

/*
 * Shared Memory State Structure
 * Total size: 144 bytes (Go alignment requires extra padding)
 *
 * Layout:
 * - Line 0 (0-71):   Version control + market data from Go (includes 4B padding)
 * - Line 1 (72-143): AI decision + metadata from Python (includes 8B padding)
 */
typedef struct {
    /* === Cache Line 0: Market Data (Written by Go) - 72 bytes === */
    volatile uint64_t seq;           // 8B: Sequence number for lock-free sync (offset 0)
    volatile uint64_t seq_end;       // 8B: End sequence (must match seq) (offset 8)

    int64_t  timestamp;              // 8B: Unix timestamp (nanoseconds) (offset 16)
    double   best_bid;               // 8B: Best bid price (offset 24)
    double   best_ask;               // 8B: Best ask price (offset 32)
    double   micro_price;            // 8B: Micro-price (weighted mid) (offset 40)
    double   ofi_signal;             // 8B: Order Flow Imbalance signal (offset 48)
    float    trade_imbalance;        // 4B: Recent trade flow imbalance (offset 56)
    float    bid_queue_pos;          // 4B: Position in bid queue (0-1) (offset 60)
    float    ask_queue_pos;          // 4B: Position in ask queue (0-1) (offset 64)
    char     _padding0[4];           // 4B: Padding to align decision_seq to 8B (offset 68-71)

    /* === Cache Line 1: AI Decision (Written by Python) - 72 bytes === */
    volatile uint64_t decision_seq;  // 8B: Decision sequence number (offset 72)
    volatile uint64_t decision_ack;  // 8B: Acknowledgment from Go (offset 80)

    int64_t  decision_timestamp;     // 8B: When decision was made (offset 88)
    double   target_position;        // 8B: Target position size (offset 96)
    double   target_size;            // 8B: Order quantity (offset 104)
    double   limit_price;            // 8B: Limit price (0 for market) (offset 112)
    float    confidence;             // 4B: AI confidence (0-1) (offset 120)
    float    volatility_forecast;    // 4B: Predicted volatility (offset 124)
    int32_t  action;                 // 4B: TradingAction enum (offset 128)
    int32_t  regime;                 // 4B: MarketRegime enum (offset 132)
    char     _padding1[8];           // 8B: Padding to reach 144 bytes (offset 136-143)

} TradingSharedState;

/* Ensure 144-byte alignment (matches Go struct size) */
_Static_assert(sizeof(TradingSharedState) == 144,
               "TradingSharedState must be exactly 144 bytes to match Go layout");

/*
 * Constants
 */
#define SHM_PATH_DEFAULT "/tmp/hft_trading_shm"
#define SHM_SIZE 144

/*
 * Offset constants for language bindings
 */
#define OFFSET_SEQ              0
#define OFFSET_SEQ_END          8
#define OFFSET_TIMESTAMP        16
#define OFFSET_BEST_BID         24
#define OFFSET_BEST_ASK         32
#define OFFSET_MICRO_PRICE      40
#define OFFSET_OFI              48
#define OFFSET_TRADE_IMBALANCE  56
#define OFFSET_BID_QUEUE_POS    60
#define OFFSET_ASK_QUEUE_POS    64
#define OFFSET_DECISION_SEQ     72
#define OFFSET_DECISION_ACK     80
#define OFFSET_DECISION_TS      88
#define OFFSET_TARGET_POS       96
#define OFFSET_TARGET_SIZE      104
#define OFFSET_LIMIT_PRICE      112
#define OFFSET_CONFIDENCE       120
#define OFFSET_VOL_FORECAST     124
#define OFFSET_ACTION           128
#define OFFSET_REGIME           132

/*
 * Helper macros for sequence lock
 */
#define SEQ_START(s) ((s)->seq)
#define SEQ_END(s) ((s)->seq_end)
#define SEQ_IS_VALID(s) (SEQ_START(s) == SEQ_END(s))
#define SEQ_INCREMENT(s) ((s)->seq++)
#define SEQ_COMMIT(s) ((s)->seq_end = (s)->seq)

#ifdef __cplusplus
}
#endif

#endif /* PROTOCOL_H */
