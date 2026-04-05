"""
指标收集器
收集和暴露Prometheus格式的交易指标
"""

import time
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from collections import deque
from datetime import datetime
import threading

logger = logging.getLogger(__name__)


@dataclass
class TradingMetrics:
    """交易指标数据"""
    timestamp: float

    # 资金指标
    total_equity: float
    cash: float
    positions_value: float
    daily_pnl: float
    total_pnl: float

    # 交易指标
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float

    # 风险指标
    current_drawdown: float
    max_drawdown: float
    risk_score: float

    # 策略指标
    active_strategies: int
    strategy_weights: Dict[str, float]

    # 系统指标
    latency_ms: float
    orders_per_minute: int


class MetricsCollector:
    """
    指标收集器

    收集交易指标并提供Prometheus格式输出
    """

    def __init__(self, max_history: int = 10000):
        self.max_history = max_history

        # 指标历史
        self.equity_history: deque = deque(maxlen=max_history)
        self.pnl_history: deque = deque(maxlen=max_history)
        self.trade_history: deque = deque(maxlen=max_history)
        self.latency_history: deque = deque(maxlen=1000)

        # 当前状态
        self.current_metrics: Optional[TradingMetrics] = None
        self.start_time = time.time()

        # 统计
        self.total_orders = 0
        self.total_fills = 0
        self.errors_count = 0

        # 锁
        self._lock = threading.RLock()

        logger.info("[MetricsCollector] Initialized")

    def record_equity(self, equity: float, cash: float, positions_value: float):
        """记录权益"""
        with self._lock:
            self.equity_history.append({
                'timestamp': time.time(),
                'equity': equity,
                'cash': cash,
                'positions_value': positions_value
            })

    def record_trade(self, symbol: str, side: str, quantity: float,
                     price: float, pnl: float = 0.0):
        """记录交易"""
        with self._lock:
            self.trade_history.append({
                'timestamp': time.time(),
                'symbol': symbol,
                'side': side,
                'quantity': quantity,
                'price': price,
                'pnl': pnl
            })
            self.total_fills += 1

    def record_order(self, symbol: str, side: str, quantity: float):
        """记录订单"""
        with self._lock:
            self.total_orders += 1

    def record_latency(self, latency_ms: float):
        """记录延迟"""
        with self._lock:
            self.latency_history.append({
                'timestamp': time.time(),
                'latency_ms': latency_ms
            })

    def record_error(self, error_type: str, message: str):
        """记录错误"""
        with self._lock:
            self.errors_count += 1
            logger.error(f"[Metrics] Error: {error_type} - {message}")

    def update_metrics(self, metrics: TradingMetrics):
        """更新完整指标"""
        with self._lock:
            self.current_metrics = metrics
            self.equity_history.append({
                'timestamp': metrics.timestamp,
                'equity': metrics.total_equity,
                'cash': metrics.cash,
                'positions_value': metrics.positions_value
            })

    def get_prometheus_metrics(self) -> str:
        """
        获取Prometheus格式的指标

        Returns:
            Prometheus格式的字符串
        """
        with self._lock:
            lines = []

            # 帮助信息
            lines.append("# HELP trading_equity Total equity in USD")
            lines.append("# TYPE trading_equity gauge")

            lines.append("# HELP trading_cash Available cash in USD")
            lines.append("# TYPE trading_cash gauge")

            lines.append("# HELP trading_positions_value Total positions value in USD")
            lines.append("# TYPE trading_positions_value gauge")

            lines.append("# HELP trading_daily_pnl Daily P&L in USD")
            lines.append("# TYPE trading_daily_pnl gauge")

            lines.append("# HELP trading_total_pnl Total P&L in USD")
            lines.append("# TYPE trading_total_pnl gauge")

            lines.append("# HELP trading_drawdown Current drawdown percentage")
            lines.append("# TYPE trading_drawdown gauge")

            lines.append("# HELP trading_total_trades Total number of trades")
            lines.append("# TYPE trading_total_trades counter")

            lines.append("# HELP trading_win_rate Win rate percentage")
            lines.append("# TYPE trading_win_rate gauge")

            lines.append("# HELP trading_latency_ms Order latency in milliseconds")
            lines.append("# TYPE trading_latency_ms histogram")

            lines.append("# HELP trading_errors_total Total number of errors")
            lines.append("# TYPE trading_errors_total counter")

            lines.append("# HELP trading_uptime_seconds System uptime in seconds")
            lines.append("# TYPE trading_uptime_seconds counter")

            # 指标值
            if self.current_metrics:
                m = self.current_metrics
                lines.append(f'trading_equity{{symbol="total"}} {m.total_equity}')
                lines.append(f'trading_cash{{symbol="total"}} {m.cash}')
                lines.append(f'trading_positions_value{{symbol="total"}} {m.positions_value}')
                lines.append(f'trading_daily_pnl{{symbol="total"}} {m.daily_pnl}')
                lines.append(f'trading_total_pnl{{symbol="total"}} {m.total_pnl}')
                lines.append(f'trading_drawdown{{symbol="total"}} {m.current_drawdown}')
                lines.append(f'trading_total_trades{{symbol="total"}} {m.total_trades}')
                lines.append(f'trading_win_rate{{symbol="total"}} {m.win_rate}')
                lines.append(f'trading_risk_score{{symbol="total"}} {m.risk_score}')
                lines.append(f'trading_active_strategies{{symbol="total"}} {m.active_strategies}')

            # 延迟直方图
            if self.latency_history:
                latencies = [l['latency_ms'] for l in self.latency_history]
                lines.append(f'trading_latency_ms_bucket{{le="10"}} {sum(1 for l in latencies if l <= 10)}')
                lines.append(f'trading_latency_ms_bucket{{le="50"}} {sum(1 for l in latencies if l <= 50)}')
                lines.append(f'trading_latency_ms_bucket{{le="100"}} {sum(1 for l in latencies if l <= 100)}')
                lines.append(f'trading_latency_ms_bucket{{le="500"}} {sum(1 for l in latencies if l <= 500)}')
                lines.append(f'trading_latency_ms_bucket{{le="+Inf"}} {len(latencies)}')
                lines.append(f'trading_latency_ms_sum {sum(latencies)}')
                lines.append(f'trading_latency_ms_count {len(latencies)}')

            # 错误计数
            lines.append(f'trading_errors_total {self.errors_count}')

            # 运行时间
            uptime = time.time() - self.start_time
            lines.append(f'trading_uptime_seconds {uptime}')

            return '\n'.join(lines)

    def get_current_stats(self) -> Dict[str, Any]:
        """获取当前统计"""
        with self._lock:
            stats = {
                'uptime_seconds': time.time() - self.start_time,
                'total_orders': self.total_orders,
                'total_fills': self.total_fills,
                'errors_count': self.errors_count,
                'equity_history_length': len(self.equity_history),
                'trade_history_length': len(self.trade_history),
            }

            if self.current_metrics:
                stats['current_metrics'] = {
                    'total_equity': self.current_metrics.total_equity,
                    'daily_pnl': self.current_metrics.daily_pnl,
                    'win_rate': self.current_metrics.win_rate,
                    'risk_score': self.current_metrics.risk_score
                }

            # 计算平均延迟
            if self.latency_history:
                latencies = [l['latency_ms'] for l in self.latency_history]
                stats['avg_latency_ms'] = sum(latencies) / len(latencies)
                stats['max_latency_ms'] = max(latencies)

            return stats

    def get_equity_curve(self) -> List[Dict]:
        """获取权益曲线"""
        with self._lock:
            return list(self.equity_history)

    def get_recent_trades(self, n: int = 10) -> List[Dict]:
        """获取最近交易"""
        with self._lock:
            return list(self.trade_history)[-n:]

    def reset(self):
        """重置所有指标"""
        with self._lock:
            self.equity_history.clear()
            self.pnl_history.clear()
            self.trade_history.clear()
            self.latency_history.clear()
            self.current_metrics = None
            self.total_orders = 0
            self.total_fills = 0
            self.errors_count = 0
            self.start_time = time.time()
            logger.info("[MetricsCollector] Reset")


# 全局指标收集器实例
_global_collector: Optional[MetricsCollector] = None


def get_global_collector() -> MetricsCollector:
    """获取全局指标收集器"""
    global _global_collector
    if _global_collector is None:
        _global_collector = MetricsCollector()
    return _global_collector
