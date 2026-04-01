"""
shm_reader.py
Python 端共享内存读取器
解析 Go Engine 写入的共享内存数据

协议定义参见: protocol.h
"""

import mmap
import struct
import time
from typing import Optional, List, Tuple
from dataclasses import dataclass
from ctypes import Structure, c_uint32, c_uint64, c_double, c_uint8, c_int


@dataclass
class PriceLevel:
    """订单簿价位"""
    price: float
    quantity: float
    orders: int


@dataclass
class MarketSnapshot:
    """市场快照"""
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


@dataclass
class OrderStatusUpdate:
    """订单状态更新"""
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


@dataclass
class TradeExecution:
    """成交执行"""
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


@dataclass
class Heartbeat:
    """心跳"""
    magic: int
    version: int
    timestamp_ns: int
    sequence: int
    go_running: bool
    ai_running: bool


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


# 结构体格式定义 (for struct.unpack)
# 按照 protocol.h 的内存布局

HEADER_FORMAT = (
    '<I'  # magic (uint32_t)
    'I'  # version
    'Q'  # size_bytes (uint64_t)
    'Q'  # go_write_index
    'Q'  # go_read_index
    'Q'  # ai_write_index
    'Q'  # ai_read_index
    'Q'  # messages_sent_go
    'Q'  # messages_sent_ai
    'Q'  # messages_lost
    'Q'  # last_heartbeat_go_ns
    'Q'  # last_heartbeat_ai_ns
)

HEARTBEAT_FORMAT = (
    '<I'  # magic
    'I'  # version
    'Q'  # timestamp_ns
    'I'  # sequence
    'B'  # go_running (uint8_t)
    'B'  # ai_running (uint8_t)
)

ACCOUNT_INFO_FORMAT = (
    '<d'  # total_balance
    'd'  # available_balance
    'd'  # position_size
    'd'  # entry_price
    'd'  # unrealized_pnl
    'd'  # realized_pnl_today
    'I'  # trades_today
)

PRICE_LEVEL_FORMAT = (
    '<d'  # price
    'd'  # quantity
    'I'  # orders
)

MARKET_SNAPSHOT_FORMAT = (
    '<Q'  # timestamp_ns
    'Q'  # sequence
    'd'  # best_bid
    'd'  # best_ask
    'd'  # last_price
    'd'  # micro_price
    'd'  # order_flow_imbalance
    'd'  # trade_imbalance
    'd'  # bid_queue_position
    'd'  # ask_queue_position
    'd'  # spread
    'd'  # volatility_estimate
    'd'  # trade_intensity
    'd'  # adverse_score
    'd'  # toxic_probability
)

ORDER_STATUS_FORMAT = (
    '<Q'  # order_id
    'Q'  # command_id
    'Q'  # timestamp_ns
    'I'  # side
    'I'  # type
    'I' # status
    'd'  # price
    'd'  # original_quantity
    'd'  # filled_quantity
    'd'  # remaining_quantity
    'd'  # average_fill_price
    'd'  # latency_us
    'B'  # is_maker
)

TRADE_EXECUTION_FORMAT = (
    '<Q'  # trade_id
    'Q'  # order_id
    'Q'  # timestamp_ns
    'I'  # side
    'd'  # price
    'd'  # quantity
    'd'  # commission
    'd'  # realized_pnl
    'd'  # adverse_selection
    'B'  # is_maker
)

# 常数
HFT_PROTOCOL_MAGIC = 0x48465453
HFT_PROTOCOL_VERSION = 1
HFT_MAX_ORDER_BOOK_DEPTH = 20
HFT_SHM_SIZE_DEFAULT = 64 * 1024 * 1024  # 64MB


