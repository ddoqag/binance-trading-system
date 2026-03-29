#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSI 策略 - Relative Strength Index Strategy
"""

import pandas as pd
import numpy as np
from .base import BaseStrategy
from indicators.technical import rsi as calculate_rsi


class RSIStrategy(BaseStrategy):
    """RSI 策略"""

    def __init__(self, rsi_period: int = 14,
                 oversold: float = 30.0,
                 overbought: float = 70.0):
        """
        初始化 RSI 策略

        Args:
            rsi_period: RSI 周期
            oversold: 超卖阈值（买入信号）
            overbought: 超买阈值（卖出信号）
        """
        super().__init__(
            name=f"RSI_{rsi_period}_{oversold:.0f}_{overbought:.0f}",
            params={
                'rsi_period': rsi_period,
                'oversold': oversold,
                'overbought': overbought
            }
        )
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought

    def _calculate_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算 RSI 指标（使用 indicators 模块）

        Args:
            df: K线数据

        Returns:
            包含 RSI 的 DataFrame
        """
        df = df.copy()
        df['rsi'] = calculate_rsi(df['close'], period=self.rsi_period)
        return df

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号

        RSI < 30: 超卖，买入信号
        RSI > 70: 超买，卖出信号

        Args:
            df: K线数据

        Returns:
            包含信号的 DataFrame
        """
        df = self._calculate_rsi(df)

        # 初始化信号
        df['signal'] = 0

        # RSI 从超卖区域回升时买入
        df.loc[(df['rsi'] > self.oversold) &
               (df['rsi'].shift(1) <= self.oversold), 'signal'] = 1

        # RSI 从超买区域回落时卖出
        df.loc[(df['rsi'] < self.overbought) &
               (df['rsi'].shift(1) >= self.overbought), 'signal'] = -1

        # 计算持仓状态（简化版：只在信号点交易）
        df['position'] = df['signal'].cumsum().clip(-1, 1)

        # 计算信号变化点（用于交易）
        df['position_change'] = df['signal']

        self.logger.debug(
            f"Generated RSI signals: {len(df)} rows, "
            f"buy signals: {(df['signal'] == 1).sum()}, "
            f"sell signals: {(df['signal'] == -1).sum()}"
        )

        return df
