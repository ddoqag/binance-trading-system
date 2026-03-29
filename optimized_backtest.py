#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
优化后的策略回测
使用策略优化器找到的最佳参数进行回测
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime

from strategy.dual_ma import DualMAStrategy
from strategy.rsi_strategy import RSIStrategy
from risk.manager import RiskManager, RiskConfig


def load_data():
    """加载数据"""
    print('='*70)
    print('  优化策略回测 - 加载数据')
    print('='*70)

    json_file = Path('data/BTCUSDT-1h-2026-03-20.json')
    if json_file.exists():
        import json
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        df = pd.DataFrame(data)
        df['datetime'] = pd.to_datetime(df['openTime'])
        df.set_index('datetime', inplace=True)
        print(f'✓ 加载数据: {len(df)} 条')
        print(f'  时间范围: {df.index.min()} ~ {df.index.max()}')
        print(f'  价格范围: ${df["low"].min():.2f} ~ ${df["high"].max():.2f}')
        return df
    else:
        print('⚠️ 未找到数据文件，生成模拟数据')
        np.random.seed(42)
        n_points = 500
        base_time = datetime.now() - pd.Timedelta(hours=n_points)
        timestamps = [base_time + pd.Timedelta(hours=i) for i in range(n_points)]

        base_price = 70000
        returns = np.random.normal(0.0001, 0.005, n_points)
        prices = base_price * np.cumprod(1 + returns)

        df = pd.DataFrame({
            'open': prices + np.random.normal(0, 100, n_points),
            'high': np.maximum(prices, prices) + np.random.normal(0, 200, n_points),
            'low': np.minimum(prices, prices) - np.random.normal(0, 200, n_points),
            'close': prices,
            'volume': np.random.randint(1000, 10000, n_points)
        }, index=timestamps)

        print(f'✓ 生成模拟数据: {len(df)} 条')
        return df


def backtest_strategy(df, strategy, risk_manager=None, name='Strategy'):
    """回测策略"""
    print(f'\n[回测策略: {name}]')

    # 生成信号
    df = strategy.generate_signals(df)

    # 初始化回测变量
    initial_capital = 10000.0
    cash = initial_capital
    position = 0.0
    equity_curve = []
    trades = []

    # 风险管理器
    if risk_manager is None:
        risk_config = RiskConfig(
            max_position_size=0.3,
            max_single_position=0.2,
            commission_rate=0.001,
            total_capital=initial_capital
        )
        risk_manager = RiskManager(risk_config)

    for i in range(len(df)):
        current_price = df['close'].iloc[i]
        timestamp = df.index[i]

        # 更新市场价格
        risk_manager.update_market_prices({df.name if hasattr(df, 'name') else 'BTCUSDT': current_price})

        # 计算当前权益
        current_equity = cash + position * current_price
        equity_curve.append({'timestamp': timestamp, 'equity': current_equity})

        # 检查交易信号
        position_change = df['position_change'].iloc[i]

        if position_change == 2:  # 金叉 - 买入
            quantity = (cash * 0.95) / current_price  # 95% 现金用于买入，保留手续费
            can_trade, reason = risk_manager.can_trade(
                'BTCUSDT', 'BUY', quantity, current_price
            )

            if can_trade:
                commission = quantity * current_price * risk_manager.config.commission_rate
                cash -= quantity * current_price + commission
                position += quantity

                risk_manager.on_trade_executed(
                    'BTCUSDT', 'BUY', quantity, current_price
                )

                trades.append({
                    'timestamp': timestamp,
                    'type': 'BUY',
                    'price': current_price,
                    'quantity': quantity,
                    'commission': commission
                })
                print(f'  [{timestamp}] BUY @ {current_price:.2f} x {quantity:.4f}')

        elif position_change == -2:  # 死叉 - 卖出
            if position > 0:
                can_trade, reason = risk_manager.can_trade(
                    'BTCUSDT', 'SELL', position, current_price
                )

                if can_trade:
                    commission = position * current_price * risk_manager.config.commission_rate
                    cash += position * current_price - commission

                    risk_manager.on_trade_executed(
                        'BTCUSDT', 'SELL', position, current_price
                    )

                    trades.append({
                        'timestamp': timestamp,
                        'type': 'SELL',
                        'price': current_price,
                        'quantity': position,
                        'commission': commission
                    })
                    print(f'  [{timestamp}] SELL @ {current_price:.2f} x {position:.4f}')
                    position = 0.0

    # 计算最终权益
    current_price = df['close'].iloc[-1]
    final_equity = cash + position * current_price
    total_return = (final_equity - initial_capital) / initial_capital * 100

    equity_df = pd.DataFrame(equity_curve)
    equity_df.set_index('timestamp', inplace=True)

    # 计算指标
    returns = equity_df['equity'].pct_change().dropna()
    annual_return = (1 + returns.mean()) ** (365 * 24) - 1 if len(returns) > 0 else 0
    sharpe_ratio = returns.mean() / returns.std() * np.sqrt(365 * 24) if len(returns) > 0 and returns.std() > 0 else 0
    max_drawdown = (equity_df['equity'].cummax() - equity_df['equity']).max() / equity_df['equity'].cummax().max() if len(equity_df) > 0 else 0

    # 打印结果
    print('-' * 70)
    print(f'回测结果 - {name}')
    print('-' * 70)
    print(f'初始资金:  ${initial_capital:,.2f}')
    print(f'最终价值:  ${final_equity:,.2f}')
    print(f'总收益率:  {total_return:+.2f}%')
    print(f'年化收益率: {annual_return*100:+.2f}%')
    print(f'夏普比率:  {sharpe_ratio:.2f}')
    print(f'最大回撤:  {-max_drawdown*100:.2f}%')
    print(f'交易次数:  {len(trades)}')

    return {
        'name': name,
        'initial_capital': initial_capital,
        'final_equity': final_equity,
        'total_return': total_return,
        'annual_return': annual_return,
        'sharpe_ratio': sharpe_ratio,
        'max_drawdown': max_drawdown,
        'trades': trades,
        'equity_curve': equity_df,
        'df': df
    }


