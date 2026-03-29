#!/usr/bin/env python3
"""
Binance API 密钥验证修复脚本
根据官方文档修复认证问题
"""
import os
from dotenv import load_dotenv
load_dotenv()

import urllib3
urllib3.disable_warnings()

import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException

# 配置
proxy = os.getenv('HTTPS_PROXY') or 'http://127.0.0.1:7897'

print("=" * 70)
print("Binance API 密钥验证 (根据官方文档)")
print("=" * 70)

# 获取配置
api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')
use_testnet = os.getenv('USE_TESTNET', 'false').lower() == 'true'

print(f"\n[配置信息]")
print(f"  测试网模式: {use_testnet}")
print(f"  API Key: {api_key[:15]}...{api_key[-10:]}" if api_key and len(api_key) > 25 else f"  API Key: {api_key}")
print(f"  Secret: {'已设置 (' + str(len(api_secret)) + ' 字符)' if api_secret else '未设置'}")
print(f"  代理: {proxy}")

# 根据文档创建 session
session = requests.Session()
session.proxies = {'http': proxy, 'https': proxy}
session.verify = False

print(f"\n[连接测试]")
print(f"  目标环境: {'测试网 (testnet.binance.vision)' if use_testnet else '主网 (api.binance.com)'}")

try:
    # 创建 Client - 根据官方文档方式
    client = Client(
        api_key=api_key,
        api_secret=api_secret,
        testnet=use_testnet,
        requests_params={'timeout': 30}
    )

    # 替换 session 以支持代理
    client.session = session

    # 测试 1: Ping (不需要签名)
    print("\n[1] Ping 测试...")
    client.ping()
    print("  [OK] Ping 成功 - 网络连接正常")

    # 测试 2: 服务器时间 (不需要签名)
    print("\n[2] 服务器时间...")
    server_time = client.get_server_time()
    import time
    local_time = int(time.time() * 1000)
    time_diff = abs(local_time - server_time['serverTime'])
    print(f"  服务器时间: {server_time['serverTime']}")
    print(f"  本地时间: {local_time}")
    print(f"  时间差: {time_diff}ms {'[OK]' if time_diff < 5000 else '[WARN] 超过5秒'}")

    # 测试 3: 现货账户信息 (需要签名)
    print("\n[3] 现货账户信息...")
    try:
        account = client.get_account()
        print(f"  [OK] 现货账户访问成功")
        print(f"  账户类型: {account.get('accountType', 'N/A')}")
        print(f"  权限: {account.get('permissions', [])}")
        print(f"  可交易: {account.get('canTrade', False)}")
        print(f"  可提现: {account.get('canWithdraw', False)}")
        print(f"  可充值: {account.get('canDeposit', False)}")

        # 显示非零余额
        balances = [b for b in account.get('balances', []) if float(b['free']) > 0 or float(b['locked']) > 0]
        if balances:
            print(f"  非零余额资产:")
            for b in balances[:5]:  # 只显示前5个
                print(f"    {b['asset']}: 可用={b['free']}, 冻结={b['locked']}")

    except BinanceAPIException as e:
        print(f"  [ERR] 现货账户访问失败")
        print(f"  错误代码: {e.code}")
        print(f"  错误信息: {e.message}")

        if e.code == -2014:
            print(f"\n  诊断: API Key 格式无效")
            print(f"  可能原因:")
            print(f"    1. API Key 在当前环境({'测试网' if use_testnet else '主网'})不存在")
            print(f"    2. API Key 已被删除或撤销")
            print(f"    3. 使用了 {'测试网' if not use_testnet else '主网'} 的 Key 连接 {'主网' if not use_testnet else '测试网'}")
            print(f"\n  解决方案:")
            print(f"    - 请访问 https://{'testnet.binance.vision' if use_testnet else 'www.binance.com'}/zh-CN/my/settings/api-management")
            print(f"    - 确认 API Key 存在且启用了 '现货交易' 权限")
            print(f"    - 如果设置了 IP 白名单，请添加当前 IP")

    # 测试 4: 杠杆账户信息 (需要签名且需要开通杠杆)
    print("\n[4] 杠杆账户信息...")
    try:
        margin_account = client.get_margin_account()
        print(f"  [OK] 杠杆账户访问成功")
        print(f"  交易启用: {margin_account.get('tradeEnabled', False)}")
        print(f"  借贷启用: {margin_account.get('borrowEnabled', False)}")
        print(f"  转账启用: {margin_account.get('transferEnabled', False)}")
        print(f"  全仓杠杆等级: {margin_account.get('marginLevel', 'N/A')}")

        # 显示资产
        assets = margin_account.get('userAssets', [])
        non_zero = [a for a in assets if float(a.get('free', 0)) > 0 or float(a.get('borrowed', 0)) > 0]
        if non_zero:
            print(f"  杠杆账户资产:")
            for a in non_zero[:5]:
                print(f"    {a['asset']}: 可用={a['free']}, 已借={a.get('borrowed', 0)}, 净值={a.get('netAsset', 0)}")
        else:
            print(f"  杠杆账户暂无资产")

    except BinanceAPIException as e:
        print(f"  [ERR] 杠杆账户访问失败")
        print(f"  错误代码: {e.code}")
        print(f"  错误信息: {e.message}")

        if e.code == -2014:
            print(f"\n  与现货账户相同的 API Key 问题")
        elif e.code == -11001:
            print(f"\n  诊断: 杠杆账户未开通")
            print(f"  解决方案: 请先在 Binance 开通全仓杠杆账户")

except Exception as e:
    print(f"\n[ERR] 连接失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)
print("总结")
print("=" * 70)
print("根据 Binance 官方文档:")
print("1. 现货 API: https://api.binance.com/api (主网)")
print("2. 杠杆 API: https://api.binance.com/sapi (主网)")
print("3. 测试网现货: https://testnet.binance.vision/api")
print("")
print("错误 -2014 'API-key format invalid' 表示:")
print("- API Key 不存在于当前连接的环境")
print("- 主网和测试网的 API Key 是不互通的")
print("=" * 70)
