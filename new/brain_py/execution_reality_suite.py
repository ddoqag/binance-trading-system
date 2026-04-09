"""
执行层真实性检验套件 (Execution Reality Test Suite)

5个压力测试验证执行引擎盈利的真实性，排除模拟器偏差:

1. 延迟冲击测试 (Latency Shock Test)
   - 模拟不同延迟条件下的执行表现
   - 验证盈利是否依赖于不切实际的低延迟假设

2. 滑点压力测试 (Slippage Stress Test)
   - 注入不同级别的滑点
   - 验证策略对执行成本的鲁棒性

3. 市场冲击测试 (Market Impact Test)
   - 模拟大单对市场价格的影响
   - 验证大仓位下的盈利可持续性

4. 流动性枯竭测试 (Liquidity Dry-up Test)
   - 模拟流动性突然下降的场景
   - 验证极端市场条件下的生存能力

5. 对抗性交易测试 (Adversarial Trading Test)
   - 模拟有毒订单流和逆向选择
   - 验证防御机制的有效性
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestResult(Enum):
    """测试结果"""
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


@dataclass
class RealityTestReport:
    """真实性测试报告"""
    test_name: str
    result: TestResult
    score: float  # 0-100
    baseline_pnl: float
    stressed_pnl: float
    pnl_retention: float  # 压力后盈利保留比例
    details: Dict = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)


@dataclass
class ExecutionRealityReport:
    """执行层真实性完整报告"""
    timestamp: datetime
    overall_score: float
    overall_result: TestResult
    individual_tests: List[RealityTestReport]
    summary: str
    recommendations: List[str]


class ExecutionRealitySuite:
    """
    执行层真实性检验套件

    通过5个维度验证执行引擎的真实性:
    - 延迟鲁棒性
    - 滑点容忍度
    - 市场冲击抗性
    - 流动性适应性
    - 对抗性防御能力
    """

    # 测试阈值
    PASS_THRESHOLD = 70.0
    WARNING_THRESHOLD = 50.0

    def __init__(
        self,
        strategy_factory: Callable,
        data: pd.DataFrame,
        initial_capital: float = 10000.0,
        random_seed: int = 42
    ):
        self.strategy_factory = strategy_factory
        self.data = data.copy()
        self.initial_capital = initial_capital
        self.random_seed = random_seed

        np.random.seed(random_seed)

        self.reports: List[RealityTestReport] = []
        self.final_report: Optional[ExecutionRealityReport] = None

        logger.info(f"ExecutionRealitySuite initialized: {len(data)} rows")

    def run_all_tests(self, verbose: bool = True) -> ExecutionRealityReport:
        """运行所有真实性测试"""
        if verbose:
            print("\n" + "=" * 80)
            print("         EXECUTION REALITY TEST SUITE")
            print("         执行层真实性检验套件")
            print("=" * 80)
            print(f"Data size: {len(self.data)} records")
            print(f"Initial capital: ${self.initial_capital:,.2f}")
            print("=" * 80 + "\n")

        self.reports = []

        # 测试1: 延迟冲击测试
        report1 = self._latency_shock_test()
        self.reports.append(report1)
        if verbose:
            self._print_report(report1)

        # 测试2: 滑点压力测试
        report2 = self._slippage_stress_test()
        self.reports.append(report2)
        if verbose:
            self._print_report(report2)

        # 测试3: 市场冲击测试
        report3 = self._market_impact_test()
        self.reports.append(report3)
        if verbose:
            self._print_report(report3)

        # 测试4: 流动性枯竭测试
        report4 = self._liquidity_dryup_test()
        self.reports.append(report4)
        if verbose:
            self._print_report(report4)

        # 测试5: 对抗性交易测试
        report5 = self._adversarial_trading_test()
        self.reports.append(report5)
        if verbose:
            self._print_report(report5)

        # 生成最终报告
        self.final_report = self._generate_final_report()

        if verbose:
            self._print_final_report()

        return self.final_report

    def _latency_shock_test(self) -> RealityTestReport:
        """
        延迟冲击测试

        验证策略在不同延迟条件下的表现:
        - 0ms (理想情况)
        - 10ms (优秀)
        - 50ms (良好)
        - 100ms (一般)
        - 200ms (较差)
        """
        test_name = "1. 延迟冲击测试 (Latency Shock)"

        latency_levels = [0, 10, 50, 100, 200]
        results = []

        # 基线测试 (0延迟)
        baseline_data = self._inject_latency(self.data, 0)
        baseline_pnl = self._run_backtest(baseline_data)

        for latency in latency_levels:
            delayed_data = self._inject_latency(self.data, latency)
            pnl = self._run_backtest(delayed_data)
            retention = pnl / baseline_pnl if baseline_pnl != 0 else 0

            results.append({
                'latency_ms': latency,
                'pnl': pnl,
                'retention': retention
            })

        # 计算加权得分 (高延迟权重更高)
        weights = [0.1, 0.15, 0.25, 0.25, 0.25]
        retentions = [r['retention'] for r in results]
        avg_retention = np.average(retentions, weights=weights)

        score = max(0, min(100, avg_retention * 100))

        if score >= 80:
            result = TestResult.PASS
        elif score >= 60:
            result = TestResult.WARNING
        else:
            result = TestResult.FAIL

        # 找出临界点
        critical_latency = None
        for r in results:
            if r['retention'] < 0.5:
                critical_latency = r['latency_ms']
                break

        recommendations = []
        if score < 80:
            recommendations.append(
                f"策略对延迟敏感，建议在延迟 < {critical_latency or 50}ms 的环境中运行"
            )
        if results[-1]['retention'] < 0.3:
            recommendations.append(
                "高延迟环境下盈利大幅下降，考虑增加延迟容忍逻辑"
            )

        return RealityTestReport(
            test_name=test_name,
            result=result,
            score=score,
            baseline_pnl=baseline_pnl,
            stressed_pnl=results[-1]['pnl'],
            pnl_retention=results[-1]['retention'],
            details={
                'latency_results': results,
                'critical_latency_ms': critical_latency,
                'avg_retention': avg_retention
            },
            recommendations=recommendations
        )

    def _slippage_stress_test(self) -> RealityTestReport:
        """
        滑点压力测试

        验证策略在不同滑点水平下的表现:
        - 0 bps (理想)
        - 1 bps (低)
        - 3 bps (正常)
        - 5 bps (高)
        - 10 bps (极高)
        """
        test_name = "2. 滑点压力测试 (Slippage Stress)"

        slippage_levels = [0, 0.0001, 0.0003, 0.0005, 0.001]  # 0, 1, 3, 5, 10 bps
        results = []

        baseline_pnl = self._run_backtest(self.data, slippage=0)

        for slippage in slippage_levels:
            pnl = self._run_backtest(self.data, slippage=slippage)
            retention = pnl / baseline_pnl if baseline_pnl != 0 else 0

            results.append({
                'slippage_bps': slippage * 10000,
                'pnl': pnl,
                'retention': retention
            })

        # 计算得分
        avg_retention = np.mean([r['retention'] for r in results[1:]])  # 排除基线
        score = max(0, min(100, avg_retention * 100))

        if score >= 75:
            result = TestResult.PASS
        elif score >= 50:
            result = TestResult.WARNING
        else:
            result = TestResult.FAIL

        # 计算盈亏平衡点
        breakeven_slippage = None
        for i in range(len(results) - 1):
            if results[i]['pnl'] > 0 and results[i + 1]['pnl'] <= 0:
                breakeven_slippage = results[i]['slippage_bps']
                break

        recommendations = []
        if breakeven_slippage:
            recommendations.append(
                f"盈亏平衡滑点: {breakeven_slippage:.1f} bps，建议控制实际滑点在此之下"
            )
        if results[2]['retention'] < 0.7:  # 3bps滑点保留率
            recommendations.append(
                "正常滑点水平下盈利下降明显，建议优化执行策略降低滑点"
            )

        return RealityTestReport(
            test_name=test_name,
            result=result,
            score=score,
            baseline_pnl=baseline_pnl,
            stressed_pnl=results[-1]['pnl'],
            pnl_retention=results[-1]['retention'],
            details={
                'slippage_results': results,
                'breakeven_slippage_bps': breakeven_slippage
            },
            recommendations=recommendations
        )

    def _market_impact_test(self) -> RealityTestReport:
        """
        市场冲击测试

        验证大单对市场价格的影响:
        - 不同订单规模下的冲击成本
        - 冲击后的价格恢复时间
        """
        test_name = "3. 市场冲击测试 (Market Impact)"

        # 模拟不同规模的订单
        order_sizes = [0.01, 0.05, 0.1, 0.2, 0.5]  # BTC
        results = []

        baseline_pnl = self._run_backtest(self.data, max_position=0.01)

        for size in order_sizes:
            # 注入市场冲击
            impacted_data = self._inject_market_impact(self.data, size)
            pnl = self._run_backtest(impacted_data, max_position=size)
            retention = pnl / baseline_pnl if baseline_pnl != 0 else 0

            results.append({
                'order_size_btc': size,
                'pnl': pnl,
                'retention': retention,
                'impact_cost': self._estimate_impact_cost(size)
            })

        # 计算得分 (关注中等规模)
        mid_scale_retention = results[2]['retention']  # 0.1 BTC
        score = max(0, min(100, mid_scale_retention * 100))

        if score >= 70:
            result = TestResult.PASS
        elif score >= 50:
            result = TestResult.WARNING
        else:
            result = TestResult.FAIL

        recommendations = []
        if results[-1]['retention'] < 0.5:
            recommendations.append(
                "大规模订单盈利显著下降，建议实施TWAP/VWAP拆分执行"
            )
        if any(r['impact_cost'] > 0.001 for r in results):
            recommendations.append(
                "市场冲击成本较高，建议增加冲击预测模型"
            )

        return RealityTestReport(
            test_name=test_name,
            result=result,
            score=score,
            baseline_pnl=baseline_pnl,
            stressed_pnl=results[-1]['pnl'],
            pnl_retention=results[-1]['retention'],
            details={
                'size_results': results
            },
            recommendations=recommendations
        )

    def _liquidity_dryup_test(self) -> RealityTestReport:
        """
        流动性枯竭测试

        模拟流动性突然下降的场景:
        - 订单簿深度减少
        - 价差扩大
        - 成交量萎缩
        """
        test_name = "4. 流动性枯竭测试 (Liquidity Dry-up)"

        scenarios = [
            {'name': 'Normal', 'depth_factor': 1.0, 'spread_factor': 1.0},
            {'name': 'Light', 'depth_factor': 0.7, 'spread_factor': 1.5},
            {'name': 'Moderate', 'depth_factor': 0.5, 'spread_factor': 2.0},
            {'name': 'Severe', 'depth_factor': 0.3, 'spread_factor': 3.0},
            {'name': 'Extreme', 'depth_factor': 0.1, 'spread_factor': 5.0},
        ]

        results = []
        baseline_pnl = None

        for scenario in scenarios:
            dry_data = self._inject_liquidity_stress(
                self.data,
                depth_factor=scenario['depth_factor'],
                spread_factor=scenario['spread_factor']
            )
            pnl = self._run_backtest(dry_data)

            if scenario['name'] == 'Normal':
                baseline_pnl = pnl
                retention = 1.0
            else:
                retention = pnl / baseline_pnl if baseline_pnl != 0 else 0

            results.append({
                'scenario': scenario['name'],
                'pnl': pnl,
                'retention': retention
            })

        # 计算得分 (关注中度压力)
        moderate_retention = results[2]['retention']
        score = max(0, min(100, moderate_retention * 100))

        if score >= 65:
            result = TestResult.PASS
        elif score >= 40:
            result = TestResult.WARNING
        else:
            result = TestResult.FAIL

        recommendations = []
        if results[-1]['retention'] < 0.2:
            recommendations.append(
                "极端流动性条件下盈利崩溃，建议实施流动性监控和熔断机制"
            )
        if results[2]['retention'] < 0.6:
            recommendations.append(
                "中度流动性压力下表现不佳，建议优化流动性自适应逻辑"
            )

        return RealityTestReport(
            test_name=test_name,
            result=result,
            score=score,
            baseline_pnl=baseline_pnl or 0,
            stressed_pnl=results[-1]['pnl'],
            pnl_retention=results[-1]['retention'],
            details={
                'liquidity_results': results
            },
            recommendations=recommendations
        )

    def _adversarial_trading_test(self) -> RealityTestReport:
        """
        对抗性交易测试

        模拟有毒订单流和逆向选择:
        -  spoofing订单
        -  虚假突破
        -  逆向选择压力
        """
        test_name = "5. 对抗性交易测试 (Adversarial Trading)"

        attack_types = [
            {'name': 'None', 'spoof_prob': 0.0, 'fakeout_prob': 0.0},
            {'name': 'Light', 'spoof_prob': 0.1, 'fakeout_prob': 0.05},
            {'name': 'Moderate', 'spoof_prob': 0.2, 'fakeout_prob': 0.1},
            {'name': 'Heavy', 'spoof_prob': 0.3, 'fakeout_prob': 0.15},
            {'name': 'Extreme', 'spoof_prob': 0.5, 'fakeout_prob': 0.25},
        ]

        results = []
        baseline_pnl = None

        for attack in attack_types:
            attacked_data = self._inject_adversarial_attacks(
                self.data,
                spoof_prob=attack['spoof_prob'],
                fakeout_prob=attack['fakeout_prob']
            )
            pnl = self._run_backtest(attacked_data)

            if attack['name'] == 'None':
                baseline_pnl = pnl
                retention = 1.0
            else:
                retention = pnl / baseline_pnl if baseline_pnl != 0 else 0

            results.append({
                'attack_type': attack['name'],
                'pnl': pnl,
                'retention': retention
            })

        # 计算得分
        avg_retention = np.mean([r['retention'] for r in results[2:]])  # 中到高攻击
        score = max(0, min(100, avg_retention * 100))

        if score >= 60:
            result = TestResult.PASS
        elif score >= 40:
            result = TestResult.WARNING
        else:
            result = TestResult.FAIL

        recommendations = []
        if results[-1]['retention'] < 0:
            recommendations.append(
                "极端对抗环境下亏损，建议增强 spoofing 检测和过滤"
            )
        if results[2]['retention'] < 0.5:
            recommendations.append(
                "中度攻击下盈利显著下降，建议实施更严格的信号验证"
            )

        return RealityTestReport(
            test_name=test_name,
            result=result,
            score=score,
            baseline_pnl=baseline_pnl or 0,
            stressed_pnl=results[-1]['pnl'],
            pnl_retention=results[-1]['retention'],
            details={
                'adversarial_results': results
            },
            recommendations=recommendations
        )

    # ===== 辅助方法 =====

    def _inject_latency(self, data: pd.DataFrame, latency_ms: int) -> pd.DataFrame:
        """注入延迟"""
        if latency_ms == 0:
            return data.copy()

        delayed = data.copy()
        # 模拟延迟：使用过去的价格
        shift_periods = max(1, latency_ms // 10)  # 假设10ms一个tick
        for col in ['open', 'high', 'low', 'close']:
            if col in delayed.columns:
                delayed[col] = delayed[col].shift(shift_periods)

        return delayed.dropna()

    def _inject_market_impact(self, data: pd.DataFrame, order_size: float) -> pd.DataFrame:
        """注入市场冲击"""
        impacted = data.copy()
        # 简化的市场冲击模型
        impact = 0.0001 * np.log(1 + order_size * 10)  # 对数冲击模型

        if 'close' in impacted.columns:
            impacted['close'] = impacted['close'] * (1 + impact * np.random.randn(len(impacted)) * 0.1)

        return impacted

    def _inject_liquidity_stress(
        self,
        data: pd.DataFrame,
        depth_factor: float,
        spread_factor: float
    ) -> pd.DataFrame:
        """注入流动性压力"""
        stressed = data.copy()

        # 扩大价差
        if 'close' in stressed.columns and 'open' in stressed.columns:
            mid = (stressed['high'] + stressed['low']) / 2
            spread = (stressed['high'] - stressed['low']) * spread_factor
            stressed['high'] = mid + spread / 2
            stressed['low'] = mid - spread / 2

        # 减少成交量
        if 'volume' in stressed.columns:
            stressed['volume'] = stressed['volume'] * depth_factor

        return stressed

    def _inject_adversarial_attacks(
        self,
        data: pd.DataFrame,
        spoof_prob: float,
        fakeout_prob: float
    ) -> pd.DataFrame:
        """注入对抗性攻击"""
        attacked = data.copy()
        n = len(attacked)

        # Spoofing: 虚假的价格波动
        spoof_mask = np.random.random(n) < spoof_prob
        if 'close' in attacked.columns:
            attacked.loc[spoof_mask, 'close'] = attacked.loc[spoof_mask, 'close'] * (
                1 + np.random.randn(spoof_mask.sum()) * 0.002
            )

        # Fakeout: 虚假突破后快速反转
        fakeout_mask = np.random.random(n) < fakeout_prob
        for i in range(1, n):
            if fakeout_mask[i]:
                # 制造假突破后反转
                if 'close' in attacked.columns:
                    attacked.iloc[i] = attacked.iloc[i - 1] * 0.998

        return attacked

    def _estimate_impact_cost(self, order_size: float) -> float:
        """估计冲击成本"""
        # 简化的冲击成本模型
        return 0.0001 * np.log(1 + order_size * 10)

    def _run_backtest(
        self,
        data: pd.DataFrame,
        slippage: float = 0,
        max_position: float = 0.1
    ) -> float:
        """
        运行简化回测

        Returns:
            净利润 (PnL)
        """
        try:
            from local_trading import LocalTrader, LocalTradingConfig
            from local_trading.data_source import DataFrameDataSource

            config = LocalTradingConfig(
                symbol="BTCUSDT",
                initial_capital=self.initial_capital,
                max_position=max_position,
                maker_fee=0.0002 + slippage,
                taker_fee=0.0005 + slippage
            )

            trader = LocalTrader(config)
            data_source = DataFrameDataSource(data, symbol="BTCUSDT")
            data_source.load()
            trader.set_data_source(data_source)

            result = trader.run_backtest(progress_interval=999999)
            return result.total_return

        except Exception as e:
            logger.error(f"Backtest error: {e}")
            return self._simple_backtest(data, slippage)

    def _simple_backtest(self, data: pd.DataFrame, slippage: float = 0) -> float:
        """简化回测 (降级方案)"""
        returns = []

        for i in range(len(data) - 1):
            row = data.iloc[i]
            next_row = data.iloc[i + 1]

            close = row.get('close', 0)
            next_close = next_row.get('close', 0)

            if close <= 0:
                continue

            # 简单的均值回归信号
            signal = 0
            if 'open' in row:
                change = (close - row['open']) / row['open']
                if change < -0.001:
                    signal = 1
                elif change > 0.001:
                    signal = -1

            if signal != 0:
                price_change = (next_close - close) / close
                trade_return = signal * price_change - slippage
                returns.append(trade_return)

        if not returns:
            return 0.0

        return self.initial_capital * np.sum(returns)

    # ===== 报告生成 =====

    def _print_report(self, report: RealityTestReport):
        """打印单个测试报告"""
        symbol = {
            TestResult.PASS: '[PASS]',
            TestResult.WARNING: '[WARN]',
            TestResult.FAIL: '[FAIL]'
        }.get(report.result, '[?]')

        print(f"{symbol} {report.test_name}")
        print(f"   Score: {report.score:.1f}/100")
        print(f"   Baseline PnL: ${report.baseline_pnl:,.2f}")
        print(f"   Stressed PnL: ${report.stressed_pnl:,.2f}")
        print(f"   Retention: {report.pnl_retention:.1%}")

        if report.recommendations:
            print("   Recommendations:")
            for rec in report.recommendations:
                print(f"      - {rec}")
        print()

    def _generate_final_report(self) -> ExecutionRealityReport:
        """生成最终报告"""
        scores = [r.score for r in self.reports]
        overall_score = np.mean(scores)

        if overall_score >= 70:
            overall_result = TestResult.PASS
            summary = "执行引擎通过真实性检验，盈利具有较高可信度"
        elif overall_score >= 50:
            overall_result = TestResult.WARNING
            summary = "执行引擎存在部分风险，建议在改进后重新测试"
        else:
            overall_result = TestResult.FAIL
            summary = "执行引擎未通过真实性检验，盈利可能存在模拟器偏差"

        all_recommendations = []
        for report in self.reports:
            all_recommendations.extend(report.recommendations)

        return ExecutionRealityReport(
            timestamp=datetime.now(),
            overall_score=overall_score,
            overall_result=overall_result,
            individual_tests=self.reports,
            summary=summary,
            recommendations=list(set(all_recommendations))  # 去重
        )

    def _print_final_report(self):
        """打印最终报告"""
        print("=" * 80)
        print("         FINAL REALITY REPORT")
        print("=" * 80)

        report = self.final_report
        symbol = {
            TestResult.PASS: '[REAL]',
            TestResult.WARNING: '[RISKY]',
            TestResult.FAIL: '[FAKE]'
        }.get(report.overall_result, '[?]')

        print(f"\n{symbol} Overall Result: {report.overall_result.value}")
        print(f"Overall Score: {report.overall_score:.1f}/100")
        print(f"\nSummary: {report.summary}")

        if report.recommendations:
            print("\nRecommendations:")
            for rec in report.recommendations:
                print(f"   - {rec}")

        print("\n" + "=" * 80)

    def save_report(self, filepath: str):
        """保存报告到文件"""
        import json

        report = {
            'timestamp': self.final_report.timestamp.isoformat(),
            'overall_score': self.final_report.overall_score,
            'overall_result': self.final_report.overall_result.value,
            'summary': self.final_report.summary,
            'recommendations': self.final_report.recommendations,
            'individual_tests': [
                {
                    'test_name': r.test_name,
                    'result': r.result.value,
                    'score': r.score,
                    'baseline_pnl': r.baseline_pnl,
                    'stressed_pnl': r.stressed_pnl,
                    'pnl_retention': r.pnl_retention,
                    'details': r.details,
                    'recommendations': r.recommendations
                }
                for r in self.reports
            ]
        }

        with open(filepath, 'w') as f:
            json.dump(report, f, indent=2, default=str)

        logger.info(f"Reality test report saved: {filepath}")


# ===== 便捷函数 =====

def run_execution_reality_check(
    data: pd.DataFrame,
    strategy_factory: Optional[Callable] = None,
    initial_capital: float = 10000.0
) -> ExecutionRealityReport:
    """
    快速运行执行层真实性检验

    Args:
        data: 市场数据
        strategy_factory: 策略工厂函数
        initial_capital: 初始资金

    Returns:
        真实性检验报告
    """
    if strategy_factory is None:
        def default_factory(**kwargs):
            return kwargs
        strategy_factory = default_factory

    suite = ExecutionRealitySuite(
        strategy_factory=strategy_factory,
        data=data,
        initial_capital=initial_capital
    )

    return suite.run_all_tests(verbose=True)


if __name__ == "__main__":
    # 简单测试
    print("=" * 80)
    print("Execution Reality Suite - Simple Test")
    print("=" * 80)

    # 创建模拟数据
    np.random.seed(42)
    n = 1000
    data = pd.DataFrame({
        'open': np.cumsum(np.random.normal(0, 1, n)) + 50000,
        'high': np.cumsum(np.random.normal(0, 1, n)) + 50100,
        'low': np.cumsum(np.random.normal(0, 1, n)) + 49900,
        'close': np.cumsum(np.random.normal(0, 1, n)) + 50000,
        'volume': np.random.uniform(100, 1000, n)
    })
    data.index = pd.date_range('2024-01-01', periods=n, freq='1min')

    # 运行检验
    report = run_execution_reality_check(data, initial_capital=10000.0)

    # 保存报告
    suite = ExecutionRealitySuite(lambda **x: x, data)
    suite.reports = report.individual_tests
    suite.final_report = report
    suite.save_report('execution_reality_report.json')

    print("\n报告已保存: execution_reality_report.json")
