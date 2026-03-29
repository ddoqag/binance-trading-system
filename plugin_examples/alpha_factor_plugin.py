#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Alpha因子插件 - Alpha Factor Plugin
封装现有的30+个Alpha因子，使其符合插件系统标准
"""

import pandas as pd
from typing import Dict, Any, List, Optional
import logging

from plugins.base import PluginBase, PluginType, PluginMetadata, PluginHealthStatus

# 导入现有的因子库
try:
    from factors import (
        momentum,
        mean_reversion,
        volatility,
        volume
    )
    FACTORS_AVAILABLE = True
except ImportError:
    FACTORS_AVAILABLE = False


class AlphaFactorPlugin(PluginBase):
    """
    Alpha因子插件 - 支持计算多种Alpha因子
    """

    def _get_metadata(self) -> PluginMetadata:
        """获取插件元数据"""
        return PluginMetadata(
            name="AlphaFactorPlugin",
            version="1.0.0",
            type=PluginType.FACTOR,
            interface_version="1.0.0",
            description="Alpha factor library with 30+ factors across momentum, mean-reversion, volatility, and volume categories",
            author="Binance Trading System",
            dependencies={},
            config_schema={
                "properties": {
                    "default_factors": {"type": "array", "default": []},
                    "use_cache": {"type": "boolean", "default": True}
                }
            }
        )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """初始化因子插件"""
        super().__init__(config)
        self.default_factors = self.config.get("default_factors", [])
        self.use_cache = self.config.get("use_cache", True)
        self._factor_cache: Dict[str, pd.Series] = {}
        self._available_factors = self._list_available_factors()

    def initialize(self):
        """初始化因子插件"""
        if not FACTORS_AVAILABLE:
            self.logger.warning("Factor library not available, using minimal implementation")

        self.logger.info(f"AlphaFactorPlugin initialized with {len(self._available_factors)} factors")

        # 订阅数据事件
        self.subscribe_event("data.ready", self._on_data_ready)
        self.subscribe_event("data.loaded", self._on_data_loaded)

    def start(self):
        """启动因子插件"""
        self.logger.info("AlphaFactorPlugin started")

    def stop(self):
        """停止因子插件"""
        self.logger.info("AlphaFactorPlugin stopped")
        self._factor_cache.clear()

    def _on_data_ready(self, event):
        """处理数据就绪事件"""
        self.logger.debug(f"Data ready: {event.data}")

    def _on_data_loaded(self, event):
        """处理数据加载事件"""
        self.logger.debug(f"Data loaded: {event.data.get('records_count', 0)} records")
        if not self.use_cache:
            self._factor_cache.clear()

    def _list_available_factors(self) -> List[str]:
        """列出可用的因子"""
        return [
            # 动量因子 (8)
            "momentum_20",
            "momentum_60",
            "ema_trend",
            "macd_momentum",
            "multi_period_momentum",
            "momentum_acceleration",
            "gap_momentum",
            "intraday_momentum",
            # 均值回归因子 (7)
            "zscore_20",
            "bollinger_position",
            "short_term_reversal",
            "rsi_reversion",
            "ma_convergence",
            "price_percentile",
            "channel_breakout_reversion",
            # 波动率因子 (8)
            "realized_volatility",
            "atr_normalized",
            "volatility_breakout",
            "volatility_change",
            "volatility_term_structure",
            "iv_premium",
            "volatility_correlation",
            "jump_volatility",
            # 成交量因子 (7)
            "volume_anomaly",
            "volume_momentum",
            "price_volume_trend",
            "volume_ratio",
            "volume_position",
            "volume_concentration",
            "volume_divergence",
        ]

    def get_available_factors(self) -> List[str]:
        """获取所有可用的因子名称"""
        return self._available_factors.copy()

    def calculate_factor(self, df: pd.DataFrame, factor_name: str,
                        **kwargs) -> Optional[pd.Series]:
        """
        计算单个因子

        Args:
            df: K线数据 DataFrame
            factor_name: 因子名称
            **kwargs: 因子参数

        Returns:
            因子值 Series，失败返回 None
        """
        # 检查缓存
        cache_key = f"{factor_name}_{kwargs.get('period', 'default')}"
        if self.use_cache and cache_key in self._factor_cache:
            return self._factor_cache[cache_key].copy()

        try:
            result = None

            if FACTORS_AVAILABLE:
                # 使用完整的因子库
                result = self._calculate_with_library(df, factor_name, **kwargs)
            else:
                # 使用简化实现
                result = self._calculate_minimal(df, factor_name, **kwargs)

            # 缓存结果
            if result is not None and self.use_cache:
                self._factor_cache[cache_key] = result.copy()

            # 发送因子计算事件
            self.emit_event("factor.calculated", {
                "factor_name": factor_name,
                "factor_category": self._get_factor_category(factor_name),
                "data_points": len(result.dropna()) if result is not None else 0,
                "from_cache": cache_key in self._factor_cache
            })

            return result

        except Exception as e:
            self.logger.error(f"Failed to calculate factor {factor_name}: {e}")
            return None

    def _calculate_with_library(self, df: pd.DataFrame, factor_name: str,
                               **kwargs) -> Optional[pd.Series]:
        """使用完整因子库计算"""
        try:
            prices = df['close']
            volumes = df['volume']
            highs = df['high']
            lows = df['low']

            # 动量因子
            if factor_name == "momentum_20":
                from factors.momentum import momentum
                return momentum(prices, period=kwargs.get('period', 20))
            elif factor_name == "momentum_60":
                from factors.momentum import momentum
                return momentum(prices, period=kwargs.get('period', 60))
            elif factor_name == "ema_trend":
                from factors.momentum import ema_trend
                return ema_trend(prices)
            elif factor_name == "macd_momentum":
                from factors.momentum import macd_momentum
                return macd_momentum(prices)
            elif factor_name == "multi_period_momentum":
                from factors.momentum import multi_period_momentum
                return multi_period_momentum(prices)

            # 均值回归因子
            elif factor_name == "zscore_20":
                from factors.mean_reversion import zscore
                return zscore(prices, period=kwargs.get('period', 20))
            elif factor_name == "bollinger_position":
                from factors.mean_reversion import bollinger_position
                return bollinger_position(prices)
            elif factor_name == "short_term_reversal":
                from factors.mean_reversion import short_term_reversal
                return short_term_reversal(prices)
            elif factor_name == "rsi_reversion":
                from factors.mean_reversion import rsi_reversion
                return rsi_reversion(prices)

            # 波动率因子
            elif factor_name == "realized_volatility":
                from factors.volatility import realized_volatility
                return realized_volatility(prices)
            elif factor_name == "atr_normalized":
                from factors.volatility import atr_normalized
                return atr_normalized(highs, lows, prices)
            elif factor_name == "volatility_breakout":
                from factors.volatility import volatility_breakout
                return volatility_breakout(prices)

            # 成交量因子
            elif factor_name == "volume_anomaly":
                from factors.volume import volume_anomaly
                return volume_anomaly(volumes)
            elif factor_name == "volume_momentum":
                from factors.volume import volume_momentum
                return volume_momentum(volumes)
            elif factor_name == "price_volume_trend":
                from factors.volume import price_volume_trend
                return price_volume_trend(prices, volumes)

            else:
                # 对于其他未实现的因子，返回 None
                return None

        except Exception as e:
            self.logger.warning(f"Library calculation failed for {factor_name}, falling back: {e}")
            return self._calculate_minimal(df, factor_name, **kwargs)

    def _calculate_minimal(self, df: pd.DataFrame, factor_name: str,
                          **kwargs) -> Optional[pd.Series]:
        """使用简化实现计算（后备方案）"""
        prices = df['close']
        volumes = df['volume']

        # 简化实现 - 只实现最常用的因子
        if factor_name in ["momentum_20", "momentum_60"]:
            period = kwargs.get('period', 20 if "20" in factor_name else 60)
            return prices / prices.shift(period) - 1

        elif factor_name == "ema_trend":
            ema_short = prices.ewm(span=12).mean()
            ema_long = prices.ewm(span=26).mean()
            return (ema_short - ema_long) / ema_long

        elif factor_name in ["zscore_20", "zscore_60"]:
            period = kwargs.get('period', 20 if "20" in factor_name else 60)
            rolling = prices.rolling(window=period)
            return (prices - rolling.mean()) / rolling.std()

        elif factor_name == "bollinger_position":
            rolling = prices.rolling(window=20)
            upper = rolling.mean() + 2 * rolling.std()
            lower = rolling.mean() - 2 * rolling.std()
            return (prices - lower) / (upper - lower)

        elif factor_name == "realized_volatility":
            returns = prices / prices.shift(1) - 1
            return returns.rolling(window=20).std()

        elif factor_name == "volume_anomaly":
            rolling_vol = volumes.rolling(window=20)
            return (volumes - rolling_vol.mean()) / rolling_vol.std()

        else:
            return None

    def _get_factor_category(self, factor_name: str) -> str:
        """获取因子类别"""
        momentum_factors = ["momentum", "ema_trend", "macd_momentum", "multi_period",
                           "momentum_acceleration", "gap_momentum", "intraday_momentum"]
        mean_reversion_factors = ["zscore", "bollinger", "short_term_reversal",
                                 "rsi_reversion", "ma_convergence", "price_percentile",
                                 "channel_breakout_reversion"]
        volatility_factors = ["realized_volatility", "atr_normalized", "volatility_breakout",
                              "volatility_change", "volatility_term_structure", "iv_premium",
                              "volatility_correlation", "jump_volatility"]
        volume_factors = ["volume_anomaly", "volume_momentum", "price_volume_trend",
                         "volume_ratio", "volume_position", "volume_concentration",
                         "volume_divergence"]

        for cat in momentum_factors:
            if cat in factor_name:
                return "momentum"
        for cat in mean_reversion_factors:
            if cat in factor_name:
                return "mean_reversion"
        for cat in volatility_factors:
            if cat in factor_name:
                return "volatility"
        for cat in volume_factors:
            if cat in factor_name:
                return "volume"

        return "unknown"

    def calculate_multiple(self, df: pd.DataFrame,
                         factor_names: Optional[List[str]] = None) -> Dict[str, pd.Series]:
        """
        批量计算多个因子

        Args:
            df: K线数据 DataFrame
            factor_names: 因子名称列表，默认使用 default_factors

        Returns:
            因子字典 {factor_name: factor_series}
        """
        if factor_names is None:
            factor_names = self.default_factors

        if not factor_names:
            factor_names = self._available_factors[:10]  # 默认计算前10个因子

        results = {}
        for name in factor_names:
            result = self.calculate_factor(df, name)
            if result is not None:
                results[name] = result

        return results

    def add_factors_to_df(self, df: pd.DataFrame,
                        factor_names: Optional[List[str]] = None) -> pd.DataFrame:
        """
        将因子添加到 DataFrame 中

        Args:
            df: K线数据 DataFrame
            factor_names: 因子名称列表

        Returns:
            包含因子的 DataFrame
        """
        df = df.copy()
        factors = self.calculate_multiple(df, factor_names)

        for name, series in factors.items():
            df[f'factor_{name}'] = series

        return df

    def health_check(self) -> PluginHealthStatus:
        """健康检查"""
        status = super().health_check()
        status.metrics.update({
            "factors_available": len(self._available_factors),
            "cache_size": len(self._factor_cache),
            "cache_enabled": self.use_cache
        })
        return status
