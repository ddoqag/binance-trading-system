"""
shm_bridge.py - Shared Memory Bridge for Reversal Detection

扩展共享内存协议，支持反转特征和信号的传输
确保延迟 < 1ms
"""

import struct
import mmap
import os
import time
import threading
from dataclasses import dataclass
from typing import Optional, Callable
import logging

logger = logging.getLogger(__name__)

# 协议常量
REVERSAL_SHM_MAGIC = 0x52455653  # "REVS" - Reversal Signal
REVERSAL_SHM_VERSION = 1

# 共享内存布局 (从偏移 16384 开始，与 go-features-dev 协商确定)
REVERSAL_FEATURES_OFFSET = 16384
REVERSAL_SIGNAL_OFFSET = 16896  # 16384 + 512
REVERSAL_FEATURES_SIZE = 512    # 512
REVERSAL_SIGNAL_SIZE = 512
REVERSAL_SHM_SIZE = 256


@dataclass
@dataclass
class ReversalFeaturesSHM:
    """
    反转特征结构 - Python 写入，Go 读取
    大小: 512 bytes
    """
    # 头部 (16 bytes)
    magic: int = REVERSAL_SHM_MAGIC
    version: int = REVERSAL_SHM_VERSION
    timestamp_ns: int = 0
    sequence: int = 0

    # 价格特征 (64 bytes)
    price_momentum_1m: float = 0.0
    price_momentum_5m: float = 0.0
    price_momentum_15m: float = 0.0
    price_zscore: float = 0.0
    price_percentile: float = 0.0
    price_velocity: float = 0.0
    price_acceleration: float = 0.0
    price_mean_reversion: float = 0.0

    # 成交量特征 (32 bytes)
    volume_surge: float = 0.0
    volume_momentum: float = 0.0
    volume_zscore: float = 0.0
    relative_volume: float = 0.0

    # 波动率特征 (32 bytes)
    volatility_current: float = 0.0
    volatility_regime: float = 0.0
    atr_ratio: float = 0.0
    bollinger_position: float = 0.0

    # 订单流特征 (40 bytes)
    ofi_signal: float = 0.0
    trade_imbalance: float = 0.0
    bid_ask_pressure: float = 0.0
    order_book_slope: float = 0.0
    micro_price_drift: float = 0.0

    # 市场微观结构 (32 bytes)
    spread_percentile: float = 0.0
    tick_pressure: float = 0.0
    queue_imbalance: float = 0.0
    trade_intensity: float = 0.0

    # 时间特征 (16 bytes)
    time_of_day: float = 0.0  # 0-1 表示当天进度
    day_of_week: int = 0
    is_market_open: int = 1
    session_type: int = 0  # 0=正常, 1=开盘, 2=收盘

    # 元数据 (16 bytes)
    symbol_id: int = 0
    timeframe: int = 0  # 秒数
    reserved: int = 0

    def pack(self) -> bytes:
        """打包为字节 - 512 bytes 固定大小"""
        # 基础数据 264 bytes，填充到 512 bytes
        data = struct.pack(
            '<IIQQ'  # 头部: 24 bytes
            'dddddddd'  # 价格特征: 64 bytes
            'dddd'  # 成交量特征: 32 bytes
            'dddd'  # 波动率特征: 32 bytes
            'ddddd'  # 订单流特征: 40 bytes
            'dddd'  # 微观结构: 32 bytes
            'd'  # 时间特征 (time_of_day): 8 bytes
            'IIII'  # 时间特征 (day_of_week, is_market_open, session_type, padding): 16 bytes
            'IIII',  # 元数据 (symbol_id, timeframe, reserved, padding): 16 bytes
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
        # 填充到 512 bytes
        padding_size = 512 - len(data)
        return data + b'\x00' * padding_size

    @classmethod
    def unpack(cls, data: bytes) -> 'ReversalFeaturesSHM':
        """从字节解包 - 解包前264 bytes的实际数据"""
        if len(data) < 264:
            raise ValueError(f"Data too short: {len(data)} bytes, expected at least 264")

        # 解包实际数据部分 (前264 bytes)
        unpacked = struct.unpack(
            '<IIQQ'  # 头部
            'dddddddd'  # 价格特征
            'dddd'  # 成交量特征
            'dddd'  # 波动率特征
            'ddddd'  # 订单流特征
            'dddd'  # 微观结构
            'd'  # time_of_day
            'IIII'  # day_of_week, is_market_open, session_type, padding
            'IIII',  # symbol_id, timeframe, reserved, padding
            data[:264]
        )

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
            reserved=unpacked[35]
        )
