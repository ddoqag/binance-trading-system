"""
Predictive Microprice Alpha Integration Test

集成测试：验证PredictiveMicropriceAlpha与现有系统的协同工作
"""

import sys
import time
import random
import numpy as np
from datetime import datetime

# 导入MVP模块
from mvp import (
    SpreadCapture,
    ToxicFlowDetector,
    SimpleQueueOptimizer,
    FillQualityAnalyzer,
    PredictiveMicropriceAlpha
)
from mvp_trader import MVPTrader, MVPState


class PredictiveMVPTrader:
    """
    增强版MVPTrader，集成PredictiveMicropriceAlpha
    """

    def __init__(self, symbol='BTCUSDT', initial_capital=1000.0, tick_size=0.01):
        self.symbol = symbol
        self.tick_size = tick_size

        # 基础组件
        self.trader = MVPTrader(
            symbol=symbol,
            initial_capital=initial_capital,
            max_position=0.5,
            tick_size=tick_size
        )

        # Alpha生成器
        self.alpha_gen = PredictiveMicropriceAlpha()

        # 成交质量分析器
        self.fill_analyzer = FillQualityAnalyzer(lookback_delays=[1, 3, 5, 10])

        # 统计
        self.alpha_triggers = 0
        self.skew_quotes_used = 0

    def process_tick(self, orderbook: dict) -> dict:
        """处理一个tick，集成Alpha信号"""

        # 更新Alpha生成器的价格历史
        mid_price = orderbook.get('mid_price', 0)
        if mid_price > 0:
            self.alpha_gen.price_history.append(mid_price)

        # 计算Alpha信号
        alpha_signal = self.alpha_gen.calculate_predictive_alpha(orderbook)

        # 获取非对称报价（如果信号强）
        skew_quote = self.alpha_gen.get_skew_quotes(
            orderbook,
            base_spread_ticks=2,
            tick_size=self.tick_size,
            max_skew_ticks=2
        )

        # 如果Alpha信号强，使用skew quote而不是默认报价
        if skew_quote and abs(alpha_signal.value) > 0.3:
            self.alpha_triggers += 1
            self.skew_quotes_used += 1

            # 根据Alpha方向决定交易方向
            if alpha_signal.value > 0:  # 看涨
                # 尝试买入 (当持仓较小时)
                if self.trader.state.current_position < self.trader.max_position * 0.5:
                    result = self._execute_skewed_buy(skew_quote, orderbook)
                    if result:
                        self._record_trade(result, orderbook)
                        return result
            else:  # 看跌
                # 尝试卖出 (当有持仓时)
                if self.trader.state.current_position > 0:
                    result = self._execute_skewed_sell(skew_quote, orderbook)
                    if result:
                        self._record_trade(result, orderbook)
                        return result

        # Alpha信号不强，使用基础策略
        result = self.trader.process_tick(orderbook)
        if result:
            self._record_trade(result, orderbook)

        return result

    def _execute_skewed_buy(self, skew_quote, orderbook) -> dict:
        """执行偏斜买入"""
        cost = skew_quote.bid_price * skew_quote.bid_size

        if cost > self.trader.cash:
            return None

        self.trader.position += skew_quote.bid_size
        self.trader.cash -= cost
        self.trader.state = MVPState.LONG

        return {
            'id': f'skew_buy_{int(time.time()*1000)}',
            'side': 'buy',
            'price': skew_quote.bid_price,
            'qty': skew_quote.bid_size,
            'alpha_enhanced': True,
            'alpha_value': skew_quote.alpha_value,
            'reasoning': skew_quote.reasoning
        }

    def _execute_skewed_sell(self, skew_quote, orderbook) -> dict:
        """执行偏斜卖出"""
        if self.trader.position < skew_quote.ask_size:
            return None

        proceeds = skew_quote.ask_price * skew_quote.ask_size

        self.trader.position -= skew_quote.ask_size
        self.trader.cash += proceeds

        if self.trader.position <= 0.001:
            self.trader.state = MVPState.NO_POSITION
        else:
            self.trader.state = MVPState.LONG

        return {
            'id': f'skew_sell_{int(time.time()*1000)}',
            'side': 'sell',
            'price': skew_quote.ask_price,
            'qty': skew_quote.ask_size,
            'alpha_enhanced': True,
            'alpha_value': skew_quote.alpha_value,
            'reasoning': skew_quote.reasoning
        }

    def _record_trade(self, result: dict, orderbook: dict):
        """记录交易用于质量分析"""
        self.fill_analyzer.record_trade({
            'trade_id': result['id'],
            'side': result['side'],
            'price': result['price'],
            'mid_price': orderbook.get('mid_price', result['price']),
            'spread_bps': orderbook.get('spread_bps', 0),
            'qty': result.get('qty', 0.1)
        })

    def update_fill_prices(self, orderbook: dict):
        """更新后续价格用于分析"""
        mid_price = orderbook.get('mid_price', 0)
        if mid_price > 0:
            self.fill_analyzer.update_mid_price(mid_price)

    def get_status(self) -> dict:
        """获取状态"""
        base_status = self.trader.get_status()
        return {
            **base_status,
            'alpha_triggers': self.alpha_triggers,
            'skew_quotes_used': self.skew_quotes_used,
            'alpha_summary': self.alpha_gen.get_signal_summary()
        }


