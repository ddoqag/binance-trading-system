#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双均线策略插件 - Dual Moving Average Strategy Plugin
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List

from plugins.base import PluginBase, PluginType, PluginMetadata
from plugins.base import PluginHealthStatus


class DualMAStrategy(PluginBase):
    """双均线策略插件"""

    def _get_metadata(self):
        return PluginMetadata(
            name="DualMAStrategy",
            version="0.1.0",
            type=PluginType.STRATEGY,
            description="Dual moving average crossover strategy",
            author="Binance Trading System",
            config_schema={
                "properties": {
                    "fast_window": {"type": "integer", "default": 5},
                    "slow_window": {"type": "integer", "default": 20},
                    "signal_threshold": {"type": "number", "default": 0.001},
                    "max_position_size": {"type": "number", "default": 0.2},
                    "stop_loss_pct": {"type": "number", "default": 0.02},
                    "take_profit_pct": {"type": "number", "default": 0.04}
                }
            }
        )

    def initialize(self):
        """初始化插件"""
        self.fast_window = self.config.get("fast_window", 5)
        self.slow_window = self.config.get("slow_window", 20)
        self.signal_threshold = self.config.get("signal_threshold", 0.001)
        self.max_position_size = self.config.get("max_position_size", 0.2)
        self.stop_loss_pct = self.config.get("stop_loss_pct", 0.02)
        self.take_profit_pct = self.config.get("take_profit_pct", 0.04)

        self.logger.info(
            f"Dual MA strategy initialized: {self.fast_window}/{self.slow_window}"
        )

        # 订阅事件
        self.subscribe_event("data.loaded", self._on_data_loaded)
        self.subscribe_event("factor.calculated", self._on_factor_calculated)

        # 状态
        self.position = 0  # 1=多头, -1=空头, 0=空仓
        self.last_signal = 0

    def start(self):
        """启动插件"""
        self.logger.info("Dual MA strategy started")

    def stop(self):
        """停止插件"""
        self.logger.info("Dual MA strategy stopped")

    def _on_data_loaded(self, event):
        """处理数据加载事件"""
        self.logger.debug(
            f"Data loaded event received: {event.data['records_count']} records"
        )

    def _on_factor_calculated(self, event):
        """处理因子计算事件"""
        self.logger.debug(
            f"Factor calculated event received: {event.data['factor_name']}"
        )

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号

        Args:
            df: K 线数据 DataFrame，包含 'close' 列

        Returns:
            包含 'signal' 列的 DataFrame
        """
        df = df.copy()

        # 计算均线
        df['ma_fast'] = df['close'].rolling(window=self.fast_window).mean()
        df['ma_slow'] = df['close'].rolling(window=self.slow_window).mean()

        # 计算信号
        df['signal'] = 0

        # 买入信号：快均线上穿慢均线
        buy_signal = (df['ma_fast'] > df['ma_slow']) & (df['ma_fast'].shift(1) <= df['ma_slow'].shift(1))
        df.loc[buy_signal, 'signal'] = 1

        # 卖出信号：快均线下穿慢均线
        sell_signal = (df['ma_fast'] < df['ma_slow']) & (df['ma_fast'].shift(1) >= df['ma_slow'].shift(1))
        df.loc[sell_signal, 'signal'] = -1

        # 发送信号生成事件
        self.emit_event("strategy.signals_generated", {
            "strategy_name": self.metadata.name,
            "signals_count": len(df['signal'].dropna()),
            "buy_signals": df['signal'].value_counts().get(1, 0),
            "sell_signals": df['signal'].value_counts().get(-1, 0)
        })

        return df

    def get_trading_signals(self, df: pd.DataFrame, price: float) -> Dict[str, Any]:
        """
        获取当前价格对应的交易信号

        Args:
            df: K 线数据
            price: 当前价格

        Returns:
            信号字典
        """
        signals_df = self.generate_signals(df)
        latest_signal = signals_df['signal'].iloc[-1]

        if latest_signal == 1 and self.position != 1:
            return {
                "signal": "BUY",
                "type": "LONG",
                "price": price,
                "size": self.max_position_size,
                "stop_loss": price * (1 - self.stop_loss_pct),
                "take_profit": price * (1 + self.take_profit_pct)
            }
        elif latest_signal == -1 and self.position != -1:
            return {
                "signal": "SELL",
                "type": "SHORT",
                "price": price,
                "size": self.max_position_size,
                "stop_loss": price * (1 + self.stop_loss_pct),
                "take_profit": price * (1 - self.take_profit_pct)
            }
        else:
            return {
                "signal": "HOLD",
                "type": "HOLD",
                "price": price
            }

    def update_position(self, signal: Dict[str, Any]):
        """
        更新持仓状态

        Args:
            signal: 交易信号字典
        """
        if signal["signal"] == "BUY":
            self.position = 1
            self.last_signal = signal
        elif signal["signal"] == "SELL":
            self.position = -1
            self.last_signal = signal
        elif signal["signal"] == "CLOSE":
            self.position = 0
            self.last_signal = None

        # 发送持仓更新事件
        self.emit_event("strategy.position_updated", {
            "strategy_name": self.metadata.name,
            "signal": signal["signal"],
            "position": self.position,
            "timestamp": pd.Timestamp.now().timestamp()
        })

    def health_check(self):
        """健康检查"""
        status = super().health_check()
        status.metrics.update({
            "fast_window": self.fast_window,
            "slow_window": self.slow_window,
            "current_position": self.position,
            "max_position_size": self.max_position_size
        })

        return status
