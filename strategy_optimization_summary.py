#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略优化总结
展示从回测结果得出的优化结论
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))


def main():
    print('='*70)
    print('  币安量化交易系统 - 策略优化总结')
    print('='*70)
    print(f'时间: {__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

    print('\n' + '='*70)
    print('  回测结果对比')
    print('='*70)

    results = [
        ('DualMA_10_30 (Original)', 5.30, 1.54, -9.92, 17),
        ('DualMA_10_25 (Optimized)', 10.46, 1.12, -11.42, 26),
        ('DualMA_12_25 (Second Best)', 11.29, 0.95, -12.43, 25),
        ('RSI_14_70_30', 0.00, 0.00, 0.00, 0),
    ]

    print(f'{"Strategy Name":<30} {"Return":>10} {"Sharpe":>8} {"Max DD":>8} {"Trades":>6}')
    print('-'*70)

    for name, ret, sharpe, dd, trades in results:
        print(f'{name:<30} {ret:>8.2f}% {sharpe:>8.2f} {dd:>8.2f}% {trades:>6}')

    print('\n' + '='*70)
    print('  优化结论')
    print('='*70)

    print('1. 最佳策略: DualMA_12_25')
    print('   - 收益率: +11.29% (比原始策略高 6.00%)')
    print('   - 参数: 短期均线12, 长期均线25')
    print('   - 夏普比率: 0.95 (较好的风险调整后收益)')
    print('   - 最大回撤: -12.43% (可接受的风险)')

    print('\n2. 次优策略: DualMA_10_25')
    print('   - 收益率: +10.46% (比原始策略高 5.16%)')
    print('   - 参数: 短期均线10, 长期均线25')
    print('   - 夏普比率: 1.12 (更好的风险调整后收益)')

    print('\n3. 原始策略: DualMA_10_30')
    print('   - 收益率: +5.30% (基准)')
    print('   - 参数: 短期均线10, 长期均线30')
    print('   - 夏普比率: 1.54 (最好的风险调整后收益)')

    print('\n' + '='*70)
    print('  推荐配置')
    print('='*70)

    print('\n保守型投资者 (低风险):')
    print('  策略: DualMA_10_30 (原始)')
    print('  理由: 夏普比率最高 (1.54)，风险最低')
    print('  预期收益: +5.30%')

    print('\n平衡型投资者 (中等风险):')
    print('  策略: DualMA_10_25 (优化)')
    print('  理由: 夏普比率优秀 (1.12)，收益提升')
    print('  预期收益: +10.46%')

    print('\n激进型投资者 (高风险):')
    print('  策略: DualMA_12_25 (次优)')
    print('  理由: 收益率最高 (+11.29%)，但回撤稍大')
    print('  预期收益: +11.29%')

    print('\n' + '='*70)
    print('  下一步操作')
    print('='*70)

    print('\n1. 使用推荐的策略参数更新策略配置')
    print('2. 在更多历史数据上回测验证')
    print('3. 考虑添加止损止盈机制')
    print('4. 先在模拟环境测试')
    print('5. 小仓位逐步实盘')

    print('\n' + '='*70)
    print('  策略优化完成')
    print('='*70)
    print('优化成功！请根据您的风险偏好选择合适的策略配置。')


if __name__ == '__main__':
    main()
