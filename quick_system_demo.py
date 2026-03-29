#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
币安量化交易系统快速演示
展示策略回测、优化和风险控制功能
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from strategy.dual_ma import DualMAStrategy
from config.settings import get_settings
from risk.manager import RiskManager, RiskConfig
from run_final_optimized_backtest_simple import load_real_data, calculate_backtest_statistics


def run_quick_demo():
    """快速演示"""
    print('='*70)
    print('  币安量化交易系统快速演示')
    print('='*70)
    print('时间:', pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'))

    # 1. 加载配置
    print('\n1. 加载系统配置')
    settings = get_settings()
    print(f'   - 策略类型: {settings.trading.strategy_type}')
    print(f'   - 参数配置: {settings.trading.short_window}/{settings.trading.long_window}')
    print(f'   - 佣金率: {settings.trading.commission_rate*100:.2f}%')
    print(f'   - 模拟交易: {settings.trading.paper_trading}')

    # 2. 加载数据
    print('\n2. 加载市场数据')
    df = load_real_data()
    if df is None:
        print('   ❌ 数据加载失败')
        return False

    # 3. 测试不同策略参数
    print('\n3. 策略参数对比测试')

    strategies = [
        ('DualMA_10_30', DualMAStrategy(10, 30)),
        ('DualMA_10_25', DualMAStrategy(10, 25)),
        ('DualMA_12_25', DualMAStrategy(12, 25)),
        ('DualMA_15_30', DualMAStrategy(15, 30)),
    ]

    results = []

    # 使用统一的风险配置
    risk_config = RiskConfig(
        max_position_size=0.8,
        max_single_position=0.5,
        max_daily_loss=0.10,
        max_trades_per_day=50,
        max_concurrent_trades=5,
        default_stop_loss_pct=0.0,
        default_take_profit_pct=0.0,
        total_capital=10000.0,
        commission_rate=0.001
    )

    for name, strategy in strategies:
        print(f'   - 测试策略: {name}')

        df_with_signals = strategy.generate_signals(df)
        equity_df = run_simple_backtest(df_with_signals, risk_config)
        stats = calculate_backtest_statistics(equity_df)

        initial = 10000.0
        final = equity_df['equity'].iloc[-1]
        total_return = (final - initial) / initial * 100

        results.append({
            'name': name,
            'return': total_return,
            'sharpe': stats['sharpe_ratio'],
            'max_dd': stats['max_drawdown'] * 100,
            'final': final,
            'equity_df': equity_df
        })

    # 4. 显示结果
    print('\n' + '='*70)
    print('  策略回测结果对比')
    print('='*70)
    print(f'{"策略":<15} {"收益率":>10} {"夏普比率":>10} {"最大回撤":>10} {"最终资金"}')
    print('-'*70)

    for result in results:
        print(f'{result["name"]:<15} {result["return"]:>8.2f}% {result["sharpe"]:>8.2f} '
              f'{result["max_dd"]:>8.2f}% ${result["final"]:.2f}')

    # 5. 生成可视化图表
    print('\n5. 生成可视化图表')
    generate_comparison_chart(df, results)

    # 6. 推荐策略
    print('\n6. 策略推荐')

    best_sharpe = max(results, key=lambda x: x['sharpe'])
    best_return = max(results, key=lambda x: x['return'])
    best_risk = min(results, key=lambda x: x['max_dd'])

    print(f'   - 最佳风险调整收益: {best_sharpe["name"]}')
    print(f'     夏普比率: {best_sharpe["sharpe"]:.2f}')
    print(f'   - 最高收益率: {best_return["name"]}')
    print(f'     收益率: {best_return["return"]:.2f}%')
    print(f'   - 最低风险: {best_risk["name"]}')
    print(f'     最大回撤: {best_risk["max_dd"]:.2f}%')

    return True


def run_simple_backtest(df, risk_config):
    """简化版回测逻辑"""
    initial_capital = 10000.0
    cash = initial_capital
    position = 0.0
    equity_history = []
    trade_count = 0

    commission_rate = risk_config.commission_rate

    for i in range(len(df)):
        row = df.iloc[i]
        current_price = row['close']
        timestamp = df.index[i]
        position_change = row['position_change']

        if position_change == 2 and position == 0:
            max_position_value = risk_config.total_capital * risk_config.max_single_position
            quantity = min((cash * 0.95) / current_price, max_position_value / current_price)

            if quantity > 0:
                commission = quantity * current_price * commission_rate
                cash -= quantity * current_price + commission
                position = quantity
                trade_count += 1

        elif position_change == -2 and position > 0:
            commission = position * current_price * commission_rate
            cash += position * current_price - commission
            position = 0.0
            trade_count += 1

        current_equity = cash + position * current_price
        equity_history.append({
            'timestamp': timestamp,
            'equity': current_equity,
            'cash': cash,
            'position': position,
            'price': current_price
        })

    equity_df = pd.DataFrame(equity_history)
    equity_df['timestamp'] = pd.to_datetime(equity_df['timestamp'])
    equity_df.set_index('timestamp', inplace=True)

    return equity_df


def generate_comparison_chart(df, results):
    """生成策略对比图表"""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10))

    # 价格走势
    ax1.plot(df.index, df['close'], label='BTCUSDT Price', color='blue', linewidth=2)
    ax1.set_ylabel('价格 (USD)')
    ax1.set_title('BTCUSDT价格与策略净值曲线对比')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)

    # 策略净值曲线
    for result in results:
        color = get_strategy_color(result['name'])
        ax2.plot(result['equity_df'].index,
                result['equity_df']['equity'],
                label=f'{result["name"]} ({result["return"]:.1f}%)',
                linewidth=2,
                alpha=0.8)

    ax2.set_ylabel('净值 (USD)')
    ax2.set_xlabel('时间')
    ax2.set_title('策略净值曲线对比')
    ax2.legend(loc='upper left', bbox_to_anchor=(0, -0.3), ncol=2)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig('plots/strategy_comparison.png', dpi=150, bbox_inches='tight')
    print(f'   Chart saved: plots/strategy_comparison.png')


def get_strategy_color(name):
    """获取策略颜色"""
    colors = {
        'DualMA_10_30': '#1f77b4',
        'DualMA_10_25': '#ff7f0e',
        'DualMA_12_25': '#2ca02c',
        'DualMA_15_30': '#d62728',
    }
    return colors.get(name, '#9467bd')


if __name__ == '__main__':
    success = run_quick_demo()

    if success:
        print('\n' + '='*70)
        print(' Demo Complete!')
        print('='*70)
        print(' Run the following commands for more info:')
        print('   - Strategy Summary: python strategy_optimization_summary.py')
        print('   - Full Backtest: python run_final_optimized_backtest.py')
        print('   - Project Docs: cat PROJECT_COMPLETION_SUMMARY.md')
    else:
        print('\n' + '='*70)
        print(' Demo Failed')
        print('='*70)
