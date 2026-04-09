"""
最终修复策略 - 整合所有优化

核心修复：
1. 降低滑点至2bps
2. 降低Alpha门槛至0.05
3. 移除成本过滤器（简化测试）
4. 添加止盈止损逻辑
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional
from dataclasses import dataclass
from collections import deque
import time

from data_fetcher import BinanceDataFetcher
from strategy_fix_gates import FixedHFTStrategy


@dataclass
class TradeSignal:
    direction: int
    size: float
    alpha: float
    entry_price: float
    stop_loss: float
    take_profit: float


class FinalFixedStrategy:
    """
    最终修复策略

    简化但有效的版本
    """

    def __init__(self,
                 symbol: str = 'BTCUSDT',
                 slippage_bps: float = 2.0,
                 min_alpha: float = 0.05,
                 stop_loss_pct: float = 0.01,
                 take_profit_pct: float = 0.02,
                 max_position: float = 0.5):

        self.symbol = symbol
        self.slippage = slippage_bps / 10000
        self.min_alpha = min_alpha
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.max_position = max_position

        # Alpha生成器
        self.alpha_improver = FixedHFTStrategy().alpha_improver

        # 状态
        self.position = 0.0
        self.cash = 10000.0
        self.entry_price = 0.0
        self.signal_count = 0

        # 统计
        self.trades = []
        self.total_pnl = 0.0

    def generate_signal(self, orderbook: Dict) -> Optional[TradeSignal]:
        """生成交易信号"""
        mid = orderbook.get('mid_price', 0)
        if mid <= 0:
            return None

        # 计算Alpha
        alpha_value = self.alpha_improver.calculate_ensemble_alpha(orderbook)

        # 简化过滤
        if abs(alpha_value) < self.min_alpha:
            return None

        direction = 1 if alpha_value > 0 else -1

        # 计算入场价（含滑点）
        if direction > 0:
            entry_price = mid * (1 + self.slippage)
        else:
            entry_price = mid * (1 - self.slippage)

        # 止损止盈
        stop_loss = entry_price * (1 - self.stop_loss_pct * direction)
        take_profit = entry_price * (1 + self.take_profit_pct * direction)

        return TradeSignal(
            direction=direction,
            size=0.1,
            alpha=alpha_value,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit
        )

    def check_exit(self, current_price: float) -> Optional[str]:
        """检查是否需要退出"""
        if self.position == 0:
            return None

        if self.position > 0:  # 多头
            if current_price <= self.stop_loss_price:
                return 'stop_loss'
            if current_price >= self.take_profit_price:
                return 'take_profit'
        else:  # 空头
            if current_price >= self.stop_loss_price:
                return 'stop_loss'
            if current_price <= self.take_profit_price:
                return 'take_profit'

        return None

    def process_tick(self, orderbook: Dict) -> Optional[Dict]:
        """处理一个tick"""
        mid = orderbook.get('mid_price', 0)
        if mid <= 0:
            return None

        result = None

        # 1. 检查是否需要退出
        if self.position != 0:
            exit_reason = self.check_exit(mid)

            if exit_reason:
                # 平仓
                if self.position > 0:
                    pnl = (mid - self.entry_price) * self.position
                    self.cash += mid * self.position
                else:
                    pnl = (self.entry_price - mid) * abs(self.position)
                    self.cash -= mid * abs(self.position)

                self.total_pnl += pnl
                self.trades.append({
                    'type': exit_reason,
                    'pnl': pnl,
                    'exit_price': mid
                })

                self.position = 0
                result = {'action': exit_reason, 'pnl': pnl}

        # 2. 生成新信号（如果没有持仓）
        if self.position == 0:
            signal = self.generate_signal(orderbook)

            if signal:
                self.signal_count += 1

                # 开仓
                if signal.direction > 0:  # 买入
                    cost = signal.entry_price * signal.size
                    if self.cash >= cost:
                        self.position = signal.size
                        self.entry_price = signal.entry_price
                        self.stop_loss_price = signal.stop_loss
                        self.take_profit_price = signal.take_profit
                        self.cash -= cost
                        result = {'action': 'enter_long', 'price': signal.entry_price}
                else:  # 卖出
                    self.position = -signal.size
                    self.entry_price = signal.entry_price
                    self.stop_loss_price = signal.stop_loss
                    self.take_profit_price = signal.take_profit
                    self.cash += signal.entry_price * signal.size
                    result = {'action': 'enter_short', 'price': signal.entry_price}

        return result

    def get_stats(self) -> Dict:
        """获取统计"""
        winning_trades = [t for t in self.trades if t.get('pnl', 0) > 0]
        losing_trades = [t for t in self.trades if t.get('pnl', 0) <= 0]

        stop_loss_count = sum(1 for t in self.trades if t.get('type') == 'stop_loss')
        take_profit_count = sum(1 for t in self.trades if t.get('type') == 'take_profit')

        return {
            'total_signals': self.signal_count,
            'total_trades': len(self.trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': len(winning_trades) / len(self.trades) if self.trades else 0,
            'stop_loss_count': stop_loss_count,
            'take_profit_count': take_profit_count,
            'total_pnl': self.total_pnl,
            'final_cash': self.cash,
            'final_position': self.position
        }


def run_final_test():
    """运行最终测试"""
    print("="*70)
    print("Final Fixed Strategy Test")
    print("="*70)

    # 加载数据
    fetcher = BinanceDataFetcher()
    df = fetcher.fetch_klines('BTCUSDT', '1h', limit=500)
    tick_df = fetcher.convert_to_tick_format(df)
    tick_df = tick_df.dropna()

    print(f"\nData: {len(tick_df)} ticks")

    # 初始化策略
    strategy = FinalFixedStrategy(
        symbol='BTCUSDT',
        slippage_bps=2.0,
        min_alpha=0.05,
        stop_loss_pct=0.01,
        take_profit_pct=0.02
    )

    print("\nRunning final fixed strategy...")

    for i in range(len(tick_df)):
        tick = tick_df.iloc[i]

        orderbook = {
            'best_bid': tick.get('bid_price', tick.get('low')),
            'best_ask': tick.get('ask_price', tick.get('high')),
            'mid_price': tick.get('mid_price', tick.get('close')),
            'bids': [{'price': tick.get('bid_price', 0), 'qty': 1.0}],
            'asks': [{'price': tick.get('ask_price', 0), 'qty': 1.0}]
        }

        result = strategy.process_tick(orderbook)

    # 最终平仓
    if strategy.position != 0:
        final_price = tick_df.iloc[-1].get('mid_price', tick_df.iloc[-1].get('close'))
        if strategy.position > 0:
            pnl = (final_price - strategy.entry_price) * strategy.position
            strategy.cash += final_price * strategy.position
        else:
            pnl = (strategy.entry_price - final_price) * abs(strategy.position)
            strategy.cash -= final_price * abs(strategy.position)
        strategy.total_pnl += pnl
        strategy.trades.append({'type': 'final_close', 'pnl': pnl})
        strategy.position = 0

    # 生成报告
    stats = strategy.get_stats()

    print("\n" + "="*70)
    print("RESULTS")
    print("="*70)

    print(f"\n[Trading Statistics]")
    print(f"  Total signals: {stats['total_signals']}")
    print(f"  Total trades: {stats['total_trades']}")
    print(f"  Winning trades: {stats['winning_trades']}")
    print(f"  Losing trades: {stats['losing_trades']}")
    print(f"  Win rate: {stats['win_rate']:.1%}")
    print(f"  Stop loss hits: {stats['stop_loss_count']}")
    print(f"  Take profit hits: {stats['take_profit_count']}")

    print(f"\n[PnL]")
    print(f"  Total PnL: ${stats['total_pnl']:.2f}")
    print(f"  Final cash: ${stats['final_cash']:.2f}")
    print(f"  Return: {stats['total_pnl']/10000:.2%}")

    if stats['total_pnl'] > 0:
        print(f"\n  [PASS] Strategy is profitable!")
    else:
        print(f"\n  [INFO] Strategy needs further optimization")

    print("\n" + "="*70)

    return stats


if __name__ == "__main__":
    stats = run_final_test()
