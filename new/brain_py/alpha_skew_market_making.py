"""
Alpha-Skew Market Making MVP
将弱趋势Alpha转化为做市报价偏移
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class SkewMarketMaker:
    """
    Alpha-Skew做市策略

    reservation_price = mid_price + alpha_signal * k
    bid = reservation_price - spread/2
    ask = reservation_price + spread/2
    """

    symbol: str = 'BTCUSDT'
    initial_capital: float = 10000.0
    base_spread_bps: float = 2.0  # 基础点差
    skew_coefficient: float = 0.5  # alpha对报价的偏移系数
    inventory_limit: float = 0.1  # 最大持仓限制

    def __post_init__(self):
        self.price_history = []
        self.position = 0.0
        self.cash = self.initial_capital
        self.trades = []

    def calculate_alpha_signal(self, orderbook: Dict) -> float:
        """
        计算Alpha信号（趋势跟踪版本）

        Returns:
            float: -1到1之间的信号，正值表示看涨，负值表示看跌
        """
        mid = orderbook.get('mid_price', 0)

        if mid <= 0:
            return 0.0

        # 更新价格历史
        self.price_history.append(mid)
        if len(self.price_history) > 20:
            self.price_history.pop(0)

        # 需要足够的历史数据
        if len(self.price_history) < 5:
            return 0.0

        # 计算趋势位置
        recent_high = max(self.price_history)
        recent_low = min(self.price_history)

        if recent_high <= recent_low:
            return 0.0

        position_in_range = (mid - recent_low) / (recent_high - recent_low)

        # 转换为-1到1的信号
        # 高位 -> 看涨信号 (正)
        # 低位 -> 看跌信号 (负)
        if position_in_range > 0.7:
            return (position_in_range - 0.5) * 2  # 0.4 to 1.0
        elif position_in_range < 0.3:
            return (position_in_range - 0.5) * 2  # -1.0 to -0.4
        else:
            return (position_in_range - 0.5) * 2  # -0.4 to 0.4

    def calculate_reservation_price(self, mid: float, alpha: float, inventory: float) -> float:
        """
        计算预留价格

        公式: reservation = mid + alpha * k - inventory * gamma

        Args:
            mid: 中间价
            alpha: alpha信号 (-1到1)
            inventory: 当前持仓 (正=多头，负=空头)

        Returns:
            float: 预留价格
        """
        # Alpha skew: 信号强时向有利方向偏移报价
        alpha_skew = alpha * self.skew_coefficient * mid * 0.001  # 0.1% base impact

        # Inventory skew: 持仓过大时反向偏移，促进平仓
        inventory_skew = -inventory * 0.0005 * mid  # 持仓影响

        return mid + alpha_skew + inventory_skew

    def generate_quotes(self, orderbook: Dict) -> Optional[Dict]:
        """
        生成做市报价

        Returns:
            Dict with 'bid' and 'ask' prices, or None
        """
        mid = orderbook.get('mid_price', 0)

        if mid <= 0:
            return None

        # 计算alpha信号
        alpha = self.calculate_alpha_signal(orderbook)

        # 计算预留价格
        reservation = self.calculate_reservation_price(mid, alpha, self.position)

        # 计算点差
        spread = mid * self.base_spread_bps / 10000

        # 生成报价
        bid_price = reservation - spread / 2
        ask_price = reservation + spread / 2

        # 确保报价合理
        bid_price = min(bid_price, mid * 0.999)  # 不超过mid
        ask_price = max(ask_price, mid * 1.001)  # 不低于mid

        # 持仓限制检查
        max_buy = self.inventory_limit - self.position if self.position >= 0 else self.inventory_limit
        max_sell = self.inventory_limit + self.position if self.position <= 0 else self.inventory_limit

        return {
            'bid': bid_price,
            'ask': ask_price,
            'bid_size': max_buy,
            'ask_size': max_sell,
            'alpha': alpha,
            'reservation': reservation,
            'spread': spread
        }

    def process_fill(self, side: str, price: float, size: float):
        """处理成交"""
        if side == 'buy':
            self.position += size
            self.cash -= price * size
        else:
            self.position -= size
            self.cash += price * size

        self.trades.append({
            'side': side,
            'price': price,
            'size': size,
            'position_after': self.position
        })

    def get_inventory_value(self, current_price: float) -> float:
        """计算持仓市值"""
        return self.cash + self.position * current_price


def run_alpha_skew_backtest(data: pd.DataFrame,
                            skew_coeff: float = 0.5,
                            verbose: bool = True) -> Dict:
    """
    运行Alpha-Skew做市回测

    Args:
        data: 市场数据
        skew_coeff: skew系数
        verbose: 是否打印详细信息

    Returns:
        Dict: 回测结果
    """
    if verbose:
        print("=" * 70)
        print(f"Alpha-Skew Market Making Backtest (skew={skew_coeff})")
        print("=" * 70)

    maker = SkewMarketMaker(skew_coefficient=skew_coeff)

    pnl_history = []
    inventory_history = []
    mid_prices = []

    for i in range(len(data)):
        tick = data.iloc[i]

        # 构建orderbook
        bid = tick.get('bid_price', tick.get('low', 0))
        ask = tick.get('ask_price', tick.get('high', 0))
        mid = (bid + ask) / 2

        if mid <= 0:
            continue

        orderbook = {
            'bid_price': bid,
            'ask_price': ask,
            'mid_price': mid
        }

        # 生成报价
        quotes = maker.generate_quotes(orderbook)

        if quotes:
            # 模拟成交（简化版）
            # 如果bid > next_bid，买单成交
            # 如果ask < next_ask，卖单成交

            if i + 1 < len(data):
                next_tick = data.iloc[i + 1]
                next_bid = next_tick.get('bid_price', next_tick.get('low', 0))
                next_ask = next_tick.get('ask_price', next_tick.get('high', 0))

                # Bid成交条件：我们的买价高于市场的买一
                if quotes['bid'] >= next_bid and quotes['bid_size'] > 0:
                    # 模拟成交概率
                    if np.random.rand() < 0.3:  # 30%成交概率
                        maker.process_fill('buy', quotes['bid'],
                                         min(quotes['bid_size'], 0.01))

                # Ask成交条件：我们的卖价低于市场的卖一
                if quotes['ask'] <= next_ask and quotes['ask_size'] > 0:
                    if np.random.rand() < 0.3:
                        maker.process_fill('sell', quotes['ask'],
                                         min(quotes['ask_size'], 0.01))

        # 记录状态
        current_value = maker.get_inventory_value(mid)
        pnl_history.append(current_value - maker.initial_capital)
        inventory_history.append(maker.position)
        mid_prices.append(mid)

    # 计算指标
    final_value = maker.get_inventory_value(mid_prices[-1])
    total_pnl = final_value - maker.initial_capital

    # 夏普比率（简化版）
    if len(pnl_history) > 1:
        pnl_changes = np.diff(pnl_history)
        if np.std(pnl_changes) > 0:
            sharpe = np.mean(pnl_changes) / np.std(pnl_changes) * np.sqrt(252 * 24)  # 小时级年化
        else:
            sharpe = 0
    else:
        sharpe = 0

    # 持仓时间
    inventory_std = np.std(inventory_history)

    if verbose:
        print(f"\nFinal PnL: ${total_pnl:.2f}")
        print(f"Sharpe: {sharpe:.2f}")
        print(f"Total trades: {len(maker.trades)}")
        print(f"Final position: {maker.position:.4f}")
        print(f"Inventory std: {inventory_std:.4f}")

    return {
        'sharpe': sharpe,
        'total_pnl': total_pnl,
        'trades': len(maker.trades),
        'final_position': maker.position,
        'inventory_std': inventory_std,
        'skew_coeff': skew_coeff,
        'pnl_history': pnl_history
    }


def test_skew_sensitivity(data: pd.DataFrame):
    """测试不同skew系数的效果"""
    print("\n" + "=" * 70)
    print("Alpha-Skew Sensitivity Test")
    print("=" * 70)

    skew_values = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0]
    results = []

    for skew in skew_values:
        result = run_alpha_skew_backtest(data, skew_coeff=skew, verbose=False)
        results.append(result)

        print(f"Skew={skew:.2f}: Sharpe={result['sharpe']:.2f}, "
              f"PnL=${result['total_pnl']:.2f}, Trades={result['trades']}")

    # 找出最佳
    best = max(results, key=lambda x: x['sharpe'])
    print(f"\nBest skew coefficient: {best['skew_coeff']:.2f}")
    print(f"Best Sharpe: {best['sharpe']:.2f}")

    return results, best


def verify_alpha_for_skew(data: pd.DataFrame):
    """
    验证alpha是否适合用于skew

    分组测试：强信号组应该有更好的未来收益
    """
    print("\n" + "=" * 70)
    print("Verifying Alpha Suitability for Skew")
    print("=" * 70)

    maker = SkewMarketMaker()
    signals = []
    future_returns = []

    for i in range(len(data) - 5):  # 预留5个周期
        tick = data.iloc[i]
        future_tick = data.iloc[i + 5]  # 5周期后的价格

        bid = tick.get('bid_price', tick.get('low', 0))
        ask = tick.get('ask_price', tick.get('high', 0))
        mid = (bid + ask) / 2

        future_mid = (future_tick.get('bid_price', 0) + future_tick.get('ask_price', 0)) / 2

        if mid <= 0 or future_mid <= 0:
            continue

        orderbook = {'bid_price': bid, 'ask_price': ask, 'mid_price': mid}

        # 计算alpha信号
        alpha = maker.calculate_alpha_signal(orderbook)
        future_return = (future_mid - mid) / mid

        signals.append(alpha)
        future_returns.append(future_return)

    if len(signals) < 50:
        print("Insufficient data")
        return None

    # 分组统计
    signals = np.array(signals)
    future_returns = np.array(future_returns)

    # 分为5组
    percentiles = np.percentile(signals, [20, 40, 60, 80])

    groups = [
        ('Strong Short', signals < percentiles[0]),
        ('Weak Short', (signals >= percentiles[0]) & (signals < percentiles[1])),
        ('Neutral', (signals >= percentiles[1]) & (signals < percentiles[2])),
        ('Weak Long', (signals >= percentiles[2]) & (signals < percentiles[3])),
        ('Strong Long', signals >= percentiles[3])
    ]

    print("\nFuture returns by signal group:")
    print(f"{'Group':<15} {'Count':<8} {'Avg Return':<12} {'Win Rate':<10}")
    print("-" * 50)

    for name, mask in groups:
        group_returns = future_returns[mask]
        if len(group_returns) > 0:
            avg_return = np.mean(group_returns)
            win_rate = np.mean(group_returns > 0)
            print(f"{name:<15} {sum(mask):<8} {avg_return:>11.4f} {win_rate:>9.1%}")

    # 检查单调性
    long_returns = future_returns[signals > percentiles[3]]
    short_returns = future_returns[signals < percentiles[0]]

    if len(long_returns) > 10 and len(short_returns) > 10:
        long_avg = np.mean(long_returns)
        short_avg = np.mean(short_returns)

        if long_avg > short_avg:
            print(f"\n[OK] Alpha shows correct directionality")
            print(f"  Long signal avg return: {long_avg:.4f}")
            print(f"  Short signal avg return: {short_avg:.4f}")
            return True
        else:
            print(f"\n[WARNING] Alpha directionality unclear")
            return False

    return None


if __name__ == "__main__":
    print("=" * 70)
    print("Alpha-Skew Market Making Strategy")
    print("=" * 70)

    # 加载数据
    from data_fetcher import BinanceDataFetcher

    fetcher = BinanceDataFetcher()
    df = fetcher.fetch_klines('BTCUSDT', '1h', limit=1000)
    tick_df = fetcher.convert_to_tick_format(df)

    print(f"\nLoaded {len(tick_df)} ticks")

    # Step 1: 验证alpha是否适合skew
    suitable = verify_alpha_for_skew(tick_df)

    if suitable:
        # Step 2: 测试不同skew系数
        results, best = test_skew_sensitivity(tick_df)

        # Step 3: 详细回测最佳参数
        print("\n" + "=" * 70)
        print(f"Detailed Backtest with Best Skew ({best['skew_coeff']})")
        print("=" * 70)
        final_result = run_alpha_skew_backtest(tick_df,
                                              skew_coeff=best['skew_coeff'],
                                              verbose=True)
    else:
        print("\nAlpha not suitable for skew approach. Recommend pure market making.")
