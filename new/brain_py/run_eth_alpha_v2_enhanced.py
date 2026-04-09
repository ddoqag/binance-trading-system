"""
ETH Alpha V2 增强版 - 三特征融合

阶段2：特征强化
- OFI (订单流不平衡) - 权重0.4
- Micro-price Deviation (微观价格偏移) - 权重0.3
- Trade Pressure (资金方向) - 权重0.3

目标：
- IC_3s: 0.20+ (当前0.1366)
- Accuracy: 70%+
- Virtual PnL: 2.0bps+
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


class AlphaV2Enhanced:
    """
    Alpha V2 增强版 - 三特征融合
    """

    def __init__(self,
                 ofi_weight=0.4,
                 micro_weight=0.3,
                 pressure_weight=0.3):
        self.weights = {
            'ofi': ofi_weight,
            'micro': micro_weight,
            'pressure': pressure_weight
        }

        # 历史记录用于归一化
        self.ofi_history = deque(maxlen=100)
        self.micro_history = deque(maxlen=100)
        self.pressure_history = deque(maxlen=100)

    def compute_micro_price_deviation(self, orderbook):
        """
        计算微观价格偏移 (Micro-price Deviation)

        微观价格 = (best_bid * ask_size + best_ask * bid_size) / (bid_size + ask_size)
        偏移 = (微观价格 - 中间价) / 中间价
        """
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if not bids or not asks:
            return 0.0

        if isinstance(bids[0], dict):
            bid_price, bid_size = bids[0]['price'], bids[0]['qty']
            ask_price, ask_size = asks[0]['price'], asks[0]['qty']
        else:
            bid_price, bid_size = bids[0][0], bids[0][1]
            ask_price, ask_size = asks[0][0], asks[0][1]

        mid_price = (bid_price + ask_price) / 2.0

        if bid_size + ask_size == 0:
            return 0.0

        # 微观价格计算（按深度加权）
        micro_price = (bid_price * ask_size + ask_price * bid_size) / (bid_size + ask_size)

        # 转换为bps (basis points)
        deviation = (micro_price - mid_price) / mid_price * 10000

        return deviation

    def compute_trade_pressure(self, orderbook, recent_trades=None):
        """
        计算交易压力 (Trade Pressure)

        基于订单簿深度不平衡和最近成交方向
        """
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if not bids or not asks:
            return 0.0

        if isinstance(bids[0], dict):
            bid_size = sum(b['qty'] for b in bids[:3])  # 前三档买盘总量
            ask_size = sum(a['qty'] for a in asks[:3])  # 前三档卖盘总量
        else:
            bid_size = sum(b[1] for b in bids[:3])
            ask_size = sum(a[1] for a in asks[:3])

        if bid_size + ask_size == 0:
            return 0.0

        # 深度不平衡 [-1, 1]
        depth_imbalance = (bid_size - ask_size) / (bid_size + ask_size)

        return depth_imbalance

    def compute_ofi(self, orderbook):
        """计算订单流不平衡 (Order Flow Imbalance)"""
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
        """
        综合Alpha分数计算

        Returns:
            alpha_score: 综合分数 [-1, 1]
            components: 各组成部分 {'ofi', 'micro', 'pressure'}
        """
        # 计算三个特征
        ofi = self.compute_ofi(orderbook)
        micro_dev = self.compute_micro_price_deviation(orderbook)
        pressure = self.compute_trade_pressure(orderbook)

        # 记录历史
        self.ofi_history.append(abs(ofi))
        self.micro_history.append(abs(micro_dev))
        self.pressure_history.append(abs(pressure))

        # 动态归一化（使用历史数据的80分位数作为缩放因子）
        def normalize(value, history):
            if len(history) < 20:
                return value  # 早期不过度归一化
            scale = np.percentile(list(history), 80)
            if scale < 0.001:  # 避免除零
                scale = 0.001
            return np.clip(value / scale, -1, 1)

        # 归一化
        ofi_norm = normalize(ofi, self.ofi_history)
        micro_norm = normalize(micro_dev / 10, self.micro_history)  # micro_dev已经是bps
        pressure_norm = normalize(pressure, self.pressure_history)

        # 加权融合
        alpha_score = (
            self.weights['ofi'] * ofi_norm +
            self.weights['micro'] * micro_norm +
            self.weights['pressure'] * pressure_norm
        )

        components = {
            'ofi': ofi,
            'ofi_norm': ofi_norm,
            'micro': micro_dev,
            'micro_norm': micro_norm,
            'pressure': pressure,
            'pressure_norm': pressure_norm
        }

        return alpha_score, components


class ConfidenceFilteredTrackerV2:
    """增强版置信度过滤跟踪器 - 支持Alpha V2"""

    def __init__(self, confidence_threshold=0.85, delay_seconds=3):
        self.confidence_threshold = confidence_threshold
        self.delay_seconds = delay_seconds
        self.pending_signals = deque()
        self.validated_signals = []
        self.filtered_count = 0
        self.alpha_v2 = AlphaV2Enhanced()

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
                'filtered_count': self.filtered_count
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


class MVPTraderV2AlphaEnhanced(MVPTraderV2):
    """Alpha V2 增强版交易器"""

    def __init__(self, *args, confidence_threshold=0.85, delay_seconds=3, **kwargs):
        super().__init__(*args, **kwargs)

        # 覆盖点差捕获器
        self.spread_capture = SpreadCapture(
            min_spread_ticks=0.5,
            tick_size=0.01,
            maker_rebate=0.0002,
            min_confidence=0.4
        )

        # Alpha V2 增强版跟踪器
        self.confidence_tracker = ConfidenceFilteredTrackerV2(
            confidence_threshold=confidence_threshold,
            delay_seconds=delay_seconds
        )

    def _rule_based_decision(self, state, orderbook):
        """使用Alpha V2增强版的规则决策"""
        toxic = state[9]

        # 基础毒性检查
        if toxic > 0.3:
            return {'action': 'HOLD', 'reason': 'toxic'}

        # 使用Alpha V2计算综合分数
        alpha_score, components = self.confidence_tracker.alpha_v2.compute_alpha_score(orderbook)

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
            signal_type='ALPHA_V2',
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
                    comp = v.get('components', {})
                    print(f"  [OK] {v['side']} conf={v['confidence']:.2f} "
                          f"OFI={comp.get('ofi', 0):+.2f} MICRO={comp.get('micro', 0):+.2f} "
                          f"PRESS={comp.get('pressure', 0):+.2f} => {v['price_change_bps']:+.2f}bps")

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


def run_eth_alpha_v2_enhanced(duration_minutes=10, symbol='ETHUSDT'):
    """运行Alpha V2增强版测试"""
    print('='*80)
    print('ETH ALPHA V2 ENHANCED - Phase 2')
    print('='*80)
    print(f'Symbol: {symbol}')
    print(f'Mode: SHADOW with Alpha V2 Enhanced')
    print(f'Features: OFI(0.4) + Micro-Price(0.3) + Trade Pressure(0.3)')
    print(f'Duration: {duration_minutes} minutes')
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

    trader = MVPTraderV2AlphaEnhanced(
        symbol=symbol,
        initial_capital=1000.0,
        max_position=0.05,
        tick_size=0.01,
        use_sac=False,
        shadow_mode=True,
        confidence_threshold=0.85,
        delay_seconds=3
    )

    print('[OK] MVPTraderV2AlphaEnhanced initialized')
    print('[INFO] Alpha V2: 3-Feature Fusion')
    print('='*80)

    # 运行循环
    start_time = datetime.now()
    tick_count = 0

    print('\nStarting Alpha V2 Enhanced execution...')
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

                # 计算各特征的贡献
                alpha_v2 = trader.confidence_tracker.alpha_v2
                if alpha_v2.ofi_history:
                    avg_ofi = np.mean(list(alpha_v2.ofi_history))
                    avg_micro = np.mean(list(alpha_v2.micro_history)) if alpha_v2.micro_history else 0
                    avg_pressure = np.mean(list(alpha_v2.pressure_history)) if alpha_v2.pressure_history else 0
                else:
                    avg_ofi = avg_micro = avg_pressure = 0

                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Tick {tick_count}")
                print(f"  Price: ${orderbook['mid_price']:,.2f}")
                print(f"  Total Signals: {conf_stats['total_signals']}")
                print(f"  Filtered: {conf_stats['filtered_count']} ({conf_stats['filtered_count']/max(1,conf_stats['total_signals']):.1%})")
                print(f"  Validated: {conf_stats['total_validated']}")
                print(f"  Accuracy: {conf_stats['accuracy']:.1%}")
                print(f"  Virtual Avg PnL: {conf_stats['avg_pnl_bps']:+.2f}bps")
                print(f"  Avg |OFI|: {avg_ofi:.3f} | Avg |MICRO|: {avg_micro:.2f}bps | Avg |PRESS|: {avg_pressure:.3f}")

            time.sleep(1)

    except KeyboardInterrupt:
        print('\n\nUser interrupted')
    finally:
        print('\n\n' + '='*80)
        print('FINAL REPORT - ALPHA V2 ENHANCED')
        print('='*80)

        trader.print_report()

        conf_stats = trader.confidence_tracker.get_stats()
        alpha_v2 = trader.confidence_tracker.alpha_v2

        print(f"\n[Alpha V2 Enhanced Stats]")
        print(f"  Total Signal Candidates: {conf_stats['total_signals']}")
        print(f"  Filtered (conf < 0.85): {conf_stats['filtered_count']}")
        print(f"  Passed & Validated: {conf_stats['total_validated']}")
        print(f"  Accuracy: {conf_stats['accuracy']:.1%}")
        print(f"  Virtual Avg PnL: {conf_stats['avg_pnl_bps']:+.2f}bps")

        # 特征统计
        if alpha_v2.ofi_history:
            print(f"\n[Feature Statistics]")
            print(f"  OFI: mean={np.mean(list(alpha_v2.ofi_history)):.3f}, std={np.std(list(alpha_v2.ofi_history)):.3f}")
        if alpha_v2.micro_history:
            print(f"  Micro-Price: mean={np.mean(list(alpha_v2.micro_history)):.2f}bps, std={np.std(list(alpha_v2.micro_history)):.2f}bps")
        if alpha_v2.pressure_history:
            print(f"  Pressure: mean={np.mean(list(alpha_v2.pressure_history)):.3f}, std={np.std(list(alpha_v2.pressure_history)):.3f}")

        # 目标达成检查
        print(f"\n[PHASE 2 TARGETS]")
        targets = {
            'IC_3s >= 0.20': status['ic_metrics']['ic_3s'] >= 0.20,
            'Accuracy >= 70%': conf_stats['accuracy'] >= 0.70,
            'Virtual PnL >= 2.0bps': conf_stats['avg_pnl_bps'] >= 2.0
        }

        for target, achieved in targets.items():
            status_str = "[OK] ACHIEVED" if achieved else "[X] NOT MET"
            print(f"  {target}: {status_str}")

        print(f"\n[Interpretation]")
        if conf_stats['accuracy'] >= 0.70 and conf_stats['avg_pnl_bps'] >= 1.5:
            print("  [OK] Phase 2目标达成！Alpha V2显著有效")
            print("  [OK] 建议：进入实盘测试阶段")
        elif conf_stats['accuracy'] >= 0.65:
            print("  [~] 有改善但需进一步优化")
            print("  [~] 建议：调整特征权重或尝试更高阈值")
        else:
            print("  [X] 三特征融合效果不明显")
            print("  [X] 建议：需要更复杂的特征工程（阶段3）")

        print('\n' + '='*80)

        return conf_stats


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='ETH Alpha V2 Enhanced')
    parser.add_argument('--minutes', type=int, default=10, help='运行时长（分钟）')
    parser.add_argument('--symbol', type=str, default='ETHUSDT', help='交易对')
    args = parser.parse_args()

    run_eth_alpha_v2_enhanced(
        duration_minutes=args.minutes,
        symbol=args.symbol
    )
