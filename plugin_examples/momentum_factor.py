#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动量因子插件 - Momentum Factor Plugin
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List

from plugins.base import PluginBase, PluginType, PluginMetadata
from plugins.base import PluginHealthStatus


class MomentumFactor(PluginBase):
    """动量因子插件"""

    def _get_metadata(self):
        return PluginMetadata(
            name="MomentumFactor",
            version="0.1.0",
            type=PluginType.FACTOR,
            description="Momentum factor calculation plugin",
            author="Binance Trading System",
            config_schema={
                "properties": {
                    "lookback_period": {"type": "integer", "default": 20},
                    "normalization": {"type": "boolean", "default": True},
                    "zscore_threshold": {"type": "number", "default": 2.0}
                }
            }
        )

    def initialize(self):
        """初始化插件"""
        self.lookback_period = self.config.get("lookback_period", 20)
        self.normalization = self.config.get("normalization", True)
        self.zscore_threshold = self.config.get("zscore_threshold", 2.0)

        self.logger.info(
            f"Momentum factor initialized: lookback={self.lookback_period}"
        )

        # 订阅数据事件
        self.subscribe_event("data.ready", self._on_data_ready)
        self.subscribe_event("data.loaded", self._on_data_loaded)

    def start(self):
        """启动插件"""
        self.logger.info("Momentum factor started")

    def stop(self):
        """停止插件"""
        self.logger.info("Momentum factor stopped")

    def _on_data_ready(self, event):
        """处理数据就绪事件"""
        self.logger.debug(
            f"Data ready event received: {event.data['symbol']}@{event.data['interval']}"
        )

    def _on_data_loaded(self, event):
        """处理数据加载事件"""
        self.logger.debug(
            f"Data loaded event received: {event.data['records_count']} records"
        )

    def calculate(self, df: pd.DataFrame) -> pd.Series:
        """
        计算动量因子

        Args:
            df: K 线数据 DataFrame，必须包含 'close' 列

        Returns:
            动量因子值 Series
        """
        if 'close' not in df.columns:
            raise ValueError("DataFrame must contain 'close' column")

        # 计算动量
        momentum = df['close'] / df['close'].shift(self.lookback_period) - 1

        # 归一化
        if self.normalization:
            # Z-score 标准化
            mean = momentum.rolling(window=self.lookback_period).mean()
            std = momentum.rolling(window=self.lookback_period).std()
            momentum = (momentum - mean) / std

        # 发送因子计算事件
        self.emit_event("factor.calculated", {
            "factor_name": self.metadata.name,
            "lookback_period": self.lookback_period,
            "data_points": len(momentum.dropna()),
            "normalization": self.normalization
        })

        return momentum

    def calculate_batch(self, data_dict: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """
        批量计算多个资产的动量因子

        Args:
            data_dict: {symbol: DataFrame} 数据字典

        Returns:
            {symbol: 因子值 Series} 结果字典
        """
        result = {}
        for symbol, df in data_dict.items():
            try:
                result[symbol] = self.calculate(df)
            except Exception as e:
                self.logger.error(f"Failed to calculate factor for {symbol}: {e}")

        return result

    def filter_signals(self, factor_series: pd.Series) -> pd.Series:
        """
        根据因子值筛选信号

        Args:
            factor_series: 因子值 Series

        Returns:
            信号 Series (1=买入, -1=卖出, 0=持有)
        """
        signals = pd.Series(0, index=factor_series.index)

        # 买入信号：正动量且 Z-score > 阈值
        buy_condition = factor_series > self.zscore_threshold
        signals[buy_condition] = 1

        # 卖出信号：负动量且 Z-score < -阈值
        sell_condition = factor_series < -self.zscore_threshold
        signals[sell_condition] = -1

        return signals

    def health_check(self):
        """健康检查"""
        status = super().health_check()
        status.metrics.update({
            "lookback_period": self.lookback_period,
            "normalization": self.normalization,
            "zscore_threshold": self.zscore_threshold
        })

        return status
