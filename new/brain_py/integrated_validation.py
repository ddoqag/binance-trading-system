"""
集成验证系统

整合三个验证层：
1. ForceFill三模式测试
2. 事件驱动回放引擎
3. 自我影响建模
"""

import sys
sys.path.insert(0, '.')

import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime
import json

from forcefill_three_mode import ForceFillThreeMode, RandomStrategy
from event_driven_replay import MinimalEventReplay, MarketEvent, SimpleStrategy
from self_impact_model import SelfImpactModel
from local_trading.data_source import SyntheticDataSource


class IntegratedValidator:
    """
    集成验证器

    运行完整的验证流程：
    1. ForceFill三模式测试 - 分离Alpha与执行
    2. 事件驱动回放 - 更真实的回测
    3. 自我影响分析 - 量化我的订单对市场的冲击
    """

    def __init__(self, strategy, data_source=None):
        """
        初始化集成验证器

        Args:
            strategy: 策略对象
            data_source: 数据源（可选）
        """
        self.strategy = strategy
        self.data_source = data_source

        # 三个核心组件
        self.forcefill = None
        self.replay = None
        self.impact = SelfImpactModel(market_sensitivity=0.3)

        # 结果
        self.results = {}

    def run_full_validation(self, verbose: bool = True) -> Dict:
        """
        运行完整验证流程

        Returns:
            Dict: 完整验证报告
        """
        if verbose:
            print("\n" + "=" * 70)
            print("         INTEGRATED VALIDATION SYSTEM")
            print("=" * 70)
            print("\nRunning three-layer validation:")
            print("  1. ForceFill Three-Mode Test")
            print("  2. Event-Driven Replay")
            print("  3. Self-Impact Analysis")
            print("=" * 70)

        # 准备数据
        data = self._prepare_data()

        # 阶段1: ForceFill三模式
        if verbose:
            print("\n" + "-" * 70)
            print("PHASE 1: ForceFill Three-Mode Test")
            print("-" * 70)

        self.forcefill = ForceFillThreeMode(self.strategy, data)
        forcefill_results = self.forcefill.run_all_modes(verbose=verbose)
        self.results['forcefill'] = forcefill_results

        # 阶段2: 事件驱动回放
        if verbose:
            print("\n" + "-" * 70)
            print("PHASE 2: Event-Driven Replay")
            print("-" * 70)

        event_results = self._run_event_driven_replay(data, verbose)
        self.results['event_driven'] = event_results

        # 阶段3: 自我影响分析
        if verbose:
            print("\n" + "-" * 70)
            print("PHASE 3: Self-Impact Analysis")
            print("-" * 70)

        impact_analysis = self._analyze_self_impact(event_results, verbose)
        self.results['impact'] = impact_analysis

        # 生成综合报告
        report = self._generate_comprehensive_report(verbose)
        self.results['report'] = report

        return self.results

    def _prepare_data(self) -> pd.DataFrame:
        """准备测试数据"""
        if self.data_source is not None:
            # 使用提供的数据源
            if hasattr(self.data_source, 'get_ticks'):
                ticks = self.data_source.get_ticks()
                data = pd.DataFrame([{
                    'timestamp': t.timestamp,
                    'bid_price': t.bid_price,
                    'ask_price': t.ask_price,
                    'mid_price': t.mid_price,
                    'spread': t.spread_bps,
                    'volume': t.volume
                } for t in ticks])
                data.set_index('timestamp', inplace=True)
                return data
            elif hasattr(self.data_source, 'data'):
                return self.data_source.data

        # 创建合成数据
        print("Preparing synthetic data...")
        np.random.seed(42)
        n = 1000

        data = pd.DataFrame({
            'bid_price': np.cumsum(np.random.normal(0, 1, n)) + 49995,
            'ask_price': np.cumsum(np.random.normal(0, 1, n)) + 50005,
            'mid_price': np.cumsum(np.random.normal(0, 1, n)) + 50000,
            'close': np.cumsum(np.random.normal(0, 1, n)) + 50000,
            'spread': np.random.uniform(1, 10, n),
            'volume': np.random.uniform(100, 1000, n)
        })
        data.index = pd.date_range('2024-01-01', periods=n, freq='1min')

        return data

    def _run_event_driven_replay(self, data: pd.DataFrame, verbose: bool) -> Dict:
        """运行事件驱动回放"""
        # 从DataFrame生成事件流
        events = self._convert_to_events(data)

        # 创建回放引擎
        replay = MinimalEventReplay()
        replay.load_events(events)

        # 运行回放
        trades = replay.replay(self.strategy, max_events=min(len(events), 500))

        # 计算指标
        if trades:
            pnl_values = [t.pnl for t in trades]
            total_pnl = sum(pnl_values)

            if len(pnl_values) > 1 and np.std(pnl_values) > 0:
                sharpe = np.mean(pnl_values) / np.std(pnl_values) * np.sqrt(252)
            else:
                sharpe = 0.0

            win_rate = np.mean([p > 0 for p in pnl_values]) if pnl_values else 0.0
        else:
            total_pnl = 0.0
            sharpe = 0.0
            win_rate = 0.0

        results = {
            'n_trades': len(trades),
            'total_pnl': total_pnl,
            'sharpe': sharpe,
            'win_rate': win_rate,
            'trades': trades
        }

        if verbose:
            print(f"\nEvent-Driven Replay Results:")
            print(f"  Trades: {results['n_trades']}")
            print(f"  Total PnL: ${results['total_pnl']:.2f}")
            print(f"  Sharpe: {results['sharpe']:.2f}")
            print(f"  Win rate: {results['win_rate']:.1%}")

        return results

    def _convert_to_events(self, data: pd.DataFrame) -> List[MarketEvent]:
        """将DataFrame转换为事件流"""
        events = []

        for i, (idx, row) in enumerate(data.iterrows()):
            timestamp = i * 1000  # 毫秒

            # 添加买单
            if 'bid_price' in row:
                events.append(MarketEvent(
                    timestamp=timestamp,
                    event_type='add',
                    side='buy',
                    price=row['bid_price'],
                    size=np.random.uniform(0.1, 1.0),
                    order_id=f"bid_{i}"
                ))

            # 添加卖单
            if 'ask_price' in row:
                events.append(MarketEvent(
                    timestamp=timestamp,
                    event_type='add',
                    side='sell',
                    price=row['ask_price'],
                    size=np.random.uniform(0.1, 1.0),
                    order_id=f"ask_{i}"
                ))

            # 随机添加成交事件
            if i % 5 == 0 and 'mid_price' in row:
                events.append(MarketEvent(
                    timestamp=timestamp + 100,
                    event_type='trade',
                    side=np.random.choice(['buy', 'sell']),
                    price=row['mid_price'],
                    size=np.random.uniform(0.05, 0.5),
                    order_id=f"trade_{i}"
                ))

        return events

    def _analyze_self_impact(self, event_results: Dict, verbose: bool) -> Dict:
        """分析自我影响"""
        trades = event_results.get('trades', [])

        if not trades:
            return {
                'impact_score': 0.0,
                'avg_price_impact': 0.0,
                'avg_queue_jump_prob': 0.0,
                'status': 'No trades to analyze'
            }

        impacts = []

        for trade in trades:
            # 转换为订单格式
            order = {
                'timestamp': trade.timestamp,
                'side': trade.side,
                'price': trade.price,
                'size': trade.size
            }

            # 预测市场反应
            response = self.impact.predict_market_response(order, {})
            impacts.append(response)

            # 记录订单
            self.impact.add_my_order(order)

        # 汇总
        avg_price_impact = np.mean([abs(i.price_impact) for i in impacts])
        avg_jump_prob = np.mean([i.queue_jump_probability for i in impacts])
        avg_spread_widen = np.mean([i.spread_widening for i in impacts])

        impact_score = self.impact.calculate_impact_score(
            [{'side': t.side, 'price': t.price, 'size': t.size} for t in trades]
        )

        results = {
            'impact_score': impact_score,
            'avg_price_impact': avg_price_impact,
            'avg_queue_jump_prob': avg_jump_prob,
            'avg_spread_widening': avg_spread_widen,
            'total_orders': len(trades)
        }

        if verbose:
            print(f"\nSelf-Impact Analysis:")
            print(f"  Impact score: {results['impact_score']:.1f}/100")
            print(f"  Avg price impact: {results['avg_price_impact']:.6f}")
            print(f"  Avg queue jump prob: {results['avg_queue_jump_prob']:.3f}")
            print(f"  Total orders: {results['total_orders']}")

        return results

    def _generate_comprehensive_report(self, verbose: bool) -> Dict:
        """生成综合验证报告"""
        # 提取各阶段结果
        alpha_sharpe = self.results['forcefill']['alpha_only']['sharpe']
        exec_sharpe = self.results['forcefill']['execution_only']['sharpe']
        full_sharpe = self.results['forcefill']['full_system']['sharpe']

        event_sharpe = self.results['event_driven']['sharpe']
        impact_score = self.results['impact']['impact_score']

        # 最终判决
        verdict = self._determine_verdict(
            alpha_sharpe, exec_sharpe, full_sharpe,
            event_sharpe, impact_score
        )

        report = {
            'timestamp': datetime.now().isoformat(),
            'forcefill': {
                'alpha_only_sharpe': alpha_sharpe,
                'execution_only_sharpe': exec_sharpe,
                'full_system_sharpe': full_sharpe,
                'execution_decay': full_sharpe / alpha_sharpe if abs(alpha_sharpe) > 0.01 else 0
            },
            'event_driven': {
                'sharpe': event_sharpe,
                'n_trades': self.results['event_driven']['n_trades'],
                'total_pnl': self.results['event_driven']['total_pnl']
            },
            'self_impact': {
                'impact_score': impact_score,
                'avg_price_impact': self.results['impact']['avg_price_impact']
            },
            'final_verdict': verdict
        }

        if verbose:
            print("\n" + "=" * 70)
            print("         COMPREHENSIVE VALIDATION REPORT")
            print("=" * 70)
            print(f"\nForceFill Results:")
            print(f"  Alpha-only Sharpe:      {alpha_sharpe:.2f}")
            print(f"  Execution-only Sharpe:  {exec_sharpe:.2f}")
            print(f"  Full system Sharpe:     {full_sharpe:.2f}")

            print(f"\nEvent-Driven Results:")
            print(f"  Sharpe: {event_sharpe:.2f}")
            print(f"  Trades: {self.results['event_driven']['n_trades']}")

            print(f"\nSelf-Impact:")
            print(f"  Impact score: {impact_score:.1f}/100")

            print(f"\n{'=' * 70}")
            print(f"FINAL VERDICT: {verdict}")
            print("=" * 70)

        return report

    def _determine_verdict(self, alpha_sharpe, exec_sharpe, full_sharpe,
                          event_sharpe, impact_score) -> str:
        """最终判决"""
        # 综合判断逻辑
        strong_alpha = alpha_sharpe > 2
        strong_exec = exec_sharpe > 1
        strong_full = full_sharpe > 1.5
        low_impact = impact_score < 30

        if strong_alpha and strong_exec and strong_full:
            if low_impact:
                return "[REAL ALPHA] Strong Alpha + Execution, Low Self-Impact -> Ready for live"
            else:
                return "[CAUTION] Strong Alpha + Execution, but High Self-Impact -> Optimize order size"

        elif strong_alpha and not strong_exec:
            return "[ALPHA ONLY] Good signals but poor execution -> Switch to market orders"

        elif not strong_alpha and strong_exec:
            return "[EXECUTION ONLY] No alpha but good execution -> Consider market-making"

        elif alpha_sharpe < 0 and exec_sharpe < 0:
            return "[FAILURE] No alpha, poor execution -> Redesign strategy"

        else:
            return "[BORDERLINE] Unclear results -> Need more data"

    def save_report(self, filepath: str):
        """保存验证报告"""
        with open(filepath, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)
        print(f"\nReport saved: {filepath}")


def run_mvp_validation():
    """运行MVP策略的完整验证"""
    print("\n" + "=" * 70)
    print("         MVP Strategy Integrated Validation")
    print("=" * 70)

    # 创建MVP策略
    from mvp_trader import MVPTrader

    strategy = MVPTrader(
        symbol='BTCUSDT',
        initial_capital=1000.0,
        max_position=0.5,
        tick_size=0.01
    )

    # 创建合成数据源
    data_source = SyntheticDataSource(n_ticks=800)

    # 创建验证器
    validator = IntegratedValidator(strategy, data_source)

    # 运行验证
    results = validator.run_full_validation(verbose=True)

    # 保存报告
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    validator.save_report(f'validation_report_{timestamp}.json')

    return results


if __name__ == "__main__":
    # 运行验证
    results = run_mvp_validation()

    print("\n" + "=" * 70)
    print("Validation Complete")
    print("=" * 70)
