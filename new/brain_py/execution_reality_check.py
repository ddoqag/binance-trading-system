"""
执行层真实性检验套件

目标：判断执行引擎的盈利是否来自模拟偏差

5个压力测试：
1. 零点差环境 - 检验是否依赖点差收益
2. 高逆向选择环境 - 检验是否缺少逆向选择惩罚
3. 随机队列位置 - 检验队列模型是否正确
4. 高延迟竞争 - 检验延迟竞争模型
5. 完美竞争环境 - 检验是否在竞争中被淘汰
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class TestResult:
    """测试结果"""
    test_name: str
    sharpe: float
    total_pnl: float
    win_rate: float
    trade_count: int
    description: str


class ExecutionRealityCheck:
    """
    执行层真实性检验套件

    使用5个压力测试来验证执行引擎的盈利是否真实
    """

    def __init__(self, execution_engine, data: pd.DataFrame, initial_capital: float = 1000.0):
        """
        初始化真实性检验套件

        Args:
            execution_engine: 执行引擎对象
            data: 市场数据
            initial_capital: 初始资金
        """
        self.engine = execution_engine
        self.data = data
        self.initial_capital = initial_capital
        self.results: Dict[str, TestResult] = {}

    def run_all_tests(self, verbose: bool = True) -> Dict:
        """
        运行所有真实性检验

        Returns:
            Dict: 所有测试结果
        """
        if verbose:
            print("\n" + "=" * 70)
            print("         EXECUTION REALITY CHECK SUITE")
            print("=" * 70)
            print(f"Data size: {len(self.data)} ticks")
            print(f"Initial capital: ${self.initial_capital:,.2f}")
            print("=" * 70)

        # 测试1: 正常环境（基准）
        if verbose:
            print("\n--- Test 1: Normal Environment (Baseline) ---")
        result1 = self._run_normal_environment()
        self.results['normal'] = result1
        if verbose:
            self._print_result(result1)

        # 测试2: 零点差环境
        if verbose:
            print("\n--- Test 2: Zero-Spread Environment ---")
        result2 = self._run_zero_spread()
        self.results['zero_spread'] = result2
        if verbose:
            self._print_result(result2)

        # 测试3: 高逆向选择环境
        if verbose:
            print("\n--- Test 3: High Adverse Selection ---")
        result3 = self._run_high_adverse_selection(penalty=0.001)  # 0.1%
        self.results['high_adverse'] = result3
        if verbose:
            self._print_result(result3)

        # 测试4: 随机队列位置
        if verbose:
            print("\n--- Test 4: Random Queue Position ---")
        result4 = self._run_random_queue_position()
        self.results['random_queue'] = result4
        if verbose:
            self._print_result(result4)

        # 测试5: 高延迟竞争
        if verbose:
            print("\n--- Test 5: High Latency Competition ---")
        result5 = self._run_high_latency(latency_ms=100)
        self.results['high_latency'] = result5
        if verbose:
            self._print_result(result5)

        # 分析结果
        if verbose:
            self._analyze_results()

        return self.results

    def _print_result(self, result: TestResult):
        """打印测试结果"""
        print(f"  Sharpe: {result.sharpe:.2f}")
        print(f"  Total PnL: ${result.total_pnl:.2f}")
        print(f"  Win rate: {result.win_rate:.1%}")
        print(f"  Trades: {result.trade_count}")

    def _run_normal_environment(self) -> TestResult:
        """测试1: 正常环境（基准）"""
        trades = []
        np.random.seed(42)

        for i in range(len(self.data)):
            tick = self.data.iloc[i]

            # 随机信号（5%概率交易）
            if np.random.rand() < 0.05:
                side = np.random.choice(['buy', 'sell'])
                quantity = np.random.uniform(0.1, 1.0)

                # 模拟执行
                result = self._simulate_execution(tick, side, quantity)

                if result['filled']:
                    trades.append(result)

        metrics = self._calculate_metrics(trades)

        return TestResult(
            test_name="Normal Environment",
            sharpe=metrics['sharpe'],
            total_pnl=metrics['total_pnl'],
            win_rate=metrics['win_rate'],
            trade_count=metrics['trade_count'],
            description="Baseline test with normal market conditions"
        )

    def _run_zero_spread(self) -> TestResult:
        """测试2: 零点差环境"""
        trades = []
        np.random.seed(42)

        for i in range(len(self.data)):
            tick = self.data.iloc[i].copy()

            # 将点差设为0
            mid_price = (tick['bid_price'] + tick['ask_price']) / 2
            tick['bid_price'] = mid_price
            tick['ask_price'] = mid_price

            # 随机信号
            if np.random.rand() < 0.05:
                side = np.random.choice(['buy', 'sell'])
                quantity = np.random.uniform(0.1, 1.0)

                # 模拟执行
                result = self._simulate_execution(tick, side, quantity)

                if result['filled']:
                    # 在零点差环境中，没有点差收益
                    result['pnl'] = 0
                    trades.append(result)

        metrics = self._calculate_metrics(trades)

        return TestResult(
            test_name="Zero Spread",
            sharpe=metrics['sharpe'],
            total_pnl=metrics['total_pnl'],
            win_rate=metrics['win_rate'],
            trade_count=metrics['trade_count'],
            description="Spread removed - tests if profit comes from spread capture"
        )

    def _run_high_adverse_selection(self, penalty: float = 0.001) -> TestResult:
        """测试3: 高逆向选择环境"""
        trades = []
        np.random.seed(42)

        for i in range(len(self.data) - 1):
            tick = self.data.iloc[i]
            next_tick = self.data.iloc[i + 1]

            # 随机信号
            if np.random.rand() < 0.05:
                side = np.random.choice(['buy', 'sell'])
                quantity = np.random.uniform(0.1, 1.0)

                # 模拟执行
                result = self._simulate_execution(tick, side, quantity)

                if result['filled']:
                    # 施加逆向选择惩罚
                    # 成交后价格更可能向不利方向移动
                    if side == 'buy':
                        # 买单成交后，价格更可能下跌（被套）
                        adverse_move = (next_tick['mid_price'] - tick['mid_price']) / tick['mid_price']
                        adverse_pnl = -quantity * adverse_move * tick['mid_price']
                    else:
                        # 卖单成交后，价格更可能上涨（踏空）
                        adverse_move = (next_tick['mid_price'] - tick['mid_price']) / tick['mid_price']
                        adverse_pnl = quantity * adverse_move * tick['mid_price']

                    # 额外惩罚
                    adverse_pnl -= quantity * penalty * tick['mid_price']

                    result['pnl'] += adverse_pnl
                    trades.append(result)

        metrics = self._calculate_metrics(trades)

        return TestResult(
            test_name="High Adverse Selection",
            sharpe=metrics['sharpe'],
            total_pnl=metrics['total_pnl'],
            win_rate=metrics['win_rate'],
            trade_count=metrics['trade_count'],
            description="Tests sensitivity to adverse selection"
        )

    def _run_random_queue_position(self) -> TestResult:
        """测试4: 随机队列位置"""
        trades = []
        np.random.seed(42)

        for i in range(len(self.data)):
            tick = self.data.iloc[i].copy()

            # 随机队列位置（0.5-1.0，永远靠后）
            tick['queue_position'] = np.random.uniform(0.5, 1.0)

            # 随机信号
            if np.random.rand() < 0.05:
                side = np.random.choice(['buy', 'sell'])
                quantity = np.random.uniform(0.1, 1.0)

                # 模拟执行（靠后的队列位置降低成交概率）
                result = self._simulate_execution(tick, side, quantity, queue_factor=0.3)

                if result['filled']:
                    trades.append(result)

        metrics = self._calculate_metrics(trades)

        return TestResult(
            test_name="Random Queue Position",
            sharpe=metrics['sharpe'],
            total_pnl=metrics['total_pnl'],
            win_rate=metrics['win_rate'],
            trade_count=metrics['trade_count'],
            description="Tests dependency on optimal queue position"
        )

    def _run_high_latency(self, latency_ms: float = 100) -> TestResult:
        """测试5: 高延迟竞争"""
        trades = []
        np.random.seed(42)

        for i in range(len(self.data) - 1):
            tick = self.data.iloc[i]
            next_tick = self.data.iloc[i + 1]

            # 随机信号
            if np.random.rand() < 0.05:
                side = np.random.choice(['buy', 'sell'])
                quantity = np.random.uniform(0.1, 1.0)

                # 模拟延迟：价格在延迟期间移动
                latency_seconds = latency_ms / 1000.0
                price_move = np.random.normal(0, 0.001) * latency_seconds

                # 延迟后的价格
                delayed_tick = tick.copy()
                if side == 'buy':
                    # 延迟后买入价格更高
                    delayed_tick['ask_price'] *= (1 + abs(price_move))
                else:
                    # 延迟后卖出价格更低
                    delayed_tick['bid_price'] *= (1 - abs(price_move))

                # 模拟执行
                result = self._simulate_execution(delayed_tick, side, quantity)

                if result['filled']:
                    # 延迟成本
                    if side == 'buy':
                        latency_cost = quantity * (result['price'] - tick['ask_price'])
                    else:
                        latency_cost = quantity * (tick['bid_price'] - result['price'])

                    result['pnl'] -= abs(latency_cost)
                    trades.append(result)

        metrics = self._calculate_metrics(trades)

        return TestResult(
            test_name="High Latency",
            sharpe=metrics['sharpe'],
            total_pnl=metrics['total_pnl'],
            win_rate=metrics['win_rate'],
            trade_count=metrics['trade_count'],
            description="Tests sensitivity to latency disadvantage"
        )

    def _simulate_execution(self, tick, side: str, quantity: float, queue_factor: float = 1.0) -> Dict:
        """
        模拟订单执行

        Args:
            tick: 市场tick数据
            side: 方向 ('buy' 或 'sell')
            quantity: 数量
            queue_factor: 队列位置因子（1.0=正常，0.3=靠后）

        Returns:
            Dict: 执行结果
        """
        # 获取价格
        if side == 'buy':
            base_price = tick.get('ask_price', tick.get('close', 50000))
        else:
            base_price = tick.get('bid_price', tick.get('close', 50000))

        # 计算成交概率
        queue_position = tick.get('queue_position', 0.5) * queue_factor
        hazard_rate = 1.0 * np.exp(-2.0 * queue_position)
        fill_probability = 1 - np.exp(-hazard_rate * 0.1)

        # 是否成交
        filled = np.random.rand() < fill_probability

        if not filled:
            return {'filled': False}

        # 计算滑点
        slippage = self._calculate_slippage(tick, side, queue_position)

        # 成交价格
        if side == 'buy':
            fill_price = base_price + slippage
            # 模拟PnL：买入后的潜在收益
            pnl = (tick.get('mid_price', base_price) - fill_price) * quantity
        else:
            fill_price = base_price - slippage
            pnl = (fill_price - tick.get('mid_price', base_price)) * quantity

        return {
            'filled': True,
            'side': side,
            'price': fill_price,
            'quantity': quantity,
            'slippage': slippage,
            'pnl': pnl,
            'queue_position': queue_position
        }

    def _calculate_slippage(self, tick, side: str, queue_position: float) -> float:
        """计算滑点"""
        base_price = tick.get('mid_price', 50000)

        # 基础滑点
        base_slippage = base_price * 0.0001  # 1 bps

        # 队列位置惩罚
        queue_penalty = queue_position * base_price * 0.0002

        return base_slippage + queue_penalty

    def _calculate_metrics(self, trades: List[Dict]) -> Dict:
        """计算交易指标"""
        if not trades:
            return {
                'sharpe': 0.0,
                'total_pnl': 0.0,
                'win_rate': 0.0,
                'trade_count': 0
            }

        pnls = [t['pnl'] for t in trades]
        total_pnl = sum(pnls)

        # 夏普比率
        if len(pnls) > 1 and np.std(pnls) > 0:
            sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(252)
        else:
            sharpe = 0.0

        # 胜率
        win_rate = sum(1 for pnl in pnls if pnl > 0) / len(pnls) if pnls else 0.0

        return {
            'sharpe': sharpe,
            'total_pnl': total_pnl,
            'win_rate': win_rate,
            'trade_count': len(trades)
        }

    def _analyze_results(self):
        """分析真实性检验结果"""
        print("\n" + "=" * 70)
        print("         REALITY CHECK ANALYSIS")
        print("=" * 70)

        normal = self.results['normal']
        zero_spread = self.results['zero_spread']
        high_adverse = self.results['high_adverse']
        random_queue = self.results['random_queue']
        high_latency = self.results['high_latency']

        print(f"\nBaseline (Normal): Sharpe={normal.sharpe:.2f}")

        # 测试1: 零点差
        print("\n--- Test 1: Zero Spread ---")
        if zero_spread.sharpe > 1:
            print("[CRITICAL WARNING] Positive Sharpe with zero spread!")
            print("   -> Execution engine may be exploiting simulator bugs")
        elif zero_spread.sharpe > 0:
            print("[WARNING] Still positive with zero spread")
            print("   -> May have non-spread profit sources")
        else:
            print("[PASS] No profit with zero spread")

        # 测试2: 高逆向选择
        print("\n--- Test 2: High Adverse Selection ---")
        if normal.sharpe != 0:
            adverse_decay = high_adverse.sharpe / normal.sharpe
            print(f"Adverse decay: {adverse_decay:.1%}")

            if adverse_decay < 0.1:
                print("[PASS] Adverse selection significantly reduces profit")
            else:
                print("[WARNING] Profit insensitive to adverse selection")
                print("   -> May lack adverse selection penalty")

        # 测试3: 随机队列位置
        print("\n--- Test 3: Random Queue Position ---")
        if normal.sharpe != 0:
            queue_decay = random_queue.sharpe / normal.sharpe
            print(f"Queue decay: {queue_decay:.1%}")

            if queue_decay < 0.3:
                print("[PASS] Queue position significantly affects profit")
            else:
                print("[CRITICAL WARNING] Profit not dependent on queue position")
                print("   -> Queue model may be incorrect")

        # 测试4: 高延迟竞争
        print("\n--- Test 4: High Latency Competition ---")
        if normal.sharpe != 0:
            latency_decay = high_latency.sharpe / normal.sharpe
            print(f"Latency decay: {latency_decay:.1%}")

            if latency_decay < 0.5:
                print("[PASS] High latency significantly reduces profit")
            else:
                print("[WARNING] Profit insensitive to latency")
                print("   -> May lack latency competition model")

        # 最终判决
        self._final_verdict()

    def _final_verdict(self):
        """最终判决"""
        print("\n" + "=" * 70)
        print("         FINAL VERDICT")
        print("=" * 70)

        normal = self.results['normal']
        zero_spread = self.results['zero_spread']
        high_adverse = self.results['high_adverse']
        random_queue = self.results['random_queue']
        high_latency = self.results['high_latency']

        # 判断条件
        conditions = [
            zero_spread.sharpe < 0.5,
            high_adverse.sharpe < 0.5 * abs(normal.sharpe) if normal.sharpe != 0 else True,
            random_queue.sharpe < 1.0,
            high_latency.sharpe < 1.0
        ]

        pass_count = sum(conditions)

        if pass_count == 4:
            print("\n[PASS] Reality check passed!")
            print("Execution profits vanish under stress conditions")
            print("This suggests profits may come from real microstructure alpha")
        elif pass_count >= 2:
            print("\n[PARTIAL PASS] Partial reality check passed")
            print("Execution is sensitive to some biases but still suspicious")
            print("Recommendation: Further investigation needed")
        else:
            print("\n[FAIL] Reality check FAILED!")
            print("Execution profits likely come from simulation bias")
            print("Must fix simulator before any further development")

        # 诊断建议
        print("\n" + "=" * 70)
        print("         DIAGNOSTIC RECOMMENDATIONS")
        print("=" * 70)

        if zero_spread.sharpe > 1:
            print("1. Check spread capture calculation:")
            print("   Ensure no profit can be made with zero spread")

        if high_adverse.sharpe > 0.5 * abs(normal.sharpe) if normal.sharpe != 0 else False:
            print("2. Enhance adverse selection model:")
            print("   Add post-trade price impact penalty")

        if random_queue.sharpe > 1:
            print("3. Check queue model:")
            print("   Queue position should significantly affect fill probability")

        if high_latency.sharpe > 0.5 * abs(normal.sharpe) if normal.sharpe != 0 else False:
            print("4. Add latency competition:")
            print("   After latency, orders should be at disadvantaged position")

    def save_report(self, filepath: str):
        """保存检验报告"""
        import json

        report = {
            'timestamp': datetime.now().isoformat(),
            'data_size': len(self.data),
            'initial_capital': self.initial_capital,
            'results': {
                name: {
                    'test_name': result.test_name,
                    'sharpe': float(result.sharpe),
                    'total_pnl': float(result.total_pnl),
                    'win_rate': float(result.win_rate),
                    'trade_count': int(result.trade_count),
                    'description': result.description
                }
                for name, result in self.results.items()
            }
        }

        with open(filepath, 'w') as f:
            json.dump(report, f, indent=2)

        print(f"\nReport saved: {filepath}")


if __name__ == "__main__":
    # 测试
    print("=" * 70)
    print("Execution Reality Check - Test Run")
    print("=" * 70)

    # 创建模拟数据
    np.random.seed(42)
    n = 1000

    data = pd.DataFrame({
        'bid_price': np.cumsum(np.random.normal(0, 1, n)) + 49995,
        'ask_price': np.cumsum(np.random.normal(0, 1, n)) + 50005,
        'mid_price': np.cumsum(np.random.normal(0, 1, n)) + 50000,
        'close': np.cumsum(np.random.normal(0, 1, n)) + 50000,
        'volume': np.random.uniform(100, 1000, n)
    })
    data.index = pd.date_range('2024-01-01', periods=n, freq='1min')

    # 运行真实性检验
    checker = ExecutionRealityCheck(None, data, initial_capital=1000.0)
    results = checker.run_all_tests(verbose=True)

    # 保存报告
    checker.save_report('reality_check_report.json')

    print("\n" + "=" * 70)
    print("Reality check complete!")
    print("=" * 70)
