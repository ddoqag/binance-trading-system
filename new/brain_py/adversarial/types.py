"""
类型定义 - 对抗训练模块
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict
import numpy as np


class AdversarialType(Enum):
    """恶意做市商行为类型"""
    SPOOFING = "spoofing"        # 假挂单
    LAYERING = "layering"        # 多层诱导
    STOP_HUNTING = "stop_hunting"  # 扫止损


@dataclass
class AdversarialState:
    """当前对抗状态"""
    is_active: bool
    adv_type: Optional[AdversarialType]
    start_time: float
    intensity: float  # 攻击强度 [0, 1]

    def get_label(self) -> int:
        """返回训练标签: 1=陷阱, 0=正常"""
        return 1 if self.is_active else 0


@dataclass
class TrapFeatures:
    """陷阱特征 (12维)"""
    ofi: float                    # Order Flow Imbalance
    cancel_rate: float            # 撤单率 = cancels / adds 最近窗口
    depth_imbalance: float        # 挂单深度失衡
    trade_intensity: float        # 成交强度
    spread_change: float          # 价差变化率
    spread_level: float           # 当前价差水平
    queue_pressure: float         # 队列压力
    price_velocity: float         # 价格加速度
    volume_per_price: float       # 单位价格成交量
    time_since_last_spike: float  # 上次异常多久前
    tick_entropy: float           # Tick-level 熵 → 机械化诱捕检测
    vpin: float                   # VPIN → 知情交易概率

    def to_numpy(self) -> np.ndarray:
        """转换为 numpy 数组 (12,)"""
        return np.array([
            self.ofi,
            self.cancel_rate,
            self.depth_imbalance,
            self.trade_intensity,
            self.spread_change,
            self.spread_level,
            self.queue_pressure,
            self.price_velocity,
            self.volume_per_price,
            self.time_since_last_spike,
            self.tick_entropy,
            self.vpin,
        ], dtype=np.float32)

    @classmethod
    def from_numpy(cls, arr: np.ndarray) -> "TrapFeatures":
        """从 numpy 数组创建"""
        return cls(
            ofi=float(arr[0]),
            cancel_rate=float(arr[1]),
            depth_imbalance=float(arr[2]),
            trade_intensity=float(arr[3]),
            spread_change=float(arr[4]),
            spread_level=float(arr[5]),
            queue_pressure=float(arr[6]),
            price_velocity=float(arr[7]),
            volume_per_price=float(arr[8]),
            time_since_last_spike=float(arr[9]),
            tick_entropy=float(arr[10]),
            vpin=float(arr[11]),
        )


@dataclass
class HarvestEvent:
    """被收割事件"""
    entry_price: float
    current_price: float
    entry_time: float
    current_time: float
    adverse_move: float
    duration: float
    is_harvested: bool
    confidence: float  # 置信度 [0, 1]
    features: TrapFeatures


@dataclass
class ModelSnapshot:
    """模型版本快照"""
    model_weights: object
    performance: float  # 检测准确率
    timestamp: float
