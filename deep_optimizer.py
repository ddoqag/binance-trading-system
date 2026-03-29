#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Deep Strategy Optimizer - Phase 2
Builds on strategy_optimizer.py best result (short=10, long=25)

1. Fine-grained parameter grid around best result
2. SL/TP joint grid search
3. Walk-forward validation (avoid overfitting)
4. Multi-objective scoring (Sharpe + Return - DD penalty)
5. RSI threshold optimization
6. Best config per timeframe
"""

import sys
import itertools
import numpy as np
import pandas as pd
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.WARNING,          # suppress noise during grid search
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger('DeepOptimizer')

INITIAL_CAPITAL = 10_000
COMMISSION      = 0.001
SYMBOL          = 'BTCUSDT'


# ── helpers ──────────────────────────────────────────────────────────────────

def load_data(symbol: str, interval: str) -> pd.DataFrame:
    """Load from DB via DatabaseClient."""
    try:
        from utils.database import DatabaseClient
        from config.settings import get_settings
        settings = get_settings()
        db = DatabaseClient(settings.db.to_dict())
        df = db.load_klines(symbol, interval)
        if not df.empty:
            return df
    except Exception as e:
        logger.warning(f"DB load failed: {e}")
    return pd.DataFrame()


def run_backtest(df: pd.DataFrame, signals: pd.Series,
                 initial_capital: float = INITIAL_CAPITAL,
                 commission: float = COMMISSION) -> dict:
    """Core vectorised backtest engine."""
    cash, position, entry_price = initial_capital, 0.0, 0.0
    trades, portfolio = [], []

    for i in range(len(df)):
        price = float(df['close'].iloc[i])
        sig   = int(signals.iloc[i])
        val   = cash + position * price
        portfolio.append(val)

        if sig == 1 and position == 0:
            qty         = cash * (1 - commission) / price
            cash       -= qty * price * (1 + commission)
            position    = qty
            entry_price = price
        elif sig == -1 and position > 0:
            pnl  = (price - entry_price) * position
            cash += position * price * (1 - commission)
            trades.append(pnl)
            position = 0

    final_val = cash + position * float(df['close'].iloc[-1])
    total_ret = (final_val - initial_capital) / initial_capital

    pf = pd.Series(portfolio)
    rets = pf.pct_change().dropna()
    sharpe = float(np.sqrt(365 * 24) * rets.mean() / rets.std()) if rets.std() > 1e-9 else 0.0
    cummax = pf.cummax()
    dd     = ((pf - cummax) / cummax).min()

    win_trades = [t for t in trades if t > 0]
    win_rate   = len(win_trades) / len(trades) if trades else 0.0

    return {
        'total_return':  total_ret,
        'sharpe_ratio':  sharpe,
        'max_drawdown':  float(dd),
        'total_trades':  len(trades),
        'win_rate':      win_rate,
        'final_value':   final_val,
    }


def composite_score(r: dict) -> float:
    """Multi-objective: Sharpe + annualised_return - drawdown_penalty."""
    return r['sharpe_ratio'] + r['total_return'] * 2 + r['max_drawdown'] * 3


# ── signal generators ─────────────────────────────────────────────────────────

def dual_ma_signals(df: pd.DataFrame, short: int, long: int) -> pd.Series:
    ma_s = df['close'].rolling(short).mean()
    ma_l = df['close'].rolling(long).mean()
    sig  = pd.Series(0, index=df.index)
    sig[ma_s > ma_l] = 1
    sig[ma_s < ma_l] = -1
    return sig


def rsi_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = df['close'].diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def apply_sltp(df: pd.DataFrame, base_sig: pd.Series,
               sl: float, tp: float, trail: bool = True) -> pd.Series:
    """Overlay fixed + optional trailing SL/TP on a signal series."""
    sig = base_sig.copy()
    position, entry_price, trail_high = 0, 0.0, 0.0

    for i in range(len(df)):
        price = float(df['close'].iloc[i])
        s     = int(sig.iloc[i])

        if position == 0 and s == 1:
            position    = 1
            entry_price = price
            trail_high  = price
        elif position == 1:
            trail_high = max(trail_high, price)
            sl_price   = (trail_high * (1 - sl)) if trail else (entry_price * (1 - sl))
            tp_price   = entry_price * (1 + tp)
            if price <= sl_price or price >= tp_price:
                sig.iloc[i] = -1
                position    = 0
            elif s == -1:
                position = 0

    return sig


# ── Phase 1 : Fine-grained grid ───────────────────────────────────────────────

def phase1_fine_grid(df: pd.DataFrame) -> List[dict]:
    """Expand grid around best (10, 25) with step-1 resolution."""
    print("\n[Phase 1] Fine-grained MA parameter grid (step=1)")
    shorts = range(6, 18)          # 12 values
    longs  = range(18, 42, 2)      # 12 values  → 144 combos
    total  = len(list(shorts)) * len(list(longs))
    print(f"  Combinations: {total}")

    results = []
    for s, l in itertools.product(shorts, longs):
        if l <= s + 4:
            continue
        sig = dual_ma_signals(df, s, l)
        r   = run_backtest(df, sig)
        r.update({'short': s, 'long': l, 'score': composite_score(r)})
        results.append(r)

    results.sort(key=lambda x: -x['score'])

    print(f"\n  TOP 10 (sorted by composite score)")
    print(f"  {'S':>4} {'L':>4} {'Return':>8} {'Sharpe':>7} {'MaxDD':>8} {'Trades':>7} {'Score':>7}")
    print(f"  {'-'*55}")
    for r in results[:10]:
        print(f"  {r['short']:>4} {r['long']:>4} "
              f"{r['total_return']*100:>+7.2f}% "
              f"{r['sharpe_ratio']:>7.2f} "
              f"{r['max_drawdown']*100:>+7.2f}% "
              f"{r['total_trades']:>7} "
              f"{r['score']:>7.3f}")
    return results


# ── Phase 2 : SL/TP grid ─────────────────────────────────────────────────────

def phase2_sltp_grid(df: pd.DataFrame, short: int, long: int) -> List[dict]:
    """Grid search SL / TP percentages on best MA params."""
    print(f"\n[Phase 2] SL/TP grid search on MA({short},{long})")
    sls  = [0.01, 0.02, 0.03, 0.04, 0.05]
    tps  = [0.02, 0.04, 0.06, 0.08, 0.10, 0.15]
    base = dual_ma_signals(df, short, long)
    print(f"  Combinations: {len(sls)*len(tps)*2} (trailing on/off)")

    results = []
    for sl, tp, trail in itertools.product(sls, tps, [True, False]):
        if tp <= sl:
            continue
        sig = apply_sltp(df, base.copy(), sl, tp, trail)
        r   = run_backtest(df, sig)
        r.update({'sl': sl, 'tp': tp, 'trail': trail, 'score': composite_score(r)})
        results.append(r)

    results.sort(key=lambda x: -x['score'])

    print(f"\n  TOP 10 SL/TP combinations")
    print(f"  {'SL':>6} {'TP':>6} {'Trail':>6} {'Return':>8} {'Sharpe':>7} {'MaxDD':>8} {'Score':>7}")
    print(f"  {'-'*56}")
    for r in results[:10]:
        print(f"  {r['sl']*100:>5.0f}% {r['tp']*100:>5.0f}% "
              f"  {'Y' if r['trail'] else 'N':>5} "
              f"{r['total_return']*100:>+7.2f}% "
              f"{r['sharpe_ratio']:>7.2f} "
              f"{r['max_drawdown']*100:>+7.2f}% "
              f"{r['score']:>7.3f}")
    return results


# ── Phase 3 : Walk-forward validation ────────────────────────────────────────

def phase3_walk_forward(df: pd.DataFrame, short: int, long: int,
                        sl: float, tp: float, trail: bool,
                        n_splits: int = 5) -> dict:
    """Walk-forward: train on 70%, test on 30% of each window."""
    print(f"\n[Phase 3] Walk-forward validation ({n_splits} splits)")
    print(f"  Config: MA({short},{long})  SL={sl*100:.0f}%  TP={tp*100:.0f}%  Trail={'Y' if trail else 'N'}")

    window   = len(df) // n_splits
    oos_rets = []

    for i in range(n_splits - 1):
        train_end = (i + 1) * window
        test_end  = min(train_end + window, len(df))

        df_train  = df.iloc[:train_end]
        df_test   = df.iloc[train_end:test_end]
        if len(df_test) < 50:
            continue

        # Re-optimise MA on train window
        best_s, best_l, best_sc = short, long, -999
        for s, l in itertools.product(range(6, 18), range(18, 40, 2)):
            if l <= s + 4:
                continue
            sig = dual_ma_signals(df_train, s, l)
            r   = run_backtest(df_train, sig)
            sc  = composite_score(r)
            if sc > best_sc:
                best_sc, best_s, best_l = sc, s, l

        # Apply to test window
        sig_test = dual_ma_signals(df_test, best_s, best_l)
        sig_test = apply_sltp(df_test, sig_test, sl, tp, trail)
        r_oos    = run_backtest(df_test, sig_test)
        oos_rets.append(r_oos['total_return'])

        print(f"  Split {i+1}: train={train_end}bars  "
              f"best_params=({best_s},{best_l})  "
              f"OOS_return={r_oos['total_return']*100:+.2f}%  "
              f"OOS_sharpe={r_oos['sharpe_ratio']:.2f}")

    mean_oos = np.mean(oos_rets)
    std_oos  = np.std(oos_rets)
    print(f"\n  Walk-forward result:  mean OOS return = {mean_oos*100:+.2f}%  "
          f"std = {std_oos*100:.2f}%  "
          f"consistency = {sum(r > 0 for r in oos_rets)}/{len(oos_rets)}")
    return {'mean_oos': mean_oos, 'std_oos': std_oos, 'splits': oos_rets}


# ── Phase 4 : RSI threshold optimisation ─────────────────────────────────────

def phase4_rsi_filter(df: pd.DataFrame, short: int, long: int,
                      sl: float, tp: float, trail: bool) -> List[dict]:
    """Search RSI overbought/oversold thresholds as entry filter."""
    print(f"\n[Phase 4] RSI threshold optimisation")
    periods     = [7, 10, 14, 21]
    ob_levels   = [60, 65, 70, 75]
    os_levels   = [25, 30, 35, 40]
    base_sig    = dual_ma_signals(df, short, long)
    rsi_results = []

    for period, ob, os_ in itertools.product(periods, ob_levels, os_levels):
        rsi    = rsi_series(df, period)
        sig    = base_sig.copy()
        # Only buy when RSI not overbought; only sell when RSI not oversold
        sig[(sig == 1)  & (rsi > ob)]  = 0
        sig[(sig == -1) & (rsi < os_)] = 0
        sig    = apply_sltp(df, sig, sl, tp, trail)
        r      = run_backtest(df, sig)
        r.update({'rsi_period': period, 'ob': ob, 'os': os_,
                  'score': composite_score(r)})
        rsi_results.append(r)

    rsi_results.sort(key=lambda x: -x['score'])

    print(f"\n  TOP 10 RSI filter configurations")
    print(f"  {'Per':>4} {'OB':>4} {'OS':>4} {'Return':>8} {'Sharpe':>7} {'MaxDD':>8} {'Trades':>7} {'Score':>7}")
    print(f"  {'-'*60}")
    for r in rsi_results[:10]:
        print(f"  {r['rsi_period']:>4} {r['ob']:>4} {r['os']:>4} "
              f"{r['total_return']*100:>+7.2f}% "
              f"{r['sharpe_ratio']:>7.2f} "
              f"{r['max_drawdown']*100:>+7.2f}% "
              f"{r['total_trades']:>7} "
              f"{r['score']:>7.3f}")
    return rsi_results


# ── Phase 5 : Best config on each timeframe ───────────────────────────────────

def phase5_per_timeframe(best_short: int, best_long: int,
                         best_sl: float, best_tp: float,
                         best_trail: bool,
                         best_rsi_period: int, best_ob: int, best_os: int):
    """Apply champion config to 15m / 1h / 4h."""
    print(f"\n[Phase 5] Champion config across timeframes")
    timeframes = ['15m', '1h', '4h']

    print(f"\n  Config: MA({best_short},{best_long})  "
          f"SL={best_sl*100:.0f}%  TP={best_tp*100:.0f}%  "
          f"Trail={'Y' if best_trail else 'N'}  "
          f"RSI({best_rsi_period}) OB={best_ob} OS={best_os}")
    print(f"\n  {'TF':>4} {'Bars':>6} {'Return':>9} {'Sharpe':>8} {'MaxDD':>9} {'Trades':>7} {'WinRate':>8}")
    print(f"  {'-'*60}")

    summary = {}
    for tf in timeframes:
        df = load_data(SYMBOL, tf)
        if df.empty:
            print(f"  {tf:>4}   no data")
            continue

        sig  = dual_ma_signals(df, best_short, best_long)
        rsi  = rsi_series(df, best_rsi_period)
        sig[(sig == 1)  & (rsi > best_ob)]  = 0
        sig[(sig == -1) & (rsi < best_os)]  = 0
        sig  = apply_sltp(df, sig, best_sl, best_tp, best_trail)
        r    = run_backtest(df, sig)
        summary[tf] = r

        print(f"  {tf:>4} {len(df):>6} "
              f"{r['total_return']*100:>+8.2f}% "
              f"{r['sharpe_ratio']:>8.2f} "
              f"{r['max_drawdown']*100:>+8.2f}% "
              f"{r['total_trades']:>7} "
              f"{r['win_rate']*100:>7.1f}%")
    return summary


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  DEEP STRATEGY OPTIMIZER — Phase 2")
    print("  Building on best result: MA(10, 25)  Sharpe=1.03  Return=+4.65%")
    print("=" * 70)

    # Load 1h data as primary optimisation dataset
    df = load_data(SYMBOL, '1h')
    if df.empty:
        print("ERROR: no 1h data available")
        return False
    print(f"\n  Data: {SYMBOL} 1h  —  {len(df)} bars  "
          f"({df.index[0].date()} → {df.index[-1].date()})")

    # ── Phase 1 ────────────────────────────────────────────────────────────
    p1 = phase1_fine_grid(df)
    best1 = p1[0]
    best_short, best_long = best1['short'], best1['long']
    print(f"\n  ★ Phase 1 best: MA({best_short},{best_long})  "
          f"score={best1['score']:.3f}  "
          f"return={best1['total_return']*100:+.2f}%  "
          f"sharpe={best1['sharpe_ratio']:.2f}")

    # ── Phase 2 ────────────────────────────────────────────────────────────
    p2 = phase2_sltp_grid(df, best_short, best_long)
    best2 = p2[0]
    best_sl, best_tp, best_trail = best2['sl'], best2['tp'], best2['trail']
    print(f"\n  ★ Phase 2 best: SL={best_sl*100:.0f}%  TP={best_tp*100:.0f}%  "
          f"trail={'Y' if best_trail else 'N'}  "
          f"score={best2['score']:.3f}  "
          f"return={best2['total_return']*100:+.2f}%")

    # ── Phase 3 ────────────────────────────────────────────────────────────
    p3 = phase3_walk_forward(df, best_short, best_long, best_sl, best_tp, best_trail)

    # ── Phase 4 ────────────────────────────────────────────────────────────
    p4 = phase4_rsi_filter(df, best_short, best_long, best_sl, best_tp, best_trail)
    best4 = p4[0]
    best_rsi_p  = best4['rsi_period']
    best_ob     = best4['ob']
    best_os     = best4['os']
    print(f"\n  ★ Phase 4 best: RSI({best_rsi_p})  OB={best_ob}  OS={best_os}  "
          f"score={best4['score']:.3f}  "
          f"return={best4['total_return']*100:+.2f}%  "
          f"sharpe={best4['sharpe_ratio']:.2f}")

    # ── Phase 5 ────────────────────────────────────────────────────────────
    p5 = phase5_per_timeframe(best_short, best_long,
                               best_sl, best_tp, best_trail,
                               best_rsi_p, best_ob, best_os)

    # ── Final summary ──────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  CHAMPION CONFIGURATION")
    print("=" * 70)
    print(f"  MA params  :  short = {best_short}  /  long = {best_long}")
    print(f"  Stop Loss  :  {best_sl*100:.0f}%  {'(trailing)' if best_trail else '(fixed)'}")
    print(f"  Take Profit:  {best_tp*100:.0f}%")
    print(f"  RSI filter :  period={best_rsi_p}  OB={best_ob}  OS={best_os}")
    print(f"  Walk-fwd   :  mean OOS = {p3['mean_oos']*100:+.2f}%  "
          f"({sum(r>0 for r in p3['splits'])}/{len(p3['splits'])} splits positive)")

    # Full-sample backtest with champion config
    sig  = dual_ma_signals(df, best_short, best_long)
    rsi  = rsi_series(df, best_rsi_p)
    sig[(sig == 1)  & (rsi > best_ob)]  = 0
    sig[(sig == -1) & (rsi < best_os)]  = 0
    sig  = apply_sltp(df, sig, best_sl, best_tp, best_trail)
    champ = run_backtest(df, sig)

    print(f"\n  Full-sample (1h) performance:")
    print(f"    Return     : {champ['total_return']*100:+.2f}%")
    print(f"    Sharpe     : {champ['sharpe_ratio']:.2f}")
    print(f"    Max Drawdown: {champ['max_drawdown']*100:.2f}%")
    print(f"    Trades     : {champ['total_trades']}")
    print(f"    Win Rate   : {champ['win_rate']*100:.1f}%")
    print("=" * 70)

    # Save equity curve plot
    _save_equity_plot(df, sig, best_short, best_long)

    return True


def _save_equity_plot(df, sig, short, long):
    """Save equity curve to plots/."""
    try:
        Path('plots').mkdir(exist_ok=True)
        cash, position = INITIAL_CAPITAL, 0.0
        equity = []
        for i in range(len(df)):
            price = float(df['close'].iloc[i])
            s     = int(sig.iloc[i])
            if s == 1 and position == 0:
                qty = cash * (1 - COMMISSION) / price
                cash -= qty * price * (1 + COMMISSION)
                position = qty
            elif s == -1 and position > 0:
                cash += position * price * (1 - COMMISSION)
                position = 0
            equity.append(cash + position * price)

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
        ax1.plot(df.index, df['close'], lw=0.8, color='steelblue', label='BTC/USDT')
        ma_s = df['close'].rolling(short).mean()
        ma_l = df['close'].rolling(long).mean()
        ax1.plot(df.index, ma_s, lw=1, color='orange', label=f'MA{short}')
        ax1.plot(df.index, ma_l, lw=1, color='red',    label=f'MA{long}')
        ax1.set_title(f'Champion Config: MA({short},{long}) + RSI filter + SL/TP')
        ax1.legend(fontsize=8); ax1.grid(alpha=0.3)

        ax2.plot(df.index, equity, lw=1.2, color='green', label='Equity')
        ax2.axhline(INITIAL_CAPITAL, color='grey', lw=0.8, ls='--')
        ax2.set_title('Equity Curve'); ax2.legend(fontsize=8); ax2.grid(alpha=0.3)

        plt.tight_layout()
        path = f'plots/deep_optim_{short}_{long}.png'
        plt.savefig(path, dpi=150)
        plt.close(fig)
        print(f"\n  Equity curve saved → {path}")
    except Exception as e:
        print(f"  (Plot skipped: {e})")


if __name__ == '__main__':
    ok = main()
    sys.exit(0 if ok else 1)
