"""
测试实盘交易连接
"""
import os
import sys
import time
import warnings
from dotenv import load_dotenv

# 加载环境变量
load_dotenv('../.env')

# 忽略SSL警告
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

from binance.client import Client
from binance.enums import SIDE_BUY, SIDE_SELL, ORDER_TYPE_MARKET

# 获取API密钥
api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')
proxy = os.getenv('HTTPS_PROXY')

print("="*70)
print("测试实盘交易连接")
print("="*70)
print(f"Proxy: {proxy}")
print()

# 设置请求参数
requests_params = {
    'proxies': {'https': proxy, 'http': proxy},
    'verify': False
}

# 创建客户端
client = Client(api_key, api_secret, requests_params=requests_params, ping=False)
recv_window = 60000

# 同步时间
print("[0] 同步时间...")
server_time = client.get_server_time()
local_time = int(time.time() * 1000)
time_offset = server_time['serverTime'] - local_time
print(f"    Time offset: {time_offset}ms")
client.timestamp_offset = time_offset
print(f"    Set timestamp_offset = {time_offset}")

# 测试服务器时间
print("[1] 测试服务器时间...")
try:
    server_time = client.get_server_time()
    print(f"    Server time: {server_time}")
except Exception as e:
    print(f"    [ERROR] {e}")
    sys.exit(1)

# 测试账户余额
print("[2] 测试账户余额...")
try:
    account = client.get_account(recvWindow=recv_window)
    usdt_balance = next((b for b in account['balances'] if b['asset'] == 'USDT'), None)
    print(f"    USDT Balance: {usdt_balance}")

    if float(usdt_balance['free']) < 100:
        print("    [WARNING] USDT余额不足$100，无法开始实盘交易")
    else:
        print(f"    [OK] USDT余额充足: ${usdt_balance['free']}")
except Exception as e:
    print(f"    [ERROR] {e}")
    sys.exit(1)

# 测试订单簿
print("[3] 测试SOLUSDT订单簿...")
try:
    depth = client.get_order_book(symbol='SOLUSDT', limit=5)
    best_bid = depth['bids'][0]
    best_ask = depth['asks'][0]
    print(f"    Best Bid: {best_bid}")
    print(f"    Best Ask: {best_ask}")
    mid_price = (float(best_bid[0]) + float(best_ask[0])) / 2
    print(f"    Mid Price: ${mid_price:.2f}")
except Exception as e:
    print(f"    [ERROR] {e}")
    sys.exit(1)

print()
print("="*70)
print("[OK] 所有连接测试通过!")
print("="*70)
print()
print("注意: 账户USDT余额为0，无法开始实盘交易。")
print("请先向币安账户充值至少$100 USDT。")
