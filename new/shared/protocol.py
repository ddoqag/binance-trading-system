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
HFT_MIN_COMPATIBLE_VERSION = 1
HFT_MAX_COMPATIBLE_VERSION = 1
HFT_MAX_ORDER_BOOK_DEPTH = 20
HFT_MAX_ORDERS = 64
HFT_SHM_SIZE_DEFAULT = 64 * 1024 * 1024  # 64MB

# 共享内存布局偏移量
HFT_HEADER_OFFSET = 0
HFT_AI_CONTEXT_OFFSET = 4096
HFT_FEATURES_OFFSET = 16384
HFT_SIGNAL_OFFSET = 17024  # 16384 + 640 = 17024, 避免与 Features 重叠

# 结构体大小常量
HFT_PRICE_LEVEL_SIZE = 20
HFT_HEARTBEAT_SIZE = 24
HFT_ACCOUNT_INFO_SIZE = 56
HFT_AI_CONTEXT_SIZE = 64
HFT_HEADER_SIZE = 1024

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


# ============================================================================
# 特征向量定义 (对应 C FeatureVector)
# ============================================================================

@dataclass
class FeatureVector:
    """特征工程输出向量 (位于 HFT_FEATURES_OFFSET)"""
    ofi: float = 0.0                   # 订单流不平衡 [-1, +1]
    queue_ratio: float = 0.0           # 队列位置 [0, 1]
    hazard_rate: float = 0.0           # 危险率
    adverse_score: float = 0.0         # 逆向选择分数 [-1, +1]
    toxic_prob: float = 0.0            # 毒流概率 [0, 1]
    spread: float = 0.0                # 价差
    micro_momentum: float = 0.0        # 微观动量 [-1, +1]
    volatility: float = 0.0            # 波动率
    trade_flow: float = 0.0            # 交易流 [-1, +1]
    inventory: float = 0.0             # 持仓压力 [-1, +1]


FEATURE_VECTOR_SIZE = struct.calcsize('<' + 'd' * 80)  # 10 + 70 reserved = 80 doubles = 640 bytes


def pack_feature_vector(fv: FeatureVector) -> bytes:
    """打包特征向量"""
    base = struct.pack('<dddddddddd',
        fv.ofi, fv.queue_ratio, fv.hazard_rate, fv.adverse_score,
        fv.toxic_prob, fv.spread, fv.micro_momentum, fv.volatility,
        fv.trade_flow, fv.inventory
    )
    # 填充到640 bytes
    padding = b'\x00' * (640 - len(base))
    return base + padding


def unpack_feature_vector(data: bytes) -> FeatureVector:
    """解包特征向量"""
    unpacked = struct.unpack('<dddddddddd', data[:80])
    return FeatureVector(
        ofi=unpacked[0],
        queue_ratio=unpacked[1],
        hazard_rate=unpacked[2],
        adverse_score=unpacked[3],
        toxic_prob=unpacked[4],
        spread=unpacked[5],
        micro_momentum=unpacked[6],
        volatility=unpacked[7],
        trade_flow=unpacked[8],
        inventory=unpacked[9]
    )


# ============================================================================
# 信号向量定义 (对应 C SignalVector)
# ============================================================================

@dataclass
class SignalVector:
    """模型预测信号向量 (位于 HFT_SIGNAL_OFFSET)"""
    action_direction: float = 0.0      # 动作方向 [-1, +1]
    action_aggression: float = 0.0     # 激进度 [0, 1]
    action_size_scale: float = 0.0     # 大小缩放 [0, 1]
    position_target: float = 0.0       # 目标仓位 [-1, +1]
    confidence: float = 0.0            # 置信度 [0, 1]
    regime_code: int = 0               # 市场状态编码
    expert_id: int = 0                 # 专家ID


SIGNAL_VECTOR_SIZE = struct.calcsize('<ddddddII' + 'd' * 26)  # 256 bytes


