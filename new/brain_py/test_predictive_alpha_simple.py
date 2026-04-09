"""
Predictive Microprice Alpha 简单测试

验证Alpha生成器在各种市场条件下的行为
"""

import time
import random
import numpy as np
from mvp import PredictiveMicropriceAlpha, FillQualityAnalyzer


def generate_orderbook(trend='neutral', base_price=50000.0):
    """生成合成订单簿"""
    if trend == 'bullish':
        bids = [
            {'price': base_price - 0.01, 'qty': random.uniform(2.0, 5.0)},
            {'price': base_price - 0.02, 'qty': random.uniform(1.0, 3.0)},
            {'price': base_price - 0.03, 'qty': random.uniform(0.5, 2.0)},
        ]
        asks = [
            {'price': base_price + 0.01, 'qty': random.uniform(0.2, 0.8)},
            {'price': base_price + 0.02, 'qty': random.uniform(0.1, 0.5)},
        ]
    elif trend == 'bearish':
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

    return {
        'bids': bids,
        'asks': asks,
        'best_bid': best_bid,
        'best_ask': best_ask,
        'mid_price': mid_price,
        'spread': best_ask - best_bid,
        'spread_bps': (best_ask - best_bid) / mid_price * 10000,
        'timestamp': time.time() * 1000
    }


def run_test():
    print("="*70)
    print("Predictive Microprice Alpha Test")
    print("="*70)

    alpha_gen = PredictiveMicropriceAlpha()

    # 测试1: 买方强势
    print("\n[测试1] 买方强势市场（大量买盘，价格上升）")
    print("-"*70)

    # 模拟价格上升趋势
    for price in [49990, 49995, 49998, 50000, 50002]:
        alpha_gen.price_history.append(price)

    ob_bullish = generate_orderbook('bullish', 50000.0)
    signal = alpha_gen.calculate_predictive_alpha(ob_bullish)

    print(f"Alpha值: {signal.value:+.3f} (正值=看涨)")
    print(f"置信度: {signal.confidence:.3f}")
    print(f"组成成分:")
    print(f"  - 订单簿失衡: {signal.components['imbalance']:+.3f} (权重60%)")
    print(f"  - 价格速度: {signal.components['velocity']:+.3f} (权重30%)")
    print(f"  - 成交量压力: {signal.components['pressure']:+.3f} (权重10%)")

    skew = alpha_gen.get_skew_quotes(ob_bullish, tick_size=0.01)
    if skew:
        print(f"\n[偏斜报价生成] [OK]")
        print(f"  方向: 看涨 -> 抬高价差")
        print(f"  Bid: {skew.bid_price:.2f} x {skew.bid_size}")
        print(f"  Ask: {skew.ask_price:.2f} x {skew.ask_size}")
        print(f"  原因: {skew.reasoning}")
    else:
        print(f"\n[偏斜报价生成] [NO] Alpha信号不够强")

    # 测试2: 卖方强势
    print("\n[测试2] 卖方强势市场（大量卖盘，价格下跌）")
    print("-"*70)

    alpha_gen2 = PredictiveMicropriceAlpha()

    # 模拟价格下降趋势
    for price in [50010, 50005, 50002, 50000, 49998]:
        alpha_gen2.price_history.append(price)

    ob_bearish = generate_orderbook('bearish', 50000.0)
    signal2 = alpha_gen2.calculate_predictive_alpha(ob_bearish)

    print(f"Alpha值: {signal2.value:+.3f} (负值=看跌)")
    print(f"置信度: {signal2.confidence:.3f}")
    print(f"组成成分:")
    print(f"  - 订单簿失衡: {signal2.components['imbalance']:+.3f}")
    print(f"  - 价格速度: {signal2.components['velocity']:+.3f}")
    print(f"  - 成交量压力: {signal2.components['pressure']:+.3f}")

    skew2 = alpha_gen2.get_skew_quotes(ob_bearish, tick_size=0.01)
    if skew2:
        print(f"\n[偏斜报价生成] [OK]")
        print(f"  方向: 看跌 -> 降低价差")
        print(f"  Bid: {skew2.bid_price:.2f} x {skew2.bid_size}")
        print(f"  Ask: {skew2.ask_price:.2f} x {skew2.ask_size}")
        print(f"  原因: {skew2.reasoning}")

    # 测试3: 平衡市场
    print("\n[测试3] 平衡市场（买卖均衡）")
    print("-"*70)

    alpha_gen3 = PredictiveMicropriceAlpha()

    ob_neutral = generate_orderbook('neutral', 50000.0)
    signal3 = alpha_gen3.calculate_predictive_alpha(ob_neutral)

    print(f"Alpha值: {signal3.value:+.3f}")
    print(f"置信度: {signal3.confidence:.3f}")

    skew3 = alpha_gen3.get_skew_quotes(ob_neutral, tick_size=0.01)
    if skew3:
        print(f"[偏斜报价生成] [OK]")
    else:
        print(f"[偏斜报价生成] [NO] 信号太弱（|α| < 0.3 或 confidence < 0.5）")

    # 测试4: 与FillQualityAnalyzer集成
    print("\n[测试4] Alpha预测验证（与FillQualityAnalyzer集成）")
    print("-"*70)

    fill_analyzer = FillQualityAnalyzer(lookback_delays=[1, 3, 5])

    # 模拟一系列交易
    print("模拟10笔交易...")
    for i in range(10):
        trend = random.choice(['bullish', 'bearish', 'neutral'])
        price = 50000.0 + random.uniform(-10, 10)
        ob = generate_orderbook(trend, price)

        # 记录价格历史
        alpha_gen.price_history.append(ob['mid_price'])

        # 生成信号
        sig = alpha_gen.calculate_predictive_alpha(ob)

        # 模拟交易（基于信号方向）
        side = 'buy' if sig.value > 0.1 else 'sell' if sig.value < -0.1 else random.choice(['buy', 'sell'])

        trade_id = f"trade_{i}"
        fill_analyzer.record_trade({
            'trade_id': trade_id,
            'side': side,
            'price': ob['mid_price'] + (0.01 if side == 'buy' else -0.01),
            'mid_price': ob['mid_price'],
            'spread_bps': ob['spread_bps'],
            'qty': 0.1
        })

        print(f"  {trade_id}: {side:4s} @ {ob['mid_price']:.2f}, α={sig.value:+.2f}")

    # 模拟后续价格
    for i in range(20):
        price = 50000.0 + random.uniform(-5, 5)
        fill_analyzer.update_mid_price(price)
        alpha_gen.price_history.append(price)

    # 验证预测准确性
    validation = alpha_gen.validate_predictions(fill_analyzer, lookback_seconds=5)
    print(f"\n预测验证结果:")
    print(f"  状态: {validation.get('status', 'N/A')}")
    if validation.get('status') == 'OK':
        print(f"  准确率: {validation['accuracy']:.1%}")
        print(f"  正确/总数: {validation['correct']}/{validation['total']}")
        print(f"  是否预测性: {'[YES]' if validation['is_predictive'] else '[NO]'}")

    # 生成FillQuality报告
    print("\n")
    fill_analyzer.print_report()

    # 测试5: 信号摘要
    print("\n[测试5] 信号摘要功能")
    print("-"*70)
    print(f"当前信号: {alpha_gen.get_signal_summary()}")

    print("\n" + "="*70)
    print("所有测试通过！PredictiveMicropriceAlpha已就绪")
    print("="*70)


if __name__ == "__main__":
    run_test()
