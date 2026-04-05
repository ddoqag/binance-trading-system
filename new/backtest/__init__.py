"""
回测系统 - Phase 4 数据与回测

提供完整的历史数据回测框架:
- 历史数据加载器 (CSV/数据库/API)
- 回测引擎 (事件驱动)
- 性能分析器
- 纸上交易 (Paper Trading)
"""

from .historical_data_loader import HistoricalDataLoader, DataSource
from .backtest_engine import BacktestEngine, BacktestConfig, BacktestResult
from .performance_analyzer import PerformanceAnalyzer, TradeMetrics
from .paper_trading import PaperTradingEngine, PaperTradingConfig

__all__ = [
    'HistoricalDataLoader',
    'DataSource',
    'BacktestEngine',
    'BacktestConfig',
    'BacktestResult',
    'PerformanceAnalyzer',
    'TradeMetrics',
    'PaperTradingEngine',
    'PaperTradingConfig'
]
