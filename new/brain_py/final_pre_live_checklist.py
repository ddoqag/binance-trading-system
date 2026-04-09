"""
Final Pre-Live Checklist (实盘前终极审判)

三关验证：
1. Causality Test - Execution是否因果一致
2. Parameter Stability - 0.8是区间还是点
3. PnL Attribution - 利润来源拆解
"""

import numpy as np
import pandas as pd
from scipy import stats
from typing import Dict, List
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """验证结果"""
    test_name: str
    passed: bool
    score: float
    details: Dict
    verdict: str


class FinalPreLiveChecklist:
    """
    实盘前终极审判

    目标：给出明确结论
    - ✅ 可以小资金上线
    - ⚠️ 需要修补
    - ❌ 不可上线
    """

    def __init__(self, data: pd.DataFrame):
        self.data = data
        self.results: List[ValidationResult] = []

    def run_all_checks(self, strategy_class) -> Dict:
        """运行所有验证"""
        print("=" * 80)
        print("       FINAL PRE-LIVE CHECKLIST (实盘前终极审判)")
        print("=" * 80)

        # Gate 1: Causality Test
        print("\n" + "=" * 80)
        print("GATE 1: CAUSALITY TEST (因果一致性验证)")
        print("=" * 80)
        causality = self._run_causality_test(strategy_class)
        self.results.append(causality)

        # Gate 2: Parameter Stability
        print("\n" + "=" * 80)
        print("GATE 2: PARAMETER STABILITY (参数稳定性)")
        print("=" * 80)
        stability = self._run_parameter_stability(strategy_class)
        self.results.append(stability)

        # Gate 3: PnL Attribution
        print("\n" + "=" * 80)
        print("GATE 3: PNL ATTRIBUTION (利润来源拆解)")
        print("=" * 80)
        attribution = self._run_pnl_attribution(strategy_class)
        self.results.append(attribution)

        # Final Verdict
        return self._generate_final_verdict()

    def _run_causality_test(self, strategy_class) -> ValidationResult:
        """
        因果一致性测试

        验证Execution是否在"选择性执行"好信号
        """
        from forcefill_three_mode import ForceFillThreeMode

        print("\n[1.1] Alpha-only Mode (Baseline)")
        strategy = strategy_class(threshold=0.8)
        tester = ForceFillThreeMode(strategy, self.data, initial_capital=1000.0)
        alpha_result = tester._run_alpha_only()
        print(f"  Sharpe: {alpha_result['sharpe']:.2f}, Trades: {alpha_result['n_trades']}")

        print("\n[1.2] Forced Execution Mode (All signals executed)")
        # 修改执行逻辑，强制成交所有信号
        forced_result = self._run_forced_execution(strategy_class)
        print(f"  Sharpe: {forced_result['sharpe']:.2f}, Trades: {forced_result['n_trades']}")

        print("\n[1.3] Full System Mode (Current)")
        strategy = strategy_class(threshold=0.8)
        tester = ForceFillThreeMode(strategy, self.data, initial_capital=1000.0)
        full_result = tester._run_full_system()
        print(f"  Sharpe: {full_result['sharpe']:.2f}, Trades: {full_result['n_trades']}")

        # 分析
        alpha_sharpe = alpha_result['sharpe']
        forced_sharpe = forced_result['sharpe']
        full_sharpe = full_result['sharpe']

        print("\n[1.4] Causality Analysis:")
        print(f"  Alpha: {alpha_sharpe:.2f}")
        print(f"  Forced: {forced_sharpe:.2f}")
        print(f"  Full: {full_sharpe:.2f}")

        # 关键判断
        if full_sharpe > forced_sharpe * 1.2:
            # Full显著优于Forced，说明Execution在"挑信号"
            passed = False
            verdict = "SIGNAL_SELECTION_BIAS"
            reason = "Full >> Forced: Execution may be selectively executing good signals"
        elif abs(full_sharpe - forced_sharpe) < 0.5:
            # Full和Forced接近，说明Execution没有选择性
            passed = True
            verdict = "CAUSALITY_VERIFIED"
            reason = "Full ≈ Forced: Execution is causal and consistent"
        elif forced_sharpe > alpha_sharpe:
            # Forced > Alpha，说明Execution本身有优势
            passed = True
            verdict = "EXECUTION_ADVANTAGE"
            reason = "Forced > Alpha: Execution layer has genuine advantage"
        else:
            passed = False
            verdict = "UNCERTAIN"
            reason = "Pattern unclear, needs more investigation"

        print(f"\n  Verdict: {verdict}")
        print(f"  Reason: {reason}")

        return ValidationResult(
            test_name="Causality Test",
            passed=passed,
            score=1.0 if passed else 0.0,
            details={
                'alpha_sharpe': alpha_sharpe,
                'forced_sharpe': forced_sharpe,
                'full_sharpe': full_sharpe
            },
            verdict=verdict
        )

    def _run_forced_execution(self, strategy_class) -> Dict:
        """强制执行所有信号，不进行选择"""
        strategy = strategy_class(threshold=0.8)
        trades = []
        pnl_history = []

        for i in range(len(self.data) - 1):
            tick = self.data.iloc[i]
            next_tick = self.data.iloc[i + 1]

            # 构建orderbook
            orderbook = {
                'bid_price': tick.get('bid_price', tick.get('low', 0)),
                'ask_price': tick.get('ask_price', tick.get('high', 0)),
                'mid_price': tick.get('mid_price', (tick.get('bid_price', 0) + tick.get('ask_price', 0)) / 2)
            }

            signal = strategy.generate_signal(orderbook)

            if abs(signal.get('direction', 0)) > 0.3:
                # 强制成交（简化版）
                side = 'buy' if signal['direction'] > 0 else 'sell'
                quantity = signal.get('quantity', 0.1)

                # 模拟执行成本
                execution_cost = 0.001

                if side == 'buy':
                    fill_price = orderbook['ask_price'] * (1 + execution_cost)
                    exit_price = next_tick.get('mid_price', next_tick.get('close', fill_price))
                    pnl = (exit_price - fill_price) * quantity
                else:
                    fill_price = orderbook['bid_price'] * (1 - execution_cost)
                    exit_price = next_tick.get('mid_price', next_tick.get('close', fill_price))
                    pnl = (fill_price - exit_price) * quantity

                pnl_history.append(pnl)
                trades.append({'pnl': pnl, 'side': side})

        # 计算指标
        if not trades:
            return {'sharpe': 0, 'n_trades': 0}

        pnls = [t['pnl'] for t in trades]
        if len(pnls) > 1 and np.std(pnls) > 0:
            sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(252)
        else:
            sharpe = 0

        return {'sharpe': sharpe, 'n_trades': len(trades)}

    def _run_parameter_stability(self, strategy_class) -> ValidationResult:
        """
        参数稳定性测试

        验证0.8是稳定区间还是过拟合点
        """
        print("\n[2.1] Fine-grained threshold scan (0.75 - 0.85)")

        thresholds = np.linspace(0.75, 0.85, 11)
        results = []

        for threshold in thresholds:
            from forcefill_three_mode import ForceFillThreeMode
            strategy = strategy_class(threshold=threshold)
            tester = ForceFillThreeMode(strategy, self.data, initial_capital=1000.0)
            result = tester._run_full_system()

            results.append({
                'threshold': threshold,
                'sharpe': result['sharpe'],
                'trades': result['n_trades']
            })

        # 打印结果
        print(f"\n  {'Threshold':<12} {'Sharpe':<10} {'Trades':<10}")
        print(f"  {'-'*32}")
        for r in results:
            marker = " <--" if abs(r['threshold'] - 0.8) < 0.01 else ""
            print(f"  {r['threshold']:<12.3f} {r['sharpe']:<10.2f} {r['trades']:<10}{marker}")

        # 分析稳定性
        sharpes = [r['sharpe'] for r in results]
        max_sharpe = max(sharpes)
        min_sharpe = min(sharpes)
        std_sharpe = np.std(sharpes)

        # 找到最佳点
        best_idx = sharpes.index(max_sharpe)
        best_threshold = results[best_idx]['threshold']

        # 判断稳定性
        print(f"\n[2.2] Stability Analysis:")
        print(f"  Max Sharpe: {max_sharpe:.2f} at threshold={best_threshold:.3f}")
        print(f"  Min Sharpe: {min_sharpe:.2f}")
        print(f"  Std Dev: {std_sharpe:.2f}")

        # 关键判断
        # 1. 最佳点是否正好是0.8？
        is_08_optimal = abs(best_threshold - 0.8) < 0.01

        # 2. 0.8附近的Sharpe是否稳定？
        near_08 = [r['sharpe'] for r in results if 0.78 <= r['threshold'] <= 0.82]
        near_08_std = np.std(near_08) if len(near_08) > 1 else float('inf')

        # 3. 整个区间的变异系数
        cv = std_sharpe / abs(np.mean(sharpes)) if np.mean(sharpes) != 0 else float('inf')

        if is_08_optimal and near_08_std < 1.0:
            passed = True
            verdict = "STABLE_SWEET_SPOT"
            reason = "0.8 is a stable sweet spot with consistent performance nearby"
        elif std_sharpe > 2.0:
            passed = False
            verdict = "HIGH_VARIANCE"
            reason = f"High variance (std={std_sharpe:.2f}) suggests overfitting"
        elif cv > 0.5:
            passed = False
            verdict = "UNSTABLE"
            reason = f"Coefficient of variation ({cv:.2f}) indicates instability"
        else:
            passed = True
            verdict = "ACCEPTABLE"
            reason = "Performance is reasonably stable across threshold range"

        print(f"\n  Near-0.8 std: {near_08_std:.2f}")
        print(f"  Coefficient of variation: {cv:.2f}")
        print(f"\n  Verdict: {verdict}")
        print(f"  Reason: {reason}")

        return ValidationResult(
            test_name="Parameter Stability",
            passed=passed,
            score=1.0 if passed else 0.0,
            details={
                'thresholds': [r['threshold'] for r in results],
                'sharpes': sharpes,
                'best_threshold': best_threshold,
                'stability_std': std_sharpe
            },
            verdict=verdict
        )

    def _run_pnl_attribution(self, strategy_class) -> ValidationResult:
        """
        PnL归因分析

        拆解利润来源
        """
        print("\n[3.1] PnL Attribution Analysis")

        strategy = strategy_class(threshold=0.8)

        # 收集交易详情
        trades = []

        for i in range(len(self.data) - 1):
            tick = self.data.iloc[i]
            next_tick = self.data.iloc[i + 1]

            orderbook = {
                'bid_price': tick.get('bid_price', tick.get('low', 0)),
                'ask_price': tick.get('ask_price', tick.get('high', 0)),
                'mid_price': tick.get('mid_price', (tick.get('bid_price', 0) + tick.get('ask_price', 0)) / 2)
            }

            signal = strategy.generate_signal(orderbook)

            if abs(signal.get('direction', 0)) > 0.3:
                side = 'buy' if signal['direction'] > 0 else 'sell'
                quantity = signal.get('quantity', 0.1)

                # 记录交易详情
                entry_price = orderbook['ask_price'] if side == 'buy' else orderbook['bid_price']
                exit_price = next_tick.get('mid_price', next_tick.get('close', entry_price))

                if side == 'buy':
                    price_move_pnl = (exit_price - entry_price) / entry_price
                else:
                    price_move_pnl = (entry_price - exit_price) / entry_price

                # 估算点差捕获（简化版）
                spread = orderbook['ask_price'] - orderbook['bid_price']
                mid = orderbook['mid_price']
                spread_capture = (spread / mid) * 0.5  # 假设捕获一半点差

                trades.append({
                    'side': side,
                    'price_move_pnl': price_move_pnl,
                    'spread_capture': spread_capture,
                    'total_pnl': price_move_pnl + spread_capture
                })

        if not trades:
            return ValidationResult(
                test_name="PnL Attribution",
                passed=False,
                score=0.0,
                details={},
                verdict="NO_TRADES"
            )

        # 计算归因
        total_price_move = sum(t['price_move_pnl'] for t in trades)
        total_spread = sum(t['spread_capture'] for t in trades)
        total_pnl = sum(t['total_pnl'] for t in trades)

        # 分类统计
        winning_trades = [t for t in trades if t['total_pnl'] > 0]
        losing_trades = [t for t in trades if t['total_pnl'] <= 0]

        print(f"\n  Total trades: {len(trades)}")
        print(f"  Win rate: {len(winning_trades)/len(trades):.1%}")

        print(f"\n  PnL Attribution:")
        print(f"    Price movement: {total_price_move:.4f} ({total_price_move/total_pnl:.1%})")
        print(f"    Spread capture: {total_spread:.4f} ({total_spread/total_pnl:.1%})")
        print(f"    Total PnL:      {total_pnl:.4f}")

        print(f"\n  Winning trades ({len(winning_trades)}):")
        win_price_move = sum(t['price_move_pnl'] for t in winning_trades)
        win_spread = sum(t['spread_capture'] for t in winning_trades)
        print(f"    Avg price move: {win_price_move/len(winning_trades):.4f}")
        print(f"    Avg spread cap: {win_spread/len(winning_trades):.4f}")

        print(f"\n  Losing trades ({len(losing_trades)}):")
        if losing_trades:
            lose_price_move = sum(t['price_move_pnl'] for t in losing_trades)
            lose_spread = sum(t['spread_capture'] for t in losing_trades)
            print(f"    Avg price move: {lose_price_move/len(losing_trades):.4f}")
            print(f"    Avg spread cap: {lose_spread/len(losing_trades):.4f}")

        # 关键判断
        price_move_ratio = total_price_move / total_pnl if total_pnl != 0 else 0

        if price_move_ratio > 0.7:
            passed = True
            verdict = "HEALTHY_ALPHA"
            reason = f"{price_move_ratio:.1%} of PnL from price movement - genuine trend alpha"
        elif price_move_ratio > 0.3:
            passed = True
            verdict = "MIXED"
            reason = f"Mixed sources: {price_move_ratio:.1%} price, {1-price_move_ratio:.1%} execution"
        else:
            passed = False
            verdict = "PSEUDO_MARKET_MAKING"
            reason = f"Only {price_move_ratio:.1%} from price move - mostly spread capture"

        print(f"\n  Verdict: {verdict}")
        print(f"  Reason: {reason}")

        return ValidationResult(
            test_name="PnL Attribution",
            passed=passed,
            score=price_move_ratio,
            details={
                'price_move_pnl': total_price_move,
                'spread_capture': total_spread,
                'total_pnl': total_pnl,
                'price_move_ratio': price_move_ratio
            },
            verdict=verdict
        )

    def _generate_final_verdict(self) -> Dict:
        """生成最终判决"""
        print("\n" + "=" * 80)
        print("       FINAL VERDICT")
        print("=" * 80)

        # 统计
        passed_count = sum(1 for r in self.results if r.passed)
        total_score = sum(r.score for r in self.results)
        max_score = len(self.results)

        print(f"\nTest Results:")
        for r in self.results:
            status = "PASS" if r.passed else "FAIL"
            print(f"  [{status}] {r.test_name}: {r.verdict}")

        print(f"\nScore: {total_score:.1f}/{max_score}")
        print(f"Tests passed: {passed_count}/{len(self.results)}")

        # 综合判决
        if passed_count >= 3 and total_score >= 2.5:
            grade = "A"
            verdict = "READY_FOR_SMALL_SCALE_LIVE"
            recommendation = "Strategy passed all critical checks. Can proceed with small capital (< $1000) live trading."
        elif passed_count >= 2 and total_score >= 1.5:
            grade = "B"
            verdict = "CONDITIONAL_READY"
            recommendation = "Strategy shows promise but has minor issues. Proceed with caution and tight risk limits."
        elif passed_count >= 1:
            grade = "C"
            verdict = "NEEDS_IMPROVEMENT"
            recommendation = "Strategy has significant issues. Requires further development before live."
        else:
            grade = "D"
            verdict = "NOT_READY"
            recommendation = "Strategy failed critical checks. Not suitable for live trading."

        print(f"\n{'='*80}")
        print(f"Grade: {grade}")
        print(f"Verdict: {verdict}")
        print(f"Recommendation: {recommendation}")
        print(f"{'='*80}")

        return {
            'tests': [
                {
                    'name': r.test_name,
                    'passed': r.passed,
                    'score': r.score,
                    'verdict': r.verdict
                }
                for r in self.results
            ],
            'total_score': total_score,
            'max_score': max_score,
            'grade': grade,
            'verdict': verdict,
            'recommendation': recommendation
        }


if __name__ == "__main__":
    print("=" * 80)
    print("Final Pre-Live Checklist")
    print("=" * 80)

    from data_fetcher import BinanceDataFetcher
    from test_fixed_strategy_three_mode import FixedTrendStrategy

    # 加载数据
    fetcher = BinanceDataFetcher()
    df = fetcher.fetch_klines('BTCUSDT', '1h', limit=1000)
    tick_df = fetcher.convert_to_tick_format(df)

    # 运行完整检查
    checklist = FinalPreLiveChecklist(tick_df)
    result = checklist.run_all_checks(FixedTrendStrategy)

    print("\n" + "=" * 80)
    print("Checklist Complete")
    print("=" * 80)
