"""
趋势信号模块 - 基于价格动量的方向性交易信号

为 MVP 系统增加方向性 alpha，解决纯 spread capture 在极小价差下无法盈利的问题。
"""
import numpy as np
from typing import Dict, Optional
from collections import deque


class TrendSignal:
    """
    简单趋势跟踪信号

    使用短周期/长周期 EMA 交叉和价格动量来产生方向性交易信号。
    """

    def __init__(self,
                 short_period: int = 3,
                 long_period: int = 8,
                 momentum_period: int = 3,
                 min_confidence: float = 0.01,
                 breakout_threshold: float = 0.00005,  # 0.005% 突破阈值
                 breakout_lookback: int = 10):
        self.short_period = short_period
        self.long_period = long_period
        self.momentum_period = momentum_period
        self.min_confidence = min_confidence
        self.breakout_threshold = breakout_threshold
        self.breakout_lookback = breakout_lookback

        self.price_history = deque(maxlen=max(long_period * 2, breakout_lookback + 5))
        self.last_signal = 0.0
        self.signal_count = 0

    def update(self, mid_price: float):
        if mid_price > 0:
            self.price_history.append(mid_price)

    def _ema(self, period: int) -> Optional[float]:
        if len(self.price_history) < period:
            return None
        values = np.array(list(self.price_history)[-period:])
        weights = np.exp(np.linspace(-1., 0., period))
        weights /= weights.sum()
        return np.dot(values, weights)

    def generate(self) -> Dict:
        """
        生成趋势信号

        Returns:
            dict: {
                'direction': 1.0 (long), -1.0 (short), 0.0 (neutral),
                'confidence': 0.0 ~ 1.0,
                'strength': 归一化强度,
                'reason': str
            }
        """
        if len(self.price_history) < self.long_period:
            return {
                'direction': 0.0,
                'confidence': 0.0,
                'strength': 0.0,
                'reason': 'insufficient_data'
            }

        ema_short = self._ema(self.short_period)
        ema_long = self._ema(self.long_period)

        if ema_short is None or ema_long is None or ema_long == 0:
            return {
                'direction': 0.0,
                'confidence': 0.0,
                'strength': 0.0,
                'reason': 'calc_error'
            }

        # EMA 差异归一化
        ema_diff = (ema_short - ema_long) / ema_long

        # 动量
        if len(self.price_history) >= self.momentum_period + 1:
            recent = list(self.price_history)
            momentum = (recent[-1] - recent[-self.momentum_period - 1]) / recent[-self.momentum_period - 1]
        else:
            momentum = 0.0

        # 综合信号（EMA 占 70%，动量占 30%）
        combined = ema_diff * 0.7 + momentum * 0.3

        # 归一化到 -1 ~ 1
        strength = max(-1.0, min(1.0, combined * 100))

        confidence = abs(strength)
        direction = 1.0 if strength > self.min_confidence else (-1.0 if strength < -self.min_confidence else 0.0)
        reason = ""

        # 如果 EMA 趋势不够强，检查突破信号
        if direction == 0.0 and len(self.price_history) >= self.breakout_lookback + 1:
            recent_prices = list(self.price_history)
            current = recent_prices[-1]
            lookback = recent_prices[-(self.breakout_lookback + 1):-1]
            high = max(lookback)
            low = min(lookback)

            if high > 0 and current > high * (1 + self.breakout_threshold):
                direction = 1.0
                strength = max(strength, 0.05)
                confidence = max(confidence, 0.05)
                reason = f"breakout_up_{self.breakout_lookback}t"
            elif low > 0 and current < low * (1 - self.breakout_threshold):
                direction = -1.0
                strength = min(strength, -0.05)
                confidence = max(confidence, 0.05)
                reason = f"breakout_down_{self.breakout_lookback}t"

        if direction != 0.0 and not reason.startswith("breakout"):
            self.last_signal = direction
            self.signal_count += 1
            reason = f"trend_{'up' if direction > 0 else 'down'}_strength={strength:.3f}"
        elif direction == 0.0:
            reason = f"no_trend_strength={strength:.3f}"

        return {
            'direction': direction,
            'confidence': confidence,
            'strength': strength,
            'reason': reason,
            'ema_diff': ema_diff,
            'momentum': momentum
        }
