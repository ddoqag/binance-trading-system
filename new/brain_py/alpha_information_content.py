"""
Alpha信号信息含量检测套件
目标：科学评估Alpha信号是否包含预测信息
"""

import numpy as np
import pandas as pd
from scipy import stats
from collections import defaultdict
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class InformationContentResult:
    """信息含量结果"""
    has_information: bool
    ic_score: float
    direction_accuracy: float
    stability_score: float
    verdict: str
    recommendation: str


class AlphaInformationContent:
    """
    Alpha信号信息含量检测器

    评估信号是否真正包含预测信息，还是只是噪声
    """

    def __init__(self, data: pd.DataFrame):
        self.data = data
        self.alpha_scores: List[Dict] = []
        self.future_returns: List[Dict] = []

    def analyze_mvp_signal(self) -> Dict:
        """
        分析MVP策略的信号信息含量

        MVP策略使用简单规则：
        - 买点差：bid + min_spread * tick_size
        - 卖点差：ask - min_spread * tick_size
        """
        print("=" * 70)
        print("       ALPHA INFORMATION CONTENT ANALYSIS")
        print("=" * 70)

        # 1. 提取信号特征
        print("\n[1] Extracting signal characteristics...")
        self._extract_mvp_signals()

        if len(self.alpha_scores) == 0:
            return {
                'verdict': 'NO_SIGNALS',
                'reason': 'No alpha signals generated',
                'recommendation': 'Check signal generation logic'
            }

        print(f"  Collected {len(self.alpha_scores)} signal observations")

        # 2. 信号分布分析
        print("\n[2] Signal distribution analysis...")
        dist_analysis = self._analyze_signal_distribution()

        # 3. 预测能力分析
        print("\n[3] Predictive power analysis...")
        pred_analysis = self._analyze_predictive_power()

        # 4. 信息系数分析
        print("\n[4] Information coefficient analysis...")
        ic_analysis = self._analyze_information_coefficient()

        # 5. 综合评估
        print("\n[5] Comprehensive evaluation...")
        final_result = self._generate_final_verdict(
            dist_analysis, pred_analysis, ic_analysis
        )

        return {
            'distribution': dist_analysis,
            'predictive': pred_analysis,
            'information_coefficient': ic_analysis,
            'final_verdict': final_result
        }

    def _extract_mvp_signals(self):
        """提取MVP策略的信号特征"""
        # MVP策略的核心逻辑：
        # 1. 当 bid + min_spread < mid 时，买点差
        # 2. 当 ask - min_spread > mid 时，卖点差

        for i in range(len(self.data) - 10):  # 预留未来10个周期
            tick = self.data.iloc[i]

            # 获取价格
            bid = tick.get('bid_price', tick.get('low', tick.get('close', 0)))
            ask = tick.get('ask_price', tick.get('high', tick.get('close', 0)))
            mid = tick.get('mid_price', (bid + ask) / 2)
            spread = ask - bid

            if mid <= 0 or spread <= 0:
                continue

            # 计算信号强度
            # 信号 = (点差 / 中间价) * 10000 (转换为bps)
            spread_bps = (spread / mid) * 10000

            # 计算未来收益 (1, 5, 10个周期后)
            future_returns = {}
            for period in [1, 5, 10]:
                if i + period < len(self.data):
                    future_tick = self.data.iloc[i + period]
                    future_mid = future_tick.get('mid_price',
                        (future_tick.get('bid_price', 0) + future_tick.get('ask_price', 0)) / 2)
                    if future_mid > 0 and mid > 0:
                        ret = (future_mid - mid) / mid
                        future_returns[f'return_{period}'] = ret

            # 生成信号方向
            # 买点差信号：预期价格会回升
            # 卖点差信号：预期价格会下跌
            if spread_bps > 2:  # 点差大于2bps才有交易价值
                # 计算相对位置（价格在近期范围内的位置）
                lookback = min(20, i)
                if lookback > 5:
                    recent_prices = [self.data.iloc[j].get('mid_price', mid)
                                   for j in range(i-lookback, i+1)]
                    price_min = min(recent_prices)
                    price_max = max(recent_prices)

                    if price_max > price_min:
                        position_in_range = (mid - price_min) / (price_max - price_min)

                        # 在低位买点差（看涨），在高位卖点差（看跌）
                        if position_in_range < 0.3:
                            direction = 1  # 看涨
                            score = spread_bps * (1 - position_in_range)
                        elif position_in_range > 0.7:
                            direction = -1  # 看跌
                            score = spread_bps * position_in_range
                        else:
                            direction = 0
                            score = 0
                    else:
                        direction = 0
                        score = 0
                else:
                    direction = 0
                    score = 0
            else:
                direction = 0
                score = 0

            self.alpha_scores.append({
                'timestamp': i,
                'spread_bps': spread_bps,
                'direction': direction,
                'score': score,
                'mid_price': mid
            })

            if future_returns and direction != 0:
                self.future_returns.append({
                    'timestamp': i,
                    'direction': direction,
                    'score': score,
                    **future_returns
                })

    def _analyze_signal_distribution(self) -> Dict:
        """分析信号分布"""
        scores = [s['score'] for s in self.alpha_scores if s['score'] != 0]
        directions = [s['direction'] for s in self.alpha_scores]

        if not scores:
            return {
                'verdict': 'NO_SIGNALS',
                'reason': 'All scores are zero'
            }

        # 基本统计
        mean_score = np.mean(scores)
        std_score = np.std(scores) if len(scores) > 1 else 0
        skewness = stats.skew(scores) if len(scores) > 2 else 0
        kurt = stats.kurtosis(scores) if len(scores) > 3 else 0

        # 方向分布
        pos_count = sum(1 for d in directions if d > 0)
        neg_count = sum(1 for d in directions if d < 0)
        neutral_count = sum(1 for d in directions if d == 0)

        # 信号频率
        signal_ratio = (pos_count + neg_count) / len(directions)

        print(f"  Signal Statistics:")
        print(f"    Mean: {mean_score:.4f}")
        print(f"    Std: {std_score:.4f}")
        print(f"    Skew: {skewness:.4f}")
        print(f"    Kurtosis: {kurt:.4f}")
        print(f"  Direction Distribution:")
        print(f"    Positive: {pos_count} ({pos_count/len(directions):.1%})")
        print(f"    Negative: {neg_count} ({neg_count/len(directions):.1%})")
        print(f"    Neutral: {neutral_count} ({neutral_count/len(directions):.1%})")
        print(f"  Signal Frequency: {signal_ratio:.1%}")

        # 判断
        if signal_ratio < 0.01:
            verdict = "TOO_SPARSE"
            reason = "Signal frequency too low (<1%)"
        elif std_score < 0.01:
            verdict = "NO_VARIATION"
            reason = "Signal has no variation"
        elif abs(skewness) > 2:
            verdict = "SKEWED"
            reason = "Highly skewed distribution"
        else:
            verdict = "OK"
            reason = "Distribution looks reasonable"

        return {
            'mean': mean_score,
            'std': std_score,
            'skew': skewness,
            'kurtosis': kurt,
            'signal_ratio': signal_ratio,
            'pos_count': pos_count,
            'neg_count': neg_count,
            'neutral_count': neutral_count,
            'verdict': verdict,
            'reason': reason
        }

    def _analyze_predictive_power(self) -> Dict:
        """分析预测能力"""
        if len(self.future_returns) < 10:
            return {
                'verdict': 'INSUFFICIENT_DATA',
                'reason': f'Only {len(self.future_returns)} labeled samples'
            }

        results = {}

        for period in [1, 5, 10]:
            col = f'return_{period}'

            # 提取数据
            directions = []
            returns = []

            for record in self.future_returns:
                if col in record:
                    directions.append(record['direction'])
                    returns.append(record[col])

            if len(directions) < 10:
                results[period] = {
                    'sample_size': len(directions),
                    'direction_accuracy': 0,
                    'mean_return_when_long': 0,
                    'mean_return_when_short': 0
                }
                continue

            # 方向准确率
            correct = sum(1 for d, r in zip(directions, returns)
                        if (d > 0 and r > 0) or (d < 0 and r < 0))
            accuracy = correct / len(directions)

            # 分方向收益
            long_returns = [r for d, r in zip(directions, returns) if d > 0]
            short_returns = [r for d, r in zip(directions, returns) if d < 0]

            mean_long = np.mean(long_returns) if long_returns else 0
            mean_short = np.mean(short_returns) if short_returns else 0

            results[period] = {
                'sample_size': len(directions),
                'direction_accuracy': accuracy,
                'mean_return_when_long': mean_long,
                'mean_return_when_short': mean_short,
                'long_count': len(long_returns),
                'short_count': len(short_returns)
            }

            print(f"  Period {period}:")
            print(f"    Sample size: {len(directions)}")
            print(f"    Direction accuracy: {accuracy:.1%}")
            print(f"    Mean return (long): {mean_long:.4f}")
            print(f"    Mean return (short): {mean_short:.4f}")

        # 综合判断
        avg_accuracy = np.mean([r['direction_accuracy']
                               for r in results.values() if 'direction_accuracy' in r])

        if avg_accuracy > 0.55:
            verdict = "PREDICTIVE"
            reason = f"Direction accuracy {avg_accuracy:.1%} > 55%"
        elif avg_accuracy > 0.52:
            verdict = "WEAK_PREDICTIVE"
            reason = f"Direction accuracy {avg_accuracy:.1%} (marginal)"
        elif avg_accuracy > 0.48:
            verdict = "RANDOM"
            reason = f"Direction accuracy {avg_accuracy:.1%} (random)"
        else:
            verdict = "CONTRARIAN"
            reason = f"Direction accuracy {avg_accuracy:.1%} (worse than random)"

        return {
            'period_results': results,
            'average_accuracy': avg_accuracy,
            'verdict': verdict,
            'reason': reason
        }

    def _analyze_information_coefficient(self) -> Dict:
        """分析信息系数 (Information Coefficient)"""
        if len(self.future_returns) < 20:
            return {
                'verdict': 'INSUFFICIENT_DATA',
                'reason': f'Only {len(self.future_returns)} samples'
            }

        ic_results = {}

        for period in [1, 5, 10]:
            col = f'return_{period}'

            scores = []
            returns = []

            for record in self.future_returns:
                if col in record:
                    scores.append(record['score'])
                    returns.append(record[col])

            if len(scores) < 10:
                ic_results[period] = {'rank_ic': 0, 'pearson_ic': 0}
                continue

            # Rank IC (Spearman)
            if len(scores) > 2 and np.std(scores) > 0 and np.std(returns) > 0:
                rank_ic, rank_p = stats.spearmanr(scores, returns)
                pearson_ic, pearson_p = stats.pearsonr(scores, returns)
            else:
                rank_ic, rank_p = 0, 1
                pearson_ic, pearson_p = 0, 1

            ic_results[period] = {
                'rank_ic': rank_ic,
                'rank_p_value': rank_p,
                'pearson_ic': pearson_ic,
                'pearson_p_value': pearson_p
            }

            print(f"  Period {period}:")
            print(f"    Rank IC: {rank_ic:.4f} (p={rank_p:.4f})")
            print(f"    Pearson IC: {pearson_ic:.4f} (p={pearson_p:.4f})")

        # 平均IC
        avg_rank_ic = np.mean([ic['rank_ic'] for ic in ic_results.values()])

        if abs(avg_rank_ic) > 0.1:
            verdict = "STRONG_IC"
            reason = f"Average Rank IC = {avg_rank_ic:.4f} (strong)"
        elif abs(avg_rank_ic) > 0.05:
            verdict = "MODERATE_IC"
            reason = f"Average Rank IC = {avg_rank_ic:.4f} (moderate)"
        elif abs(avg_rank_ic) > 0.02:
            verdict = "WEAK_IC"
            reason = f"Average Rank IC = {avg_rank_ic:.4f} (weak)"
        else:
            verdict = "NO_IC"
            reason = f"Average Rank IC = {avg_rank_ic:.4f} (no predictive power)"

        return {
            'period_ics': ic_results,
            'average_rank_ic': avg_rank_ic,
            'verdict': verdict,
            'reason': reason
        }

    def _generate_final_verdict(self, dist: Dict, pred: Dict, ic: Dict) -> Dict:
        """生成最终判决"""
        print("\n" + "=" * 70)
        print("       FINAL VERDICT")
        print("=" * 70)

        score = 0
        issues = []

        # 分布评分
        if dist.get('verdict') == 'OK':
            score += 1
        else:
            issues.append(f"Distribution: {dist.get('reason', 'Unknown')}")

        if dist.get('signal_ratio', 0) < 0.05:
            score -= 1
            issues.append("Signal too sparse")

        # 预测能力评分
        if pred.get('verdict') == 'PREDICTIVE':
            score += 3
        elif pred.get('verdict') == 'WEAK_PREDICTIVE':
            score += 1
        else:
            issues.append(f"Predictive: {pred.get('reason', 'Unknown')}")

        # IC评分
        if ic.get('verdict') == 'STRONG_IC':
            score += 3
        elif ic.get('verdict') == 'MODERATE_IC':
            score += 2
        elif ic.get('verdict') == 'WEAK_IC':
            score += 1
        else:
            issues.append(f"IC: {ic.get('reason', 'Unknown')}")

        # 最终判决
        if score >= 5:
            verdict = "STRONG_ALPHA"
            recommendation = "Signal has strong information content. Proceed with execution optimization."
        elif score >= 3:
            verdict = "WEAK_ALPHA"
            recommendation = "Signal has weak information content. Consider feature engineering or strategy redesign."
        elif score >= 1:
            verdict = "MARGINAL"
            recommendation = "Signal is marginal. High risk of overfitting. Recommend redesign."
        else:
            verdict = "NOISE"
            recommendation = "Signal appears to be noise. Recommend abandoning or complete redesign."

        print(f"\nScore: {score}/7")
        print(f"Verdict: {verdict}")
        print(f"Recommendation: {recommendation}")

        if issues:
            print("\nIssues identified:")
            for issue in issues:
                print(f"  - {issue}")

        return {
            'score': score,
            'max_score': 7,
            'verdict': verdict,
            'recommendation': recommendation,
            'issues': issues
        }


if __name__ == "__main__":
    print("=" * 70)
    print("Alpha Information Content Analysis")
    print("=" * 70)

    # 加载数据
    from data_fetcher import BinanceDataFetcher

    fetcher = BinanceDataFetcher()
    df = fetcher.fetch_klines('BTCUSDT', '1h', limit=1000)
    tick_df = fetcher.convert_to_tick_format(df)

    print(f"\nLoaded {len(tick_df)} ticks for analysis")

    # 运行信息含量分析
    analyzer = AlphaInformationContent(tick_df)
    result = analyzer.analyze_mvp_signal()

    print("\n" + "=" * 70)
    print("Analysis Complete")
    print("=" * 70)
