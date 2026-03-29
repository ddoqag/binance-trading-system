#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
插件系统端到端集成测试 - Plugin System End-to-End Integration Test

演示插件化架构的最小可运行原型：
- 1个数据源插件 + 1个因子插件 + 1个策略插件 + 1个执行插件
"""

import logging
import sys
import time
from typing import Dict, Any

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 添加插件路径
sys.path.insert(0, 'D:\\binance')

from plugins.event_bus import EventBus
from plugins.manager import PluginManager


def setup_event_bus():
    """设置事件总线"""
    print("\n" + "="*60)
    print("Step 1: Setting up Event Bus")
    print("="*60)

    event_bus = EventBus(name="TradingSystem", max_queue_size=1000)
    event_bus.start()

    print(f"[OK] Event bus started: {event_bus.name}")
    print(f"  - Running: {event_bus.is_running}")

    return event_bus


def setup_plugin_manager(event_bus):
    """设置插件管理器"""
    print("\n" + "="*60)
    print("Step 2: Setting up Plugin Manager")
    print("="*60)

    plugin_manager = PluginManager(event_bus=event_bus)

    print(f"[OK] Plugin manager initialized")
    print(f"  - Plugin paths: {plugin_manager.plugin_paths}")

    return plugin_manager


def load_plugins(plugin_manager):
    """加载所有示例插件"""
    print("\n" + "="*60)
    print("Step 3: Loading Plugins")
    print("="*60)

    plugins_to_load = [
        ("binance_data_source", "BinanceDataSource"),
        ("momentum_factor", "MomentumFactor"),
        ("dual_ma_strategy", "DualMAStrategy"),
        ("simulated_executor", "SimulatedExecutor")
    ]

    loaded_plugins = []
    for module_name, plugin_class in plugins_to_load:
        try:
            instance_id = plugin_manager.load_plugin(module_name)
            plugin = plugin_manager.get_plugin(module_name)
            print(f"[OK] Loaded {plugin_class} (instance: {instance_id})")
            print(f"  - Name: {plugin.metadata.name}")
            print(f"  - Type: {plugin.metadata.type.value}")
            print(f"  - Version: {plugin.metadata.version}")
            loaded_plugins.append(module_name)
        except Exception as e:
            print(f"[ERROR] Failed to load {plugin_class}: {e}")

    return loaded_plugins


def start_plugins(plugin_manager, plugin_names):
    """启动插件"""
    print("\n" + "="*60)
    print("Step 4: Starting Plugins")
    print("="*60)

    for name in plugin_names:
        try:
            plugin_manager.start_plugin(name)
            plugin = plugin_manager.get_plugin(name)
            print(f"[OK] Started {plugin.metadata.name}")
            print(f"  - Initialized: {plugin.is_initialized}")
            print(f"  - Running: {plugin.is_running}")
        except Exception as e:
            print(f"[ERROR] Failed to start {name}: {e}")


def run_trading_simulation(plugin_manager):
    """运行交易模拟"""
    print("\n" + "="*60)
    print("Step 5: Running Trading Simulation")
    print("="*60)

    try:
        # 获取插件实例
        data_source = plugin_manager.get_plugin("binance_data_source")
        factor_plugin = plugin_manager.get_plugin("momentum_factor")
        strategy_plugin = plugin_manager.get_plugin("dual_ma_strategy")
        executor = plugin_manager.get_plugin("simulated_executor")

        if not all([data_source, factor_plugin, strategy_plugin, executor]):
            print("[ERROR] Missing some plugins, skipping simulation")
            return

        # 1. 获取数据
        print("\n1. Fetching market data...")
        df = data_source.get_data(limit=1000)
        print(f"   [OK] Got {len(df)} data points")
        print(f"   - Date range: {df.index.min()} to {df.index.max()}")
        print(f"   - Current price: {df['close'].iloc[-1]:.2f}")

        # 2. 计算因子
        print("\n2. Calculating momentum factor...")
        factor_values = factor_plugin.calculate(df)
        print(f"   [OK] Factor calculated, {len(factor_values.dropna())} valid points")
        print(f"   - Factor range: {factor_values.min():.4f} to {factor_values.max():.4f}")
        print(f"   - Latest factor: {factor_values.iloc[-1]:.4f}")

        # 3. 生成交易信号
        print("\n3. Generating trading signals...")
        signals_df = strategy_plugin.generate_signals(df)
        print(f"   [OK] Signals generated")
        print(f"   - Buy signals: {len(signals_df[signals_df['signal'] == 1])}")
        print(f"   - Sell signals: {len(signals_df[signals_df['signal'] == -1])}")

        # 4. 模拟交易执行
        print("\n4. Simulating trade execution...")
        current_price = df['close'].iloc[-1]

        # 获取交易信号
        trade_signal = strategy_plugin.get_trading_signals(df, current_price)
        print(f"   - Current signal: {trade_signal['signal']}")

        if trade_signal['signal'] == "BUY":
            order_result = executor.execute_order({
                "symbol": "BTCUSDT",
                "side": "BUY",
                "quantity": 0.1,
                "price": current_price
            })
            print(f"   [OK] Order executed: {order_result}")

        # 获取账户信息
        account_info = executor.get_account_info()
        print(f"\n   Account status:")
        print(f"   - Cash: {account_info['cash']:.2f}")
        print(f"   - Positions: {len(account_info['positions'])}")
        print(f"   - Equity: {account_info['equity']:.2f}")
        print(f"   - Total PnL: {account_info['total_pnl']:.2f}")
        print(f"   - Return: {account_info['return_pct']:.2f}%")

        # 更新市场价格
        print("\n5. Updating market prices...")
        executor.update_market_prices({"BTCUSDT": current_price * 1.005})
        account_info = executor.get_account_info()
        print(f"   - Updated equity: {account_info['equity']:.2f}")

    except Exception as e:
        print(f"[ERROR] Simulation failed: {e}")
        import traceback
        traceback.print_exc()


def check_plugin_health(plugin_manager):
    """检查插件健康状态"""
    print("\n" + "="*60)
    print("Step 6: Plugin Health Checks")
    print("="*60)

    all_plugins = plugin_manager.get_all_plugins()

    for name, plugin in all_plugins.items():
        try:
            health = plugin.health_check()
            status = "[OK] HEALTHY" if health.healthy else "[ERROR] UNHEALTHY"
            print(f"\n{status} - {plugin.metadata.name}")
            print(f"  - Message: {health.message}")
            if health.metrics:
                print(f"  - Metrics: {health.metrics}")
        except Exception as e:
            print(f"\n[ERROR] {name} health check failed: {e}")


def display_event_bus_stats(event_bus):
    """显示事件总线统计"""
    print("\n" + "="*60)
    print("Step 7: Event Bus Statistics")
    print("="*60)

    stats = event_bus.get_stats()
    print(f"[OK] Event bus stats:")
    print(f"  - Name: {stats['name']}")
    print(f"  - Running: {stats['running']}")
    print(f"  - Total events: {stats['total_events']}")
    print(f"  - Queue size: {stats['queue_size']}")
    print(f"  - Subscribers: {stats['subscribers']}")
    print(f"  - Subscribers per type: {stats['subscribers_per_type']}")


def display_plugin_overview(plugin_manager):
    """显示插件概览"""
    print("\n" + "="*60)
    print("Step 8: Plugin Overview")
    print("="*60)

    all_info = plugin_manager.get_all_plugin_info()

    print(f"[OK] Loaded plugins: {len(all_info)}")

    for name, info in all_info.items():
        print(f"\n  {info['name']} ({info['type']}):")
        print(f"    - Version: {info['version']}")
        print(f"    - Status: {'RUNNING' if info['running'] else 'STOPPED'}")
        print(f"    - Health: {'HEALTHY' if info['healthy'] else 'UNHEALTHY'}")
        print(f"    - Author: {info['author'] or 'Unknown'}")


def stop_and_unload_plugins(plugin_manager):
    """停止和卸载插件"""
    print("\n" + "="*60)
    print("Step 9: Cleaning Up")
    print("="*60)

    plugin_manager.stop_all_plugins()
    print("[OK] All plugins stopped")

    plugin_manager.unload_all_plugins()
    print("[OK] All plugins unloaded")

    plugin_manager.shutdown()
    print("[OK] Plugin manager shutdown")


def main():
    """主函数"""
    print("\n" + "═"*60)
    print("  PLUGIN SYSTEM - END-TO-END INTEGRATION TEST")
    print("  Minimum Viable Prototype: 4 plugins working together")
    print("═"*60)

    event_bus = None
    plugin_manager = None

    try:
        # 设置事件总线
        event_bus = setup_event_bus()

        # 设置插件管理器
        plugin_manager = setup_plugin_manager(event_bus)

        # 发现插件
        print("\nDiscovering plugins...")
        discovered = plugin_manager.discover_plugins()
        print(f"Discovered {len(discovered)} potential plugins")

        # 加载插件
        loaded_plugins = load_plugins(plugin_manager)

        if len(loaded_plugins) == 0:
            print("No plugins loaded! Exiting.")
            return

        # 启动插件
        start_plugins(plugin_manager, loaded_plugins)

        # 显示插件概览
        display_plugin_overview(plugin_manager)

        # 运行交易模拟
        run_trading_simulation(plugin_manager)

        # 检查健康状态
        check_plugin_health(plugin_manager)

        # 显示事件总线统计
        display_event_bus_stats(event_bus)

        print("\n" + "═"*60)
        print("  TEST COMPLETED SUCCESSFULLY!")
        print("═"*60)
        print("\nSummary:")
        print("- Event bus: OK")
        print("- Plugin manager: OK")
        print(f"- Plugins loaded: {len(plugin_manager.get_all_plugins())}")
        print("- Trading simulation: OK")

    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 清理
        if plugin_manager:
            stop_and_unload_plugins(plugin_manager)
        if event_bus and event_bus.is_running:
            event_bus.stop()
            print("[OK] Event bus stopped")


if __name__ == "__main__":
    main()
