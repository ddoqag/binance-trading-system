"""
保证金账户诊断脚本
快速查询完整账户余额和最近交易历史，排查资金差异原因
"""
import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv('../.env')

from binance.client import Client

api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')

if not api_key or not api_secret:
    print('ERROR: BINANCE_API_KEY or BINANCE_API_SECRET not set')
    sys.exit(1)

client = Client(api_key, api_secret)
symbol = 'BTCUSDT'
base_asset = 'BTC'
quote_asset = 'USDT'

print('=' * 70)
print('保证金账户完整诊断报告')
print(f'查询时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
print('=' * 70)
print()

# 1. 完整账户信息
print('【1】保证金账户总览')
print('-' * 70)
try:
    account = client.get_margin_account()
    print(f"总净资产 (BTC折算): {account.get('totalNetAssetOfBtc', 'N/A')} BTC")
    print(f"总负债 (BTC折算):   {account.get('totalLiabilityOfBtc', 'N/A')} BTC")
    print(f"账户状态:           {account.get('tradeEnabled', 'N/A')} (tradeEnabled)")
    print()

    # 所有资产详情
    print('【2】各资产详细余额')
    print('-' * 70)
    print(f"{'Asset':<8} {'Free':>18} {'Locked':>18} {'NetAsset':>18} {'Borrowed':>18}")
    print('-' * 70)
    for asset in account.get('userAssets', []):
        free = float(asset.get('free', 0))
        locked = float(asset.get('locked', 0))
        net = float(asset.get('netAsset', 0))
        borrowed = float(asset.get('borrowed', 0))
        if free != 0 or locked != 0 or net != 0 or borrowed != 0:
            print(f"{asset['asset']:<8} {free:>18.8f} {locked:>18.8f} {net:>18.8f} {borrowed:>18.8f}")
    print()

    # 单独高亮 BTC 和 USDT
    assets = {a['asset']: a for a in account.get('userAssets', [])}
    btc = assets.get(base_asset, {})
    usdt = assets.get(quote_asset, {})

    print('【3】BTC/USDT 重点关注')
    print('-' * 70)
    print(f"BTC  可用:   {float(btc.get('free', 0)):.8f}")
    print(f"BTC  冻结:   {float(btc.get('locked', 0)):.8f}")
    print(f"BTC  净资产: {float(btc.get('netAsset', 0)):.8f}")
    print(f"BTC  已借:   {float(btc.get('borrowed', 0)):.8f}")
    print()
    print(f"USDT 可用:   {float(usdt.get('free', 0)):.2f}")
    print(f"USDT 冻结:   {float(usdt.get('locked', 0)):.2f}")
    print(f"USDT 净资产: {float(usdt.get('netAsset', 0)):.2f}")
    print(f"USDT 已借:   {float(usdt.get('borrowed', 0)):.2f}")
    print()

except Exception as e:
    print(f'查询保证金账户失败: {e}')

# 2. 查询账户所有币对的最近成交
print('【4】最近成交记录 (全账户)')
print('-' * 70)
try:
    # 尝试获取最近24小时内的成交
    trades = client.get_margin_trades(symbol=symbol, limit=50)
    if trades:
        print(f"{'Time':<22} {'Side':<6} {'Qty':>16} {'Price':>14} {'QuoteQty':>16}")
        print('-' * 70)
        for t in trades:
            ts = datetime.fromtimestamp(t['time'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
            side = t['isBuyer'] and 'BUY' or 'SELL'
            qty = float(t['qty'])
            price = float(t['price'])
            quote_qty = float(t['quoteQty'])
            print(f"{ts:<22} {side:<6} {qty:>16.8f} {price:>14.2f} {quote_qty:>16.2f}")
    else:
        print('最近24小时内无成交记录')
except Exception as e:
    print(f'查询成交记录失败: {e}')
print()

# 3. 查询转账/借贷记录（可能导致资金变动）
print('【5】最近转账/借贷记录')
print('-' * 70)
try:
    # 最近10条转账记录
    transfers = client.get_margin_transfer_history(limit=10)
    records = transfers.get('rows', [])
    if records:
        print(f"{'Time':<22} {'Type':<12} {'Asset':<8} {'Amount':>18} {'Status':>10}")
        print('-' * 70)
        for r in records:
            ts = datetime.fromtimestamp(r['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
            tx_type = r.get('type', 'N/A')
            asset = r.get('asset', 'N/A')
            amt = float(r.get('amount', 0))
            status = r.get('status', 'N/A')
            print(f"{ts:<22} {tx_type:<12} {asset:<8} {amt:>18.8f} {status:>10}")
    else:
        print('无最近转账记录')
except Exception as e:
    print(f'查询转账记录失败: {e}')
print()

# 6. 价格参考
print('【6】当前市场价格参考')
print('-' * 70)
try:
    ticker = client.get_symbol_ticker(symbol=symbol)
    price = float(ticker['price'])
    print(f"{symbol} 最新价格: ${price:,.2f}")
    
    usdt_net = float(usdt.get('netAsset', 0)) if 'usdt' in dir() else 0
    btc_net = float(btc.get('netAsset', 0)) if 'btc' in dir() else 0
    total_usd_value = usdt_net + btc_net * price
    print(f"账户总价值估算: ${total_usd_value:,.2f} (USDT净资产 + BTC净资产×价格)")
except Exception as e:
    print(f'查询价格失败: {e}')

print()
print('=' * 70)
print('诊断完成')
print('=' * 70)
