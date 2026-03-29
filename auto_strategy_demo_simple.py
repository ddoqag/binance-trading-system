#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略自动选择演示 - 简单版本
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


def demo_strategy_matcher():
    """演示策略匹配器"""
    print("\n" + "="*70)
    print("策略自动选择演示")
    print("="*70)

    try:
        from ai_trading.market_analyzer import TrendType, MarketRegime
        from ai_trading.strategy_matcher import StrategyMatcher

        matcher = StrategyMatcher()
        print(f"\n系统已加载 {len(matcher.get_all_strategies())} 个策略:")
        for name, config in matcher.get_all_strategies().items():
            print(f"  - {name}: {config.description}")

        print("\n" + "-"*70)
        print("策略自动匹配过程")
        print("-"*70)

        test_cases = [
            ("上涨趋势 (bull)", TrendType.UPTREND, MarketRegime.BULL, 0.85),
            ("下跌趋势 (bear)", TrendType.DOWNTREND, MarketRegime.BEAR, 0.75),
            ("震荡市场 (neutral)", TrendType.SIDEWAYS, MarketRegime.NEUTRAL, 0.65),
            ("高波动市场 (high_volatility)", TrendType.VOLATILE, MarketRegime.HIGH_VOLATILITY, 0.55),
        ]

        for name, trend, regime, confidence in test_cases:
            print(f"\n市场状态: {name}")
            print(f"  置信度: {confidence:.2f}")

            trend_analysis = {
                'trend': trend,
                'regime': regime,
                'confidence': confidence
            }

            matched = matcher.match_strategies(trend_analysis, max_strategies=3)
            print(f"  匹配策略数量: {len(matched)}")

            for i, config in enumerate(matched):
                print(f"  #{i+1}: {config.name}")
                print(f"      类型: {config.priority.value}")
                print(f"      描述: {config.description}")

            best_strategy = matcher.select_best_strategy(trend_analysis)
            print(f"  最佳策略: {best_strategy.name} (自动选择)")

        return True

    except Exception as e:
        logger.error(f"系统初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def demo_ai_trading_system():
    """演示AI交易系统"""
    print("\n" + "="*70)
    print("AI交易系统完整流程演示 (规则版)")
    print("="*70)

    try:
        from ai_trading.ai_trading_system import AITradingSystem

        config = {
            'symbol': 'BTCUSDT',
            'interval': '1h',
            'initial_capital': 10000,
            'paper_trading': True,
            'model_path': None
        }

        system = AITradingSystem(config)
        print("系统初始化成功")

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

        print(f"生成模拟数据: {len(df)} 条K线")

        trend_analysis = system.analyze_market(df)
        print(f"\n市场分析结果:")
        print(f"  趋势: {trend_analysis['trend'].value}")
        print(f"  状态: {trend_analysis['regime'].value}")
        print(f"  置信度: {trend_analysis['confidence']:.2f}")

        strategy = system.select_and_apply_strategy(trend_analysis)
        print(f"\n自动选择策略: {strategy.name}")

        df_signals = system.generate_signals(df)
        signal_counts = df_signals['signal'].value_counts()
        print(f"\n信号生成:")
        for s, c in signal_counts.items():
            print(f"  信号 {s}: {c} 次")

        results = system.run_backtest(df, initial_capital=10000)
        print(f"\n回测结果:")
        print(f"  初始资金: ${results['initial_capital']:.2f}")
        print(f"  最终资金: ${results['final_value']:.2f}")
        print(f"  总收益: {results['total_return']*100:.2f}%")
        print(f"  交易次数: {results['total_trades']}")

        return True

    except Exception as e:
        logger.error(f"系统运行失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    success = True
    success &= demo_strategy_matcher()

    if success:
        success &= demo_ai_trading_system()

    print("\n" + "="*70)
    print("演示总结")
    print("="*70)

    if success:
        print("系统自动策略选择功能运行正常")
        print("\n核心要点:")
        print("  - 系统会根据市场状态自动匹配最优策略")
        print("  - 策略匹配考虑：趋势类型、市场状态、置信度")
        print("  - 不需要手动选择，系统完全自动运行")
        print("\n下一步:")
        print("  1. 使用 npm run fetch 获取真实数据")
        print("  2. 运行 python strategy_simple_backtest.py 进行真实回测")
    else:
        print("演示过程中出现错误")

    return success


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
