#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略自动选择演示 - 展示系统如何自动匹配和选择最优策略
"""

import sys
import pandas as pd
import numpy as np
import logging
from pathlib import Path

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('AutoStrategyDemo')


def simulate_market_conditions():
    """模拟不同的市场条件"""
    conditions = [
        {
            'name': '上涨趋势',
            'trend': 'uptrend',
            'regime': 'bull',
            'confidence': 0.85,
            'description': '价格持续上涨，成交量放大，市场情绪积极'
        },
        {
            'name': '下跌趋势',
            'trend': 'downtrend',
            'regime': 'bear',
            'confidence': 0.75,
            'description': '价格持续下跌，成交量萎缩，市场情绪消极'
        },
        {
            'name': '震荡市场',
            'trend': 'sideways',
            'regime': 'neutral',
            'confidence': 0.65,
            'description': '价格在窄幅区间波动，无明显趋势'
        },
        {
            'name': '高波动市场',
            'trend': 'volatile',
            'regime': 'high_volatility',
            'confidence': 0.55,
            'description': '价格波动剧烈，成交量大，市场情绪不稳定'
        }
    ]

    return conditions


def auto_strategy_selection_demo():
    """演示自动策略选择"""
    print("\n" + "="*80)
    print("策略自动选择演示")
    print("="*80)

    try:
        from ai_trading.market_analyzer import TrendType, MarketRegime
        from ai_trading.strategy_matcher import StrategyMatcher

        # 创建策略匹配器
        matcher = StrategyMatcher()

        print(f"\n✅ 系统已加载 {len(matcher.get_all_strategies())} 个策略")
        for name, config in matcher.get_all_strategies().items():
            print(f"  - {name}: {config.description}")

        # 模拟不同的市场条件
        conditions = simulate_market_conditions()

        print("\n" + "-"*80)
        print("策略自动匹配过程")
        print("-"*80)

        for condition in conditions:
            print(f"\n📊 市场状态: {condition['name']}")
            print(f"  描述: {condition['description']}")
            print(f"  置信度: {condition['confidence']:.2f}")

            try:
                # 转换趋势类型
                trend = TrendType[condition['trend'].upper()]
                regime = MarketRegime[condition['regime'].upper()]

                # 模拟分析结果
                trend_analysis = {
                    'trend': trend,
                    'regime': regime,
                    'confidence': condition['confidence']
                }

                # 自动匹配策略
                matched = matcher.match_strategies(trend_analysis, max_strategies=3)

                print(f"  匹配策略数量: {len(matched)}")

                for i, config in enumerate(matched):
                    # 计算匹配分数
                    score = 0
                    if trend in config.suitable_trends:
                        score += 40
                    if regime in config.suitable_regimes:
                        score += 30
                    if config.priority.value == 'primary':
                        score += 20
                    elif config.priority.value == 'secondary':
                        score += 10
                    score *= condition['confidence']

                    print(f"  #{i+1}: {config.name}")
                    print(f"      类型: {config.priority.value}")
                    print(f"      匹配度: {score:.1f}分")
                    print(f"      描述: {config.description}")

                # 选择最佳策略
                best_strategy = matcher.select_best_strategy(trend_analysis)
                print(f"  最佳策略: {best_strategy.name} (自动选择)")

            except Exception as e:
                logger.error(f"  ❌ 处理 {condition['name']} 时出错: {e}")

        return True

    except Exception as e:
        logger.error(f"❌ 系统初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_system_demo():
    """运行完整系统演示"""
    print("\n" + "="*80)
    print("AI交易系统完整流程演示 (规则版)")
    print("="*80)

    try:
        from ai_trading.ai_trading_system import AITradingSystem

        config = {
            'symbol': 'BTCUSDT',
            'interval': '1h',
            'initial_capital': 10000,
            'paper_trading': True,
            'model_path': None  # 使用规则版
        }

        system = AITradingSystem(config)

        print("✅ 系统初始化成功")

        # 生成模拟数据
        np.random.seed(123)
        dates = pd.date_range(start='2024-01-01', periods=300, freq='1h')
        base_price = 45000
        trend = np.linspace(0, 0.1, 300)
        noise = np.random.normal(0, 0.005, 300)
        prices = base_price * (1 + trend + noise).cumprod()
        volumes = np.random.randint(10000, 50000, 300)

        df = pd.DataFrame({
            'open': prices * (1 - np.random.normal(0, 0.001, 300)),
            'high': prices * (1 + np.random.normal(0, 0.002, 300)),
            'low': prices * (1 - np.random.normal(0, 0.002, 300)),
            'close': prices,
            'volume': volumes
        }, index=dates)

        print(f"✅ 生成模拟数据: {len(df)} 条K线")

        # 分析市场（自动）
        trend_analysis = system.analyze_market(df)
        print(f"\n📈 市场分析结果:")
        print(f"  趋势: {trend_analysis['trend'].value}")
        print(f"  状态: {trend_analysis['regime'].value}")
        print(f"  置信度: {trend_analysis['confidence']:.2f}")

        # 自动选择策略
        strategy = system.select_and_apply_strategy(trend_analysis)
        print(f"\n🎯 自动选择策略: {strategy.name}")

        # 生成信号（自动）
        df_signals = system.generate_signals(df)
        signal_counts = df_signals['signal'].value_counts()
        print(f"\n🚦 信号生成:")
        for s, c in signal_counts.items():
            print(f"  信号 {s}: {c} 次")

        # 回测（自动）
        results = system.run_backtest(df, initial_capital=10000)
        print(f"\n📊 回测结果:")
        print(f"  初始资金: ${results['initial_capital']:.2f}")
        print(f"  最终资金: ${results['final_value']:.2f}")
        print(f"  总收益: {results['total_return']*100:.2f}%")
        print(f"  交易次数: {results['total_trades']}")

        return True

    except Exception as e:
        logger.error(f"❌ 系统运行失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主函数"""
    success = True

    # 1. 策略自动选择演示
    success &= auto_strategy_selection_demo()

    # 2. 完整系统演示
    if success:
        success &= run_system_demo()

    print("\n" + "="*80)
    print("演示总结")
    print("="*80)

    if success:
        print("✅ 系统自动策略选择功能运行正常")
        print("\n🎯 核心要点:")
        print("  - 系统会根据市场状态自动匹配最优策略")
        print("  - 策略匹配考虑：趋势类型、市场状态、置信度")
        print("  - 不需要手动选择，系统完全自动运行")
        print("  - 支持规则版和AI增强版两种模式")
        print("\n📚 下一步:")
        print("  1. 使用 npm run fetch 获取真实数据")
        print("  2. 运行 python strategy_simple_backtest.py 进行真实回测")
        print("  3. 根据需要调整策略参数")
    else:
        print("❌ 演示过程中出现错误")

    return success


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
