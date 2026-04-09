"""
ETH信号过滤测试 - 置信度阈值0.7

目标：
1. 过滤低质量信号，提升准确率
2. 交易数量减少60-70%
3. 虚拟PnL提升至1.0bps+
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


class ConfidenceFilteredTracker:
    """置信度过滤跟踪器"""

    def __init__(self, confidence_threshold=0.7, delay_seconds=3):
        self.confidence_threshold = confidence_threshold
        self.delay_seconds = delay_seconds
        self.pending_signals = deque()
        self.validated_signals = []
        self.filtered_count = 0  # 被过滤的信号数

    def should_trade(self, alpha_score):
        """
        判断是否应该交易

        Returns:
            (should_trade: bool, normalized_score: float, confidence: float)
        """
        # 标准化到[-1, 1]范围
        normalized_score = np.tanh(alpha_score * 2)
        confidence = abs(normalized_score)

        if confidence < self.confidence_threshold:
            self.filtered_count += 1
            return False, normalized_score, confidence

        return True, normalized_score, confidence

    def record_signal(self, timestamp, signal_type, side, entry_price,
                      expected_direction, alpha_score, confidence):
        """记录通过过滤的信号"""
        self.pending_signals.append({
            'timestamp': timestamp,
            'signal_type': signal_type,
            'side': side,
            'entry_price': entry_price,
            'expected_direction': expected_direction,
            'alpha_score': alpha_score,
            'confidence': confidence,
            'validated': False
        })

    def validate_signals(self, current_time, current_price):
        """验证到期的信号"""
        validated = []

        while self.pending_signals:
            signal = self.pending_signals[0]
            elapsed = (current_time - signal['timestamp']).total_seconds()

            if elapsed >= self.delay_seconds:
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
            else:
                break

        return validated

    def get_stats(self):
        """获取统计信息"""
        if not self.validated_signals:
            return {
                'accuracy': 0,
                'avg_pnl_bps': 0,
                'total_validated': 0,
                'filtered_count': self.filtered_count
            }

        correct_count = sum(1 for s in self.validated_signals if s.get('is_correct', False))

        # 虚拟PnL（买入做多，卖出做空）
        total_pnl = sum(
            s['price_change_bps'] if s['expected_direction'] == 1 else -s['price_change_bps']
            for s in self.validated_signals
        )

        return {
            'accuracy': correct_count / len(self.validated_signals),
            'avg_pnl_bps': total_pnl / len(self.validated_signals),
            'total_validated': len(self.validated_signals),
            'correct_count': correct_count,
            'filtered_count': self.filtered_count,
            'total_signals': len(self.validated_signals) + self.filtered_count
        }


class MVPTraderV2Confidence(MVPTraderV2):
    """带置信度过滤的ETH交易器"""

    def __init__(self, *args, confidence_threshold=0.7, delay_seconds=3, **kwargs):
        super().__init__(*args, **kwargs)

        # 覆盖点差捕获器
        self.spread_capture = SpreadCapture(
            min_spread_ticks=0.5,
            tick_size=0.01,
            maker_rebate=0.0002,
            min_confidence=0.4
        )

        # 置信度过滤跟踪器
        self.confidence_tracker = ConfidenceFilteredTracker(
            confidence_threshold=confidence_threshold,
            delay_seconds=delay_seconds
        )

        # 降低基础阈值以产生更多信号供过滤
        self.alpha_threshold = 0.0001  # 从0.0003降低

    def _rule_based_decision(self, state, orderbook):
        """带置信度过滤的规则决策"""
        ofi = state[0]
        toxic = state[9]

        # 基础毒性检查
        if toxic > 0.3:
            return {'action': 'HOLD', 'reason': 'toxic'}

        # 计算Alpha分数（这里用OFI作为代理）
        alpha_score = ofi

        # 应用置信度过滤
        should_trade, normalized_score, confidence = self.confidence_tracker.should_trade(alpha_score)

        if not should_trade:
            return {'action': 'HOLD', 'reason': f'low_confidence_{confidence:.2f}'}

        # 通过过滤，产生交易信号
        side = 'BUY' if normalized_score > 0 else 'SELL'
        expected_direction = 1 if normalized_score > 0 else -1

        # 记录信号
        current_price = orderbook['mid_price']
        self.confidence_tracker.record_signal(
            timestamp=datetime.now(),
            signal_type='OFI_CONFIDENCE',
            side=side,
            entry_price=current_price,
            expected_direction=expected_direction,
            alpha_score=alpha_score,
            confidence=confidence
        )

        return {
            'action': 'LIMIT',
            'side': side,
            'size': self.max_position,
            'price': orderbook['best_bid'] if side == 'SELL' else orderbook['best_ask'],
            'confidence': confidence
        }

    def process_tick(self, orderbook):
        """处理tick并验证延迟信号"""
        # 获取当前价格
        current_price = orderbook.get('mid_price')

        # 先调用父类处理
        result = super().process_tick(orderbook)

        # 验证到期的信号
        if current_price:
            validated = self.confidence_tracker.validate_signals(
                datetime.now(),
                current_price
            )

            if validated:
                for v in validated:
                    print(f"  [OK] {v['side']} conf={v['confidence']:.2f}: "
                          f"{v['price_change_bps']:+.2f}bps correct={v['is_correct']}")

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


def run_eth_confidence_filter(duration_minutes=10, symbol='ETHUSDT', confidence_threshold=0.7):
    """运行ETH置信度过滤测试"""
    print('='*80)
    print('ETH CONFIDENCE FILTER TEST')
    print('='*80)
    print(f'Symbol: {symbol}')
    print(f'Mode: SHADOW with Confidence Filter')
    print(f'Confidence Threshold: {confidence_threshold}')
    print(f'Duration: {duration_minutes} minutes')
    print('='*80)
    print('[CONFIGURATION]')
    print(f'  Confidence Threshold: {confidence_threshold}')
    print('  Validation Delay: 3 seconds')
    print('  Alpha Threshold: 0.0001 (lower to generate more candidates)')
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

    trader = MVPTraderV2Confidence(
        symbol=symbol,
        initial_capital=1000.0,
        max_position=0.05,
        tick_size=0.01,
        use_sac=False,
        shadow_mode=True,
        confidence_threshold=confidence_threshold,
        delay_seconds=3
    )

    print(f'[OK] MVPTraderV2Confidence initialized')
    print(f'[INFO] Confidence Threshold: {confidence_threshold}')
    print('='*80)

    # 运行循环
    start_time = datetime.now()
    tick_count = 0

    print('\nStarting confidence-filtered execution...')
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
                conf_stats = trader.confidence_tracker.get_stats()

                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Tick {tick_count}")
                print(f"  Price: ${orderbook['mid_price']:,.2f}")
                print(f"  Total Signals: {conf_stats['total_signals']}")
                print(f"  Filtered (low conf): {conf_stats['filtered_count']}")
                print(f"  Passed & Validated: {conf_stats['total_validated']}")
                print(f"  Accuracy: {conf_stats['accuracy']:.1%}")
                print(f"  Virtual Avg PnL: {conf_stats['avg_pnl_bps']:+.2f}bps")
                print(f"  IC_3s: {status['ic_metrics']['ic_3s']:+.3f}")

            time.sleep(1)

    except KeyboardInterrupt:
        print('\n\nUser interrupted')
    finally:
        print('\n\n' + '='*80)
        print('FINAL REPORT - ETH CONFIDENCE FILTER')
        print('='*80)

        trader.print_report()

        conf_stats = trader.confidence_tracker.get_stats()

        print(f"\n[Confidence Filter Stats]")
        print(f"  Total Signal Candidates: {conf_stats['total_signals']}")
        print(f"  Filtered (conf < {confidence_threshold}): {conf_stats['filtered_count']}")
        print(f"  Filter Rate: {conf_stats['filtered_count']/max(1,conf_stats['total_signals']):.1%}")
        print(f"  Passed & Validated: {conf_stats['total_validated']}")
        print(f"  Accuracy: {conf_stats['accuracy']:.1%}")
        print(f"  Virtual Avg PnL: {conf_stats['avg_pnl_bps']:+.2f}bps")

        # 目标达成检查
        print(f"\n[TARGET CHECK]")
        targets = {
            'Accuracy >= 60%': conf_stats['accuracy'] >= 0.60,
            'Filter Rate 60-70%': 0.60 <= conf_stats['filtered_count']/max(1,conf_stats['total_signals']) <= 0.70,
            'Virtual PnL > 1.0bps': conf_stats['avg_pnl_bps'] > 1.0
        }

        for target, achieved in targets.items():
            status = "[OK] ACHIEVED" if achieved else "[X] NOT MET"
            print(f"  {target}: {status}")

        print(f"\n[Interpretation]")
        if conf_stats['accuracy'] >= 0.60 and conf_stats['avg_pnl_bps'] > 0.5:
            print("  [OK] 信号过滤有效！准确率显著提升")
            print(f"  [OK] 建议：使用confidence_threshold={confidence_threshold}进入实盘")
        elif conf_stats['accuracy'] >= 0.55:
            print("  [~] 有一定改善，但可能需要调整threshold")
            print("  [~] 建议：尝试threshold=0.6或0.8进行对比")
        else:
            print("  [X] 过滤效果不明显")
            print("  [X] 建议：需要强化特征本身（进入阶段2）")

        print('\n' + '='*80)

        return conf_stats


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='ETH Confidence Filter Test')
    parser.add_argument('--minutes', type=int, default=10, help='运行时长（分钟）')
    parser.add_argument('--symbol', type=str, default='ETHUSDT', help='交易对')
    parser.add_argument('--confidence', type=float, default=0.7, help='置信度阈值(0-1)')
    args = parser.parse_args()

    run_eth_confidence_filter(
        duration_minutes=args.minutes,
        symbol=args.symbol,
        confidence_threshold=args.confidence
    )