class SharedMemoryReader:
    """共享内存读取器

    从共享内存读取 Go Engine 发送的市场数据和订单更新
    """

    def __init__(self, shm_name: str = "hft_shared_memory", size: int = HFT_SHM_SIZE_DEFAULT):
        self.shm_name = shm_name
        self.size = size
        self.mmap: Optional[mmap.mmap] = None
        self._buffer = bytearray()

    def connect(self) -> bool:
        """连接到共享内存"""
        try:
            # Windows 创建或打开文件映射
            self.mmap = mmap.mmap(
                -1,
                self.size,
                tagname=self.shm_name,
                access=mmap.ACCESS_READ
            )
            return self._verify_header()
        except Exception as e:
            print(f"Failed to connect to shared memory: {e}")
            return False

    def _verify_header(self) -> bool:
        """验证头部魔数和版本"""
        self.mmap.seek(0)
        header_bytes = self.mmap.read(struct.calcsize(HEADER_FORMAT))
        magic, version = struct.unpack('<II', header_bytes[:8])

        if magic != HFT_PROTOCOL_MAGIC:
            print(f"Invalid magic: 0x{magic:08x}, expected 0x{HFT_PROTOCOL_MAGIC:08x}")
            return False

        if version != HFT_PROTOCOL_VERSION:
            print(f"Invalid version: {version}, expected {HFT_PROTOCOL_VERSION}")
            return False

        return True

    def read_header(self) -> SharedMemoryHeader:
        """读取头部信息"""
        self.mmap.seek(0)
        header_bytes = self.mmap.read(struct.calcsize(HEADER_FORMAT))
        unpacked = struct.unpack(HEADER_FORMAT, header_bytes)

        (magic, version, size_bytes,
         go_write_index, go_read_index, ai_write_index, ai_read_index,
         messages_sent_go, messages_sent_ai, messages_lost,
         last_heartbeat_go_ns, last_heartbeat_ai_ns) = unpacked

        # 读取心跳
        heartbeat_bytes = self.mmap.read(struct.calcsize(HEARTBEAT_FORMAT))
        hb_unpacked = struct.unpack(HEARTBEAT_FORMAT, heartbeat_bytes)
        hb_magic, hb_version, hb_ts, hb_seq, go_run, ai_run = hb_unpacked
        heartbeat = Heartbeat(
            magic=hb_magic,
            version=hb_version,
            timestamp_ns=hb_ts,
            sequence=hb_seq,
            go_running=bool(go_run),
            ai_running=bool(ai_run)
        )

        # 读取账户信息
        account_bytes = self.mmap.read(struct.calcsize(ACCOUNT_INFO_FORMAT))
        acc_unpacked = struct.unpack(ACCOUNT_INFO_FORMAT, account_bytes)
        account = AccountInfo(
            total_balance=acc_unpacked[0],
            available_balance=acc_unpacked[1],
            position_size=acc_unpacked[2],
            entry_price=acc_unpacked[3],
            unrealized_pnl=acc_unpacked[4],
            realized_pnl_today=acc_unpacked[5],
            trades_today=acc_unpacked[6]
        )

        # 读取最新市场快照
        snapshot = self._read_market_snapshot()

        return SharedMemoryHeader(
            magic=magic,
            version=version,
            size_bytes=size_bytes,
            go_write_index=go_write_index,
            go_read_index=go_read_index,
            ai_write_index=ai_write_index,
            ai_read_index=ai_read_index,
            messages_sent_go=messages_sent_go,
            messages_sent_ai=messages_sent_ai,
            messages_lost=messages_lost,
            last_heartbeat_go_ns=last_heartbeat_go_ns,
            last_heartbeat_ai_ns=last_heartbeat_ai_ns,
            last_heartbeat=heartbeat,
            account_info=account,
            last_market_snapshot=snapshot
        )

    def _read_market_snapshot(self) -> MarketSnapshot:
        """读取市场快照"""
        snapshot_bytes = self.mmap.read(struct.calcsize(MARKET_SNAPSHOT_FORMAT))
        unpacked = struct.unpack(MARKET_SNAPSHOT_FORMAT, snapshot_bytes)

        # 读取 bids
        num_bids = HFT_MAX_ORDER_BOOK_DEPTH
        bids = []
        for _ in range(num_bids):
            pl_bytes = self.mmap.read(struct.calcsize(PRICE_LEVEL_FORMAT))
            pl_unpacked = struct.unpack(PRICE_LEVEL_FORMAT, pl_bytes)
            if pl_unpacked[0] > 0:  # 只添加有效价位
                bids.append(PriceLevel(price=pl_unpacked[0], quantity=pl_unpacked[1], orders=pl_unpacked[2]))

        # 读取 asks
        num_asks = HFT_MAX_ORDER_BOOK_DEPTH
        asks = []
        for _ in range(num_asks):
            pl_bytes = self.mmap.read(struct.calcsize(PRICE_LEVEL_FORMAT))
            pl_unpacked = struct.unpack(PRICE_LEVEL_FORMAT, pl_bytes)
            if pl_unpacked[0] > 0:
                asks.append(PriceLevel(price=pl_unpacked[0], quantity=pl_unpacked[1], orders=pl_unpacked[2]))

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

    def read_latest_market_snapshot(self) -> MarketSnapshot:
        """读取头部中缓存的最新市场快照"""
        # 头部位置: 0
        # HEADER_FORMAT 大小
        offset = struct.calcsize(HEADER_FORMAT)
        # + heartbeat
        offset += struct.calcsize(HEARTBEAT_FORMAT)
        # + account_info
        offset += struct.calcsize(ACCOUNT_INFO_FORMAT)

        self.mmap.seek(offset)
        return self._read_market_snapshot()

    def is_go_running(self) -> bool:
        """检查 Go 引擎是否运行"""
        header = self.read_header()
        return header.last_heartbeat.go_running

    def get_latency_ms(self) -> float:
        """获取从上次心跳到现在的延迟 (ms)"""
        header = self.read_header()
        now_ns = time.time_ns()
        return (now_ns - header.last_heartbeat_go_ns) / 1_000_000.0

    def close(self):
        """关闭映射"""
        if self.mmap:
            self.mmap.close()
            self.mmap = None


