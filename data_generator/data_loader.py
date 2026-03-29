"""
数据下载器和加载器
机构级Binance数据获取模块
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
from functools import lru_cache

import pandas as pd
import numpy as np

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

try:
    from data_generator.db_loader import DatabaseLoader, DatabaseConfig
    HAS_DB_LOADER = True
except ImportError:
    HAS_DB_LOADER = False

class BinanceDataLoader:
    """币安数据加载器"""

    def __init__(self, config=None):
        """
        初始化币安数据加载器

        Args:
            config: 配置对象
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Initialize database loader if available
        if HAS_DB_LOADER:
            try:
                db_config = DatabaseConfig()
                self.db_loader = DatabaseLoader(db_config)
                self.logger.info("Database loader initialized")
            except Exception as e:
                self.logger.warning(f"Failed to initialize database loader: {e}")
                self.db_loader = None
        else:
            self.logger.warning("Database loader module not available")
            self.db_loader = None

    def load_data_from_csv(self, file_path: str) -> pd.DataFrame:
        """
        从CSV文件加载数据

        Args:
            file_path: CSV文件路径

        Returns:
            DataFrame: 加载的数据
        """
        try:
            self.logger.info(f"从文件 {file_path} 加载数据")
            df = pd.read_csv(file_path)

            # 确保必要的列存在
            required_columns = ['open', 'high', 'low', 'close', 'volume']
            for col in required_columns:
                if col not in df.columns:
                    raise ValueError(f"缺少必要的列: {col}")

            # 确保时间列存在
            time_columns = ['timestamp', 'time', 'open_time', 'openTime']
            found_time_col = None
            for col in time_columns:
                if col in df.columns:
                    found_time_col = col
                    break

            if found_time_col is None:
                raise ValueError(f"缺少时间列，需要其中之一: {time_columns}")

            df = df.set_index(found_time_col)

            self.logger.info(f"数据加载完成，共 {len(df)} 条记录")
            return df

        except Exception as e:
            self.logger.error(f"从CSV文件加载数据失败: {e}")
            raise

    def load_multiple_files(self, file_paths: List[str]) -> pd.DataFrame:
        """
        加载多个CSV文件并合并

        Args:
            file_paths: 文件路径列表

        Returns:
            DataFrame: 合并后的数据
        """
        dataframes = []
        for file_path in file_paths:
            try:
                df = self.load_data_from_csv(file_path)
                dataframes.append(df)
            except Exception as e:
                self.logger.error(f"加载文件 {file_path} 失败: {e}")

        if not dataframes:
            raise ValueError("没有成功加载任何数据文件")

        # 合并并去重
        combined_df = pd.concat(dataframes)
        combined_df = combined_df[~combined_df.index.duplicated(keep='first')]
        combined_df = combined_df.sort_index()

        self.logger.info(f"合并后共 {len(combined_df)} 条记录")
        return combined_df

    def load_from_database(
        self,
        symbol: str,
        interval: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: Optional[int] = None
    ) -> pd.DataFrame:
        """
        从数据库加载数据

        Args:
            symbol: 交易对符号（如"BTCUSDT"）
            interval: 时间周期（如"1h"、"5m"）
            start_time: 开始时间（ISO格式或"YYYY-MM-DD"）
            end_time: 结束时间（ISO格式或"YYYY-MM-DD"）
            limit: 最大返回记录数

        Returns:
            DataFrame: OHLCV数据
        """
        if self.db_loader is None:
            self.logger.error("Database loader not initialized")
            return pd.DataFrame()

        self.logger.info(f"Loading {symbol} {interval} from database...")
        df = self.db_loader.load_klines(
            symbol=symbol,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
            limit=limit
        )

        if not df.empty:
            self.logger.info(f"Successfully loaded {len(df)} records from database")
        else:
            self.logger.warning(f"No data found for {symbol} {interval} in database")

        return df

    def get_available_symbols_from_db(self) -> List[str]:
        """
        从数据库获取可用的交易对列表

        Returns:
            交易对列表
        """
        if self.db_loader is None:
            return []

        return self.db_loader.load_available_symbols()

    def get_available_intervals_from_db(self, symbol: str) -> List[str]:
        """
        从数据库获取指定交易对的可用时间周期

        Args:
            symbol: 交易对符号

        Returns:
            时间周期列表
        """
        if self.db_loader is None:
            return []

        return self.db_loader.load_available_intervals(symbol)

    def filter_by_price(self, df: pd.DataFrame, min_price: float, max_price: float) -> pd.DataFrame:
        """
        按价格范围过滤数据

        Args:
            df: 输入DataFrame
            min_price: 最低价格
            max_price: 最高价格

        Returns:
            DataFrame: 过滤后的DataFrame
        """
        initial_count = len(df)
        df_filtered = df[
            (df['close'] >= min_price) &
            (df['close'] <= max_price)
        ].copy()

        removed = initial_count - len(df_filtered)
        if removed > 0:
            self.logger.warning(f"移除了 {removed} 条价格异常记录")

        return df_filtered

    def create_combined_dataframe(self, base_dir: str, symbols: List[str] = None) -> Dict[str, pd.DataFrame]:
        """
        从目录加载所有可用数据并创建组合DataFrame

        Args:
            base_dir: 基础目录
            symbols: 符号列表

        Returns:
            Dict: 符号到DataFrame的映射
        """
        if symbols is None:
            symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT']

        data_dir = Path(base_dir)
        if not data_dir.exists():
            raise FileNotFoundError(f"数据目录不存在: {data_dir}")

        result = {}
        for symbol in symbols:
            # 查找符号的所有数据文件
            pattern = f"{symbol}-*.csv"
            files = list(data_dir.glob(pattern))

            if not files:
                self.logger.warning(f"未找到 {symbol} 的数据文件")
                continue

            try:
                df = self.load_multiple_files([str(f) for f in sorted(files)])
                result[symbol] = df
            except Exception as e:
                self.logger.error(f"处理 {symbol} 数据失败: {e}")

        return result

def test_data_loader():
    """测试数据加载器"""
    logging.basicConfig(level=logging.INFO)

    from config import DataGeneratorConfig
    config = DataGeneratorConfig()

    loader = BinanceDataLoader(config)

    # 测试加载示例数据
    data_dir = Path(__file__).parent.parent / "data"
    if data_dir.exists():
        btc_files = list(data_dir.glob("BTCUSDT-*.csv"))
        if btc_files:
            df = loader.load_data_from_csv(str(btc_files[0]))
            print(f"加载成功: {len(df)} 条记录")
            print(df.head())
        else:
            print("未找到BTC数据文件")
    else:
        print("数据目录不存在")

if __name__ == "__main__":
    test_data_loader()
