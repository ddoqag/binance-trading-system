"""
Database Loader - Load data from PostgreSQL
数据库加载器 - 从 PostgreSQL 加载数据
"""

import os
import sys
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
import pandas as pd
from dataclasses import dataclass

# Add project path
sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)


@dataclass
class DatabaseConfig:
    """Database configuration"""
    host: str = "localhost"
    port: int = 5432
    database: str = "binance"
    user: str = "postgres"
    password: str = ""


class DatabaseLoader:
    """Database Loader - Load market data from PostgreSQL"""

    def __init__(self, config: Optional[DatabaseConfig] = None):
        """
        Initialize database loader

        Args:
            config: Database configuration
        """
        if config is None:
            self.config = self._load_config_from_env()
        else:
            self.config = config

        self.conn = None
        self.logger = logging.getLogger(__name__)

    def _load_config_from_env(self) -> DatabaseConfig:
        """Load database configuration from environment variables"""
        return DatabaseConfig(
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", 5432)),
            database=os.environ.get("DB_NAME", "binance"),
            user=os.environ.get("DB_USER", "postgres"),
            password=os.environ.get("DB_PASSWORD", "")
        )

    def connect(self):
        """Connect to PostgreSQL database"""
        try:
            import psycopg2

            self.logger.info(f"Connecting to PostgreSQL: {self.config.host}:{self.config.port}/{self.config.database}")
            self.conn = psycopg2.connect(
                host=self.config.host,
                port=self.config.port,
                database=self.config.database,
                user=self.config.user,
                password=self.config.password
            )
            self.logger.info("Database connection established successfully")
            return True

        except ImportError:
            self.logger.error("psycopg2 not installed, cannot load from database")
            self.logger.info("Please install: pip install psycopg2-binary")
            return False

        except Exception as e:
            self.logger.error(f"Database connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from database"""
        if self.conn is not None:
            self.conn.close()
            self.conn = None
            self.logger.info("Database disconnected")

    def load_klines(
        self,
        symbol: str,
        interval: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Load K-line (candle) data from database

        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")
            interval: Time interval (e.g., "1h", "5m")
            start_time: Start time (ISO format or "YYYY-MM-DD")
            end_time: End time (ISO format or "YYYY-MM-DD")
            limit: Maximum number of records to return

        Returns:
            DataFrame with OHLCV data
        """
        if self.conn is None:
            if not self.connect():
                raise Exception("Database connection failed")

        # Build query
        query = """
            SELECT open_time, open, high, low, close, volume,
                   close_time, quote_volume, trades,
                   taker_buy_base_volume, taker_buy_quote_volume,
                   data_source, is_complete
            FROM klines
            WHERE symbol = %s AND interval = %s
        """
        params = [symbol, interval]

        if start_time:
            query += " AND open_time >= %s"
            params.append(start_time)

        if end_time:
            query += " AND open_time <= %s"
            params.append(end_time)

        query += " ORDER BY open_time ASC"

        if limit:
            query += " LIMIT %s"
            params.append(limit)

        try:
            self.logger.info(f"Loading {symbol} {interval} data from database...")
            df = pd.read_sql_query(query, self.conn, params=tuple(params))

            if not df.empty:
                # Set index
                df = df.set_index("open_time")

                # Rename columns to match expected format
                column_rename = {
                    "open_time": "openTime",
                    "close_time": "closeTime",
                    "quote_volume": "quoteVolume",
                    "taker_buy_base_volume": "takerBuyBaseVolume",
                    "taker_buy_quote_volume": "takerBuyQuoteVolume",
                    "data_source": "dataSource",
                    "is_complete": "isComplete"
                }
                df = df.rename(columns=column_rename)

                self.logger.info(f"Successfully loaded {len(df)} records")
                return df

            else:
                self.logger.warning(f"No data found for {symbol} {interval}")
                return pd.DataFrame()

        except Exception as e:
            self.logger.error(f"Error loading data from database: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return pd.DataFrame()

    def load_available_symbols(self) -> List[str]:
        """Load list of available symbols from database"""
        if self.conn is None:
            if not self.connect():
                return []

        try:
            query = "SELECT DISTINCT symbol FROM klines ORDER BY symbol"
            df = pd.read_sql_query(query, self.conn)
            symbols = df["symbol"].tolist()
            self.logger.info(f"Found {len(symbols)} symbols in database")
            return symbols

        except Exception as e:
            self.logger.error(f"Error loading symbols: {e}")
            return []

    def load_available_intervals(self, symbol: str) -> List[str]:
        """Load list of available intervals for a symbol"""
        if self.conn is None:
            if not self.connect():
                return []

        try:
            query = "SELECT DISTINCT interval FROM klines WHERE symbol = %s ORDER BY interval"
            df = pd.read_sql_query(query, self.conn, params=(symbol,))
            intervals = df["interval"].tolist()
            self.logger.info(f"Found {len(intervals)} intervals for {symbol}")
            return intervals

        except Exception as e:
            self.logger.error(f"Error loading intervals: {e}")
            return []

    def get_data_statistics(self, symbol: str, interval: str) -> Dict[str, Any]:
        """Get statistics about available data"""
        if self.conn is None:
            if not self.connect():
                return {}

        try:
            query = """
                SELECT COUNT(*) as record_count,
                       MIN(open_time) as earliest_time,
                       MAX(open_time) as latest_time,
                       MIN(close) as min_price,
                       MAX(close) as max_price,
                       AVG(volume) as avg_volume
                FROM klines
                WHERE symbol = %s AND interval = %s
            """
            df = pd.read_sql_query(query, self.conn, params=(symbol, interval))

            if not df.empty:
                stats = df.iloc[0].to_dict()
                self.logger.info(f"Data statistics for {symbol} {interval}:")
                self.logger.info(f"  Records: {stats['record_count']}")
                self.logger.info(f"  Date range: {stats['earliest_time']} to {stats['latest_time']}")
                self.logger.info(f"  Price range: ${stats['min_price']:.2f} - ${stats['max_price']:.2f}")
                return stats

            return {}

        except Exception as e:
            self.logger.error(f"Error loading statistics: {e}")
            return {}

    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()


def test_db_loader():
    """Test database loader"""
    logging.basicConfig(level=logging.INFO)

    # Try to load config from environment or use default
    loader = DatabaseLoader()

    try:
        if loader.connect():
            # Get available symbols
            symbols = loader.load_available_symbols()
            print(f"Available symbols: {symbols}")

            if symbols:
                # Get available intervals for first symbol
                symbol = symbols[0]
                intervals = loader.load_available_intervals(symbol)
                print(f"\nAvailable intervals for {symbol}: {intervals}")

                if intervals:
                    # Load data
                    interval = intervals[0] if "1h" in intervals else intervals[0]
                    df = loader.load_klines(
                        symbol=symbol,
                        interval=interval,
                        limit=100
                    )

                    if not df.empty:
                        print(f"\nLoaded data shape: {df.shape}")
                        print(f"Columns: {list(df.columns)}")
                        print("\nFirst 5 records:")
                        print(df.head())

                        # Get statistics
                        stats = loader.get_data_statistics(symbol, interval)
                        print(f"\nStatistics: {stats}")

        loader.disconnect()

    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")


if __name__ == "__main__":
    test_db_loader()
