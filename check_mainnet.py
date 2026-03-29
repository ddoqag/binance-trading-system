from dotenv import load_dotenv
load_dotenv()

from binance.client import Client
import os

client = Client(
    os.getenv('BINANCE_API_KEY'),
    os.getenv('BINANCE_API_SECRET'),
    testnet=False
)

# 测试连接
print("Testing mainnet connection...")
client.ping()
print("[OK] Connected to Binance Mainnet")

# 获取价格
price = client.get_symbol_ticker(symbol='BTCUSDT')
print(f"BTC Price: ${price['price']}")

# 获取账户信息
try:
    account = client.get_account()
    print("[OK] Account access verified")

    # 查找余额
    for asset in ['USDT', 'BTC', 'ETH', 'BNB']:
        balance = next((b for b in account['balances'] if b['asset'] == asset), None)
        if balance:
            free = float(balance['free'])
            locked = float(balance['locked'])
            if free > 0 or locked > 0:
                print(f"  {asset}: Free={free:.4f}, Locked={locked:.4f}")

    # 检查权限
    print(f"Permissions: {account.get('permissions', [])}")

except Exception as e:
    print(f"[ERROR] Account access failed: {e}")
