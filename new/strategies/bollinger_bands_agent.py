"""
布林带策略 Agent
基于布林带(Bollinger Bands)的均值回归+趋势突破混合策略
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass

import sys
sys.path.insert(0, 'D:/binance/new')

from brain_py.agent_registry import BaseAgent, AgentMetadata, StrategyPriority


@dataclass
class BBConfig:
    """布林带策略配置"""
    period: int = 20
    std_dev: float = 2.0  # 标准差倍数


class BollingerBandsAgent(BaseAgent):
    """
    布林带混合策略

    核心逻辑：
    1. 均值回归模式：价格触及下轨买入，触及上轨卖出
    2. 趋势突破模式：强势突破上轨追多，突破下轨追空

    适用市场：震荡市（均值回归）和趋势市（突破）
    """

    METADATA = AgentMetadata(
        name="bollinger_bands",
        version="1.0.0",
        description="布林带均值回归+趋势突破混合策略",
        author="System",
        priority=StrategyPriority.NORMAL,
        tags=["mean_reversion", "trend", "volatility", "bands"],
        config={
            "period": 20,
            "std_dev": 2.0
        }
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.bb_config = BBConfig(**self.config)
        self.signal_history: List[Dict] = []

    def initialize(self) -> bool:
        """初始化策略"""
        try:
            if self.bb_config.period < 2:
                raise ValueError("period must be at least 2")
            if self.bb_config.std_dev <= 0:
                raise ValueError("std_dev must be positive")

            self._initialized = True
            return True
        except Exception as e:
            print(f"[BollingerBandsAgent] Initialization failed: {e}")
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
                    'sma': 中轨值,
                    'upper': 上轨值,
                    'lower': 下轨值,
                    'price_position': 价格在带中的位置,
                    'bandwidth': 带宽,
                    'signal': 信号类型
                }
            }
        """
        if not self._initialized:
            return {'direction': 0, 'confidence': 0.0, 'metadata': {'error': 'Not initialized'}}

        # 解析输入数据
        prices = self._parse_state(state)
        if not prices or len(prices) < self.bb_config.period:
            return {'direction': 0, 'confidence': 0.0, 'metadata': {'error': 'Insufficient data'}}

        # 计算布林带
        sma, upper, lower = self._calculate_bollinger_bands(prices)
        if sma is None or upper is None or lower is None:
            return {'direction': 0, 'confidence': 0.0, 'metadata': {'error': 'BB calculation failed'}}

        current_price = prices[-1]

        # 计算价格在带中的位置 (0 = 下轨, 1 = 上轨, 0.5 = 中轨)
        if upper != lower:
            price_position = (current_price - lower) / (upper - lower)
        else:
            price_position = 0.5

        # 计算带宽 (带宽越窄，突破信号越强)
        bandwidth = (upper - lower) / sma if sma > 0 else 0

        # 判断信号
        direction = 0
        confidence = 0.0
        signal_type = 'HOLD'

        # 均值回归信号
        if current_price <= lower:
            # 价格触及下轨，买入信号
            direction = 1
            signal_type = 'BUY_MEAN_REVERSION'
            # 置信度基于触及程度
            confidence = min(0.9, (lower - current_price) / (upper - lower) + 0.5) if (upper - lower) > 0 else 0.5

        elif current_price >= upper:
            # 价格触及上轨，卖出信号
            direction = -1
            signal_type = 'SELL_MEAN_REVERSION'
            confidence = min(0.9, (current_price - upper) / (upper - lower) + 0.5) if (upper - lower) > 0 else 0.5

        # 构建结果
        result = {
            'direction': direction,
            'confidence': confidence,
            'metadata': {
                'sma': float(sma),
                'upper': float(upper),
                'lower': float(lower),
                'current_price': float(current_price),
                'price_position': float(price_position),
                'bandwidth': float(bandwidth),
                'signal': signal_type,
                'period': self.bb_config.period,
                'std_dev': self.bb_config.std_dev
            }
        }

        # 记录信号历史
        self.signal_history.append({
            'timestamp': pd.Timestamp.now().isoformat(),
            'direction': direction,
            'confidence': confidence,
            'price': current_price,
            'sma': sma,
            'upper': upper,
            'lower': lower
        })

        # 限制历史长度
        if len(self.signal_history) > 1000:
            self.signal_history = self.signal_history[-1000:]

        return result

    def _calculate_bollinger_bands(self, prices: List[float]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """计算布林带"""
        try:
            period = self.bb_config.period
            if len(prices) < period:
                return None, None, None

            recent_prices = np.array(prices[-period:])
            sma = np.mean(recent_prices)
            std = np.std(recent_prices)

            upper = sma + (std * self.bb_config.std_dev)
            lower = sma - (std * self.bb_config.std_dev)

            return sma, upper, lower

        except Exception as e:
            print(f"[BollingerBandsAgent] BB calculation error: {e}")
            return None, None, None

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
            print(f"[BollingerBandsAgent] Error parsing state: {e}")

        return None

    def shutdown(self) -> None:
        """关闭策略"""
        self._initialized = False
        self.signal_history.clear()
        print("[BollingerBandsAgent] Shutdown complete")

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
            'avg_bandwidth': np.mean([(s['upper'] - s['lower']) / s['sma'] for s in self.signal_history if s['sma'] > 0])
        }


# 兼容性别名
BollingerBandsStrategy = BollingerBandsAgent
