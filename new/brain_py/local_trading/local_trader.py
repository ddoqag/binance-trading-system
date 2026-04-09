"""
本地交易主模块

整合:
- 本地数据源
- MVP交易策略
- 本地执行引擎
- 投资组合管理
- 性能分析
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import json
import logging

# 导入MVP模块
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mvp import SimpleQueueOptimizer, ToxicFlowDetector, SpreadCapture
from mvp_trader import MVPTrader

from .data_source import LocalDataSource, SyntheticDataSource, CSVDataSource
from .execution_engine import LocalExecutionEngine, ExecutionResult
from .portfolio import LocalPortfolio


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('LocalTrader')


@dataclass
class LocalTradingConfig:
    """本地交易配置"""
    # 资金配置
    initial_capital: float = 1000.0
    max_position: float = 0.1  # 最大仓位10%

    # MVP参数
    queue_target_ratio: float = 0.2
    toxic_threshold: float = 0.35
    min_spread_ticks: int = 3

    # 交易对
    symbol: str = "BTCUSDT"

    # 手续费
    maker_fee: float = 0.0002
    taker_fee: float = 0.0005

    # 数据源
    data_source_type: str = "synthetic"  # 'synthetic', 'csv', 'sqlite', 'postgresql'
    data_source_path: Optional[str] = None

    # 回测参数
    start_date: Optional[str] = None
    end_date: Optional[str] = None


@dataclass
class BacktestResult:
    """回测结果"""
    config: LocalTradingConfig
    start_time: datetime
    end_time: datetime
    duration_seconds: float

    # 盈亏
    initial_capital: float
    final_capital: float
    total_return: float
    total_return_pct: float

    # 交易统计
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float

    # 风险指标
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    volatility: float

    # 详细数据
    equity_curve: pd.DataFrame
    trades_df: pd.DataFrame
    statistics: Dict


class LocalTrader:
    """
    本地交易主类

    支持:
    - 离线回测
    - 模拟交易
    - 性能分析
    """

    def __init__(self, config: Optional[LocalTradingConfig] = None):
        self.config = config or LocalTradingConfig()

        # 初始化MVP Trader
        self.mvp = MVPTrader(
            symbol=self.config.symbol,
            initial_capital=self.config.initial_capital,
            max_position=self.config.max_position
        )

        # 设置MVP参数
        self.mvp.queue_optimizer.target_queue_ratio = self.config.queue_target_ratio
        self.mvp.toxic_detector.threshold = self.config.toxic_threshold
        self.mvp.spread_capture.min_spread_ticks = self.config.min_spread_ticks

        # 本地执行引擎
        self.execution_engine = LocalExecutionEngine(
            maker_fee=self.config.maker_fee,
            taker_fee=self.config.taker_fee
        )

        # 投资组合
        self.portfolio = LocalPortfolio(
            initial_capital=self.config.initial_capital
        )

        # 数据源
        self.data_source: Optional[LocalDataSource] = None

        # 记录
        self.trade_history: List[Dict] = []

        logger.info(f"LocalTrader initialized: {self.config.symbol}")

    def set_data_source(self, data_source: LocalDataSource):
        """设置数据源"""
        self.data_source = data_source

    def load_data(self, **kwargs):
        """加载数据"""
        if self.data_source is None:
            # 根据配置创建数据源
            if self.config.data_source_type == "synthetic":
                self.data_source = SyntheticDataSource(
                    symbol=self.config.symbol,
                    n_ticks=kwargs.get('n_ticks', 1000)
                )
            elif self.config.data_source_type == "csv":
                if not self.config.data_source_path:
                    raise ValueError("CSV数据源需要指定路径")
                self.data_source = CSVDataSource(
                    filepath=self.config.data_source_path,
                    symbol=self.config.symbol
                )
            else:
                raise ValueError(f"不支持的数据源类型: {self.config.data_source_type}")

        # 加载数据
        self.data_source.load(
            start_date=kwargs.get('start_date'),
            end_date=kwargs.get('end_date')
        )

    def run_backtest(self, progress_interval: int = 100) -> BacktestResult:
        """
        运行回测

        Args:
            progress_interval: 进度报告间隔

        Returns:
            BacktestResult
        """
        if self.data_source is None or self.data_source.data is None:
            raise ValueError("请先加载数据")

        start_time = datetime.now()
        logger.info(f"开始回测: {len(self.data_source.data)} ticks")

        # 遍历所有tick
        for i, tick in enumerate(self.data_source.iter_ticks()):
            # 更新投资组合价格
            self.portfolio.update(tick.timestamp, tick.mid_price)

            # 转换订单簿格式
            orderbook = {
                'bids': [
                    {'price': tick.bid_price, 'qty': tick.bid_qty},
                    {'price': tick.bid_price * 0.999, 'qty': 1.0}
                ],
                'asks': [
                    {'price': tick.ask_price, 'qty': tick.ask_qty},
                    {'price': tick.ask_price * 1.001, 'qty': 1.0}
                ]
            }

            # MVP决策
            order = self.mvp.process_tick(orderbook)

            if order:
                # 执行订单
                result = self.execution_engine.execute_limit_order(
                    side=order['side'],
                    qty=order['qty'],
                    price=order['price'],
                    tick=tick,
                    queue_position=0.3
                )

                if result.success:
                    # 更新MVP状态
                    fill_event = {
                        'order_id': result.order_id,
                        'side': order['side'],
                        'qty': result.filled_qty,
                        'order_price': order['price'],
                        'fill_price': result.filled_price,
                        'bid_price': tick.bid_price,
                        'ask_price': tick.ask_price,
                        'fee': result.fee,
                        'market_price_after': tick.mid_price
                    }
                    self.mvp.on_fill(fill_event)

                    # 更新投资组合
                    pnl_comp = self.mvp.pnl_attributor.get_cumulative_report().get('components', {})
                    self.portfolio.execute_trade(
                        symbol=self.config.symbol,
                        side=order['side'],
                        qty=result.filled_qty,
                        price=result.filled_price,
                        fee=result.fee,
                        timestamp=tick.timestamp,
                        pnl_components={k: v.get('value', 0) for k, v in pnl_comp.items()}
                    )

                    # 记录
                    self.trade_history.append({
                        'timestamp': tick.timestamp,
                        'side': order['side'],
                        'qty': result.filled_qty,
                        'price': result.filled_price,
                        'pnl': self.portfolio.get_total_equity(tick.mid_price)
                    })

            # 进度报告
            if (i + 1) % progress_interval == 0:
                equity = self.portfolio.get_total_equity(tick.mid_price)
                pnl = equity - self.config.initial_capital
                logger.info(f"Progress: {(i+1)/len(self.data_source.data)*100:.1f}% | "
                           f"PnL: ${pnl:.2f} | Trades: {len(self.portfolio.trades)}")

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        logger.info(f"回测完成，用时 {duration:.1f} 秒")

        return self._generate_result(start_time, end_time, duration)

    def _generate_result(self, start: datetime, end: datetime, duration: float) -> BacktestResult:
        """生成回测结果"""
        stats = self.portfolio.get_statistics()

        # 计算最大回撤
        equity_df = self.portfolio.get_equity_curve_df()
        if not equity_df.empty:
            equity_df['peak'] = equity_df['equity'].cummax()
            equity_df['drawdown'] = equity_df['equity'] - equity_df['peak']
            equity_df['drawdown_pct'] = equity_df['drawdown'] / equity_df['peak']

            max_drawdown = equity_df['drawdown'].min()
            max_drawdown_pct = equity_df['drawdown_pct'].min()

            # 计算夏普比率
            returns = equity_df['equity'].pct_change().dropna()
            if len(returns) > 1 and returns.std() > 0:
                sharpe = (returns.mean() / returns.std()) * np.sqrt(252 * 24 * 60)
                volatility = returns.std() * np.sqrt(252 * 24 * 60)
            else:
                sharpe = 0
                volatility = 0
        else:
            max_drawdown = 0
            max_drawdown_pct = 0
            sharpe = 0
            volatility = 0

        final_equity = self.portfolio.get_total_equity()
        total_return = final_equity - self.config.initial_capital
        total_return_pct = total_return / self.config.initial_capital

        # 创建交易DataFrame
        trades_df = pd.DataFrame([
            {
                'timestamp': t.timestamp,
                'symbol': t.symbol,
                'side': t.side,
                'qty': t.qty,
                'price': t.price,
                'fee': t.fee,
                'pnl': t.pnl
            }
            for t in self.portfolio.trades
        ])

        return BacktestResult(
            config=self.config,
            start_time=start,
            end_time=end,
            duration_seconds=duration,
            initial_capital=self.config.initial_capital,
            final_capital=final_equity,
            total_return=total_return,
            total_return_pct=total_return_pct,
            total_trades=stats['total_trades'],
            winning_trades=stats['winning_trades'],
            losing_trades=stats['losing_trades'],
            win_rate=stats['win_rate'],
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            sharpe_ratio=sharpe,
            volatility=volatility,
            equity_curve=equity_df if not equity_df.empty else pd.DataFrame(),
            trades_df=trades_df,
            statistics=stats
        )

    def save_results(self, filepath: str):
        """保存结果到文件"""
        result = {
            'config': {
                'symbol': self.config.symbol,
                'initial_capital': self.config.initial_capital,
                'max_position': self.config.max_position,
                'queue_target_ratio': self.config.queue_target_ratio,
                'toxic_threshold': self.config.toxic_threshold,
                'min_spread_ticks': self.config.min_spread_ticks
            },
            'portfolio_stats': self.portfolio.get_statistics(),
            'execution_stats': self.execution_engine.get_statistics()
        }

        with open(filepath, 'w') as f:
            json.dump(result, f, indent=2, default=str)

        logger.info(f"结果已保存: {filepath}")


def print_backtest_report(result: BacktestResult):
    """打印回测报告"""
    print("\n" + "=" * 70)
    print("本地回测报告")
    print("=" * 70)

    print(f"\n配置:")
    print(f"  交易对: {result.config.symbol}")
    print(f"  初始资金: ${result.config.initial_capital:.2f}")
    print(f"  MVP参数: queue={result.config.queue_target_ratio}, "
          f"toxic={result.config.toxic_threshold}, spread={result.config.min_spread_ticks}")

    print(f"\n时间:")
    print(f"  开始: {result.start_time}")
    print(f"  结束: {result.end_time}")
    print(f"  用时: {result.duration_seconds:.1f} 秒")

    print(f"\n盈亏:")
    print(f"  最终资金: ${result.final_capital:.2f}")
    print(f"  总收益: ${result.total_return:.2f} ({result.total_return_pct*100:.2f}%)")

    print(f"\n交易统计:")
    print(f"  总交易: {result.total_trades}")
    print(f"  盈利: {result.winning_trades}")
    print(f"  亏损: {result.losing_trades}")
    print(f"  胜率: {result.win_rate:.1%}")

    print(f"\n风险指标:")
    print(f"  最大回撤: ${result.max_drawdown:.2f} ({result.max_drawdown_pct*100:.2f}%)")
    print(f"  夏普比率: {result.sharpe_ratio:.2f}")
    print(f"  波动率: {result.volatility:.2f}")

    print("\n" + "=" * 70)


# 测试代码
if __name__ == "__main__":
    print("=" * 70)
    print("本地交易模块测试")
    print("=" * 70)

    # 配置
    config = LocalTradingConfig(
        symbol="BTCUSDT",
        initial_capital=1000.0,
        max_position=0.1,
        queue_target_ratio=0.2,
        toxic_threshold=0.35,
        min_spread_ticks=3
    )

    # 创建交易者
    trader = LocalTrader(config)

    # 使用合成数据
    trader.load_data(n_ticks=500)

    print(f"\n开始回测...")
    print(f"配置: {config}")

    # 运行回测
    result = trader.run_backtest(progress_interval=50)

    # 打印报告
    print_backtest_report(result)

    # 保存结果
    trader.save_results("local_backtest_result.json")

    print("\n测试完成!")
