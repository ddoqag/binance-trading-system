"""
ForceFill 三模式测试
目标：分离策略Alpha与执行优势
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Trade:
    """交易记录"""
    timestamp: datetime
    side: str
    price: float
    quantity: float
    slippage: float
    fill_probability: float
    mode: str
    pnl: float = 0.0


class ForceFillThreeMode:
    """
    ForceFill 三模式测试

    三种测试模式：
    1. Alpha-only: 理想成交，无滑点，100%成交 - 测试纯信号质量
    2. Execution-only: 随机信号，真实执行 - 测试纯执行能力
    3. Full system: 策略信号 + 真实执行 - 测试综合表现
    """

    def __init__(self, strategy, data: pd.DataFrame, initial_capital: float = 1000.0):
        """
        初始化三模式测试

        Args:
            strategy: 策略对象，需实现generate_signal方法
            data: 市场数据DataFrame
            initial_capital: 初始资金
        """
        self.strategy = strategy
        self.data = data
        self.initial_capital = initial_capital
        self.results = {}

    def run_all_modes(self, verbose: bool = True) -> Dict:
        """运行三模式测试"""
        if verbose:
            print("\n" + "=" * 70)
            print("         ForceFill Three-Mode Test")
            print("=" * 70)
            print(f"Data size: {len(self.data)} ticks")
            print(f"Initial capital: ${self.initial_capital:,.2f}")
            print("=" * 70 + "\n")

        # 模式1: Alpha-only（理想成交）
        if verbose:
            print("[MODE 1] Alpha-only: Ideal execution")
        result1 = self._run_alpha_only()
        self.results['alpha_only'] = result1

        if verbose:
            print(f"  Sharpe: {result1['sharpe']:.2f}")
            print(f"  Win rate: {result1['win_rate']:.1%}")
            print(f"  Trades: {result1['n_trades']}")
            print(f"  PnL: ${result1['total_pnl']:.2f}\n")

        # 模式2: Execution-only（随机信号，真实执行）
        if verbose:
            print("[MODE 2] Execution-only: Random signals, real execution")
        result2 = self._run_execution_only()
        self.results['execution_only'] = result2

        if verbose:
            print(f"  Sharpe: {result2['sharpe']:.2f}")
            print(f"  Win rate: {result2['win_rate']:.1%}")
            print(f"  Trades: {result2['n_trades']}")
            print(f"  PnL: ${result2['total_pnl']:.2f}\n")

        # 模式3: Full system（真实）
        if verbose:
            print("[MODE 3] Full system: Strategy signals + real execution")
        result3 = self._run_full_system()
        self.results['full_system'] = result3

        if verbose:
            print(f"  Sharpe: {result3['sharpe']:.2f}")
            print(f"  Win rate: {result3['win_rate']:.1%}")
            print(f"  Trades: {result3['n_trades']}")
            print(f"  PnL: ${result3['total_pnl']:.2f}\n")

        # 分析结果
        if verbose:
            self._analyze_results()

        return self.results

    def _run_alpha_only(self) -> Dict:
        """Alpha-only 模式：假设理想成交"""
        trades = []
        position = 0.0
        entry_price = 0.0
        pnl_history = []

        for i in range(len(self.data) - 1):
            tick = self.data.iloc[i]
            next_tick = self.data.iloc[i + 1]

            # 获取策略信号
            try:
                signal = self._get_signal(tick)
            except Exception:
                signal = {'direction': 0, 'strength': 0}

            if abs(signal.get('direction', 0)) > 0.3:  # 有交易信号
                side = 'buy' if signal['direction'] > 0 else 'sell'
                quantity = signal.get('quantity', 0.01)

                # 理想成交：立即以当前mid价格成交
                if side == 'buy':
                    fill_price = tick.get('mid_price', tick.get('close', 50000))
                    if position <= 0:  # 可以买入
                        position += quantity
                        entry_price = fill_price

                        # 计算PnL（假设下一个tick平仓）
                        exit_price = next_tick.get('mid_price', next_tick.get('close', fill_price))
                        pnl = (exit_price - fill_price) * quantity
                        pnl_history.append(pnl)

                        trade = {
                            'timestamp': tick.name if hasattr(tick, 'name') else i,
                            'side': side,
                            'price': fill_price,
                            'quantity': quantity,
                            'slippage': 0,
                            'fill_probability': 1.0,
                            'mode': 'alpha_only',
                            'pnl': pnl
                        }
                        trades.append(trade)

                else:  # sell
                    fill_price = tick.get('mid_price', tick.get('close', 50000))
                    if position >= 0:  # 可以卖出
                        position -= quantity

                        # 计算PnL
                        exit_price = next_tick.get('mid_price', next_tick.get('close', fill_price))
                        pnl = (fill_price - exit_price) * quantity
                        pnl_history.append(pnl)

                        trade = {
                            'timestamp': tick.name if hasattr(tick, 'name') else i,
                            'side': side,
                            'price': fill_price,
                            'quantity': quantity,
                            'slippage': 0,
                            'fill_probability': 1.0,
                            'mode': 'alpha_only',
                            'pnl': pnl
                        }
                        trades.append(trade)

        return self._calculate_metrics(trades, pnl_history)

    def _run_execution_only(self) -> Dict:
        """Execution-only 模式：随机信号，真实执行"""
        trades = []
        pnl_history = []
        np.random.seed(42)

        for i in range(len(self.data) - 1):
            tick = self.data.iloc[i]
            next_tick = self.data.iloc[i + 1]

            # 随机信号（5%概率交易）
            if np.random.rand() < 0.05:
                side = np.random.choice(['buy', 'sell'])
                quantity = np.random.uniform(0.01, 0.05)

                # 通过真实执行模型
                execution_result = self._execute_order(tick, side, quantity)

                if execution_result['filled']:
                    # 计算PnL
                    if side == 'buy':
                        exit_price = next_tick.get('mid_price', next_tick.get('close', execution_result['price']))
                        pnl = (exit_price - execution_result['price']) * quantity
                    else:
                        exit_price = next_tick.get('mid_price', next_tick.get('close', execution_result['price']))
                        pnl = (execution_result['price'] - exit_price) * quantity

                    pnl_history.append(pnl)

                    trade = {
                        'timestamp': tick.name if hasattr(tick, 'name') else i,
                        'side': side,
                        'price': execution_result['price'],
                        'quantity': quantity,
                        'slippage': execution_result['slippage'],
                        'fill_probability': execution_result['fill_probability'],
                        'mode': 'execution_only',
                        'pnl': pnl
                    }
                    trades.append(trade)

        return self._calculate_metrics(trades, pnl_history)

    def _run_full_system(self) -> Dict:
        """Full system 模式：策略信号 + 真实执行"""
        trades = []
        pnl_history = []

        for i in range(len(self.data) - 1):
            tick = self.data.iloc[i]
            next_tick = self.data.iloc[i + 1]

            # 获取策略信号
            try:
                signal = self._get_signal(tick)
            except Exception:
                signal = {'direction': 0, 'strength': 0}

            if abs(signal.get('direction', 0)) > 0.3:  # 有交易信号
                side = 'buy' if signal['direction'] > 0 else 'sell'
                quantity = signal.get('quantity', 0.01)

                # 通过真实执行模型
                execution_result = self._execute_order(tick, side, quantity)

                if execution_result['filled']:
                    # 计算PnL
                    if side == 'buy':
                        exit_price = next_tick.get('mid_price', next_tick.get('close', execution_result['price']))
                        pnl = (exit_price - execution_result['price']) * quantity
                    else:
                        exit_price = next_tick.get('mid_price', next_tick.get('close', execution_result['price']))
                        pnl = (execution_result['price'] - exit_price) * quantity

                    pnl_history.append(pnl)

                    trade = {
                        'timestamp': tick.name if hasattr(tick, 'name') else i,
                        'side': side,
                        'price': execution_result['price'],
                        'quantity': quantity,
                        'slippage': execution_result['slippage'],
                        'fill_probability': execution_result['fill_probability'],
                        'mode': 'full_system',
                        'pnl': pnl
                    }
                    trades.append(trade)

        return self._calculate_metrics(trades, pnl_history)

    def _get_signal(self, tick) -> Dict:
        """获取策略信号"""
        # 将tick数据转换为orderbook格式
        orderbook = self._tick_to_orderbook(tick)

        if hasattr(self.strategy, 'generate_signal'):
            return self.strategy.generate_signal(orderbook)
        elif hasattr(self.strategy, 'process_tick'):
            # MVPTrader风格
            order = self.strategy.process_tick(orderbook)
            if order:
                return {
                    'direction': 1 if order.get('side') == 'buy' else -1,
                    'quantity': order.get('quantity', 0.01),
                    'price': order.get('price', orderbook.get('mid_price'))
                }
            return {'direction': 0}
        else:
            # 简单均值回归信号
            mid_price = orderbook.get('mid_price', 50000)
            return {'direction': 0}

    def _tick_to_orderbook(self, tick) -> Dict:
        """将tick数据转换为orderbook格式"""
        # 获取价格
        bid_price = tick.get('bid_price', tick.get('low', tick.get('close', 50000)))
        ask_price = tick.get('ask_price', tick.get('high', tick.get('close', 50000)))
        mid_price = tick.get('mid_price', (bid_price + ask_price) / 2)

        # 构建orderbook格式（与spread_capture期望的格式一致）
        orderbook = {
            'timestamp': tick.name if hasattr(tick, 'name') else None,
            'bid_price': bid_price,
            'ask_price': ask_price,
            'mid_price': mid_price,
            'spread': ask_price - bid_price,
            # spread_capture期望bids/asks是字典列表
            'bids': [{'price': bid_price, 'qty': tick.get('bid_qty', 1.0)}],
            'asks': [{'price': ask_price, 'qty': tick.get('ask_qty', 1.0)}],
            'bid_qty': tick.get('bid_qty', 1.0),
            'ask_qty': tick.get('ask_qty', 1.0),
            'volume': tick.get('volume', 0)
        }

        return orderbook

    def _execute_order(self, tick, side: str, quantity: float) -> Dict:
        """真实执行模型（带队列位置、成交率等）"""
        # 获取当前队列位置
        queue_position = self._get_queue_position(tick, side)

        # 计算成交概率（基于hazard model简化版）
        base_rate = 1.0
        queue_factor = np.exp(-2.0 * queue_position)  # 队列越靠前概率越高
        hazard_rate = base_rate * queue_factor

        # 假设1个tick的时间窗口
        fill_probability = 1 - np.exp(-hazard_rate * 0.1)

        # 是否成交
        filled = np.random.rand() < fill_probability

        if filled:
            # 计算滑点
            slippage = self._calculate_slippage(tick, side, queue_position)

            # 成交价格
            if side == 'buy':
                base_price = tick.get('ask_price', tick.get('high', tick.get('close', 50000)))
                price = base_price + slippage
            else:
                base_price = tick.get('bid_price', tick.get('low', tick.get('close', 50000)))
                price = base_price - slippage

            return {
                'filled': True,
                'price': price,
                'slippage': slippage,
                'fill_probability': fill_probability
            }
        else:
            return {'filled': False}

    def _get_queue_position(self, tick, side: str) -> float:
        """获取队列位置"""
        # 简化模型：随机队列位置
        # 实际应该基于订单簿深度和当前挂单计算
        return np.random.uniform(0, 1)

    def _calculate_slippage(self, tick, side: str, queue_position: float) -> float:
        """计算滑点"""
        base_price = tick.get('mid_price', tick.get('close', 50000))

        # 滑点模型：
        # 1. 基础滑点（市场影响）
        base_slippage = base_price * 0.0001  # 1 bps

        # 2. 队列位置惩罚（越靠后滑点越大）
        queue_penalty = queue_position * base_price * 0.0002  # 最多2 bps

        # 3. 点差影响
        spread = tick.get('spread', 0)
        spread_slippage = spread * base_price * 0.0001

        total_slippage = base_slippage + queue_penalty + spread_slippage

        return total_slippage

    def _calculate_metrics(self, trades: List[Dict], pnl_history: List[float]) -> Dict:
        """计算表现指标"""
        if not trades or not pnl_history:
            return {
                'trades': trades,
                'total_pnl': 0.0,
                'sharpe': 0.0,
                'win_rate': 0.0,
                'n_trades': 0
            }

        pnl_array = np.array(pnl_history)

        # 总PnL
        total_pnl = np.sum(pnl_array)

        # 夏普比率
        if len(pnl_array) > 1 and np.std(pnl_array) > 0:
            sharpe = np.mean(pnl_array) / np.std(pnl_array) * np.sqrt(252)
        else:
            sharpe = 0.0

        # 胜率
        win_rate = np.mean(pnl_array > 0) if len(pnl_array) > 0 else 0.0

        return {
            'trades': trades,
            'total_pnl': total_pnl,
            'sharpe': sharpe,
            'win_rate': win_rate,
            'n_trades': len(trades)
        }

    def _analyze_results(self):
        """分析三模式结果"""
        alpha_sharpe = self.results['alpha_only']['sharpe']
        exec_sharpe = self.results['execution_only']['sharpe']
        full_sharpe = self.results['full_system']['sharpe']

        print("=" * 70)
        print("         Three-Mode Analysis")
        print("=" * 70)
        print(f"\nAlpha-only Sharpe:    {alpha_sharpe:.2f}")
        print(f"Execution-only Sharpe: {exec_sharpe:.2f}")
        print(f"Full system Sharpe:   {full_sharpe:.2f}")

        # 关键判断
        print("\n" + "-" * 70)

        if alpha_sharpe > 2 and exec_sharpe < 0:
            print("[VERDICT] Strategy has Alpha, but execution is a disadvantage")
            print("[ACTION]  Optimize execution engine or switch to market orders")

        elif alpha_sharpe < 0 and exec_sharpe > 0:
            print("[VERDICT] Strategy has no Alpha, but has execution advantage")
            print("[ACTION]  Consider market-making strategy")

        elif alpha_sharpe > 0 and exec_sharpe > 0:
            print("[VERDICT] Alpha + Execution dual advantage")
            print("[ACTION]  Ready for live testing")

        elif alpha_sharpe < 0 and exec_sharpe < 0:
            print("[VERDICT] Complete failure")
            print("[ACTION]  Redesign strategy from scratch")

        else:
            print("[VERDICT] Borderline case")
            print("[ACTION]  Need more data for validation")

        # 计算衰减
        if abs(alpha_sharpe) > 0.01:
            execution_decay = full_sharpe / alpha_sharpe
            print(f"\nExecution decay: {execution_decay:.2%}")

            if execution_decay < 0.3:
                print("[WARNING] Severe execution decay - execution is destroying alpha")
            elif execution_decay < 0.7:
                print("[WARNING] Moderate execution decay - room for improvement")
            else:
                print("[OK] Execution preserves most of the alpha")

        print("=" * 70)


# 简单的随机策略（用于对比）
class RandomStrategy:
    """随机策略 - 作为基准对比"""

    def __init__(self, seed=42):
        np.random.seed(seed)

    def generate_signal(self, tick):
        """生成随机信号"""
        if np.random.rand() < 0.1:  # 10%概率交易
            return {
                'direction': np.random.choice([-1, 1]),
                'quantity': np.random.uniform(0.01, 0.05)
            }
        return {'direction': 0}


if __name__ == "__main__":
    # 测试
    print("=" * 70)
    print("ForceFill Three-Mode Test")
    print("=" * 70)

    # 创建模拟数据
    np.random.seed(42)
    n = 1000
    data = pd.DataFrame({
        'open': np.cumsum(np.random.normal(0, 1, n)) + 50000,
        'high': np.cumsum(np.random.normal(0, 1, n)) + 50100,
        'low': np.cumsum(np.random.normal(0, 1, n)) + 49900,
        'close': np.cumsum(np.random.normal(0, 1, n)) + 50000,
        'bid_price': np.cumsum(np.random.normal(0, 1, n)) + 49995,
        'ask_price': np.cumsum(np.random.normal(0, 1, n)) + 50005,
        'mid_price': np.cumsum(np.random.normal(0, 1, n)) + 50000,
        'spread': np.random.uniform(1, 10, n),
        'volume': np.random.uniform(100, 1000, n)
    })
    data.index = pd.date_range('2024-01-01', periods=n, freq='1min')

    # 测试随机策略
    strategy = RandomStrategy()

    tester = ForceFillThreeMode(strategy, data, initial_capital=1000.0)
    results = tester.run_all_modes(verbose=True)

    print("\nTest complete!")
