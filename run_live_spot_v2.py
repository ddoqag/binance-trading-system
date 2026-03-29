#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实盘交易启动脚本 v2 - 增强代理和超时处理
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
    proxy_url='http://127.0.0.1:7897',
    use_ssl_verify=False,
)

print("="*60)
print("实盘交易模式已启动")
print("="*60)
print(f"交易对: {config.symbol}")
print(f"模拟交易: {config.paper_trading}")
print(f"杠杆交易: {config.use_leverage}")
print(f"现货杠杆: {config.use_spot_margin}")
print(f"代理: {config.proxy_url}")
print("="*60)

# 修改requests默认超时
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 创建带重试的session
def create_robust_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        read=3,
        connect=3,
        backoff_factor=1,
        status_forcelist=(500, 502, 503, 504)
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=20)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

# 先测试代理连接
print("\n测试代理连接...")
try:
    test_session = create_robust_session()
    test_proxy = {'http': config.proxy_url, 'https': config.proxy_url}
    response = test_session.get(
        'https://api.binance.com/api/v3/ping',
        proxies=test_proxy,
        verify=False,
        timeout=30
    )
    print(f"[OK] 代理连接成功: HTTP {response.status_code}")
except Exception as e:
    print(f"[!] 代理连接测试失败: {e}")
    print("继续尝试启动交易...")

print("\n初始化交易客户端...")
try:
    trader = ProTraderV2(config)
    print("\n" + "="*60)
    print("[SUCCESS] 实盘交易已成功启动！")
    print("="*60)
    print("\n按 Ctrl+C 停止交易")
    print("="*60)
    trader.run()
except KeyboardInterrupt:
    print("\n\n用户停止交易")
except Exception as e:
    print(f"\n\n[ERROR] 错误: {e}")
    import traceback
    traceback.print_exc()
    print("\n建议:")
    print("1. 检查VPN代理是否正常工作")
    print("2. 检查网络连接")
    print("3. 检查API密钥是否正确")
