"""
ETH Alpha V2.1 - 替代特征版本

针对ETH市场特性优化：
1. 放弃Micro-Price（ETH上失效）
2. 新增订单簿斜率 (Order Book Slope)
3. 新增点差变化率 (Spread Change Rate)
4. 保留OFI但降低权重

目标：解决特征失效问题，提升IC和PnL
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


class AlphaV2_1:
    """
    Alpha V2.1 - ETH优化版

    特征组合：
    - OFI (0.25) - 降低权重
    - Order Book Slope (0.40) - 新增核心特征
    - Spread Change (0.25) - 新增动量特征
    - Depth Imbalance (0.10) - 新增深度特征
    """

    def __init__(self):
        self.weights = {
            'ofi': 0.25,
            'slope': 0.40,
            'spread_change': 0.25,
            'depth_imbalance': 0.10
        }

        # 历史记录
        self.spread_history = deque(maxlen=20)
        self.ofi_history = deque(maxlen=50)
        self.slope_history = deque(maxlen=50)

    def compute_order_book_slope(self, orderbook):
        """
        计算订单簿斜率

        斜率 = (L1价 - L3价) / (L3量 - L1量)
        正斜率 = 买盘陡峭（支撑强）
        负斜率 = 卖盘陡峭（阻力强）
        """
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if len(bids) < 3 or len(asks) < 3:
            return 0.0

        try:
            # 买盘斜率（取前三档）
            bid_prices = [b['price'] if isinstance(b, dict) else b[0] for b in bids[:3]]
            bid_qtys = [b['qty'] if isinstance(b, dict) else b[1] for b in bids[:3]]

            # 卖盘斜率
            ask_prices = [a['price'] if isinstance(a, dict) else a[0] for a in asks[:3]]
            ask_qtys = [a['qty'] if isinstance(a, dict) else a[1] for a in asks[:3]]

            mid_price = (bid_prices[0] + ask_prices[0]) / 2

            # 买盘斜率：价格下降 vs 数量增加
            bid_slope = ((bid_prices[0] - bid_prices[2]) / mid_price * 10000) / max(bid_qtys[2] - bid_qtys[0], 0.1)

            # 卖盘斜率：价格上升 vs 数量增加
            ask_slope = ((ask_prices[2] - ask_prices[0]) / mid_price * 10000) / max(ask_qtys[2] - ask_qtys[0], 0.1)

            # 综合斜率：买盘陡峭为正，卖盘陡峭为负
            slope = bid_slope - ask_slope

            return slope

        except Exception:
            return 0.0

    def compute_spread_change(self, current_spread_bps):
        """
        计算点差变化率（动量特征）

        点差扩大 = 市场不确定性增加
        点差收缩 = 市场趋于稳定
        """
        self.spread_history.append(current_spread_bps)

        if len(self.spread_history) < 5:
            return 0.0

        # 当前点差 vs 5个周期前的点差
        recent_mean = np.mean(list(self.spread_history)[-5:])
        older_mean = np.mean(list(self.spread_history)[:-5]) if len(self.spread_history) > 5 else recent_mean

        change_rate = (recent_mean - older_mean) / max(older_mean, 0.001)

        return change_rate

    def compute_depth_imbalance(self, orderbook):
        """
        计算深度不平衡（L2+L3 vs L1）
        """
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if len(bids) < 3 or len(asks) < 3:
            return 0.0

        try:
            bid_qtys = [b['qty'] if isinstance(b, dict) else b[1] for b in bids[:3]]
            ask_qtys = [a['qty'] if isinstance(a, dict) else a[1] for a in asks[:3]]

            # L2+L3 vs L1
            bid_deep = bid_qtys[1] + bid_qtys[2]
            bid_l1 = bid_qtys[0]
            ask_deep = ask_qtys[1] + ask_qtys[2]
            ask_l1 = ask_qtys[0]

            # 深度比率不平衡
            bid_deep_ratio = bid_deep / max(bid_l1, 0.001)
            ask_deep_ratio = ask_deep / max(ask_l1, 0.001)

            imbalance = (bid_deep_ratio - ask_deep_ratio) / (bid_deep_ratio + ask_deep_ratio)

            return imbalance

        except Exception:
            return 0.0

    def compute_ofi(self, orderbook):
        """计算OFI"""
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if not bids or not asks:
            return 0.0

        if isinstance(bids[0], dict):
            bid_size = bids[0]['qty']
            ask_size = asks[0]['qty']
        else:
            bid_size = bids[0][1]
            ask_size = asks[0][1]

        if bid_size + ask_size == 0:
            return 0.0

        return (bid_size - ask_size) / (bid_size + ask_size)

    def compute_alpha_score(self, orderbook):
        """计算Alpha V2.1综合分数"""
        # 获取基础数据
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if not bids or not asks:
            return 0.0, {}

        if isinstance(bids[0], dict):
            bid_price, bid_size = bids[0]['price'], bids[0]['qty']
            ask_price, ask_size = asks[0]['price'], asks[0]['qty']
        else:
            bid_price, bid_size = bids[0][0], bids[0][1]
            ask_price, ask_size = asks[0][0], asks[0][1]

        mid_price = (bid_price + ask_price) / 2
        spread_bps = (ask_price - bid_price) / mid_price * 10000

        # 计算四个特征
        ofi = self.compute_ofi(orderbook)
        slope = self.compute_order_book_slope(orderbook)
        spread_change = self.compute_spread_change(spread_bps)
        depth_imb = self.compute_depth_imbalance(orderbook)

        # 记录历史用于归一化
        self.ofi_history.append(abs(ofi))
        self.slope_history.append(abs(slope))

        # 动态归一化
        def normalize(value, history):
            if len(history) < 20:
                return np.tanh(value)  # 早期使用tanh
            scale = np.percentile(list(history), 75)
            if scale < 0.001:
                scale = 0.001
            return np.clip(value / scale, -1, 1)

        ofi_norm = normalize(ofi, self.ofi_history)
        slope_norm = normalize(slope / 10, self.slope_history)  # slope已经是bps
        spread_norm = np.tanh(spread_change * 5)  # 放大变化率信号
        depth_norm = depth_imb  # 已经在[-1,1]

        # 加权融合
        alpha_score = (
            self.weights['ofi'] * ofi_norm +
            self.weights['slope'] * slope_norm +
            self.weights['spread_change'] * spread_norm +
            self.weights['depth_imbalance'] * depth_norm
        )

        components = {
            'ofi': ofi,
            'ofi_norm': ofi_norm,
            'slope': slope,
            'slope_norm': slope_norm,
            'spread_change': spread_change,
            'spread_norm': spread_norm,
            'depth_imb': depth_imb,
            'depth_norm': depth_norm
        }

        return alpha_score, components


class ConfidenceTrackerV2_1:
    """Alpha V2.1 置信度跟踪器"""

    def __init__(self, confidence_threshold=0.85, delay_seconds=3):
        self.confidence_threshold = confidence_threshold
        self.delay_seconds = delay_seconds
        self.pending_signals = deque()
        self.validated_signals = []
        self.filtered_count = 0
        self.alpha_v2_1 = AlphaV2_1()

    def should_trade(self, alpha_score):
        """判断是否应该交易"""
        normalized_score = np.tanh(alpha_score * 2)
        confidence = abs(normalized_score)

        if confidence < self.confidence_threshold:
            self.filtered_count += 1
            return False, normalized_score, confidence

        return True, normalized_score, confidence

    def record_signal(self, timestamp, signal_type, side, entry_price,
                      expected_direction, alpha_score, confidence, components):
        """记录通过过滤的信号"""
        self.pending_signals.append({
            'timestamp': timestamp,
            'signal_type': signal_type,
            'side': side,
            'entry_price': entry_price,
            'expected_direction': expected_direction,
            'alpha_score': alpha_score,
            'confidence': confidence,
            'components': components,
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
                'filtered_count': self.filtered_count,
                'total_signals': self.filtered_count,
                'correct_count': 0
            }

        correct_count = sum(1 for s in self.validated_signals if s.get('is_correct', False))
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


class MVPTraderV2AlphaV2_1(MVPTraderV2):
    """Alpha V2.1 ETH优化版交易器"""

    def __init__(self, *args, confidence_threshold=0.85, delay_seconds=3, **kwargs):
        super().__init__(*args, **kwargs)

        self.spread_capture = SpreadCapture(
            min_spread_ticks=0.5,
            tick_size=0.01,
            maker_rebate=0.0002,
            min_confidence=0.4
        )

        self.confidence_tracker = ConfidenceTrackerV2_1(
            confidence_threshold=confidence_threshold,
            delay_seconds=delay_seconds
        )

    def _rule_based_decision(self, state, orderbook):
        """使用Alpha V2.1的规则决策"""
        toxic = state[9]

        if toxic > 0.3:
            return {'action': 'HOLD', 'reason': 'toxic'}

        alpha_score, components = self.confidence_tracker.alpha_v2_1.compute_alpha_score(orderbook)

        should_trade, normalized_score, confidence = self.confidence_tracker.should_trade(alpha_score)

        if not should_trade:
            return {'action': 'HOLD', 'reason': f'low_confidence_{confidence:.2f}'}

        side = 'BUY' if normalized_score > 0 else 'SELL'
        expected_direction = 1 if normalized_score > 0 else -1

        current_price = orderbook['mid_price']
        self.confidence_tracker.record_signal(
            timestamp=datetime.now(),
            signal_type='ALPHA_V2_1',
            side=side,
            entry_price=current_price,
            expected_direction=expected_direction,
            alpha_score=alpha_score,
            confidence=confidence,
            components=components
        )

        return {
            'action': 'LIMIT',
            'side': side,
            'size': self.max_position,
            'price': orderbook['best_bid'] if side == 'SELL' else orderbook['best_ask'],
            'confidence': confidence,
            'alpha_score': alpha_score
        }

    def process_tick(self, orderbook):
        """处理tick并验证延迟信号"""
        current_price = orderbook.get('mid_price')

        result = super().process_tick(orderbook)

        if current_price:
            validated = self.confidence_tracker.validate_signals(
                datetime.now(),
                current_price
            )

            if validated:
                for v in validated:
                    comp = v.get('components', {})
                    print(f"  [OK] {v['side']} conf={v['confidence']:.2f} "
                          f"OFI={comp.get('ofi', 0):+.2f} SLOPE={comp.get('slope', 0):+.2f} "
                          f"SP_CHG={comp.get('spread_change', 0):+.2f} => {v['price_change_bps']:+.2f}bps")

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


def run_eth_alpha_v2_1(duration_minutes=10, symbol='ETHUSDT'):
    """运行Alpha V2.1测试"""
    print('='*80)
    print('ETH ALPHA V2.1 - Phase 2.1 (ETH-Optimized)')
    print('='*80)
    print(f'Symbol: {symbol}')
    print(f'Mode: SHADOW with Alpha V2.1')
    print(f'Features: OFI(0.25) + Slope(0.40) + SpreadChg(0.25) + Depth(0.10)')
    print(f'Duration: {duration_minutes} minutes')
    print('='*80)

    try:
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        client = Client(api_key, api_secret)
        print('[OK] Binance API connected')
    except Exception as e:
        print(f'[ERROR] API连接失败: {e}')
        return

    trader = MVPTraderV2AlphaV2_1(
        symbol=symbol,
        initial_capital=1000.0,
        max_position=0.05,
        tick_size=0.01,
        use_sac=False,
        shadow_mode=True,
        confidence_threshold=0.85,
        delay_seconds=3
    )

    print('[OK] MVPTraderV2AlphaV2_1 initialized')
    print('[INFO] Alpha V2.1: 4-Feature Fusion (ETH-Optimized)')
    print('='*80)

    start_time = datetime.now()
    tick_count = 0

    print('\nStarting Alpha V2.1 execution...')
    print('-'*80)

    try:
        while (datetime.now() - start_time).seconds < duration_minutes * 60:
            orderbook = get_live_market_data(client, symbol)
            if not orderbook:
                time.sleep(5)
                continue

            result = trader.process_tick(orderbook)
            tick_count += 1

            if tick_count % 30 == 0:
                status = trader.get_status()
                conf_stats = trader.confidence_tracker.get_stats()

                alpha_v2_1 = trader.confidence_tracker.alpha_v2_1

                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Tick {tick_count}")
                print(f"  Price: ${orderbook['mid_price']:,.2f}")
                print(f"  Signals: {conf_stats['total_signals']} | Filtered: {conf_stats['filtered_count']} ({conf_stats['filtered_count']/max(1,conf_stats['total_signals']):.1%})")
                print(f"  Validated: {conf_stats['total_validated']} | Accuracy: {conf_stats['accuracy']:.1%}")
                print(f"  Virtual PnL: {conf_stats['avg_pnl_bps']:+.2f}bps")

            time.sleep(1)

    except KeyboardInterrupt:
        print('\n\nUser interrupted')
    finally:
        print('\n\n' + '='*80)
        print('FINAL REPORT - ALPHA V2.1')
        print('='*80)

        trader.print_report()

        conf_stats = trader.confidence_tracker.get_stats()

        print(f"\n[Alpha V2.1 Stats]")
        print(f"  Total Signals: {conf_stats['total_signals']}")
        print(f"  Filtered: {conf_stats['filtered_count']}")
        print(f"  Validated: {conf_stats['total_validated']}")
        print(f"  Accuracy: {conf_stats['accuracy']:.1%}")
        print(f"  Virtual PnL: {conf_stats['avg_pnl_bps']:+.2f}bps")

        print(f"\n[PHASE 2 TARGETS]")
        targets = {
            'IC_3s >= 0.20': status['ic_metrics']['ic_3s'] >= 0.20,
            'Accuracy >= 70%': conf_stats['accuracy'] >= 0.70,
            'Virtual PnL >= 2.0bps': conf_stats['avg_pnl_bps'] >= 2.0
        }

        achieved_count = sum(1 for v in targets.values() if v)
        for target, achieved in targets.items():
            status_str = "[OK] ACHIEVED" if achieved else "[X] NOT MET"
            print(f"  {target}: {status_str}")

        print(f"\n[Summary] {achieved_count}/3 targets achieved")

        if achieved_count >= 2:
            print("  [OK] Phase 2 substantially complete!")
        elif achieved_count == 1:
            print("  [~] Partial success - needs further tuning")
        else:
            print("  [X] Need Phase 3: Advanced feature engineering")

        print('\n' + '='*80)

        return conf_stats


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='ETH Alpha V2.1')
    parser.add_argument('--minutes', type=int, default=10, help='运行时长（分钟）')
    parser.add_argument('--symbol', type=str, default='ETHUSDT', help='交易对')
    args = parser.parse_args()

    run_eth_alpha_v2_1(
        duration_minutes=args.minutes,
        symbol=args.symbol
    )
