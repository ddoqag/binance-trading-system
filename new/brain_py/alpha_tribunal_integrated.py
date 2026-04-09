"""
Alpha审判系统 - 本地交易模块集成版本

将Alpha审判系统与本地交易模块连接，实现真实的回测评估
"""

import sys
sys.path.insert(0, '.')

import numpy as np
import pandas as pd
from typing import Dict, List, Callable
from datetime import datetime
import json
import logging

from alpha_tribunal import AlphaTribunal, TribunalVerdict, FinalVerdict
from local_trading import LocalTrader, LocalTradingConfig
from local_trading.data_source import SyntheticDataSource

logger = logging.getLogger(__name__)


class AlphaTribunalIntegrated(AlphaTribunal):
    """
    集成本地交易模块的Alpha审判系统

    使用实际的回测引擎评估策略，而非简化模拟
    """

    def __init__(self,
                 strategy_params_factory: Callable,
                 data: pd.DataFrame,
                 initial_capital: float = 10000.0,
                 random_seed: int = 42):
        """
        初始化集成审判系统

        Args:
            strategy_params_factory: 策略参数工厂函数，接收参数返回配置字典
            data: 市场数据DataFrame
            initial_capital: 初始资金
            random_seed: 随机种子
        """
        self.strategy_params_factory = strategy_params_factory
        self.data = data.copy()
        self.initial_capital = initial_capital
        self.random_seed = random_seed

        np.random.seed(random_seed)

        self.verdicts: List[TribunalVerdict] = []
        self.final_verdict: FinalVerdict = None

        # 将数据转换为tick格式
        self.tick_data = self._convert_to_ticks(data)

        logger.info(f"AlphaTribunalIntegrated initialized: {len(data)} rows, "
                   f"{len(self.tick_data)} ticks, capital=${initial_capital}")

    def _convert_to_ticks(self, data: pd.DataFrame) -> List[Dict]:
        """将DataFrame转换为tick数据列表"""
        ticks = []

        for idx, row in data.iterrows():
            tick = {
                'timestamp': idx,
                'bid_price': row.get('bid_price', row.get('low', row.get('close', 50000))),
                'ask_price': row.get('ask_price', row.get('high', row.get('close', 50000))),
                'bid_qty': row.get('bid_qty', 1.0),
                'ask_qty': row.get('ask_qty', 1.0),
                'mid_price': row.get('mid_price', row.get('close', 50000)),
                'volume': row.get('volume', 0.0)
            }
            ticks.append(tick)

        return ticks

    def _evaluate_strategy(self,
                          data: pd.DataFrame,
                          params: Dict) -> Dict:
        """
        使用本地交易模块评估策略表现

        这是核心集成点：使用真实的回测引擎
        """
        try:
            # 创建本地交易配置
            config = LocalTradingConfig(
                symbol='BTCUSDT',
                initial_capital=self.initial_capital,
                max_position=params.get('max_position', 0.1),
                queue_target_ratio=params.get('queue_target_ratio', 0.2),
                toxic_threshold=params.get('toxic_threshold', 0.35),
                min_spread_ticks=params.get('min_spread_ticks', 3),
                maker_fee=0.0002,
                taker_fee=0.0005
            )

            # 创建本地交易者
            trader = LocalTrader(config)

            # 准备数据源
            from local_trading.data_source import SyntheticDataSource

            # 使用数据子集
            n_ticks = min(len(data), len(self.tick_data))
            start_idx = np.random.randint(0, max(1, len(self.tick_data) - n_ticks))
            tick_subset = self.tick_data[start_idx:start_idx + n_ticks]

            # 创建数据源
            data_source = SyntheticDataSource(n_ticks=len(tick_subset))
            data_source.ticks = tick_subset
            data_source.data = pd.DataFrame(tick_subset)

            trader.set_data_source(data_source)

            # 加载数据
            if not trader.load_data():
                return self._empty_result()

            # 运行回测
            result = trader.run_backtest(progress_interval=None)  # 静默模式

            # 转换为标准格式
            return {
                'sharpe': result.sharpe_ratio if hasattr(result, 'sharpe_ratio') else 0.0,
                'total_return': result.total_return_pct if hasattr(result, 'total_return_pct') else 0.0,
                'max_drawdown': result.max_drawdown_pct if hasattr(result, 'max_drawdown_pct') else 0.0,
                'win_rate': result.win_rate if hasattr(result, 'win_rate') else 0.0,
                'n_trades': result.total_trades if hasattr(result, 'total_trades') else 0,
                'total_trades': result.total_trades if hasattr(result, 'total_trades') else 0,
                'total_pnl': result.total_pnl if hasattr(result, 'total_pnl') else 0.0,
                'avg_pnl_per_trade': result.avg_pnl_per_trade if hasattr(result, 'avg_pnl_per_trade') else 0.0
            }

        except Exception as e:
            logger.error(f"Error evaluating strategy: {e}")
            return self._empty_result()

    def _empty_result(self) -> Dict:
        """返回空结果"""
        return {
            'sharpe': 0.0,
            'total_return': 0.0,
            'max_drawdown': 0.0,
            'win_rate': 0.0,
            'n_trades': 0,
            'total_trades': 0,
            'total_pnl': 0.0,
            'avg_pnl_per_trade': 0.0
        }


def create_mvp_params_factory():
    """创建MVP策略参数工厂"""
    def factory(**params):
        """返回MVP策略配置"""
        return {
            'queue_target_ratio': params.get('queue_target_ratio', 0.2),
            'toxic_threshold': params.get('toxic_threshold', 0.35),
            'min_spread_ticks': params.get('min_spread_ticks', 3),
            'max_position': 0.1,
            'initial_capital': params.get('initial_capital', 1000.0)
        }
    return factory


def run_integrated_tribunal():
    """运行集成版本的Alpha审判"""
    print("\n" + "=" * 70)
    print("         Alpha Tribunal - Integrated with Local Trading")
    print("=" * 70)

    # 准备数据
    print("\nPreparing test data...")
    np.random.seed(42)
    n_ticks = 1000

    # 使用合成数据源
    data_source = SyntheticDataSource(n_ticks=n_ticks)
    ticks = data_source.get_ticks()

    # 转换为DataFrame
    data = pd.DataFrame([{
        'timestamp': t.timestamp,
        'bid_price': t.bid_price,
        'ask_price': t.ask_price,
        'mid_price': t.mid_price,
        'spread': t.spread_bps,
        'bid_qty': t.bid_qty,
        'ask_qty': t.ask_qty,
        'volume': t.volume
    } for t in ticks])
    data.set_index('timestamp', inplace=True)

    print(f"  Data: {len(data)} ticks")
    print(f"  Price range: ${data['bid_price'].min():.2f} - ${data['ask_price'].max():.2f}")

    # 创建参数工厂
    params_factory = create_mvp_params_factory()

    # 创建审判系统
    tribunal = AlphaTribunalIntegrated(
        strategy_params_factory=params_factory,
        data=data,
        initial_capital=1000.0,
        random_seed=42
    )

    # 运行所有测试
    verdict = tribunal.run_all_tests(verbose=True)

    # 保存报告
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = f'alpha_tribunal_integrated_{timestamp}.json'
    tribunal.save_report(report_path)

    print(f"\nReport saved: {report_path}")

    return tribunal, verdict


if __name__ == "__main__":
    # 运行集成测试
    tribunal, verdict = run_integrated_tribunal()

    print("\n" + "=" * 70)
    print("Integrated Tribunal Test Complete")
    print("=" * 70)
