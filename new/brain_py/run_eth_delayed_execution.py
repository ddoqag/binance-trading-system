"""
ETH延迟执行策略 - 利用IC_3s信号

核心修改：
1. 信号产生后等待3秒验证
2. 如果3秒后价格按预测方向移动，则确认信号有效
3. 在影子模式下统计"虚拟成交"来估算真实表现
"""
import os
import sys
import time
import numpy as np
from datetime import datetime
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:7897'
os.environ['HTTP_PROXY'] = 'http://127.0.0.1:7897'

from binance.client import Client
from mvp_trader_v2 import MVPTraderV2
from mvp import SpreadCapture


class DelayedExecutionTracker:
    """延迟执行跟踪器 - 在影子模式下验证3秒预测能力"""

    def __init__(self, delay_seconds=3):
        self.delay_seconds = delay_seconds
        self.pending_signals = deque()  # 待验证的信号
        self.validated_signals = []     # 已验证的信号
        self.virtual_trades = []        # 虚拟成交记录

    def record_signal(self, timestamp, signal_type, side, entry_price, expected_direction):
        """记录信号，等待验证"""
        self.pending_signals.append({
            'timestamp': timestamp,
            'signal_type': signal_type,
            'side': side,
            'entry_price': entry_price,
            'expected_direction': expected_direction,  # +1=上涨, -1=下跌
            'validated': False
        })

    def validate_signals(self, current_time, current_price):
        """验证到期的信号"""
        validated = []

        while self.pending_signals:
            signal = self.pending_signals[0]
            elapsed = (current_time - signal['timestamp']).total_seconds()

            if elapsed >= self.delay_seconds:
                # 验证信号
                self.pending_signals.popleft()

                price_change = (current_price - signal['entry_price']) / signal['entry_price']
                actual_direction = 1 if price_change > 0 else -1

                is_correct = actual_direction == signal['expected_direction']

                signal['exit_price'] = current_price
                signal['price_change_bps'] = price_change * 10000
                signal['is_correct'] = is_correct
                signal['validated'] = True

                self.validated_signals.append(signal)

                if is_correct:
                    validated.append(signal)

                # 记录虚拟成交
                self.virtual_trades.append({
                    'timestamp': signal['timestamp'],
                    'side': signal['side'],
                    'entry': signal['entry_price'],
                    'exit': current_price,
                    'pnl_bps': price_change * 10000 if signal['side'] == 'buy' else -price_change * 10000,
                    'correct': is_correct
                })
            else:
                break

        return validated

    def get_stats(self):
        """获取统计信息"""
        if not self.validated_signals:
            return {'accuracy': 0, 'avg_pnl_bps': 0, 'total': 0}

        correct_count = sum(1 for s in self.validated_signals if s.get('is_correct', False))

        # 计算虚拟PnL（假设买入信号做多，卖出信号做空）
        total_pnl = sum(
            s['price_change_bps'] if s['expected_direction'] == 1 else -s['price_change_bps']
            for s in self.validated_signals
        )

        return {
            'accuracy': correct_count / len(self.validated_signals),
            'avg_pnl_bps': total_pnl / len(self.validated_signals),
            'total_validated': len(self.validated_signals),
            'correct_count': correct_count
        }


class MVPTraderV2Delayed(MVPTraderV2):
    """支持延迟执行的ETH修复版本"""

    def __init__(self, *args, delay_seconds=3, **kwargs):
        super().__init__(*args, **kwargs)

        # 覆盖点差捕获器
        self.spread_capture = SpreadCapture(
            min_spread_ticks=0.5,
            tick_size=0.01,
            maker_rebate=0.0002,
            min_confidence=0.4
        )

        # 延迟执行跟踪
        self.delayed_tracker = DelayedExecutionTracker(delay_seconds=delay_seconds)
        self.price_history = deque(maxlen=100)

        # 降低阈值
        self.alpha_threshold = 0.0003
        self.ofi_threshold = 0.2

    def _rule_based_decision(self, state, orderbook):
        """覆盖规则决策"""
        ofi = state[0]
        toxic = state[9]

        threshold = self.alpha_threshold

        # 只要有OFI信号就产生决策
        if abs(ofi) < threshold or toxic > 0.3:
            return {'action': 'HOLD'}

        side = 'BUY' if ofi > 0 else 'SELL'
        expected_direction = 1 if ofi > 0 else -1

        # 记录信号到延迟跟踪器
        current_price = orderbook['mid_price']
        self.delayed_tracker.record_signal(
            timestamp=datetime.now(),
            signal_type='OFI',
            side=side,
            entry_price=current_price,
            expected_direction=expected_direction
        )

        # 返回决策
        return {
            'action': 'LIMIT',
            'side': side,
            'size': self.max_position,
            'price': orderbook['best_bid'] if side == 'SELL' else orderbook['best_ask']
        }

    def process_tick(self, orderbook):
        """处理tick并验证延迟信号"""
        # 先调用父类处理
        result = super().process_tick(orderbook)

        # 获取当前价格
        current_price = orderbook.get('mid_price')
        if current_price:
            self.price_history.append(current_price)

            # 验证到期的信号
            validated = self.delayed_tracker.validate_signals(
                datetime.now(),
                current_price
            )

            if validated:
                for v in validated:
                    print(f"  [VALIDATED] {v['side']} signal: {v['price_change_bps']:+.2f}bps, correct={v['is_correct']}")

        return result


