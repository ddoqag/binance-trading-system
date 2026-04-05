"""
移动平均线策略 Agent
基于双均线交叉的趋势跟踪策略
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

import sys
sys.path.insert(0, 'D:/binance/new')

from brain_py.agent_registry import BaseAgent, AgentMetadata, StrategyPriority


@dataclass
class MAConfig:
    """移动平均线策略配置"""
    fast_period: int = 5
    slow_period: int = 20
    signal_threshold: float = 0.001  # 金叉/死叉判断阈值


class MovingAverageAgent(BaseAgent):
    """
    双均线交叉策略

    核心逻辑：
    - 快线（短期）上穿慢线（长期）→ 买入信号（金叉）
    - 快线下穿慢线 → 卖出信号（死叉）

    适用市场：趋势明显的市场
    """

    METADATA = AgentMetadata(
        name="moving_average",
        version="1.0.0",
        description="双均线交叉趋势跟踪策略",
        author="System",
        priority=StrategyPriority.NORMAL,
        tags=["trend", "ma", "technical"],
        config={
            "fast_period": 5,
            "slow_period": 20,
            "signal_threshold": 0.001
        }
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.ma_config = MAConfig(**self.config)
        self.price_history: List[float] = []
        self.signal_history: List[Dict] = []

    def initialize(self) -> bool:
        """初始化策略"""
        try:
            # 验证配置
            if self.ma_config.fast_period >= self.ma_config.slow_period:
                raise ValueError("fast_period must be less than slow_period")
            if self.ma_config.fast_period < 1:
                raise ValueError("fast_period must be positive")

            self._initialized = True
            return True
        except Exception as e:
            print(f"[MovingAverageAgent] Initialization failed: {e}")
            return False

    def predict(self, state: Any) -> Dict[str, Any]:
        """
        执行预测

        Args:
            state: 可以是numpy数组、DataFrame或字典

        Returns:
            {
                'direction': 1 (BUY), -1 (SELL), 0 (HOLD)
                'confidence': 置信度 0.0-1.0
                'metadata': {
                    'fast_ma': 快线值,
                    'slow_ma': 慢线值,
                    'signal': 信号类型,
                    'ma_ratio': 均线比率
                }
            }
        """
        if not self._initialized:
            return {'direction': 0, 'confidence': 0.0, 'metadata': {'error': 'Not initialized'}}

        # 解析输入数据
        prices = self._parse_state(state)
        if not prices or len(prices) < self.ma_config.slow_period:
            return {'direction': 0, 'confidence': 0.0, 'metadata': {'error': 'Insufficient data'}}

        # 计算移动平均线
        fast_ma = np.mean(prices[-self.ma_config.fast_period:])
        slow_ma = np.mean(prices[-self.ma_config.slow_period:])

        # 判断信号
        direction = 0
        confidence = 0.0
        signal_type = 'HOLD'

        if fast_ma > slow_ma * (1 + self.ma_config.signal_threshold):
            # 金叉买入信号
            direction = 1
            signal_type = 'BUY'
            # 计算交叉强度（偏离程度）
            ma_ratio = fast_ma / slow_ma - 1
            confidence = min(0.9, ma_ratio * 100)  # 偏离越大，置信度越高

        elif fast_ma < slow_ma * (1 - self.ma_config.signal_threshold):
            # 死叉卖出信号
            direction = -1
            signal_type = 'SELL'
            ma_ratio = 1 - fast_ma / slow_ma
            confidence = min(0.9, ma_ratio * 100)

        # 构建结果
        result = {
            'direction': direction,
            'confidence': confidence,
            'metadata': {
                'fast_ma': float(fast_ma),
                'slow_ma': float(slow_ma),
                'signal': signal_type,
                'ma_ratio': float(fast_ma / slow_ma - 1),
                'fast_period': self.ma_config.fast_period,
                'slow_period': self.ma_config.slow_period
            }
        }

        # 记录信号历史
        self.signal_history.append({
            'timestamp': pd.Timestamp.now().isoformat(),
            'direction': direction,
            'confidence': confidence,
            'fast_ma': fast_ma,
            'slow_ma': slow_ma
        })

        # 限制历史长度
        if len(self.signal_history) > 1000:
            self.signal_history = self.signal_history[-1000:]

        return result

    def _parse_state(self, state: Any) -> Optional[List[float]]:
        """解析输入状态为价格列表"""
        try:
            if isinstance(state, np.ndarray):
                # 假设是一维价格数组
                return state.tolist() if len(state.shape) == 1 else state[:, 0].tolist()

            elif isinstance(state, pd.DataFrame):
                # 尝试获取close列
                if 'close' in state.columns:
                    return state['close'].tolist()
                elif 'price' in state.columns:
                    return state['price'].tolist()
                else:
                    # 使用第一列
                    return state.iloc[:, 0].tolist()

            elif isinstance(state, dict):
                # 尝试从字典获取价格
                if 'close' in state:
                    return state['close'] if isinstance(state['close'], list) else [state['close']]
                elif 'prices' in state:
                    return state['prices']
                elif 'data' in state:
                    return self._parse_state(state['data'])

            elif isinstance(state, list):
                return state

        except Exception as e:
            print(f"[MovingAverageAgent] Error parsing state: {e}")

        return None

    def shutdown(self) -> None:
        """关闭策略"""
        self._initialized = False
        self.price_history.clear()
        print("[MovingAverageAgent] Shutdown complete")

    def get_signal_stats(self) -> Dict[str, Any]:
        """获取信号统计"""
        if not self.signal_history:
            return {'total_signals': 0}

        buy_signals = sum(1 for s in self.signal_history if s['direction'] == 1)
        sell_signals = sum(1 for s in self.signal_history if s['direction'] == -1)
        hold_signals = sum(1 for s in self.signal_history if s['direction'] == 0)

        return {
            'total_signals': len(self.signal_history),
            'buy_signals': buy_signals,
            'sell_signals': sell_signals,
            'hold_signals': hold_signals,
            'avg_confidence': np.mean([s['confidence'] for s in self.signal_history])
        }


# 兼容性别名
MovingAverageStrategy = MovingAverageAgent
