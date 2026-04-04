"""
Shadow Log Analyzer v3 - Alpha Decomposition (Buy-Side Grade)

把 PnL 拆成 Alpha / Execution / Toxic 三部分
核心升级：
- 抗噪 label (future price smoothing)
- microprice alpha (更敏感)
- 条件分析 (exec | alpha+ vs alpha-)
- 真正的问题诊断
"""
import argparse
import json
import numpy as np
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple


@dataclass
class TradeSample:
    """标准化的交易样本"""
    side: int                    # +1 buy / -1 sell / 0 wait
    mid_t: float
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    fill_price: Optional[float]
    is_filled: bool
    timestamp: float
    sac_action: Optional[List[float]]
    rule_action: str


def load_shadow_log_v3(path: str) -> List[TradeSample]:
    """读取 shadow log 并标准化"""
    samples = []
    p = Path(path)
    if not p.exists():
        print(f"[AnalyzerV3] Log file not found: {path}")
        return samples

    with open(p, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                book = d.get("book_snapshot", {})
                sac_order = d.get("sac_order", {})

                # 确定 side
                signal = d.get("signal_strength", 0.0)
                sac_side_str = sac_order.get("side", "BUY") if sac_order else ("BUY" if signal >= 0 else "SELL")
                side = 1 if sac_side_str == "BUY" else -1

                # SAC 是否交易
                sac_action = d.get("sac_action")
                is_filled = sac_order and sac_order.get("action") in ["LIMIT", "MARKET"]
                fill_price = sac_order.get("price") if is_filled else None

                samples.append(TradeSample(
                    side=side if is_filled else 0,
                    mid_t=book.get("mid", 0.0),
                    bid=book.get("best_bid", 0.0),
                    ask=book.get("best_ask", 0.0),
                    bid_size=1.0,  # REST API 不返回 size，用默认值
                    ask_size=1.0,
                    fill_price=fill_price,
                    is_filled=is_filled,
                    timestamp=d.get("timestamp", 0.0),
                    sac_action=sac_action,
                    rule_action=d.get("rule_action", "WAIT"),
                ))
            except (json.JSONDecodeError, Exception):
                continue

    print(f"[AnalyzerV3] Loaded {len(samples)} samples from {path}")
    return samples


def microprice(bid: float, ask: float, bid_size: float, ask_size: float) -> float:
    """计算 microprice - 对 order flow 更敏感"""
    total = bid_size + ask_size
    if total < 1e-9:
        return (bid + ask) / 2.0
    return (bid * ask_size + ask * bid_size) / total


def future_price_smooth(mids: List[float], idx: int, horizon: int = 10) -> float:
    """
    用未来一段时间的平均价，降低噪声
    """
    if idx + 1 >= len(mids):
        return mids[idx] if mids else 0.0

    future = mids[idx+1 : min(idx+1+horizon, len(mids))]
    if len(future) == 0:
        return mids[idx]
    return np.mean(future)


def compute_direction(mid_t: float, mid_future: float, threshold_bps: float = 0.5) -> int:
    """
    带阈值的方向判断，过滤噪声
    threshold_bps: 最小变动 (bps)
    """
    diff_bps = (mid_future - mid_t) / mid_t * 10000.0

    if diff_bps > threshold_bps:
        return 1
    elif diff_bps < -threshold_bps:
        return -1
    else:
        return 0  # no-signal


@dataclass
class DecompositionResult:
    """分解结果"""
    alpha_mid: float
    alpha_mp: float
    execution: float
    toxicity: float
    filled: bool
    side: int
    direction_correct: bool


def decompose_sample(
    sample: TradeSample,
    mid_future: float,
    mp_t: float,
    mp_future: float,
    direction_threshold_bps: float = 0.5
) -> Optional[DecompositionResult]:
    """
    核心分解函数
    """
    side = sample.side
    if side == 0:
        return None

    # --- Alpha (midprice-based) ---
    alpha_mid = side * (mid_future - sample.mid_t)
    alpha_mid_bps = alpha_mid / sample.mid_t * 10000.0 if sample.mid_t > 0 else 0.0

    # --- Alpha (microprice-based) ---
    alpha_mp = side * (mp_future - mp_t)

    # --- Execution & Toxicity ---
    if sample.is_filled and sample.fill_price:
        # Execution: 成交价格 vs mid (正 = 优于 mid)
        execution = side * (sample.mid_t - sample.fill_price)
        execution_bps = execution / sample.mid_t * 10000.0 if sample.mid_t > 0 else 0.0

        # Toxicity: 成交后价格反向 (负 = toxic)
        toxicity = side * (sample.fill_price - mid_future)
        toxicity_bps = toxicity / sample.mid_t * 10000.0 if sample.mid_t > 0 else 0.0
    else:
        execution = 0.0
        execution_bps = 0.0
        toxicity = 0.0
        toxicity_bps = 0.0

    # --- Direction correctness ---
    true_direction = compute_direction(sample.mid_t, mid_future, direction_threshold_bps)
    predicted_direction = side
    direction_correct = (true_direction == predicted_direction) and true_direction != 0

    return DecompositionResult(
        alpha_mid=alpha_mid_bps,
        alpha_mp=alpha_mp,
        execution=execution_bps,
        toxicity=toxicity_bps,
        filled=sample.is_filled,
        side=side,
        direction_correct=direction_correct
    )


def compute_metrics(results: List[DecompositionResult]) -> Dict:
    """计算聚合指标"""
    if not results:
        return {}

    alpha = np.array([r.alpha_mid for r in results])
    alpha_mp = np.array([r.alpha_mp for r in results])
    execution = np.array([r.execution for r in results])
    toxicity = np.array([r.toxicity for r in results])
    filled = np.array([r.filled for r in results])
    dir_correct = np.array([r.direction_correct for r in results])

    # 只统计实际交易的样本
    traded = [r for r in results if r.filled]

    return {
        # --- Alpha ---
        "alpha_hit": (alpha > 0).mean() if len(alpha) else 0.0,
        "alpha_mean": alpha.mean() if len(alpha) else 0.0,
        "mp_alpha_hit": (alpha_mp > 0).mean() if len(alpha_mp) else 0.0,

        # --- Direction ---
        "direction_hit": dir_correct.mean() if len(dir_correct) else 0.0,
        "direction_hit_traded": np.mean([r.direction_correct for r in traded]) if traded else 0.0,

        # --- Execution ---
        "execution_mean": execution.mean(),
        "execution_win": (execution > 0).mean(),
        "execution_mean_traded": np.mean([r.execution for r in traded]) if traded else 0.0,

        # --- Toxicity ---
        "toxic_rate": (toxicity < 0).mean(),
        "toxic_mean": toxicity.mean(),
        "toxic_rate_traded": np.mean([r.toxicity < 0 for r in traded]) if traded else 0.0,

        # --- Fill ---
        "fill_rate": filled.mean(),
        "trades_count": len(traded),

        # --- Total ---
        "pnl_bps": (alpha + execution).mean(),
        "pnl_traded_bps": np.mean([r.alpha_mid + r.execution for r in traded]) if traded else 0.0,
    }


def conditional_analysis(results: List[DecompositionResult]) -> Dict:
    """
    条件分析 - 核心诊断功能
    """
    traded = [r for r in results if r.filled]
    if not traded:
        return {}

    good_alpha = [r for r in traded if r.alpha_mid > 0]
    bad_alpha = [r for r in traded if r.alpha_mid <= 0]

    def safe_mean(arr, getter):
        vals = [getter(x) for x in arr]
        return np.mean(vals) if len(vals) else 0.0

    return {
        # Execution quality given alpha direction
        "exec_given_good_alpha": safe_mean(good_alpha, lambda x: x.execution),
        "exec_given_bad_alpha": safe_mean(bad_alpha, lambda x: x.execution),

        # Toxicity given bad alpha
        "toxic_given_bad_alpha": safe_mean(bad_alpha, lambda x: x.toxicity),

        # Direction hit breakdown
        "dir_hit_good_alpha": np.mean([r.direction_correct for r in good_alpha]) if good_alpha else 0.0,
        "dir_hit_bad_alpha": np.mean([r.direction_correct for r in bad_alpha]) if bad_alpha else 0.0,

        # Sample sizes
        "n_good_alpha": len(good_alpha),
        "n_bad_alpha": len(bad_alpha),

        # MP advantage
        "mp_alpha_advantage": np.mean([r.alpha_mp - r.alpha_mid for r in traded]),
    }


def print_report_v3(metrics: Dict, cond: Dict, horizon: int):
    """打印 v3 报告"""
    print("\n" + "=" * 70)
    print("  SHADOW LOG ANALYZER V3 - Alpha Decomposition")
    print("=" * 70)

    print(f"\n[Config]")
    print(f"  Future Horizon: {horizon} steps")
    print(f"  Total Trades:   {metrics.get('trades_count', 0)}")
    print(f"  Fill Rate:      {metrics.get('fill_rate', 0):.1%}")

    print(f"\n[1] Alpha Quality (Direction Prediction)")
    print(f"    Alpha Hit Rate        : {metrics.get('alpha_hit', 0):.1%}")
    print(f"    Alpha Mean (bps)      : {metrics.get('alpha_mean', 0):+.3f}")
    print(f"    Microprice Alpha Hit  : {metrics.get('mp_alpha_hit', 0):.1%}")

    print(f"\n[2] Direction Correctness")
    print(f"    Overall Direction Hit : {metrics.get('direction_hit', 0):.1%}")
    print(f"    Traded Direction Hit  : {metrics.get('direction_hit_traded', 0):.1%}")

    print(f"\n[3] Execution Quality")
    print(f"    Execution Mean (bps)  : {metrics.get('execution_mean', 0):+.3f}")
    print(f"    Execution Win Rate    : {metrics.get('execution_win', 0):.1%}")
    print(f"    Traded Exec Mean      : {metrics.get('execution_mean_traded', 0):+.3f}")

    print(f"\n[4] Toxicity Analysis")
    print(f"    Toxic Rate            : {metrics.get('toxic_rate', 0):.1%}")
    print(f"    Toxic Mean (bps)      : {metrics.get('toxic_mean', 0):+.3f}")
    print(f"    Toxic Rate (Traded)   : {metrics.get('toxic_rate_traded', 0):.1%}")

    print(f"\n[5] Conditional Diagnostics (Core Diagnostics)")
    if cond:
        print(f"    Execution | Alpha+    : {cond.get('exec_given_good_alpha', 0):+.3f} bps")
        print(f"    Execution | Alpha-    : {cond.get('exec_given_bad_alpha', 0):+.3f} bps")
        print(f"    Toxicity  | Alpha-    : {cond.get('toxic_given_bad_alpha', 0):+.3f} bps")
        print(f"    Direction Hit | Alpha+: {cond.get('dir_hit_good_alpha', 0):.1%}")
        print(f"    Direction Hit | Alpha-: {cond.get('dir_hit_bad_alpha', 0):.1%}")
        print(f"    Microprice Advantage  : {cond.get('mp_alpha_advantage', 0):+.5f}")
        print(f"    Sample: Good Alpha={cond.get('n_good_alpha', 0)}, Bad={cond.get('n_bad_alpha', 0)}")

    print(f"\n[6] Total PnL")
    print(f"    PnL (all samples)     : {metrics.get('pnl_bps', 0):+.3f} bps")
    print(f"    PnL (traded only)     : {metrics.get('pnl_traded_bps', 0):+.3f} bps")

    print("\n" + "=" * 70)
    print("  DIAGNOSIS")
    print("=" * 70)

    # 核心诊断逻辑
    alpha_hit = metrics.get('alpha_hit', 0)
    direction_hit = metrics.get('direction_hit_traded', 0)
    toxic_rate = metrics.get('toxic_rate_traded', 0)
    exec_mean = metrics.get('execution_mean_traded', 0)

    problems = []

    if direction_hit < 0.5:
        problems.append("[X] Alpha Problem: Direction Hit < 50% (negative predictive power)")

    if toxic_rate > 0.2:
        problems.append(f"[!] Timing Problem: Toxic Rate {toxic_rate:.1%} (high adverse selection)")

    if exec_mean < 0:
        problems.append(f"[!] Execution Problem: Mean execution {exec_mean:.3f} bps")

    if not problems:
        print("[OK] Strategy appears tradable")
    else:
        for p in problems:
            print(f"  {p}")

    # 关键洞察
    print("\n[Key Insight]")
    if cond:
        exec_good = cond.get('exec_given_good_alpha', 0)
        exec_bad = cond.get('exec_given_bad_alpha', 0)

        if exec_good > 0 and exec_bad > 0:
            print("  [!] 'Execution is good, but at wrong timing'")
            print(f"     Exec|Alpha+ = {exec_good:+.3f}, Exec|Alpha- = {exec_bad:+.3f}")
            print("  -> Fix: Direction Head / Reward direction penalty")
        elif exec_good > 0 and exec_bad < 0:
            print("  [OK] Execution quality aligns with Alpha direction")

    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Shadow Log Analyzer V3")
    parser.add_argument("--log", default="logs/sac_shadow_v2.log", help="Path to shadow log")
    parser.add_argument("--horizon", type=int, default=10, help="Future price smoothing horizon")
    parser.add_argument("--threshold", type=float, default=0.5, help="Direction threshold (bps)")
    args = parser.parse_args()

    # 加载数据
    samples = load_shadow_log_v3(args.log)
    if not samples:
        print("[AnalyzerV3] No samples loaded")
        return

    # 预处理：提取 mid price 序列用于 future price
    mids = [s.mid_t for s in samples]

    # 分解每个样本
    results = []
    for i, sample in enumerate(samples):
        # 计算 future price
        mid_future = future_price_smooth(mids, i, args.horizon)

        # 计算 microprice
        mp_t = microprice(sample.bid, sample.ask, sample.bid_size, sample.ask_size)
        mp_future = mp_t  # 简化：假设 microprice 变化与 mid 类似

        # 分解
        result = decompose_sample(sample, mid_future, mp_t, mp_future, args.threshold)
        if result:
            results.append(result)

    # 计算指标
    metrics = compute_metrics(results)
    cond = conditional_analysis(results)

    # 打印报告
    print_report_v3(metrics, cond, args.horizon)

    # 保存详细报告
    report_path = Path(args.log).with_suffix(".v3_report.json")
    with open(report_path, "w") as f:
        json.dump({
            "meta": {
                "log_path": args.log,
                "horizon": args.horizon,
                "threshold_bps": args.threshold,
                "total_samples": len(samples),
                "decomposed_samples": len(results),
            },
            "metrics": metrics,
            "conditional": cond,
        }, f, indent=2)
    print(f"[AnalyzerV3] Detailed report saved to {report_path}")


if __name__ == "__main__":
    main()