class ReversalSignalSHM:
    """
    反转信号结构 - Python 写入，Go 读取
    大小: 512 bytes
    """
    # 头部 (16 bytes)
    magic: int = REVERSAL_SHM_MAGIC
    version: int = REVERSAL_SHM_VERSION
    timestamp_ns: int = 0
    sequence: int = 0

    # 信号数据 (40 bytes)
    signal_strength: float = 0.0  # -1.0 to 1.0, 负=下跌反转, 正=上涨反转
    confidence: float = 0.0  # 0.0 to 1.0
    probability: float = 0.0  # 0.0 to 1.0
    expected_return: float = 0.0  # 预期收益
    time_horizon_ms: int = 0  # 预期时间范围

    # 模型信息 (24 bytes)
    model_version: int = 0
    model_type: int = 0  # 0=LightGBM, 1=NN, 2=Ensemble
    inference_latency_us: int = 0
    feature_timestamp_ns: int = 0

    # 特征重要性 (64 bytes) - 8个最重要的特征
    top_feature_1: float = 0.0
    top_feature_2: float = 0.0
    top_feature_3: float = 0.0
    top_feature_4: float = 0.0
    top_feature_5: float = 0.0
    top_feature_6: float = 0.0
    top_feature_7: float = 0.0
    top_feature_8: float = 0.0

    # 风险指标 (32 bytes)
    prediction_uncertainty: float = 0.0
    market_regime: int = 0  # 0=unknown, 1=trend_up, 2=trend_down, 3=range, 4=high_vol
    risk_score: float = 0.0  # 0-1
    max_adverse_excursion: float = 0.0  # 最大不利波动

    # 执行建议 (24 bytes)
    suggested_urgency: float = 0.0  # 0-1
    suggested_ttl_ms: int = 0
    execution_priority: int = 0  # 0=normal, 1=high, 2=critical
    reserved: int = 0

    # 信号原因和元数据 (256 bytes)
    # Reason codes: 1=price_momentum, 2=volume_surge, 3=ofi_signal, 4=volatility_spike,
    #               5=support_resistance, 6=pattern_completion, 7=composite
    reason_code: int = 0
    reason_details: str = ""  # UTF-8 encoded description or JSON

    def pack(self) -> bytes:
        """打包为字节 - 512 bytes 固定大小"""
        # 基础数据 256 bytes + reason_details 248 bytes = 504 bytes
        # + reason_code 4 bytes + padding 4 bytes = 512 bytes
        reason_bytes = self.reason_details.encode('utf-8')[:247]  # 限制247字节，留1字节给null terminator
        reason_padded = reason_bytes + b'\x00' * (248 - len(reason_bytes))

        data = struct.pack(
            '<IIQQ'  # 头部: 24 bytes
            'dddd'  # 信号数据: 32 bytes
            'I'  # time_horizon_ms: 4 bytes
            'III'  # model_version, model_type, inference_latency_us: 12 bytes
            'Q'  # feature_timestamp_ns: 8 bytes
            'dddddddd'  # 特征重要性: 64 bytes
            'd'  # prediction_uncertainty: 8 bytes
            'I'  # market_regime: 4 bytes
            'dd'  # risk_score, max_adverse_excursion: 16 bytes
            'd'  # suggested_urgency: 8 bytes
            'III'  # suggested_ttl_ms, execution_priority, reserved: 12 bytes
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
            self.reserved, 0
        )
        # 添加 reason_code 和 reason_details
        data += struct.pack('<I', self.reason_code)
        data += reason_padded
        # 确保总大小为 512 bytes
        if len(data) < 512:
            data += b'\x00' * (512 - len(data))
        return data[:512]

    @classmethod
    def unpack(cls, data: bytes) -> 'ReversalSignalSHM':
        """从字节解包"""
        if len(data) < 512:
            raise ValueError(f"Data too short: {len(data)} bytes, expected 512")

        # 解包前256 bytes的基础数据
        unpacked = struct.unpack(
            '<IIQQ'  # 头部
            'dddd'  # 信号数据
            'I'  # time_horizon_ms
            'III'  # model信息
            'Q'  # feature_timestamp_ns
            'dddddddd'  # 特征重要性
            'd'  # prediction_uncertainty
            'I'  # market_regime
            'dd'  # risk_score, max_adverse_excursion
            'd'  # suggested_urgency
            'III'  # suggested_ttl_ms, execution_priority, reserved
            'I',  # padding
            data[:256]
        )

        # 解包 reason_code 和 reason_details (256-512)
        reason_code = struct.unpack('<I', data[256:260])[0]
        reason_details = data[260:512].split(b'\x00')[0].decode('utf-8')

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
            reserved=unpacked[28],
            reason_code=reason_code,
            reason_details=reason_details
        )
