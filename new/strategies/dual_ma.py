"""
双均线策略 - 趋势跟踪策略

适合市场状态: TRENDING, BULL, BEAR
"""

import pandas as pd
import numpy as np
from strategies.base import StrategyBase, StrategyMetadata, Signal, SignalType


class DualMAStrategy(StrategyBase):
    """双均线交叉策略"""

    METADATA = StrategyMetadata(
        name="dual_ma",
        version="1.0.0",
        description="双均线交叉策略，短期均线上穿长期均线买入，下穿卖出",
        author="System",
        tags=["trend_following", "ma"],
        suitable_regimes=["TRENDING", "BULL", "BEAR"],
        params={
            "fast_period": 10,
            "slow_period": 30
        }
    )

    def on_init(self):
        """初始化"""
        params = self.get_params()
        self.fast_period = params.get("fast_period", 10)
        self.slow_period = params.get("slow_period", 30)
        self.prev_fast = None
        self.prev_slow = None

    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """生成信号"""
        if len(data) < self.slow_period:
            return Signal(type=SignalType.HOLD, confidence=0.0)

        close = data['close'].values

        # 计算均线
        fast_ma = np.mean(close[-self.fast_period:])
        slow_ma = np.mean(close[-self.slow_period:])

        # 记录历史用于交叉检测
        if len(data) >= self.slow_period + 1:
            prev_fast = np.mean(close[-(self.fast_period+1):-1])
            prev_slow = np.mean(close[-(self.slow_period+1):-1])
        else:
            prev_fast = fast_ma
            prev_slow = slow_ma

        # 交叉检测
        signal_type = SignalType.HOLD
        confidence = 0.5

        if prev_fast <= prev_slow and fast_ma > slow_ma:
            # 金叉 - 买入
            signal_type = SignalType.BUY
            confidence = min(0.9, abs(fast_ma - slow_ma) / slow_ma * 100 + 0.5)
        elif prev_fast >= prev_slow and fast_ma < slow_ma:
            # 死叉 - 卖出
            signal_type = SignalType.SELL
            confidence = min(0.9, abs(fast_ma - slow_ma) / slow_ma * 100 + 0.5)

        # 趋势强度调整
        trend_strength = abs(fast_ma - slow_ma) / slow_ma

        return Signal(
            type=signal_type,
            confidence=confidence,
            metadata={
                "fast_ma": fast_ma,
                "slow_ma": slow_ma,
                "trend_strength": trend_strength
            }
        )

    def on_params_changed(self, params: dict):
        """参数更新"""
        if "fast_period" in params:
            self.fast_period = params["fast_period"]
        if "slow_period" in params:
            self.slow_period = params["slow_period"]
