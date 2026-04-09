"""
自动参数调优脚本 - 基于Optuna

目标：自动寻找最优参数组合，最大化IC * sqrt(交易次数)
"""
import os
import sys
import time
import json
import numpy as np
from datetime import datetime
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 尝试导入Optuna
try:
    import optuna
    OPTUNA_AVAILABLE = True
except ImportError:
    print("[WARN] Optuna not installed, using grid search fallback")
    OPTUNA_AVAILABLE = False

from mvp_trader_v2 import MVPTraderV2


class ParameterTuner:
    """
    参数调优器

    优化目标：在产生足够交易频率的同时，保持信号质量
    评分函数：score = IC * log(1 + trade_count)
    """

    def __init__(self, symbol='ETHUSDT', test_duration_minutes=5):
        self.symbol = symbol
        self.test_duration = test_duration_minutes * 60  # 转换为秒
        self.results = []

    def simulate_market_data(self, n_ticks=100, seed=None) -> List[Dict]:
        """
        生成模拟市场数据（基于ETH特征）

        ETH特征：
        - 价格：$2000-2500
        - 点差：1-3 ticks (0.01-0.03)
        - 波动率：中等
        """
        if seed:
            np.random.seed(seed)

        data = []
        base_price = 2180.0

        for i in range(n_ticks):
            # ETH特征点差
            spread_ticks = np.random.choice([1, 1, 1, 2, 2, 3], p=[0.5, 0.2, 0.1, 0.1, 0.07, 0.03])
            spread = spread_ticks * 0.01

            # 趋势 + 噪声
            trend = np.sin(i / 20) * 1.5
            noise = np.random.randn() * 0.5

            bid_pressure = max(0.5, 1.5 + trend + noise)
            ask_pressure = max(0.5, 1.5 - trend - noise)

            bid = base_price - spread / 2
            ask = base_price + spread / 2
            base_price *= (1 + (trend * 0.0001 + np.random.randn() * 0.00005))

            data.append({
                'bids': [{'price': bid, 'qty': bid_pressure}],
                'asks': [{'price': ask, 'qty': ask_pressure}],
                'best_bid': bid,
                'best_ask': ask,
                'mid_price': (bid + ask) / 2,
                'spread': spread,
                'spread_bps': spread / ((bid + ask) / 2) * 10000
            })

        return data

    def evaluate_params(self,
                       min_spread: float,
                       alpha_threshold: float,
                       max_position: float,
                       n_ticks: int = 100) -> Dict:
        """
        评估一组参数的表现

        Returns:
            {
                'score': float,  # 综合评分
                'ic': float,     # IC值
                'trades': int,   # 交易次数
                'frequency': float,  # 交易频率
                'sharpe': float  # 夏普比率（模拟）
            }
        """
        # 创建交易器
        trader = MVPTraderV2(
            symbol=self.symbol,
            initial_capital=1000.0,
            max_position=max_position,
            use_sac=False,
            shadow_mode=False
        )

        # 设置参数
        trader.spread_capture.min_spread_ticks = min_spread
        trader.base_alpha_threshold = alpha_threshold

        # 模拟运行
        market_data = self.simulate_market_data(n_ticks, seed=42)

        for orderbook in market_data:
            trader.process_tick(orderbook)

        # 获取结果
        status = trader.get_status()

        ic = status['ic_metrics']['ic_1s']
        trades = status['trade_count']
        frequency = trades / n_ticks

        # 评分函数：平衡IC质量和交易频率
        # 如果交易次数太少，给予惩罚
        if trades < 5:
            score = -1.0  # 惩罚
        else:
            # 核心评分：IC * log(1 + trade_count)
            score = ic * np.log1p(trades)

        return {
            'score': score,
            'ic': ic,
            'trades': trades,
            'frequency': frequency,
            'params': {
                'min_spread': min_spread,
                'alpha_threshold': alpha_threshold,
                'max_position': max_position
            }
        }

    def grid_search(self, n_trials=50) -> Dict:
        """
        网格搜索（Optuna不可用时使用）
        """
        print("="*80)
        print("GRID SEARCH PARAMETER OPTIMIZATION")
        print("="*80)

        # 参数空间
        min_spread_range = [1.0, 1.2, 1.5, 2.0, 2.5]
        alpha_threshold_range = [0.0003, 0.0005, 0.0008, 0.001, 0.0015]
        max_position_range = [0.05, 0.1, 0.15, 0.2]

        best_result = None
        best_score = -float('inf')

        trial = 0
        total_trials = len(min_spread_range) * len(alpha_threshold_range) * len(max_position_range)

        for min_spread in min_spread_range:
            for alpha_threshold in alpha_threshold_range:
                for max_position in max_position_range:
                    trial += 1

                    print(f"\n[Trial {trial}/{total_trials}]")
                    print(f"  min_spread: {min_spread}")
                    print(f"  alpha_threshold: {alpha_threshold}")
                    print(f"  max_position: {max_position}")

                    result = self.evaluate_params(
                        min_spread=min_spread,
                        alpha_threshold=alpha_threshold,
                        max_position=max_position
                    )

                    print(f"  Score: {result['score']:.4f}")
                    print(f"  Trades: {result['trades']}")
                    print(f"  IC: {result['ic']:.4f}")
                    print(f"  Frequency: {result['frequency']:.2%}")

                    self.results.append(result)

                    if result['score'] > best_score:
                        best_score = result['score']
                        best_result = result
                        print(f"  *** NEW BEST ***")

        return best_result

    def optuna_optimize(self, n_trials=100) -> Dict:
        """
        使用Optuna进行贝叶斯优化
        """
        print("="*80)
        print("OPTUNA BAYESIAN OPTIMIZATION")
        print("="*80)

        def objective(trial):
            # 定义参数空间
            min_spread = trial.suggest_float('min_spread', 1.0, 3.0)
            alpha_threshold = trial.suggest_float('alpha_threshold', 0.0002, 0.002, log=True)
            max_position = trial.suggest_float('max_position', 0.03, 0.25)

            result = self.evaluate_params(
                min_spread=min_spread,
                alpha_threshold=alpha_threshold,
                max_position=max_position
            )

            return result['score']

        # 创建study
        study = optuna.create_study(
            direction='maximize',
            pruner=optuna.pruners.MedianPruner()
        )

        # 优化
        study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

        # 获取最佳参数
        best_params = study.best_params
        best_result = self.evaluate_params(**best_params)

        # 保存所有结果
        for trial in study.trials:
            if trial.value is not None:
                self.results.append({
                    'score': trial.value,
                    'params': trial.params
                })

        return best_result

    def run_optimization(self, n_trials=50) -> Dict:
        """
        运行优化（自动选择方法）
        """
        if OPTUNA_AVAILABLE:
            best = self.optuna_optimize(n_trials)
        else:
            print("[INFO] Optuna not available, using grid search")
            print("[INFO] Install optuna: pip install optuna")
            best = self.grid_search(n_trials)

        return best

    def save_results(self, filename='tuning_results.json'):
        """保存调优结果"""
        output = {
            'timestamp': datetime.now().isoformat(),
            'symbol': self.symbol,
            'results': self.results,
            'best': self.best_result if hasattr(self, 'best_result') else None
        }

        with open(filename, 'w') as f:
            json.dump(output, f, indent=2)

        print(f"\n[OK] Results saved to {filename}")

    def print_report(self, best_result: Dict):
        """打印调优报告"""
        print("\n" + "="*80)
        print("OPTIMIZATION REPORT")
        print("="*80)

        print("\n[BEST PARAMETERS]")
        for key, value in best_result['params'].items():
            print(f"  {key}: {value}")

        print("\n[PERFORMANCE METRICS]")
        print(f"  Score: {best_result['score']:.4f}")
        print(f"  IC: {best_result['ic']:.4f}")
        print(f"  Trades: {best_result['trades']}")
        print(f"  Frequency: {best_result['frequency']:.2%}")

        print("\n[RECOMMENDATION]")
        if best_result['frequency'] < 0.1:
            print("  ⚠️  Trade frequency too low, consider further reducing thresholds")
        elif best_result['frequency'] > 0.8:
            print("  ⚠️  Trade frequency too high, may increase transaction costs")
        else:
            print("  ✓ Balanced trade frequency")

        if best_result['ic'] < 0:
            print("  ✗ IC negative, signal may be inverted")
        elif best_result['ic'] < 0.05:
            print("  ~ IC weak but positive, consider longer training")
        else:
            print("  ✓ Good IC, signal has predictive power")

        print("="*80)


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='Parameter Tuner for Alpha V2')
    parser.add_argument('--symbol', type=str, default='ETHUSDT', help='Trading pair')
    parser.add_argument('--trials', type=int, default=50, help='Number of trials')
    parser.add_argument('--output', type=str, default='tuning_results.json', help='Output file')
    args = parser.parse_args()

    # 创建调优器
    tuner = ParameterTuner(
        symbol=args.symbol,
        test_duration_minutes=5
    )

    # 运行优化
    best = tuner.run_optimization(n_trials=args.trials)

    # 保存结果
    tuner.best_result = best
    tuner.save_results(args.output)

    # 打印报告
    tuner.print_report(best)

    print("\n" + "="*80)
    print("NEXT STEPS")
    print("="*80)
    print("1. Review best parameters above")
    print("2. Apply to run_alpha_v2_paper_trading.py")
    print("3. Run real market test for 30+ minutes")
    print("4. Verify IC convergence")
    print("="*80)


if __name__ == '__main__':
    main()
