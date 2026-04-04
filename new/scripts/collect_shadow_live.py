#!/usr/bin/env python3
"""
Live Shadow Log Collector (REST Polling Mode) - v2 Alpha-aware
通过 Binance REST API 轮询 Order Book，在中国大陆网络环境下更稳定。
使用 rl.feature_engine 计算 state，为 SAC v2 收集真实 shadow 数据。
"""
import argparse
import json
import time
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.execution_models import OrderBook
from core.execution_policy import ExecutionPolicy
from core.queue_model import QueueModel
from core.fill_model import FillModel
from core.slippage_model import SlippageModel
from rl.feature_engine import FeatureEngine
from rl.sac_execution_agent import SACExecutionAgent


def fetch_order_book(symbol: str):
    url = "https://api.binance.com/api/v3/depth"
    resp = requests.get(url, params={"symbol": symbol.upper(), "limit": 5}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    bids = [(float(p), float(s)) for p, s in data.get("bids", [])]
    asks = [(float(p), float(s)) for p, s in data.get("asks", [])]
    return OrderBook(bids=bids, asks=asks)


def collect_shadow_log(symbol: str, duration: float, interval: float, output: str, model_path: str = None):
    print(f"[ShadowCollector] Starting {symbol} REST polling for {duration}s (sample every {interval}s)")

    qm = QueueModel()
    fm = FillModel()
    sm = SlippageModel()
    policy = ExecutionPolicy(qm, fm, sm)
    feature_engine = FeatureEngine(window_size=20)
    sac = SACExecutionAgent(model_path=model_path)

    entries = []
    start = time.time()
    sample_idx = 0

    try:
        while time.time() - start < duration:
            sample_idx += 1
            try:
                book = fetch_order_book(symbol)
            except Exception as e:
                print(f"[ShadowCollector] Fetch failed: {e}")
                time.sleep(max(0.5, interval))
                continue

            if not book.bids or not book.asks:
                time.sleep(0.5)
                continue

            # Compute alpha-aware state via FeatureEngine (no real trades from REST depth)
            state, mid = feature_engine.update(
                {"bids": book.bids, "asks": book.asks},
                trades=[]
            )

            # Use OFI sign as default signal direction for rule policy
            signal_strength = float(state[4]) if not (state is None or len(state) == 0) else 0.0

            action, price = policy.decide(signal_strength, book, estimated_size=1.0)

            sac_action = None
            sac_order = None
            if sac.available and state is not None:
                sac_action = sac.get_action(state, deterministic=False)
                side = "BUY" if signal_strength >= 0 else "SELL"
                sac_order = sac.map_action_to_order(sac_action, side, 1.0, book, tick_size=0.01)

            entry = {
                "timestamp": time.time(),
                "state": state.tolist() if state is not None else None,
                "sac_action": sac_action.tolist() if sac_action is not None else None,
                "sac_order": sac_order,
                "rule_action": action.value,
                "rule_price": price,
                "signal_strength": signal_strength,
                "quantity": 1.0,
                "book_snapshot": {
                    "best_bid": book.best_bid(),
                    "best_ask": book.best_ask(),
                    "mid": book.mid_price(),
                    "spread": book.spread(),
                },
            }
            entries.append(entry)

            if sample_idx % 10 == 0:
                print(
                    f"[ShadowCollector] {sample_idx} samples | "
                    f"bid={book.best_bid()} ask={book.best_ask()} spread={book.spread():.2f}"
                )

            # Periodic flush
            if len(entries) >= 50:
                out_path = Path(output)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with open(out_path, "a") as f:
                    for e in entries:
                        f.write(json.dumps(e) + "\n")
                print(f"[ShadowCollector] Flushed {len(entries)} entries to {out_path}")
                entries.clear()

            elapsed = time.time() - (start + sample_idx * interval)
            sleep_time = max(0, interval - elapsed)
            time.sleep(sleep_time)
    except KeyboardInterrupt:
        print("[ShadowCollector] Interrupted by user")

    if entries:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "a") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    total_written = sample_idx
    print(f"[ShadowCollector] Done. Total samples ~{total_written} appended to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--duration", type=float, default=300.0, help="Collection duration in seconds")
    parser.add_argument("--interval", type=float, default=2.0, help="Sampling interval in seconds")
    parser.add_argument("--output", default="logs/sac_shadow.log")
    parser.add_argument("--sac-model", default=None, help="Optional SAC checkpoint path")
    args = parser.parse_args()
    collect_shadow_log(args.symbol, args.duration, args.interval, args.output, args.sac_model)