def pack_signal_vector(sv: SignalVector) -> bytes:
    """打包信号向量"""
    base = struct.pack('<ddddddII',
        sv.action_direction, sv.action_aggression, sv.action_size_scale,
        sv.position_target, sv.confidence, 0.0,  # padding to align
        sv.regime_code, sv.expert_id
    )
    # 填充到256 bytes
    padding = b'\x00' * (256 - len(base))
    return base + padding


def unpack_signal_vector(data: bytes) -> SignalVector:
    """解包信号向量"""
    unpacked = struct.unpack('<ddddddII', data[:48])
    return SignalVector(
        action_direction=unpacked[0],
        action_aggression=unpacked[1],
        action_size_scale=unpacked[2],
        position_target=unpacked[3],
        confidence=unpacked[4],
        regime_code=unpacked[6],
        expert_id=unpacked[7]
    )


# ============================================================================
# 版本兼容性检查
# ============================================================================

def check_version(version: int) -> bool:
    """检查版本是否兼容"""
    return HFT_MIN_COMPATIBLE_VERSION <= version <= HFT_MAX_COMPATIBLE_VERSION


def check_magic(magic: int) -> bool:
    """检查魔数是否匹配"""
    return magic == HFT_PROTOCOL_MAGIC


def negotiate_version(go_version: int, py_version: int) -> int:
    """协商使用哪个版本"""
    return min(go_version, py_version)


class ProtocolError(Exception):
    """协议基础错误"""
    pass


class MagicMismatchError(ProtocolError):
    """魔数不匹配"""
    pass


class VersionMismatchError(ProtocolError):
    """版本不匹配"""
    pass


def verify_header(magic: int, version: int) -> None:
    """验证协议头部"""
    if not check_magic(magic):
        raise MagicMismatchError(
            f"Magic mismatch: expected 0x{HFT_PROTOCOL_MAGIC:08X}, got 0x{magic:08X}"
        )
    if not check_version(version):
        raise VersionMismatchError(
            f"Version {version} not in compatible range "
            f"[{HFT_MIN_COMPATIBLE_VERSION}, {HFT_MAX_COMPATIBLE_VERSION}]"
        )


# ============================================================================
# Reversal Detection SHM Protocol (扩展协议)
# ============================================================================

# Reversal SHM 魔数和版本
REVERSAL_SHM_MAGIC = 0x52455653  # "REVS"
REVERSAL_SHM_VERSION = 1

# Reversal SHM 布局
REVERSAL_FEATURES_OFFSET = 16384
REVERSAL_FEATURES_SIZE = 640   # 512 + 128 reason
REVERSAL_SIGNAL_OFFSET = 17024  # 16384 + 640
REVERSAL_SIGNAL_SIZE = 256

# Verification SHM 定义
VERIFICATION_SHM_MAGIC = 0x54525554  # "TRUT"
VERIFICATION_SHM_VERSION = 1
VERIFICATION_METRICS_OFFSET = 17252  # 17024 + 256
VERIFICATION_METRICS_SIZE = 288

# 版本控制
PROTOCOL_VERSION_MAJOR = 1
PROTOCOL_VERSION_MINOR = 0
PROTOCOL_VERSION_PATCH = 0
PROTOCOL_VERSION_FULL = (PROTOCOL_VERSION_MAJOR << 16) | (PROTOCOL_VERSION_MINOR << 8) | PROTOCOL_VERSION_PATCH

# 验证标志位
VERIFICATION_FLAG_LATENCY_OK = 0x0001
VERIFICATION_FLAG_SLIPPAGE_OK = 0x0002
VERIFICATION_FLAG_CONSISTENCY_OK = 0x0004
VERIFICATION_FLAG_ANOMALY_FREE = 0x0008
VERIFICATION_FLAG_ALL_OK = 0x000F


