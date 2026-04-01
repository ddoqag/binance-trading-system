"""
动量策略 - 高波动市场

适合市场状态: HIGH_VOLATILITY
"""

import pandas as pd
import numpy as np
from strategies.base import StrategyBase, StrategyMetadata, Signal, SignalType


class MomentumStrategy(StrategyBase):
    """价格动量策略"""

    METADATA = StrategyMetadata(
        name="momentum",
        version="1.0.0",
        description="价格动量策略，基于短期收益率动量交易",
        author="System",
        tags=["momentum", "high_volatility"],
        suitable_regimes=["HIGH_VOLATILITY", "TRENDING"],
        params={
            "lookback": 5,
            "threshold": 0.02
        }
    )

    def on_init(self):
        """初始化"""
        params = self.get_params()
        self.lookback = params.get("lookback", 5)
        self.threshold = params.get("threshold", 0.02)

    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """生成信号"""
        if len(data) < self.lookback + 1:
            return Signal(type=SignalType.HOLD, confidence=0.0)

        close = data['close'].values

        # 计算动量（收益率）
        momentum = (close[-1] - close[-(self.lookback+1)]) / close[-(self.lookback+1)]

        signal_type = SignalType.HOLD
        confidence = 0.5

        if momentum > self.threshold:
            signal_type = SignalType.BUY
            confidence = min(0.9, abs(momentum) / self.threshold * 0.5)
        elif momentum < -self.threshold:
            signal_type = SignalType.SELL
            confidence = min(0.9, abs(momentum) / self.threshold * 0.5)

        return Signal(
            type=signal_type,
            confidence=confidence,
            metadata={
                "momentum": momentum,
                "threshold": self.threshold
            }
        )
