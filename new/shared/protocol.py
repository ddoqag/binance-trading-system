"""
protocol.py
Python 端协议定义
对应 protocol.h 的数据结构
"""

from dataclasses import dataclass
import struct
from typing import List, Optional

# 协议常数
HFT_PROTOCOL_MAGIC = 0x48465453  # "HFTS"
HFT_PROTOCOL_VERSION = 1
HFT_MAX_ORDER_BOOK_DEPTH = 20
HFT_MAX_ORDERS = 64
HFT_SHM_SIZE_DEFAULT = 64 * 1024 * 1024  # 64MB

# 消息类型
class MessageType:
    HEARTBEAT = 0
    MARKET_SNAPSHOT = 1
    ORDER_COMMAND = 2
    ORDER_STATUS = 3
    TRADE_EXECUTION = 4
    SYNC_REQUEST = 5
    SYNC_RESPONSE = 6

# 订单方向
class OrderSide:
    BUY = 1
    SELL = 2

# 订单类型
class OrderType:
    LIMIT = 1
    MARKET = 2
    CANCEL = 3

# 订单状态
class OrderStatus:
    NEW = 0
    PENDING = 1
    PARTIAL = 2
    FILLED = 3
    CANCELED = 4
    REJECTED = 5
    EXPIRED = 6


@dataclass
class PriceLevel:
    """订单簿档位"""
    price: float
    quantity: float
    orders: int


# 预计算大小
PRICE_LEVEL_SIZE = struct.calcsize('<ddI')


@dataclass
class MarketSnapshot:
    """市场快照 (Go -> Python)"""
    timestamp_ns: int
    sequence: int
    best_bid: float
    best_ask: float
    last_price: float
    micro_price: float
    order_flow_imbalance: float
    trade_imbalance: float
    bid_queue_position: float
    ask_queue_position: float
    spread: float
    volatility_estimate: float
    trade_intensity: float
    adverse_score: float
    toxic_probability: float
    bids: List[PriceLevel]
    asks: List[PriceLevel]


# 市场快照固定大小
MARKET_SNAPSHOT_BASE = struct.calcsize('<QQddddddddddddd')
MARKET_SNAPSHOT_SIZE = (
    MARKET_SNAPSHOT_BASE +
    HFT_MAX_ORDER_BOOK_DEPTH * PRICE_LEVEL_SIZE +
    HFT_MAX_ORDER_BOOK_DEPTH * PRICE_LEVEL_SIZE
)


@dataclass
class OrderCommand:
    """订单命令 (Python -> Go)"""
    command_id: int
    timestamp_ns: int
    order_type: int
    side: int
    price: float
    quantity: float
    max_slippage_bps: float
    expires_after_ms: int
    dry_run: bool


# 订单命令大小
ORDER_COMMAND_SIZE = struct.calcsize('<QQIIdddB')


@dataclass
class OrderStatusUpdate:
    """订单状态更新 (Go -> Python)"""
    order_id: int
    command_id: int
    timestamp_ns: int
    side: int
    type: int
    status: int
    price: float
    original_quantity: float
    filled_quantity: float
    remaining_quantity: float
    average_fill_price: float
    latency_us: float
    is_maker: bool


ORDER_STATUS_SIZE = struct.calcsize('<QQIIIdddddddB')


@dataclass
class TradeExecution:
    """成交执行 (Go -> Python)"""
    trade_id: int
    order_id: int
    timestamp_ns: int
    side: int
    price: float
    quantity: float
    commission: float
    realized_pnl: float
    adverse_selection: float
    is_maker: bool


TRADE_EXECUTION_SIZE = struct.calcsize('<QQIdddddddB')


@dataclass
class Heartbeat:
    """心跳"""
    magic: int
    version: int
    timestamp_ns: int
    sequence: int
    go_running: bool
    ai_running: bool


HEARTBEAT_SIZE = struct.calcsize('<IIIBB')


@dataclass
class AccountInfo:
    """账户信息"""
    total_balance: float
    available_balance: float
    position_size: float
    entry_price: float
    unrealized_pnl: float
    realized_pnl_today: float
    trades_today: int


ACCOUNT_INFO_SIZE = struct.calcsize('<ddddddI')


@dataclass
class AIContext:
    """AI 决策上下文 (Python -> Go)"""
    ai_position: float
    ai_confidence: float
    moe_weight_0: float
    moe_weight_1: float
    moe_weight_2: float
    moe_weight_3: float
    regime_code: int
    num_active_experts: int


AI_CONTEXT_SIZE = struct.calcsize('<ddddddIIII')
AI_CONTEXT_OFFSET = 4096