@dataclass
class ReversalFeaturesSHM:
    """反转特征结构 - Python 写入，Go 读取 (640 bytes)"""
    # Header (24 bytes)
    magic: int = REVERSAL_SHM_MAGIC
    version: int = REVERSAL_SHM_VERSION
    timestamp_ns: int = 0
    sequence: int = 0

    # Price features (64 bytes)
    price_momentum_1m: float = 0.0
    price_momentum_5m: float = 0.0
    price_momentum_15m: float = 0.0
    price_zscore: float = 0.0
    price_percentile: float = 0.0
    price_velocity: float = 0.0
    price_acceleration: float = 0.0
    price_mean_reversion: float = 0.0

    # Volume features (32 bytes)
    volume_surge: float = 0.0
    volume_momentum: float = 0.0
    volume_zscore: float = 0.0
    relative_volume: float = 0.0

    # Volatility features (32 bytes)
    volatility_current: float = 0.0
    volatility_regime: float = 0.0
    atr_ratio: float = 0.0
    bollinger_position: float = 0.0

    # Order flow features (40 bytes)
    ofi_signal: float = 0.0
    trade_imbalance: float = 0.0
    bid_ask_pressure: float = 0.0
    order_book_slope: float = 0.0
    micro_price_drift: float = 0.0

    # Microstructure (32 bytes)
    spread_percentile: float = 0.0
    tick_pressure: float = 0.0
    queue_imbalance: float = 0.0
    trade_intensity: float = 0.0

    # Time features (16 bytes)
    time_of_day: float = 0.0
    day_of_week: int = 0
    is_market_open: int = 1
    session_type: int = 0

    # Metadata (16 bytes)
    symbol_id: int = 0
    timeframe: int = 0
    reserved: int = 0

    # Reason (128 bytes)
    reason: str = ""

    def pack(self) -> bytes:
        """打包为字节 - 640 bytes 固定大小"""
        # 基础数据 264 bytes
        data = struct.pack(
            '<IIQQ'  # Header: 24 bytes
            'dddddddd'  # Price features: 64 bytes
            'dddd'  # Volume features: 32 bytes
            'dddd'  # Volatility features: 32 bytes
            'ddddd'  # Order flow features: 40 bytes
            'dddd'  # Microstructure: 32 bytes
            'd'  # time_of_day: 8 bytes
            'IIII'  # day_of_week, is_market_open, session_type, padding: 16 bytes
            'IIII',  # symbol_id, timeframe, reserved, padding: 16 bytes
            self.magic, self.version, self.timestamp_ns, self.sequence,
            self.price_momentum_1m, self.price_momentum_5m, self.price_momentum_15m,
            self.price_zscore, self.price_percentile, self.price_velocity,
            self.price_acceleration, self.price_mean_reversion,
            self.volume_surge, self.volume_momentum, self.volume_zscore, self.relative_volume,
            self.volatility_current, self.volatility_regime, self.atr_ratio, self.bollinger_position,
            self.ofi_signal, self.trade_imbalance, self.bid_ask_pressure,
            self.order_book_slope, self.micro_price_drift,
            self.spread_percentile, self.tick_pressure, self.queue_imbalance, self.trade_intensity,
            self.time_of_day,
            self.day_of_week, self.is_market_open, self.session_type, 0,
            self.symbol_id, self.timeframe, self.reserved, 0
        )
        # Reason field (128 bytes)
        reason_bytes = self.reason.encode('utf-8')[:127]
        reason_padded = reason_bytes + b'\x00' * (128 - len(reason_bytes))
        data += reason_padded

        # Padding to 640 bytes (640 - 264 - 128 = 248)
        data += b'\x00' * 248
        return data

    @classmethod
    def unpack(cls, data: bytes) -> 'ReversalFeaturesSHM':
        """从字节解包"""
        if len(data) < 264:
            raise ValueError(f"Data too short: {len(data)} bytes")

        unpacked = struct.unpack(
            '<IIQQdddddddddddddddddddddddddddddIIIIIIII',
            data[:264]
        )

        # Extract reason (128 bytes at offset 264)
        reason = data[264:392].split(b'\x00')[0].decode('utf-8')

        return cls(
            magic=unpacked[0],
            version=unpacked[1],
            timestamp_ns=unpacked[2],
            sequence=unpacked[3],
            price_momentum_1m=unpacked[4],
            price_momentum_5m=unpacked[5],
            price_momentum_15m=unpacked[6],
            price_zscore=unpacked[7],
            price_percentile=unpacked[8],
            price_velocity=unpacked[9],
            price_acceleration=unpacked[10],
            price_mean_reversion=unpacked[11],
            volume_surge=unpacked[12],
            volume_momentum=unpacked[13],
            volume_zscore=unpacked[14],
            relative_volume=unpacked[15],
            volatility_current=unpacked[16],
            volatility_regime=unpacked[17],
            atr_ratio=unpacked[18],
            bollinger_position=unpacked[19],
            ofi_signal=unpacked[20],
            trade_imbalance=unpacked[21],
            bid_ask_pressure=unpacked[22],
            order_book_slope=unpacked[23],
            micro_price_drift=unpacked[24],
            spread_percentile=unpacked[25],
            tick_pressure=unpacked[26],
            queue_imbalance=unpacked[27],
            trade_intensity=unpacked[28],
            time_of_day=unpacked[29],
            day_of_week=unpacked[30],
            is_market_open=unpacked[31],
            session_type=unpacked[32],
            symbol_id=unpacked[33],
            timeframe=unpacked[34],
            reserved=unpacked[35],
            reason=reason
        )


