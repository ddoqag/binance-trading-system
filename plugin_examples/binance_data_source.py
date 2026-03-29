#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Binance 数据源插件 - Binance Data Source Plugin
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List
import logging
import os

from plugins.base import PluginBase, PluginType, PluginMetadata
from plugins.base import PluginHealthStatus


class BinanceDataSource(PluginBase):
    """Binance 数据源插件 - 获取 Binance K线数据"""

    def _get_metadata(self):
        return PluginMetadata(
            name="BinanceDataSource",
            version="0.1.0",
            type=PluginType.DATA_SOURCE,
            description="Binance K-line data source plugin",
            author="Binance Trading System",
            config_schema={
                "required": ["symbol", "interval"],
                "properties": {
                    "symbol": {"type": "string", "default": "BTCUSDT"},
                    "interval": {"type": "string", "default": "1h"},
                    "data_dir": {"type": "string", "default": "data"},
                    "use_cache": {"type": "boolean", "default": True},
                    "cache_timeout": {"type": "integer", "default": 3600}
                }
            }
        )

    def initialize(self):
        """初始化插件"""
        self.symbol = self.config.get("symbol", "BTCUSDT")
        self.interval = self.config.get("interval", "1h")
        self.data_dir = self.config.get("data_dir", "data")
        self.use_cache = self.config.get("use_cache", True)
        self.cache_timeout = self.config.get("cache_timeout", 3600)

        # 检查数据目录
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

        self.logger.info(
            f"Data source initialized: {self.symbol}@{self.interval}"
        )

    def start(self):
        """启动插件"""
        self.logger.info(f"Data source started: {self.symbol}@{self.interval}")

        # 发送数据就绪事件
        self.emit_event("data.ready", {
            "symbol": self.symbol,
            "interval": self.interval
        })

    def stop(self):
        """停止插件"""
        self.logger.info(f"Data source stopped: {self.symbol}@{self.interval}")

    def get_data(self, start_date: Optional[str] = None,
                 end_date: Optional[str] = None,
                 limit: int = 1000) -> pd.DataFrame:
        """
        获取 K 线数据

        Args:
            start_date: 开始日期
            end_date: 结束日期
            limit: 数据限制

        Returns:
            K 线数据 DataFrame
        """
        try:
            # 首先尝试从文件加载
            file_path = os.path.join(
                self.data_dir,
                f"{self.symbol}_{self.interval}.csv"
            )

            if os.path.exists(file_path):
                df = pd.read_csv(file_path)
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.set_index('timestamp', inplace=True)

                # 发送数据加载事件
                self.emit_event("data.loaded", {
                    "symbol": self.symbol,
                    "interval": self.interval,
                    "records_count": len(df),
                    "file_path": file_path
                })

                return df

            # 模拟数据（如果没有真实数据）
            return self._generate_synthetic_data()

        except Exception as e:
            self.logger.error(f"Failed to get data: {e}")
            return self._generate_synthetic_data()

    def _generate_synthetic_data(self) -> pd.DataFrame:
        """生成合成数据用于测试"""
        self.logger.warning("Using synthetic data for testing")

        # 生成测试数据
        periods = 1000
        start_date = pd.Timestamp.now() - pd.Timedelta(hours=periods)
        timestamps = pd.date_range(start=start_date, periods=periods, freq='H')

        # 生成价格数据（模拟随机游走）
        np.random.seed(42)
        base_price = 50000.0
        returns = np.random.normal(0, 0.001, periods)
        prices = base_price * np.exp(np.cumsum(returns))

        df = pd.DataFrame({
            'timestamp': timestamps,
            'open': prices,
            'high': prices * (1 + np.random.random(periods) * 0.005),
            'low': prices * (1 - np.random.random(periods) * 0.005),
            'close': prices,
            'volume': np.random.randint(100, 10000, periods)
        })

        df.set_index('timestamp', inplace=True)

        # 发送数据生成事件
        self.emit_event("data.generated", {
            "symbol": self.symbol,
            "interval": self.interval,
            "records_count": len(df),
            "data_source": "synthetic"
        })

        return df

    def health_check(self):
        """健康检查"""
        status = super().health_check()

        try:
            # 检查数据目录是否可读写
            if not os.access(self.data_dir, os.W_OK):
                status.healthy = False
                status.message = "Data directory not writable"

            # 测试获取数据
            df = self.get_data(limit=100)
            if len(df) < 10:
                status.healthy = False
                status.message = "Insufficient data available"

            status.metrics['data_records'] = len(df)
            status.metrics['data_dir'] = self.data_dir
            status.metrics['symbol'] = self.symbol
            status.metrics['interval'] = self.interval

        except Exception as e:
            status.healthy = False
            status.message = f"Health check failed: {e}"

        return status
