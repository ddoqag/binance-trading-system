#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实盘交易启动脚本 - 现货杠杆 3x
强制使用现货杠杆模式（支持做空）
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from live_trading_pro_v2_live_only import ProConfig, ProTraderV2

# 强制设置环境变量确保使用现货杠杆
os.environ['USE_LEVERAGE'] = 'true'
os.environ['USE_SPOT_MARGIN'] = 'true'

# 创建配置
config = ProConfig(
    symbol='BTCUSDT',
    use_leverage=True,
    use_spot_margin=True,
    max_leverage=3.0,
    short_enabled=True,
)

print("="*60)
print("实盘交易模式 - 现货杠杆 3x")
print("="*60)
print(f"交易对: {config.symbol}")
print(f"杠杆: {config.max_leverage}x")
print(f"模式: 现货杠杆全仓")
print(f"做空: 已启用")
print("="*60)
print("WARNING: 真实资金交易！")
print("="*60)

# 确认启动
auto_confirm = os.getenv('AUTO_CONFIRM', 'false').lower() == 'true'
if auto_confirm:
    confirm = 'yes'
    print("\n[Auto-confirmed via AUTO_CONFIRM env var]")
else:
    confirm = input("\n确认启动实盘交易? (yes/no): ")
if confirm.lower() != 'yes':
    print("已取消")
    sys.exit(0)

try:
    trader = ProTraderV2(config)
    print("\n" + "="*60)
    print("实盘交易已启动")
    print("按 Ctrl+C 停止")
    print("="*60)
    trader.run()
except KeyboardInterrupt:
    print("\n\n用户停止交易")
except Exception as e:
    print(f"\n\n[ERROR] {e}")
    import traceback
    traceback.print_exc()
