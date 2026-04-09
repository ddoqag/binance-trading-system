"""
从PostgreSQL数据库获取历史数据
用于本地回测
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class BinanceDataFetcher:
    """
    Binance历史数据获取器

    从PostgreSQL数据库获取klines数据
    """

    def __init__(self,
                 host: str = 'localhost',
                 port: int = 5432,
                 database: str = 'binance',
                 user: str = 'postgres',
                 password: str = '362232'):
        """
        初始化数据获取器

        Args:
            host: 数据库主机
            port: 数据库端口
            database: 数据库名
            user: 用户名
            password: 密码
        """
        self.connection_params = {
            'host': host,
            'port': port,
            'database': database,
            'user': user,
            'password': password
        }

    def _get_connection(self):
        """获取数据库连接"""
        import psycopg2
        return psycopg2.connect(**self.connection_params)

    def fetch_klines(self,
                    symbol: str = 'BTCUSDT',
                    interval: str = '1m',
                    start_time: Optional[datetime] = None,
                    end_time: Optional[datetime] = None,
                    limit: int = 1000) -> pd.DataFrame:
        """
        获取K线数据

        Args:
            symbol: 交易对，如 'BTCUSDT'
            interval: 时间周期，如 '1m', '5m', '1h'
            start_time: 开始时间
            end_time: 结束时间
            limit: 最大返回条数

        Returns:
            pd.DataFrame: OHLCV数据
        """
        conn = self._get_connection()

        try:
            # 构建查询
            query = f"""
                SELECT
                    open_time as timestamp,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    quote_volume
                FROM klines
                WHERE symbol = '{symbol}'
                AND interval = '{interval}'
            """

            if start_time:
                query += f" AND open_time >= '{start_time}'"
            if end_time:
                query += f" AND open_time <= '{end_time}'"

            query += f" ORDER BY open_time ASC LIMIT {limit}"

            logger.info(f"Fetching klines: {symbol} {interval}")
            df = pd.read_sql(query, conn)

            if len(df) == 0:
                logger.warning(f"No data found for {symbol} {interval}")
                return pd.DataFrame()

            # 转换时间戳
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)

            # 转换价格为float
            for col in ['open', 'high', 'low', 'close']:
                if col in df.columns:
                    df[col] = df[col].astype(float)

            # 转换volume
            if 'volume' in df.columns:
                df['volume'] = df['volume'].astype(float)

            logger.info(f"Fetched {len(df)} rows")
            return df

        finally:
            conn.close()

    def fetch_recent_data(self,
                         symbol: str = 'BTCUSDT',
                         interval: str = '1m',
                         hours: int = 24) -> pd.DataFrame:
        """
        获取最近的数据

        Args:
            symbol: 交易对
            interval: 时间周期
            hours: 最近多少小时

        Returns:
            pd.DataFrame
        """
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours)

        return self.fetch_klines(
            symbol=symbol,
            interval=interval,
            start_time=start_time,
            end_time=end_time
        )

    def convert_to_tick_format(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        将K线数据转换为tick格式

        为回测引擎生成模拟的bid/ask价格
        """
        if len(df) == 0:
            return pd.DataFrame()

        # 基于OHLC生成模拟的orderbook价格
        df['mid_price'] = (df['high'] + df['low']) / 2

        # 假设点差为high-low的10%
        spread = (df['high'] - df['low']) * 0.1
        spread = spread.clip(lower=0.01)  # 最小点差

        df['bid_price'] = df['mid_price'] - spread / 2
        df['ask_price'] = df['mid_price'] + spread / 2

        # 添加spread bps
        df['spread_bps'] = (spread / df['mid_price']) * 10000

        # 添加模拟的队列位置（随机）
        df['queue_position'] = np.random.uniform(0, 1, len(df))

        return df

    def get_available_symbols(self) -> list:
        """获取可用的交易对列表"""
        conn = self._get_connection()

        try:
            query = "SELECT DISTINCT symbol FROM klines ORDER BY symbol"
            df = pd.read_sql(query, conn)
            return df['symbol'].tolist()
        finally:
            conn.close()

    def get_data_summary(self, symbol: str = 'BTCUSDT') -> dict:
        """获取数据摘要"""
        conn = self._get_connection()

        try:
            query = f"""
                SELECT
                    MIN(open_time) as start_time,
                    MAX(open_time) as end_time,
                    COUNT(*) as total_rows,
                    COUNT(DISTINCT interval) as intervals
                FROM klines
                WHERE symbol = '{symbol}'
            """
            df = pd.read_sql(query, conn)

            if len(df) == 0:
                return {}

            row = df.iloc[0]
            return {
                'symbol': symbol,
                'start_time': row['start_time'],
                'end_time': row['end_time'],
                'total_rows': row['total_rows'],
                'intervals': row['intervals']
            }
        finally:
            conn.close()


def test_data_fetcher():
    """测试数据获取器"""
    print("=" * 70)
    print("Binance Data Fetcher Test")
    print("=" * 70)

    fetcher = BinanceDataFetcher()

    # 测试连接
    print("\nTesting database connection...")
    try:
        symbols = fetcher.get_available_symbols()
        print(f"Available symbols: {len(symbols)}")
        if symbols:
            print(f"First 5: {symbols[:5]}")
    except Exception as e:
        print(f"Error: {e}")
        return

    # 获取数据摘要
    print("\nFetching data summary for BTCUSDT...")
    try:
        summary = fetcher.get_data_summary('BTCUSDT')
        for key, value in summary.items():
            print(f"  {key}: {value}")
    except Exception as e:
        print(f"Error: {e}")

    # 获取最近数据
    print("\nFetching recent 1-hour data...")
    try:
        df = fetcher.fetch_recent_data('BTCUSDT', '1m', hours=1)
        print(f"Fetched {len(df)} rows")

        if len(df) > 0:
            print(f"\nData sample:")
            print(df.head(3))

            # 转换为tick格式
            tick_df = fetcher.convert_to_tick_format(df)
            print(f"\nTick format sample:")
            print(tick_df[['bid_price', 'ask_price', 'spread_bps']].head(3))

    except Exception as e:
        print(f"Error: {e}")

    print("\n" + "=" * 70)
    print("Test complete!")
    print("=" * 70)


if __name__ == "__main__":
    test_data_fetcher()