@dataclass
class SharedMemoryHeader:
    """共享内存头部"""
    magic: int
    version: int
    size_bytes: int
    go_write_index: int
    go_read_index: int
    ai_write_index: int
    ai_read_index: int
    messages_sent_go: int
    messages_sent_ai: int
    messages_lost: int
    last_heartbeat_go_ns: int
    last_heartbeat_ai_ns: int
    last_heartbeat: Heartbeat
    account_info: AccountInfo
    last_market_snapshot: MarketSnapshot
    ai_context: AIContext = None


# 计算总头部大小
HEADER_BASE_SIZE = struct.calcsize('<IIQQQQQQQQQQ')
HEADER_SIZE = (
    HEADER_BASE_SIZE +
    HEARTBEAT_SIZE +
    ACCOUNT_INFO_SIZE +
    MARKET_SNAPSHOT_SIZE
)


def pack_price_level(pl: PriceLevel) -> bytes:
    """打包价格档位"""
    return struct.pack('<ddI', pl.price, pl.quantity, pl.orders)


def unpack_price_level(data: bytes) -> PriceLevel:
    """解包价格档位"""
    price, quantity, orders = struct.unpack('<ddI', data)
    return PriceLevel(price=price, quantity=quantity, orders=orders)


def pack_market_snapshot(snap: MarketSnapshot) -> bytes:
    """打包市场快照"""
    # 填充 bids 和 asks 到固定大小
    padded_bids = snap.bids.copy()
    while len(padded_bids) < HFT_MAX_ORDER_BOOK_DEPTH:
        padded_bids.append(PriceLevel(0, 0, 0))

    padded_asks = snap.asks.copy()
    while len(padded_asks) < HFT_MAX_ORDER_BOOK_DEPTH:
        padded_asks.append(PriceLevel(0, 0, 0))

    # 打包基础字段
    base = struct.pack(
        '<QQddddddddddddd',
        snap.timestamp_ns,
        snap.sequence,
        snap.best_bid,
        snap.best_ask,
        snap.last_price,
        snap.micro_price,
        snap.order_flow_imbalance,
        snap.trade_imbalance,
        snap.bid_queue_position,
        snap.ask_queue_position,
        snap.spread,
        snap.volatility_estimate,
        snap.trade_intensity,
        snap.adverse_score,
        snap.toxic_probability
    )

    # 打包价格档位
    for pl in padded_bids:
        base += pack_price_level(pl)
    for pl in padded_asks:
        base += pack_price_level(pl)

    return base


def unpack_market_snapshot(data: bytes) -> MarketSnapshot:
    """解包市场快照"""
    # 解包基础字段
    offset = 0
    base_size = struct.calcsize('<QQddddddddddddd')
    unpacked = struct.unpack_from('<QQddddddddddddd', data, offset)
    offset += base_size

    bids: List[PriceLevel] = []
    for _ in range(HFT_MAX_ORDER_BOOK_DEPTH):
        pl = unpack_price_level(data[offset:offset + PRICE_LEVEL_SIZE])
        offset += PRICE_LEVEL_SIZE
        if pl.price > 0:
            bids.append(pl)

    asks: List[PriceLevel] = []
    for _ in range(HFT_MAX_ORDER_BOOK_DEPTH):
        pl = unpack_price_level(data[offset:offset + PRICE_LEVEL_SIZE])
        offset += PRICE_LEVEL_SIZE
        if pl.price > 0:
            asks.append(pl)

    return MarketSnapshot(
        timestamp_ns=unpacked[0],
        sequence=unpacked[1],
        best_bid=unpacked[2],
        best_ask=unpacked[3],
        last_price=unpacked[4],
        micro_price=unpacked[5],
        order_flow_imbalance=unpacked[6],
        trade_imbalance=unpacked[7],
        bid_queue_position=unpacked[8],
        ask_queue_position=unpacked[9],
        spread=unpacked[10],
        volatility_estimate=unpacked[11],
        trade_intensity=unpacked[12],
        adverse_score=unpacked[13],
        toxic_probability=unpacked[14],
        bids=bids,
        asks=asks
    )


def pack_order_command(cmd: OrderCommand) -> bytes:
    """打包订单命令"""
    return struct.pack(
        '<QQIIdddB',
        cmd.command_id,
        cmd.timestamp_ns,
        cmd.order_type,
        cmd.side,
        cmd.price,
        cmd.quantity,
        cmd.max_slippage_bps,
        cmd.expires_after_ms,
        1 if cmd.dry_run else 0
    )


def unpack_order_command(data: bytes) -> OrderCommand:
    """解包订单命令"""
    unpacked = struct.unpack('<QQIIdddB', data[:ORDER_COMMAND_SIZE])
    return OrderCommand(
        command_id=unpacked[0],
        timestamp_ns=unpacked[1],
        order_type=unpacked[2],
        side=unpacked[3],
        price=unpacked[4],
        quantity=unpacked[5],
        max_slippage_bps=unpacked[6],
        expires_after_ms=unpacked[7],
        dry_run=bool(unpacked[8])
    )


