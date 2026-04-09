"""
本地交易模块

支持:
1. 本地数据源 (CSV/SQLite/PostgreSQL)
2. 离线回测
3. 模拟交易执行
4. 本地投资组合管理
5. 性能分析
"""

from .local_trader import LocalTrader, LocalTradingConfig, BacktestResult
from .data_source import (
    LocalDataSource, CSVDataSource, SQLiteDataSource,
    SyntheticDataSource, DataFrameDataSource
)
from .execution_engine import LocalExecutionEngine, ExecutionResult
from .portfolio import LocalPortfolio, Position, TradeRecord

__all__ = [
    'LocalTrader',
    'LocalTradingConfig',
    'BacktestResult',
    'LocalDataSource',
    'CSVDataSource',
    'SQLiteDataSource',
    'SyntheticDataSource',
    'DataFrameDataSource',
    'LocalExecutionEngine',
    'ExecutionResult',
    'LocalPortfolio',
    'Position',
    'TradeRecord'
]