class SharedMemoryBridge:
    """
    共享内存桥接器 - 用于反转特征和信号的高速传输

    支持两种模式:
    1. SHM 模式: 通过 mmap 共享内存 (延迟 < 0.5μs)
    2. ZMQ 模式: 通过 ZeroMQ 传输 (延迟 < 1ms)
    """

    def __init__(
        self,
        shm_path: Optional[str] = None,
        zmq_endpoint: Optional[str] = None,
        use_shm: bool = True
    ):
        self.shm_path = shm_path or "/tmp/hft_reversal_shm"
        self.zmq_endpoint = zmq_endpoint or "ipc:///tmp/hft_reversal.sock"
        self.use_shm = use_shm

        self._shm_fd: Optional[int] = None
        self._shm_mmap: Optional[mmap.mmap] = None
        self._sequence = 0
        self._lock = threading.Lock()

        # ZMQ 相关
        self._zmq_context = None
        self._zmq_socket = None

        # 统计
        self.write_count = 0
        self.write_errors = 0
        self.last_write_latency_us = 0.0

    def connect(self) -> bool:
        """连接到共享内存"""
        if self.use_shm:
            return self._connect_shm()
        else:
            return self._connect_zmq()

    def _connect_shm(self) -> bool:
        """连接到 mmap 共享内存"""
        try:
            # 创建或打开文件
            fd = os.open(
                self.shm_path,
                os.O_RDWR | os.O_CREAT,
                0o666
            )

            # 确保文件大小足够
            os.ftruncate(fd, 1024 * 1024)  # 1MB

            # 内存映射
            self._shm_mmap = mmap.mmap(fd, 1024 * 1024, access=mmap.ACCESS_WRITE)
            self._shm_fd = fd

            logger.info(f"Connected to SHM: {self.shm_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to SHM: {e}")
            return False

    def _connect_zmq(self) -> bool:
        """连接到 ZMQ"""
        try:
            import zmq
            self._zmq_context = zmq.Context()
            self._zmq_socket = self._zmq_context.socket(zmq.PUB)
            self._zmq_socket.bind(self.zmq_endpoint)
            logger.info(f"Connected to ZMQ: {self.zmq_endpoint}")
            return True
        except ImportError:
            logger.error("zmq not installed, falling back to SHM")
            self.use_shm = True
            return self._connect_shm()
        except Exception as e:
            logger.error(f"Failed to connect to ZMQ: {e}")
            return False

    def disconnect(self):
        """断开连接"""
        if self._shm_mmap:
            self._shm_mmap.close()
            self._shm_mmap = None

        if self._shm_fd:
            os.close(self._shm_fd)
            self._shm_fd = None

        if self._zmq_socket:
            self._zmq_socket.close()
            self._zmq_socket = None

        if self._zmq_context:
            self._zmq_context.term()
            self._zmq_context = None

        logger.info("Disconnected from SHM/ZMQ")

    def write_features(self, features: ReversalFeaturesSHM) -> bool:
        """写入反转特征到共享内存"""
        start_ns = time.time_ns()

        try:
            with self._lock:
                self._sequence += 1
                features.sequence = self._sequence
                features.timestamp_ns = start_ns

                if self.use_shm and self._shm_mmap:
                    # 写入 SHM
                    data = features.pack()
                    self._shm_mmap[REVERSAL_FEATURES_OFFSET:REVERSAL_FEATURES_OFFSET + REVERSAL_FEATURES_SIZE] = data
                elif self._zmq_socket:
                    # 通过 ZMQ 发送
                    self._zmq_socket.send(b"F" + features.pack(), zmq.NOBLOCK)

            self.write_count += 1
            self.last_write_latency_us = (time.time_ns() - start_ns) / 1000.0
            return True

        except Exception as e:
            self.write_errors += 1
            logger.error(f"Failed to write features: {e}")
            return False

    def write_signal(self, signal: ReversalSignalSHM) -> bool:
        """写入反转信号到共享内存"""
        start_ns = time.time_ns()

        try:
            with self._lock:
                self._sequence += 1
                signal.sequence = self._sequence
                signal.timestamp_ns = start_ns

                if self.use_shm and self._shm_mmap:
                    # 写入 SHM
                    data = signal.pack()
                    self._shm_mmap[REVERSAL_SIGNAL_OFFSET:REVERSAL_SIGNAL_OFFSET + len(data)] = data
                elif self._zmq_socket:
                    # 通过 ZMQ 发送
                    self._zmq_socket.send(b"S" + signal.pack(), zmq.NOBLOCK)

            self.write_count += 1
            self.last_write_latency_us = (time.time_ns() - start_ns) / 1000.0
            return True

        except Exception as e:
            self.write_errors += 1
            logger.error(f"Failed to write signal: {e}")
            return False

    def read_features(self) -> Optional[ReversalFeaturesSHM]:
        """从共享内存读取反转特征 (用于调试)"""
        if not self.use_shm or not self._shm_mmap:
            return None

        try:
            data = self._shm_mmap[REVERSAL_FEATURES_OFFSET:REVERSAL_FEATURES_OFFSET + REVERSAL_FEATURES_SIZE]
            return ReversalFeaturesSHM.unpack(data)
        except Exception as e:
            logger.error(f"Failed to read features: {e}")
            return None

    def read_signal(self) -> Optional[ReversalSignalSHM]:
        """从共享内存读取反转信号 (用于调试)"""
        if not self.use_shm or not self._shm_mmap:
            return None

        try:
            data = self._shm_mmap[REVERSAL_SIGNAL_OFFSET:REVERSAL_SIGNAL_OFFSET + 256]
            return ReversalSignalSHM.unpack(data)
        except Exception as e:
            logger.error(f"Failed to read signal: {e}")
            return None

    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            'write_count': self.write_count,
            'write_errors': self.write_errors,
            'last_write_latency_us': self.last_write_latency_us,
            'sequence': self._sequence,
            'mode': 'shm' if self.use_shm else 'zmq'
        }

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False