def main():
    """主函数"""
    print('='*70)
    print('  优化策略回测')
    print('='*70)

    # 加载数据
    df = load_data()

    # 定义策略对比
    strategies = [
        {
            'name': 'DualMA_10_30 (原始)',
            'strategy': DualMAStrategy(short_window=10, long_window=30)
        },
        {
            'name': 'DualMA_10_25 (优化)',
            'strategy': DualMAStrategy(short_window=10, long_window=25)
        },
        {
            'name': 'DualMA_12_25 (次优)',
            'strategy': DualMAStrategy(short_window=12, long_window=25)
        },
        {
            'name': 'RSI_14_70_30',
            'strategy': RSIStrategy(rsi_period=14, rsi_overbought=70, rsi_oversold=30)
        }
    ]

    # 回测所有策略
    results = []
    for strat_config in strategies:
        result = backtest_strategy(df.copy(), strat_config['strategy'], name=strat_config['name'])
        results.append(result)

    # 对比结果
    print('\n' + '='*70)
    print('  策略对比总结')
    print('='*70)

    print(f'{"策略名称":<30} {"总收益":>10} {"夏普":>6} {"回撤":>8} {"交易":>5}')
    print('-'*70)

    for result in results:
        print(f'{result["name"]:<30} '
              f'{result["total_return"]:>+9.2f}% '
              f'{result["sharpe_ratio"]:>6.2f} '
              f'{-result["max_drawdown"]*100:>7.2f}% '
              f'{len(result["trades"]):>5}')

    # 找出最佳策略
    best_by_return = max(results, key=lambda x: x['total_return'])
    best_by_sharpe = max(results, key=lambda x: x['sharpe_ratio'])

    print('\n' + '='*70)
    print('  最佳策略')
    print('='*70)
    print(f'收益率最高: {best_by_return["name"]} (+{best_by_return["total_return"]:.2f}%)')
    print(f'夏普比率最高: {best_by_sharpe["name"]} ({best_by_sharpe["sharpe_ratio"]:.2f})')

    # 生成对比图
    print('\n生成对比图表...')
    fig, axes = plt.subplots(2, 1, figsize=(12, 10))

    # 权益曲线
    ax1 = axes[0]
    for result in results:
        ax1.plot(result['equity_curve'].index, result['equity_curve']['equity'],
                label=f'{result["name"]} (+{result["total_return"]:.1f}%)', linewidth=2)
    ax1.axhline(y=10000, color='gray', linestyle='--', label='初始资金')
    ax1.set_title('策略权益曲线对比', fontsize=14, fontweight='bold')
    ax1.set_ylabel('权益 ($)', fontsize=12)
    ax1.legend(loc='best', fontsize=10)
    ax1.grid(True, alpha=0.3)

    # 回撤对比
    ax2 = axes[1]
    for result in results:
        equity = result['equity_curve']['equity']
        cummax = equity.cummax()
        drawdown = (cummax - equity) / cummax
        ax2.plot(result['equity_curve'].index, -drawdown*100,
                label=f'{result["name"]} (-{result["max_drawdown"]*100:.1f}%)', linewidth=2)
    ax2.set_title('策略回撤对比', fontsize=14, fontweight='bold')
    ax2.set_ylabel('回撤 (%)', fontsize=12)
    ax2.legend(loc='best', fontsize=10)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plot_file = 'plots/optimized_strategies_comparison.png'
    Path('plots').mkdir(exist_ok=True)
    plt.savefig(plot_file, dpi=150, bbox_inches='tight')
    print(f'✓ 图表已保存: {plot_file}')

    print('\n' + '='*70)
    print('  优化回测完成！')
    print('='*70)
    print('\n建议：')
    print('1. 根据您的风险偏好选择合适的策略')
    print('2. 保守型投资者选择夏普比率高的策略')
    print('3. 激进型投资者可以选择收益率高的策略')
    print('4. 建议在实盘前进行更多历史数据回测')


if __name__ == '__main__':
    main()
