"""
策略基类 - 所有交易策略的基础

与 brain_py.agent_registry.BaseAgent 兼容
支持热插拔和动态注册
"""

import sys
sys.path.insert(0, 'D:/binance/new')

from abc import abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum, auto
import numpy as np
import pandas as pd
import time

from brain_py.agent_registry import BaseAgent


class SignalType(Enum):
    """信号类型"""
    BUY = 1
    SELL = -1
    HOLD = 0


@dataclass
class Signal:
    """交易信号"""
    type: SignalType
    confidence: float  # 0-1
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class StrategyMetadata:
    """策略元数据"""
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    tags: List[str] = field(default_factory=list)
    suitable_regimes: List[str] = field(default_factory=list)  # 适合的市场状态
    params: Dict[str, Any] = field(default_factory=dict)


class StrategyBase(BaseAgent):
    """
    策略基类

    兼容 brain_py.agent_registry.BaseAgent 接口
    支持热插拔和动态注册
    """

    # 类级别的元数据定义（子类可覆盖）
    METADATA: Optional[StrategyMetadata] = None

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化策略

        Args:
            config: 配置字典，包含策略参数
        """
        # 调用 BaseAgent 的 __init__
        super().__init__(config)

        self.config = config or {}
        self._initialized = False
        self._metadata = self._build_metadata()

        # 运行时状态
        self.position = 0  # 当前持仓方向: -1, 0, 1
        self.last_signal: Optional[Signal] = None
        self.signal_history: List[Signal] = []

    def _build_metadata(self) -> StrategyMetadata:
        """构建元数据"""
        if self.METADATA:
            # 使用类定义的元数据，但允许配置覆盖参数
            params = {**self.METADATA.params, **self.config.get('params', {})}
            return StrategyMetadata(
                name=self.METADATA.name,
                version=self.METADATA.version,
                description=self.METADATA.description,
                author=self.METADATA.author,
                tags=self.METADATA.tags.copy(),
                suitable_regimes=self.METADATA.suitable_regimes.copy(),
                params=params
            )

        # 默认元数据
        return StrategyMetadata(
            name=self.__class__.__name__,
            description=f"Strategy: {self.__class__.__name__}",
            params=self.config.get('params', {})
        )

    # ============ 抽象方法（子类必须实现） ============

    @abstractmethod
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """
        生成交易信号

        Args:
            data: K线数据 DataFrame，包含 columns:
                - open, high, low, close, volume
                - 可能包含其他技术指标

        Returns:
            Signal: 交易信号
        """
        pass

    # ============ brain_py.BaseAgent 兼容接口 ============

    def initialize(self) -> bool:
        """初始化策略（brain_py.BaseAgent 接口）"""
        try:
            self.on_init()
            self._initialized = True
            return True
        except Exception as e:
            print(f"[Strategy:{self._metadata.name}] Initialization failed: {e}")
            return False

    def predict(self, state: Any) -> Dict[str, Any]:
        """
        预测/执行（brain_py.BaseAgent 接口）

        Args:
            state: 可以是 numpy 数组或 DataFrame

        Returns:
            dict: 包含 action 的字典
        """
        # 转换 state 为 DataFrame
        if isinstance(state, np.ndarray):
            # 如果是数组，创建简单的 DataFrame
            df = self._array_to_dataframe(state)
        elif isinstance(state, pd.DataFrame):
            df = state
        else:
            # 默认返回 HOLD
            return {'direction': 0, 'confidence': 0}

        signal = self.generate_signal(df)
        self.last_signal = signal
        self.signal_history.append(signal)

        # 限制历史长度
        if len(self.signal_history) > 1000:
            self.signal_history = self.signal_history[-1000:]

        return {
            'direction': signal.type.value,
            'confidence': signal.confidence,
            'metadata': signal.metadata
        }

    def execute(self, state: Any) -> Dict[str, Any]:
        """执行（brain_py.BaseAgent 接口，同 predict）"""
        return self.predict(state)

    def shutdown(self) -> None:
        """关闭策略（brain_py.BaseAgent 接口）"""
        self.on_stop()
        self._initialized = False

    def health_check(self) -> bool:
        """健康检查（brain_py.BaseAgent 接口）"""
        return self._initialized

    def get_metadata(self) -> StrategyMetadata:
        """获取元数据（brain_py.BaseAgent 接口）"""
        return self._metadata

    def set_metadata(self, metadata: Any) -> None:
        """设置元数据（brain_py.BaseAgent 接口）

        支持 AgentMetadata 和 StrategyMetadata 两种类型
        """
        from brain_py.agent_registry import AgentMetadata
        if isinstance(metadata, AgentMetadata):
            # 转换 AgentMetadata 到 StrategyMetadata
            self._metadata = StrategyMetadata(
                name=metadata.name,
                version=metadata.version,
                description=metadata.description,
                author=metadata.author,
                params=metadata.config if metadata.config else {}
            )
        else:
            self._metadata = metadata

    def get_suitable_regimes(self) -> List[str]:
        """获取适合的市场状态列表"""
        if hasattr(self._metadata, 'suitable_regimes'):
            return self._metadata.suitable_regimes
        return []

    # ============ 生命周期钩子（子类可选覆盖） ============

    def on_init(self):
        """初始化钩子"""
        pass

    def on_stop(self):
        """停止钩子"""
        pass

    def on_market_regime_change(self, regime: str):
        """
        市场状态变化回调

        Args:
            regime: 新的市场状态
        """
        pass

    # ============ 工具方法 ============

    def _array_to_dataframe(self, arr: np.ndarray) -> pd.DataFrame:
        """将 numpy 数组转换为 DataFrame"""
        # 简化处理：假设数组包含价格信息
        if len(arr) >= 4:
            return pd.DataFrame({
                'close': arr[:, 0] if len(arr.shape) > 1 else arr
            })
        return pd.DataFrame({'close': [0]})

    def get_params(self) -> Dict[str, Any]:
        """获取策略参数"""
        if hasattr(self._metadata, 'params'):
            return self._metadata.params.copy()
        elif hasattr(self._metadata, 'config'):
            return self._metadata.config.copy() if self._metadata.config else {}
        return {}

    def set_params(self, params: Dict[str, Any]):
        """设置策略参数（支持热更新）"""
        self._metadata.params.update(params)
        self.on_params_changed(params)

    def on_params_changed(self, params: Dict[str, Any]):
        """参数变化钩子（子类可覆盖）"""
        pass

    def reset(self):
        """重置策略状态"""
        self.position = 0
        self.last_signal = None
        self.signal_history.clear()

    # ============ 统计信息 ============

    def get_stats(self) -> Dict[str, Any]:
        """获取策略统计信息"""
        if not self.signal_history:
            return {'total_signals': 0}

        buy_count = sum(1 for s in self.signal_history if s.type == SignalType.BUY)
        sell_count = sum(1 for s in self.signal_history if s.type == SignalType.SELL)
        hold_count = sum(1 for s in self.signal_history if s.type == SignalType.HOLD)

        return {
            'total_signals': len(self.signal_history),
            'buy_signals': buy_count,
            'sell_signals': sell_count,
            'hold_signals': hold_count,
            'avg_confidence': np.mean([s.confidence for s in self.signal_history])
        }
