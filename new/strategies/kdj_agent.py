"""
KDJ策略 Agent
基于随机指标(KDJ)的震荡策略
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass

import sys
sys.path.insert(0, 'D:/binance/new')

from brain_py.agent_registry import BaseAgent, AgentMetadata, StrategyPriority


@dataclass
class KDJConfig:
    """KDJ策略配置"""
    n_period: int = 9   # RSV计算周期
    m1: int = 3         # K值平滑周期
    m2: int = 3         # D值平滑周期


class KDJAgent(BaseAgent):
    """
    KDJ随机指标策略

    核心逻辑：
    - K线上穿D线（金叉）且J值较低 → 买入信号
    - K线下穿D线（死叉）且J值较高 → 卖出信号
    - J值 > 100 超买区域，J值 < 0 超卖区域

    适用市场：震荡市场，价格有回归均值的特性
    """

    METADATA = AgentMetadata(
        name="kdj",
        version="1.0.0",
        description="KDJ随机指标震荡策略",
        author="System",
        priority=StrategyPriority.NORMAL,
        tags=["mean_reversion", "oscillator", "stochastic"],
        config={
            "n_period": 9,
            "m1": 3,
            "m2": 3
        }
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.kdj_config = KDJConfig(**self.config)
        self.signal_history: List[Dict] = []
        self.k_history: List[float] = []
        self.d_history: List[float] = []

    def initialize(self) -> bool:
        """初始化策略"""
        try:
            if self.kdj_config.n_period < 2:
                raise ValueError("n_period must be at least 2")
            if self.kdj_config.m1 < 1 or self.kdj_config.m2 < 1:
                raise ValueError("m1 and m2 must be positive")

            self._initialized = True
            return True
        except Exception as e:
            print(f"[KDJAgent] Initialization failed: {e}")
            return False

    def predict(self, state: Any) -> Dict[str, Any]:
        """
        执行预测

        Returns:
            {
                'direction': 1 (BUY), -1 (SELL), 0 (HOLD)
                'confidence': 置信度 0.0-1.0
                'metadata': {
                    'k': K值,
                    'd': D值,
                    'j': J值,
                    'signal_type': 信号类型
                }
            }
        """
        if not self._initialized:
            return {'direction': 0, 'confidence': 0.0, 'metadata': {'error': 'Not initialized'}}

        # 解析输入数据
        highs, lows, closes = self._parse_ohlc(state)
        min_periods = self.kdj_config.n_period + max(self.kdj_config.m1, self.kdj_config.m2)

        if not closes or len(closes) < min_periods:
            return {'direction': 0, 'confidence': 0.0, 'metadata': {'error': f'Insufficient data (need {min_periods})'}}

        # 计算KDJ
        k, d, j = self._calculate_kdj(highs, lows, closes)
        if k is None or d is None or j is None:
            return {'direction': 0, 'confidence': 0.0, 'metadata': {'error': 'KDJ calculation failed'}}

        # 判断信号（需要历史值来判断交叉）
        direction = 0
        confidence = 0.0
        signal_type = 'HOLD'

        if len(self.k_history) > 0 and len(self.d_history) > 0:
            prev_k = self.k_history[-1]
            prev_d = self.d_history[-1]

            # 金叉：K从下方上穿D
            if prev_k <= prev_d and k > d:
                if j < 50:  # J值在低位，买入信号更强
                    direction = 1
                    signal_type = 'BUY_GOLDEN_CROSS'
                    confidence = min(0.9, (50 - j) / 50 + 0.3)
                else:
                    direction = 1
                    signal_type = 'BUY_WEAK_CROSS'
                    confidence = 0.4

            # 死叉：K从上方下穿D
            elif prev_k >= prev_d and k < d:
                if j > 50:  # J值在高位，卖出信号更强
                    direction = -1
                    signal_type = 'SELL_DEATH_CROSS'
                    confidence = min(0.9, (j - 50) / 50 + 0.3)
                else:
                    direction = -1
                    signal_type = 'SELL_WEAK_CROSS'
                    confidence = 0.4

            # 极端区域信号
            elif j < 0 and prev_k > prev_d:
                # J值超卖区域，且K>D，强买入
                direction = 1
                signal_type = 'BUY_OVERSOLD'
                confidence = min(0.9, abs(j) / 20 + 0.5)

            elif j > 100 and prev_k < prev_d:
                # J值超买区域，且K<D，强卖出
                direction = -1
                signal_type = 'SELL_OVERBOUGHT'
                confidence = min(0.9, (j - 100) / 20 + 0.5)

        # 更新历史
        self.k_history.append(k)
        self.d_history.append(d)
        if len(self.k_history) > 100:
            self.k_history = self.k_history[-100:]
            self.d_history = self.d_history[-100:]

        # 构建结果
        result = {
            'direction': direction,
            'confidence': confidence,
            'metadata': {
                'k': float(k),
                'd': float(d),
                'j': float(j),
                'signal_type': signal_type,
                'n_period': self.kdj_config.n_period,
                'm1': self.kdj_config.m1,
                'm2': self.kdj_config.m2
            }
        }

        # 记录信号历史
        self.signal_history.append({
            'timestamp': pd.Timestamp.now().isoformat(),
            'direction': direction,
            'confidence': confidence,
            'k': k,
            'd': d,
            'j': j
        })

        # 限制历史长度
        if len(self.signal_history) > 1000:
            self.signal_history = self.signal_history[-1000:]

        return result

    def _calculate_kdj(self, highs: List[float], lows: List[float], closes: List[float]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """计算KDJ指标"""
        try:
            n = self.kdj_config.n_period
            m1 = self.kdj_config.m1
            m2 = self.kdj_config.m2

            if len(closes) < n + max(m1, m2):
                return None, None, None

            # 计算RSV
            rsv_values = []
            for i in range(n - 1, len(closes)):
                high_n = max(highs[i - n + 1:i + 1])
                low_n = min(lows[i - n + 1:i + 1])
                close = closes[i]

                if high_n == low_n:
                    rsv = 50.0
                else:
                    rsv = 100 * (close - low_n) / (high_n - low_n)
                rsv_values.append(rsv)

            if len(rsv_values) < max(m1, m2):
                return None, None, None

            # 计算K值（RSV的m1日EMA）
            k = self._calculate_kd_smooth(rsv_values, m1, 50.0)

            # 计算D值（K的m2日EMA）
            # 需要K值的历史
            k_values = []
            for i in range(m1 - 1, len(rsv_values)):
                k_val = self._calculate_kd_smooth(rsv_values[:i + 1], m1, 50.0)
                k_values.append(k_val)

            d = self._calculate_kd_smooth(k_values, m2, 50.0)

            # 计算J值 = 3K - 2D
            j = 3 * k - 2 * d

            return k, d, j

        except Exception as e:
            print(f"[KDJAgent] KDJ calculation error: {e}")
            return None, None, None

    def _calculate_kd_smooth(self, values: List[float], period: int, initial: float) -> float:
        """计算K或D的平滑值"""
        if not values:
            return initial

        result = initial
        for value in values:
            result = (result * (period - 1) + value) / period
        return result

    def _parse_ohlc(self, state: Any) -> Tuple[Optional[List[float]], Optional[List[float]], Optional[List[float]]]:
        """解析OHLC数据"""
        try:
            if isinstance(state, pd.DataFrame):
                highs = state['high'].tolist() if 'high' in state.columns else None
                lows = state['low'].tolist() if 'low' in state.columns else None
                closes = state['close'].tolist() if 'close' in state.columns else None

                if closes is None and len(state.columns) > 0:
                    closes = state.iloc[:, 0].tolist()
                if highs is None:
                    highs = closes
                if lows is None:
                    lows = closes

                return highs, lows, closes

            elif isinstance(state, dict):
                if 'high' in state and 'low' in state and 'close' in state:
                    highs = state['high'] if isinstance(state['high'], list) else [state['high']]
                    lows = state['low'] if isinstance(state['low'], list) else [state['low']]
                    closes = state['close'] if isinstance(state['close'], list) else [state['close']]
                    return highs, lows, closes
                elif 'prices' in state:
                    prices = state['prices']
                    return prices, prices, prices

            elif isinstance(state, np.ndarray):
                if len(state.shape) == 2 and state.shape[1] >= 3:
                    return state[:, 1].tolist(), state[:, 2].tolist(), state[:, 3].tolist()
                else:
                    prices = state.tolist() if len(state.shape) == 1 else state[:, 0].tolist()
                    return prices, prices, prices

            elif isinstance(state, list):
                if state and isinstance(state[0], dict):
                    highs = [s.get('high', s.get('close', 0)) for s in state]
                    lows = [s.get('low', s.get('close', 0)) for s in state]
                    closes = [s.get('close', 0) for s in state]
                    return highs, lows, closes
                else:
                    return state, state, state

        except Exception as e:
            print(f"[KDJAgent] Error parsing OHLC: {e}")

        return None, None, None

    def shutdown(self) -> None:
        """关闭策略"""
        self._initialized = False
        self.signal_history.clear()
        self.k_history.clear()
        self.d_history.clear()
        print("[KDJAgent] Shutdown complete")

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
            'avg_confidence': np.mean([s['confidence'] for s in self.signal_history]),
            'avg_j': np.mean([s['j'] for s in self.signal_history])
        }


# 兼容性别名
KDJStrategy = KDJAgent
