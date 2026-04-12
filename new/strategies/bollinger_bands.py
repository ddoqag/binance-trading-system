"""
布林带策略 (Bollinger Bands Strategy)
结合均值回归和波动率交易
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional
try:
    from .base import StrategyBase, Signal, SignalType, safe_divide
except ImportError:
    from strategies.base import StrategyBase, Signal, SignalType, safe_divide


class BollingerBandsStrategy(StrategyBase):
    """
    布林带策略

    核心逻辑：
    1. 价格触及上轨 + 反转信号 → 做空（均值回归）
    2. 价格触及下轨 + 反转信号 → 做多（均值回归）
    3. 价格突破上轨 + 趋势确认 → 做多（趋势跟踪）
    4. 价格突破下轨 + 趋势确认 → 做空（趋势跟踪）
    5. 带宽收缩（Squeeze）→ 预示大行情即将到来

    适用市场：震荡市（均值回归模式）和趋势市（突破模式）
    与RSI相关性：中等（都是震荡指标）
    与Dual_MA相关性：低（不同逻辑）
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None
    ):
        super().__init__(config)
        config = config or {}

        self.period = config.get('period', 20)
        self.std_dev = config.get('std_dev', 2.0)
        self.squeeze_threshold = config.get('squeeze_threshold', 0.1)
        self.mean_reversion_mode = config.get('mean_reversion_mode', True)
        self.trend_following_mode = config.get('trend_following_mode', True)

        # 状态
        self._upper: Optional[float] = None
        self._middle: Optional[float] = None
        self._lower: Optional[float] = None
        self._bandwidth: Optional[float] = None
        self._squeeze_active: bool = False

    def _calculate_bands(self, data: pd.DataFrame) -> tuple:
        """计算布林带"""
        close = data['close']

        middle = close.rolling(window=self.period).mean()
        std = close.rolling(window=self.period).std()

        upper = middle + std * self.std_dev
        lower = middle - std * self.std_dev

        # 带宽 = (上轨 - 下轨) / 中轨 (使用安全除法)
        bandwidth = safe_divide(upper - lower, middle, default=0.0)

        return (
            upper.iloc[-1],
            middle.iloc[-1],
            lower.iloc[-1],
            bandwidth.iloc[-1],
            bandwidth.iloc[-(self.period//2):].mean()  # 近期平均带宽
        )

    def _calculate_position_in_band(self, price: float) -> float:
        """计算价格在布林带中的位置（0=下轨，1=上轨，0.5=中轨）"""
        if self._upper is None or self._lower is None:
            return 0.5

        return safe_divide(price - self._lower, self._upper - self._lower, default=0.5)

    def _detect_squeeze(self, current_bw: float, avg_bw: float) -> bool:
        """检测布林带收缩（Squeeze）"""
        return current_bw < avg_bw * (1 - self.squeeze_threshold)

    def _check_reversal_pattern(self, data: pd.DataFrame, direction: int) -> bool:
        """检查反转形态"""
        close = data['close'].values
        if len(close) < 3:
            return False

        if direction == 1:  # 检查底部反转
            # 连续下跌后上涨
            return close[-3] > close[-2] < close[-1]
        else:  # 检查顶部反转
            # 连续上涨后下跌
            return close[-3] < close[-2] > close[-1]

    def _check_trend_strength(self, data: pd.DataFrame) -> float:
        """检查趋势强度（-1到1）"""
        close = data['close']

        # 多周期均线排列
        ma5 = close.rolling(window=5).mean().iloc[-1]
        ma10 = close.rolling(window=10).mean().iloc[-1]
        ma20 = close.rolling(window=self.period).mean().iloc[-1]

        if ma5 > ma10 > ma20:
            return 1.0  # 强上涨趋势
        elif ma5 < ma10 < ma20:
            return -1.0  # 强下跌趋势
        else:
            return 0.0  # 无明确趋势

    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """
        生成交易信号

        Returns:
            Signal: 交易信号对象
        """
        if len(data) < self.period + 5:
            return Signal(
                type=SignalType.HOLD,
                confidence=0.0,
                metadata={'error': 'Insufficient data'}
            )

        # 计算布林带
        upper, middle, lower, bandwidth, avg_bandwidth = self._calculate_bands(data)
        current_price = data['close'].iloc[-1]

        self._upper = upper
        self._middle = middle
        self._lower = lower
        self._bandwidth = bandwidth
        self._squeeze_active = self._detect_squeeze(bandwidth, avg_bandwidth)

        # 计算位置
        position_in_band = self._calculate_position_in_band(current_price)

        direction = 0
        strength = 0.0
        mode = 'none'

        # 策略1: 均值回归（价格极端时反转）
        if self.mean_reversion_mode and not self._squeeze_active:
            if position_in_band > 0.95:  # 接近上轨
                # 检查反转信号
                if self._check_reversal_pattern(data, -1):
                    direction = -1
                    strength = (position_in_band - 0.5) * 2  # 越极端越强
                    mode = 'mean_reversion'

            elif position_in_band < 0.05:  # 接近下轨
                if self._check_reversal_pattern(data, 1):
                    direction = 1
                    strength = (0.5 - position_in_band) * 2
                    mode = 'mean_reversion'

        # 策略2: 趋势跟踪（突破布林带）
        if self.trend_following_mode and direction == 0:
            trend_strength = self._check_trend_strength(data)

            if position_in_band > 0.98 and trend_strength > 0.5:
                # 强势突破上轨
                direction = 1
                strength = trend_strength
                mode = 'trend_following'

            elif position_in_band < 0.02 and trend_strength < -0.5:
                # 强势突破下轨
                direction = -1
                strength = abs(trend_strength)
                mode = 'trend_following'

        # 策略3: Squeeze突破预警
        if self._squeeze_active and direction == 0:
            # 收缩期间，准备大行情
            if position_in_band > 0.6:
                direction = 0.3  # 弱做多预期
                strength = 0.2
                mode = 'squeeze'
            elif position_in_band < 0.4:
                direction = -0.3  # 弱做空预期
                strength = 0.2
                mode = 'squeeze'

        # 计算置信度
        confidence = self._calculate_confidence(
            direction, strength, mode, position_in_band, data
        )

        # 根据 direction 确定 SignalType
        if direction > 0.5:
            signal_type = SignalType.BUY
        elif direction < -0.5:
            signal_type = SignalType.SELL
        else:
            signal_type = SignalType.HOLD

        return Signal(
            type=signal_type,
            confidence=float(confidence),
            metadata={
                'direction': direction,
                'strength': float(strength),
                'upper': float(upper),
                'middle': float(middle),
                'lower': float(lower),
                'position_in_band': float(position_in_band),
                'bandwidth': float(bandwidth),
                'squeeze': self._squeeze_active,
                'mode': mode,
                'trend_strength': float(self._check_trend_strength(data))
            }
        )

    def _calculate_confidence(
        self,
        direction: float,
        strength: float,
        mode: str,
        position_in_band: float,
        data: pd.DataFrame
    ) -> float:
        """计算信号置信度"""
        if direction == 0:
            return 0.0

        confidence = strength * 0.5

        # 根据模式调整
        if mode == 'mean_reversion':
            # 均值回归：越极端置信度越高
            confidence += abs(position_in_band - 0.5) * 0.3

        elif mode == 'trend_following':
            # 趋势跟踪：趋势越强置信度越高
            trend = self._check_trend_strength(data)
            confidence += abs(trend) * 0.3

        elif mode == 'squeeze':
            # Squeeze模式置信度较低
            confidence *= 0.7

        # 成交量确认
        if 'volume' in data.columns:
            volume = data['volume']
            avg_vol = volume.rolling(window=self.period).mean().iloc[-1]
            curr_vol = volume.iloc[-1]
            if curr_vol > avg_vol * 1.3:
                confidence += 0.2

        return min(1.0, confidence)

    def get_state(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'upper': self._upper,
            'middle': self._middle,
            'lower': self._lower,
            'bandwidth': self._bandwidth,
            'squeeze_active': self._squeeze_active
        }

    def reset(self):
        super().reset()
        self._upper = None
        self._middle = None
        self._lower = None
        self._bandwidth = None
        self._squeeze_active = False
