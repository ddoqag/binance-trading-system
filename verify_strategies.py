#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略验证脚本 - 对比多种规则策略的表现
"""

import pandas as pd
import numpy as np
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


class DualMAStrategy:
    """双均线策略"""
    def __init__(self, short_window: int = 10, long_window: int = 30):
        self.short_window = short_window
        self.long_window = long_window
        self.name = f"DualMA_{short_window}_{long_window}"

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['ma_short'] = df['close'].rolling(window=self.short_window).mean()
        df['ma_long'] = df['close'].rolling(window=self.long_window).mean()
        df['signal'] = 0
        df.loc[df['ma_short'] > df['ma_long'], 'signal'] = 1
        df.loc[df['ma_short'] < df['ma_long'], 'signal'] = -1
        df['position_change'] = df['signal'].diff()
        return df


class RSIStrategy:
    """RSI策略"""
    def __init__(self, period: int = 14, overbought: int = 70, oversold: int = 30):
        self.period = period
        self.overbought = overbought
        self.oversold = oversold
        self.name = f"RSI_{period}_{overbought}_{oversold}"

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.period).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        df['signal'] = 0
        df.loc[df['rsi'] < self.oversold, 'signal'] = 1
        df.loc[df['rsi'] > self.overbought, 'signal'] = -1
        df['position_change'] = df['signal'].diff()
        return df


class GridTradingStrategy:
    """网格交易策略"""
    def __init__(self, grid_size: float = 0.02, num_grids: int = 10):
        self.grid_size = grid_size
        self.num_grids = num_grids
        self.name = f"Grid_{grid_size:.0%}_{num_grids}"

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        base_price = df['close'].iloc[0]
        df['grid_level'] = np.floor((df['close'] - base_price) / (base_price * self.grid_size))
        df['signal'] = 0
        df['position_change'] = df['grid_level'].diff()
        df['signal'] = np.where(df['position_change'] > 0, 1,
                               np.where(df['position_change'] < 0, -1, 0))
        return df


def load_data(filepath: str) -> pd.DataFrame:
    """加载币安K线数据"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        df = pd.DataFrame(data, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ])
        df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
        df.set_index('open_time', inplace=True)
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        return df.dropna()
    except FileNotFoundError:
        print(f"❌ 数据文件 {filepath} 未找到")
        return pd.DataFrame()


def run_backtest(df: pd.DataFrame, strategy) -> dict:
    """回测引擎"""
    df_signals = strategy.generate_signals(df)

    cash = 10000
    position = 0
    trades = []
    portfolio_history = []

    for i in range(len(df_signals)):
        date = df_signals.index[i]
        price = df_signals['close'].iloc[i]
        signal = df_signals['signal'].iloc[i]

        current_value = cash + position * price
        portfolio_history.append({
            'date': date,
            'price': price,
            'cash': cash,
            'position': position,
            'total_value': current_value
        })

        if signal == 1 and position == 0:
            shares = cash * (1 - 0.001) / price
            cost = shares * price
            commission = cost * 0.001
            cash -= (cost + commission)
            position = shares
            trades.append({'date': date, 'action': 'BUY', 'price': price})
        elif signal == -1 and position > 0:
            revenue = position * price
            commission = revenue * 0.001
            cash += (revenue - commission)
            trades.append({'date': date, 'action': 'SELL', 'price': price})
            position = 0

    final_value = cash + position * df_signals['close'].iloc[-1]
    total_return = (final_value - 10000) / 10000

    portfolio_df = pd.DataFrame(portfolio_history).set_index('date')
    returns = portfolio_df['total_value'].pct_change().dropna()
    sharpe = np.sqrt(365*24) * returns.mean() / returns.std() if returns.std() > 0 else 0

    cumulative = (1 + returns).cumprod()
    running_max = cumulative.expanding().max()
    drawdown = (cumulative - running_max) / running_max
    max_dd = drawdown.min()

    return {
        'strategy': strategy.name,
        'initial_capital': 10000,
        'final_value': final_value,
        'total_return': total_return,
        'sharpe_ratio': sharpe,
        'max_drawdown': max_dd,
        'total_trades': len(trades) // 2
    }


