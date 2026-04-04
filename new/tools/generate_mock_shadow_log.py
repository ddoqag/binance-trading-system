#!/usr/bin/env python3
"""
快速生成 mock shadow log，用于测试 analyze_shadow.py 和 BC pre-training。
"""
import json
import random
import numpy as np
from pathlib import Path


def generate_mock_shadow_log(n=500, path="logs/sac_shadow.log"):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    base_price = 65000.0
    entries = []

    for i in range(n):
        mid = base_price + np.sin(i / 50) * 200 + random.gauss(0, 15)
        spread = abs(random.gauss(2.5, 1.0))
        best_bid = round(mid - spread / 2, 2)
        best_ask = round(mid + spread / 2, 2)
        mid = round(mid, 2)

        signal_strength = np.sin(i / 20) + random.gauss(0, 0.3)
        side = "BUY" if signal_strength >= 0 else "SELL"

        # SAC action: [price_offset, size_ratio, urgency]
        sac_action = [
            float(np.clip(random.gauss(0, 0.5), -1.0, 1.0)),
            float(np.clip(random.gauss(0.5, 0.3), 0.0, 1.0)),
            float(np.clip(random.gauss(0.3, 0.4), 0.0, 1.0)),
        ]

        # Map urgency to action
        if sac_action[2] > 0.7:
            sac_order = {"action": "MARKET", "side": side, "size": sac_action[1] * 2.0, "price": None}
        elif sac_action[1] < 0.05:
            sac_order = {"action": "WAIT", "side": side, "size": 0.0, "price": None}
        else:
            offset_ticks = sac_action[0] * 2.0
            price = round(mid + offset_ticks * 0.01, 2)
            if side == "BUY":
                price = min(price, best_ask)
            else:
                price = max(price, best_bid)
            sac_order = {"action": "LIMIT", "side": side, "size": sac_action[1] * 2.0, "price": price}

        # Rule action (correlated but noisier)
        rule_action = random.choices(
            ["WAIT", "MARKET", "LIMIT_PASSIVE", "LIMIT_AGGRESSIVE"],
            weights=[0.45, 0.15, 0.25, 0.15]
        )[0]

        rule_price = None
        if rule_action == "LIMIT_PASSIVE":
            rule_price = best_bid if side == "BUY" else best_ask
        elif rule_action == "LIMIT_AGGRESSIVE":
            rule_price = best_ask if side == "BUY" else best_bid

        state = [
            float(np.clip(signal_strength, -1.0, 1.0)),
            float(np.clip(random.random(), 0.0, 1.0)),
            float(np.clip(random.random(), 0.0, 1.0)),
            float(random.gauss(0, 0.5)),
            float(random.gauss(0, 0.2)),
            float(spread / mid * 10000.0 / 100.0),
            float(random.gauss(0, 0.3)),
            float(np.clip(random.random(), 0.0, 1.0)),
            float(np.clip(random.gauss(0, 0.2), -1.0, 1.0)),
            float(np.clip(random.random(), 0.0, 1.0)),
        ]

        entry = {
            "timestamp": 1743615000.0 + i * 5.0,
            "state": state,
            "sac_action": sac_action,
            "sac_order": sac_order,
            "rule_action": rule_action,
            "rule_price": rule_price,
            "signal_strength": float(signal_strength),
            "quantity": sac_action[1] * 2.0,
            "book_snapshot": {
                "best_bid": best_bid,
                "best_ask": best_ask,
                "mid": mid,
                "spread": round(spread, 2),
            },
        }
        entries.append(entry)

    with open(p, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

    print(f"[MockShadow] Generated {n} entries -> {p}")


if __name__ == "__main__":
    generate_mock_shadow_log()
