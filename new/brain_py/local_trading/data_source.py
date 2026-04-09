"""
本地数据源模块

支持多种本地数据源:
- CSV文件
- SQLite数据库
- PostgreSQL数据库
- 内存数据 (DataFrame)
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Iterator, Union
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


@dataclass
class TickData:
    """Tick数据"""
    timestamp: datetime
    symbol: str
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float
    mid_price: float
    spread_bps: float
    volume: float = 0.0

    @classmethod
    def from_ohlcv(cls, timestamp: datetime, symbol: str,
                   open_p: float, high: float, low: float, close: float,
                   volume: float = 0.0) -> 'TickData':
        """从OHLCV数据创建Tick"""
        mid = (high + low) / 2
        spread = (high - low) / mid * 10000 if mid > 0 else 0

        return cls(
            timestamp=timestamp,
            symbol=symbol,
            bid_price=low,
            bid_qty=volume * 0.1,
            ask_price=high,
            ask_qty=volume * 0.1,
            mid_price=mid,
            spread_bps=spread,
            volume=volume
        )


class LocalDataSource:
    """本地数据源基类"""

    def __init__(self, symbol: str = "BTCUSDT"):
        self.symbol = symbol
        self.data: Optional[pd.DataFrame] = None

    def load(self, start_date: Optional[datetime] = None,
             end_date: Optional[datetime] = None) -> pd.DataFrame:
        """加载数据"""
        raise NotImplementedError

    def get_ticks(self) -> List[TickData]:
        """获取tick列表"""
        if self.data is None:
            self.load()

        ticks = []
        for idx, row in self.data.iterrows():
            tick = TickData.from_ohlcv(
                timestamp=idx if isinstance(idx, datetime) else pd.to_datetime(idx),
                symbol=self.symbol,
                open_p=row.get('open', row.get('Open', 0)),
                high=row.get('high', row.get('High', 0)),
                low=row.get('low', row.get('Low', 0)),
                close=row.get('close', row.get('Close', 0)),
                volume=row.get('volume', row.get('Volume', 0))
            )
            ticks.append(tick)
        return ticks

    def iter_ticks(self) -> Iterator[TickData]:
        """迭代tick数据"""
        if self.data is None:
            self.load()

        for idx, row in self.data.iterrows():
            yield TickData.from_ohlcv(
                timestamp=idx if isinstance(idx, datetime) else pd.to_datetime(idx),
                symbol=self.symbol,
                open_p=row.get('open', row.get('Open', 0)),
                high=row.get('high', row.get('High', 0)),
                low=row.get('low', row.get('Low', 0)),
                close=row.get('close', row.get('Close', 0)),
                volume=row.get('volume', row.get('Volume', 0))
            )


class CSVDataSource(LocalDataSource):
    """CSV文件数据源"""

    def __init__(self, filepath: str, symbol: str = "BTCUSDT",
                 timestamp_col: str = 'timestamp',
                 date_format: Optional[str] = None):
        super().__init__(symbol)
        self.filepath = Path(filepath)
        self.timestamp_col = timestamp_col
        self.date_format = date_format

    def load(self, start_date: Optional[datetime] = None,
             end_date: Optional[datetime] = None) -> pd.DataFrame:
        """从CSV加载数据"""
        if not self.filepath.exists():
            raise FileNotFoundError(f"文件不存在: {self.filepath}")

        logger.info(f"从CSV加载数据: {self.filepath}")

        # 读取CSV
        df = pd.read_csv(self.filepath)

        # 解析时间戳
        if self.timestamp_col in df.columns:
            if self.date_format:
                df[self.timestamp_col] = pd.to_datetime(df[self.timestamp_col],
                                                        format=self.date_format)
            else:
                df[self.timestamp_col] = pd.to_datetime(df[self.timestamp_col])
            df.set_index(self.timestamp_col, inplace=True)

        # 时间过滤
        if start_date:
            df = df[df.index >= start_date]
        if end_date:
            df = df[df.index <= end_date]

        self.data = df.sort_index()
        logger.info(f"加载了 {len(df)} 条记录")
        return self.data


class SQLiteDataSource(LocalDataSource):
    """SQLite数据库数据源"""

    def __init__(self, db_path: str, table_name: str = "klines",
                 symbol: str = "BTCUSDT"):
        super().__init__(symbol)
        self.db_path = db_path
        self.table_name = table_name

    def load(self, start_date: Optional[datetime] = None,
             end_date: Optional[datetime] = None) -> pd.DataFrame:
        """从SQLite加载数据"""
        import sqlite3

        conn = sqlite3.connect(self.db_path)

        query = f"SELECT * FROM {self.table_name} WHERE symbol = ?"
        params = [self.symbol]

        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND timestamp <= ?"
            params.append(end_date.isoformat())

        query += " ORDER BY timestamp"

        df = pd.read_sql_query(query, conn, params=params)
        conn.close()

        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)

        self.data = df
        logger.info(f"从SQLite加载了 {len(df)} 条记录")
        return self.data


class PostgreSQLDataSource(LocalDataSource):
    """PostgreSQL数据源"""

    def __init__(self, host: str = "localhost", port: int = 5432,
                 database: str = "binance", user: str = "postgres",
                 password: str = "", table_name: str = "klines_1m",
                 symbol: str = "BTCUSDT"):
        super().__init__(symbol)
        self.conn_params = {
            'host': host,
            'port': port,
            'database': database,
            'user': user,
            'password': password
        }
        self.table_name = table_name

    def load(self, start_date: Optional[datetime] = None,
             end_date: Optional[datetime] = None) -> pd.DataFrame:
        """从PostgreSQL加载数据"""
        try:
            import psycopg2
        except ImportError:
            logger.error("psycopg2未安装，请运行: pip install psycopg2-binary")
            raise

        conn = psycopg2.connect(**self.conn_params)

        query = f"""
        SELECT open_time as timestamp, open, high, low, close, volume
        FROM {self.table_name}
        WHERE symbol = %s
        """
        params = [self.symbol]

        if start_date:
            query += " AND open_time >= %s"
            params.append(start_date)
        if end_date:
            query += " AND open_time <= %s"
            params.append(end_date)

        query += " ORDER BY open_time"

        df = pd.read_sql_query(query, conn, params=params)
        conn.close()

        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)

        self.data = df
        logger.info(f"从PostgreSQL加载了 {len(df)} 条记录")
        return self.data


class SyntheticDataSource(LocalDataSource):
    """合成数据生成器（用于测试）"""

    def __init__(self, symbol: str = "BTCUSDT", n_ticks: int = 1000,
                 base_price: float = 50000.0, volatility: float = 0.001):
        super().__init__(symbol)
        self.n_ticks = n_ticks
        self.base_price = base_price
        self.volatility = volatility

    def load(self, start_date: Optional[datetime] = None,
             end_date: Optional[datetime] = None) -> pd.DataFrame:
        """生成合成数据"""
        logger.info(f"生成合成数据: {self.n_ticks} ticks")

        # 生成随机游走价格
        returns = np.random.randn(self.n_ticks) * self.volatility
        prices = self.base_price * np.exp(np.cumsum(returns))

        # 生成OHLCV
        data = []
        start = start_date or datetime.now() - timedelta(hours=self.n_ticks)

        for i, price in enumerate(prices):
            timestamp = start + timedelta(minutes=i)
            spread = price * np.random.uniform(0.0001, 0.0008)  # 1-8 bps

            data.append({
                'timestamp': timestamp,
                'open': price * (1 + np.random.randn() * 0.0001),
                'high': price + spread/2,
                'low': price - spread/2,
                'close': price * (1 + np.random.randn() * 0.0001),
                'volume': np.random.uniform(1, 10)
            })

        df = pd.DataFrame(data)
        df.set_index('timestamp', inplace=True)

        self.data = df
        return self.data


class DataFrameDataSource(LocalDataSource):
    """内存DataFrame数据源（用于Alpha Tribunal）"""

    def __init__(self, df: pd.DataFrame, symbol: str = "BTCUSDT"):
        super().__init__(symbol)
        self.source_df = df.copy()

    def load(self, start_date: Optional[datetime] = None,
             end_date: Optional[datetime] = None) -> pd.DataFrame:
        """从DataFrame加载数据"""
        logger.info(f"从DataFrame加载数据: {len(self.source_df)} 行")

        df = self.source_df.copy()

        # 确保时间索引
        if not isinstance(df.index, pd.DatetimeIndex):
            # 尝试找到时间列
            time_cols = ['timestamp', 'open_time', 'date', 'datetime']
            for col in time_cols:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col])
                    df.set_index(col, inplace=True)
                    break

        # 时间过滤
        if start_date:
            df = df[df.index >= start_date]
        if end_date:
            df = df[df.index <= end_date]

        self.data = df.sort_index()
        logger.info(f"加载了 {len(self.data)} 条记录")
        return self.data


# 测试代码
if __name__ == "__main__":
    print("=" * 60)
    print("本地数据源测试")
    print("=" * 60)

    # 测试合成数据源
    print("\n1. 合成数据源测试")
    synth = SyntheticDataSource(n_ticks=100)
    ticks = synth.get_ticks()
    print(f"生成了 {len(ticks)} 个tick")
    print(f"价格范围: ${ticks[0].mid_price:.2f} - ${ticks[-1].mid_price:.2f}")

    # 测试CSV数据源（如果存在）
    print("\n2. CSV数据源测试")
    try:
        csv_source = CSVDataSource("../data/btcusdt_1h.csv")
        if csv_source.filepath.exists():
            ticks = csv_source.get_ticks()
            print(f"从CSV加载了 {len(ticks)} 个tick")
        else:
            print("测试CSV文件不存在，跳过")
    except Exception as e:
        print(f"CSV测试失败: {e}")

    print("\n" + "=" * 60)
    print("测试完成")