def compare_strategies(df: pd.DataFrame):
    """对比多种策略"""
    strategies = [
        DualMAStrategy(10, 30),
        DualMAStrategy(5, 20),
        RSIStrategy(14, 70, 30),
        RSIStrategy(10, 65, 35),
        GridTradingStrategy(0.01, 15),
        GridTradingStrategy(0.02, 10)
    ]

    results = []
    for strategy in strategies:
        print(f"Running: {strategy.name}...", end='')
        try:
            result = run_backtest(df, strategy)
            results.append(result)
            print(f" Done")
        except Exception as e:
            print(f" Error: {e}")

    return pd.DataFrame(results)


def print_results_table(results_df):
    """打印结果表格"""
    print("\n" + "="*80)
    print(f"策略表现对比 ({len(results_df)}个策略)")
    print("="*80)
    print(results_df.to_string(
        formatters={
            'final_value': '${:,.2f}'.format,
            'total_return': '{:+.2%}'.format,
            'sharpe_ratio': '{:.2f}'.format,
            'max_drawdown': '{:.2%}'.format,
            'total_trades': '{:d}'.format
        },
        columns=['strategy', 'final_value', 'total_return', 'sharpe_ratio', 'max_drawdown', 'total_trades']
    ))
    print("="*80)


def plot_comparison(results_df, output_dir='plots'):
    """可视化对比"""
    Path(output_dir).mkdir(exist_ok=True)

    fig, axes = plt.subplots(2, 1, figsize=(12, 10))

    # 收益对比
    ax1 = axes[0]
    bars = ax1.bar(range(len(results_df)),
                   results_df['total_return'],
                   color=plt.cm.viridis(results_df['total_return'] / max(results_df['total_return'])))
    ax1.set_ylabel('Total Return (%)')
    ax1.set_title('Strategy Performance Comparison')
    ax1.set_xticks(range(len(results_df)))
    ax1.set_xticklabels([f"{i}\n{name}" for i, name in enumerate(results_df['strategy'])], rotation=45)
    ax1.grid(True, alpha=0.3)
    for i, v in enumerate(results_df['total_return']):
        ax1.text(i, v + 0.01, f"{v:.1%}", ha='center', va='bottom')

    # 夏普比率 vs 最大回撤
    ax2 = axes[1]
    scatter = ax2.scatter(results_df['sharpe_ratio'],
                        -results_df['max_drawdown'],
                        c=results_df['total_return'],
                        cmap='viridis', s=100)
    ax2.set_xlabel('Sharpe Ratio')
    ax2.set_ylabel('Max Drawdown (%)')
    ax2.set_title('Risk-Reward Analysis')
    ax2.grid(True, alpha=0.3)
    for i, (name, sharpe, dd, ret) in enumerate(zip(
        results_df['strategy'],
        results_df['sharpe_ratio'],
        results_df['max_drawdown'],
        results_df['total_return']
    )):
        ax2.text(sharpe + 0.02, -dd + 0.01,
                f"{name}\n{ret:.1%}",
                fontsize=8)

    plt.tight_layout()
    plt.colorbar(scatter, label='Total Return (%)')
    plt.savefig(f"{output_dir}/strategy_comparison.png", dpi=150, bbox_inches='tight')
    plt.close()
    print(f"图表已保存: {output_dir}/strategy_comparison.png")


def main():
    """主函数"""
    print("="*80)
    print("策略验证程序 (规则版)")
    print("="*80)

    # 数据准备
    data_file = "data/BTCUSDT-1h.json"
    if not Path(data_file).exists():
        print("❌ 数据文件不存在，请先运行 `npm run fetch`")
        return False

    print("Loading data...", end='')
    df = load_data(data_file)
    print(f" Done ({len(df)} bars)")

    # 策略对比
    print("\nRunning strategy comparisons...")
    results_df = compare_strategies(df)

    if len(results_df) == 0:
        print("❌ 所有策略回测失败")
        return False

    # 打印结果
    print_results_table(results_df)

    # 可视化
    plot_comparison(results_df)

    # 最佳策略
    best_sharpe = results_df.loc[results_df['sharpe_ratio'].idxmax()]
    best_return = results_df.loc[results_df['total_return'].idxmax()]
    best_risk = results_df.loc[results_df['max_drawdown'].idxmax()]

    print("\nTop Performers:")
    print(f"  Best Sharpe Ratio: {best_sharpe['strategy']} ({best_sharpe['sharpe_ratio']:.2f})")
    print(f"  Highest Return:    {best_return['strategy']} ({best_return['total_return']:.2%})")
    print(f"  Lowest Risk:       {best_risk['strategy']} ({best_risk['max_drawdown']:.2%})")

    return True


if __name__ == "__main__":
    import sys
    success = main()
    sys.exit(0 if success else 1)