@dataclass
class ReversalSignalSHM:
    """反转信号结构 - Python 写入，Go 读取 (256 bytes)"""
    # Header (24 bytes)
    magic: int = REVERSAL_SHM_MAGIC
    version: int = REVERSAL_SHM_VERSION
    timestamp_ns: int = 0
    sequence: int = 0

    # Signal data (40 bytes)
    signal_strength: float = 0.0
    confidence: float = 0.0
    probability: float = 0.0
    expected_return: float = 0.0
    time_horizon_ms: int = 0

    # Model info (24 bytes)
    model_version: int = 0
    model_type: int = 0
    inference_latency_us: int = 0
    feature_timestamp_ns: int = 0

    # Feature importance (64 bytes)
    top_feature_1: float = 0.0
    top_feature_2: float = 0.0
    top_feature_3: float = 0.0
    top_feature_4: float = 0.0
    top_feature_5: float = 0.0
    top_feature_6: float = 0.0
    top_feature_7: float = 0.0
    top_feature_8: float = 0.0

    # Risk metrics (32 bytes)
    prediction_uncertainty: float = 0.0
    market_regime: int = 0
    risk_score: float = 0.0
    max_adverse_excursion: float = 0.0

    # Execution advice (24 bytes)
    suggested_urgency: float = 0.0
    suggested_ttl_ms: int = 0
    execution_priority: int = 0
    reason_code: int = 0

    # Reason details (48 bytes)
    reason_details: str = ""

    def pack(self) -> bytes:
        """打包为字节 - 256 bytes 固定大小"""
        # Pack base data (208 bytes)
        data = struct.pack(
            '<IIQQ'  # Header: 24 bytes
            'dddd'  # Signal data: 32 bytes
            'I'  # time_horizon_ms: 4 bytes
            'III'  # model_version, model_type, inference_latency_us: 12 bytes
            'Q'  # feature_timestamp_ns: 8 bytes
            'dddddddd'  # Feature importance: 64 bytes
            'd'  # prediction_uncertainty: 8 bytes
            'I'  # market_regime: 4 bytes
            'dd'  # risk_score, max_adverse_excursion: 16 bytes
            'd'  # suggested_urgency: 8 bytes
            'III'  # suggested_ttl_ms, execution_priority, reason_code: 12 bytes
            'I',  # padding: 4 bytes
            self.magic, self.version, self.timestamp_ns, self.sequence,
            self.signal_strength, self.confidence, self.probability, self.expected_return,
            self.time_horizon_ms,
            self.model_version, self.model_type, self.inference_latency_us,
            self.feature_timestamp_ns,
            self.top_feature_1, self.top_feature_2, self.top_feature_3, self.top_feature_4,
            self.top_feature_5, self.top_feature_6, self.top_feature_7, self.top_feature_8,
            self.prediction_uncertainty, self.market_regime, self.risk_score,
            self.max_adverse_excursion,
            self.suggested_urgency, self.suggested_ttl_ms, self.execution_priority,
            self.reason_code, 0
        )

        # Reason details (48 bytes)
        reason_bytes = self.reason_details.encode('utf-8')[:47]
        reason_padded = reason_bytes + b'\x00' * (48 - len(reason_bytes))
        data += reason_padded

        return data

    @classmethod
    def unpack(cls, data: bytes) -> 'ReversalSignalSHM':
        """从字节解包"""
        if len(data) < 256:
            raise ValueError(f"Data too short: {len(data)} bytes, expected 256")

        unpacked = struct.unpack(
            '<IIQQddddIIIIQddddddddddIddddddIIII',
            data[:208]
        )

        # Extract reason_details (48 bytes at offset 208)
        reason_details = data[208:256].split(b'\x00')[0].decode('utf-8')

        return cls(
            magic=unpacked[0],
            version=unpacked[1],
            timestamp_ns=unpacked[2],
            sequence=unpacked[3],
            signal_strength=unpacked[4],
            confidence=unpacked[5],
            probability=unpacked[6],
            expected_return=unpacked[7],
            time_horizon_ms=unpacked[8],
            model_version=unpacked[9],
            model_type=unpacked[10],
            inference_latency_us=unpacked[11],
            feature_timestamp_ns=unpacked[12],
            top_feature_1=unpacked[13],
            top_feature_2=unpacked[14],
            top_feature_3=unpacked[15],
            top_feature_4=unpacked[16],
            top_feature_5=unpacked[17],
            top_feature_6=unpacked[18],
            top_feature_7=unpacked[19],
            top_feature_8=unpacked[20],
            prediction_uncertainty=unpacked[21],
            market_regime=unpacked[22],
            risk_score=unpacked[23],
            max_adverse_excursion=unpacked[24],
            suggested_urgency=unpacked[25],
            suggested_ttl_ms=unpacked[26],
            execution_priority=unpacked[27],
            reason_code=unpacked[28],
            reason_details=reason_details
        )


