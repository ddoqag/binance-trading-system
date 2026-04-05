"""
MACD策略 Agent
基于指数平滑异同移动平均线(MACD)的趋势跟踪策略
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

import sys
sys.path.insert(0, 'D:/binance/new')

from brain_py.agent_registry import BaseAgent, AgentMetadata, StrategyPriority


@dataclass
class MACDConfig:
    """MACD策略配置"""
    fast_period: int = 12    # 快线周期
    slow_period: int = 26    # 慢线周期
    signal_period: int = 9   # 信号线周期


class MACDAgent(BaseAgent):
    """
    MACD趋势跟踪策略

    核心逻辑：
    - MACD线（DIF）上穿信号线（DEA）→ 买入信号（金叉）
    - MACD线下穿信号线 → 卖出信号（死叉）
    - 柱状图（Histogram）强度确认趋势

    适用市场：趋势明显的市场
    """

    METADATA = AgentMetadata(
        name="macd",
        version="1.0.0",
        description="MACD趋势跟踪策略",
        author="System",
        priority=StrategyPriority.NORMAL,
        tags=["trend", "macd", "momentum"],
        config={
            "fast_period": 12,
            "slow_period": 26,
            "signal_period": 9
        }
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.macd_config = MACDConfig(**self.config)
        self.signal_history: List[Dict] = []

    def initialize(self) -> bool:
        """初始化策略"""
        try:
            if self.macd_config.fast_period >= self.macd_config.slow_period:
                raise ValueError("fast_period must be less than slow_period")
            if self.macd_config.signal_period < 1:
                raise ValueError("signal_period must be positive")

            self._initialized = True
            return True
        except Exception as e:
            print(f"[MACDAgent] Initialization failed: {e}")
            return False

    def predict(self, state: Any) -> Dict[str, Any]:
        """
        执行预测

        Returns:
            {
                'direction': 1 (BUY), -1 (SELL), 0 (HOLD)
                'confidence': 置信度 0.0-1.0
                'metadata': {
                    'macd': MACD线值,
                    'signal': 信号线值,
                    'histogram': 柱状图值,
                    'signal_type': 信号类型
                }
            }
        """
        if not self._initialized:
            return {'direction': 0, 'confidence': 0.0, 'metadata': {'error': 'Not initialized'}}

        # 解析输入数据
        prices = self._parse_state(state)
        min_periods = self.macd_config.slow_period + self.macd_config.signal_period
        if not prices or len(prices) < min_periods:
            return {'direction': 0, 'confidence': 0.0, 'metadata': {'error': f'Insufficient data (need {min_periods})'}}

        # 计算MACD
        macd_line, signal_line, histogram = self._calculate_macd(prices)
        if macd_line is None or signal_line is None or histogram is None:
            return {'direction': 0, 'confidence': 0.0, 'metadata': {'error': 'MACD calculation failed'}}

        # 判断信号（需要至少2个点的历史来判断交叉）
        direction = 0
        confidence = 0.0
        signal_type = 'HOLD'

        # 计算前一点的MACD值来判断交叉
        if len(prices) >= min_periods + 1:
            prev_prices = prices[:-1]
            prev_macd, prev_signal, _ = self._calculate_macd(prev_prices)

            if prev_macd is not None and prev_signal is not None:
                # 金叉：MACD从下方上穿信号线
                if prev_macd <= prev_signal and macd_line > signal_line:
                    direction = 1
                    signal_type = 'BUY_GOLDEN_CROSS'
                    # 置信度基于柱状图强度
                    confidence = min(0.9, abs(histogram) / 10 + 0.3)

                # 死叉：MACD从上方下穿信号线
                elif prev_macd >= prev_signal and macd_line < signal_line:
                    direction = -1
                    signal_type = 'SELL_DEATH_CROSS'
                    confidence = min(0.9, abs(histogram) / 10 + 0.3)

                # 没有交叉，但MACD和信号线同向且柱状图扩大
                elif abs(histogram) > 0.5:
                    if histogram > 0 and macd_line > 0:
                        direction = 1
                        signal_type = 'BUY_TREND_CONTINUATION'
                        confidence = min(0.7, abs(histogram) / 20)
                    elif histogram < 0 and macd_line < 0:
                        direction = -1
                        signal_type = 'SELL_TREND_CONTINUATION'
                        confidence = min(0.7, abs(histogram) / 20)

        # 构建结果
        result = {
            'direction': direction,
            'confidence': confidence,
            'metadata': {
                'macd': float(macd_line),
                'signal': float(signal_line),
                'histogram': float(histogram),
                'signal_type': signal_type,
                'fast_period': self.macd_config.fast_period,
                'slow_period': self.macd_config.slow_period,
                'signal_period': self.macd_config.signal_period
            }
        }

        # 记录信号历史
        self.signal_history.append({
            'timestamp': pd.Timestamp.now().isoformat(),
            'direction': direction,
            'confidence': confidence,
            'macd': macd_line,
            'signal': signal_line,
            'histogram': histogram
        })

        # 限制历史长度
        if len(self.signal_history) > 1000:
            self.signal_history = self.signal_history[-1000:]

        return result

    def _calculate_macd(self, prices: List[float]) -> tuple:
        """计算MACD指标"""
        try:
            # 计算EMA
            fast_ema = self._calculate_ema(prices, self.macd_config.fast_period)
            slow_ema = self._calculate_ema(prices, self.macd_config.slow_period)

            if fast_ema is None or slow_ema is None:
                return None, None, None

            # MACD线 = 快线EMA - 慢线EMA
            macd_line = fast_ema - slow_ema

            # 为了计算信号线，我们需要MACD线的历史
            # 这里简化处理：使用当前MACD值作为近似
            # 实际应该计算MACD线的EMA
            macd_series = []
            for i in range(len(prices) - self.macd_config.slow_period + 1, len(prices) + 1):
                if i >= self.macd_config.slow_period:
                    subset = prices[:i]
                    fast = self._calculate_ema(subset, self.macd_config.fast_period)
                    slow = self._calculate_ema(subset, self.macd_config.slow_period)
                    if fast is not None and slow is not None:
                        macd_series.append(fast - slow)

            if len(macd_series) < self.macd_config.signal_period:
                return macd_line, macd_line, 0.0  # 简化返回

            # 计算信号线（MACD线的EMA）
            signal_line = self._calculate_ema_simple(macd_series, self.macd_config.signal_period)

            # 柱状图 = MACD线 - 信号线
            histogram = macd_line - signal_line if signal_line is not None else 0.0

            return macd_line, signal_line if signal_line is not None else macd_line, histogram

        except Exception as e:
            print(f"[MACDAgent] MACD calculation error: {e}")
            return None, None, None

    def _calculate_ema(self, prices: List[float], period: int) -> Optional[float]:
        """计算指数移动平均"""
        if len(prices) < period:
            return None

        alpha = 2 / (period + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = alpha * price + (1 - alpha) * ema
        return ema

    def _calculate_ema_simple(self, values: List[float], period: int) -> Optional[float]:
        """简化EMA计算"""
        if len(values) < period:
            return None

        alpha = 2 / (period + 1)
        ema = values[0]
        for value in values[1:]:
            ema = alpha * value + (1 - alpha) * ema
        return ema

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
            print(f"[MACDAgent] Error parsing state: {e}")

        return None

    def shutdown(self) -> None:
        """关闭策略"""
        self._initialized = False
        self.signal_history.clear()
        print("[MACDAgent] Shutdown complete")

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
            'avg_histogram': np.mean([s['histogram'] for s in self.signal_history])
        }


# 兼容性别名
MACDStrategy = MACDAgent
