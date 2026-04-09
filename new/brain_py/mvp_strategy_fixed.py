"""
MVP策略修复版
修复：反转信号方向逻辑
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional


class MVPTraderFixed:
    """
    MVP策略 - 修复信号方向

    原逻辑（错误）：
    - 低位买点差（看涨）-> 实际市场下跌
    - 高位卖点差（看跌）-> 实际市场上涨

    新逻辑（正确）：
    - 低位卖点差（看跌）-> 捕捉下跌趋势
    - 高位买点差（看涨）-> 捕捉上涨趋势

    核心逻辑：跟随趋势，而不是反向操作
    """

    def __init__(self, symbol: str = 'BTCUSDT',
                 initial_capital: float = 10000.0,
                 max_position: float = 0.1,
                 min_spread_ticks: int = 2,
                 tick_size: float = 0.01):
        self.symbol = symbol
        self.initial_capital = initial_capital
        self.max_position = max_position
        self.min_spread_ticks = min_spread_ticks
        self.tick_size = tick_size

        self.position = 0.0
        self.cash = initial_capital
        self.trades = []

    def generate_signal(self, tick: pd.Series) -> Dict:
        """
        生成交易信号（修复版）

        逻辑：
        1. 计算当前点差
        2. 计算价格在近期区间的位置
        3. 价格高位 -> 看涨（买点差）
        4. 价格低位 -> 看跌（卖点差）
        """
        # 获取价格
        bid = tick.get('bid_price', tick.get('low', tick.get('close', 0)))
        ask = tick.get('ask_price', tick.get('high', tick.get('close', 0)))
        mid = tick.get('mid_price', (bid + ask) / 2)
        spread = ask - bid

        if mid <= 0 or spread <= 0:
            return {'direction': 0}

        # 计算点差（bps）
        spread_bps = (spread / mid) * 10000

        # 点差必须大于最小阈值
        if spread_bps < self.min_spread_ticks:
            return {'direction': 0}

        # 获取近期价格范围（简化版，实际应该维护滑动窗口）
        # 这里假设tick中包含历史信息
        recent_high = tick.get('recent_high', ask)
        recent_low = tick.get('recent_low', bid)

        if recent_high <= recent_low:
            return {'direction': 0}

        # 计算价格在近期区间的位置
        position_in_range = (mid - recent_low) / (recent_high - recent_low)

        # 核心逻辑（修复）：跟随趋势
        # 价格高位 -> 趋势向上 -> 买点差
        # 价格低位 -> 趋势向下 -> 卖点差
        if position_in_range > 0.7:
            # 价格在高位，趋势向上，买点差
            return {
                'side': 'buy',
                'direction': 1,  # 兼容ForceFillThreeMode
                'price': bid + self.min_spread_ticks * self.tick_size,
                'quantity': self.max_position * self.cash / mid,
                'reason': 'uptrend',
                'position_in_range': position_in_range,
                'spread_bps': spread_bps
            }

        elif position_in_range < 0.3:
            # 价格在低位，趋势向下，卖点差
            return {
                'side': 'sell',
                'direction': -1,  # 兼容ForceFillThreeMode
                'price': ask - self.min_spread_ticks * self.tick_size,
                'quantity': self.max_position * self.cash / mid,
                'reason': 'downtrend',
                'position_in_range': position_in_range,
                'spread_bps': spread_bps
            }

        return {'direction': 0}

    def process_tick(self, orderbook: Dict) -> Optional[Dict]:
        """处理市场数据tick"""
        # 转换为Series格式
        tick = pd.Series({
            'bid_price': orderbook.get('bid_price', 0),
            'ask_price': orderbook.get('ask_price', 0),
            'mid_price': orderbook.get('mid_price', 0),
            'recent_high': orderbook.get('high', orderbook.get('ask_price', 0)),
            'recent_low': orderbook.get('low', orderbook.get('bid_price', 0))
        })

        return self.generate_signal(tick)


class MVPTraderContrarian:
    """
    MVP策略 - 逆向版本（原逻辑）

    保留原逻辑用于对比测试
    """

    def __init__(self, symbol: str = 'BTCUSDT',
                 initial_capital: float = 10000.0,
                 max_position: float = 0.1,
                 min_spread_ticks: int = 2,
                 tick_size: float = 0.01):
        self.symbol = symbol
        self.initial_capital = initial_capital
        self.max_position = max_position
        self.min_spread_ticks = min_spread_ticks
        self.tick_size = tick_size

    def generate_signal(self, tick: pd.Series) -> Dict:
        """生成逆向信号（原逻辑）"""
        bid = tick.get('bid_price', tick.get('low', tick.get('close', 0)))
        ask = tick.get('ask_price', tick.get('high', tick.get('close', 0)))
        mid = tick.get('mid_price', (bid + ask) / 2)
        spread = ask - bid

        if mid <= 0 or spread <= 0:
            return {'direction': 0}

        spread_bps = (spread / mid) * 10000

        if spread_bps < self.min_spread_ticks:
            return {'direction': 0}

        recent_high = tick.get('recent_high', ask)
        recent_low = tick.get('recent_low', bid)

        if recent_high <= recent_low:
            return {'direction': 0}

        position_in_range = (mid - recent_low) / (recent_high - recent_low)

        # 逆向逻辑（原逻辑）
        if position_in_range < 0.3:
            # 低位买入（抄底）
            return {
                'side': 'buy',
                'direction': 1,  # 兼容ForceFillThreeMode
                'price': bid + self.min_spread_ticks * self.tick_size,
                'quantity': self.max_position * self.initial_capital / mid,
                'reason': 'mean_reversion_long',
                'position_in_range': position_in_range,
                'spread_bps': spread_bps
            }

        elif position_in_range > 0.7:
            # 高位卖出（逃顶）
            return {
                'side': 'sell',
                'direction': -1,  # 兼容ForceFillThreeMode
                'price': ask - self.min_spread_ticks * self.tick_size,
                'quantity': self.max_position * self.initial_capital / mid,
                'reason': 'mean_reversion_short',
                'position_in_range': position_in_range,
                'spread_bps': spread_bps
            }

        return {'direction': 0}


if __name__ == "__main__":
    print("=" * 70)
    print("MVP Strategy - Fixed Version")
    print("=" * 70)

    from data_fetcher import BinanceDataFetcher
    from forcefill_three_mode import ForceFillThreeMode

    # 加载数据
    fetcher = BinanceDataFetcher()
    df = fetcher.fetch_klines('BTCUSDT', '1h', limit=500)
    tick_df = fetcher.convert_to_tick_format(df)

    # 添加高低价信息
    tick_df['recent_high'] = tick_df['ask_price'].rolling(20, min_periods=1).max()
    tick_df['recent_low'] = tick_df['bid_price'].rolling(20, min_periods=1).min()

    print(f"\nLoaded {len(tick_df)} ticks")

    # 测试修复版策略
    print("\n" + "=" * 70)
    print("Testing FIXED strategy (trend following)")
    print("=" * 70)

    strategy_fixed = MVPTraderFixed(
        symbol='BTCUSDT',
        initial_capital=1000.0,
        max_position=0.5,
        min_spread_ticks=2,
        tick_size=0.01
    )

    tester_fixed = ForceFillThreeMode(strategy_fixed, tick_df, initial_capital=1000.0)
    results_fixed = tester_fixed.run_all_modes(verbose=True)

    # 测试逆向版策略（原逻辑）
    print("\n" + "=" * 70)
    print("Testing CONTRARIAN strategy (original mean reversion)")
    print("=" * 70)

    strategy_contrarian = MVPTraderContrarian(
        symbol='BTCUSDT',
        initial_capital=1000.0,
        max_position=0.5,
        min_spread_ticks=2,
        tick_size=0.01
    )

    tester_contrarian = ForceFillThreeMode(strategy_contrarian, tick_df, initial_capital=1000.0)
    results_contrarian = tester_contrarian.run_all_modes(verbose=True)

    # 对比结果
    print("\n" + "=" * 70)
    print("COMPARISON")
    print("=" * 70)

    print("\nFixed (Trend Following):")
    print(f"  Alpha-only Sharpe: {results_fixed['alpha_only']['sharpe']:.2f}")
    print(f"  Full system Sharpe: {results_fixed['full_system']['sharpe']:.2f}")

    print("\nContrarian (Mean Reversion - Original):")
    print(f"  Alpha-only Sharpe: {results_contrarian['alpha_only']['sharpe']:.2f}")
    print(f"  Full system Sharpe: {results_contrarian['full_system']['sharpe']:.2f}")

    print("\n" + "=" * 70)