@dataclass
class VerificationMetricsSHM:
    """真实性检验指标结构 (288 bytes)"""
    # Header (16 bytes)
    magic: int = VERIFICATION_SHM_MAGIC
    version: int = VERIFICATION_SHM_VERSION
    timestamp_ns: int = 0

    # Latency measurements (32 bytes)
    latency_total_us: int = 0
    latency_feature_us: int = 0
    latency_inference_us: int = 0
    latency_decision_us: int = 0
    latency_transmit_us: int = 0
    latency_execute_us: int = 0

    # Validation status (16 bytes)
    validation_flags: int = 0
    anomaly_count: int = 0
    slippage_bps: float = 0.0
    consistency_score: float = 0.0

    # Extended metrics (64 bytes)
    execution_price: float = 0.0
    predicted_price: float = 0.0
    price_error: float = 0.0
    price_error_std: float = 0.0
    market_impact_bps: float = 0.0
    timing_score: float = 0.0
    queue_position_error: float = 0.0
    fill_rate: float = 0.0

    # Quality metrics (32 bytes)
    signal_to_noise: float = 0.0
    prediction_accuracy: float = 0.0
    model_drift_score: float = 0.0
    data_freshness_ms: float = 0.0
    consecutive_errors: int = 0
    recovery_count: int = 0

    def pack(self) -> bytes:
        """打包为字节 - 288 bytes 固定大小"""
        # Header + Latency + Validation (64 bytes)
        data = struct.pack(
            '<IIQQ'  # Header: 16 bytes
            'IIIIIIII'  # Latency measurements: 32 bytes (6 values + 2 padding)
            'IIff',  # Validation status: 16 bytes
            self.magic, self.version, self.timestamp_ns, 0,  # timestamp_ns is 8 bytes
            self.latency_total_us, self.latency_feature_us, self.latency_inference_us,
            self.latency_decision_us, self.latency_transmit_us, self.latency_execute_us,
            0, 0,  # padding
            self.validation_flags, self.anomaly_count, self.slippage_bps, self.consistency_score
        )

        # Extended metrics (64 bytes)
        data += struct.pack(
            '<dddddddd',
            self.execution_price, self.predicted_price, self.price_error, self.price_error_std,
            self.market_impact_bps, self.timing_score, self.queue_position_error, self.fill_rate
        )

        # Quality metrics (32 bytes)
        data += struct.pack(
            '<ffffIIff',
            self.signal_to_noise, self.prediction_accuracy, self.model_drift_score, self.data_freshness_ms,
            self.consecutive_errors, self.recovery_count, 0.0, 0.0  # padding
        )

        # Reserved (128 bytes)
        data += b'\x00' * 128

        return data

    @classmethod
    def unpack(cls, data: bytes) -> 'VerificationMetricsSHM':
        """从字节解包"""
        if len(data) < 288:
            raise ValueError(f"Data too short: {len(data)} bytes, expected 288")

        # Unpack header + latency + validation (64 bytes)
        header = struct.unpack('<IIQQIIIIIIIIIIff', data[:64])

        # Unpack extended metrics (64 bytes at offset 64)
        extended = struct.unpack('<dddddddd', data[64:128])

        # Unpack quality metrics (32 bytes at offset 128)
        quality = struct.unpack('<ffffIIff', data[128:160])

        return cls(
            magic=header[0],
            version=header[1],
            timestamp_ns=header[2],
            latency_total_us=header[4],
            latency_feature_us=header[5],
            latency_inference_us=header[6],
            latency_decision_us=header[7],
            latency_transmit_us=header[8],
            latency_execute_us=header[9],
            validation_flags=header[12],
            anomaly_count=header[13],
            slippage_bps=header[14],
            consistency_score=header[15],
            execution_price=extended[0],
            predicted_price=extended[1],
            price_error=extended[2],
            price_error_std=extended[3],
            market_impact_bps=extended[4],
            timing_score=extended[5],
            queue_position_error=extended[6],
            fill_rate=extended[7],
            signal_to_noise=quality[0],
            prediction_accuracy=quality[1],
            model_drift_score=quality[2],
            data_freshness_ms=quality[3],
            consecutive_errors=quality[4],
            recovery_count=quality[5]
        )

    def is_latency_ok(self) -> bool:
        """检查延迟是否正常"""
        return (self.validation_flags & VERIFICATION_FLAG_LATENCY_OK) != 0

    def is_slippage_ok(self) -> bool:
        """检查滑点是否正常"""
        return (self.validation_flags & VERIFICATION_FLAG_SLIPPAGE_OK) != 0

    def is_consistency_ok(self) -> bool:
        """检查一致性是否正常"""
        return (self.validation_flags & VERIFICATION_FLAG_CONSISTENCY_OK) != 0

    def is_all_ok(self) -> bool:
        """检查所有验证是否通过"""
        return (self.validation_flags & VERIFICATION_FLAG_ALL_OK) == VERIFICATION_FLAG_ALL_OK


def check_reversal_magic(magic: int) -> bool:
    """检查 Reversal SHM 魔数"""
    return magic == REVERSAL_SHM_MAGIC


def check_reversal_version(version: int) -> bool:
    """检查 Reversal SHM 版本"""
    return version == REVERSAL_SHM_VERSION


def check_verification_magic(magic: int) -> bool:
    """检查 Verification SHM 魔数"""
    return magic == VERIFICATION_SHM_MAGIC


def check_verification_version(version: int) -> bool:
    """检查 Verification SHM 版本"""
    return version == VERIFICATION_SHM_VERSION


def check_version_major(version: int) -> bool:
    """检查主版本号"""
    return (version >> 16) == PROTOCOL_VERSION_MAJOR


def check_version_compat(version: int) -> bool:
    """检查版本兼容性"""
    major_ok = (version >> 16) == PROTOCOL_VERSION_MAJOR
    minor_ok = ((version >> 8) & 0xFF) <= PROTOCOL_VERSION_MINOR
    return major_ok and minor_ok
