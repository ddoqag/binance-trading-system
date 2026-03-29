#!/usr/bin/env python3
"""API 密钥诊断工具"""
import os
from dotenv import load_dotenv
load_dotenv()

import urllib3
urllib3.disable_warnings()

from binance.client import Client
import requests

# 获取密钥
api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')
use_testnet = os.getenv('USE_TESTNET', 'false').lower() == 'true'
proxy = os.getenv('HTTPS_PROXY') or 'http://127.0.0.1:7897'

print("=" * 60)
print("API 密钥诊断")
print("=" * 60)

print(f"\n[配置信息]")
print(f"  测试网模式: {use_testnet}")
print(f"  API Key 长度: {len(api_key) if api_key else 0}")
print(f"  Secret 长度: {len(api_secret) if api_secret else 0}")
print(f"  API Key 前缀: {api_key[:10]}..." if api_key else "  API Key: None")
print(f"  API Key 后缀: ...{api_key[-10:]}" if api_key else "")

# 检查密钥是否包含空格或换行
if api_key:
    has_space = ' ' in api_key
    has_newline = '\n' in api_key or '\r' in api_key
    print(f"  包含空格: {has_space}")
    print(f"  包含换行: {has_newline}")
    print(f"  密钥字节数: {len(api_key.encode('utf-8'))}")

print(f"\n[连接测试]")
try:
    # 创建带代理的 session
    session = requests.Session()
    session.proxies = {'http': proxy, 'https': proxy}
    session.verify = False

    # 创建客户端
    client = Client(api_key, api_secret, testnet=use_testnet)
    client.session = session

    # 测试 ping
    client.ping()
    print("  Ping: 成功")

    # 获取服务器时间
    server_time = client.get_server_time()
    print(f"  服务器时间戳: {server_time.get('serverTime')}")

    # 尝试获取账户信息（需要签名）
    print("\n[账户信息测试]")
    try:
        account = client.get_account()
        print("  现货账户: 可以访问")
        print(f"  账户权限: {account.get('permissions', [])}")
    except Exception as e:
        print(f"  现货账户访问失败: {e}")
        print(f"  错误类型: {type(e).__name__}")

    # 尝试获取杠杆账户
    print("\n[杠杆账户测试]")
    try:
        margin_account = client.get_margin_account()
        print("  杠杆账户: 可以访问")
        print(f"  交易启用: {margin_account.get('tradeEnabled', False)}")
        print(f"  借贷启用: {margin_account.get('borrowEnabled', False)}")
    except Exception as e:
        print(f"  杠杆账户访问失败: {e}")
        print(f"  错误类型: {type(e).__name__}")

except Exception as e:
    print(f"  连接失败: {e}")
    print(f"  错误类型: {type(e).__name__}")

print("\n" + "=" * 60)
print("诊断建议:")
print("- 如果显示 'API-key format invalid'，请检查:")
print("  1. 密钥是否完整（64字符）")
print("  2. 密钥是否包含空格或换行")
print("  3. 密钥是否被 Binance 撤销")
print("  4. IP 白名单是否限制了当前 IP")
print("- 如果显示 'Invalid API-key, IP, or permissions'，请检查:")
print("  1. API 密钥是否有现货/杠杆交易权限")
print("  2. IP 白名单是否包含当前 IP")
print("=" * 60)
