#!/usr/bin/env python3
"""
检查币安期货账户状态
"""
import os
import sys
from pathlib import Path

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Fix SSL issues
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from binance.client import Client

def check_account():
    """检查期货账户详情"""
    # Get API credentials
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')

    if not api_key or not api_secret:
        print("[错误] 未设置 BINANCE_API_KEY 或 BINANCE_API_SECRET")
        return

    # Get proxy settings
    proxy = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY') or 'http://127.0.0.1:7897'

    # Create client with SSL disabled
    client = Client(
        api_key,
        api_secret,
        testnet=(os.getenv('USE_TESTNET', 'false').lower() == 'true'),
        requests_params={
            'proxies': {'http': proxy, 'https': proxy},
            'verify': False
        }
    )

    print("=" * 60)
    print("币安期货账户检查")
    print("=" * 60)

    # 1. 检查账户模式
    try:
        print("\n[账户模式]")
        position_mode = client.futures_get_position_mode()
        print(f"  双向持仓模式: {'开启' if position_mode['dualSidePosition'] else '关闭'}")
    except Exception as e:
        print(f"  获取账户模式失败: {e}")

    # 2. 检查期货账户余额
    try:
        print("\n[期货账户余额 - USDT 合约]")
        account = client.futures_account()

        # 总权益
        total_wallet = float(account.get('totalWalletBalance', 0))
        print(f"  总权益 (Wallet Balance): {total_wallet:.2f} USDT")

        # 可用余额
        available = float(account.get('availableBalance', 0))
        print(f"  可用余额 (Available):    {available:.2f} USDT")

        # 未实现盈亏
        unrealized = float(account.get('totalUnrealizedProfit', 0))
        print(f"  未实现盈亏 (Unrealized): {unrealized:.2f} USDT")

        # 保证金余额
        margin = float(account.get('totalMarginBalance', 0))
        print(f"  保证金余额 (Margin):     {margin:.2f} USDT")

        # 持仓保证金
        position_margin = float(account.get('totalPositionInitialMargin', 0))
        print(f"  持仓保证金 (Position):   {position_margin:.2f} USDT")

        if total_wallet < 10:
            print("\n[!] 警告: 期货账户余额不足 (最少需要 ~10 USDT 才能下单)")
            print("\n解决方案:")
            print("  1. 登录币安官网: https://www.binance.com")
            print("  2. 进入 钱包 -> 现货账户 -> 划转")
            print("  3. 选择 USDT，从现货账户划转到 U本位合约账户")
            print("  4. 建议初次划转 50-100 USDT 进行测试")

    except Exception as e:
        print(f"  获取账户余额失败: {e}")

    # 3. 检查当前持仓
    try:
        print("\n[当前持仓]")
        positions = client.futures_position_information()
        active_positions = [p for p in positions if float(p.get('positionAmt', 0)) != 0]

        if active_positions:
            for pos in active_positions:
                symbol = pos['symbol']
                amt = float(pos['positionAmt'])
                entry = float(pos['entryPrice'])
                pnl = float(pos['unrealizedProfit'])
                margin_type = pos.get('marginType', 'ISOLATED')
                leverage = pos.get('leverage', '1')

                side = "做多" if amt > 0 else "做空"
                print(f"  {symbol}: {side} {abs(amt)} @ {entry}")
                print(f"    杠杆: {leverage}x | 保证金模式: {margin_type}")
                print(f"    未实现盈亏: {pnl:.2f} USDT")
        else:
            print("  当前无持仓")

    except Exception as e:
        print(f"  获取持仓失败: {e}")

    # 4. 检查交易对信息
    try:
        print("\n[BTCUSDT 合约信息]")
        info = client.futures_exchange_info()
        btc_info = None
        for s in info['symbols']:
            if s['symbol'] == 'BTCUSDT':
                btc_info = s
                break

        if btc_info:
            print(f"  状态: {btc_info.get('status')}")
            print(f"  最小数量: {btc_info.get('filters', [{}])[1].get('minQty', 'N/A')}")
            print(f"  数量精度: {btc_info.get('filters', [{}])[1].get('stepSize', 'N/A')}")

            # 检查是否支持全仓
            margin_types = [m for m in btc_info.get('marginTypes', [])]
            print(f"  支持保证金模式: {margin_types if margin_types else '默认逐仓'}")

    except Exception as e:
        print(f"  获取合约信息失败: {e}")

    print("\n" + "=" * 60)

if __name__ == "__main__":
    check_account()
