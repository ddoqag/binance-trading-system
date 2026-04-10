"""
MarketMakerV1 参数网格搜索优化
测试关键参数组合，找到最优配置
"""
import time
import sys
import os
import json
import itertools
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Tuple, Any
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy.market_maker_v1 import MarketMakerV1, MarketState
from execution.client import ExecutorClient
import requests
import numpy as np


@dataclass
class ParameterSet:
    """参数组合。"""
    min_spread_ticks: int
    inventory_skew_factor: float
    base_order_size: float
    toxic_threshold: float = 0.6

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def __hash__(self):
        return hash((self.min_spread_ticks, self.inventory_skew_factor,
                    self.base_order_size, self.toxic_threshold))


@dataclass
class BacktestResult:
    """回测结果。"""
    params: ParameterSet
    total_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    total_trades: int
    fill_rate: float
    avg_trade_pnl: float
    final_position: float
    total_fees: float
    runtime_seconds: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            'params': self.params.to_dict(),
            'total_return_pct': self.total_return_pct,
            'sharpe_ratio': self.sharpe_ratio,
            'max_drawdown_pct': self.max_drawdown_pct,
            'total_trades': self.total_trades,
            'fill_rate': self.fill_rate,
            'avg_trade_pnl': self.avg_trade_pnl,
            'final_position': self.final_position,
            'total_fees': self.total_fees,
            'runtime_seconds': self.runtime_seconds
        }


