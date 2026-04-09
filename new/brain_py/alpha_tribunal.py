"""
Alpha 审判系统
目标：用5个严格测试，识别真正的alpha vs 虚假信号

核心原则：
- 证伪优于证实：设计测试来揭穿虚假alpha
- 多重验证：通过多个独立维度交叉验证
- 统计严谨：使用严格的统计检验，不依赖肉眼观察
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class TribunalVerdict:
    """单个测试的Verdict"""
    test_name: str
    verdict: str  # 'pass', 'warning', 'fail'
    score: float  # 0-1
    details: Dict = field(default_factory=dict)
    raw_data: Dict = field(default_factory=dict)


@dataclass
class FinalVerdict:
    """最终判决"""
    verdict: str  # 'REAL_ALPHA', 'FRAGILE_ALPHA', 'BORDERLINE', 'ILLUSION'
    confidence: str  # 'High', 'Medium', 'Low', 'None'
    total_score: float
    max_possible: float
    recommendation: str
    failed_tests: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class AlphaTribunal:
    """
    Alpha审判系统

    使用5个严格测试来验证策略的真实性：
    1. 时间分层验证 (Walk-Forward) - 防过拟合
    2. 信号打乱测试 (Permutation) - 防结构性偏见
    3. 边际贡献分析 (Marginal) - 防假组件
    4. 参数稳定性测试 (Stability) - 防过拟合尖峰
    5. 微结构噪声测试 (Robustness) - 防模拟偏差
    """

    # Score阈值
    THRESHOLDS = {
        'REAL_ALPHA': 8.0,      # 8分以上：真正的alpha
        'FRAGILE_ALPHA': 5.0,   # 5-7分：脆弱的alpha
        'BORDERLINE': 3.0,      # 3-4分：边缘
        'ILLUSION': 0.0         # 0-2分：幻觉
    }

    def __init__(self,
                 strategy_factory: Callable,
                 data: pd.DataFrame,
                 initial_capital: float = 10000.0,
                 random_seed: int = 42):
        """
        初始化审判系统

        Args:
            strategy_factory: 策略工厂函数，接收参数返回策略实例
            data: 市场数据DataFrame
            initial_capital: Initial capital
            random_seed: 随机种子，保证可重复
        """
        self.strategy_factory = strategy_factory
        self.data = data.copy()
        self.initial_capital = initial_capital
        self.random_seed = random_seed

        np.random.seed(random_seed)

        self.verdicts: List[TribunalVerdict] = []
        self.final_verdict: Optional[FinalVerdict] = None

        logger.info(f"AlphaTribunal initialized: data={len(data)} rows, capital=${initial_capital}")

    def run_all_tests(self, verbose: bool = True) -> FinalVerdict:
        """
        运行所有审判测试

        Returns:
            FinalVerdict: 最终Verdict
        """
        if verbose:
            print("\n" + "="*70)
            print("           ALPHA TRIBUNAL - 审判系统启动")
            print("="*70)
            print(f"Data size: {len(self.data)} records")
            print(f"Time range: {self.data.index[0]} to {self.data.index[-1]}")
            print(f"Initial capital: ${self.initial_capital:,.2f}")
            print("="*70 + "\n")

        self.verdicts = []

        # 测试1: 时间分层验证
        verdict1 = self._walk_forward_validation()
        self.verdicts.append(verdict1)
        if verbose:
            self._print_verdict(verdict1)

        # 测试2: 信号打乱测试
        verdict2 = self._permutation_test()
        self.verdicts.append(verdict2)
        if verbose:
            self._print_verdict(verdict2)

        # 测试3: 边际贡献分析
        verdict3 = self._marginal_contribution_analysis()
        self.verdicts.append(verdict3)
        if verbose:
            self._print_verdict(verdict3)

        # 测试4: 参数稳定性测试
        verdict4 = self._parameter_stability_test()
        self.verdicts.append(verdict4)
        if verbose:
            self._print_verdict(verdict4)

        # 测试5: 微结构噪声测试
        verdict5 = self._microstructure_robustness()
        self.verdicts.append(verdict5)
        if verbose:
            self._print_verdict(verdict5)

        # 最终判决
        self.final_verdict = self._calculate_final_verdict()

        if verbose:
            self._print_final_verdict()

        return self.final_verdict

    def _print_verdict(self, verdict: TribunalVerdict):
        """打印单个测试结果"""
        symbol = {
            'pass': '[OK]',
            'warning': '[WARN]',
            'fail': '[FAIL]'
        }.get(verdict.verdict, '[?]')

        print(f"{symbol} {verdict.test_name}")
        print(f"   Score: {verdict.score:.2f}/2.00")

        for key, value in verdict.details.items():
            if isinstance(value, float):
                print(f"   {key}: {value:.4f}")
            else:
                print(f"   {key}: {value}")
        print()

    def _print_final_verdict(self):
        """打印最终判决"""
        verdict = self.final_verdict

        print("="*70)
        print("           FINAL VERDICT")
        print("="*70)

        symbol = {
            'REAL_ALPHA': '[REAL]',
            'FRAGILE_ALPHA': '[FRAGILE]',
            'BORDERLINE': '[BORDERLINE]',
            'ILLUSION': '[ILLUSION]'
        }.get(verdict.verdict, '[?]')

        print(f"\n{symbol} Verdict: {verdict.verdict}")
        print(f"Confidence: {verdict.confidence}")
        print(f"Total score: {verdict.total_score:.1f}/{verdict.max_possible:.0f}")

        if verdict.failed_tests:
            print(f"\n[FAILED TESTS]:")
            for test in verdict.failed_tests:
                print(f"   - {test}")

        if verdict.warnings:
            print(f"\n[WARNINGS]:")
            for warning in verdict.warnings:
                print(f"   - {warning}")

        print(f"\n[RECOMMENDATION]:")
        print(f"   {verdict.recommendation}")
        print("="*70)

    def _walk_forward_validation(self, n_splits: int = 5) -> TribunalVerdict:
        """
        时间分层验证 - 核心防过拟合测试

        原理：
        - 将数据按时间分成n份
        - 用前i份训练，第i+1份测试
        - 真正的alpha应该在OOS样本上表现稳定
        """
        test_name = "1. 时间分层验证 (Walk-Forward)"

        # 按时间分割数据
        split_size = len(self.data) // n_splits
        splits = [
            self.data.iloc[i*split_size:(i+1)*split_size]
            for i in range(n_splits)
        ]

        is_results = []
        oos_results = []

        # 使用固定参数进行测试（避免优化偏差）
        default_params = {
            'queue_target_ratio': 0.2,
            'toxic_threshold': 0.35,
            'min_spread_ticks': 3
        }

        for i in range(1, n_splits):
            # 训练数据：前i个块
            train_data = pd.concat(splits[:i])
            # 测试数据：第i个块
            test_data = splits[i]

            if len(train_data) < 50 or len(test_data) < 50:
                continue

            # 训练集表现
            is_result = self._evaluate_strategy(train_data, default_params)
            is_results.append(is_result)

            # 测试集表现
            oos_result = self._evaluate_strategy(test_data, default_params)
            oos_results.append(oos_result)

        if not is_results or not oos_results:
            return TribunalVerdict(
                test_name=test_name,
                verdict='fail',
                score=0.0,
                details={'error': 'Insufficient data for walk-forward'}
            )

        # 计算平均表现
        is_sharpe = np.mean([r['sharpe'] for r in is_results])
        oos_sharpe = np.mean([r['sharpe'] for r in oos_results])

        # 计算Decay rate
        if abs(is_sharpe) < 0.01:
            decay_rate = 0.0
        else:
            decay_rate = oos_sharpe / is_sharpe

        # Score逻辑
        if decay_rate > 0.7:
            verdict = 'pass'
            score = 2.0
        elif decay_rate > 0.4:
            verdict = 'warning'
            score = 1.0
        else:
            verdict = 'fail'
            score = 0.0

        return TribunalVerdict(
            test_name=test_name,
            verdict=verdict,
            score=score,
            details={
                'decay_rate': decay_rate,
                'is_sharpe': is_sharpe,
                'oos_sharpe': oos_sharpe,
                'n_folds': len(oos_results)
            },
            raw_data={
                'is_results': is_results,
                'oos_results': oos_results
            }
        )

    def _permutation_test(self, n_permutations: int = 100) -> TribunalVerdict:
        """
        信号打乱测试 - 防结构性偏见

        原理：
        - 打乱价格/成交量的时间顺序
        - 如果策略在打乱数据上仍然有效，说明是结构偏见
        - 真正的alpha应该对打乱敏感
        """
        test_name = "2. 信号打乱测试 (Permutation)"

        # 原始策略表现
        default_params = {
            'queue_target_ratio': 0.2,
            'toxic_threshold': 0.35,
            'min_spread_ticks': 3
        }

        original_result = self._evaluate_strategy(self.data, default_params)
        original_sharpe = original_result['sharpe']

        # 打乱测试
        permuted_sharpes = []

        for i in range(n_permutations):
            # 打乱数据（但保持时间索引）
            shuffled_data = self.data.copy()

            # 打乱价格列
            price_cols = [c for c in shuffled_data.columns if 'price' in c.lower()]
            if price_cols:
                for col in price_cols:
                    shuffled_data[col] = np.random.permutation(shuffled_data[col].values)

            # 评估打乱后的策略
            result = self._evaluate_strategy(shuffled_data, default_params)
            permuted_sharpes.append(result['sharpe'])

        permuted_sharpes = np.array(permuted_sharpes)

        # 计算p-value：原始夏普在打乱分布中的位置
        p_value = np.mean(permuted_sharpes >= original_sharpe)

        # 计算Effect size（与打乱分布的差距）
        permuted_mean = np.mean(permuted_sharpes)
        permuted_std = np.std(permuted_sharpes) if len(permuted_sharpes) > 1 else 1.0
        effect_size = (original_sharpe - permuted_mean) / (permuted_std + 1e-6)

        # Score逻辑
        if p_value < 0.05 and effect_size > 1.5:
            verdict = 'pass'
            score = 2.0
        elif p_value < 0.1:
            verdict = 'warning'
            score = 1.0
        else:
            verdict = 'fail'
            score = 0.0

        return TribunalVerdict(
            test_name=test_name,
            verdict=verdict,
            score=score,
            details={
                'p_value': p_value,
                'effect_size': effect_size,
                'original_sharpe': original_sharpe,
                'permuted_mean': permuted_mean,
                'permuted_std': permuted_std
            },
            raw_data={
                'permuted_sharpes': permuted_sharpes.tolist()
            }
        )

    def _marginal_contribution_analysis(self) -> TribunalVerdict:
        """
        边际贡献分析 - 防假组件

        原理：
        - 分别移除每个组件，看策略表现下降多少
        - 真正的组件应该有正的边际贡献
        - 假组件或过度拟合的组件贡献为负或零
        """
        test_name = "3. 边际贡献分析 (Marginal)"

        # 完整策略表现
        default_params = {
            'queue_target_ratio': 0.2,
            'toxic_threshold': 0.35,
            'min_spread_ticks': 3
        }

        full_result = self._evaluate_strategy(self.data, default_params)
        full_sharpe = full_result['sharpe']

        # 测试每个组件的贡献
        components = {
            'queue_optimizer': {'queue_target_ratio': None},  # 禁用队列优化
            'toxic_detector': {'toxic_threshold': 1.0},       # 禁用毒流检测
            'spread_capture': {'min_spread_ticks': 100}       # 禁用点差捕获
        }

        contributions = {}

        for comp_name, disabled_params in components.items():
            # 创建禁用该组件的参数
            test_params = default_params.copy()
            test_params.update(disabled_params)

            # 评估
            result = self._evaluate_strategy(self.data, test_params)
            sharpe_without = result['sharpe']

            # 边际贡献 = 完整 - 去掉组件
            marginal = full_sharpe - sharpe_without
            contributions[comp_name] = marginal

        # 分析
        positive_contribs = sum(1 for c in contributions.values() if c > 0)
        total_contribs = len(contributions)
        negative_contribs = sum(1 for c in contributions.values() if c < -0.1)

        # Score逻辑
        if positive_contribs == total_contribs and negative_contribs == 0:
            verdict = 'pass'
            score = 2.0
        elif positive_contribs >= 2 and negative_contribs == 0:
            verdict = 'warning'
            score = 1.0
        else:
            verdict = 'fail'
            score = 0.0

        return TribunalVerdict(
            test_name=test_name,
            verdict=verdict,
            score=score,
            details={
                'positive_components': positive_contribs,
                'total_components': total_contribs,
                'negative_components': negative_contribs,
                'contributions': {k: round(v, 4) for k, v in contributions.items()},
                'full_sharpe': full_sharpe
            },
            raw_data={'contributions': contributions}
        )

    def _parameter_stability_test(self) -> TribunalVerdict:
        """
        参数稳定性测试 - 防过拟合尖峰

        原理：
        - 在2D参数空间上测试策略表现
        - 真正的alpha应该有"高原"状表现
        - 过拟合的策略只有"尖峰"
        """
        test_name = "4. 参数稳定性 (Stability)"

        # 参数网格
        queue_values = np.linspace(0.1, 0.4, 7)
        toxic_values = np.linspace(0.25, 0.45, 5)

        heatmap = np.zeros((len(queue_values), len(toxic_values)))

        for i, q in enumerate(queue_values):
            for j, t in enumerate(toxic_values):
                params = {
                    'queue_target_ratio': q,
                    'toxic_threshold': t,
                    'min_spread_ticks': 3
                }
                result = self._evaluate_strategy(self.data, params)
                heatmap[i, j] = result['sharpe']

        # 分析稳定性
        max_sharpe = np.max(heatmap)
        min_sharpe = np.min(heatmap)
        mean_sharpe = np.mean(heatmap)
        std_sharpe = np.std(heatmap)

        # 定义Stable area（Max的70%以上）
        if max_sharpe > 0:
            threshold = max_sharpe * 0.7
            stable_mask = heatmap >= threshold
            stable_area = np.mean(stable_mask)
        else:
            stable_area = 0.0

        # CV
        cv = std_sharpe / (abs(mean_sharpe) + 1e-6)

        # Score逻辑
        if stable_area > 0.25:  # 25%的区域稳定
            verdict = 'pass'
            score = 2.0
        elif stable_area > 0.1:
            verdict = 'warning'
            score = 1.0
        else:
            verdict = 'fail'
            score = 0.0

        return TribunalVerdict(
            test_name=test_name,
            verdict=verdict,
            score=score,
            details={
                'stable_area_pct': stable_area * 100,
                'max_sharpe': max_sharpe,
                'min_sharpe': min_sharpe,
                'cv': cv,
                'n_params_tested': len(queue_values) * len(toxic_values)
            },
            raw_data={
                'heatmap': heatmap.tolist(),
                'queue_values': queue_values.tolist(),
                'toxic_values': toxic_values.tolist()
            }
        )

    def _microstructure_robustness(self) -> TribunalVerdict:
        """
        微结构噪声测试 - 防模拟偏差

        原理：
        - 注入各种微结构噪声
        - 真正的alpha应该对噪声有一定的鲁棒性
        - 过于脆弱的策略可能是模拟偏差
        """
        test_name = "5. 微结构噪声 (Robustness)"

        # 噪声水平
        noise_levels = [0.0, 0.001, 0.005, 0.01]

        results = []
        default_params = {
            'queue_target_ratio': 0.2,
            'toxic_threshold': 0.35,
            'min_spread_ticks': 3
        }

        for noise_level in noise_levels:
            # 注入噪声
            noisy_data = self._inject_microstructure_noise(
                self.data.copy(),
                noise_level
            )

            # 评估
            result = self._evaluate_strategy(noisy_data, default_params)
            results.append({
                'noise_level': noise_level,
                'sharpe': result['sharpe'],
                'total_return': result['total_return']
            })

        # 计算Robustness score
        base_sharpe = results[0]['sharpe']

        if abs(base_sharpe) < 0.01:
            robustness_score = 0.0
        else:
            # 计算各噪声水平的保持率
            retentions = []
            for r in results[1:]:
                retention = r['sharpe'] / (base_sharpe + 1e-6)
                # 限制在合理范围
                retention = max(0, min(2, retention))
                retentions.append(retention)

            # 加权平均（高噪声权重更低）
            weights = [0.4, 0.3, 0.2, 0.1][:len(retentions)]
            if retentions:
                robustness_score = np.average(retentions, weights=weights[:len(retentions)])
            else:
                robustness_score = 0.0

        # Score逻辑
        if robustness_score > 0.7:
            verdict = 'pass'
            score = 2.0
        elif robustness_score > 0.4:
            verdict = 'warning'
            score = 1.0
        else:
            verdict = 'fail'
            score = 0.0

        return TribunalVerdict(
            test_name=test_name,
            verdict=verdict,
            score=score,
            details={
                'robustness_score': robustness_score,
                'base_sharpe': base_sharpe,
                'noise_results': results
            },
            raw_data={'results': results}
        )

    def _inject_microstructure_noise(self, data: pd.DataFrame, noise_level: float) -> pd.DataFrame:
        """
        注入微结构噪声

        模拟真实交易中的各种摩擦：
        - 价格滑点
        - 队列插队
        - 点差变化
        - 延迟
        """
        noisy_data = data.copy()

        # 1. 价格噪声
        price_cols = [c for c in noisy_data.columns if 'price' in c.lower()]
        for col in price_cols:
            noise = np.random.normal(0, noise_level, len(noisy_data))
            noisy_data[col] = noisy_data[col] * (1 + noise)

        # 2. 队列位置噪声（插队/被插队）
        if 'queue_position' in noisy_data.columns:
            queue_noise = np.random.uniform(-0.1, 0.1, len(noisy_data))
            noisy_data['queue_position'] = noisy_data['queue_position'] + queue_noise
            noisy_data['queue_position'] = noisy_data['queue_position'].clip(0, 1)

        # 3. 点差噪声
        if 'spread' in noisy_data.columns:
            spread_noise = np.random.uniform(0.8, 1.2, len(noisy_data))
            noisy_data['spread'] = noisy_data['spread'] * spread_noise

        return noisy_data

    def _evaluate_strategy(self,
                          data: pd.DataFrame,
                          params: Dict) -> Dict:
        """
        评估策略表现 - 连接到本地交易模块

        使用 LocalTrader 运行真实回测
        """
        try:
            from local_trading import LocalTrader, LocalTradingConfig
            from local_trading.data_source import DataFrameDataSource

            # 创建配置
            config = LocalTradingConfig(
                symbol="BTCUSDT",
                initial_capital=self.initial_capital,
                max_position=0.1,
                queue_target_ratio=params.get('queue_target_ratio', 0.2),
                toxic_threshold=params.get('toxic_threshold', 0.35),
                min_spread_ticks=params.get('min_spread_ticks', 3)
            )

            # 创建交易者
            trader = LocalTrader(config)

            # 创建数据源
            data_source = DataFrameDataSource(data, symbol="BTCUSDT")
            data_source.load()
            trader.set_data_source(data_source)

            # 运行回测
            result = trader.run_backtest(progress_interval=999999)  # 禁用进度输出

            # 返回指标
            return {
                'sharpe': result.sharpe_ratio,
                'total_return': result.total_return_pct,
                'max_drawdown': result.max_drawdown_pct,
                'win_rate': result.win_rate,
                'n_trades': result.total_trades,
                'volatility': result.volatility,
                'final_capital': result.final_capital
            }

        except Exception as e:
            logger.error(f"本地交易模块回测失败: {e}")
            # 降级到简化评估
            return self._evaluate_strategy_simple(data, params)

    def _evaluate_strategy_simple(self, data: pd.DataFrame, params: Dict) -> Dict:
        """
        简化版策略评估 (降级方案)
        """
        # 使用MVP策略逻辑进行简化评估
        returns = []

        # 简化的回测逻辑
        for i in range(len(data) - 1):
            row = data.iloc[i]
            next_row = data.iloc[i + 1]

            # 获取价格
            close = row.get('close', row.get('Close', 0))
            next_close = next_row.get('close', next_row.get('Close', 0))

            if close <= 0:
                continue

            # 简化的信号生成 (基于队列优化和毒流检测概念)
            signal = 0

            # 价格动量信号
            if 'open' in row:
                change = (close - row['open']) / row['open']
                if change < -params.get('toxic_threshold', 0.35) * 0.01:
                    signal = 1  # 超跌买入
                elif change > params.get('toxic_threshold', 0.35) * 0.01:
                    signal = -1  # 超涨卖出

            if signal != 0:
                # 计算收益率
                price_change = (next_close - close) / close
                # 考虑点差成本
                spread_cost = params.get('min_spread_ticks', 3) * 0.0001
                trade_return = signal * price_change - spread_cost
                returns.append(trade_return)

        if not returns:
            return {
                'sharpe': 0.0,
                'total_return': 0.0,
                'max_drawdown': 0.0,
                'win_rate': 0.0,
                'n_trades': 0,
                'volatility': 0.0,
                'final_capital': self.initial_capital
            }

        returns = np.array(returns)

        # 计算指标
        total_return = np.sum(returns)

        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)
            volatility = np.std(returns) * np.sqrt(252)
        else:
            sharpe = 0.0
            volatility = 0.0

        # 最大回撤
        cumulative = np.cumsum(returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = cumulative - running_max
        max_drawdown = np.min(drawdown) if len(drawdown) > 0 else 0.0

        # 胜率
        win_rate = np.mean(returns > 0) if len(returns) > 0 else 0.0

        # 计算最终资金
        final_capital = self.initial_capital * (1 + total_return)

        return {
            'sharpe': sharpe,
            'total_return': total_return,
            'max_drawdown': max_drawdown,
            'win_rate': win_rate,
            'n_trades': len(returns),
            'volatility': volatility,
            'final_capital': final_capital
        }

    def _generate_signal(self, row: pd.Series, params: Dict) -> int:
        """
        生成交易信号（简化版）

        实际应该调用MVP策略的逻辑
        """
        # 简化的信号生成逻辑
        # 这里只是一个占位符，实际应该集成MVP策略

        # 基于价格的简单均值回归
        if 'close' in row and 'open' in row:
            change = (row['close'] - row['open']) / row['open']
            if change < -0.001:  # 下跌时买入
                return 1
            elif change > 0.001:  # 上涨时卖出
                return -1

        return 0

    def _calculate_final_verdict(self) -> FinalVerdict:
        """计算最终判决"""
        total_score = sum(v.score for v in self.verdicts)
        max_possible = len(self.verdicts) * 2.0

        failed_tests = [v.test_name for v in self.verdicts if v.verdict == 'fail']
        warnings = [v.test_name for v in self.verdicts if v.verdict == 'warning']

        # 确定判决等级
        if total_score >= self.THRESHOLDS['REAL_ALPHA']:
            verdict = 'REAL_ALPHA'
            confidence = 'High'
            recommendation = ('Strategy passed all tests. Proceed to live test. '
                            'Recommendation: $1000 testnet with strict monitoring.')
        elif total_score >= self.THRESHOLDS['FRAGILE_ALPHA']:
            verdict = 'FRAGILE_ALPHA'
            confidence = 'Medium'
            recommendation = ('Strategy has some alpha but is fragile. '
                            'Recommendation: Optimize and test with small capital ($100).')
        elif total_score >= self.THRESHOLDS['BORDERLINE']:
            verdict = 'BORDERLINE'
            confidence = 'Low'
            recommendation = ('Strategy is borderline, not recommended for live trading. '
                            'Recommendation: Redesign core strategy logic.')
        else:
            verdict = 'ILLUSION'
            confidence = 'None'
            recommendation = ('Strategy failed all tests, likely a backtest illusion.',
                            'Recommendation: Abandon this strategy and analyze failure reasons.')

        return FinalVerdict(
            verdict=verdict,
            confidence=confidence,
            total_score=total_score,
            max_possible=max_possible,
            recommendation=recommendation,
            failed_tests=failed_tests,
            warnings=warnings
        )

    def save_report(self, filepath: str):
        """保存详细报告"""
        report = {
            'timestamp': datetime.now().isoformat(),
            'final_verdict': {
                'verdict': self.final_verdict.verdict,
                'confidence': self.final_verdict.confidence,
                'total_score': self.final_verdict.total_score,
                'max_possible': self.final_verdict.max_possible,
                'recommendation': self.final_verdict.recommendation,
                'failed_tests': self.final_verdict.failed_tests,
                'warnings': self.final_verdict.warnings
            },
            'individual_tests': [
                {
                    'test_name': v.test_name,
                    'verdict': v.verdict,
                    'score': v.score,
                    'details': v.details
                }
                for v in self.verdicts
            ]
        }

        with open(filepath, 'w') as f:
            json.dump(report, f, indent=2, default=str)

        logger.info(f"Tribunal report saved: {filepath}")


# 简单的随机策略（用于对比测试）
class RandomStrategy:
    """随机策略 - 作为基准对比"""

    def __init__(self, seed=42):
        np.random.seed(seed)

    def generate_signal(self, data):
        return np.random.choice([-1, 0, 1])


if __name__ == "__main__":
    # 简单测试
    print("="*70)
    print("Alpha Tribunal - Simple Test")
    print("="*70)

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

    # 简单的策略工厂
    def strategy_factory(**params):
        return params

    # 运行审判
    tribunal = AlphaTribunal(strategy_factory, data, initial_capital=10000.0)
    verdict = tribunal.run_all_tests(verbose=True)

    # 保存报告
    tribunal.save_report('alpha_tribunal_report.json')

    print("\n报告已保存: alpha_tribunal_report.json")
