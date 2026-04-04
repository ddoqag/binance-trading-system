#!/usr/bin/env python3
"""
Live Shadow Log Collector v3 - Dual-Head SAC Support

支持 v3 模型的方向预测记录
"""
import argparse
import json
import time
import sys
from pathlib import Path

import requests
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.execution_models import OrderBook
from core.execution_policy import ExecutionPolicy
from core.queue_model import QueueModel
from core.fill_model import FillModel
from core.slippage_model import SlippageModel
from rl.feature_engine import FeatureEngine

# 尝试导入 v3 模型
try:
    from rl.train_sac_v3 import DualHeadSAC
    V3_AVAILABLE = True
except ImportError:
    V3_AVAILABLE = False
    print("[ShadowCollectorV3] Warning: DualHeadSAC not available, falling back to v2")

# 也支持 v2 模型
from rl.sac_execution_agent import SACExecutionAgent


def fetch_order_book(symbol: str):
    url = "https://api.binance.com/api/v3/depth"
    resp = requests.get(url, params={"symbol": symbol.upper(), "limit": 5}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    bids = [(float(p), float(s)) for p, s in data.get("bids", [])]
    asks = [(float(p), float(s)) for p, s in data.get("asks", [])]
    return OrderBook(bids=bids, asks=asks)


class DualHeadAgentWrapper:
    """包装 DualHeadSAC 以兼容 collector 接口"""

    def __init__(self, model_path: str):
        self.agent = DualHeadSAC(state_dim=10, action_dim=3, device="cpu")
        self.available = self.agent.load(model_path)
        if self.available:
            print(f"[DualHeadAgent] Loaded v3 model from {model_path}")

    def get_action(self, state, deterministic=False):
        action, direction, confidence = self.agent.select_action(state, deterministic)
        return action, direction, confidence

    def map_action_to_order(self, action, side, size, book, tick_size=0.01):
        """将动作映射为订单"""
        price_offset = float(action[0])
        size_ratio = float(action[1])
        urgency = float(action[2])

        mid = book.mid_price()
        if mid is None:
            return {"action": "WAIT", "side": side, "size": 0.0, "price": None}

        # 根据 urgency 决定动作类型
        if urgency < 0.15:
            return {"action": "WAIT", "side": side, "size": 0.0, "price": None}
        elif urgency > 0.8:
            # Market order
            exec_price = book.best_ask() if side == "BUY" else book.best_bid()
            return {
                "action": "MARKET",
                "side": side,
                "size": size * size_ratio,
                "price": exec_price
            }
        else:
            # Limit order
            offset_ticks = price_offset * 3.0
            price = mid + offset_ticks * tick_size
            bb = book.best_bid()
            ba = book.best_ask()
            if bb and ba:
                if side == "BUY":
                    price = min(price, ba)
                else:
                    price = max(price, bb)
            price = round(price / tick_size) * tick_size
            return {
                "action": "LIMIT",
                "side": side,
                "size": size * size_ratio,
                "price": price
            }


def collect_shadow_v3(symbol: str, duration: float, interval: float, output: str, model_path: str = None):
    print(f"[ShadowCollectorV3] Starting {symbol} REST polling for {duration}s")

    qm = QueueModel()
    fm = FillModel()
    sm = SlippageModel()
    policy = ExecutionPolicy(qm, fm, sm)
    feature_engine = FeatureEngine(window_size=20)

    # 尝试加载 v3 模型，否则回退到 v2
    agent = None
    agent_type = None
    if model_path:
        if V3_AVAILABLE:
            agent = DualHeadAgentWrapper(model_path)
            if agent.available:
                agent_type = "v3"
            else:
                agent = None

        if agent is None:
            # 回退到 v2
            agent = SACExecutionAgent(model_path=model_path)
            agent_type = "v2" if agent.available else None

    if agent_type:
        print(f"[ShadowCollectorV3] Using {agent_type} agent: {model_path}")
    else:
        print("[ShadowCollectorV3] No model loaded, collecting state only")

    entries = []
    start = time.time()
    sample_idx = 0

    try:
        while time.time() - start < duration:
            sample_idx += 1
            try:
                book = fetch_order_book(symbol)
            except Exception as e:
                print(f"[ShadowCollectorV3] Fetch failed: {e}")
                time.sleep(max(0.5, interval))
                continue

            if not book.bids or not book.asks:
                time.sleep(0.5)
                continue

            # Compute state
            state, mid = feature_engine.update(
                {"bids": book.bids, "asks": book.asks},
                trades=[]
            )

            signal_strength = float(state[4]) if state is not None else 0.0
            action, price = policy.decide(signal_strength, book, estimated_size=1.0)

            # SAC prediction
            sac_action = None
            sac_order = None
            sac_direction = None
            sac_confidence = None

            if agent and agent_type == "v3" and state is not None:
                sac_action, sac_direction, sac_confidence = agent.get_action(state, deterministic=False)
                side = "BUY" if sac_direction >= 0 else "SELL"
                sac_order = agent.map_action_to_order(sac_action, side, 1.0, book, tick_size=0.01)
            elif agent and agent_type == "v2" and state is not None:
                sac_action = agent.get_action(state, deterministic=False)
                side = "BUY" if signal_strength >= 0 else "SELL"
                sac_order = agent.map_action_to_order(sac_action, side, 1.0, book, tick_size=0.01)

            entry = {
                "timestamp": time.time(),
                "state": state.tolist() if state is not None else None,
                "sac_action": sac_action.tolist() if sac_action is not None else None,
                "sac_order": sac_order,
                "sac_direction": sac_direction,
                "sac_confidence": sac_confidence,
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
                "agent_type": agent_type,
            }
            entries.append(entry)

            if sample_idx % 10 == 0:
                print(
                    f"[ShadowCollectorV3] {sample_idx} samples | "
                    f"bid={book.best_bid()} ask={book.best_ask()} "
                    f"dir={sac_direction} conf={sac_confidence:.2f}" if sac_direction is not None else ""
                )

            # Periodic flush
            if len(entries) >= 50:
                out_path = Path(output)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with open(out_path, "a") as f:
                    for e in entries:
                        f.write(json.dumps(e) + "\n")
                print(f"[ShadowCollectorV3] Flushed {len(entries)} entries to {out_path}")
                entries.clear()

            elapsed = time.time() - (start + sample_idx * interval)
            sleep_time = max(0, interval - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("[ShadowCollectorV3] Interrupted by user")

    if entries:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "a") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    total_written = sample_idx
    print(f"[ShadowCollectorV3] Done. Total samples ~{total_written} appended to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--duration", type=float, default=300.0)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--output", default="logs/sac_shadow_v3.log")
    parser.add_argument("--sac-model", default=None, help="Path to SAC v3 checkpoint")
    args = parser.parse_args()
    collect_shadow_v3(args.symbol, args.duration, args.interval, args.output, args.sac_model)
