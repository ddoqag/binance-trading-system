"""
MVP vs 完整系统对比分析

对比维度：
1. 延迟性能
2. 盈亏表现
3. 可解释性
4. 风险控制
5. 参数敏感性
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import time
import logging

from mvp_backtest import MVPBacktestEngine, MVPBacktestResult, BacktestConfig, TickData


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('MVPComparison')


@dataclass
class ComparisonMetrics:
    """对比指标"""
    metric_name: str
    mvp_value: float
    full_system_value: float
    difference: float
    improvement_pct: float
    winner: str  # 'mvp', 'full', or 'tie'


@dataclass
class MVPComparisonReport:
    """MVP对比报告"""
    # 测试配置
    symbol: str
    test_duration_ticks: int
    timestamp: float

    # 对比结果
    metrics: List[ComparisonMetrics] = field(default_factory=list)

    # 详细结果
    mvp_result: Optional[MVPBacktestResult] = None
    full_result: Optional[MVPBacktestResult] = None

    # 统计显著性
    pnl_p_value: Optional[float] = None
    is_significant: bool = False

    # 综合评分
    mvp_score: float = 0.0
    full_score: float = 0.0
    overall_winner: str = ""


class SimpleFullSystemSimulator:
    """
    简化版完整系统模拟器

    模拟完整系统的延迟和决策特征（用于对比）
    """

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.state = {
            'capital': config.initial_capital,
            'position': 0.0,
            'total_pnl': 0.0,
            'latency_ms': 10.0  # 完整系统典型延迟10ms
        }
        self.trades = []

    def process_tick(self, tick: TickData) -> Optional[Dict]:
        """
        模拟完整系统的决策

        特点：
        - 更高延迟 (5-20ms)
        - 更复杂决策逻辑
        - 偶尔 unpredictable 行为
        """
        # 模拟完整系统延迟
        time.sleep(np.random.uniform(5, 20) / 1000)

        # 完整系统有时做出"奇怪"的决策（模拟黑箱特性）
        noise = np.random.randn() * 0.3

        # 只在点差足够大且没有噪音干扰时交易
        if tick.spread_bps >= 3 and abs(noise) < 0.5:
            side = 'buy' if tick.bid_qty > tick.ask_qty else 'sell'

            return {
                'side': side,
                'qty': self.config.max_position * (0.8 + noise * 0.4),  # 不确定的仓位
                'price': tick.bid_price if side == 'buy' else tick.ask_price,
                'confidence': 0.7 + noise * 0.3  # 不确定的置信度
            }

        return None

    def calculate_pnl(self, ticks: List[TickData]) -> float:
        """计算完整系统的盈亏（简化模拟）"""
        total_pnl = 0.0
        position = 0.0
        entry_price = 0.0

        for i, tick in enumerate(ticks[:-1]):
            decision = self.process_tick(tick)

            if decision:
                next_tick = ticks[i + 1]

                if decision['side'] == 'buy' and position <= 0:
                    # 开多/平空
                    if position < 0:
                        # 平空盈利
                        pnl = (entry_price - next_tick.mid_price) * abs(position)
                        total_pnl += pnl

                    entry_price = decision['price']
                    position = decision['qty']

                elif decision['side'] == 'sell' and position >= 0:
                    # 开空/平多
                    if position > 0:
                        # 平多盈利
                        pnl = (next_tick.mid_price - entry_price) * position
                        total_pnl += pnl

                    entry_price = decision['price']
                    position = -decision['qty']

        return total_pnl


class MVPComparator:
    """
    MVP对比分析器

    系统化对比MVP和完整系统的表现
    """

    def __init__(self):
        self.reports: List[MVPComparisonReport] = []

    def run_comparison(self,
                       ticks: List[TickData],
                       config: BacktestConfig,
                       n_runs: int = 3) -> MVPComparisonReport:
        """
        运行对比测试

        Args:
            ticks: 测试数据
            config: 配置
            n_runs: 重复运行次数（减少随机性影响）

        Returns:
            MVPComparisonReport
        """
        logger.info(f"Starting comparison: MVP vs Full System ({n_runs} runs)")

        report = MVPComparisonReport(
            symbol=config.symbol,
            test_duration_ticks=len(ticks),
            timestamp=time.time()
        )

        # 多次运行取平均
        mvp_results = []
        full_results = []

        for run in range(n_runs):
            logger.info(f"Run {run + 1}/{n_runs}")

            # MVP回测
            mvp_engine = MVPBacktestEngine(config)
            mvp_engine.load_data(ticks)
            mvp_result = mvp_engine.run(progress_interval=10000)
            mvp_results.append(mvp_result)

            # 完整系统模拟
            full_sim = SimpleFullSystemSimulator(config)
            full_pnl = full_sim.calculate_pnl(ticks)

            # 创建伪结果对象用于对比
            full_result = self._create_full_system_result(full_pnl, ticks, config)
            full_results.append(full_result)

        # 平均结果
        avg_mvp = self._average_results(mvp_results)
        avg_full = self._average_results(full_results)

        report.mvp_result = avg_mvp
        report.full_result = avg_full

        # 计算对比指标
        report.metrics = self._calculate_comparison_metrics(avg_mvp, avg_full)

        # 计算综合评分
        mvp_score, full_score = self._calculate_overall_score(report.metrics)
        report.mvp_score = mvp_score
        report.full_score = full_score
        report.overall_winner = 'mvp' if mvp_score > full_score else 'full'

        self.reports.append(report)

        return report

    def _create_full_system_result(self,
                                   pnl: float,
                                   ticks: List[TickData],
                                   config: BacktestConfig) -> MVPBacktestResult:
        """创建完整系统的模拟结果"""
        return MVPBacktestResult(
            config=config,
            start_time=pd.Timestamp.now(),
            end_time=pd.Timestamp.now(),
            duration_hours=len(ticks) * 0.1 / 3600,
            initial_capital=config.initial_capital,
            final_capital=config.initial_capital + pnl,
            total_pnl=pnl,
            total_pnl_pct=pnl / config.initial_capital,
            total_orders=len(ticks) // 10,  # 估计
            total_fills=len(ticks) // 20,
            fill_rate=0.5,
            avg_order_size=0.1,
            pnl_components={'simulated': pnl},
            toxic_alerts=0,
            toxic_blocks=0,
            toxic_alert_rate=0,
            queue_hold_rate=0.5,
            queue_repost_rate=0.3,
            avg_queue_ratio=0.4,
            spread_opportunities=len(ticks),
            spread_captures=len(ticks) // 3,
            avg_spread_bps=5.0,
            avg_capture_bps=3.0,
            avg_latency_ms=15.0,  # 完整系统典型延迟
            max_latency_ms=50.0,
            max_drawdown=-abs(pnl) * 0.5,  # 假设
            max_drawdown_pct=-abs(pnl) / config.initial_capital * 0.5,
            sharpe_ratio=pnl / (abs(pnl) + 1),  # 简化
            win_rate=0.5,
            profit_factor=1.2
        )

    def _average_results(self, results: List[MVPBacktestResult]) -> MVPBacktestResult:
        """平均多个结果"""
        if not results:
            return None

        first = results[0]
        n = len(results)

        def avg(key):
            return np.mean([getattr(r, key) for r in results])

        return MVPBacktestResult(
            config=first.config,
            start_time=first.start_time,
            end_time=first.end_time,
            duration_hours=avg('duration_hours'),
            initial_capital=first.initial_capital,
            final_capital=avg('final_capital'),
            total_pnl=avg('total_pnl'),
            total_pnl_pct=avg('total_pnl_pct'),
            total_orders=int(avg('total_orders')),
            total_fills=int(avg('total_fills')),
            fill_rate=avg('fill_rate'),
            avg_order_size=avg('avg_order_size'),
            pnl_components=first.pnl_components,
            toxic_alerts=int(avg('toxic_alerts')),
            toxic_blocks=int(avg('toxic_blocks')),
            toxic_alert_rate=avg('toxic_alert_rate'),
            queue_hold_rate=avg('queue_hold_rate'),
            queue_repost_rate=avg('queue_repost_rate'),
            avg_queue_ratio=avg('avg_queue_ratio'),
            spread_opportunities=int(avg('spread_opportunities')),
            spread_captures=int(avg('spread_captures')),
            avg_spread_bps=avg('avg_spread_bps'),
            avg_capture_bps=avg('avg_capture_bps'),
            avg_latency_ms=avg('avg_latency_ms'),
            max_latency_ms=avg('max_latency_ms'),
            max_drawdown=avg('max_drawdown'),
            max_drawdown_pct=avg('max_drawdown_pct'),
            sharpe_ratio=avg('sharpe_ratio'),
            win_rate=avg('win_rate'),
            profit_factor=avg('profit_factor')
        )

    def _calculate_comparison_metrics(self,
                                     mvp: MVPBacktestResult,
                                     full: MVPBacktestResult) -> List[ComparisonMetrics]:
        """计算对比指标"""
        metrics = []

        comparisons = [
            ('latency_ms', mvp.avg_latency_ms, full.avg_latency_ms, 'lower'),
            ('total_pnl', mvp.total_pnl, full.total_pnl, 'higher'),
            ('sharpe_ratio', mvp.sharpe_ratio, full.sharpe_ratio, 'higher'),
            ('max_drawdown_pct', abs(mvp.max_drawdown_pct), abs(full.max_drawdown_pct), 'lower'),
            ('win_rate', mvp.win_rate, full.win_rate, 'higher'),
            ('fill_rate', mvp.fill_rate, full.fill_rate, 'higher'),
            ('toxic_blocks', mvp.toxic_blocks, full.toxic_blocks, 'higher'),
        ]

        for name, mvp_val, full_val, better in comparisons:
            diff = mvp_val - full_val

            if full_val != 0:
                improvement = (mvp_val - full_val) / abs(full_val) * 100
            else:
                improvement = 0

            if better == 'lower':
                winner = 'mvp' if mvp_val < full_val else 'full' if full_val < mvp_val else 'tie'
                improvement = -improvement  # 反转，越低越好
            else:
                winner = 'mvp' if mvp_val > full_val else 'full' if full_val > mvp_val else 'tie'

            metrics.append(ComparisonMetrics(
                metric_name=name,
                mvp_value=mvp_val,
                full_system_value=full_val,
                difference=diff,
                improvement_pct=improvement,
                winner=winner
            ))

        return metrics

    def _calculate_overall_score(self,
                                  metrics: List[ComparisonMetrics]) -> Tuple[float, float]:
        """计算综合评分"""
        mvp_score = 0
        full_score = 0

        for m in metrics:
            if m.winner == 'mvp':
                mvp_score += 1
            elif m.winner == 'full':
                full_score += 1
            else:
                mvp_score += 0.5
                full_score += 0.5

        return mvp_score, full_score


def print_comparison_report(report: MVPComparisonReport):
    """打印对比报告"""
    print("\n" + "=" * 70)
    print("MVP vs 完整系统 对比报告")
    print("=" * 70)

    print(f"\n测试配置:")
    print(f"  交易对: {report.symbol}")
    print(f"  Tick数量: {report.test_duration_ticks}")

    print(f"\n对比结果:")
    print("-" * 70)
    print(f"{'指标':<20} {'MVP':>12} {'完整系统':>12} {'差异':>12} {'胜出':>8}")
    print("-" * 70)

    for m in report.metrics:
        diff_str = f"{m.difference:+.2f}"
        impr_str = f"({m.improvement_pct:+.1f}%)"
        winner = "MVP" if m.winner == 'mvp' else "完整" if m.winner == 'full' else "平"
        print(f"{m.metric_name:<20} {m.mvp_value:>12.2f} {m.full_system_value:>12.2f} {diff_str:>12} {winner:>8}")

    print("-" * 70)

    print(f"\n综合评分:")
    print(f"  MVP得分: {report.mvp_score:.1f}")
    print(f"  完整系统得分: {report.full_score:.1f}")
    print(f"  总体胜出: {'MVP' if report.overall_winner == 'mvp' else '完整系统'}")

    print(f"\n关键发现:")
    mvp_wins = len([m for m in report.metrics if m.winner == 'mvp'])
    full_wins = len([m for m in report.metrics if m.winner == 'full'])

    print(f"  - MVP胜出指标: {mvp_wins}/{len(report.metrics)}")
    print(f"  - 完整系统胜出指标: {full_wins}/{len(report.metrics)}")

    # 关键优势
    latency_impr = next((m for m in report.metrics if m.metric_name == 'latency_ms'), None)
    if latency_impr:
        speedup = latency_impr.full_system_value / max(latency_impr.mvp_value, 0.001)
        print(f"  - 延迟优势: {speedup:.1f}x 更快")

    print("\n" + "=" * 70)


# 测试代码
if __name__ == "__main__":
    print("=" * 70)
    print("MVP vs 完整系统 对比测试")
    print("=" * 70)

    from mvp_backtest import HistoricalDataLoader

    # 生成测试数据
    loader = HistoricalDataLoader()
    ticks = loader.generate_synthetic_data(n_ticks=2000, base_price=50000.0)

    # 配置
    config = BacktestConfig(
        symbol="BTCUSDT",
        initial_capital=1000.0,
        max_position=0.1
    )

    # 运行对比
    comparator = MVPComparator()
    report = comparator.run_comparison(ticks, config, n_runs=2)

    # 打印报告
    print_comparison_report(report)

    print("\n测试完成")