class SharedMemoryWriter:
    """共享内存写入器

    Python 端写入订单命令到共享内存，供 Go Engine 读取
    """

    def __init__(self, shm_name: str = "hft_shared_memory", size: int = HFT_SHM_SIZE_DEFAULT):
        self.shm_name = shm_name
        self.size = size
        self.mmap: Optional[mmap.mmap] = None
        self._command_id = 0

    def connect(self) -> bool:
        """连接到共享内存（写入模式）"""
        try:
            self.mmap = mmap.mmap(
                -1,
                self.size,
                tagname=self.shm_name,
                access=mmap.ACCESS_WRITE
            )
            return True
        except Exception as e:
            print(f"Failed to connect for writing: {e}")
            return False

    def write_order_command(self, order_type: int, side: int, price: float,
                            quantity: float, max_slippage: float = 0.001,
                            expires_after_ms: int = 5000,
                            dry_run: bool = True) -> int:
        """写入订单命令"""
        if self.mmap is None:
            return -1

        self._command_id += 1
        command_id = self._command_id
        timestamp_ns = time.time_ns()

        # 打包数据
        data = struct.pack(
            '<QQIIdddB',
            command_id,
            timestamp_ns,
            order_type,
            side,
            price,
            quantity,
            max_slippage,
            expires_after_ms,
            1 if dry_run else 0
        )

        # TODO: 写入环形缓冲区
        # 简化版本：直接写到固定位置，覆盖
        buffer_start = struct.calcsize(HEADER_FORMAT) + \
                       struct.calcsize(HEARTBEAT_FORMAT) + \
                       struct.calcsize(ACCOUNT_INFO_FORMAT) + \
                       HFT_MAX_ORDER_BOOK_DEPTH * 2 * struct.calcsize(PRICE_LEVEL_FORMAT) + \
                       struct.calcsize(MARKET_SNAPSHOT_FORMAT)

        self.mmap.seek(buffer_start)
        self.mmap.write(data)
        self.mmap.flush()

        return command_id

    def update_heartbeat(self, ai_running: bool = True):
        """更新心跳"""
        if self.mmap is None:
            return

        self.mmap.seek(0)
        header = self.read_header()

        # 更新 AI 心跳时间
        now_ns = time.time_ns()
        offset = struct.calcsize(HEADER_FORMAT) + \
                 8 * 8  # 跳过前面的字段到 last_heartbeat_ai_ns
        self.mmap.seek(offset)
        self.mmap.write(struct.pack('<Q', now_ns))
        self.mmap.flush()

    def close(self):
        """关闭"""
        if self.mmap:
            self.mmap.close()
            self.mmap = None


# 消息类型常量
class MessageTypes:
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
class OrderTypes:
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
