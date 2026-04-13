"""
Live Trading Monitor - 实时监控盘状态并自动优化参数建议

功能：
1. 每 5 秒抓取 Go 引擎 API 和 trader 状态
2. 记录价格、价差、持仓、PnL、毒性流级别到 CSV
3. 实时计算趋势指标和交易机会
4. 输出优化建议和异常告警
"""
import os
import sys
import time
import csv
import json
import requests
from datetime import datetime
from collections import deque
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 配置
GO_BASE_URL = 'http://127.0.0.1:8080'
POLL_INTERVAL = 5.0  # 秒
MAX_HISTORY = 500

# 数据缓存
price_history = deque(maxlen=MAX_HISTORY)
spread_bps_history = deque(maxlen=MAX_HISTORY)
toxic_levels = deque(maxlen=MAX_HISTORY)
trades_history = deque(maxlen=100)

CSV_FILE = f'logs/live_monitor_{datetime.now().strftime("%Y%m%d")}.csv'


def ensure_csv():
    os.makedirs('logs', exist_ok=True)
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp', 'price', 'spread_usd', 'spread_bps',
                'position', 'unrealized_pnl', 'daily_pnl',
                'toxic_level', 'toxic_prob', 'trend_score',
                'opportunity', 'suggestion'
            ])


def fetch_status():
    try:
        r = requests.get(f'{GO_BASE_URL}/api/v1/status', timeout=3)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        print(f'[ERROR] API status: {e}')
        return None


def fetch_market():
    try:
        r = requests.get(f'{GO_BASE_URL}/api/v1/market/book', timeout=3)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        print(f'[ERROR] API market: {e}')
        return None


def fetch_position():
    try:
        r = requests.get(f'{GO_BASE_URL}/api/v1/position', timeout=3)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        return None


def fetch_risk():
    try:
        r = requests.get(f'{GO_BASE_URL}/api/v1/risk/stats', timeout=3)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        return None


def calc_ema(values, period):
    if len(values) < period:
        return None
    arr = np.array(list(values)[-period:])
    weights = np.exp(np.linspace(-1., 0., period))
    weights /= weights.sum()
    return np.convolve(arr, weights, mode='valid')[-1]


def calc_trend_score():
    if len(price_history) < 30:
        return 0.0
    ema_short = calc_ema(price_history, 10)
    ema_long = calc_ema(price_history, 30)
    if ema_short is None or ema_long is None or ema_long == 0:
        return 0.0
    # 归一化趋势得分: -1.0 ~ 1.0
    raw = (ema_short - ema_long) / ema_long * 100
    return max(-1.0, min(1.0, raw))


def get_suggestion(trend_score, spread_bps, toxic_level, position):
    suggestions = []

    # 毒性流建议
    if toxic_level >= 8:
        suggestions.append('TOXIC-HIGH: 建议停止交易')
    elif toxic_level >= 5:
        suggestions.append('TOXIC-MED: 仅交易强趋势')

    # 价差建议
    if spread_bps < 0.5:
        suggestions.append('SPREAD-LOW: 价差<0.5bps, spread capture 不可行')
    elif spread_bps > 5.0:
        suggestions.append('SPREAD-HIGH: 价差>5bps, 适合 passive 挂单')

    # 趋势建议
    if abs(trend_score) > 0.3:
        direction = 'BUY' if trend_score > 0 else 'SELL'
        suggestions.append(f'TREND-STRONG: 方向性信号 {direction} (score={trend_score:+.2f})')
    elif abs(trend_score) > 0.1:
        suggestions.append(f'TREND-WEAK: 轻微趋势 (score={trend_score:+.2f})')
    else:
        suggestions.append('TREND-NONE: 无趋势')

    # 持仓建议
    if position == 0:
        suggestions.append('POS-0: 空仓，可建仓')
    else:
        suggestions.append(f'POS-HOLD: 持仓 {position:.4f}')

    return ' | '.join(suggestions)


def main():
    ensure_csv()
    print('=' * 80)
    print('LIVE MONITOR - 实盘监控系统启动')
    print(f'数据记录: {CSV_FILE}')
    print(f'轮询间隔: {POLL_INTERVAL}s')
    print('=' * 80)
    print()

    tick = 0
    while True:
        loop_start = time.time()
        now = datetime.now()

        status = fetch_status()
        market = fetch_market()
        position = fetch_position()
        risk = fetch_risk()

        if market:
            best_bid = market['bids'][0][0] if market.get('bids') else 0
            best_ask = market['asks'][0][0] if market.get('asks') else 0
            mid_price = (best_bid + best_ask) / 2
            spread = best_ask - best_bid
            spread_bps = spread / mid_price * 10000 if mid_price > 0 else 0

            price_history.append(mid_price)
            spread_bps_history.append(spread_bps)
        else:
            mid_price = 0
            spread = 0
            spread_bps = 0

        pos_size = position.get('size', 0) if position else 0
        unrealized = position.get('unrealized', 0) if position else 0
        daily_pnl = risk.get('daily_pnl', 0) if risk else 0

        trend_score = calc_trend_score()
        toxic_level = 0  # 无法直接从 API 获取，后续可扩展
        toxic_prob = 0.0

        # 模拟毒性流级别（基于历史价格波动的异常检测作为代理）
        if len(price_history) > 20:
            returns = np.diff(list(price_history)[-20:]) / np.array(list(price_history)[-20:])[:-1]
            volatility = np.std(returns) * 100  # 百分比
            # 简单代理：高波动视为毒性增加
            toxic_prob = min(1.0, volatility / 0.05)  # 5% 波动率为 100%
            toxic_level = int(toxic_prob * 10)

        toxic_levels.append(toxic_level)

        suggestion = get_suggestion(trend_score, spread_bps, toxic_level, pos_size)
        opportunity = 'YES' if (abs(trend_score) > 0.2 and toxic_level < 8 and spread_bps > 0.1) else 'NO'

        # 写入 CSV
        with open(CSV_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                now.isoformat(), f'{mid_price:.2f}', f'{spread:.4f}', f'{spread_bps:.4f}',
                pos_size, f'{unrealized:.4f}', f'{daily_pnl:.4f}',
                toxic_level, f'{toxic_prob:.2f}', f'{trend_score:.3f}',
                opportunity, suggestion
            ])

        # 每 6 个 tick (30s) 打印一次摘要
        if tick % 6 == 0:
            print(f"[{now.strftime('%H:%M:%S')}] Price=${mid_price:,.2f} | "
                  f"Spread=${spread:.2f} ({spread_bps:.4f}bps) | "
                  f"Pos={pos_size:.4f} | PnL=${daily_pnl:.2f} | "
                  f"Trend={trend_score:+.3f} | Toxic={toxic_level}")
            print(f"  -> {suggestion}")
            print()

        tick += 1
        elapsed = time.time() - loop_start
        sleep_time = max(0, POLL_INTERVAL - elapsed)
        time.sleep(sleep_time)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n监控已停止')
