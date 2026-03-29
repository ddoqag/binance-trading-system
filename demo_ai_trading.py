#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI驱动的量化交易系统演示
"""

import sys
import pandas as pd
import logging
from pathlib import Path

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger('DemoAITrading')


def demo_market_analysis():
    """演示市场分析功能"""
    print("\n" + "="*60)
    print("演示 1: 市场分析器")
    print("="*60)

    try:
        from ai_trading.market_analyzer import MarketAnalyzer, TrendType, MarketRegime

        # 创建市场分析器（不使用AI模型，仅规则分析）
        analyzer = MarketAnalyzer()

        # 生成模拟市场数据
        import numpy as np
        np.random.seed(42)
        dates = pd.date_range(start='2024-01-01', periods=100, freq='1h')
        base_price = 45000
        price_changes = np.random.normal(0, 0.005, 100)
        prices = base_price * (1 + price_changes).cumprod()
        volumes = np.random.randint(10000, 50000, 100)

        df = pd.DataFrame({
            'open': prices * (1 - np.random.normal(0, 0.001, 100)),
            'high': prices * (1 + np.random.normal(0, 0.002, 100)),
            'low': prices * (1 - np.random.normal(0, 0.002, 100)),
            'close': prices,
            'volume': volumes
        }, index=dates)

        print(f"\n生成模拟数据: {len(df)} 条K线")
        print(f"价格范围: ${df['low'].min():.2f} - ${df['high'].max():.2f}")

        # 分析趋势
        analysis = analyzer.analyze_trend(df)

        print(f"\n市场分析结果:")
        print(f"  趋势类型: {analysis['trend'].value}")
        print(f"  市场状态: {analysis['regime'].value}")
        print(f"  置信度: {analysis['confidence']:.2f}")
        print(f"  当前价格: ${analysis['current_price']:.2f}")
        print(f"  波动率: {analysis['volatility']:.4f}")
        print(f"  支撑位: ${analysis['support_level']:.2f}")
        print(f"  阻力位: ${analysis['resistance_level']:.2f}")

        # 获取适合的策略
        strategies = analyzer.get_suitable_strategies(analysis)
        print(f"\n适合的策略: {strategies}")

        return True

    except Exception as e:
        logger.error(f"市场分析演示失败: {e}")
        return False


def demo_strategy_matching():
    """演示策略匹配功能"""
    print("\n" + "="*60)
    print("演示 2: 策略匹配器")
    print("="*60)

    try:
        from ai_trading.market_analyzer import TrendType, MarketRegime
        from ai_trading.strategy_matcher import StrategyMatcher, StrategyConfig

        # 创建策略匹配器
        matcher = StrategyMatcher()

        # 显示所有可用策略
        all_strategies = matcher.get_all_strategies()
        print(f"\n已注册的策略 ({len(all_strategies)}):")
        for name, config in all_strategies.items():
            print(f"  - {name}: {config.description}")
            print(f"    优先级: {config.priority.value}")
            print(f"    适合趋势: {[t.value for t in config.suitable_trends]}")
            print()

        # 测试不同市场状态下的策略匹配
        test_cases = [
            ("上涨趋势", TrendType.UPTREND, MarketRegime.BULL, 0.8),
            ("下跌趋势", TrendType.DOWNTREND, MarketRegime.BEAR, 0.75),
            ("震荡市场", TrendType.SIDEWAYS, MarketRegime.NEUTRAL, 0.6),
            ("高波动市场", TrendType.VOLATILE, MarketRegime.HIGH_VOLATILITY, 0.55),
        ]

        for name, trend, regime, confidence in test_cases:
            trend_analysis = {
                'trend': trend,
                'regime': regime,
                'confidence': confidence
            }

            matched = matcher.match_strategies(trend_analysis, max_strategies=2)
            print(f"\n{name}:")
            for config in matched:
                print(f"  - {config.name}")

        # 测试最优策略选择
        print(f"\n最优策略选择:")
        for name, trend, regime, confidence in test_cases[:2]:
            trend_analysis = {
                'trend': trend,
                'regime': regime,
                'confidence': confidence
            }
            best = matcher.select_best_strategy(trend_analysis)
            print(f"  {name} -> {best.name}")

        return True

    except Exception as e:
        logger.error(f"策略匹配演示失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def demo_ai_trading_system():
    """演示AI交易系统"""
    print("\n" + "="*60)
    print("演示 3: AI交易系统 (规则版)")
    print("="*60)

    try:
        from ai_trading.ai_trading_system import AITradingSystem

        # 创建配置（不使用AI模型，使用规则）
        config = {
            'symbol': 'BTCUSDT',
            'interval': '1h',
            'initial_capital': 10000,
            'paper_trading': True,
            'model_path': None  # 不加载模型
        }

        print(f"\n配置:")
        for k, v in config.items():
            print(f"  {k}: {v}")

        # 创建AI交易系统
        system = AITradingSystem(config)

        # 生成模拟数据
        print(f"\n生成模拟数据...")
        import numpy as np
        np.random.seed(123)
        dates = pd.date_range(start='2024-01-01', periods=300, freq='1h')
        base_price = 45000
        # 创建有趋势的价格
        trend = np.linspace(0, 0.1, 300)  # 上涨10%
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

        print(f"模拟数据: {len(df)} 条K线")
        print(f"价格: ${df['close'].iloc[0]:.2f} -> ${df['close'].iloc[-1]:.2f}")
        print(f"变化: {(df['close'].iloc[-1] / df['close'].iloc[0] - 1)*100:.2f}%")

        # 分析市场
        print(f"\n分析市场...")
        trend_analysis = system.analyze_market(df)
        print(f"  趋势: {trend_analysis['trend'].value}")
        print(f"  状态: {trend_analysis['regime'].value}")
        print(f"  置信度: {trend_analysis['confidence']:.2f}")

        # 选择策略
        print(f"\n选择策略...")
        strategy = system.select_and_apply_strategy(trend_analysis)
        print(f"  策略: {strategy.name}")

        # 生成信号
        print(f"\n生成交易信号...")
        df_signals = system.generate_signals(df)
        signal_counts = df_signals['signal'].value_counts()
        print(f"  信号统计:")
        for s, c in signal_counts.items():
            print(f"    {s}: {c} 次")

        # 运行回测
        print(f"\n运行回测...")
        results = system.run_backtest(df, initial_capital=10000)
        print(f"  初始资金: ${results['initial_capital']:.2f}")
        print(f"  最终资金: ${results['final_value']:.2f}")
        print(f"  总收益: {results['total_return']*100:.2f}%")
        print(f"  交易次数: {results['total_trades']}")

        return True

    except Exception as e:
        logger.error(f"AI交易系统演示失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主函数"""
    print("="*60)
    print("AI驱动的量化交易系统 - 演示程序")
    print("="*60)

    success = 0
    total = 0

    # 演示1: 市场分析
    total += 1
    if demo_market_analysis():
        success += 1

    # 演示2: 策略匹配
    total += 1
    if demo_strategy_matching():
        success += 1

    # 演示3: AI交易系统
    total += 1
    if demo_ai_trading_system():
        success += 1

    # 总结
    print("\n" + "="*60)
    print("演示总结")
    print("="*60)
    print(f"成功: {success}/{total}")

    if success == total:
        print("\n所有演示成功!")
        print("\n下一步:")
        print("1. 确保Qwen3-8B模型下载完成")
        print("2. 配置数据库连接")
        print("3. 获取真实市场数据")
        print("4. 运行完整回测")
        print("5. 配置实盘交易参数")
    else:
        print(f"\n{total - success} 个演示失败，请检查错误信息")

    return success == total


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n演示被用户中断")
        sys.exit(1)
