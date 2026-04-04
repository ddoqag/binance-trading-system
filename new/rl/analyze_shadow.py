"""
Shadow Log Analyzer - SAC vs Rule 执行质量审判官

读取 logs/sac_shadow.log (JSON Lines)，计算：
1. Slippage Gap: 规则 vs SAC 的滑点差异
2. Opportunity Cost: 规则 WAIT 但 SAC 建议行动且价格随后起飞的次数
3. Toxic Fill Rate: SAC 相比规则在避免"被埋"上的差异
4. 综合 Alpha-Slippage 报告

用法:
    python rl/analyze_shadow.py --log logs/sac_shadow.log
"""

import argparse
import json
import numpy as np
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional


@dataclass
class ShadowEntry:
    timestamp: float
    state: Optional[List[float]]
    sac_action: Optional[List[float]]
    sac_order: Optional[Dict]
    rule_action: str
    rule_price: Optional[float]
    signal_strength: float
    quantity: float
    book_snapshot: Dict


def load_shadow_log(path: str) -> List[ShadowEntry]:
    entries = []
    p = Path(path)
    if not p.exists():
        print(f"[Analyzer] Log file not found: {path}")
        return entries

    with open(p, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                entries.append(ShadowEntry(
                    timestamp=d.get("timestamp", 0.0),
                    state=d.get("state"),
                    sac_action=d.get("sac_action"),
                    sac_order=d.get("sac_order"),
                    rule_action=d.get("rule_action", "UNKNOWN"),
                    rule_price=d.get("rule_price"),
                    signal_strength=d.get("signal_strength", 0.0),
                    quantity=d.get("quantity", 0.0),
                    book_snapshot=d.get("book_snapshot", {}),
                ))
            except json.JSONDecodeError:
                continue

    print(f"[Analyzer] Loaded {len(entries)} shadow entries from {path}")
    return entries


def estimate_slippage_bps(order: Dict, book: Dict) -> float:
    """
    基于 book snapshot 估算订单执行的滑点（相对 mid）.
    """
    mid = book.get("mid")
    if not mid or mid <= 0:
        return 0.0

    side = order.get("side", "BUY")
    action = order.get("action", "MARKET")
    price = order.get("price")

    if action == "MARKET" or price is None:
        # 简化：MARKET 假设以 best_ask/best_bid 成交，滑点 ≈ half spread
        spread = book.get("spread", 0.0)
        return (spread / mid) * 10000.0 / 2.0

    # LIMIT: 如果挂价比 mid 优（BUY 更低 / SELL 更高），滑点为负（赚 spread）
    if side == "BUY":
        slippage = (price - mid) / mid
    else:
        slippage = (mid - price) / mid
    return slippage * 10000.0


def compute_slippage_gap(entries: List[ShadowEntry]) -> Dict:
    """
    计算 SAC 与规则之间的滑点差异.
    Positive gap = SAC 比规则更省钱（滑点更低）.
    """
    gaps = []
    sac_slips = []
    rule_slips = []

    for e in entries:
        if not e.sac_order:
            continue

        sac_slip = estimate_slippage_bps(e.sac_order, e.book_snapshot)
        rule_order = {
            "action": e.rule_action,
            "side": "BUY" if e.signal_strength >= 0 else "SELL",
            "size": e.quantity,
            "price": e.rule_price,
        }
        rule_slip = estimate_slippage_bps(rule_order, e.book_snapshot)

        gaps.append(rule_slip - sac_slip)
        sac_slips.append(sac_slip)
        rule_slips.append(rule_slip)

    if not gaps:
        return {}

    return {
        "mean_gap_bps": float(np.mean(gaps)),
        "median_gap_bps": float(np.median(gaps)),
        "positive_gap_rate": float(np.mean([g > 0 for g in gaps])),
        "mean_sac_slip_bps": float(np.mean(sac_slips)),
        "mean_rule_slip_bps": float(np.mean(rule_slips)),
        "sample_count": len(gaps),
    }


def compute_opportunity_cost(entries: List[ShadowEntry], look_ahead: int = 3) -> Dict:
    """
    统计规则 WAIT 但 SAC 建议行动，且随后价格向有利方向运动的次数.
    look_ahead: 向后看 N 条记录作为"随后价格"的简化代理.
    """
    opportunities = []
    missed_count = 0

    for i, e in enumerate(entries):
        if e.rule_action != "WAIT":
            continue
        if not e.sac_order or e.sac_order.get("action") == "WAIT":
            continue

        # Rule waited, SAC wanted to act
        side = e.sac_order.get("side", "BUY")
        future_idx = min(i + look_ahead, len(entries) - 1)
        current_mid = e.book_snapshot.get("mid")
        future_mid = entries[future_idx].book_snapshot.get("mid")

        if not current_mid or not future_mid:
            continue

        missed_count += 1
        if side == "BUY" and future_mid > current_mid:
            opportunities.append(1)
        elif side == "SELL" and future_mid < current_mid:
            opportunities.append(1)
        else:
            opportunities.append(0)

    if not missed_count:
        return {"missed_count": 0, "correct_sac_rate": 0.0}

    return {
        "missed_count": missed_count,
        "correct_sac_rate": float(np.mean(opportunities)),
        "mean_opportunity_bps": float(np.mean([
            abs(entries[min(i + look_ahead, len(entries) - 1)].book_snapshot.get("mid", 0) - e.book_snapshot.get("mid", 0)) / e.book_snapshot.get("mid", 1) * 10000.0
            for i, e in enumerate(entries)
            if e.rule_action == "WAIT" and e.sac_order and e.sac_order.get("action") != "WAIT"
        ])),
    }


def compute_toxic_fill_rate(entries: List[ShadowEntry], look_ahead: int = 3) -> Dict:
    """
    估算"被埋"率：下单成交后，价格立刻往不利方向运动的比例.
    由于 shadow log 不含真实成交，我们用"如果按建议下单会被埋的概率"作为代理.
    """
    sac_toxic = []
    rule_toxic = []

    for i, e in enumerate(entries):
        future_idx = min(i + look_ahead, len(entries) - 1)
        current_mid = e.book_snapshot.get("mid")
        future_mid = entries[future_idx].book_snapshot.get("mid")

        if not current_mid or not future_mid:
            continue

        def is_toxic(side: str) -> bool:
            if side == "BUY" and future_mid < current_mid:
                return True
            if side == "SELL" and future_mid > current_mid:
                return True
            return False

        side = "BUY" if e.signal_strength >= 0 else "SELL"

        if e.sac_order and e.sac_order.get("action") != "WAIT":
            sac_toxic.append(int(is_toxic(e.sac_order.get("side", side))))

        if e.rule_action != "WAIT":
            rule_toxic.append(int(is_toxic(side)))

    return {
        "sac_toxic_rate": float(np.mean(sac_toxic)) if sac_toxic else 0.0,
        "rule_toxic_rate": float(np.mean(rule_toxic)) if rule_toxic else 0.0,
        "delta_toxic_rate": (float(np.mean(rule_toxic)) if rule_toxic else 0.0) - (float(np.mean(sac_toxic)) if sac_toxic else 0.0),
        "sample_sac": len(sac_toxic),
        "sample_rule": len(rule_toxic),
    }


def action_distribution(entries: List[ShadowEntry]) -> Dict:
    sac_actions = []
    rule_actions = []
    for e in entries:
        if e.sac_order:
            sac_actions.append(e.sac_order.get("action", "UNKNOWN"))
        rule_actions.append(e.rule_action)

    def dist(actions):
        total = len(actions)
        if total == 0:
            return {}
        return {a: float(actions.count(a)) / total for a in set(actions)}

    return {
        "sac_dist": dist(sac_actions),
        "rule_dist": dist(rule_actions),
    }


def print_report(report: Dict):
    print("\n" + "=" * 60)
    print("  Shadow Log Analysis Report - SAC vs Rule")
    print("=" * 60)

    sg = report.get("slippage_gap", {})
    print("\n[1] Slippage Gap (SAC - Rule)")
    print(f"    Mean Gap (bps)      : {sg.get('mean_gap_bps', 0):+.3f}")
    print(f"    Median Gap (bps)    : {sg.get('median_gap_bps', 0):+.3f}")
    print(f"    SAC Win Rate        : {sg.get('positive_gap_rate', 0):.1%}")
    print(f"    SAC Avg Slip (bps)  : {sg.get('mean_sac_slip_bps', 0):.3f}")
    print(f"    Rule Avg Slip (bps) : {sg.get('mean_rule_slip_bps', 0):.3f}")
    print(f"    Samples             : {sg.get('sample_count', 0)}")

    oc = report.get("opportunity_cost", {})
    print("\n[2] Opportunity Cost (Rule WAIT + SAC Act)")
    print(f"    Missed Signals      : {oc.get('missed_count', 0)}")
    print(f"    SAC Direction Hit   : {oc.get('correct_sac_rate', 0):.1%}")

    tx = report.get("toxic_fill", {})
    print("\n[3] Toxic Fill Proxy (Price Reversal Rate)")
    print(f"    SAC Toxic Rate      : {tx.get('sac_toxic_rate', 0):.1%}")
    print(f"    Rule Toxic Rate     : {tx.get('rule_toxic_rate', 0):.1%}")
    print(f"    Delta (Rule - SAC)  : {tx.get('delta_toxic_rate', 0):+.1%}")

    ad = report.get("action_dist", {})
    print("\n[4] Action Distribution")
    print(f"    SAC  : {ad.get('sac_dist', {})}")
    print(f"    Rule : {ad.get('rule_dist', {})}")

    print("\n" + "=" * 60)
    verdict = "SAC WINS" if sg.get("mean_gap_bps", 0) > 0.5 else "RULE WINS" if sg.get("mean_gap_bps", 0) < -0.5 else "TOO CLOSE"
    print(f"  Verdict: {verdict}")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Analyze SAC Shadow Log")
    parser.add_argument("--log", default="logs/sac_shadow.log", help="Path to JSON Lines shadow log")
    parser.add_argument("--look-ahead", type=int, default=3, help="Future steps for opportunity/toxic proxy")
    args = parser.parse_args()

    entries = load_shadow_log(args.log)
    if not entries:
        return

    report = {
        "meta": {
            "log_path": args.log,
            "total_entries": len(entries),
        },
        "slippage_gap": compute_slippage_gap(entries),
        "opportunity_cost": compute_opportunity_cost(entries, args.look_ahead),
        "toxic_fill": compute_toxic_fill_rate(entries, args.look_ahead),
        "action_dist": action_distribution(entries),
    }

    print_report(report)

    # Optional: save report as JSON
    report_path = Path(args.log).with_suffix(".report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[Analyzer] Report saved to {report_path}")


if __name__ == "__main__":
    main()
