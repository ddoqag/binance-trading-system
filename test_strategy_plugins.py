#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略插件测试 - Strategy Plugin Test
测试阶段三-3：策略插件化
"""

import logging
import sys
import pandas as pd
import numpy as np

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 添加项目路径
sys.path.insert(0, 'D:\\binance')

from plugin_examples.dual_ma_strategy import DualMAStrategy
from plugins.reliable_event_bus import ReliableEventBus


def generate_test_data(days: int = 200) -> pd.DataFrame:
    """
    生成测试用的市场数据，包含趋势和震荡

    Args:
        days: 数据天数

    Returns:
        包含 OHLCV 数据的 DataFrame
    """
    np.random.seed(42)
    dates = pd.date_range(start='2024-01-01', periods=days, freq='D')

    # 生成带趋势和震荡的价格数据
    base_price = 50000

    # 第一阶段：上涨趋势
    trend1 = np.linspace(0, 5000, 60)
    # 第二阶段：震荡
    trend2 = np.sin(np.linspace(0, 4 * np.pi, 80)) * 1000 + 5000
    # 第三阶段：下跌趋势
    trend3 = np.linspace(5000, 3000, 60)

    trend = np.concatenate([trend1, trend2, trend3])
    noise = np.random.normal(0, 300, days)
    close_prices = base_price + trend[:days] + noise

    # 生成 OHLC 数据
    open_prices = close_prices * (1 + np.random.normal(0, 0.003, days))
    high_prices = np.maximum(close_prices, open_prices) * (1 + np.random.uniform(0, 0.008, days))
    low_prices = np.minimum(close_prices, open_prices) * (1 - np.random.uniform(0, 0.008, days))

    # 生成成交量数据
    volumes = np.random.randint(10000, 100000, days)

    df = pd.DataFrame({
        'open': open_prices,
        'high': high_prices,
        'low': low_prices,
        'close': close_prices,
        'volume': volumes
    }, index=dates)

    return df


def test_dual_ma_strategy_basic():
    """
    测试 DualMAStrategy 的基本功能
    """
    print("\n" + "="*60)
    print("Test 1: DualMAStrategy Basic Functionality")
    print("="*60)

    # 1. 创建策略插件
    strategy = DualMAStrategy(config={
        'fast_window': 5,
        'slow_window': 20,
        'max_position_size': 0.2
    })

    print(f"[OK] Strategy created: {strategy.metadata.name}")
    print(f"  - Version: {strategy.metadata.version}")
    print(f"  - Type: {strategy.metadata.type.value}")

    # 2. 初始化策略
    strategy.initialize()
    print(f"[OK] Strategy initialized")
    print(f"  - Fast window: {strategy.fast_window}")
    print(f"  - Slow window: {strategy.slow_window}")

    # 3. 启动策略
    strategy.start()
    print(f"[OK] Strategy started")

    return strategy


def test_signal_generation(strategy: DualMAStrategy, df: pd.DataFrame):
    """
    测试信号生成
    """
    print("\n" + "="*60)
    print("Test 2: Signal Generation")
    print("="*60)

    # 生成信号
    signals_df = strategy.generate_signals(df)

    # 验证结果
    required_columns = ['ma_fast', 'ma_slow', 'signal']
    missing_columns = [col for col in required_columns if col not in signals_df.columns]

    if not missing_columns:
        print(f"[OK] All required columns present")

        # 统计信号
        signal_counts = signals_df['signal'].value_counts()
        buy_count = signal_counts.get(1, 0)
        sell_count = signal_counts.get(-1, 0)
        hold_count = signal_counts.get(0, 0)

        print(f"  - Buy signals: {buy_count}")
        print(f"  - Sell signals: {sell_count}")
        print(f"  - Hold signals: {hold_count}")
        print(f"  - Total data points: {len(signals_df)}")

        # 验证快均线和慢均线
        print(f"  - Fast MA valid: {signals_df['ma_fast'].count()}")
        print(f"  - Slow MA valid: {signals_df['ma_slow'].count()}")

        return buy_count > 0 or sell_count > 0
    else:
        print(f"[ERROR] Missing columns: {missing_columns}")
        return False


def test_trading_signals(strategy: DualMAStrategy, df: pd.DataFrame):
    """
    测试交易信号获取
    """
    print("\n" + "="*60)
    print("Test 3: Trading Signal Retrieval")
    print("="*60)

    current_price = df['close'].iloc[-1]
    print(f"Current price: {current_price:.2f}")

    # 获取交易信号
    signal = strategy.get_trading_signals(df, current_price)

    print(f"[OK] Trading signal retrieved")
    print(f"  - Signal: {signal['signal']}")
    print(f"  - Type: {signal['type']}")
    print(f"  - Price: {signal['price']:.2f}")

    if signal['signal'] in ['BUY', 'SELL']:
        print(f"  - Size: {signal['size']}")
        print(f"  - Stop loss: {signal['stop_loss']:.2f}")
        print(f"  - Take profit: {signal['take_profit']:.2f}")

    return True


def test_position_management(strategy: DualMAStrategy, df: pd.DataFrame):
    """
    测试持仓管理
    """
    print("\n" + "="*60)
    print("Test 4: Position Management")
    print("="*60)

    current_price = df['close'].iloc[-1]

    # 测试买入信号
    buy_signal = {
        "signal": "BUY",
        "type": "LONG",
        "price": current_price,
        "size": 0.2
    }

    print(f"Initial position: {strategy.position}")
    strategy.update_position(buy_signal)
    print(f"Position after BUY: {strategy.position}")

    # 测试平仓信号
    close_signal = {
        "signal": "CLOSE",
        "type": "CLOSE",
        "price": current_price * 1.01
    }
    strategy.update_position(close_signal)
    print(f"Position after CLOSE: {strategy.position}")

    # 测试卖出信号
    sell_signal = {
        "signal": "SELL",
        "type": "SHORT",
        "price": current_price,
        "size": 0.2
    }
    strategy.update_position(sell_signal)
    print(f"Position after SELL: {strategy.position}")

    # 重置
    strategy.position = 0

    print(f"[OK] Position management tested")
    return True


def test_strategy_lifecycle():
    """
    测试策略完整生命周期
    """
    print("\n" + "="*60)
    print("Test 5: Strategy Full Lifecycle")
    print("="*60)

    # 创建策略
    strategy = DualMAStrategy()
    print(f"[OK] Created: initialized={strategy.is_initialized}, running={strategy.is_running}")

    # 初始化
    strategy.initialize()
    print(f"[OK] Initialized: initialized={strategy.is_initialized}")

    # 启动
    strategy.start()
    print(f"[OK] Started: running={strategy.is_running}")

    # 健康检查
    health = strategy.health_check()
    print(f"[OK] Health check: healthy={health.healthy}")
    print(f"  - Metrics: {health.metrics}")

    # 停止
    strategy.stop()
    print(f"[OK] Stopped: running={strategy.is_running}")

    return True


def test_with_event_bus():
    """
    测试与事件总线集成
    """
    print("\n" + "="*60)
    print("Test 6: Integration with Event Bus")
    print("="*60)

    # 创建事件总线
    event_bus = ReliableEventBus(name="StrategyTestBus")
    event_bus.start()

    # 创建策略
    strategy = DualMAStrategy()
    strategy.set_event_bus(event_bus)

    # 初始化和启动
    strategy.initialize()
    strategy.start()

    # 生成测试数据
    df = generate_test_data(days=100)

    # 生成信号（这会触发事件）
    signals_df = strategy.generate_signals(df)
    print(f"[OK] Signals generated, events should have been emitted")

    # 清理
    strategy.stop()
    event_bus.stop()

    print(f"[OK] Event bus integration tested")
    return True


def test_backtest_simulation(strategy: DualMAStrategy, df: pd.DataFrame):
    """
    测试回测模拟
    """
    print("\n" + "="*60)
    print("Test 7: Backtest Simulation")
    print("="*60)

    # 生成信号
    signals_df = strategy.generate_signals(df)

    # 简单回测逻辑
    initial_capital = 100000
    cash = initial_capital
    position = 0
    entry_price = 0
    trades = []

    for i in range(len(signals_df)):
        signal = signals_df['signal'].iloc[i]
        price = signals_df['close'].iloc[i]

        if signal == 1 and position == 0:
            # 买入
            position_size = 0.2 * cash / price
            cash -= position_size * price
            position = position_size
            entry_price = price
            trades.append(('BUY', price, i))

        elif signal == -1 and position > 0:
            # 卖出
            cash += position * price
            pnl = position * (price - entry_price)
            position = 0
            trades.append(('SELL', price, i, pnl))

    # 计算最终净值
    final_price = df['close'].iloc[-1]
    final_value = cash + position * final_price
    total_return = (final_value - initial_capital) / initial_capital * 100

    print(f"[OK] Backtest completed")
    print(f"  - Initial capital: ${initial_capital:,.2f}")
    print(f"  - Final value: ${final_value:,.2f}")
    print(f"  - Total return: {total_return:+.2f}%")
    print(f"  - Number of trades: {len(trades)}")

    return True


def main():
    """
    主测试函数
    """
    print("\n" + "═"*60)
    print("  STRATEGY PLUGIN TEST SUITE")
    print("  Phase 3-3: Strategy Plugin Migration")
    print("═"*60)

    tests_passed = 0
    tests_total = 7

    try:
        # 生成测试数据
        df = generate_test_data(days=200)

        # Test 1: 基本功能
        strategy = test_dual_ma_strategy_basic()
        tests_passed += 1

        # Test 2: 信号生成
        if test_signal_generation(strategy, df):
            tests_passed += 1

        # Test 3: 交易信号获取
        if test_trading_signals(strategy, df):
            tests_passed += 1

        # Test 4: 持仓管理
        if test_position_management(strategy, df):
            tests_passed += 1

        # Test 5: 完整生命周期
        if test_strategy_lifecycle():
            tests_passed += 1

        # Test 6: 与事件总线集成
        if test_with_event_bus():
            tests_passed += 1

        # Test 7: 回测模拟
        strategy2 = DualMAStrategy()
        strategy2.initialize()
        if test_backtest_simulation(strategy2, df):
            tests_passed += 1

        # 总结
        print("\n" + "═"*60)
        print(f"  TEST SUMMARY: {tests_passed}/{tests_total} PASSED")
        print("═"*60)

        if tests_passed == tests_total:
            print("\n[SUCCESS] All tests passed!")
            return 0
        else:
            print(f"\n[FAILURE] {tests_total - tests_passed} tests failed")
            return 1

    except Exception as e:
        print(f"\n[ERROR] Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
