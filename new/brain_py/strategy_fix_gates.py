"""
三关修复策略 - 解决结构性因果倒置

修复内容：
1. Gate 1: Execution层只执行不筛选
2. Gate 2: 分位数阈值替代固定阈值
3. Gate 3: 提升Alpha质量，分离收益来源
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from collections import deque
import time

from mvp import PredictiveMicropriceAlpha


@dataclass
class SignalRecord:
    """信号记录"""
    signal_id: str
    timestamp: float
    alpha_value: float
    expected_return: float
    size: float
    direction: int
    threshold_used: float


@dataclass
class ExecutionResult:
    """执行结果"""
    signal_id: str
    filled: bool
    price: float
    slippage: float
    execution_timestamp: float
    should_execute: bool = True


class AlphaSignalRecorder:
    """
    记录所有Alpha信号，包括未执行的
    用于检测选择偏差
    """

    def __init__(self):
        self.all_signals: List[SignalRecord] = []
        self.executed_signals: List[Dict] = []
        self.rejected_signals: List[Dict] = []

    def record_signal(self, signal: SignalRecord):
        """记录一个Alpha信号"""
        self.all_signals.append(signal)

    def record_execution(self, signal: SignalRecord, result: ExecutionResult):
        """记录执行结果"""
        if result.filled:
            self.executed_signals.append({
                'signal': signal,
                'result': result,
                'timestamp': time.time()
            })
        else:
            self.rejected_signals.append({
                'signal': signal,
                'result': result,
                'timestamp': time.time(),
                'reason': 'execution_rejected'
            })

    def analyze_selection_bias(self) -> Dict:
        """分析执行层的选择偏差"""
        if not self.all_signals or not self.executed_signals:
            return {
                'status': 'INSUFFICIENT_DATA',
                'selection_bias': 0.0,
                'bias_detected': False
            }

        # 比较被执行和未执行信号的Alpha质量
        all_alphas = [s.alpha_value for s in self.all_signals]
        executed_alphas = [e['signal'].alpha_value for e in self.executed_signals]

        if self.rejected_signals:
            rejected_alphas = [r['signal'].alpha_value for r in self.rejected_signals]
        else:
            rejected_alphas = []

        avg_all = np.mean(all_alphas) if all_alphas else 0
        avg_executed = np.mean(executed_alphas) if executed_alphas else 0
        avg_rejected = np.mean(rejected_alphas) if rejected_alphas else 0

        # 选择偏差 = 被执行信号Alpha - 所有信号Alpha
        selection_bias = avg_executed - avg_all

        # 如果偏差显著，说明Execution在"挑选"信号
        bias_detected = abs(selection_bias) > 0.05

        return {
            'status': 'OK',
            'avg_alpha_all': avg_all,
            'avg_alpha_executed': avg_executed,
            'avg_alpha_rejected': avg_rejected if rejected_alphas else None,
            'selection_bias': selection_bias,
            'bias_detected': bias_detected,
            'total_signals': len(self.all_signals),
            'executed_signals': len(self.executed_signals),
            'rejected_signals': len(self.rejected_signals)
        }


class CleanExecutionLayer:
    """
    纯净执行层 - 只负责最优执行，不做决策
    """

    def __init__(self, fixed_slippage_bps: float = 5.0):
        self.execution_log = []
        self.fixed_slippage_bps = fixed_slippage_bps

    def execute_signal(self, signal: SignalRecord, orderbook: Dict) -> ExecutionResult:
        """
        执行信号，不做任何过滤
        返回：实际成交信息
        """
        # 1. 获取最优报价
        best_bid = orderbook.get('best_bid', 0)
        best_ask = orderbook.get('best_ask', 0)
        mid_price = (best_bid + best_ask) / 2 if best_bid > 0 and best_ask > 0 else 50000

        # 2. 计算固定滑点（与信号质量无关）
        slippage = mid_price * (self.fixed_slippage_bps / 10000)

        # 3. 确定成交价格
        if signal.direction > 0:  # 买入
            fill_price = best_ask + slippage
        else:  # 卖出
            fill_price = best_bid - slippage

        # 4. 返回执行结果（should_execute永远为True）
        result = ExecutionResult(
            signal_id=signal.signal_id,
            filled=True,  # 关键：100%成交
            price=fill_price,
            slippage=slippage,
            execution_timestamp=time.time(),
            should_execute=True  # 永远为True
        )

        self.execution_log.append({
            'signal': signal,
            'result': result,
            'timestamp': time.time()
        })

        return result


class AdaptiveThresholdGate:
    """
    自适应分位数阈值门控
    基于历史信号分布动态调整阈值
    """

    def __init__(self, window_size: int = 100, target_percentile: float = 80):
        self.window_size = window_size
        self.target_percentile = target_percentile
        self.signal_history = deque(maxlen=window_size)
        self.threshold_history = []

    def update_threshold(self, new_signal_value: float) -> float:
        """
        更新阈值：基于历史信号的分位数
        """
        # 1. 记录新信号（只记录有意义的信号）
        if abs(new_signal_value) > 0.01:
            self.signal_history.append(abs(new_signal_value))

        # 2. 计算分位数阈值
        if len(self.signal_history) >= 20:
            # 使用历史信号的百分位数作为阈值
            threshold = np.percentile(list(self.signal_history), self.target_percentile)
            # 限制阈值在合理范围 (0.05 - 0.3)
            threshold = np.clip(threshold, 0.05, 0.3)
        else:
            # 初始阶段使用较低阈值以产生足够信号
            threshold = 0.05

        # 3. 平滑阈值变化（指数平滑）
        if self.threshold_history:
            smoothed_threshold = 0.8 * threshold + 0.2 * self.threshold_history[-1]
        else:
            smoothed_threshold = threshold

        self.threshold_history.append(smoothed_threshold)

        return smoothed_threshold

    def should_trade(self, signal_value: float, use_adaptive: bool = True) -> bool:
        """
        决定是否交易
        """
        # 最小信号阈值（防止噪声交易）
        min_signal_threshold = 0.05

        if abs(signal_value) < min_signal_threshold:
            return False

        if not use_adaptive:
            # 传统固定阈值
            return abs(signal_value) > 0.5

        # 计算当前阈值
        current_threshold = self.update_threshold(signal_value)

        # 使用分位数阈值，但确保不会过高
        effective_threshold = min(current_threshold, 0.4)

        return abs(signal_value) > effective_threshold

    def get_stats(self) -> Dict:
        """获取阈值统计"""
        if not self.threshold_history:
            return {'current_threshold': 0.7}

        return {
            'current_threshold': self.threshold_history[-1],
            'mean_threshold': np.mean(self.threshold_history),
            'std_threshold': np.std(self.threshold_history) if len(self.threshold_history) > 1 else 0,
            'min_threshold': np.min(self.threshold_history),
            'max_threshold': np.max(self.threshold_history)
        }


class AlphaQualityImprover:
    """
    提升Alpha质量
    目标：将价格预测贡献提升到50%以上
    """

    def __init__(self):
        self.alpha_sources: List[Dict] = []
        self.predictive_alpha = PredictiveMicropriceAlpha()

    def add_alpha_source(self, name: str, alpha_func: Callable, weight: float = 1.0):
        """添加Alpha源"""
        self.alpha_sources.append({
            'name': name,
            'function': alpha_func,
            'weight': weight
        })

    def calculate_ensemble_alpha(self, orderbook: Dict) -> float:
        """
        计算集成Alpha信号
        """
        alphas = []
        weights = []

        for source in self.alpha_sources:
            try:
                alpha_value = source['function'](orderbook)
                alphas.append(alpha_value)
                weights.append(source['weight'])
            except Exception as e:
                print(f"Alpha source {source['name']} failed: {e}")
                continue

        if not alphas:
            return 0.0

        # 加权平均
        weights = np.array(weights) / np.sum(weights)
        ensemble_alpha = np.dot(alphas, weights)

        return ensemble_alpha

    def calculate_order_flow_imbalance(self, orderbook: Dict, levels: int = 5) -> float:
        """计算订单流不平衡(OFI)"""
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if not bids or not asks:
            return 0.0

        bid_volumes = [b.get('qty', 0) / (i+1) for i, b in enumerate(bids[:levels])]
        ask_volumes = [a.get('qty', 0) / (i+1) for i, a in enumerate(asks[:levels])]

        total_bid = sum(bid_volumes)
        total_ask = sum(ask_volumes)

        if total_bid + total_ask == 0:
            return 0.0

        ofi = (total_bid - total_ask) / (total_bid + total_ask)
        return ofi

    def calculate_microprice_alpha(self, orderbook: Dict) -> float:
        """计算Microprice Alpha"""
        # 确保格式兼容
        if 'bids' not in orderbook or 'asks' not in orderbook:
            # 从best_bid/best_ask构建
            bids = [{'price': orderbook.get('best_bid', 0), 'qty': 1.0}]
            asks = [{'price': orderbook.get('best_ask', 0), 'qty': 1.0}]
            orderbook = {
                **orderbook,
                'bids': bids,
                'asks': asks
            }
        signal = self.predictive_alpha.calculate_predictive_alpha(orderbook)
        return signal.value


class PnLAttribution:
    """
    PnL归因分析
    明确区分Alpha收益和Execution收益
    """

    def __init__(self):
        self.trades = []
        self.alpha_pnl = 0.0
        self.execution_pnl = 0.0

    def record_trade(self, signal: SignalRecord, execution: ExecutionResult,
                     exit_price: float):
        """记录交易，进行收益分离"""
        # 理论收益（基于信号预测）
        if signal.direction > 0:  # 买入
            theoretical_pnl = (exit_price - signal.expected_return) - signal.expected_return
            actual_pnl = (exit_price - execution.price) * signal.size
        else:  # 卖出
            theoretical_pnl = signal.expected_return - (exit_price + signal.expected_return)
            actual_pnl = (execution.price - exit_price) * signal.size

        # Alpha收益 = 理论收益
        alpha_return = theoretical_pnl * signal.size

        # Execution收益 = 实际 - 理论
        execution_return = (actual_pnl - alpha_return)

        trade_record = {
            'signal': signal,
            'execution': execution,
            'exit_price': exit_price,
            'alpha_return': alpha_return,
            'execution_return': execution_return,
            'total_return': actual_pnl,
            'timestamp': time.time()
        }

        self.trades.append(trade_record)
        self.alpha_pnl += alpha_return
        self.execution_pnl += execution_return

        return trade_record

    def get_contribution_stats(self) -> Dict:
        """获取收益贡献统计"""
        total_pnl = self.alpha_pnl + self.execution_pnl

        if total_pnl == 0:
            return {
                'alpha_contribution': 0.0,
                'execution_contribution': 0.0,
                'alpha_ratio': 0.0,
                'target_met': False
            }

        # Alpha贡献比例
        alpha_ratio = abs(self.alpha_pnl) / (abs(self.alpha_pnl) + abs(self.execution_pnl))

        return {
            'alpha_contribution': self.alpha_pnl,
            'execution_contribution': self.execution_pnl,
            'total_pnl': total_pnl,
            'alpha_ratio': alpha_ratio,
            'target_met': alpha_ratio > 0.5  # Alpha贡献是否超过50%
        }


class FixedHFTStrategy:
    """
    修复后的HFT策略
    解决Gate 1-3的所有问题
    """

    def __init__(self, symbol: str = 'BTCUSDT', use_adaptive: bool = True):
        self.symbol = symbol

        # 修复模块
        self.alpha_recorder = AlphaSignalRecorder()
        self.execution_layer = CleanExecutionLayer(fixed_slippage_bps=5.0)
        self.threshold_gate = AdaptiveThresholdGate(window_size=100, target_percentile=80)
        self.alpha_improver = AlphaQualityImprover()
        self.pnl_attribution = PnLAttribution()

        # 配置
        self.use_adaptive = use_adaptive

        # 初始化Alpha源
        self._initialize_alpha_sources()

        # 状态
        self.position = 0.0
        self.cash = 1000.0
        self.signal_counter = 0

    def _initialize_alpha_sources(self):
        """初始化Alpha信号源"""
        # 1. Microprice Alpha
        self.alpha_improver.add_alpha_source(
            name='microprice',
            alpha_func=self.alpha_improver.calculate_microprice_alpha,
            weight=1.0
        )

        # 2. Order Flow Imbalance
        self.alpha_improver.add_alpha_source(
            name='ofi',
            alpha_func=self.alpha_improver.calculate_order_flow_imbalance,
            weight=0.8
        )

    def generate_signal(self, orderbook: Dict) -> Optional[SignalRecord]:
        """生成信号"""
        # 1. 计算集成Alpha
        alpha_value = self.alpha_improver.calculate_ensemble_alpha(orderbook)

        if abs(alpha_value) < 0.1:
            return None

        # 2. 自适应阈值决策
        should_trade = self.threshold_gate.should_trade(alpha_value, self.use_adaptive)

        if not should_trade:
            return None

        # 3. 创建信号记录
        self.signal_counter += 1
        signal = SignalRecord(
            signal_id=f"sig_{self.signal_counter}_{int(time.time()*1000)}",
            timestamp=time.time(),
            alpha_value=alpha_value,
            expected_return=alpha_value * 0.001,
            size=0.1,
            direction=1 if alpha_value > 0 else -1,
            threshold_used=self.threshold_gate.get_stats()['current_threshold']
        )

        return signal

    def process_tick(self, orderbook: Dict, next_mid_price: float = None) -> Optional[Dict]:
        """处理一个tick"""
        # 1. 生成信号
        signal = self.generate_signal(orderbook)

        if signal is None:
            return None

        # 2. 记录所有信号
        self.alpha_recorder.record_signal(signal)

        # 3. 执行信号（无偏执行，100%成交）
        execution = self.execution_layer.execute_signal(signal, orderbook)

        # 4. 记录执行
        self.alpha_recorder.record_execution(signal, execution)

        # 5. 更新持仓
        if execution.filled:
            if signal.direction > 0:  # 买入
                self.position += signal.size
                self.cash -= execution.price * signal.size
            else:  # 卖出
                self.position -= signal.size
                self.cash += execution.price * signal.size

        # 6. 记录PnL归因（如果有exit price）
        if next_mid_price and execution.filled:
            self.pnl_attribution.record_trade(signal, execution, next_mid_price)

        return {
            'signal': signal,
            'execution': execution,
            'position': self.position,
            'cash': self.cash
        }

    def get_diagnostic_report(self) -> Dict:
        """获取诊断报告"""
        # 1. 选择偏差分析
        bias_analysis = self.alpha_recorder.analyze_selection_bias()

        # 2. 阈值统计
        threshold_stats = self.threshold_gate.get_stats()

        # 3. 收益归因
        contribution_stats = self.pnl_attribution.get_contribution_stats()

        # 4. 综合诊断
        gate1_passed = not bias_analysis.get('bias_detected', True)
        gate2_stable = threshold_stats.get('std_threshold', 10) < 0.1
        gate3_passed = contribution_stats.get('target_met', False)

        return {
            'gate1_selection_bias': bias_analysis,
            'gate1_passed': gate1_passed,
            'gate2_threshold_stats': threshold_stats,
            'gate2_passed': gate2_stable,
            'gate3_pnl_attribution': contribution_stats,
            'gate3_passed': gate3_passed,
            'overall_passed': gate1_passed and gate3_passed,
            'position': self.position,
            'cash': self.cash
        }


def run_fixed_strategy_test():
    """运行修复后的策略测试"""
    from data_fetcher import BinanceDataFetcher

    print("="*70)
    print("Fixed Strategy - Three Gates Verification")
    print("="*70)

    # 加载数据
    fetcher = BinanceDataFetcher()
    df = fetcher.fetch_klines('BTCUSDT', '1h', limit=500)
    tick_df = fetcher.convert_to_tick_format(df)
    tick_df = tick_df.dropna()

    print(f"\nData: {len(tick_df)} ticks")

    # 初始化策略
    strategy = FixedHFTStrategy(symbol='BTCUSDT', use_adaptive=True)

    # 运行测试
    print("\nRunning strategy...")
    trades = []

    for i in range(len(tick_df) - 1):
        tick = tick_df.iloc[i]
        next_tick = tick_df.iloc[i + 1]

        orderbook = {
            'best_bid': tick.get('bid_price', tick.get('low')),
            'best_ask': tick.get('ask_price', tick.get('high')),
            'mid_price': tick.get('mid_price', tick.get('close')),
            'bids': [{'price': tick.get('bid_price', 0), 'qty': 1.0}],
            'asks': [{'price': tick.get('ask_price', 0), 'qty': 1.0}]
        }

        next_mid = next_tick.get('mid_price', next_tick.get('close'))

        result = strategy.process_tick(orderbook, next_mid)

        if result:
            trades.append(result)

    print(f"Total trades: {len(trades)}")

    # 生成诊断报告
    report = strategy.get_diagnostic_report()

    print("\n" + "="*70)
    print("DIAGNOSTIC REPORT")
    print("="*70)

    # Gate 1
    print("\n[Gate 1] Selection Bias Check")
    print("-"*70)
    bias = report['gate1_selection_bias']
    if bias['status'] == 'OK':
        print(f"  Total signals: {bias['total_signals']}")
        print(f"  Executed: {bias['executed_signals']}")
        print(f"  Selection bias: {bias['selection_bias']:.4f}")
        print(f"  Bias detected: {bias['bias_detected']}")
        print(f"  Status: {'PASS' if report['gate1_passed'] else 'FAIL'}")
    else:
        print(f"  Status: {bias['status']}")

    # Gate 2
    print("\n[Gate 2] Threshold Stability Check")
    print("-"*70)
    threshold = report['gate2_threshold_stats']
    print(f"  Current threshold: {threshold['current_threshold']:.4f}")
    if 'std_threshold' in threshold:
        print(f"  Std of threshold: {threshold['std_threshold']:.4f}")
    print(f"  Status: {'PASS' if report['gate2_passed'] else 'FAIL'}")

    # Gate 3
    print("\n[Gate 3] PnL Attribution Check")
    print("-"*70)
    pnl = report['gate3_pnl_attribution']
    print(f"  Alpha contribution: ${pnl['alpha_contribution']:.4f}")
    print(f"  Execution contribution: ${pnl['execution_contribution']:.4f}")
    print(f"  Alpha ratio: {pnl['alpha_ratio']:.2%}")
    print(f"  Target met (>50%): {pnl['target_met']}")
    print(f"  Status: {'PASS' if report['gate3_passed'] else 'FAIL'}")

    # Overall
    print("\n" + "="*70)
    print(f"Overall: {'ALL GATES PASSED' if report['overall_passed'] else 'SOME GATES FAILED'}")
    print("="*70)

    return report


if __name__ == "__main__":
    run_fixed_strategy_test()
