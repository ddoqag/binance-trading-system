"""
Alpha信号分层测试 (Signal Decile Test)
核心：验证信号是否具有排序能力 (ranking power)
"""

import numpy as np
import pandas as pd
from scipy import stats
from typing import Dict, List, Tuple


class AlphaDecileTest:
    """
    Alpha信号分层测试

    将信号分成10组（deciles），检查每组未来的收益表现
    健康的Alpha应该呈现单调递减/递增关系
    """

    def __init__(self, data: pd.DataFrame):
        self.data = data
        self.signals = []
        self.returns = []

    def run_decile_analysis(self, lookahead_periods: List[int] = [1, 5, 10, 20]) -> Dict:
        """
        运行分层分析

        Returns:
            Dict: 包含每层收益、单调性检验、IC分析
        """
        print("=" * 70)
        print("       ALPHA DECILE TEST - Ranking Power Analysis")
        print("=" * 70)

        # 1. 收集信号和未来收益
        print("\n[1] Collecting signals and future returns...")
        self._collect_data(lookahead_periods)

        if len(self.signals) < 100:
            return {
                'verdict': 'INSUFFICIENT_DATA',
                'reason': f'Only {len(self.signals)} samples'
            }

        print(f"  Collected {len(self.signals)} signal-return pairs")

        results = {}

        for period in lookahead_periods:
            print(f"\n[2] Analyzing period t+{period}...")
            result = self._analyze_period(period)
            results[f't+{period}'] = result

        # 综合评估
        final_verdict = self._generate_comprehensive_verdict(results)

        return {
            'period_results': results,
            'final_verdict': final_verdict,
            'sample_size': len(self.signals)
        }

    def _collect_data(self, lookahead_periods: List[int]):
        """收集信号和未来收益数据"""
        for i in range(len(self.data) - max(lookahead_periods)):
            tick = self.data.iloc[i]

            # 计算信号（修复后的趋势跟踪逻辑）
            signal = self._calculate_signal(tick, i)

            if signal is not None:
                # 计算各周期的未来收益
                future_returns = {}
                for period in lookahead_periods:
                    if i + period < len(self.data):
                        future_tick = self.data.iloc[i + period]
                        future_return = self._calculate_return(tick, future_tick)
                        future_returns[f'return_{period}'] = future_return

                self.signals.append({
                    'timestamp': i,
                    'score': signal['score'],
                    'direction': signal['direction'],
                    'position_in_range': signal['position_in_range']
                })

                self.returns.append(future_returns)

    def _calculate_signal(self, tick: pd.Series, index: int) -> Dict:
        """计算Alpha信号（修复后的趋势跟踪版本）"""
        bid = tick.get('bid_price', tick.get('low', tick.get('close', 0)))
        ask = tick.get('ask_price', tick.get('high', tick.get('close', 0)))
        mid = tick.get('mid_price', (bid + ask) / 2)
        spread = ask - bid

        if mid <= 0 or spread <= 0:
            return None

        spread_bps = (spread / mid) * 10000

        if spread_bps < 2:
            return None

        # 获取近期价格范围
        lookback = min(20, index)
        if lookback < 5:
            return None

        recent_prices = [self.data.iloc[j].get('mid_price', mid)
                        for j in range(index - lookback, index + 1)]
        price_min = min(recent_prices)
        price_max = max(recent_prices)

        if price_max <= price_min:
            return None

        position_in_range = (mid - price_min) / (price_max - price_min)

        # 修复后的逻辑：趋势跟踪
        # 价格高位 -> 看涨信号
        # 价格低位 -> 看跌信号
        if position_in_range > 0.7:
            return {
                'score': position_in_range,  # 高分 = 看涨
                'direction': 1,
                'position_in_range': position_in_range
            }
        elif position_in_range < 0.3:
            return {
                'score': -(1 - position_in_range),  # 负分 = 看跌
                'direction': -1,
                'position_in_range': position_in_range
            }

        return None

    def _calculate_return(self, current_tick: pd.Series, future_tick: pd.Series) -> float:
        """计算收益率"""
        current_mid = current_tick.get('mid_price',
            (current_tick.get('bid_price', 0) + current_tick.get('ask_price', 0)) / 2)
        future_mid = future_tick.get('mid_price',
            (future_tick.get('bid_price', 0) + future_tick.get('ask_price', 0)) / 2)

        if current_mid <= 0 or future_mid <= 0:
            return 0

        return (future_mid - current_mid) / current_mid

    def _analyze_period(self, period: int) -> Dict:
        """分析特定周期的分层表现"""
        col = f'return_{period}'

        # 提取数据
        scores = []
        returns = []

        for i, signal in enumerate(self.signals):
            if i < len(self.returns) and col in self.returns[i]:
                scores.append(signal['score'])
                returns.append(self.returns[i][col])

        if len(scores) < 50:
            return {
                'verdict': 'INSUFFICIENT_DATA',
                'sample_size': len(scores)
            }

        # 分成10组（deciles）
        try:
            decile_labels = pd.qcut(scores, 10, labels=False, duplicates='drop')
            n_deciles = len(np.unique(decile_labels))
        except:
            return {
                'verdict': 'DECILE_ERROR',
                'reason': 'Could not create deciles'
            }

        # 计算每组的平均收益
        decile_returns = []
        decile_counts = []

        for d in range(n_deciles):
            mask = decile_labels == d
            decile_return = np.mean([returns[i] for i in range(len(returns)) if mask[i]])
            decile_count = sum(mask)
            decile_returns.append(decile_return)
            decile_counts.append(decile_count)

        # 计算单调性
        monotonicity = self._calculate_monotonicity(decile_returns)

        # 计算Rank IC
        if len(scores) > 10 and np.std(scores) > 0 and np.std(returns) > 0:
            rank_ic, p_value = stats.spearmanr(scores, returns)
        else:
            rank_ic, p_value = 0, 1

        # 计算多空组合收益（第10组 - 第1组）
        long_short_return = decile_returns[-1] - decile_returns[0] if len(decile_returns) >= 2 else 0

        # 计算每层统计
        decile_stats = []
        for d in range(n_deciles):
            mask = decile_labels == d
            decile_rets = [returns[i] for i in range(len(returns)) if mask[i]]

            decile_stats.append({
                'decile': d + 1,
                'count': decile_counts[d],
                'mean_return': decile_returns[d],
                'std': np.std(decile_rets) if len(decile_rets) > 1 else 0,
                'win_rate': sum(1 for r in decile_rets if r > 0) / len(decile_rets) if decile_rets else 0
            })

        # 打印结果
        print(f"\n  Decile Analysis (t+{period}):")
        print(f"  {'Decile':<10} {'Count':<8} {'Mean Return':<12} {'Win Rate':<10}")
        print(f"  {'-'*42}")
        for stat in decile_stats:
            print(f"  {stat['decile']:<10} {stat['count']:<8} {stat['mean_return']:>11.4f} {stat['win_rate']:>9.1%}")

        print(f"\n  Monotonicity: {monotonicity:.2f}")
        print(f"  Rank IC: {rank_ic:.4f} (p={p_value:.4f})")
        print(f"  Long-Short Return: {long_short_return:.4f}")

        # 判断
        if abs(rank_ic) > 0.1 and p_value < 0.05 and monotonicity > 0.5:
            verdict = "STRONG_RANKING"
        elif abs(rank_ic) > 0.05 and p_value < 0.1 and monotonicity > 0.3:
            verdict = "WEAK_RANKING"
        elif abs(rank_ic) > 0.02:
            verdict = "MARGINAL_RANKING"
        else:
            verdict = "NO_RANKING"

        return {
            'verdict': verdict,
            'n_deciles': n_deciles,
            'decile_stats': decile_stats,
            'monotonicity': monotonicity,
            'rank_ic': rank_ic,
            'rank_ic_pvalue': p_value,
            'long_short_return': long_short_return,
            'sample_size': len(scores)
        }

    def _calculate_monotonicity(self, decile_returns: List[float]) -> float:
        """计算单调性分数

        理想情况下，高分组应该有高收益
        返回：-1到1之间的值，1表示完全单调递增
        """
        if len(decile_returns) < 2:
            return 0

        # 计算相邻组的收益变化方向
        correct_direction = 0
        total_comparisons = 0

        for i in range(1, len(decile_returns)):
            if decile_returns[i] > decile_returns[i-1]:
                correct_direction += 1
            elif decile_returns[i] < decile_returns[i-1]:
                correct_direction -= 1
            total_comparisons += 1

        return correct_direction / total_comparisons if total_comparisons > 0 else 0

    def _generate_comprehensive_verdict(self, results: Dict) -> Dict:
        """生成综合评估"""
        print("\n" + "=" * 70)
        print("       COMPREHENSIVE VERDICT")
        print("=" * 70)

        # 收集各周期结果
        rank_ics = [r['rank_ic'] for r in results.values() if 'rank_ic' in r]
        monotonicities = [r['monotonicity'] for r in results.values() if 'monotonicity' in r]
        verdicts = [r['verdict'] for r in results.values() if 'verdict' in r]

        avg_rank_ic = np.mean([abs(ic) for ic in rank_ics]) if rank_ics else 0
        avg_monotonicity = np.mean(monotonicities) if monotonicities else 0

        # 计算分层稳定性（跨周期的IC稳定性）
        ic_stability = np.std(rank_ics) if len(rank_ics) > 1 else 0

        print(f"\n  Average |Rank IC|: {avg_rank_ic:.4f}")
        print(f"  Average Monotonicity: {avg_monotonicity:.2f}")
        print(f"  IC Stability (std): {ic_stability:.4f}")

        # 评分系统
        score = 0

        # IC评分
        if avg_rank_ic > 0.1:
            score += 3
        elif avg_rank_ic > 0.05:
            score += 2
        elif avg_rank_ic > 0.02:
            score += 1

        # 单调性评分
        if avg_monotonicity > 0.6:
            score += 3
        elif avg_monotonicity > 0.4:
            score += 2
        elif avg_monotonicity > 0.2:
            score += 1

        # 稳定性评分
        if ic_stability < 0.02:
            score += 2
        elif ic_stability < 0.05:
            score += 1

        # 最终判决
        if score >= 6:
            verdict = "TRADEABLE_ALPHA"
            recommendation = "Signal has strong ranking power. Proceed with execution optimization."
        elif score >= 4:
            verdict = "WEAK_ALPHA"
            recommendation = "Signal has moderate ranking power. Consider feature engineering."
        elif score >= 2:
            verdict = "MARGINAL_ALPHA"
            recommendation = "Signal is marginal. High risk of overfitting."
        else:
            verdict = "NOISE"
            recommendation = "Signal lacks ranking power. Recommend redesign."

        print(f"\n  Quality Score: {score}/8")
        print(f"  Verdict: {verdict}")
        print(f"  Recommendation: {recommendation}")

        return {
            'score': score,
            'max_score': 8,
            'verdict': verdict,
            'recommendation': recommendation,
            'avg_rank_ic': avg_rank_ic,
            'avg_monotonicity': avg_monotonicity,
            'ic_stability': ic_stability,
            'period_verdicts': verdicts
        }