def get_live_market_data(client, symbol='ETHUSDT'):
    """获取实时市场数据"""
    try:
        depth = client.get_order_book(symbol=symbol, limit=5)
        bids = [{'price': float(price), 'qty': float(qty)} for price, qty in depth['bids']]
        asks = [{'price': float(price), 'qty': float(qty)} for price, qty in depth['asks']]

        best_bid = bids[0]['price']
        best_ask = asks[0]['price']

        return {
            'symbol': symbol,
            'bids': bids,
            'asks': asks,
            'best_bid': best_bid,
            'best_ask': best_ask,
            'mid_price': (best_bid + best_ask) / 2,
            'spread': best_ask - best_bid,
            'spread_bps': (best_ask - best_bid) / ((best_bid + best_ask) / 2) * 10000
        }
    except Exception as e:
        print(f'[ERROR] 获取市场数据失败: {e}')
        return None


def run_eth_delayed(duration_minutes=10, symbol='ETHUSDT'):
    """运行ETH延迟执行策略"""
    print('='*80)
    print('ETH DELAYED EXECUTION - 3s Validation')
    print('='*80)
    print(f'Symbol: {symbol}')
    print(f'Mode: SHADOW with 3s Delayed Validation')
    print(f'Duration: {duration_minutes} minutes')
    print('='*80)
    print('[CONFIGURATION]')
    print('  Validation Delay: 3 seconds')
    print('  min_spread_ticks: 0.5')
    print('  min_confidence: 0.4')
    print('  alpha_threshold: 0.0003')
    print('='*80)

    # 初始化
    try:
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        client = Client(api_key, api_secret)
        print('[OK] Binance API connected')
    except Exception as e:
        print(f'[ERROR] API连接失败: {e}')
        return

    trader = MVPTraderV2Delayed(
        symbol=symbol,
        initial_capital=1000.0,
        max_position=0.05,
        tick_size=0.01,
        use_sac=False,
        shadow_mode=True,
        delay_seconds=3
    )

    print('[OK] MVPTraderV2Delayed initialized')
    print('='*80)

    # 运行循环
    start_time = datetime.now()
    tick_count = 0

    print('\nStarting delayed execution loop...')
    print('-'*80)

    try:
        while (datetime.now() - start_time).seconds < duration_minutes * 60:
            orderbook = get_live_market_data(client, symbol)
            if not orderbook:
                time.sleep(5)
                continue

            result = trader.process_tick(orderbook)
            tick_count += 1

            # 每30秒打印状态
            if tick_count % 30 == 0:
                status = trader.get_status()
                delayed_stats = trader.delayed_tracker.get_stats()

                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Tick {tick_count}")
                print(f"  Price: ${orderbook['mid_price']:,.2f}")
                print(f"  Pending Signals: {len(trader.delayed_tracker.pending_signals)}")
                print(f"  Validated Signals: {delayed_stats['total_validated']}")
                print(f"  3s Prediction Accuracy: {delayed_stats['accuracy']:.1%}")
                print(f"  Virtual Avg PnL: {delayed_stats['avg_pnl_bps']:+.2f}bps")
                print(f"  IC_1s: {status['ic_metrics']['ic_1s']:+.3f} | IC_3s: {status['ic_metrics']['ic_3s']:+.3f}")

            time.sleep(1)

    except KeyboardInterrupt:
        print('\n\nUser interrupted')
    finally:
        print('\n\n' + '='*80)
        print('FINAL REPORT - ETH DELAYED EXECUTION')
        print('='*80)

        trader.print_report()

        delayed_stats = trader.delayed_tracker.get_stats()
        print(f"\n[Delayed Execution Stats]")
        print(f"  Total Validated Signals: {delayed_stats['total_validated']}")
        print(f"  3s Prediction Accuracy: {delayed_stats['accuracy']:.1%}")
        print(f"  Virtual Avg PnL: {delayed_stats['avg_pnl_bps']:+.2f}bps")

        if delayed_stats['total_validated'] > 0:
            print(f"\n[Interpretation]")
            if delayed_stats['accuracy'] > 0.55:
                print("  ✓ 3秒预测有效！信号具备实战价值")
                print(f"  ✓ 建议：使用3秒延迟执行策略")
            elif delayed_stats['accuracy'] > 0.45:
                print("  ~ 预测接近随机，需要优化特征")
            else:
                print("  ✗ 预测反向，检查特征逻辑")

        print('\n' + '='*80)

        return delayed_stats


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='ETH Delayed Execution')
    parser.add_argument('--minutes', type=int, default=10, help='运行时长（分钟）')
    parser.add_argument('--symbol', type=str, default='ETHUSDT', help='交易对')
    args = parser.parse_args()

    run_eth_delayed(
        duration_minutes=args.minutes,
        symbol=args.symbol
    )
