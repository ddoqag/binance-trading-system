"""
Alpha V2 影子模式 - 本地数据源版本

使用合成数据模拟ETH市场特征，完整测试IC指标和信号质量
"""
import os
import sys
import time
import numpy as np
from datetime import datetime
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from local_trading import LocalTrader, LocalTradingConfig, SyntheticDataSource
from mvp_trader_v2 import MVPTraderV2


def generate_eth_synthetic_data(n_ticks=2000, seed=42):
    """
    生成ETH特征的合成市场数据

    ETH特征：
    - 价格：$2000-2500
    - 点差：1-3 ticks (0.01-0.03)
    - 波动率：中等
    - 添加趋势和均值回归模式
    """
    np.random.seed(seed)

    data = []
    base_price = 2180.0
    trend = 0

    for i in range(n_ticks):
        # 周期性趋势变化（模拟上涨/下跌/震荡）
        if i % 500 == 0:
            trend = np.random.choice([-1, 0, 1], p=[0.3, 0.4, 0.3])

        # ETH特征点差（1-3 ticks）
        spread_ticks = np.random.choice([1, 1, 1, 2, 2, 3], p=[0.5, 0.2, 0.1, 0.1, 0.07, 0.03])
        spread = spread_ticks * 0.01

        # 价格变动（趋势 + 噪声）
        trend_component = trend * 0.02  # 趋势项
        noise = np.random.randn() * 0.1  # 噪声项

        # 订单簿压力（模拟买卖盘不平衡）
        bid_pressure = max(0.5, 1.5 + trend_component * 10 + noise * 0.5)
        ask_pressure = max(0.5, 1.5 - trend_component * 10 - noise * 0.5)

        # 价格更新
        price_change = (trend_component + noise * 0.01) * 0.001
        base_price *= (1 + price_change)

        bid = base_price - spread / 2
        ask = base_price + spread / 2

        data.append({
            'bids': [{'price': bid, 'qty': bid_pressure}],
            'asks': [{'price': ask, 'qty': ask_pressure}],
            'best_bid': bid,
            'best_ask': ask,
            'mid_price': (bid + ask) / 2,
            'spread': spread,
            'spread_bps': spread / ((bid + ask) / 2) * 10000,
            'timestamp': i
        })

    return data


def run_alpha_v2_shadow_local(duration_minutes=20, symbol='ETHUSDT'):
    """
    运行Alpha V2影子模式（本地数据）

    重点关注指标：
    - IC_1s: 1秒信息系数
    - IC_IR: 信息比率
    - Signal Effectiveness: 信号有效性
    - Trade Frequency: 交易频率
    """
    print('='*80)
    print('ALPHA V2 SHADOW MODE - LOCAL DATA')
    print('='*80)
    print(f'Symbol: {symbol}')
    print(f'Mode: SHADOW (Learning)')
    print(f'Duration: {duration_minutes} minutes (simulated)')
    print('='*80)

    # 初始化Alpha V2交易器
    trader = MVPTraderV2(
        symbol=symbol,
        initial_capital=1000.0,
        max_position=0.05,
        tick_size=0.01,
        use_sac=False,
        shadow_mode=True  # 关键：影子模式
    )

    # 设置ETH优化参数
    trader.spread_capture.min_spread_ticks = 1.0
    trader.base_alpha_threshold = 0.0005

    print('[OK] MVPTraderV2 initialized')
    print(f'[INFO] Shadow Mode: True')
    print(f'[INFO] IC Monitor: Active')
    print(f'[INFO] Feature Engine: Active')
    print('='*80)

    # 生成合成数据
    n_ticks = duration_minutes * 60  # 每秒一个tick
    market_data = generate_eth_synthetic_data(n_ticks=n_ticks)

    print(f'\n[DATA] Generated {len(market_data)} synthetic ticks')
    print(f'[DATA] Price range: ${market_data[0]["mid_price"]:.2f} - ${market_data[-1]["mid_price"]:.2f}')
    print('-'*80)

    # 运行交易循环
    tick_count = 0
    price_history = []
    ic_history = deque(maxlen=100)

    print('\n开始影子交易循环...')
    print('-'*80)

    for orderbook in market_data:
        current_price = orderbook['mid_price']
        price_history.append(current_price)

        # 处理tick
        result = trader.process_tick(orderbook)
        tick_count += 1

        # 每10个tick打印仪表盘
        if tick_count % 10 == 0:
            status = trader.get_status()
            ic = status['ic_metrics']

            ic_history.append(ic['ic_1s'])

            # 构建状态行
            line = f"[{tick_count:4d}] "
            line += f"Price: ${current_price:,.2f} | "
            line += f"Trades: {status['trade_count']} | "
            line += f"IC_1s: {ic['ic_1s']:+.3f} | "
            line += f"IC_IR: {ic['ic_ir']:+.2f} | "
            line += f"Signal: {'EFFECTIVE' if ic['signal_effective'] else 'WEAK'}"

            print(line)

    # 打印最终报告
    print('\n\n' + '='*80)
    print('FINAL REPORT - ALPHA V2 SHADOW MODE')
    print('='*80)

    trader.print_report()

    # IC统计
    if ic_history:
        ic_array = np.array(list(ic_history))
        print(f'\n[IC Statistics]')
        print(f'  Mean IC_1s: {np.mean(ic_array):+.4f}')
        print(f'  Std IC_1s: {np.std(ic_array):.4f}')
        print(f'  Positive Rate: {np.mean(ic_array > 0):.1%}')
        print(f'  IC > 0.05 Rate: {np.mean(ic_array > 0.05):.1%}')

    # 价格统计
    if price_history:
        print(f'\n[Price Statistics]')
        print(f'  Start: ${price_history[0]:,.2f}')
        print(f'  End: ${price_history[-1]:,.2f}')
        print(f'  Change: {(price_history[-1]/price_history[0]-1)*100:.3f}%')

    print('\n' + '='*80)
    print('INTERPRETATION GUIDE')
    print('='*80)
    print('IC_1s > 0.05: 信号有效，具备预测能力')
    print('IC_1s ≈ 0: 信号无效，需要重构特征')
    print('IC_1s < 0: 信号反向，检查特征逻辑')
    print('='*80)

    return trader.get_status()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Alpha V2 Shadow Mode (Local Data)')
    parser.add_argument('--minutes', type=int, default=20, help='运行时长（分钟）')
    parser.add_argument('--symbol', type=str, default='ETHUSDT', help='交易对')
    args = parser.parse_args()

    run_alpha_v2_shadow_local(
        duration_minutes=args.minutes,
        symbol=args.symbol
    )