class AlphaQualityScorecard:
    """
    Alpha质量评分卡

    综合评估Alpha的可交易性
    """

    def __init__(self, data: pd.DataFrame):
        self.data = data

    def run_full_scorecard(self) -> Dict:
        """运行完整评分卡"""
        print("=" * 70)
        print("       ALPHA QUALITY SCORECARD")
        print("=" * 70)

        # 1. Decile Test
        print("\n[TEST 1] Decile Ranking Test")
        decile_test = AlphaDecileTest(self.data)
        decile_result = decile_test.run_decile_analysis()

        # 2. Win/Loss Analysis
        print("\n[TEST 2] Win/Loss Ratio Analysis")
        winloss_result = self._analyze_win_loss_ratio()

        # 3. Skew/Kurtosis Analysis
        print("\n[TEST 3] Return Distribution Analysis")
        distribution_result = self._analyze_distribution()

        # 综合评分
        final_score = self._calculate_final_score(
            decile_result, winloss_result, distribution_result
        )

        return {
            'decile_test': decile_result,
            'winloss_analysis': winloss_result,
            'distribution_analysis': distribution_result,
            'final_score': final_score
        }

    def _analyze_win_loss_ratio(self) -> Dict:
        """分析盈亏比"""
        trades = []

        for i in range(len(self.data) - 10):
            tick = self.data.iloc[i]
            future_tick = self.data.iloc[i + 10]

            # 简化：模拟交易
            signal = self._get_signal_direction(tick, i)

            if signal != 0:
                current_price = tick.get('mid_price', tick.get('close', 1))
                future_price = future_tick.get('mid_price', future_tick.get('close', 1))

                if current_price > 0 and future_price > 0:
                    if signal > 0:  # 做多
                        pnl = (future_price - current_price) / current_price
                    else:  # 做空
                        pnl = (current_price - future_price) / current_price

                    trades.append(pnl)

        if not trades:
            return {'verdict': 'NO_TRADES'}

        wins = [p for p in trades if p > 0]
        losses = [p for p in trades if p < 0]

        avg_win = np.mean(wins) if wins else 0
        avg_loss = abs(np.mean(losses)) if losses else 0

        win_rate = len(wins) / len(trades)
        loss_rate = len(losses) / len(trades)

        # 盈亏比
        if avg_loss > 0:
            payoff_ratio = avg_win / avg_loss
        else:
            payoff_ratio = float('inf')

        # 期望值
        expected_value = win_rate * avg_win - loss_rate * avg_loss

        print(f"  Total Trades: {len(trades)}")
        print(f"  Win Rate: {win_rate:.1%}")
        print(f"  Avg Win: {avg_win:.4f}")
        print(f"  Avg Loss: {avg_loss:.4f}")
        print(f"  Payoff Ratio: {payoff_ratio:.2f}")
        print(f"  Expected Value: {expected_value:.4f}")

        # 判断
        if expected_value > 0.001 and payoff_ratio > 1.0:
            verdict = "POSITIVE_EXPECTATION"
        elif expected_value > 0:
            verdict = "MARGINAL_EXPECTATION"
        else:
            verdict = "NEGATIVE_EXPECTATION"

        return {
            'verdict': verdict,
            'win_rate': win_rate,
            'payoff_ratio': payoff_ratio,
            'expected_value': expected_value,
            'avg_win': avg_win,
            'avg_loss': avg_loss
        }

    def _analyze_distribution(self) -> Dict:
        """分析收益分布"""
        returns = []

        for i in range(len(self.data) - 10):
            tick = self.data.iloc[i]
            future_tick = self.data.iloc[i + 10]

            current_price = tick.get('mid_price', tick.get('close', 1))
            future_price = future_tick.get('mid_price', future_tick.get('close', 1))

            if current_price > 0 and future_price > 0:
                ret = (future_price - current_price) / current_price
                returns.append(ret)

        if len(returns) < 30:
            return {'verdict': 'INSUFFICIENT_DATA'}

        skewness = stats.skew(returns)
        kurt = stats.kurtosis(returns)

        print(f"  Skewness: {skewness:.4f}")
        print(f"  Kurtosis: {kurt:.4f}")

        # 肥尾风险
        tail_risk = kurt > 3

        return {
            'skewness': skewness,
            'kurtosis': kurt,
            'tail_risk': tail_risk
        }

    def _get_signal_direction(self, tick: pd.Series, index: int) -> int:
        """获取信号方向"""
        bid = tick.get('bid_price', tick.get('low', tick.get('close', 0)))
        ask = tick.get('ask_price', tick.get('high', tick.get('close', 0)))
        mid = tick.get('mid_price', (bid + ask) / 2)

        if mid <= 0:
            return 0

        lookback = min(20, index)
        if lookback < 5:
            return 0

        recent_prices = [self.data.iloc[j].get('mid_price', mid)
                        for j in range(index - lookback, index + 1)]
        price_min = min(recent_prices)
        price_max = max(recent_prices)

        if price_max <= price_min:
            return 0

        position_in_range = (mid - price_min) / (price_max - price_min)

        if position_in_range > 0.7:
            return 1
        elif position_in_range < 0.3:
            return -1

        return 0

    def _calculate_final_score(self, decile: Dict, winloss: Dict, dist: Dict) -> Dict:
        """计算最终评分"""
        print("\n" + "=" * 70)
        print("       FINAL SCORECARD")
        print("=" * 70)

        score = 0
        max_score = 10

        # Decile Test贡献
        decile_score = decile.get('final_verdict', {}).get('score', 0)
        score += min(decile_score, 3)  # 最高3分

        # Win/Loss贡献
        if winloss.get('verdict') == 'POSITIVE_EXPECTATION':
            score += 3
        elif winloss.get('verdict') == 'MARGINAL_EXPECTATION':
            score += 1

        # Distribution贡献
        if not dist.get('tail_risk', True):
            score += 2

        # 最终等级
        if score >= 7:
            grade = "A - TRADEABLE"
            recommendation = "Ready for live trading with proper risk management"
        elif score >= 5:
            grade = "B - PROMISING"
            recommendation = "Good potential, optimize execution and parameters"
        elif score >= 3:
            grade = "C - MARGINAL"
            recommendation = "Weak signal, requires significant improvement"
        else:
            grade = "D - NOT TRADEABLE"
            recommendation = "Signal lacks quality, recommend redesign"

        print(f"\n  Total Score: {score}/{max_score}")
        print(f"  Grade: {grade}")
        print(f"  Recommendation: {recommendation}")

        return {
            'score': score,
            'max_score': max_score,
            'grade': grade,
            'recommendation': recommendation
        }


if __name__ == "__main__":
    print("=" * 70)
    print("Alpha Decile Test - Running Full Analysis")
    print("=" * 70)

    from data_fetcher import BinanceDataFetcher

    # 加载数据
    fetcher = BinanceDataFetcher()
    df = fetcher.fetch_klines('BTCUSDT', '1h', limit=1000)
    tick_df = fetcher.convert_to_tick_format(df)

    print(f"\nLoaded {len(tick_df)} ticks")

    # 运行完整评分卡
    scorecard = AlphaQualityScorecard(tick_df)
    results = scorecard.run_full_scorecard()

    print("\n" + "=" * 70)
    print("Analysis Complete")
    print("=" * 70)
