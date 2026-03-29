#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统演示脚本
"""

import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from core.system import TradingSystem


def setup_logging():
    """设置日志"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler()
        ]
    )


def generate_sample_data():
    """生成示例市场数据"""
    np.random.seed(42)
    periods = 100
    start_price = 45000
    dates = pd.date_range(start=datetime.now() - timedelta(hours=periods),
                         periods=periods, freq='h')
    returns = np.random.normal(0, 0.02, periods)
    prices = start_price * (1 + returns).cumprod()

    df = pd.DataFrame({
        'timestamp': dates,
        'open': prices,
        'high': prices * (1 + np.random.normal(0, 0.005, periods)),
        'low': prices * (1 - np.random.normal(0, 0.005, periods)),
        'close': prices,
        'volume': np.random.randint(10000, 50000, periods)
    }).set_index('timestamp')

    return df


def main():
    """主函数"""
    setup_logging()

    print("=" * 60)
    print("Qwen3.5-7B 驱动的 AI 交易系统演示")
    print("=" * 60)
    print()

    # 初始化系统
    system = TradingSystem()
    print("1. 初始化系统")
    system.initialize()
    print("[OK] 系统初始化成功")
    print()

    # 启动系统
    print("2. 启动系统")
    system.start()
    print("[OK] 系统启动成功")
    print()

    # 生成模拟数据
    print("3. 生成模拟市场数据")
    market_data = generate_sample_data()
    print(f"[OK] 生成 {len(market_data)} 条数据")
    print(f"价格范围: ${market_data['close'].min():.2f} - ${market_data['close'].max():.2f}")
    print()

    # 运行一个交易周期
    print("4. 运行交易周期")
    result = system.run_single_cycle(market_data)
    print("[OK] 交易周期完成")
    print()

    # 输出结果
    print("5. 输出结果")
    print(f"状态: {result['status']}")
    print()

    if result['trend_analysis']:
        print("趋势分析:")
        analysis = result['trend_analysis']
        print(f"  趋势: {analysis['trend']}")
        print(f"  置信度: {analysis['confidence']:.2f}")
        print(f"  波动率: {analysis['volatility']:.2%}")
        print()

    if result['matched_strategies']:
        print("策略匹配:")
        strategies = result['matched_strategies']
        for strat in strategies:
            print(f"  {strat['name']} ({strat['score']:.2f})")
        print()

    print("6. 停止系统")
    system.stop()
    print("[OK] 系统停止")
    print()

    print("=" * 60)
    print("系统演示完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