def pack_order_status(status: OrderStatusUpdate) -> bytes:
    """打包订单状态更新"""
    return struct.pack(
        '<QQIIIdddddddB',
        status.order_id,
        status.command_id,
        status.timestamp_ns,
        status.side,
        status.type,
        status.status,
        status.price,
        status.original_quantity,
        status.filled_quantity,
        status.remaining_quantity,
        status.average_fill_price,
        status.latency_us,
        1 if status.is_maker else 0
    )


def unpack_order_status(data: bytes) -> OrderStatusUpdate:
    """解包订单状态更新"""
    unpacked = struct.unpack('<QQIIIdddddddB', data[:ORDER_STATUS_SIZE])
    return OrderStatusUpdate(
        order_id=unpacked[0],
        command_id=unpacked[1],
        timestamp_ns=unpacked[2],
        side=unpacked[3],
        type=unpacked[4],
        status=unpacked[5],
        price=unpacked[6],
        original_quantity=unpacked[7],
        filled_quantity=unpacked[8],
        remaining_quantity=unpacked[9],
        average_fill_price=unpacked[10],
        latency_us=unpacked[11],
        is_maker=bool(unpacked[12])
    )


def pack_trade_execution(trade: TradeExecution) -> bytes:
    """打包成交执行"""
    return struct.pack(
        '<QQIdddddddB',
        trade.trade_id,
        trade.order_id,
        trade.side,
        trade.price,
        trade.quantity,
        trade.commission,
        trade.realized_pnl,
        trade.adverse_selection,
        1 if trade.is_maker else 0
    )


def unpack_trade_execution(data: bytes) -> TradeExecution:
    """解包成交执行"""
    unpacked = struct.unpack('<QQIdddddddB', data[:TRADE_EXECUTION_SIZE])
    return TradeExecution(
        trade_id=unpacked[0],
        order_id=unpacked[1],
        timestamp_ns=unpacked[2],
        side=unpacked[3],
        price=unpacked[4],
        quantity=unpacked[5],
        commission=unpacked[6],
        realized_pnl=unpacked[7],
        adverse_selection=unpacked[8],
        is_maker=bool(unpacked[9])
    )


def pack_heartbeat(hb: Heartbeat) -> bytes:
    """打包心跳"""
    return struct.pack(
        '<IIIBB',
        hb.magic,
        hb.version,
        hb.timestamp_ns,
        hb.sequence,
        1 if hb.go_running else 0,
        1 if hb.ai_running else 0
    )


def unpack_heartbeat(data: bytes) -> Heartbeat:
    """解包心跳"""
    unpacked = struct.unpack('<IIIBB', data[:HEARTBEAT_SIZE])
    return Heartbeat(
        magic=unpacked[0],
        version=unpacked[1],
        timestamp_ns=unpacked[2],
        sequence=unpacked[3],
        go_running=bool(unpacked[4]),
        ai_running=bool(unpacked[5])
    )


def pack_account_info(acc: AccountInfo) -> bytes:
    """打包账户信息"""
    return struct.pack(
        '<ddddddI',
        acc.total_balance,
        acc.available_balance,
        acc.position_size,
        acc.entry_price,
        acc.unrealized_pnl,
        acc.realized_pnl_today,
        acc.trades_today
    )


def unpack_account_info(data: bytes) -> AccountInfo:
    """解包账户信息"""
    unpacked = struct.unpack('<ddddddI', data[:ACCOUNT_INFO_SIZE])
    return AccountInfo(
        total_balance=unpacked[0],
        available_balance=unpacked[1],
        position_size=unpacked[2],
        entry_price=unpacked[3],
        unrealized_pnl=unpacked[4],
        realized_pnl_today=unpacked[5],
        trades_today=unpacked[6]
    )


def pack_ai_context(ctx: AIContext) -> bytes:
    """打包 AI 决策上下文"""
    return struct.pack(
        '<ddddddIIII',
        ctx.ai_position,
        ctx.ai_confidence,
        ctx.moe_weight_0,
        ctx.moe_weight_1,
        ctx.moe_weight_2,
        ctx.moe_weight_3,
        ctx.regime_code,
        ctx.num_active_experts,
        0,
        0
    )


def unpack_ai_context(data: bytes) -> AIContext:
    """解包 AI 决策上下文"""
    unpacked = struct.unpack('<ddddddIIII', data[:AI_CONTEXT_SIZE])
    return AIContext(
        ai_position=unpacked[0],
        ai_confidence=unpacked[1],
        moe_weight_0=unpacked[2],
        moe_weight_1=unpacked[3],
        moe_weight_2=unpacked[4],
        moe_weight_3=unpacked[5],
        regime_code=unpacked[6],
        num_active_experts=unpacked[7]
    )
