#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双均线策略 - Dual Moving Average Strategy
"""

import pandas as pd
from .base import BaseStrategy


class DualMAStrategy(BaseStrategy):
    """双均线策略"""

    def __init__(self, short_window: int = 10, long_window: int = 30):
        """
        初始化双均线策略

        Args:
            short_window: 短期均线周期
            long_window: 长期均线周期
        """
        super().__init__(
            name=f"DualMA_{short_window}_{long_window}",
            params={'short_window': short_window, 'long_window': long_window}
        )
        self.short_window = short_window
        self.long_window = long_window

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号

        金叉：短期均线上穿长期均线 -> 买入
        死叉：短期均线下穿长期均线 -> 卖出

        Args:
            df: K线数据

        Returns:
            包含信号的 DataFrame
        """
        df = df.copy()

        # 计算移动平均线
        df['ma_short'] = df['close'].rolling(window=self.short_window).mean()
        df['ma_long'] = df['close'].rolling(window=self.long_window).mean()

        # 生成信号
        df['signal'] = 0

        # 当短期均线在长期均线上方时，持有多头
        df.loc[df['ma_short'] > df['ma_long'], 'signal'] = 1
        # 当短期均线在长期均线下方时，持有空头（或空仓）
        df.loc[df['ma_short'] < df['ma_long'], 'signal'] = -1

        # 计算信号变化点（用于交易）
        df['position_change'] = df['signal'].diff()

        self.logger.debug(
            f"Generated signals: {len(df)} rows, "
            f"buy signals: {(df['position_change'] == 2).sum()}, "
            f"sell signals: {(df['position_change'] == -2).sum()}"
        )

        return df

    def get_entry_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        获取入场点（金叉）
        """
        df = self.generate_signals(df)
        df['entry'] = (df['position_change'] == 2)
        return df[df['entry']].copy()

    def get_exit_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        获取出场点（死叉）
        """
        df = self.generate_signals(df)
        df['exit'] = (df['position_change'] == -2)
        return df[df['exit']].copy()
