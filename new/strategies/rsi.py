"""
RSI策略 - 均值回归策略

适合市场状态: MEAN_REVERTING, RANGE_BOUND
"""

import pandas as pd
import numpy as np
from strategies.base import StrategyBase, StrategyMetadata, Signal, SignalType


class RSIStrategy(StrategyBase):
    """RSI超买超卖策略"""

    METADATA = StrategyMetadata(
        name="rsi",
        version="1.0.0",
        description="RSI超买超卖策略，RSI低于超卖线买入，高于超买线卖出",
        author="System",
        tags=["mean_reversion", "oscillator"],
        suitable_regimes=["MEAN_REVERTING", "RANGE_BOUND"],
        params={
            "period": 14,
            "oversold": 30,
            "overbought": 70
        }
    )

    def on_init(self):
        """初始化"""
        params = self.get_params()
        self.period = params.get("period", 14)
        self.oversold = params.get("oversold", 30)
        self.overbought = params.get("overbought", 70)

    def _calculate_rsi(self, prices: np.ndarray) -> float:
        """计算RSI"""
        if len(prices) < self.period + 1:
            return 50.0

        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains[-self.period:])
        avg_loss = np.mean(losses[-self.period:])

        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """生成信号"""
        if len(data) < self.period + 1:
            return Signal(type=SignalType.HOLD, confidence=0.0)

        close = data['close'].values
        rsi = self._calculate_rsi(close)

        # 生成信号
        signal_type = SignalType.HOLD
        confidence = 0.5

        if rsi < self.oversold:
            # 超卖 - 买入
            signal_type = SignalType.BUY
            confidence = (self.oversold - rsi) / self.oversold * 0.5 + 0.5
        elif rsi > self.overbought:
            # 超买 - 卖出
            signal_type = SignalType.SELL
            confidence = (rsi - self.overbought) / (100 - self.overbought) * 0.5 + 0.5

        return Signal(
            type=signal_type,
            confidence=min(0.95, confidence),
            metadata={
                "rsi": rsi,
                "oversold": self.oversold,
                "overbought": self.overbought
            }
        )
