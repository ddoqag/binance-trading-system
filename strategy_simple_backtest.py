#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单策略回测 - 直接从 JSON 文件读取数据
不依赖数据库
"""

import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import datetime
import sys

# 设置 matplotlib 后端
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def load_data_from_json(filepath: str) -> pd.DataFrame:
    """
    从 JSON 文件加载 K 线数据

    Args:
        filepath: JSON 文件路径

    Returns:
        K线 DataFrame
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 币安 K线数据格式:
    # [
    #   [
    #     1499040000000,      // 开盘时间
    #     "0.01634790",       // 开盘价
    #     "0.80000000",       // 最高价
    #     "0.01575800",       // 最低价
    #     "0.01577100",       // 收盘价
    #     "148976.11427915",  // 成交量
    #     1499644799999,      // 收盘时间
    #     "2434.19055334",    // 成交额
    #     308,                // 成交笔数
    #     "1756.87402397",    // 主动买入成交量
    #     "28.46694368",      // 主动买入成交额
    #     "17928899.62484339" // 忽略
    #   ]
    # ]

    df = pd.DataFrame(data, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades', 'taker_buy_base',
        'taker_buy_quote', 'ignore'
    ])

    # 转换时间戳
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    df.set_index('open_time', inplace=True)

    # 转换数值列
    numeric_cols = ['open', 'high', 'low', 'close', 'volume']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    return df


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


def run_backtest(df: pd.DataFrame, strategy,
                 initial_capital: float = 10000,
                 commission: float = 0.001) -> dict:
    """
    运行回测

    Args:
        df: K线数据
        strategy: 策略实例
        initial_capital: 初始资金
        commission: 手续费率

    Returns:
        回测结果字典
    """
    df_signals = strategy.generate_signals(df)

    cash = initial_capital
    position = 0
    entry_price = 0
    trades = []
    portfolio_history = []

    for i in range(len(df_signals)):
        date = df_signals.index[i]
        price = df_signals['close'].iloc[i]
        signal = df_signals['signal'].iloc[i]

        # 记录组合价值
        current_value = cash + position * price
        portfolio_history.append({
            'date': date,
            'price': price,
            'cash': cash,
            'position': position,
            'total_value': current_value
        })

        # 交易逻辑
        if signal == 1 and position == 0:
            # 买入
            shares = cash * (1 - commission) / price
            cost = shares * price
            comm_fee = cost * commission
            cash -= (cost + comm_fee)
            position = shares
            entry_price = price
            trades.append({
                'date': date,
                'action': 'BUY',
                'price': price,
                'shares': shares
            })

        elif signal == -1 and position > 0:
            # 卖出
            revenue = position * price
            comm_fee = revenue * commission
            cash += (revenue - comm_fee)
            trades.append({
                'date': date,
                'action': 'SELL',
                'price': price,
                'shares': position,
                'pnl': (price - entry_price) * position
            })
            position = 0

    # 计算最终结果
    final_value = cash + position * df_signals['close'].iloc[-1]
    total_return = (final_value - initial_capital) / initial_capital

    # 计算指标
    portfolio_df = pd.DataFrame(portfolio_history).set_index('date')
    returns = portfolio_df['total_value'].pct_change().dropna()

    if len(returns) > 0:
        annual_return = (1 + total_return) ** (365 * 24 / len(df_signals)) - 1
        sharpe = np.sqrt(365 * 24) * returns.mean() / returns.std() if returns.std() > 0 else 0
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        max_dd = drawdown.min()
    else:
        annual_return = 0
        sharpe = 0
        max_dd = 0

    results = {
        'strategy': strategy.name,
        'initial_capital': initial_capital,
        'final_value': final_value,
        'total_return': total_return,
        'annual_return': annual_return,
        'sharpe_ratio': sharpe,
        'max_drawdown': max_dd,
        'total_trades': len(trades) // 2,
        'trades': trades,
        'portfolio_df': portfolio_df,
        'signals_df': df_signals
    }

    return results


