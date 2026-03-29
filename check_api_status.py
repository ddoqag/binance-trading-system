#!/usr/bin/env python3
"""检查币安 API 密钥状态"""
import os
from dotenv import load_dotenv
load_dotenv()

import urllib3
urllib3.disable_warnings()

from binance.client import Client
import requests

# 配置
proxy = os.getenv('HTTPS_PROXY') or 'http://127.0.0.1:7897'
print("=" * 60)
print("币安 API 密钥诊断")
print("=" * 60)

# 检查环境变量
api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')
use_testnet = os.getenv('USE_TESTNET', 'false').lower() == 'true'

print(f"\n[环境变量]")
print(f"  API Key: {'已设置' if api_key else '未设置'} ({len(api_key) if api_key else 0} 字符)")
print(f"  Secret: {'已设置' if api_secret else '未设置'} ({len(api_secret) if api_secret else 0} 字符)")
print(f"  测试网模式: {'是' if use_testnet else '否'}")
print(f"  代理: {proxy}")

# 测试连接
print(f"\n[连接测试]")
try:
    session = requests.Session()
    session.proxies = {'http': proxy, 'https': proxy}
    session.verify = False

    client = Client(api_key, api_secret, testnet=use_testnet)
    client.session = session

    # 测试 ping
    client.ping()
    print("  Ping: 成功")

    # 获取服务器时间
    server_time = client.get_server_time()
    print(f"  服务器时间: {server_time}")

    # 获取账户信息
    print("\n[账户信息]")
    try:
        account = client.get_account()
        print("  现货账户: 可以访问")
        print(f"  账户权限: {account.get('permissions', [])}")
        print(f"  可交易: {account.get('canTrade', False)}")
        print(f"  可提现: {account.get('canWithdraw', False)}")
        print(f"  可充值: {account.get('canDeposit', False)}")
    except Exception as e:
        print(f"  现货账户访问失败: {e}")

    # 检查杠杆账户
    print("\n[杠杆账户]")
    try:
        margin_account = client.get_margin_account()
        print("  杠杆账户: 可以访问")
        print(f"  交易启用: {margin_account.get('tradeEnabled', False)}")
        print(f"  借贷启用: {margin_account.get('borrowEnabled', False)}")
        print(f"  转账启用: {margin_account.get('transferEnabled', False)}")
    except Exception as e:
        print(f"  杠杆账户访问失败: {e}")
        print("  可能原因: 杠杆账户未开通 或 API 密钥无权限")

except Exception as e:
    print(f"  连接失败: {e}")

print("\n" + "=" * 60)
