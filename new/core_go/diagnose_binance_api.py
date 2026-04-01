#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Binance API 诊断工具
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests
import os
import hmac
import hashlib
import time
from urllib.parse import urlencode

# API 配置
API_KEY = "aViqrCfrE2iFzbD5exSDIn396AlyrjmjMPnaNHozBNJ501l0iGQMRIzp1rdMn3ju"
API_SECRET = "T9mKg7CL5lgtc3WDIpyZPM2O5KQcjk78EAGMq1E4ObJGxF2ZXddlwAiPyGreC531"
BASE_URL = "https://api.binance.com"
PROXY = os.getenv("HTTPS_PROXY", "http://127.0.0.1:7897")

def get_timestamp():
    """获取服务器时间戳（本地时间，可能有时差）"""
    return int(time.time() * 1000)

def get_server_time():
    """获取 Binance 服务器时间"""
    proxies = {"https": PROXY} if PROXY else None
    try:
        resp = requests.get(f"{BASE_URL}/api/v3/time", proxies=proxies, timeout=10)
        return resp.json().get("serverTime")
    except Exception as e:
        print(f"[错误] 无法获取服务器时间: {e}")
        return None

def test_public_api():
    """测试公共 API（不需要认证）"""
    print("\n" + "="*60)
    print("1. 测试公共 API（无需认证）")
    print("="*60)

    proxies = {"https": PROXY} if PROXY else None

    # 测试 ping
    try:
        resp = requests.get(f"{BASE_URL}/api/v3/ping", proxies=proxies, timeout=10)
        print(f"   [OK] Ping: {resp.status_code} {resp.json()}")
    except Exception as e:
        print(f"   [FAIL] Ping 失败: {e}")

    # 测试服务器时间
    try:
        resp = requests.get(f"{BASE_URL}/api/v3/time", proxies=proxies, timeout=10)
        data = resp.json()
        server_time = data.get("serverTime")
        local_time = get_timestamp()
        diff = abs(server_time - local_time)
        print(f"   [OK] 服务器时间: {server_time}")
        print(f"   [OK] 本地时间: {local_time}")
        print(f"   {'[OK]' if diff < 1000 else '[WARN]'} 时间差: {diff}ms")
    except Exception as e:
        print(f"   [FAIL] 时间同步失败: {e}")

def test_signed_endpoint():
    """测试需要签名的端点（需要 API key）"""
    print("\n" + "="*60)
    print("2. 测试私有 API（需要认证和签名）")
    print("="*60)

    proxies = {"https": PROXY} if PROXY else None

    # 准备签名参数
    timestamp = get_timestamp()
    params = {"timestamp": timestamp}
    query_string = urlencode(params)
    signature = hmac.new(
        API_SECRET.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    params["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    # 测试账户信息
    try:
        print(f"   请求: GET /api/v3/account")
        print(f"   时间戳: {timestamp}")
        print(f"   签名: {signature[:16]}...")

        resp = requests.get(
            f"{BASE_URL}/api/v3/account",
            params=params,
            headers=headers,
            proxies=proxies,
            timeout=10
        )

        if resp.status_code == 200:
            data = resp.json()
            print(f"   [OK] 认证成功!")
            print(f"   [OK] 账户权限: {data.get('permissions', [])}")
            print(f"   [OK] 可以交易: {data.get('canTrade')}")
        else:
            error = resp.json()
            code = error.get("code")
            msg = error.get("msg")
            print(f"   [FAIL] 请求失败")
            print(f"   [FAIL] HTTP 状态: {resp.status_code}")
            print(f"   [FAIL] 错误码: {code}")
            print(f"   [FAIL] 错误信息: {msg}")

            if code == -2015:
                print("\n   [诊断] -2015 错误可能原因:")
                print("   1. API key 未启用 '读取' 权限")
                print("   2. API key 启用了 IP 白名单，但当前 IP 不在列表中")
                print("   3. API key 已被删除或过期（90天规则）")
                print("\n   [解决方案]:")
                print("   - 登录 Binance → API 管理 → 检查 key 权限")
                print("   - 禁用 IP 白名单或添加当前 IP")
                print("   - 重新生成 API key（如果超过90天）")

    except Exception as e:
        print(f"   [FAIL] 请求异常: {e}")

def check_ip_info():
    """检查当前 IP 地址"""
    print("\n" + "="*60)
    print("3. 网络信息")
    print("="*60)

    proxies = {"https": PROXY} if PROXY else None

    try:
        resp = requests.get("https://httpbin.org/ip", proxies=proxies, timeout=10)
        data = resp.json()
        print(f"   当前出口 IP: {data.get('origin')}")
        print(f"   代理设置: {PROXY}")
    except Exception as e:
        print(f"   无法获取 IP: {e}")

def main():
    print("Binance API 诊断工具")
    print("="*60)
    print(f"API Key: {API_KEY[:20]}...")
    print(f"Base URL: {BASE_URL}")
    print(f"Proxy: {PROXY}")

    test_public_api()
    check_ip_info()
    test_signed_endpoint()

    print("\n" + "="*60)
    print("诊断完成")
    print("="*60)

if __name__ == "__main__":
    main()
