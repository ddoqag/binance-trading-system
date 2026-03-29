#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DNA策略 SL/TP/超期 三维 Grid Search
在 BTC 校准因子的基础上，穷举止损/止盈/最大持仓时间组合
"""

import sys
import itertools
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path
from dataclasses import dataclass
from typing import List

sys.path.insert(0, str(Path(__file__).parent))

INITIAL_CAPITAL = 10_000
COMMISSION      = 0.001
SYMBOL          = 'BTCUSDT'
INTERVAL        = '1h'


# ── 数据加载 ──────────────────────────────────────────────────────────────────

def load_data() -> pd.DataFrame:
    from utils.database import DatabaseClient
    from config.settings import get_settings
    settings = get_settings()
    db = DatabaseClient(settings.db.to_dict())
    df = db.load_klines(SYMBOL, INTERVAL)
    df.index = pd.to_datetime(df.index)
    return df


# ── TDX 辅助 ─────────────────────────────────────────────────────────────────

def tdx_ema(s, n): return s.ewm(span=n, adjust=False).mean()
def tdx_ma(s, n):  return s.rolling(n).mean()
def tdx_std(s, n): return s.rolling(n).std(ddof=0)


# ── DNA 信号（BTC校准，固定） ─────────────────────────────────────────────────

def build_dna_score(df: pd.DataFrame) -> pd.Series:
    """
    计算 DNA TOTAL_SCORE（已按 BTC 1h 分位数校准阈值）
    """
    C, H, L = df['close'], df['high'], df['low']

    M10 = tdx_ma(C, 10)
    MA10_RATIO = (C - M10) / M10 * 100
    MA10_SCORE = np.where(MA10_RATIO >  1.0,  25,
                 np.where(MA10_RATIO >  0.0,  15,
                 np.where(MA10_RATIO > -1.0,   5, -15)))

    HL_RATIO = (H - L) / C.shift(1) * 100
    HL_SCORE = np.where(HL_RATIO > 1.5,  20,
               np.where(HL_RATIO > 0.75, 10,
               np.where(HL_RATIO > 0.4,   5, -5)))

    VOL_RATIO = tdx_std(C, 5) / C
    VOL_SCORE = np.where(VOL_RATIO > 0.008, 15,
                np.where(VOL_RATIO > 0.005, 10, 5))

    NL_RATIO  = (tdx_ema(C, 5) - tdx_ema(C, 20)) / C
    NLT_SCORE = np.where(NL_RATIO >  0.003,  23,
                np.where(NL_RATIO >  0.000,  13,
                np.where(NL_RATIO > -0.001,   5, -10)))

    return (pd.Series(MA10_SCORE, index=C.index) * 0.2466 +
            pd.Series(HL_SCORE,   index=C.index) * 0.2042 +
            pd.Series(VOL_SCORE,  index=C.index) * 0.1462 +
            pd.Series(NLT_SCORE,  index=C.index) * 0.2310)


# ── 核心回测（逐 bar，支持可变 SL/TP/超期） ──────────────────────────────────

def run_dna(score: pd.Series,
            close: np.ndarray,
            sl: float,
            tp: float,
            max_hold: int,
            buy_thr: float = 10.0,
            sell_thr: float = 5.0) -> dict:
    n         = len(close)
    cash      = INITIAL_CAPITAL
    position  = 0.0
    entry_p   = 0.0
    entry_bar = -1
    portfolio = np.empty(n)
    trades    = []

    for i in range(n):
        p   = close[i]
        val = cash + position * p
        portfolio[i] = val
        sc  = score.iloc[i]

        if np.isnan(sc):
            continue

        if position == 0:
            if sc > buy_thr:
                qty        = cash * (1 - COMMISSION) / p
                cash      -= qty * p * (1 + COMMISSION)
                position   = qty
                entry_p    = p
                entry_bar  = i
        else:
            bars_held  = i - entry_bar
            exit_flag  = (sc < sell_thr or
                          p < entry_p * (1 - sl) or
                          p > entry_p * (1 + tp) or
                          bars_held > max_hold)
            if exit_flag:
                pnl   = (p - entry_p) * position
                cash += position * p * (1 - COMMISSION)
                trades.append(pnl)
                position  = 0
                entry_p   = 0.0
                entry_bar = -1

    # close any remaining position at last bar
    if position > 0:
        pnl   = (close[-1] - entry_p) * position
        cash += position * close[-1] * (1 - COMMISSION)
        trades.append(pnl)

    final_val = cash
    ret       = (final_val - INITIAL_CAPITAL) / INITIAL_CAPITAL
    peak      = np.maximum.accumulate(portfolio)
    max_dd    = float(((portfolio - peak) / peak).min())

    daily_ret = pd.Series(portfolio).pct_change().dropna()
    sharpe    = (daily_ret.mean() / daily_ret.std() * np.sqrt(8760)
                 if daily_ret.std() > 1e-9 else 0.0)

    n_t      = len(trades)
    win_rate = sum(1 for t in trades if t > 0) / n_t if n_t else 0.0

    score_val = sharpe + ret * 2 + max_dd * 3   # composite (drawdown penalty)

    return {
        'sl':        sl,
        'tp':        tp,
        'max_hold':  max_hold,
        'return':    ret,
        'sharpe':    sharpe,
        'max_dd':    max_dd,
        'n_trades':  n_t,
        'win_rate':  win_rate,
        'score':     score_val,
        'portfolio': portfolio,
    }


# ── Grid Search ───────────────────────────────────────────────────────────────

def grid_search(df: pd.DataFrame) -> List[dict]:
    score_series = build_dna_score(df)
    close        = df['close'].values

    # 参数网格
    sl_grid       = [0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10]        # 止损 2-10%
    tp_grid       = [0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25]  # 止盈 4-25%
    max_hold_grid = [6, 12, 18, 24, 36, 48, 72, 96, 120]               # 超期 6-120h

    combos  = list(itertools.product(sl_grid, tp_grid, max_hold_grid))
    total   = len(combos)
    results = []

    print(f"  参数组合数: {total}  ({len(sl_grid)} SL × {len(tp_grid)} TP × {len(max_hold_grid)} MaxHold)")

    for idx, (sl, tp, mh) in enumerate(combos):
        if idx % 100 == 0:
            print(f"  进度: {idx}/{total} ...", end='\r')
        r = run_dna(score_series, close, sl, tp, mh)
        results.append(r)

    print(f"  完成: {total}/{total}           ")
    return results


# ── Walk-Forward 验证 ─────────────────────────────────────────────────────────

def walk_forward(df: pd.DataFrame,
                 best_sl: float, best_tp: float, best_mh: int,
                 n_splits: int = 4) -> dict:
    """在最优参数上做 walk-forward OOS 验证（70% train / 30% test）"""
    n        = len(df)
    oos_rets = []

    for i in range(1, n_splits + 1):
        train_end = int(n * i / (n_splits + 1))
        test_end  = min(int(n * (i + 1) / (n_splits + 1)), n)
        if test_end <= train_end:
            continue

        oos_df    = df.iloc[train_end:test_end].copy()
        oos_score = build_dna_score(oos_df)
        oos_close = oos_df['close'].values

        r = run_dna(oos_score, oos_close, best_sl, best_tp, best_mh)
        oos_rets.append(r['return'])
        print(f"  Split {i}: OOS bars={len(oos_df)}  return={r['return']:+.2%}  sharpe={r['sharpe']:.2f}")

    mean_oos = float(np.mean(oos_rets)) if oos_rets else 0.0
    pos      = sum(1 for x in oos_rets if x > 0)
    return {'mean_oos': mean_oos, 'positive': pos, 'total': len(oos_rets)}


# ── 绘图 ──────────────────────────────────────────────────────────────────────

def plot_results(results: List[dict], best: dict, df: pd.DataFrame):
    df_r = pd.DataFrame([
        {'sl': r['sl'], 'tp': r['tp'], 'max_hold': r['max_hold'],
         'return': r['return'], 'sharpe': r['sharpe'],
         'max_dd': r['max_dd'], 'n_trades': r['n_trades'],
         'score': r['score']}
        for r in results
    ])

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))

    # Heatmap: SL vs TP (best max_hold fixed)
    best_mh = best['max_hold']
    sub = df_r[df_r['max_hold'] == best_mh]
    pivot = sub.pivot_table(values='sharpe', index='sl', columns='tp', aggfunc='mean')
    im = axes[0, 0].imshow(pivot.values, aspect='auto', cmap='RdYlGn')
    axes[0, 0].set_xticks(range(len(pivot.columns)))
    axes[0, 0].set_xticklabels([f'{v:.0%}' for v in pivot.columns], fontsize=7)
    axes[0, 0].set_yticks(range(len(pivot.index)))
    axes[0, 0].set_yticklabels([f'{v:.0%}' for v in pivot.index], fontsize=7)
    axes[0, 0].set_title(f'Sharpe Heatmap  SL x TP  (MaxHold={best_mh}h)')
    axes[0, 0].set_xlabel('Take Profit')
    axes[0, 0].set_ylabel('Stop Loss')
    plt.colorbar(im, ax=axes[0, 0])

    # Heatmap: SL vs MaxHold (best TP fixed)
    best_tp = best['tp']
    sub2  = df_r[df_r['tp'] == best_tp]
    pivot2 = sub2.pivot_table(values='sharpe', index='sl', columns='max_hold', aggfunc='mean')
    im2 = axes[0, 1].imshow(pivot2.values, aspect='auto', cmap='RdYlGn')
    axes[0, 1].set_xticks(range(len(pivot2.columns)))
    axes[0, 1].set_xticklabels([f'{v}h' for v in pivot2.columns], fontsize=7)
    axes[0, 1].set_yticks(range(len(pivot2.index)))
    axes[0, 1].set_yticklabels([f'{v:.0%}' for v in pivot2.index], fontsize=7)
    axes[0, 1].set_title(f'Sharpe Heatmap  SL x MaxHold  (TP={best_tp:.0%})')
    axes[0, 1].set_xlabel('Max Hold (bars)')
    axes[0, 1].set_ylabel('Stop Loss')
    plt.colorbar(im2, ax=axes[0, 1])

    # Score distribution
    axes[0, 2].hist(df_r['score'], bins=50, color='steelblue', edgecolor='white', linewidth=0.3)
    axes[0, 2].axvline(best['score'], color='red', linestyle='--', label=f"Best={best['score']:.3f}")
    axes[0, 2].set_title('Composite Score Distribution')
    axes[0, 2].set_xlabel('Score')
    axes[0, 2].legend()
    axes[0, 2].grid(alpha=0.3)

    # Top 20 by Sharpe
    top = df_r.nlargest(20, 'sharpe')
    axes[1, 0].barh(range(len(top)), top['sharpe'].values, color='steelblue')
    axes[1, 0].set_yticks(range(len(top)))
    axes[1, 0].set_yticklabels(
        [f"SL{r.sl:.0%} TP{r.tp:.0%} MH{r.max_hold}h" for r in top.itertuples()],
        fontsize=7)
    axes[1, 0].set_title('Top 20 by Sharpe')
    axes[1, 0].set_xlabel('Sharpe')
    axes[1, 0].grid(alpha=0.3, axis='x')

    # Best equity curve vs champion
    champ_port = _champion_portfolio(df)
    best_port  = best['portfolio']
    idx_dates  = df.index[:len(best_port)]
    axes[1, 1].plot(idx_dates, best_port,  color='#e74c3c', linewidth=1.5, label='DNA (best params)')
    axes[1, 1].plot(df.index[:len(champ_port)], champ_port,
                    color='#2ecc71', linewidth=1.5, label='Champion MA(12,28)')
    axes[1, 1].set_title('Best DNA vs Champion')
    axes[1, 1].set_ylabel('Equity (USDT)')
    axes[1, 1].legend()
    axes[1, 1].grid(alpha=0.3)

    # Return vs Drawdown scatter (top 200)
    top200 = df_r.nlargest(200, 'score')
    sc = axes[1, 2].scatter(top200['max_dd'], top200['return'],
                            c=top200['sharpe'], cmap='RdYlGn', s=15, alpha=0.7)
    axes[1, 2].axhline(0, color='gray', linewidth=0.8)
    axes[1, 2].set_xlabel('Max Drawdown')
    axes[1, 2].set_ylabel('Return')
    axes[1, 2].set_title('Return vs Drawdown (Top 200)')
    plt.colorbar(sc, ax=axes[1, 2], label='Sharpe')
    axes[1, 2].grid(alpha=0.3)

    plt.tight_layout()
    Path('plots').mkdir(exist_ok=True)
    out = 'plots/dna_grid_search.png'
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return out


def _champion_portfolio(df: pd.DataFrame) -> np.ndarray:
    """复现 champion MA(12,28)+SL3%+TP8%+Trail+RSI21 的权益曲线"""
    C    = df['close']
    MAS  = C.rolling(12).mean()
    MAL  = C.rolling(28).mean()
    d    = C - C.shift(1)
    ag   = d.clip(lower=0).ewm(com=20, adjust=False).mean()
    al   = (-d).clip(lower=0).ewm(com=20, adjust=False).mean()
    rsi  = 100 - 100 / (1 + ag / (al + 1e-9))

    close = C.values; mas = MAS.values; mal = MAL.values; rsi_v = rsi.values
    cash  = INITIAL_CAPITAL; pos = 0.0; ep = 0.0; trail_peak = 0.0
    port  = np.empty(len(close))
    for i in range(len(close)):
        p = close[i]; port[i] = cash + pos * p
        if np.isnan(mas[i]): continue
        if pos > 0:
            trail_peak = max(trail_peak, p)
            if p < trail_peak * 0.97 or p > ep * 1.08 or mas[i] < mal[i]:
                cash += pos * p * (1 - COMMISSION); pos = 0
        else:
            if (i > 0 and mas[i] > mal[i] and mas[i-1] <= mal[i-1]
                    and 40 < rsi_v[i] < 65):
                qty = cash * (1 - COMMISSION) / p
                cash -= qty * p * (1 + COMMISSION)
                pos = qty; ep = p; trail_peak = p
    if pos > 0:
        cash += pos * close[-1] * (1 - COMMISSION)
    return port


# ── 主程序 ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  DNA策略  SL / TP / MaxHold  三维 Grid Search")
    print("=" * 65)

    print("\n[1] 加载数据...")
    df = load_data()
    print(f"  {len(df)} bars  ({df.index[0].date()} -> {df.index[-1].date()})")

    print("\n[2] 预计算 DNA 信号分数...")
    score_series = build_dna_score(df)
    print(f"  score 范围: {score_series.min():.2f} ~ {score_series.max():.2f}")
    print(f"  score > 10 的 bar 数: {(score_series > 10).sum()}")

    print("\n[3] Grid Search...")
    results = grid_search(df)

    # 按综合得分排序
    results.sort(key=lambda x: x['score'], reverse=True)

    print("\n[4] TOP 20 结果 (按综合得分)")
    print(f"  {'SL':>6} {'TP':>7} {'MaxHold':>8} {'Return':>9} {'Sharpe':>8} {'MaxDD':>8} {'Trades':>7} {'WinRate':>8} {'Score':>8}")
    print("  " + "─" * 75)
    for r in results[:20]:
        print(f"  {r['sl']:>5.0%} {r['tp']:>6.0%} {r['max_hold']:>7}h "
              f"{r['return']:>+8.2%} {r['sharpe']:>8.2f} {r['max_dd']:>8.2%} "
              f"{r['n_trades']:>7} {r['win_rate']:>7.1%} {r['score']:>8.3f}")

    best = results[0]

    # 按 Sharpe 也看一下
    by_sharpe = sorted(results, key=lambda x: x['sharpe'], reverse=True)
    print(f"\n  最高 Sharpe: SL={by_sharpe[0]['sl']:.0%}  TP={by_sharpe[0]['tp']:.0%}  "
          f"MaxHold={by_sharpe[0]['max_hold']}h  Sharpe={by_sharpe[0]['sharpe']:.2f}  "
          f"Return={by_sharpe[0]['return']:+.2%}")

    print(f"\n[5] Walk-Forward 验证 (最优参数: SL={best['sl']:.0%} TP={best['tp']:.0%} MaxHold={best['max_hold']}h)")
    wf = walk_forward(df, best['sl'], best['tp'], best['max_hold'])
    print(f"  均值 OOS return = {wf['mean_oos']:+.2%}  ({wf['positive']}/{wf['total']} splits 正收益)")

    print("\n[6] 绘制图表...")
    best_full = run_dna(build_dna_score(df), df['close'].values,
                        best['sl'], best['tp'], best['max_hold'])
    best_full['portfolio'] = best_full['portfolio']
    out = plot_results(results, best_full, df)
    print(f"  图表已保存 -> {out}")

    print("\n" + "=" * 65)
    print("  冠军 DNA 参数")
    print("=" * 65)
    print(f"  止损 (SL)    : {best['sl']:.0%}")
    print(f"  止盈 (TP)    : {best['tp']:.0%}")
    print(f"  最大持仓     : {best['max_hold']}h")
    print(f"  收益率       : {best['return']:+.2%}")
    print(f"  Sharpe       : {best['sharpe']:.2f}")
    print(f"  最大回撤     : {best['max_dd']:.2%}")
    print(f"  交易次数     : {best['n_trades']}")
    print(f"  胜率         : {best['win_rate']:.1%}")
    print(f"  综合得分     : {best['score']:.3f}")
    print("=" * 65)


if __name__ == '__main__':
    main()
