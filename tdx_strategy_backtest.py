#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TDX策略回测 - 将通达信公式移植为Python并与冠军配置对比
策略1: BALANCED MOMENTUM 多因子主图
策略2: DNA副图策略
基准: deep_optimizer 冠军 MA(12,28) SL=3% TP=8% Trail RSI(21) OB=65 OS=40
"""

import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path

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


# ── TDX 辅助函数 ──────────────────────────────────────────────────────────────

def tdx_sma(series: pd.Series, n: int, m: int = 1) -> pd.Series:
    """TDX SMA(X,N,M): Y = (Y*(N-M) + X*M) / N  即 alpha = M/N"""
    alpha = m / n
    return series.ewm(alpha=alpha, adjust=False).mean()


def tdx_ema(series: pd.Series, n: int) -> pd.Series:
    """TDX EMA(C,N): 2/(N+1) 加权"""
    return series.ewm(span=n, adjust=False).mean()


def tdx_ma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n).mean()


def tdx_std(series: pd.Series, n: int) -> pd.Series:
    """TDX STD 用总体标准差 ddof=0"""
    return series.rolling(n).std(ddof=0)


# ── 策略 1: BALANCED MOMENTUM ─────────────────────────────────────────────────

def compute_balanced_signals(df: pd.DataFrame) -> pd.Series:
    """
    移植 因子主图-副本.txt
    BUY_PROB = TOTAL_SCORE / 400
    买入: BUY_PROB 上穿 0.6
    卖出: BUY_PROB 下穿 0.4
    """
    C, H, L, V = df['close'], df['high'], df['low'], df['volume']
    N1, N2, N3 = 5, 20, 60

    # ── 趋势层 ──
    MA5  = tdx_ma(C, N1)
    MA20 = tdx_ma(C, N2)
    MA60 = tdx_ma(C, N3)

    MA_TREND1 = np.where(C > MA5,  30, 0) + \
                np.where(C > MA20, 30, 0) + \
                np.where(C > MA60, 20, 0)
    MA_TREND2 = np.where(MA5  > MA5.shift(1),  10, 0) + \
                np.where(MA20 > MA20.shift(1),   5, 0) + \
                np.where(MA60 > MA60.shift(1),   5, 0)
    MA_TREND = MA_TREND1 + MA_TREND2

    DIFF = tdx_ema(C, 12) - tdx_ema(C, 26)
    DEA  = tdx_ema(DIFF, 9)
    MACD_TREND = np.where(DIFF > 0,            20, 0) + \
                 np.where(DIFF > DEA,           20, 0) + \
                 np.where(DIFF > DIFF.shift(1), 10, 0)

    TR1      = pd.concat([H - L,
                          (H - C.shift(1)).abs(),
                          (L - C.shift(1)).abs()], axis=1).max(axis=1)
    PLUS_DM  = np.where((H > H.shift(1)) & (H > L.shift(1)), H - H.shift(1), 0)
    MINUS_DM = np.where((L < L.shift(1)) & (L < H.shift(1)), L.shift(1) - L, 0)
    PLUS_DI  = 100 * pd.Series(PLUS_DM,  index=C.index).rolling(N2).mean() / \
                     TR1.rolling(N2).mean()
    MINUS_DI = 100 * pd.Series(MINUS_DM, index=C.index).rolling(N2).mean() / \
                     TR1.rolling(N2).mean()
    DX  = 100 * (PLUS_DI - MINUS_DI).abs() / (PLUS_DI + MINUS_DI + 1)
    ADX = tdx_ma(DX, N2)
    ADX_TREND = np.where(ADX > 25,           15, 0) + \
                np.where(PLUS_DI > MINUS_DI, 15, 0)

    TREND_SCORE = pd.Series(MA_TREND, index=C.index) + \
                  pd.Series(MACD_TREND, index=C.index) + \
                  pd.Series(ADX_TREND, index=C.index)

    # ── 动量层 ──
    delta = C - C.shift(1)
    RSI6  = tdx_sma(delta.clip(lower=0), 6, 1) / \
            tdx_sma(delta.abs(), 6, 1) * 100
    RSI24 = tdx_sma(delta.clip(lower=0), 24, 1) / \
            tdx_sma(delta.abs(), 24, 1) * 100
    RSI_SIGNAL = np.where(RSI6  > 50, 15, 0) + \
                 np.where(RSI6  < 80, 10, 0) + \
                 np.where(RSI24 > 50, 15, 0)

    LLV9 = L.rolling(9).min()
    HHV9 = H.rolling(9).max()
    RSV  = (C - LLV9) / (HHV9 - LLV9 + 0.001) * 100
    K    = tdx_sma(RSV, 3, 1)
    D    = tdx_sma(K,   3, 1)
    J    = 3 * K - 2 * D
    KDJ_SIGNAL = np.where(K > D,             20, 0) + \
                 np.where(J > J.shift(1),    15, 0) + \
                 np.where(K < 80,            10, 0)

    ROC5  = (C - C.shift(5))  / C.shift(5)  * 100
    ROC20 = (C - C.shift(20)) / C.shift(20) * 100
    ROC_SIGNAL = np.where(ROC5  > 0,       15, 0) + \
                 np.where(ROC20 > 0,       15, 0) + \
                 np.where(ROC5  > ROC20,   10, 0)

    MOM_SCORE = pd.Series(RSI_SIGNAL + KDJ_SIGNAL + ROC_SIGNAL, index=C.index)

    # ── 波动率层 ──
    BOLL_MID   = tdx_ma(C, N2)
    BOLL_STD   = tdx_std(C, N2)
    BOLL_UPPER = BOLL_MID + 2 * BOLL_STD
    BOLL_LOWER = BOLL_MID - 2 * BOLL_STD
    BOLL_POS   = (C - BOLL_LOWER) / (BOLL_UPPER - BOLL_LOWER + 0.001) * 100
    BOLL_SIGNAL = np.where((BOLL_POS > 30) & (BOLL_POS < 70), 20, 0) + \
                  np.where(BOLL_POS > 50, 15, 0)
    ATR14      = tdx_ma(TR1, 14)
    ATR_RATIO  = ATR14 / C * 100
    ATR_SIGNAL = np.where(ATR_RATIO < 3, 20, 0) + np.where(ATR_RATIO > 1, 10, 0)
    VOLA_SCORE = pd.Series(BOLL_SIGNAL + ATR_SIGNAL, index=C.index)

    # ── 成交量层 ──
    VOL_MA5  = tdx_ma(V, 5)
    VOL_MA20 = tdx_ma(V, 20)
    VOL_TREND = np.where(V > V.shift(1),   20, 0) + \
                np.where(V > VOL_MA5,      15, 0) + \
                np.where(VOL_MA5 > VOL_MA20, 15, 0)
    obv_delta = np.where(C > C.shift(1), V, np.where(C < C.shift(1), -V, 0))
    OBV       = pd.Series(obv_delta, index=C.index).cumsum()
    OBV_MA    = tdx_ma(OBV, N2)
    OBV_SIGNAL = np.where(OBV > OBV_MA,        25, 0) + \
                 np.where(OBV > OBV.shift(1),   15, 0)
    VOL_SCORE = pd.Series(VOL_TREND + OBV_SIGNAL, index=C.index)

    # ── 综合 ──
    TOTAL_SCORE = TREND_SCORE * 1.2 + MOM_SCORE * 1.0 + VOLA_SCORE * 0.8 + VOL_SCORE * 0.6
    BUY_PROB = (TOTAL_SCORE / 400).clip(0, 1)
    BUY_LINE, SELL_LINE = 0.6, 0.4

    # 金叉/死叉形式的信号
    sig = pd.Series(0, index=C.index)
    sig[(BUY_PROB > BUY_LINE) & (BUY_PROB.shift(1) <= BUY_LINE)]  = 1
    sig[(BUY_PROB < SELL_LINE) & (BUY_PROB.shift(1) >= SELL_LINE)] = -1
    return sig, BUY_PROB


# ── 策略 2: DNA 副图 ──────────────────────────────────────────────────────────

def compute_dna_signals(df: pd.DataFrame) -> pd.Series:
    """
    移植 DNA副图.txt，阈值已按 BTC 1h 实际分位数重新校准
    原公式为 A 股设计：HL振幅 3-10%，BTC 1h 振幅均值仅 0.92%
    校准后阈值：HL >1.5/0.75/0.4, VOL >0.008/0.005, MA10 >1/0/-1
    买入阈值从 15 → 10（分布适配）
    """
    C, H, L = df['close'], df['high'], df['low']

    M10 = tdx_ma(C, 10)

    # MA10比率因子 — BTC: 75th pct=0.49%, 90th=1.12%
    MA10_RATIO = (C - M10) / M10 * 100
    MA10_SCORE = np.where(MA10_RATIO >  1.0,  25,
                 np.where(MA10_RATIO >  0.0,  15,
                 np.where(MA10_RATIO > -1.0,   5, -15)))

    # 高低价比率因子 — BTC 1h: 50th=0.76%, 75th=1.15%, 90th=1.68%
    HL_RATIO = (H - L) / C.shift(1) * 100
    HL_SCORE = np.where(HL_RATIO > 1.5,  20,
               np.where(HL_RATIO > 0.75, 10,
               np.where(HL_RATIO > 0.4,   5, -5)))

    # 波动率因子 — VOL/C: 50th=0.35%, 75th=0.55%, 90th=0.87%
    VOLATILITY_5 = tdx_std(C, 5)
    VOL_RATIO    = VOLATILITY_5 / C
    VOL_SCORE    = np.where(VOL_RATIO > 0.008, 15,
                   np.where(VOL_RATIO > 0.005, 10, 5))

    # 非线性趋势因子 — NLT/C: 50th=-0.09%, 75th=0.39%
    NL_TREND  = tdx_ema(C, 5) - tdx_ema(C, 20)
    NL_RATIO  = NL_TREND / C
    NLT_SCORE = np.where(NL_RATIO >  0.003,  23,
                np.where(NL_RATIO >  0.000,  13,
                np.where(NL_RATIO > -0.001,   5, -10)))

    TOTAL = (pd.Series(MA10_SCORE, index=C.index) * 0.2466 +
             pd.Series(HL_SCORE,   index=C.index) * 0.2042 +
             pd.Series(VOL_SCORE,  index=C.index) * 0.1462 +
             pd.Series(NLT_SCORE,  index=C.index) * 0.2310)

    return TOTAL


def run_dna_backtest(df: pd.DataFrame,
                     sl: float = 0.097,
                     tp: float = 0.244,
                     max_hold: int = 44,
                     commission: float = COMMISSION,
                     initial: float = INITIAL_CAPITAL) -> dict:
    """逐 bar 模拟 DNA 策略（含止损/止盈/超期）"""
    score = compute_dna_signals(df)
    close = df['close'].values
    n = len(close)

    cash      = initial
    position  = 0.0
    entry_p   = 0.0
    entry_bar = -1
    portfolio = []
    trades    = []

    for i in range(n):
        p   = close[i]
        sc  = score.iloc[i]
        val = cash + position * p
        portfolio.append(val)

        if np.isnan(sc):
            continue

        if position == 0:
            # 买入条件（BTC校准阈值10，原A股阈值15）
            if sc > 10:
                qty        = cash * (1 - commission) / p
                cash      -= qty * p * (1 + commission)
                position   = qty
                entry_p    = p
                entry_bar  = i
        else:
            bars_held = i - entry_bar
            exit_cond = (sc < 5 or
                         p < entry_p * (1 - sl) or
                         p > entry_p * (1 + tp) or
                         bars_held > max_hold)
            if exit_cond:
                pnl   = (p - entry_p) * position
                cash += position * p * (1 - commission)
                trades.append(pnl)
                position  = 0
                entry_p   = 0.0
                entry_bar = -1

    final_val = cash + position * close[-1]
    portfolio = np.array(portfolio)
    ret = (final_val - initial) / initial

    if len(trades) > 0:
        wins     = [t for t in trades if t > 0]
        win_rate = len(wins) / len(trades)
    else:
        win_rate = 0.0

    peak   = np.maximum.accumulate(portfolio)
    dd_arr = (portfolio - peak) / peak
    max_dd = float(dd_arr.min())

    daily_ret = pd.Series(portfolio).pct_change().dropna()
    sharpe = (daily_ret.mean() / daily_ret.std() * np.sqrt(8760)
              if daily_ret.std() > 0 else 0.0)

    return {
        'final_value': final_val,
        'return':      ret,
        'sharpe':      sharpe,
        'max_dd':      max_dd,
        'n_trades':    len(trades),
        'win_rate':    win_rate,
        'portfolio':   portfolio,
    }


# ── 策略 3: 冠军基准 MA(12,28) + SL/TP + RSI ────────────────────────────────

def run_champion_backtest(df: pd.DataFrame) -> dict:
    """deep_optimizer 冠军配置"""
    short, long_ = 12, 28
    sl, tp, trail = 0.03, 0.08, True
    rsi_period, ob, os_ = 21, 65, 40
    C = df['close']

    MA_S = C.rolling(short).mean()
    MA_L = C.rolling(long_).mean()

    delta   = C - C.shift(1)
    gain    = delta.clip(lower=0)
    loss    = (-delta).clip(lower=0)
    avg_g   = gain.ewm(com=rsi_period - 1, adjust=False).mean()
    avg_l   = loss.ewm(com=rsi_period - 1, adjust=False).mean()
    rsi     = 100 - 100 / (1 + avg_g / (avg_l + 1e-9))

    n     = len(C)
    close = C.values
    mas   = MA_S.values
    mal   = MA_L.values
    rsi_v = rsi.values

    cash       = INITIAL_CAPITAL
    position   = 0.0
    entry_p    = 0.0
    trail_peak = 0.0
    portfolio  = []
    trades     = []

    for i in range(n):
        p   = close[i]
        val = cash + position * p
        portfolio.append(val)

        if np.isnan(mas[i]) or np.isnan(mal[i]) or np.isnan(rsi_v[i]):
            continue

        if position > 0:
            if trail:
                trail_peak = max(trail_peak, p)
                stopped    = p < trail_peak * (1 - sl)
            else:
                stopped    = p < entry_p * (1 - sl)
            taken_profit = p > entry_p * (1 + tp)

            if stopped or taken_profit or (mas[i] < mal[i]):
                pnl   = (p - entry_p) * position
                cash += position * p * (1 - COMMISSION)
                trades.append(pnl)
                position   = 0
                entry_p    = 0.0
                trail_peak = 0.0
        else:
            cross_up  = (mas[i] > mal[i]) and (i > 0 and mas[i - 1] <= mal[i - 1])
            rsi_ok    = os_ < rsi_v[i] < ob
            if cross_up and rsi_ok:
                qty        = cash * (1 - COMMISSION) / p
                cash      -= qty * p * (1 + COMMISSION)
                position   = qty
                entry_p    = p
                trail_peak = p

    final_val = cash + position * close[-1]
    portfolio = np.array(portfolio)
    ret       = (final_val - INITIAL_CAPITAL) / INITIAL_CAPITAL
    peak      = np.maximum.accumulate(portfolio)
    max_dd    = float(((portfolio - peak) / peak).min())
    daily_ret = pd.Series(portfolio).pct_change().dropna()
    sharpe    = (daily_ret.mean() / daily_ret.std() * np.sqrt(8760)
                 if daily_ret.std() > 0 else 0.0)
    wins      = [t for t in trades if t > 0]
    win_rate  = len(wins) / len(trades) if trades else 0.0

    return {
        'final_value': final_val,
        'return':      ret,
        'sharpe':      sharpe,
        'max_dd':      max_dd,
        'n_trades':    len(trades),
        'win_rate':    win_rate,
        'portfolio':   portfolio,
    }


def run_balanced_backtest(df: pd.DataFrame) -> dict:
    """向量化回测 BALANCED MOMENTUM"""
    sig, prob = compute_balanced_signals(df)
    close     = df['close'].values
    n         = len(close)

    cash     = INITIAL_CAPITAL
    position = 0.0
    entry_p  = 0.0
    portfolio = []
    trades    = []

    for i in range(n):
        p   = close[i]
        val = cash + position * p
        portfolio.append(val)
        s   = sig.iloc[i]

        if s == 1 and position == 0:
            qty        = cash * (1 - COMMISSION) / p
            cash      -= qty * p * (1 + COMMISSION)
            position   = qty
            entry_p    = p
        elif s == -1 and position > 0:
            pnl   = (p - entry_p) * position
            cash += position * p * (1 - COMMISSION)
            trades.append(pnl)
            position = 0

    final_val = cash + position * close[-1]
    portfolio = np.array(portfolio)
    ret       = (final_val - INITIAL_CAPITAL) / INITIAL_CAPITAL
    peak      = np.maximum.accumulate(portfolio)
    max_dd    = float(((portfolio - peak) / peak).min())
    daily_ret = pd.Series(portfolio).pct_change().dropna()
    sharpe    = (daily_ret.mean() / daily_ret.std() * np.sqrt(8760)
                 if daily_ret.std() > 0 else 0.0)
    wins      = [t for t in trades if t > 0]
    win_rate  = len(wins) / len(trades) if trades else 0.0

    return {
        'final_value': final_val,
        'return':      ret,
        'sharpe':      sharpe,
        'max_dd':      max_dd,
        'n_trades':    len(trades),
        'win_rate':    win_rate,
        'portfolio':   portfolio,
        'prob':        prob,
    }


# ── 主程序 ────────────────────────────────────────────────────────────────────

def print_result(name: str, r: dict):
    print(f"\n{'─'*50}")
    print(f"  {name}")
    print(f"{'─'*50}")
    print(f"  收益率  : {r['return']:+.2%}")
    print(f"  Sharpe  : {r['sharpe']:.2f}")
    print(f"  最大回撤: {r['max_dd']:.2%}")
    print(f"  交易次数: {r['n_trades']}")
    print(f"  胜率    : {r['win_rate']:.1%}")
    print(f"  最终权益: ${r['final_value']:,.2f}")


def main():
    print("=" * 60)
    print("  TDX 策略回测  (BTCUSDT 1h)")
    print("=" * 60)

    print("\n加载数据...")
    df = load_data()
    print(f"  {len(df)} bars  ({df.index[0].date()} → {df.index[-1].date()})")

    print("\n运行回测中...")

    r_dna      = run_dna_backtest(df)
    r_balanced = run_balanced_backtest(df)
    r_champion = run_champion_backtest(df)

    print_result("DNA副图策略  (SL=9.7% TP=24.4% 超期44bar)", r_dna)
    print_result("BALANCED MOMENTUM 多因子主图",               r_balanced)
    print_result("冠军基准  MA(12,28)+SL3%+TP8%+Trail+RSI(21)", r_champion)

    # ── 对比汇总 ──
    results = {
        'DNA副图':           r_dna,
        'Balanced Momentum': r_balanced,
        '冠军基准':           r_champion,
    }
    print("\n\n" + "=" * 60)
    print("  策略排名  (按 Sharpe)")
    print("=" * 60)
    print(f"  {'策略':<22} {'收益':>8} {'Sharpe':>8} {'最大回撤':>10} {'交易':>6} {'胜率':>7}")
    print(f"  {'─'*60}")
    for name, r in sorted(results.items(), key=lambda x: x[1]['sharpe'], reverse=True):
        print(f"  {name:<22} {r['return']:>+8.2%} {r['sharpe']:>8.2f} "
              f"{r['max_dd']:>10.2%} {r['n_trades']:>6} {r['win_rate']:>7.1%}")

    # ── 权益曲线 ──
    fig, axes = plt.subplots(2, 1, figsize=(14, 10))
    colors = {'DNA副图': '#e74c3c', 'Balanced Momentum': '#3498db', '冠军基准': '#2ecc71'}
    ax = axes[0]
    for name, r in results.items():
        pf = pd.Series(r['portfolio'], index=df.index[:len(r['portfolio'])])
        ax.plot(pf.index, pf.values, label=name, color=colors[name], linewidth=1.5)
    ax.set_title(f'权益曲线对比  —  {SYMBOL} {INTERVAL}', fontsize=13)
    ax.set_ylabel('权益 (USDT)')
    ax.legend()
    ax.grid(alpha=0.3)

    # BALANCED 概率线
    ax2 = axes[1]
    ax2.plot(df.index, r_balanced['prob'].values, color='#3498db', linewidth=1, label='BAL_SIGNAL')
    ax2.axhline(0.6, color='red',   linestyle='--', alpha=0.7, label='买入线 0.6')
    ax2.axhline(0.4, color='green', linestyle='--', alpha=0.7, label='卖出线 0.4')
    ax2.set_title('BALANCED 综合概率信号')
    ax2.set_ylabel('买入概率')
    ax2.legend()
    ax2.grid(alpha=0.3)

    plt.tight_layout()
    Path('plots').mkdir(exist_ok=True)
    out = 'plots/tdx_strategy_compare.png'
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"\n  图表已保存 → {out}")
    print("=" * 60)


if __name__ == '__main__':
    main()
