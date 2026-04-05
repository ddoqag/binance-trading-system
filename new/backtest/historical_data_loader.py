"""
历史数据加载器
支持多种数据源: CSV文件、PostgreSQL数据库、Binance API
"""

import os
import pandas as pd
import numpy as np
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class DataSource(Enum):
    """数据源类型"""
    CSV = "csv"
    POSTGRESQL = "postgresql"
    BINANCE_API = "binance_api"
    MEMORY = "memory"


@dataclass
class DataConfig:
    """数据配置"""
    source: DataSource = DataSource.CSV
    symbol: str = "BTCUSDT"
    timeframe: str = "1h"  # 1m, 5m, 15m, 1h, 4h, 1d
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    data_dir: str = "./data"
    # PostgreSQL配置
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "binance"
    db_user: str = "postgres"
    db_password: str = ""


class HistoricalDataLoader:
    """
    历史数据加载器

    统一接口加载历史K线数据
    """

    # 时间周期到分钟的映射
    TIMEFRAME_MINUTES = {
        '1m': 1,
        '3m': 3,
        '5m': 5,
        '15m': 15,
        '30m': 30,
        '1h': 60,
        '2h': 120,
        '4h': 240,
        '6h': 360,
        '8h': 480,
        '12h': 720,
        '1d': 1440,
        '3d': 4320,
        '1w': 10080
    }

    def __init__(self, config: Optional[DataConfig] = None):
        self.config = config or DataConfig()
        self._cache: Dict[str, pd.DataFrame] = {}

    def load_data(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> pd.DataFrame:
        """
        加载历史数据

        Returns:
            DataFrame with columns: [timestamp, open, high, low, close, volume]
        """
        symbol = symbol or self.config.symbol
        timeframe = timeframe or self.config.timeframe
        start_date = start_date or self.config.start_date
        end_date = end_date or self.config.end_date

        # 检查缓存
        cache_key = f"{symbol}_{timeframe}_{start_date}_{end_date}"
        if cache_key in self._cache:
            return self._cache[cache_key].copy()

        # 根据数据源加载
        if self.config.source == DataSource.CSV:
            df = self._load_from_csv(symbol, timeframe, start_date, end_date)
        elif self.config.source == DataSource.POSTGRESQL:
            df = self._load_from_postgresql(symbol, timeframe, start_date, end_date, limit)
        elif self.config.source == DataSource.BINANCE_API:
            df = self._load_from_binance_api(symbol, timeframe, start_date, end_date, limit)
        elif self.config.source == DataSource.MEMORY:
            df = self._generate_sample_data(symbol, timeframe, start_date, end_date)
        else:
            raise ValueError(f"Unknown data source: {self.config.source}")

        # 缓存结果
        self._cache[cache_key] = df.copy()

        return df

    def _load_from_csv(
        self,
        symbol: str,
        timeframe: str,
        start_date: Optional[datetime],
        end_date: Optional[datetime]
    ) -> pd.DataFrame:
        """从CSV文件加载数据"""
        filename = f"{symbol}_{timeframe}.csv"
        filepath = os.path.join(self.config.data_dir, filename)

        if not os.path.exists(filepath):
            # 尝试其他文件名格式
            alt_filename = f"{symbol.lower()}_{timeframe}.csv"
            filepath = os.path.join(self.config.data_dir, alt_filename)

        if not os.path.exists(filepath):
            logger.warning(f"CSV file not found: {filepath}, generating sample data")
            return self._generate_sample_data(symbol, timeframe, start_date, end_date)

        df = pd.read_csv(filepath)

        # 标准化列名
        df.columns = [c.lower().strip() for c in df.columns]

        # 解析时间戳
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        elif 'datetime' in df.columns:
            df['timestamp'] = pd.to_datetime(df['datetime'])
        elif 'time' in df.columns:
            df['timestamp'] = pd.to_datetime(df['time'], unit='ms')

        # 过滤日期范围
        if start_date:
            df = df[df['timestamp'] >= start_date]
        if end_date:
            df = df[df['timestamp'] <= end_date]

        return df

    def _load_from_postgresql(
        self,
        symbol: str,
        timeframe: str,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        limit: Optional[int] = None
    ) -> pd.DataFrame:
        """从PostgreSQL数据库加载数据"""
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor

            conn = psycopg2.connect(
                host=self.config.db_host,
                port=self.config.db_port,
                database=self.config.db_name,
                user=self.config.db_user,
                password=self.config.db_password
            )

            query = """
                SELECT
                    open_time as timestamp,
                    open,
                    high,
                    low,
                    close,
                    volume
                FROM klines
                WHERE symbol = %s AND interval = %s
            """

            params = [symbol, timeframe]

            if start_date:
                query += " AND open_time >= %s"
                params.append(start_date)
            if end_date:
                query += " AND open_time <= %s"
                params.append(end_date)

            query += " ORDER BY open_time ASC"

            if limit:
                query += f" LIMIT {limit}"

            df = pd.read_sql(query, conn, params=params)
            conn.close()

            # 转换时间戳
            df['timestamp'] = pd.to_datetime(df['timestamp'])

            return df

        except ImportError:
            logger.warning("psycopg2 not installed, falling back to sample data")
            return self._generate_sample_data(symbol, timeframe, start_date, end_date)
        except Exception as e:
            logger.error(f"Database error: {e}, falling back to sample data")
            return self._generate_sample_data(symbol, timeframe, start_date, end_date)

    def _load_from_binance_api(
        self,
        symbol: str,
        timeframe: str,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        limit: Optional[int] = None
    ) -> pd.DataFrame:
        """从Binance API加载数据"""
        try:
            import requests

            url = "https://api.binance.com/api/v3/klines"

            params = {
                'symbol': symbol.upper(),
                'interval': timeframe,
                'limit': min(limit or 1000, 1000)
            }

            if start_date:
                params['startTime'] = int(start_date.timestamp() * 1000)
            if end_date:
                params['endTime'] = int(end_date.timestamp() * 1000)

            response = requests.get(url, params=params, timeout=30)
            data = response.json()

            if not data or not isinstance(data, list):
                raise ValueError(f"Invalid API response: {data}")

            # 解析K线数据
            df = pd.DataFrame(data, columns=[
                'open_time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])

            # 转换类型
            df['timestamp'] = pd.to_datetime(df['open_time'], unit='ms')
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]

        except Exception as e:
            logger.error(f"API error: {e}, falling back to sample data")
            return self._generate_sample_data(symbol, timeframe, start_date, end_date)

    def _generate_sample_data(
        self,
        symbol: str,
        timeframe: str,
        start_date: Optional[datetime],
        end_date: Optional[datetime]
    ) -> pd.DataFrame:
        """生成样本数据用于测试"""
        logger.info(f"Generating sample data for {symbol} {timeframe}")

        # 默认时间范围
        if not end_date:
            end_date = datetime.now()
        if not start_date:
            days = 30
            start_date = end_date - timedelta(days=days)

        # 生成时间序列
        minutes = self.TIMEFRAME_MINUTES.get(timeframe, 60)
        periods = int((end_date - start_date).total_seconds() / (minutes * 60))
        periods = min(periods, 10000)  # 限制最大数量

        timestamps = pd.date_range(start=start_date, periods=periods, freq=f'{minutes}min')

        # 生成随机游走价格
        np.random.seed(42)
        returns = np.random.randn(periods) * 0.001
        prices = 50000 * np.exp(np.cumsum(returns))

        # 生成OHLCV
        df = pd.DataFrame({
            'timestamp': timestamps,
            'open': prices * (1 + np.random.randn(periods) * 0.001),
            'high': prices * (1 + np.abs(np.random.randn(periods) * 0.002)),
            'low': prices * (1 - np.abs(np.random.randn(periods) * 0.002)),
            'close': prices * (1 + np.random.randn(periods) * 0.001),
            'volume': np.random.rand(periods) * 100
        })

        return df

    def get_cache_info(self) -> Dict[str, Any]:
        """获取缓存信息"""
        return {
            'cached_items': len(self._cache),
            'cache_keys': list(self._cache.keys()),
            'total_rows': sum(len(df) for df in self._cache.values())
        }

    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()
        logger.info("Cache cleared")

    def resample_data(
        self,
        df: pd.DataFrame,
        target_timeframe: str
    ) -> pd.DataFrame:
        """
        重采样数据到不同时间周期

        Args:
            df: 原始数据
            target_timeframe: 目标时间周期

        Returns:
            重采样后的DataFrame
        """
        if df.empty:
            return df

        df = df.copy()
        df.set_index('timestamp', inplace=True)

        # 映射时间周期到pandas频率
        freq_map = {
            '1m': '1min', '3m': '3min', '5m': '5min', '15m': '15min',
            '30m': '30min', '1h': '1H', '2h': '2H', '4h': '4H',
            '6h': '6H', '8h': '8H', '12h': '12H', '1d': '1D'
        }

        freq = freq_map.get(target_timeframe, '1H')

        resampled = df.resample(freq).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()

        resampled.reset_index(inplace=True)
        return resampled
