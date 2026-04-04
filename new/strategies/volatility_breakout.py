"""
波动率突破策略 (Volatility Breakout Strategy)
基于ATR和波动率通道捕捉突破行情
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional
try:
    from .base import StrategyBase, Signal, SignalType
except ImportError:
    from strategies.base import StrategyBase, Signal, SignalType


class VolatilityBreakoutStrategy(StrategyBase):
    """
    波动率突破策略

    核心逻辑：
    1. 计算ATR (Average True Range) 作为波动率度量
    2. 构建波动率通道 (上轨/下轨)
    3. 价格突破上轨 → 做多信号
    4. 价格突破下轨 → 做空信号
    5. 结合成交量确认突破有效性

    适用市场：高波动、突破行情
    与Dual_MA相关性：中等（都是趋势策略，但触发时机不同）
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None
    ):
        super().__init__(config)
        config = config or {}

        self.atr_period = config.get('atr_period', 14)
        self.channel_multiplier = config.get('channel_multiplier', 2.0)
        self.volume_confirm = config.get('volume_confirm', True)
        self.volume_threshold = config.get('volume_threshold', 1.5)

        # 状态跟踪
        self._upper_channel: Optional[float] = None
        self._lower_channel: Optional[float] = None
        self._atr: Optional[float] = None
        self._last_signal: Optional[Dict] = None

    def _calculate_atr(self, data: pd.DataFrame) -> float:
        """计算ATR (Average True Range)"""
        high = data['high']
        low = data['low']
        close = data['close']

        # True Range = max(high-low, |high-prev_close|, |low-prev_close|)
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.rolling(window=self.atr_period).mean().iloc[-1]

        return atr

    def _calculate_channels(self, data: pd.DataFrame) -> tuple:
        """计算波动率通道"""
        close = data['close']

        # 使用简单移动平均作为中轨
        middle = close.rolling(window=self.atr_period).mean().iloc[-1]

        # 计算ATR
        atr = self._calculate_atr(data)

        # 上下轨 = 中轨 ± ATR * multiplier
        upper = middle + atr * self.channel_multiplier
        lower = middle - atr * self.channel_multiplier

        return upper, lower, atr, middle

    def _check_volume_confirmation(self, data: pd.DataFrame) -> bool:
        """检查成交量确认"""
        if not self.volume_confirm or 'volume' not in data.columns:
            return True

        volume = data['volume']
        avg_volume = volume.rolling(window=self.atr_period).mean().iloc[-1]
        current_volume = volume.iloc[-1]

        return current_volume > avg_volume * self.volume_threshold

    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """
        生成交易信号

        Returns:
            Signal: 交易信号对象
        """
        if len(data) < self.atr_period + 5:
            return Signal(
                type=SignalType.HOLD,
                confidence=0.0,
                metadata={'error': 'Insufficient data'}
            )

        # 计算通道
        upper, lower, atr, middle = self._calculate_channels(data)
        current_price = data['close'].iloc[-1]

        self._upper_channel = upper
        self._lower_channel = lower
        self._atr = atr

        # 检查成交量确认
        volume_confirmed = self._check_volume_confirmation(data)

        # 判断突破
        direction = 0
        strength = 0.0
        breakout_type = 'none'

        # 上轨突破（做多）
        if current_price > upper:
            direction = 1
            breakout_type = 'upper'
            # 强度 = 突破幅度 / ATR
            strength = min(1.0, (current_price - upper) / atr)

        # 下轨突破（做空）
        elif current_price < lower:
            direction = -1
            breakout_type = 'lower'
            # 强度 = 突破幅度 / ATR
            strength = min(1.0, (lower - current_price) / atr)

        # 如果没有突破，计算接近程度（用于弱信号）
        if direction == 0:
            upper_distance = (upper - current_price) / atr
            lower_distance = (current_price - lower) / atr

            # 接近上轨（0.3 ATR以内）
            if 0 < upper_distance < 0.3:
                direction = 0.5  # 弱做多信号
                strength = 0.3 * (1 - upper_distance / 0.3)
                breakout_type = 'near_upper'

            # 接近下轨
            elif 0 < lower_distance < 0.3:
                direction = -0.5  # 弱做空信号
                strength = 0.3 * (1 - lower_distance / 0.3)
                breakout_type = 'near_lower'

        # 成交量调整
        if not volume_confirmed and abs(direction) > 0:
            strength *= 0.7  # 无成交量确认，降低强度

        # 置信度计算
        confidence = self._calculate_confidence(
            data, direction, strength, volume_confirmed
        )

        # 根据 direction 确定 SignalType
        if direction > 0.5:
            signal_type = SignalType.BUY
        elif direction < -0.5:
            signal_type = SignalType.SELL
        else:
            signal_type = SignalType.HOLD

        signal = Signal(
            type=signal_type,
            confidence=float(confidence),
            metadata={
                'direction': direction,
                'strength': float(strength),
                'upper_channel': float(upper),
                'lower_channel': float(lower),
                'atr': float(atr),
                'middle_band': float(middle),
                'current_price': float(current_price),
                'volume_confirmed': volume_confirmed,
                'breakout_type': breakout_type,
                'channel_width': float((upper - lower) / middle)  # 通道宽度百分比
            }
        )

        self._last_signal = signal
        return signal

    def _calculate_confidence(
        self,
        data: pd.DataFrame,
        direction: float,
        strength: float,
        volume_confirmed: bool
    ) -> float:
        """计算信号置信度"""
        if direction == 0:
            return 0.0

        confidence = strength * 0.6  # 基础置信度来自强度

        # 成交量确认加分
        if volume_confirmed:
            confidence += 0.2

        # 趋势一致性检查（与短期趋势方向一致）
        close = data['close']
        short_ma = close.rolling(window=5).mean().iloc[-1]
        long_ma = close.rolling(window=20).mean().iloc[-1]

        trend_direction = 1 if short_ma > long_ma else -1
        if np.sign(direction) == trend_direction:
            confidence += 0.2

        return min(1.0, confidence)

    def get_state(self) -> Dict[str, Any]:
        """获取策略状态"""
        last_signal_dict = None
        if self._last_signal is not None:
            last_signal_dict = {
                'type': self._last_signal.type.name,
                'confidence': self._last_signal.confidence,
                'metadata': self._last_signal.metadata
            }
        return {
            'name': self.name,
            'upper_channel': self._upper_channel,
            'lower_channel': self._lower_channel,
            'atr': self._atr,
            'last_signal': last_signal_dict
        }

    def reset(self):
        """重置策略状态"""
        super().reset()
        self._upper_channel = None
        self._lower_channel = None
        self._atr = None
        self._last_signal = None