def generate_synthetic_orderbook(base_price: float, trend: str = 'neutral') -> dict:
    """生成合成订单簿数据"""

    if trend == 'bullish':
        # 买方强势
        bids = [
            {'price': base_price - 0.01, 'qty': random.uniform(2.0, 5.0)},
            {'price': base_price - 0.02, 'qty': random.uniform(1.0, 3.0)},
            {'price': base_price - 0.03, 'qty': random.uniform(0.5, 2.0)},
        ]
        asks = [
            {'price': base_price + 0.01, 'qty': random.uniform(0.2, 0.8)},
            {'price': base_price + 0.02, 'qty': random.uniform(0.1, 0.5)},
            {'price': base_price + 0.03, 'qty': random.uniform(0.1, 0.3)},
        ]
    elif trend == 'bearish':
        # 卖方强势
        bids = [
            {'price': base_price - 0.01, 'qty': random.uniform(0.2, 0.8)},
            {'price': base_price - 0.02, 'qty': random.uniform(0.1, 0.5)},
        ]
        asks = [
            {'price': base_price + 0.01, 'qty': random.uniform(2.0, 5.0)},
            {'price': base_price + 0.02, 'qty': random.uniform(1.0, 3.0)},
            {'price': base_price + 0.03, 'qty': random.uniform(0.5, 2.0)},
        ]
    else:
        # 平衡
        bids = [
            {'price': base_price - 0.01, 'qty': random.uniform(0.5, 1.5)},
            {'price': base_price - 0.02, 'qty': random.uniform(0.3, 1.0)},
        ]
        asks = [
            {'price': base_price + 0.01, 'qty': random.uniform(0.5, 1.5)},
            {'price': base_price + 0.02, 'qty': random.uniform(0.3, 1.0)},
        ]

    best_bid = bids[0]['price']
    best_ask = asks[0]['price']
    mid_price = (best_bid + best_ask) / 2
    spread = best_ask - best_bid
    spread_bps = (spread / mid_price) * 10000

    return {
        'symbol': 'BTCUSDT',
        'bids': bids,
        'asks': asks,
        'best_bid': best_bid,
        'best_ask': best_ask,
        'mid_price': mid_price,
        'spread': spread,
        'spread_bps': spread_bps,
        'timestamp': time.time() * 1000
    }


def run_integration_test():
    """运行集成测试"""
    print("="*70)
    print("Predictive Microprice Alpha Integration Test")
    print("="*70)

    # 初始化增强版Trader
    trader = PredictiveMVPTrader(
        symbol='BTCUSDT',
        initial_capital=1000.0,
        tick_size=0.01
    )

    print("\n[Phase 1] 模拟价格上升趋势（应触发看涨Alpha）")
    print("-"*70)

    base_price = 50000.0
    trades_in_bullish = 0

    for i in range(30):
        # 模拟上升趋势
        price = base_price + i * 2 + random.uniform(-1, 1)
        orderbook = generate_synthetic_orderbook(price, trend='bullish')

        result = trader.process_tick(orderbook)
        trader.update_fill_prices(orderbook)

        if result:
            trades_in_bullish += 1
            alpha_info = "[ALPHA] " if result.get('alpha_enhanced') else ""
            print(f"  Tick {i+1}: {alpha_info}{result['side'].upper()} @ {result['price']:.2f}, "
                  f"α={result.get('alpha_value', 0):+.2f}")

        time.sleep(0.01)

    print(f"\n  Trades in bullish phase: {trades_in_bullish}")
    print(f"  Alpha triggers: {trader.alpha_triggers}")

    print("\n[Phase 2] 模拟价格下降趋势（应触发看跌Alpha）")
    print("-"*70)

    trades_in_bearish = 0

    for i in range(30):
        # 模拟下降趋势
        price = base_price + 60 - i * 2 + random.uniform(-1, 1)
        orderbook = generate_synthetic_orderbook(price, trend='bearish')

        result = trader.process_tick(orderbook)
        trader.update_fill_prices(orderbook)

        if result:
            trades_in_bearish += 1
            alpha_info = "[ALPHA] " if result.get('alpha_enhanced') else ""
            print(f"  Tick {i+1}: {alpha_info}{result['side'].upper()} @ {result['price']:.2f}, "
                  f"α={result.get('alpha_value', 0):+.2f}")

        time.sleep(0.01)

    print(f"\n  Trades in bearish phase: {trades_in_bearish}")

    print("\n[Phase 3] 最终状态报告")
    print("-"*70)

    status = trader.get_status()
    print(f"  Total Alpha Triggers: {status['alpha_triggers']}")
    print(f"  Skew Quotes Used: {status['skew_quotes_used']}")
    print(f"  Current Alpha: {status['alpha_summary']}")
    print(f"  Total PnL: ${status['state']['total_pnl']:.2f}")
    print(f"  Current Position: {status['state']['current_position']:.4f}")

    print("\n[Phase 4] Fill Quality Analysis")
    print("-"*70)

    # 模拟一些后续价格数据
    for i in range(10):
        price = base_price + random.uniform(-5, 5)
        trader.update_fill_prices({'mid_price': price})

    # 生成报告
    trader.fill_analyzer.print_report()

    print("\n" + "="*70)
    print("Integration Test Completed")
    print("="*70)


if __name__ == "__main__":
    run_integration_test()
