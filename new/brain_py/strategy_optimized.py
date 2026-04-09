"""
优化后的策略 - 解决Alpha质量问题

优化内容：
1. 改进Microprice算法（使用加权深度）
2. 添加动量Alpha源
3. 添加反转Alpha源
4. 实现动态权重调整
5. 添加止损机制
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
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
    stop_loss: float


@dataclass
class ExecutionResult:
    """执行结果"""
    signal_id: str
    filled: bool
    price: float
    slippage: float
    execution_timestamp: float


class AdvancedAlphaImprover:
    """
    高级Alpha质量提升器

    包含多个Alpha源：
    1. Microprice (改进版)
    2. Order Flow Imbalance
    3. Price Momentum
    4. Mean Reversion
    """

    def __init__(self):
        self.predictive_alpha = PredictiveMicropriceAlpha()
        self.price_history = deque(maxlen=50)
        self.return_history = deque(maxlen=20)

        # Alpha源权重（动态调整）
        self.weights = {
            'microprice': 1.0,
            'ofi': 0.8,
            'momentum': 0.6,
            'reversion': 0.4
        }

        # 性能跟踪
        self.performance = {
            'microprice': {'correct': 0, 'total': 0},
            'ofi': {'correct': 0, 'total': 0},
            'momentum': {'correct': 0, 'total': 0},
            'reversion': {'correct': 0, 'total': 0}
        }

    def calculate_microprice_improved(self, orderbook: Dict) -> float:
        """
        改进的Microprice计算
        考虑多档深度加权
        """
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if not bids or not asks:
            return 0.0

        # 构建更丰富的订单簿
        if len(bids) == 1 and 'best_bid' in orderbook:
            # 从best_bid/best_ask扩展
            base_bid = orderbook['best_bid']
            base_ask = orderbook['best_ask']
            spread = base_ask - base_bid

            bids = [
                {'price': base_bid, 'qty': 1.0},
                {'price': base_bid - spread * 0.5, 'qty': 2.0},
                {'price': base_bid - spread, 'qty': 3.0}
            ]
            asks = [
                {'price': base_ask, 'qty': 1.0},
                {'price': base_ask + spread * 0.5, 'qty': 2.0},
                {'price': base_ask + spread, 'qty': 3.0}
            ]

            orderbook = {**orderbook, 'bids': bids, 'asks': asks}

        # 计算加权mid
        bid_sum = sum(b['price'] * b['qty'] / (i+1) for i, b in enumerate(bids[:5]))
        ask_sum = sum(a['price'] * a['qty'] / (i+1) for i, a in enumerate(asks[:5]))
        bid_weight = sum(b['qty'] / (i+1) for i, b in enumerate(bids[:5]))
        ask_weight = sum(a['qty'] / (i+1) for i, a in enumerate(asks[:5]))

        if bid_weight == 0 or ask_weight == 0:
            return 0.0

        weighted_bid = bid_sum / bid_weight
        weighted_ask = ask_sum / ask_weight

        # 微价格偏向
        imbalance = (bid_weight - ask_weight) / (bid_weight + ask_weight)
        microprice = (weighted_bid + weighted_ask) / 2 + (weighted_ask - weighted_bid) * imbalance * 0.5

        mid = (bids[0]['price'] + asks[0]['price']) / 2
        return (microprice - mid) / mid * 100  # 转换为百分比

    def calculate_ofi(self, orderbook: Dict) -> float:
        """订单流不平衡"""
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if not bids or not asks:
            return 0.0

        bid_vol = sum(b.get('qty', 0) for b in bids[:3])
        ask_vol = sum(a.get('qty', 0) for a in asks[:3])

        total = bid_vol + ask_vol
        if total == 0:
            return 0.0

        return (bid_vol - ask_vol) / total

    def calculate_momentum(self, orderbook: Dict) -> float:
        """价格动量"""
        mid = orderbook.get('mid_price', 0)
        if mid <= 0 or len(self.price_history) < 5:
            return 0.0

        # 短期趋势
        recent_prices = list(self.price_history)[-5:]
        if len(recent_prices) < 2:
            return 0.0

        returns = [(recent_prices[i] - recent_prices[i-1]) / recent_prices[i-1]
                   for i in range(1, len(recent_prices))]

        avg_return = np.mean(returns)

        # 更新返回历史
        self.return_history.append(avg_return)

        # 动量信号：正返回=看涨
        return np.sign(avg_return) * min(abs(avg_return) * 1000, 1.0)

    def calculate_reversion(self, orderbook: Dict) -> float:
        """均值回归"""
        mid = orderbook.get('mid_price', 0)
        if mid <= 0 or len(self.price_history) < 20:
            return 0.0

        prices = list(self.price_history)
        ma20 = np.mean(prices[-20:])
        std20 = np.std(prices[-20:])

        if std20 == 0:
            return 0.0

        # Z-score
        zscore = (mid - ma20) / std20

        # 极端值时回归
        if abs(zscore) > 1.5:
            return -np.sign(zscore) * min(abs(zscore) / 3, 1.0)

        return 0.0

    def update_price_history(self, mid_price: float):
        """更新价格历史"""
        self.price_history.append(mid_price)
        for price in self.price_history:
            self.predictive_alpha.price_history.append(price)

    def calculate_ensemble_alpha(self, orderbook: Dict) -> float:
        """计算集成Alpha"""
        mid = orderbook.get('mid_price', 0)
        if mid > 0:
            self.update_price_history(mid)

        # 计算各Alpha源
        alphas = {
            'microprice': self.calculate_microprice_improved(orderbook),
            'ofi': self.calculate_ofi(orderbook),
            'momentum': self.calculate_momentum(orderbook),
            'reversion': self.calculate_reversion(orderbook)
        }

        # 加权集成
        total_weight = sum(self.weights.values())
        ensemble = sum(alphas[k] * self.weights[k] for k in alphas) / total_weight

        return ensemble

    def update_weights(self, source: str, was_correct: bool):
        """根据表现更新权重"""
        if was_correct:
            self.weights[source] = min(self.weights[source] * 1.01, 2.0)
        else:
            self.weights[source] = max(self.weights[source] * 0.99, 0.1)


class OptimizedStrategy:
    """
    优化后的策略

    改进：
    1. 多个Alpha源集成
    2. 动态权重调整
    3. 止损机制
    4. 仓位管理
    """

    def __init__(self,
                 symbol: str = 'BTCUSDT',
                 use_adaptive: bool = True,
                 stop_loss_pct: float = 0.01,
                 max_position: float = 0.5):

        self.symbol = symbol
        self.use_adaptive = use_adaptive
        self.stop_loss_pct = stop_loss_pct
        self.max_position = max_position

        # Alpha生成器
        self.alpha_improver = AdvancedAlphaImprover()

        # 阈值门控
        self.threshold = 0.05
        self.signal_history = deque(maxlen=100)

        # 状态
        self.position = 0.0
        self.cash = 1000.0
        self.entry_price = 0.0
        self.signal_counter = 0

        # 统计
        self.trades = []
        self.total_pnl = 0.0

    def generate_signal(self, orderbook: Dict) -> Optional[SignalRecord]:
        """生成信号"""
        # 计算集成Alpha
        alpha_value = self.alpha_improver.calculate_ensemble_alpha(orderbook)

        # 记录信号历史用于自适应阈值
        if abs(alpha_value) > 0.01:
            self.signal_history.append(abs(alpha_value))

        # 自适应阈值
        if len(self.signal_history) >= 20:
            self.threshold = np.percentile(list(self.signal_history), 75)
            self.threshold = np.clip(self.threshold, 0.03, 0.15)

        # 信号过滤
        if abs(alpha_value) < self.threshold:
            return None

        # 止损检查
        stop_loss = self._calculate_stop_loss(orderbook)

        # 创建信号
        self.signal_counter += 1
        return SignalRecord(
            signal_id=f"sig_{self.signal_counter}_{int(time.time()*1000)}",
            timestamp=time.time(),
            alpha_value=alpha_value,
            expected_return=alpha_value * 0.001,
            size=0.1,
            direction=1 if alpha_value > 0 else -1,
            threshold_used=self.threshold,
            stop_loss=stop_loss
        )

    def _calculate_stop_loss(self, orderbook: Dict) -> float:
        """计算止损价"""
        mid = orderbook.get('mid_price', 0)
        if mid <= 0:
            return 0

        # 基于ATR的止损（简化版使用固定百分比）
        return mid * self.stop_loss_pct

    def check_stop_loss(self, current_price: float) -> bool:
        """检查是否触发止损"""
        if self.position == 0 or self.entry_price == 0:
            return False

        if self.position > 0:  # 多头
            loss = (self.entry_price - current_price) / self.entry_price
        else:  # 空头
            loss = (current_price - self.entry_price) / self.entry_price

        return loss > self.stop_loss_pct

    def process_tick(self, orderbook: Dict, next_mid_price: float = None) -> Optional[Dict]:
        """处理一个tick"""
        mid = orderbook.get('mid_price', 0)

        # 1. 检查止损
        if self.check_stop_loss(mid):
            # 平仓
            if self.position != 0:
                exit_price = mid
                if self.position > 0:
                    pnl = (exit_price - self.entry_price) * abs(self.position)
                else:
                    pnl = (self.entry_price - exit_price) * abs(self.position)

                self.cash += exit_price * abs(self.position)
                self.total_pnl += pnl

                trade = {
                    'type': 'stop_loss',
                    'pnl': pnl,
                    'exit_price': exit_price,
                    'position': self.position
                }
                self.trades.append(trade)

                self.position = 0
                self.entry_price = 0

                return trade

        # 2. 生成新信号
        signal = self.generate_signal(orderbook)

        if signal is None:
            return None

        # 3. 执行信号（无偏执行）
        mid = orderbook.get('mid_price', 0)
        slippage = mid * 0.0005  # 5 bps

        if signal.direction > 0:  # 买入
            fill_price = orderbook.get('best_ask', mid) + slippage

            # 如果已有空头，先平仓
            if self.position < 0:
                # 空头平仓：买入回补
                cover_cost = fill_price * abs(self.position)
                short_proceeds = self.entry_price * abs(self.position)
                pnl = short_proceeds - cover_cost
                self.cash -= cover_cost  # 支付买入成本
                self.total_pnl += pnl
                self.trades.append({'type': 'cover_short', 'pnl': pnl})
                self.position = 0
                self.entry_price = 0

            # 开多或加仓
            if self.position >= 0 and self.position < self.max_position:
                new_position = min(0.1, self.max_position - self.position)
                if new_position > 0:
                    cost = fill_price * new_position
                    if self.cash >= cost:  # 确保有足够现金
                        self.position += new_position
                        self.entry_price = fill_price
                        self.cash -= cost

        else:  # 卖出
            fill_price = orderbook.get('best_bid', mid) - slippage

            # 如果已有多头，先平仓
            if self.position > 0:
                proceeds = fill_price * self.position
                cost = self.entry_price * self.position
                pnl = proceeds - cost
                self.cash += proceeds
                self.total_pnl += pnl
                self.trades.append({'type': 'sell_long', 'pnl': pnl})
                self.position = 0
                self.entry_price = 0

            # 开空（卖空）
            if self.position <= 0 and abs(self.position) < self.max_position:
                new_position = min(0.1, self.max_position - abs(self.position))
                if new_position > 0:
                    # 卖空获得现金
                    proceeds = fill_price * new_position
                    self.cash += proceeds
                    self.position -= new_position
                    self.entry_price = fill_price

        return {
            'signal': signal,
            'fill_price': fill_price,
            'position': self.position,
            'cash': self.cash,
            'total_pnl': self.total_pnl
        }

    def get_stats(self) -> Dict:
        """获取统计"""
        winning_trades = [t for t in self.trades if t.get('pnl', 0) > 0]
        losing_trades = [t for t in self.trades if t.get('pnl', 0) <= 0]

        return {
            'total_trades': len(self.trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': len(winning_trades) / len(self.trades) if self.trades else 0,
            'total_pnl': self.total_pnl,
            'final_position': self.position,
            'final_cash': self.cash,
            'alpha_weights': self.alpha_improver.weights
        }


def run_optimized_test():
    """运行优化策略测试"""
    from data_fetcher import BinanceDataFetcher

    print("="*70)
    print("Optimized Strategy Test")
    print("="*70)

    # 加载数据
    fetcher = BinanceDataFetcher()
    df = fetcher.fetch_klines('BTCUSDT', '1h', limit=500)
    tick_df = fetcher.convert_to_tick_format(df)
    tick_df = tick_df.dropna()

    print(f"\nData: {len(tick_df)} ticks")

    # 初始化策略
    strategy = OptimizedStrategy(
        symbol='BTCUSDT',
        use_adaptive=True,
        stop_loss_pct=0.01,  # 1%止损
        max_position=0.5
    )

    # 运行测试
    print("\nRunning optimized strategy...")

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

    # 最终平仓
    if strategy.position != 0:
        final_price = tick_df.iloc[-1].get('mid_price', tick_df.iloc[-1].get('close'))
        if strategy.position > 0:
            pnl = (final_price - strategy.entry_price) * strategy.position
        else:
            pnl = (strategy.entry_price - final_price) * abs(strategy.position)
        strategy.total_pnl += pnl
        strategy.cash += final_price * abs(strategy.position)
        strategy.position = 0

    # 生成报告
    stats = strategy.get_stats()

    print("\n" + "="*70)
    print("RESULTS")
    print("="*70)

    print(f"\n[Trading Statistics]")
    print(f"  Total trades: {stats['total_trades']}")
    print(f"  Winning trades: {stats['winning_trades']}")
    print(f"  Losing trades: {stats['losing_trades']}")
    print(f"  Win rate: {stats['win_rate']:.1%}")

    print(f"\n[PnL]")
    print(f"  Total PnL: ${stats['total_pnl']:.2f}")
    print(f"  Final cash: ${stats['final_cash']:.2f}")

    print(f"\n[Alpha Weights]")
    for source, weight in stats['alpha_weights'].items():
        print(f"  {source}: {weight:.2f}")

    print("\n" + "="*70)

    return stats


if __name__ == "__main__":
    stats = run_optimized_test()
