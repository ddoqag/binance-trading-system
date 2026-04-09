"""
MVP历史数据连接器

连接真实历史数据源：
1. PostgreSQL数据库
2. CSV文件
3. 币安API历史数据
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_PG = True
except ImportError:
    HAS_PG = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from mvp_backtest import TickData


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('MVPDataConnector')


@dataclass
class DataSourceConfig:
    """数据源配置"""
    # PostgreSQL配置
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_database: str = "binance"
    pg_user: str = "postgres"
    pg_password: str = ""

    # CSV配置
    csv_path: str = "./data"

    # 币安API配置
    use_testnet: bool = True


class HistoricalDataConnector:
    """
    历史数据连接器

    统一接口连接多种数据源
    """

    def __init__(self, config: Optional[DataSourceConfig] = None):
        self.config = config or DataSourceConfig()
        self.pg_conn = None

    def _get_pg_connection(self):
        """获取PostgreSQL连接"""
        if not HAS_PG:
            raise ImportError("psycopg2 not installed")

        if self.pg_conn is None:
            self.pg_conn = psycopg2.connect(
                host=self.config.pg_host,
                port=self.config.pg_port,
                database=self.config.pg_database,
                user=self.config.pg_user,
                password=self.config.pg_password
            )
        return self.pg_conn

    def load_from_postgresql(self,
                            symbol: str,
                            start_date: str,
                            end_date: str,
                            interval: str = "1m") -> List[TickData]:
        """
        从PostgreSQL加载K线数据

        Args:
            symbol: 交易对 (如 BTCUSDT)
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            interval: 时间间隔 (1m, 5m, 1h, 1d)

        Returns:
            List[TickData]
        """
        conn = self._get_pg_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        table_map = {
            "1m": "klines_1m",
            "5m": "klines_5m",
            "15m": "klines_15m",
            "1h": "klines_1h",
            "4h": "klines_4h",
            "1d": "klines_1d"
        }
        table = table_map.get(interval, "klines_1m")

        query = f"""
        SELECT open_time, open, high, low, close, volume,
               quote_asset_volume, number_of_trades
        FROM {table}
        WHERE symbol = %s
          AND open_time BETWEEN %s AND %s
        ORDER BY open_time ASC
        """

        try:
            cursor.execute(query, (symbol, start_date, end_date))
            rows = cursor.fetchall()

            ticks = []
            for row in rows:
                # 从K线生成模拟tick
                mid = (row['high'] + row['low']) / 2
                spread = (row['high'] - row['low']) / mid * 10000  # bps

                tick = TickData(
                    timestamp=row['open_time'].timestamp(),
                    symbol=symbol,
                    bid_price=row['low'],
                    bid_qty=row['volume'] * 0.1,
                    ask_price=row['high'],
                    ask_qty=row['volume'] * 0.1,
                    mid_price=mid,
                    spread_bps=spread,
                    volume_24h=row['quote_asset_volume']
                )
                ticks.append(tick)

            logger.info(f"Loaded {len(ticks)} ticks from PostgreSQL")
            return ticks

        except Exception as e:
            logger.error(f"Error loading from PostgreSQL: {e}")
            return []

        finally:
            cursor.close()

    def load_from_csv(self,
                     symbol: str,
                     filepath: str) -> List[TickData]:
        """
        从CSV加载数据

        期望列：timestamp, open, high, low, close, volume
        """
        try:
            df = pd.read_csv(filepath)

            # 转换时间戳
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            elif 'open_time' in df.columns:
                df['timestamp'] = pd.to_datetime(df['open_time'])

            ticks = []
            for _, row in df.iterrows():
                mid = (row['high'] + row['low']) / 2
                spread = (row['high'] - row['low']) / mid * 10000 if mid > 0 else 0

                tick = TickData(
                    timestamp=row['timestamp'].timestamp() if hasattr(row['timestamp'], 'timestamp') else row['timestamp'],
                    symbol=symbol,
                    bid_price=row['low'],
                    bid_qty=row.get('volume', 1.0) * 0.1,
                    ask_price=row['high'],
                    ask_qty=row.get('volume', 1.0) * 0.1,
                    mid_price=mid,
                    spread_bps=spread,
                    volume_24h=row.get('quote_volume', row.get('volume', 0))
                )
                ticks.append(tick)

            logger.info(f"Loaded {len(ticks)} ticks from CSV: {filepath}")
            return ticks

        except Exception as e:
            logger.error(f"Error loading from CSV: {e}")
            return []

    def fetch_from_binance(self,
                          symbol: str,
                          start_date: str,
                          end_date: str,
                          interval: str = "1m") -> List[TickData]:
        """
        从币安API获取历史数据

        Args:
            symbol: 交易对
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            interval: K线间隔

        Returns:
            List[TickData]
        """
        if not HAS_REQUESTS:
            raise ImportError("requests not installed")

        base_url = "https://testnet.binance.vision/api/v3/klines" if self.config.use_testnet else "https://api.binance.com/api/v3/klines"

        # 转换日期到毫秒时间戳
        start_ts = int(pd.Timestamp(start_date).timestamp() * 1000)
        end_ts = int(pd.Timestamp(end_date).timestamp() * 1000)

        all_ticks = []
        limit = 1000

        while start_ts < end_ts:
            params = {
                "symbol": symbol,
                "interval": interval,
                "startTime": start_ts,
                "endTime": min(start_ts + limit * 60 * 1000, end_ts),  # 粗略估计
                "limit": limit
            }

            try:
                response = requests.get(base_url, params=params, timeout=30)
                data = response.json()

                if not data:
                    break

                for candle in data:
                    # Binance Kline格式：[open_time, open, high, low, close, volume, close_time, quote_volume, trades, ...]
                    open_time = candle[0] / 1000  # 转换为秒
                    open_price = float(candle[1])
                    high = float(candle[2])
                    low = float(candle[3])
                    close = float(candle[4])
                    volume = float(candle[5])
                    quote_volume = float(candle[7])
                    trades = int(candle[8])

                    mid = (high + low) / 2
                    spread = (high - low) / mid * 10000 if mid > 0 else 0

                    tick = TickData(
                        timestamp=open_time,
                        symbol=symbol,
                        bid_price=low,
                        bid_qty=volume * 0.1,
                        ask_price=high,
                        ask_qty=volume * 0.1,
                        mid_price=mid,
                        spread_bps=spread,
                        volume_24h=quote_volume
                    )
                    all_ticks.append(tick)

                # 更新开始时间
                start_ts = data[-1][6] + 1  # close_time + 1

                logger.info(f"Fetched {len(data)} candles, total: {len(all_ticks)}")

            except Exception as e:
                logger.error(f"Error fetching from Binance: {e}")
                break

        logger.info(f"Total fetched: {len(all_ticks)} ticks from Binance API")
        return all_ticks

    def load_orderbook_data(self,
                           filepath: str,
                           symbol: str = "BTCUSDT") -> List[TickData]:
        """
        从订单簿快照加载数据

        期望列：timestamp, bid_price, bid_qty, ask_price, ask_qty
        """
        try:
            df = pd.read_csv(filepath)

            ticks = []
            for _, row in df.iterrows():
                bid = row.get('bid_price', row.get('bids_0_price', 0))
                ask = row.get('ask_price', row.get('asks_0_price', 0))
                mid = (bid + ask) / 2 if bid > 0 and ask > 0 else row.get('mid_price', 0)
                spread_bps = ((ask - bid) / mid * 10000) if mid > 0 else 0

                tick = TickData(
                    timestamp=row.get('timestamp', row.get('event_time', 0)),
                    symbol=symbol,
                    bid_price=bid,
                    bid_qty=row.get('bid_qty', row.get('bids_0_qty', 1.0)),
                    ask_price=ask,
                    ask_qty=row.get('ask_qty', row.get('asks_0_qty', 1.0)),
                    mid_price=mid,
                    spread_bps=spread_bps
                )
                ticks.append(tick)

            logger.info(f"Loaded {len(ticks)} orderbook ticks from {filepath}")
            return ticks

        except Exception as e:
            logger.error(f"Error loading orderbook data: {e}")
            return []

    def close(self):
        """关闭连接"""
        if self.pg_conn:
            self.pg_conn.close()
            self.pg_conn = None


class DataValidator:
    """
    数据验证器

    验证历史数据的质量和完整性
    """

    def __init__(self):
        self.issues: List[str] = []

    def validate(self, ticks: List[TickData]) -> bool:
        """
        验证数据质量

        Returns:
            bool: 是否通过验证
        """
        self.issues = []

        if not ticks:
            self.issues.append("No data")
            return False

        # 检查数量
        if len(ticks) < 100:
            self.issues.append(f"Too few ticks: {len(ticks)}")

        # 检查时间连续性
        timestamps = [t.timestamp for t in ticks]
        time_diffs = np.diff(timestamps)
        avg_interval = np.mean(time_diffs)
        max_gap = np.max(time_diffs)

        if max_gap > avg_interval * 10:
            self.issues.append(f"Large time gap detected: {max_gap:.1f}s")

        # 检查价格合理性
        prices = [t.mid_price for t in ticks]
        if any(p <= 0 for p in prices):
            self.issues.append("Invalid prices (<= 0)")

        price_changes = np.diff(prices) / np.array(prices[:-1])
        if np.max(np.abs(price_changes)) > 0.1:  # 10%单tick变化
            self.issues.append("Extreme price movement detected")

        # 检查点差
        spreads = [t.spread_bps for t in ticks]
        if np.mean(spreads) > 100:  # 平均点差 > 100bps
            self.issues.append("Abnormally wide spreads")

        # 检查缺失值
        for i, tick in enumerate(ticks):
            if tick.bid_price <= 0 or tick.ask_price <= 0:
                self.issues.append(f"Invalid bid/ask at tick {i}")
                break

        return len(self.issues) == 0

    def get_report(self) -> Dict:
        """获取验证报告"""
        return {
            'valid': len(self.issues) == 0,
            'issues': self.issues,
            'issue_count': len(self.issues)
        }


# 测试代码
if __name__ == "__main__":
    print("=" * 70)
    print("MVP Data Connector Test")
    print("=" * 70)

    # 创建连接器
    config = DataSourceConfig()
    connector = HistoricalDataConnector(config)

    # 生成合成数据用于测试
    print("\n生成合成测试数据...")
    from mvp_backtest import HistoricalDataLoader

    loader = HistoricalDataLoader()
    ticks = loader.generate_synthetic_data(n_ticks=1000)

    # 验证数据
    print("\n验证数据质量...")
    validator = DataValidator()
    is_valid = validator.validate(ticks)
    report = validator.get_report()

    print(f"验证结果: {'通过' if is_valid else '未通过'}")
    if report['issues']:
        print(f"问题: {report['issues']}")

    print(f"\n数据概览:")
    print(f"  Tick数量: {len(ticks)}")
    print(f"  价格范围: ${ticks[0].mid_price:.2f} - ${ticks[-1].mid_price:.2f}")
    print(f"  平均点差: {np.mean([t.spread_bps for t in ticks]):.2f} bps")

    # 尝试连接PostgreSQL（如果有配置）
    if HAS_PG and config.pg_password:
        print("\n尝试连接PostgreSQL...")
        try:
            ticks_pg = connector.load_from_postgresql(
                symbol="BTCUSDT",
                start_date="2024-01-01",
                end_date="2024-01-02",
                interval="1h"
            )
            print(f"从PostgreSQL加载了 {len(ticks_pg)} ticks")
        except Exception as e:
            print(f"PostgreSQL连接失败: {e}")
    else:
        print("\n跳过PostgreSQL测试（未配置）")

    print("\n" + "=" * 70)
    print("测试完成")
