#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试模块导入和基本功能
"""

import sys
from pathlib import Path

print("="*60)
print("测试币安量化交易系统模块")
print("="*60)

# 测试 1: 工具模块
print("\n[1/6] 测试 utils 模块...")
try:
    from utils.helpers import setup_logger, safe_float, get_timestamp
    from utils.database import DatabaseClient
    print("  ✓ utils.helpers 导入成功")
    print(f"  ✓ safe_float 测试: safe_float('123.45') = {safe_float('123.45')}")
    print("  ✓ utils.database 导入成功")
except Exception as e:
    print(f"  ✗ 失败: {e}")

# 测试 2: 交易模块
print("\n[2/6] 测试 trading 模块...")
try:
    from trading.order import Order, OrderType, OrderSide, OrderStatus
    from trading.execution import TradingExecutor
    print("  ✓ trading.order 导入成功")
    print("  ✓ trading.execution 导入成功")

    # 测试订单创建
    order = Order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        type=OrderType.MARKET,
        quantity=0.001
    )
    print(f"  ✓ Order 创建成功: {order.symbol} {order.side.value}")
except Exception as e:
    print(f"  ✗ 失败: {e}")

# 测试 3: 策略模块
print("\n[3/6] 测试 strategy 模块...")
try:
    from strategy.base import BaseStrategy
    from strategy.dual_ma import DualMAStrategy
    from strategy.rsi_strategy import RSIStrategy
    from strategy.ml_strategy import MLStrategy
    print("  ✓ strategy.base 导入成功")
    print("  ✓ strategy.dual_ma 导入成功")
    print("  ✓ strategy.rsi_strategy 导入成功")
    print("  ✓ strategy.ml_strategy 导入成功")

    # 测试策略创建
    strategy = DualMAStrategy(short_window=10, long_window=30)
    print(f"  ✓ DualMAStrategy 创建成功: {strategy.name}")
except Exception as e:
    print(f"  ✗ 失败: {e}")

# 测试 4: 风险控制模块
print("\n[4/6] 测试 risk 模块...")
try:
    from risk.manager import RiskManager, RiskConfig
    from risk.position import PositionManager
    from risk.stop_loss import StopLossManager, StopType
    print("  ✓ risk.manager 导入成功")
    print("  ✓ risk.position 导入成功")
    print("  ✓ risk.stop_loss 导入成功")

    # 测试风险配置
    config = RiskConfig(total_capital=10000)
    risk_manager = RiskManager(config)
    print(f"  ✓ RiskManager 创建成功, 总资金: {config.total_capital}")
except Exception as e:
    print(f"  ✗ 失败: {e}")

# 测试 5: ML 模型模块
print("\n[5/6] 测试 models 模块...")
try:
    from models.features import FeatureEngineer
    from models.predictor import PricePredictor
    from models.model_trainer import ModelTrainer
    print("  ✓ models.features 导入成功")
    print("  ✓ models.predictor 导入成功")
    print("  ✓ models.model_trainer 导入成功")

    # 测试特征工程
    fe = FeatureEngineer()
    print("  ✓ FeatureEngineer 创建成功")
except Exception as e:
    print(f"  ✗ 失败: {e}")

# 测试 6: 创建简单的 DataFrame 测试策略
print("\n[6/6] 测试策略信号生成...")
try:
    import pandas as pd
    import numpy as np

    # 创建模拟数据
    dates = pd.date_range(start='2024-01-01', periods=100, freq='1h')
    np.random.seed(42)
    prices = 50000 + np.cumsum(np.random.randn(100) * 100)

    df = pd.DataFrame({
        'open': prices,
        'high': prices + 50,
        'low': prices - 50,
        'close': prices,
        'volume': np.random.randint(1000, 10000, 100)
    }, index=dates)

    # 测试双均线策略
    from strategy.dual_ma import DualMAStrategy
    strategy = DualMAStrategy(short_window=5, long_window=20)
    signals = strategy.generate_signals(df)

    print(f"  ✓ 模拟数据创建成功: {len(df)} 行")
    print(f"  ✓ 信号生成成功:")
    print(f"    - 买入信号: {(signals['position_change'] == 2).sum()}")
    print(f"    - 卖出信号: {(signals['position_change'] == -2).sum()}")
    print(f"    - MA 短期平均值: {signals['ma_short'].mean():.2f}")
    print(f"    - MA 长期平均值: {signals['ma_long'].mean():.2f}")

except Exception as e:
    print(f"  ✗ 失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("模块测试完成!")
print("="*60)
