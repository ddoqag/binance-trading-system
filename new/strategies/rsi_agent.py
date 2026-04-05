"""
RSI策略 Agent
基于相对强弱指数(RSI)的均值回归策略
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

import sys
sys.path.insert(0, 'D:/binance/new')

from brain_py.agent_registry import BaseAgent, AgentMetadata, StrategyPriority


@dataclass
class RSIConfig:
    """RSI策略配置"""
    period: int = 14
    overbought: float = 70.0  # 超买阈值
    oversold: float = 30.0    # 超卖阈值


class RSIAgent(BaseAgent):
    """
    RSI均值回归策略

    核心逻辑：
    - RSI < oversold (30) → 超卖，买入信号
    - RSI > overbought (70) → 超买，卖出信号
    - 中间区域 → 观望

    适用市场：震荡市场，价格有回归均值的特性
    """

    METADATA = AgentMetadata(
        name="rsi",
        version="1.0.0",
        description="RSI均值回归策略",
        author="System",
        priority=StrategyPriority.NORMAL,
        tags=["mean_reversion", "rsi", "oscillator"],
        config={
            "period": 14,
            "overbought": 70.0,
            "oversold": 30.0
        }
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.rsi_config = RSIConfig(**self.config)
        self.signal_history: List[Dict] = []

    def initialize(self) -> bool:
        """初始化策略"""
        try:
            # 验证配置
            if self.rsi_config.period < 2:
                raise ValueError("period must be at least 2")
            if not (0 < self.rsi_config.oversold < self.rsi_config.overbought < 100):
                raise ValueError("Invalid overbought/oversold thresholds")

            self._initialized = True
            return True
        except Exception as e:
            print(f"[RSIAgent] Initialization failed: {e}")
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
                    'rsi': RSI值,
                    'signal': 信号类型,
                    'oversold_level': 超卖程度,
                    'overbought_level': 超买程度
                }
            }
        """
        if not self._initialized:
            return {'direction': 0, 'confidence': 0.0, 'metadata': {'error': 'Not initialized'}}

        # 解析输入数据
        prices = self._parse_state(state)
        if not prices or len(prices) < self.rsi_config.period + 1:
            return {'direction': 0, 'confidence': 0.0, 'metadata': {'error': 'Insufficient data'}}

        # 计算RSI
        rsi = self._calculate_rsi(prices)
        if rsi is None:
            return {'direction': 0, 'confidence': 0.0, 'metadata': {'error': 'RSI calculation failed'}}

        # 判断信号
        direction = 0
        confidence = 0.0
        signal_type = 'HOLD'

        if rsi < self.rsi_config.oversold:
            # 超卖，买入信号
            direction = 1
            signal_type = 'BUY'
            # 计算超卖程度（越接近0，置信度越高）
            oversold_level = (self.rsi_config.oversold - rsi) / self.rsi_config.oversold
            confidence = min(0.9, oversold_level)

        elif rsi > self.rsi_config.overbought:
            # 超买，卖出信号
            direction = -1
            signal_type = 'SELL'
            # 计算超买程度（越接近100，置信度越高）
            overbought_level = (rsi - self.rsi_config.overbought) / (100 - self.rsi_config.overbought)
            confidence = min(0.9, overbought_level)

        # 构建结果
        result = {
            'direction': direction,
            'confidence': confidence,
            'metadata': {
                'rsi': float(rsi),
                'signal': signal_type,
                'period': self.rsi_config.period,
                'oversold_threshold': self.rsi_config.oversold,
                'overbought_threshold': self.rsi_config.overbought,
                'distance_from_mid': abs(rsi - 50) / 50  # 距离中线的程度
            }
        }

        # 记录信号历史
        self.signal_history.append({
            'timestamp': pd.Timestamp.now().isoformat(),
            'direction': direction,
            'confidence': confidence,
            'rsi': rsi
        })

        # 限制历史长度
        if len(self.signal_history) > 1000:
            self.signal_history = self.signal_history[-1000:]

        return result

    def _calculate_rsi(self, prices: List[float]) -> Optional[float]:
        """计算RSI指标"""
        try:
            deltas = np.diff(prices)
            period = self.rsi_config.period

            if len(deltas) < period:
                return None

            # 计算初始平均涨跌
            seed = deltas[:period]
            up = np.mean(seed[seed >= 0]) if np.any(seed >= 0) else 0
            down = -np.mean(seed[seed < 0]) if np.any(seed < 0) else 0

            if down == 0:
                return 100.0

            rs = up / down
            rsi = 100 - (100 / (1 + rs))

            # 使用平滑RSI计算
            for i in range(period, len(deltas)):
                delta = deltas[i]

                if delta > 0:
                    upval = delta
                    downval = 0
                else:
                    upval = 0
                    downval = -delta

                up = (up * (period - 1) + upval) / period
                down = (down * (period - 1) + downval) / period

                if down == 0:
                    rsi = 100.0
                else:
                    rs = up / down
                    rsi = 100 - (100 / (1 + rs))

            return rsi

        except Exception as e:
            print(f"[RSIAgent] RSI calculation error: {e}")
            return None

    def _parse_state(self, state: Any) -> Optional[List[float]]:
        """解析输入状态为价格列表"""
        try:
            if isinstance(state, np.ndarray):
                return state.tolist() if len(state.shape) == 1 else state[:, 0].tolist()

            elif isinstance(state, pd.DataFrame):
                if 'close' in state.columns:
                    return state['close'].tolist()
                elif 'price' in state.columns:
                    return state['price'].tolist()
                else:
                    return state.iloc[:, 0].tolist()

            elif isinstance(state, dict):
                if 'close' in state:
                    return state['close'] if isinstance(state['close'], list) else [state['close']]
                elif 'prices' in state:
                    return state['prices']
                elif 'data' in state:
                    return self._parse_state(state['data'])

            elif isinstance(state, list):
                return state

        except Exception as e:
            print(f"[RSIAgent] Error parsing state: {e}")

        return None

    def shutdown(self) -> None:
        """关闭策略"""
        self._initialized = False
        self.signal_history.clear()
        print("[RSIAgent] Shutdown complete")

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
            'avg_rsi': np.mean([s['rsi'] for s in self.signal_history])
        }


# 兼容性别名
RSIStrategy = RSIAgent
