"""
ATR策略 Agent
基于平均真实波幅(ATR)的波动率突破策略
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass

import sys
sys.path.insert(0, 'D:/binance/new')

from brain_py.agent_registry import BaseAgent, AgentMetadata, StrategyPriority


@dataclass
class ATRConfig:
    """ATR策略配置"""
    period: int = 14          # ATR计算周期
    multiplier: float = 2.0   # 通道倍数
    trend_threshold: float = 0.02  # 趋势确认阈值(2%)


class ATRAgent(BaseAgent):
    """
    ATR波动率突破策略

    核心逻辑：
    - ATR扩大 + 价格突破 → 趋势确认信号
    - ATR收缩 → 低波动观望
    - 基于ATR的止损/止盈位置

    适用市场：高波动市场，趋势启动阶段
    """

    METADATA = AgentMetadata(
        name="atr",
        version="1.0.0",
        description="ATR波动率突破策略",
        author="System",
        priority=StrategyPriority.NORMAL,
        tags=["volatility", "trend", "breakout", "atr"],
        config={
            "period": 14,
            "multiplier": 2.0,
            "trend_threshold": 0.02
        }
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.atr_config = ATRConfig(**self.config)
        self.signal_history: List[Dict] = []
        self.atr_history: List[float] = []

    def initialize(self) -> bool:
        """初始化策略"""
        try:
            if self.atr_config.period < 2:
                raise ValueError("period must be at least 2")
            if self.atr_config.multiplier <= 0:
                raise ValueError("multiplier must be positive")

            self._initialized = True
            return True
        except Exception as e:
            print(f"[ATRAgent] Initialization failed: {e}")
            return False

    def predict(self, state: Any) -> Dict[str, Any]:
        """
        执行预测

        Returns:
            {
                'direction': 1 (BUY), -1 (SELL), 0 (HOLD)
                'confidence': 置信度 0.0-1.0
                'metadata': {
                    'atr': ATR值,
                    'upper_channel': 上轨,
                    'lower_channel': 下轨,
                    'atr_ratio': ATR比率,
                    'signal_type': 信号类型
                }
            }
        """
        if not self._initialized:
            return {'direction': 0, 'confidence': 0.0, 'metadata': {'error': 'Not initialized'}}

        # 解析输入数据
        highs, lows, closes = self._parse_ohlc(state)
        if not closes or len(closes) < self.atr_config.period + 1:
            return {'direction': 0, 'confidence': 0.0, 'metadata': {'error': 'Insufficient data'}}

        # 计算ATR
        atr = self._calculate_atr(highs, lows, closes)
        if atr is None:
            return {'direction': 0, 'confidence': 0.0, 'metadata': {'error': 'ATR calculation failed'}}

        current_price = closes[-1]
        prev_price = closes[-2] if len(closes) > 1 else current_price

        # 计算ATR通道
        middle = np.mean(closes[-self.atr_config.period:])
        upper_channel = middle + atr * self.atr_config.multiplier
        lower_channel = middle - atr * self.atr_config.multiplier

        # 计算ATR比率（当前ATR相对于历史ATR）
        self.atr_history.append(atr)
        if len(self.atr_history) > 50:
            self.atr_history = self.atr_history[-50:]

        atr_ratio = atr / np.mean(self.atr_history) if self.atr_history else 1.0

        # 价格变化率
        price_change = (current_price - prev_price) / prev_price if prev_price > 0 else 0

        # 判断信号
        direction = 0
        confidence = 0.0
        signal_type = 'HOLD'

        # 突破上轨 + ATR扩大 + 上涨趋势
        if current_price > upper_channel and atr_ratio > 1.2 and price_change > self.atr_config.trend_threshold:
            direction = 1
            signal_type = 'BUY_VOLATILITY_BREAKOUT'
            confidence = min(0.9, atr_ratio - 0.2 + abs(price_change) * 10)

        # 突破下轨 + ATR扩大 + 下跌趋势
        elif current_price < lower_channel and atr_ratio > 1.2 and price_change < -self.atr_config.trend_threshold:
            direction = -1
            signal_type = 'SELL_VOLATILITY_BREAKOUT'
            confidence = min(0.9, atr_ratio - 0.2 + abs(price_change) * 10)

        # ATR收缩（观望）
        elif atr_ratio < 0.8:
            signal_type = 'LOW_VOLATILITY_HOLD'
            confidence = 0.1

        # 价格在通道内但接近边界（预警）
        elif current_price > middle + atr and price_change > 0:
            direction = 0.5  # 弱买入信号
            signal_type = 'BUY_NEAR_CHANNEL'
            confidence = 0.3

        elif current_price < middle - atr and price_change < 0:
            direction = -0.5  # 弱卖出信号
            signal_type = 'SELL_NEAR_CHANNEL'
            confidence = 0.3

        # 构建结果
        result = {
            'direction': direction,
            'confidence': confidence,
            'metadata': {
                'atr': float(atr),
                'middle': float(middle),
                'upper_channel': float(upper_channel),
                'lower_channel': float(lower_channel),
                'current_price': float(current_price),
                'atr_ratio': float(atr_ratio),
                'price_change': float(price_change),
                'signal_type': signal_type,
                'period': self.atr_config.period,
                'multiplier': self.atr_config.multiplier
            }
        }

        # 记录信号历史
        self.signal_history.append({
            'timestamp': pd.Timestamp.now().isoformat(),
            'direction': direction,
            'confidence': confidence,
            'atr': atr,
            'price': current_price,
            'atr_ratio': atr_ratio
        })

        # 限制历史长度
        if len(self.signal_history) > 1000:
            self.signal_history = self.signal_history[-1000:]

        return result

    def _calculate_atr(self, highs: List[float], lows: List[float], closes: List[float]) -> Optional[float]:
        """计算ATR指标"""
        try:
            period = self.atr_config.period
            if len(closes) < period + 1:
                return None

            tr_values = []
            for i in range(1, len(closes)):
                high = highs[i]
                low = lows[i]
                prev_close = closes[i - 1]

                # True Range = max(high-low, |high-prev_close|, |low-prev_close|)
                tr1 = high - low
                tr2 = abs(high - prev_close)
                tr3 = abs(low - prev_close)
                tr = max(tr1, tr2, tr3)
                tr_values.append(tr)

            if len(tr_values) < period:
                return None

            # 计算ATR（TR的简单移动平均）
            atr = np.mean(tr_values[-period:])
            return atr

        except Exception as e:
            print(f"[ATRAgent] ATR calculation error: {e}")
            return None

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
                if len(state.shape) == 2 and state.shape[1] >= 4:
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
            print(f"[ATRAgent] Error parsing OHLC: {e}")

        return None, None, None

    def shutdown(self) -> None:
        """关闭策略"""
        self._initialized = False
        self.signal_history.clear()
        self.atr_history.clear()
        print("[ATRAgent] Shutdown complete")

    def get_signal_stats(self) -> Dict[str, Any]:
        """获取信号统计"""
        if not self.signal_history:
            return {'total_signals': 0}

        buy_signals = sum(1 for s in self.signal_history if s['direction'] > 0)
        sell_signals = sum(1 for s in self.signal_history if s['direction'] < 0)
        hold_signals = sum(1 for s in self.signal_history if s['direction'] == 0)

        return {
            'total_signals': len(self.signal_history),
            'buy_signals': buy_signals,
            'sell_signals': sell_signals,
            'hold_signals': hold_signals,
            'avg_confidence': np.mean([s['confidence'] for s in self.signal_history]),
            'avg_atr_ratio': np.mean([s['atr_ratio'] for s in self.signal_history])
        }


# 兼容性别名
ATRStrategy = ATRAgent
