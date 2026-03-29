#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实盘交易启动脚本 - 使用普通现货交易（无杠杆）
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 强制设置环境变量
os.environ['USE_LEVERAGE'] = 'false'
os.environ['USE_SPOT_MARGIN'] = 'false'

from live_trading_pro_v2 import ProConfig, ProTraderV2

# 创建实盘交易配置（明确覆盖所有参数）
config = ProConfig(
    symbol='BTCUSDT',
    paper_trading=False,  # 关键：禁用模拟交易
    use_leverage=False,   # 禁用杠杆
    use_spot_margin=False, # 禁用现货杠杆
)

print("="*60)
print("实盘交易模式已启动")
print("="*60)
print(f"交易对: {config.symbol}")
print(f"模拟交易: {config.paper_trading}")
print(f"杠杆交易: {config.use_leverage}")
print(f"现货杠杆: {config.use_spot_margin}")
print("="*60)

trader = ProTraderV2(config)

print("\n按 Ctrl+C 停止交易")
print("="*60)

try:
    trader.run()
except KeyboardInterrupt:
    print("\n用户停止交易")
except Exception as e:
    print(f"\n错误: {e}")
    import traceback
    traceback.print_exc()
