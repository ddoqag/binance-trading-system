import os
from dotenv import load_dotenv
load_dotenv('../.env')

from binance.client import Client

client = Client(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'))

# 获取交易规则
info = client.get_symbol_info('DOGEUSDT')
tick_size = None
step_size = None
min_notional = None
for f in info.get('filters', []):
    if f['filterType'] == 'PRICE_FILTER':
        tick_size = float(f['tickSize'])
    if f['filterType'] == 'LOT_SIZE':
        step_size = float(f['stepSize'])
    if f['filterType'] == 'MIN_NOTIONAL':
        min_notional = float(f['minNotional'])

price = float(client.get_symbol_ticker(symbol='DOGEUSDT')['price'])
capital = 10.10
max_pos = capital / price * 0.95
maker_fee_rate = 0.0002
taker_fee_rate = 0.0005

print(f'DOGEUSDT Price: ${price:.5f}')
print(f'Tick Size: {tick_size}')
print(f'Step Size: {step_size}')
print(f'Min Notional: {min_notional}')
print(f'Capital: ${capital:.2f}')
print(f'Max Position: {max_pos:.2f} DOGE')
print()

# 1-tick profit
gross_profit_1tick = max_pos * tick_size if tick_size else 0
maker_cost = capital * maker_fee_rate * 2
taker_cost = capital * taker_fee_rate * 2

print(f'1-tick gross profit: ${gross_profit_1tick:.6f}')
print(f'Maker fee (2-way): ${maker_cost:.6f}')
print(f'Taker fee (2-way): ${taker_cost:.6f}')
print(f'1-tick Maker net: ${gross_profit_1tick - maker_cost:.6f}')
print(f'1-tick Taker net: ${gross_profit_1tick - taker_cost:.6f}')
print()

# Break-even price move
if max_pos > 0:
    break_even_maker = maker_cost / max_pos
    break_even_taker = taker_cost / max_pos
    print(f'Break-even price move (Maker): ${break_even_maker:.5f} ({break_even_maker/price*100:.4f}%)')
    print(f'Break-even price move (Taker): ${break_even_taker:.5f} ({break_even_taker/price*100:.4f}%)')
    print(f'Required ticks (Maker): {break_even_maker/tick_size:.1f}')
    print(f'Required ticks (Taker): {break_even_taker/tick_size:.1f}')

# Compare with BTC
btc_price = 70943.29
btc_max_pos = capital / btc_price * 0.95
btc_tick = 0.01
btc_gross = btc_max_pos * btc_tick
print()
print('--- Comparison with BTC ---')
print(f'BTC 1-tick gross: ${btc_gross:.6f}')
print(f'DOGE 1-tick gross: ${gross_profit_1tick:.6f}')
print(f'Improvement: {gross_profit_1tick/btc_gross:.0f}x')