def plot_results(results: dict, symbol: str, output_dir: str = 'plots'):
    """绘制回测结果"""
    Path(output_dir).mkdir(exist_ok=True)

    portfolio_df = results['portfolio_df']
    df_signals = results['signals_df']

    fig, axes = plt.subplots(3, 1, figsize=(14, 12))

    # 1. 价格和均线
    ax1 = axes[0]
    ax1.plot(df_signals.index, df_signals['close'], label='Price', alpha=0.7, linewidth=1)
    if 'ma_short' in df_signals.columns:
        ax1.plot(df_signals.index, df_signals['ma_short'],
                label='MA Short', alpha=0.8, linewidth=1.5)
        ax1.plot(df_signals.index, df_signals['ma_long'],
                label='MA Long', alpha=0.8, linewidth=1.5)

    # 标记买卖点
    buy_points = df_signals[df_signals['position_change'] == 2]
    sell_points = df_signals[df_signals['position_change'] == -2]
    if len(buy_points) > 0:
        ax1.scatter(buy_points.index, buy_points['close'],
                   marker='^', color='green', s=100, zorder=5, label='Buy')
    if len(sell_points) > 0:
        ax1.scatter(sell_points.index, sell_points['close'],
                   marker='v', color='red', s=100, zorder=5, label='Sell')

    ax1.set_title(f'{symbol} - Price & Signals ({results["strategy"]})',
                 fontsize=12, fontweight='bold')
    ax1.set_ylabel('Price')
    ax1.legend(loc='best')
    ax1.grid(True, alpha=0.3)

    # 2. 组合价值
    ax2 = axes[1]
    ax2.plot(portfolio_df.index, portfolio_df['total_value'],
            label='Portfolio Value', color='green', linewidth=2)
    ax2.axhline(y=results['initial_capital'],
               color='red', linestyle='--', label='Initial Capital')
    ax2.set_title(f'Portfolio Performance - Return: {results["total_return"]*100:.2f}%',
                 fontsize=12, fontweight='bold')
    ax2.set_ylabel('Value (USDT)')
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    # 3. 回撤
    ax3 = axes[2]
    returns = portfolio_df['total_value'].pct_change().dropna()
    if len(returns) > 0:
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        ax3.fill_between(drawdown.index, drawdown, 0,
                        color='red', alpha=0.5, label='Drawdown')
        ax3.axhline(y=results['max_drawdown'],
                   color='darkred', linestyle='--',
                   label=f'Max DD: {results["max_drawdown"]*100:.2f}%')
    ax3.set_title('Drawdown Analysis', fontsize=12, fontweight='bold')
    ax3.set_ylabel('Drawdown')
    ax3.set_xlabel('Time')
    ax3.legend()
    ax3.grid(True, alpha=0.3)

    plt.tight_layout()
    filename = f'{output_dir}/backtest_{symbol}_{results["strategy"]}.png'
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    plt.close()
    return filename


def print_results(results: dict, symbol: str):
    """打印回测结果"""
    print("\n" + "="*60)
    print(f"BACKTEST RESULTS - {symbol} - {results['strategy']}")
    print("="*60)
    print(f"Initial Capital:  ${results['initial_capital']:,.2f}")
    print(f"Final Value:      ${results['final_value']:,.2f}")
    print(f"Total Return:     {results['total_return']*100:+.2f}%")
    print(f"Annual Return:    {results['annual_return']*100:+.2f}%")
    print(f"Sharpe Ratio:     {results['sharpe_ratio']:.2f}")
    print(f"Max Drawdown:     {results['max_drawdown']*100:.2f}%")
    print(f"Total Trades:     {results['total_trades']}")
    print("="*60)


def find_data_file(symbol: str, interval: str, data_dir: str = 'data') -> str:
    """查找数据文件"""
    data_path = Path(data_dir)
    files = list(data_path.glob(f"{symbol}-{interval}-*.json"))
    if files:
        return str(files[0])
    return None


def main():
    """主函数"""
    print("="*60)
    print("币安量化交易 - 简单策略回测")
    print("="*60)

    # 配置
    SYMBOL = 'BTCUSDT'
    INTERVAL = '1h'
    INITIAL_CAPITAL = 10000
    COMMISSION = 0.001
    SHORT_WINDOW = 10
    LONG_WINDOW = 30

    # 查找数据文件
    print(f"\n[1/4] 查找数据文件: {SYMBOL} {INTERVAL}")
    data_file = find_data_file(SYMBOL, INTERVAL)
    if not data_file:
        print(f"  错误: 找不到数据文件 {SYMBOL}-{INTERVAL}")
        # 尝试列出可用文件
        data_path = Path('data')
        if data_path.exists():
            print("\n可用的数据文件:")
            for f in sorted(data_path.glob("*.json"))[:10]:
                print(f"  - {f.name}")
        return

    print(f"  找到文件: {data_file}")

    # 加载数据
    print("\n[2/4] 加载数据...")
    df = load_data_from_json(data_file)
    print(f"  数据行数: {len(df)}")
    print(f"  时间范围: {df.index[0]} ~ {df.index[-1]}")
    print(f"  价格范围: {df['low'].min():.2f} ~ {df['high'].max():.2f}")

    # 创建策略
    print(f"\n[3/4] 创建策略: DualMA({SHORT_WINDOW}, {LONG_WINDOW})")
    strategy = DualMAStrategy(short_window=SHORT_WINDOW, long_window=LONG_WINDOW)

    # 运行回测
    print("\n[4/4] 运行回测...")
    results = run_backtest(df, strategy, initial_capital=INITIAL_CAPITAL, commission=COMMISSION)

    # 打印结果
    print_results(results, SYMBOL)

    # 绘制图表
    print("\n生成图表...")
    plot_file = plot_results(results, SYMBOL)
    print(f"  图表已保存: {plot_file}")

    # 打印交易记录
    if results['trades']:
        print("\n交易记录 (前5笔):")
        for i, trade in enumerate(results['trades'][:10]):
            print(f"  {i+1}. {trade['date']} {trade['action']} @ {trade['price']:.2f}")

    print("\n" + "="*60)
    print("回测完成!")
    print("="*60)


if __name__ == '__main__':
    main()
