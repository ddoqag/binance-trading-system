"""
BTC Trade Flow Alpha v3 - 优化参数版本

优化参数：
- WINDOW_SECONDS = 10.0 (扩大窗口捕捉更多成交)
- DELAY_SECONDS = 1 (缩短验证延迟)
- CONF_THRESHOLD = 0.7 (降低置信度阈值增加信号)
- MIN_TRADES = 5 (增加最小成交数提高质量)
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
from mvp import SpreadCapture


class Trade:
    """简化成交记录"""
    def __init__(self, timestamp, price, qty, side, is_buyer_maker):
        self.timestamp = timestamp
        self.price = float(price)
        self.qty = float(qty)
        self.side = side
        self.is_buyer_maker = is_buyer_maker


class TradeFlowAlphaV3:
    """Trade Flow Alpha v3 引擎"""

    def __init__(self, window_seconds=10.0, min_trades=5):
        self.window_seconds = window_seconds
        self.min_trades = min_trades
        self.trade_history = deque(maxlen=1000)

        # 权重
        self.w_imbalance = 0.50
        self.w_intensity = 0.30
        self.w_impact = 0.20

        # 历史记录（用于归一化）
        self.imbalance_hist = deque(maxlen=100)
        self.intensity_hist = deque(maxlen=100)

    def add_agg_trade(self, agg_trade):
        """添加聚合成交"""
        is_buyer_maker = agg_trade.get('m', False)
        side = 'sell' if is_buyer_maker else 'buy'

        trade = Trade(
            timestamp=datetime.now().timestamp(),
            price=agg_trade['p'],
            qty=agg_trade['q'],
            side=side,
            is_buyer_maker=is_buyer_maker
        )
        self.trade_history.append(trade)

    def compute_alpha(self, current_mid_price):
        """计算Trade Flow Alpha"""
        now = datetime.now().timestamp()
        cutoff = now - self.window_seconds

        recent = [t for t in self.trade_history if t.timestamp >= cutoff]

        if len(recent) < self.min_trades:
            return 0.0, {'imbalance': 0, 'intensity': 0, 'impact': 0, 'count': 0}

        # 1. Trade Imbalance
        buy_vol = sum(t.qty for t in recent if t.side == 'buy')
        sell_vol = sum(t.qty for t in recent if t.side == 'sell')
        total_vol = buy_vol + sell_vol
        imbalance = (buy_vol - sell_vol) / total_vol if total_vol > 0 else 0

        # 2. Trade Intensity
        trades_per_sec = len(recent) / self.window_seconds
        vol_per_sec = total_vol / self.window_seconds
        intensity = trades_per_sec * np.log1p(vol_per_sec)

        # 3. Price Impact
        vwap = sum(t.price * t.qty for t in recent) / total_vol
        impact = (vwap - current_mid_price) / current_mid_price * 10000

        # 记录历史
        self.imbalance_hist.append(abs(imbalance))
        self.intensity_hist.append(intensity)

        # 归一化
        imb_norm = imbalance
        int_norm = np.tanh(intensity / 5.0) if len(self.intensity_hist) < 20 else \
                   np.clip(intensity / np.percentile(list(self.intensity_hist), 75), -1, 1)
        imp_norm = np.clip(impact / 10.0, -1, 1)

        # Alpha合成
        alpha = self.w_imbalance * imb_norm + \
                self.w_intensity * int_norm + \
                self.w_impact * imp_norm

        return alpha, {
            'imbalance': imbalance,
            'intensity': intensity,
            'impact': impact,
            'count': len(recent),
            'buy_vol': buy_vol,
            'sell_vol': sell_vol
        }


class SignalValidator:
    """信号验证器"""

    def __init__(self, delay_seconds=1, conf_threshold=0.7):
        self.delay_seconds = delay_seconds
        self.conf_threshold = conf_threshold
        self.pending = deque()
        self.validated = []
        self.filtered = 0

    def should_trade(self, alpha_score):
        """置信度过滤"""
        conf = abs(np.tanh(alpha_score * 2))
        if conf < self.conf_threshold:
            self.filtered += 1
            return False, conf
        return True, conf

    def submit_signal(self, timestamp, side, entry_price, expected_dir, alpha, conf, details):
        """提交信号等待验证"""
        self.pending.append({
            'timestamp': timestamp,
            'side': side,
            'entry_price': entry_price,
            'expected_dir': expected_dir,
            'alpha': alpha,
            'conf': conf,
            'details': details
        })

    def validate(self, current_time, current_price):
        """验证到期信号"""
        results = []
        while self.pending:
            sig = self.pending[0]
            elapsed = (current_time - sig['timestamp']).total_seconds()

            if elapsed >= self.delay_seconds:
                self.pending.popleft()

                price_change = (current_price - sig['entry_price']) / sig['entry_price'] * 10000
                actual_dir = 1 if price_change > 0 else -1
                is_correct = actual_dir == sig['expected_dir']

                sig['exit_price'] = current_price
                sig['pnl'] = price_change if sig['expected_dir'] == 1 else -price_change
                sig['correct'] = is_correct

                self.validated.append(sig)
                results.append(sig)
            else:
                break

        return results

    def get_stats(self):
        """获取统计"""
        if not self.validated:
            return {'accuracy': 0, 'avg_pnl': 0, 'total': 0, 'filtered': self.filtered}

        correct = sum(1 for s in self.validated if s.get('correct', False))
        avg_pnl = np.mean([s['pnl'] for s in self.validated])

        return {
            'accuracy': correct / len(self.validated),
            'avg_pnl': avg_pnl,
            'total': len(self.validated),
            'filtered': self.filtered
        }


def run_btc_optimized(duration_minutes=10, symbol='BTCUSDT'):
    """运行优化版BTC Trade Flow测试"""
    print('='*80)
    print('BTC TRADE FLOW ALPHA v3 - Optimized Parameters')
    print('='*80)
    print(f'Symbol: {symbol}')
    print(f'Window: 10s | Delay: 1s | Threshold: 0.7 | Min Trades: 5')
    print(f'Duration: {duration_minutes} minutes')
    print('='*80)

    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    client = Client(api_key, api_secret)
    print('[OK] Binance API connected')

    tf_engine = TradeFlowAlphaV3(window_seconds=10.0, min_trades=5)
    validator = SignalValidator(delay_seconds=1, conf_threshold=0.7)
    spread_cap = SpreadCapture(min_spread_ticks=0.5, tick_size=0.01, min_confidence=0.4)

    print('[OK] Trade Flow Engine initialized')
    print('='*80)

    # 获取初始数据
    print('\nFetching initial trades...')
    try:
        agg_trades = client.get_aggregate_trades(symbol=symbol, limit=100)
        for t in agg_trades:
            tf_engine.add_agg_trade({'p': float(t['p']), 'q': float(t['q']), 'm': t['m']})
        print(f'[OK] Loaded {len(agg_trades)} historical trades')
    except Exception as e:
        print(f'[WARN] Could not load historical trades: {e}')

    start_time = datetime.now()
    tick_count = 0
    last_trade_fetch = 0

    print('\nStarting optimized BTC Trade Flow execution...')
    print('-'*80)

    try:
        while (datetime.now() - start_time).seconds < duration_minutes * 60:
            now = datetime.now()

            try:
                depth = client.get_order_book(symbol=symbol, limit=5)
                bids = [{'price': float(p), 'qty': float(q)} for p, q in depth['bids']]
                asks = [{'price': float(p), 'qty': float(q)} for p, q in depth['asks']]
                mid_price = (bids[0]['price'] + asks[0]['price']) / 2

                if tick_count % 5 == 0 and tick_count > last_trade_fetch:
                    try:
                        new_trades = client.get_aggregate_trades(symbol=symbol, limit=10)
                        for t in new_trades:
                            tf_engine.add_agg_trade({'p': float(t['p']), 'q': float(t['q']), 'm': t['m']})
                        last_trade_fetch = tick_count
                    except:
                        pass

                alpha, details = tf_engine.compute_alpha(mid_price)
                should_trade, conf = validator.should_trade(alpha)

                if should_trade:
                    side = 'BUY' if alpha > 0 else 'SELL'
                    expected_dir = 1 if alpha > 0 else -1

                    validator.submit_signal(
                        timestamp=now, side=side, entry_price=mid_price,
                        expected_dir=expected_dir, alpha=alpha, conf=conf, details=details
                    )

                validated = validator.validate(now, mid_price)

                if validated:
                    for v in validated:
                        d = v['details']
                        status_mark = '[OK]' if v['correct'] else '[X]'
                        print(f"  [{v['side']}] conf={v['conf']:.2f} "
                              f"imb={d['imbalance']:+.2f} int={d['intensity']:.1f} "
                              f"imp={d['impact']:+.2f} => {v['pnl']:+.2f}bps {status_mark}")

                tick_count += 1

                if tick_count % 30 == 0:
                    stats = validator.get_stats()
                    print(f"\n[{now.strftime('%H:%M:%S')}] Tick {tick_count}")
                    print(f"  Price: ${mid_price:,.2f}")
                    print(f"  Signals: {stats['total'] + stats['filtered']} | Filtered: {stats['filtered']}")
                    print(f"  Validated: {stats['total']} | Accuracy: {stats['accuracy']:.1%}")
                    print(f"  Virtual Avg PnL: {stats['avg_pnl']:+.2f}bps")

            except Exception as e:
                print(f"[ERROR] {e}")

            time.sleep(1)

    except KeyboardInterrupt:
        print('\n\nUser interrupted')

    # 最终报告
    print('\n\n' + '='*80)
    print('FINAL REPORT - BTC Trade Flow v3 (Optimized)')
    print('='*80)

    stats = validator.get_stats()

    print(f"\n[Trade Flow Stats]")
    print(f"  Total Signal Candidates: {stats['total'] + stats['filtered']}")
    print(f"  Filtered (conf < 0.7): {stats['filtered']}")
    print(f"  Validated Signals: {stats['total']}")
    print(f"  Accuracy: {stats['accuracy']:.1%}")
    print(f"  Virtual Avg PnL: {stats['avg_pnl']:+.2f}bps")

    if stats['total'] > 0:
        print(f"\n[TARGET CHECK]")
        targets = {
            'Accuracy >= 55%': stats['accuracy'] >= 0.55,
            'Virtual PnL > 1.0bps': stats['avg_pnl'] > 1.0
        }

        for target, achieved in targets.items():
            status = "[OK] ACHIEVED" if achieved else "[X] NOT MET"
            print(f"  {target}: {status}")

        print(f"\n[Interpretation]")
        if stats['accuracy'] >= 0.55 and stats['avg_pnl'] > 0.5:
            print("  [OK] Trade Flow Alpha有效！参数优化成功")
            print("  [OK] 建议：进入SAC集成阶段")
        elif stats['accuracy'] >= 0.50:
            print("  [~] 有一定信号但不够强")
            print("  [~] 建议：进一步调整参数或尝试其他市场")
        else:
            print("  [X] 即使在BTC上Trade Flow Alpha仍无效")
            print("  [X] 建议：放弃此方向，寻找全新Alpha")

    print('\n' + '='*80)

    return stats


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--minutes', type=int, default=10)
    parser.add_argument('--symbol', type=str, default='BTCUSDT')
    args = parser.parse_args()

    run_btc_optimized(args.minutes, args.symbol)
