#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试余额同步修复
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from trading.spot_margin_executor import SpotMarginExecutor

def test_balance_sync():
    """测试余额同步"""
    print("=" * 60)
    print("测试余额同步修复")
    print("=" * 60)

    # 从环境变量获取API密钥
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')

    if not api_key or not api_secret:
        print("错误: 未设置 BINANCE_API_KEY 或 BINANCE_API_SECRET")
        return

    # 创建执行器（会自动同步余额）
    executor = SpotMarginExecutor(
        api_key=api_key,
        api_secret=api_secret,
        initial_margin=10000,  # 这个默认值会被覆盖
        max_leverage=3.0,
    )

    # 获取余额信息
    balance = executor.get_balance_info()

    print("\n【余额信息】")
    print(f"  total_balance: {balance['total_balance']:.2f} USDT")
    print(f"  available_balance: {balance['available_balance']:.2f} USDT")
    print(f"  margin_level: {balance['margin_level']}")
    print(f"  trade_enabled: {balance['trade_enabled']}")

    # 验证
    print("\n【验证】")
    if balance['available_balance'] >= 10.0:
        print(f"  ✓ available_balance 正确: {balance['available_balance']:.2f} >= 10.0")
    else:
        print(f"  ✗ available_balance 错误: {balance['available_balance']:.2f} < 10.0")

    if balance['total_balance'] > 0:
        print(f"  ✓ total_balance 已设置: {balance['total_balance']:.2f}")
    else:
        print(f"  ✗ total_balance 未设置")

    print("\n" + "=" * 60)

if __name__ == '__main__':
    test_balance_sync()
