import os
from dotenv import load_dotenv
load_dotenv('../.env')

from binance.client import Client

client = Client(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'))

# 1. 当前价格（轻量接口）
try:
    price = client.get_symbol_ticker(symbol='DOGEUSDT')
    print('Current DOGEUSDT price:', price['price'])
except Exception as e:
    print('Price error:', e)

# 2. 保证金账户中是否有 DOGE
try:
    account = client.get_margin_account()
    assets = {a['asset']: a for a in account.get('userAssets', [])}
    if 'DOGE' in assets:
        print('DOGE in margin:', assets['DOGE'])
    else:
        print('DOGE not found in margin account')
    print('All margin assets:', {k: v for k, v in assets.items() if float(v.get('netAsset', 0)) != 0})
except Exception as e:
    print('Margin account error:', e)