class GridSearchOptimizer:
    """网格搜索优化器。"""

    def __init__(self, base_url: str = "http://localhost:8080",
                 symbol: str = "BTCUSDT",
                 duration_minutes: int = 10):
        self.base_url = base_url
        self.symbol = symbol
        self.duration_minutes = duration_minutes
        self.results: List[BacktestResult] = []

    def check_engine(self) -> bool:
        """检查引擎连接。"""
        try:
            resp = requests.get(f"{self.base_url}/api/v1/status", timeout=2.0)
            return resp.status_code == 200
        except:
            return False

    def reset_engine(self):
        """重置引擎状态。"""
        try:
            # 取消所有订单
            requests.post(f"{self.base_url}/api/v1/cancel_all", timeout=2.0)
            time.sleep(0.5)
        except:
            pass

    def run_single_backtest(self, params: ParameterSet) -> BacktestResult:
        """运行单组参数回测。"""
        start_time = time.time()

        # 重置引擎
        self.reset_engine()

        # 获取初始状态
        try:
            status_resp = requests.get(f"{self.base_url}/api/v1/status", timeout=2.0)
            status = status_resp.json()
            initial_value = status.get('total_value', 10000.0)
            initial_position = status.get('position', 0.0)
        except:
            initial_value = 10000.0
            initial_position = 0.0

        # 初始化策略
        client = ExecutorClient(base_url=self.base_url, timeout=2.0)
        strategy = MarketMakerV1(
            executor=client,
            symbol=self.symbol,
            max_position=0.02,
            base_order_size=params.base_order_size,
            min_spread_ticks=params.min_spread_ticks,
            tick_size=0.01,
            toxic_threshold=params.toxic_threshold,
            inventory_skew_factor=params.inventory_skew_factor
        )

        # 清空已有订单
        client.cancel_all_orders(self.symbol)
        time.sleep(0.5)

        # 运行回测
        end_time = time.time() + self.duration_minutes * 60
        tick_count = 0
        processed_fill_ids = set()
        value_history = [initial_value]
        peak_value = initial_value
        max_drawdown = 0.0

        try:
            while time.time() < end_time:
                tick_start = time.time()
                tick_count += 1

                # 获取市场数据
                try:
                    resp = requests.get(f"{self.base_url}/api/v1/market/book",
                                       params={"symbol": self.symbol}, timeout=1.0)
                    data = resp.json()
                    bid = float(data['bids'][0][0])
                    ask = float(data['asks'][0][0])
                    mid = (bid + ask) / 2

                    position_info = client.get_position(self.symbol)
                    current_position = float(position_info.get('position', 0.0))
                    current_cash = float(position_info.get('cash', 10000.0))
                    current_value = current_cash + current_position * mid

                    # 更新最大回撤
                    peak_value = max(peak_value, current_value)
                    drawdown = (peak_value - current_value) / peak_value * 100
                    max_drawdown = max(max_drawdown, drawdown)
                    value_history.append(current_value)

                    # 构建市场状态
                    market = MarketState(
                        timestamp=time.time(),
                        bid=bid, ask=ask,
                        bid_size=float(data['bids'][0][1]),
                        ask_size=float(data['asks'][0][1]),
                        last_price=float(data.get('last_price', mid)),
                        spread=ask - bid,
                        mid_price=mid,
                        toxic_score=0.0,
                        volatility=0.001,
                        trade_imbalance=0.0
                    )

                    # 策略处理
                    strategy.on_market_tick(market, position_info)

                    # 检查成交
                    try:
                        fills_resp = requests.get(f"{self.base_url}/api/v1/orders/filled",
                                                 params={"symbol": self.symbol}, timeout=0.5)
                        for fill in fills_resp.json().get('fills', []):
                            fill_id = fill.get('order_id', '')
                            if fill_id and fill_id not in processed_fill_ids:
                                strategy.on_fill(fill)
                                processed_fill_ids.add(fill_id)
                    except:
                        pass

                except Exception as e:
                    pass

                # 控制频率 (2Hz)
                elapsed = time.time() - tick_start
                sleep_time = max(0, 0.5 - elapsed)
                time.sleep(sleep_time)

        except KeyboardInterrupt:
            pass

        # 清理
        client.cancel_all_orders(self.symbol)

        # 计算结果
        final_value = value_history[-1] if value_history else initial_value
        total_return_pct = (final_value - initial_value) / initial_value * 100

        # 计算夏普比率（简化版）
        returns = []
        for i in range(1, len(value_history)):
            r = (value_history[i] - value_history[i-1]) / value_history[i-1]
            returns.append(r)

        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252 * 24 * 60 * 2)  # 年化
        else:
            sharpe = 0.0

        # 获取最终报告
        report = strategy.get_performance_report()

        runtime = time.time() - start_time

        return BacktestResult(
            params=params,
            total_return_pct=total_return_pct,
            sharpe_ratio=sharpe,
            max_drawdown_pct=max_drawdown,
            total_trades=report['orders_filled'],
            fill_rate=report['orders_filled'] / max(report['orders_placed'], 1) * 100,
            avg_trade_pnl=(final_value - initial_value) / max(report['orders_filled'], 1),
            final_position=report['current_position'],
            total_fees=report.get('total_fees', 0.0),
            runtime_seconds=runtime
        )

    def run_grid_search(self,
                       spread_ticks_range: List[int] = [2, 3, 4, 5],
                       skew_range: List[float] = [1.5, 2.0, 2.5, 3.0, 3.5],
                       order_size_range: List[float] = [0.0005, 0.001, 0.002],
                       toxic_range: List[float] = [0.5, 0.6, 0.7]) -> List[BacktestResult]:
        """运行网格搜索。"""
        print("=" * 70)
        print("MarketMakerV1 Parameter Grid Search")
        print("=" * 70)
        print(f"Search Space:")
        print(f"  min_spread_ticks: {spread_ticks_range}")
        print(f"  inventory_skew_factor: {skew_range}")
        print(f"  base_order_size: {order_size_range}")
        print(f"  toxic_threshold: {toxic_range}")
        print(f"Duration per test: {self.duration_minutes} minutes")
        print()

        # 检查引擎
        if not self.check_engine():
            print("[ERROR] Cannot connect to engine!")
            print("Make sure mock_go_engine_v2.py is running on port 8080")
            return []

        print("[OK] Engine connected")
        print()

        # 生成所有参数组合
        param_combinations = list(itertools.product(
            spread_ticks_range, skew_range, order_size_range, toxic_range
        ))

        total_tests = len(param_combinations)
        print(f"Total parameter combinations: {total_tests}")
        print(f"Estimated total time: {total_tests * self.duration_minutes} minutes")
        print()

        # 运行测试
        self.results = []
        for i, (spread, skew, size, toxic) in enumerate(param_combinations, 1):
            params = ParameterSet(
                min_spread_ticks=spread,
                inventory_skew_factor=skew,
                base_order_size=size,
                toxic_threshold=toxic
            )

            print(f"[{i}/{total_tests}] Testing: spread={spread}, skew={skew:.1f}, "
                  f"size={size}, toxic={toxic}")

            result = self.run_single_backtest(params)
            self.results.append(result)

            print(f"  Return: {result.total_return_pct:+.3f}% | "
                  f"Sharpe: {result.sharpe_ratio:+.3f} | "
                  f"Trades: {result.total_trades} | "
                  f"DD: {result.max_drawdown_pct:.2f}%")
            print()

        return self.results

    def get_best_params(self, metric: str = 'sharpe_ratio') -> BacktestResult:
        """获取最优参数。"""
        if not self.results:
            raise ValueError("No results available")

        # 过滤掉无效结果
        valid_results = [r for r in self.results if r.total_trades > 0]

        if not valid_results:
            raise ValueError("No valid results with trades")

        if metric == 'sharpe_ratio':
            return max(valid_results, key=lambda x: x.sharpe_ratio)
        elif metric == 'total_return_pct':
            return max(valid_results, key=lambda x: x.total_return_pct)
        elif metric == 'max_drawdown_pct':
            return min(valid_results, key=lambda x: x.max_drawdown_pct)
        else:
            raise ValueError(f"Unknown metric: {metric}")

    def analyze_results(self):
        """分析结果并打印报告。"""
        if not self.results:
            print("No results to analyze")
            return

        print("\n" + "=" * 70)
        print("GRID SEARCH ANALYSIS")
        print("=" * 70)

        # 按夏普比率排序
        sorted_by_sharpe = sorted(self.results, key=lambda x: x.sharpe_ratio, reverse=True)

        print("\nTop 5 by Sharpe Ratio:")
        print("-" * 70)
        print(f"{'Rank':<6} {'Spread':<8} {'Skew':<8} {'Size':<10} {'Toxic':<8} "
              f"{'Return':<10} {'Sharpe':<10} {'Trades':<8}")
        print("-" * 70)

        for i, r in enumerate(sorted_by_sharpe[:5], 1):
            p = r.params
            print(f"{i:<6} {p.min_spread_ticks:<8} {p.inventory_skew_factor:<8.1f} "
                  f"{p.base_order_size:<10.4f} {p.toxic_threshold:<8.1f} "
                  f"{r.total_return_pct:<10.3f} {r.sharpe_ratio:<10.3f} {r.total_trades:<8}")

        # 按收益排序
        sorted_by_return = sorted(self.results, key=lambda x: x.total_return_pct, reverse=True)

        print("\nTop 5 by Total Return:")
        print("-" * 70)
        print(f"{'Rank':<6} {'Spread':<8} {'Skew':<8} {'Size':<10} {'Toxic':<8} "
              f"{'Return':<10} {'Sharpe':<10} {'Trades':<8}")
        print("-" * 70)

        for i, r in enumerate(sorted_by_return[:5], 1):
            p = r.params
            print(f"{i:<6} {p.min_spread_ticks:<8} {p.inventory_skew_factor:<8.1f} "
                  f"{p.base_order_size:<10.4f} {p.toxic_threshold:<8.1f} "
                  f"{r.total_return_pct:<10.3f} {r.sharpe_ratio:<10.3f} {r.total_trades:<8}")

        # 最优参数
        best_sharpe = self.get_best_params('sharpe_ratio')
        best_return = self.get_best_params('total_return_pct')

        print("\n" + "=" * 70)
        print("OPTIMAL PARAMETERS")
        print("=" * 70)

        print("\nBest Sharpe Ratio:")
        p = best_sharpe.params
        print(f"  min_spread_ticks: {p.min_spread_ticks}")
        print(f"  inventory_skew_factor: {p.inventory_skew_factor}")
        print(f"  base_order_size: {p.base_order_size}")
        print(f"  toxic_threshold: {p.toxic_threshold}")
        print(f"  Performance: Sharpe={best_sharpe.sharpe_ratio:.3f}, "
              f"Return={best_sharpe.total_return_pct:.3f}%")

        print("\nBest Total Return:")
        p = best_return.params
        print(f"  min_spread_ticks: {p.min_spread_ticks}")
        print(f"  inventory_skew_factor: {p.inventory_skew_factor}")
        print(f"  base_order_size: {p.base_order_size}")
        print(f"  toxic_threshold: {p.toxic_threshold}")
        print(f"  Performance: Return={best_return.total_return_pct:.3f}%, "
              f"Sharpe={best_return.sharpe_ratio:.3f}")

    def save_results(self, filename: str = None):
        """保存结果到文件。"""
        if filename is None:
            filename = f"grid_search_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        data = {
            'timestamp': datetime.now().isoformat(),
            'duration_per_test': self.duration_minutes,
            'total_tests': len(self.results),
            'results': [r.to_dict() for r in self.results]
        }

        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"\nResults saved to: {filename}")
        return filename


def main():
    import argparse
    parser = argparse.ArgumentParser(description="MarketMakerV1 Grid Search Optimization")
    parser.add_argument("--duration", type=int, default=5,
                       help="Duration per test in minutes (default: 5)")
    parser.add_argument("--quick", action="store_true",
                       help="Quick mode: fewer parameter combinations")
    args = parser.parse_args()

    optimizer = GridSearchOptimizer(duration_minutes=args.duration)

    if args.quick:
        # 快速模式：参数范围较小
        results = optimizer.run_grid_search(
            spread_ticks_range=[2, 3, 4],
            skew_range=[2.0, 2.5, 3.0],
            order_size_range=[0.001],
            toxic_range=[0.6]
        )
    else:
        # 完整模式
        results = optimizer.run_grid_search(
            spread_ticks_range=[2, 3, 4, 5],
            skew_range=[1.5, 2.0, 2.5, 3.0, 3.5],
            order_size_range=[0.0005, 0.001, 0.002],
            toxic_range=[0.5, 0.6, 0.7]
        )

    if results:
        optimizer.analyze_results()
        filename = optimizer.save_results()
        print(f"\nOptimization complete! Results saved to {filename}")


if __name__ == "__main__":
    main()
