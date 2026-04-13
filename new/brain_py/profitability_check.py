# 数学验证当前盈利可行性
price = 70943.29
capital = 10.10
max_pos = capital / price * 0.95  # ~0.000135 BTC
maker_fee_rate = 0.0002
taker_fee_rate = 0.0005
tick_size = 0.01

# 1-tick 盈利（假设能买到并立即以+1tick卖出）
gross_profit_1tick = max_pos * tick_size
maker_cost = capital * maker_fee_rate * 2
taker_cost = capital * taker_fee_rate * 2

print(f'本金: ${capital:.2f}')
print(f'最大仓位: {max_pos:.6f} BTC')
print(f'1-tick 毛利: ${gross_profit_1tick:.6f}')
print(f'Maker 手续费(双边): ${maker_cost:.6f}')
print(f'Taker 手续费(双边): ${taker_cost:.6f}')
print(f'1-tick Maker 净利: ${gross_profit_1tick - maker_cost:.6f}')
print(f'1-tick Taker 净利: ${gross_profit_1tick - taker_cost:.6f}')
print()
# 需要多少价格变动才能盈亏平衡
break_even_maker = maker_cost / max_pos
break_even_taker = taker_cost / max_pos
print(f'盈亏平衡所需价格变动 (Maker): ${break_even_maker:.2f} ({break_even_maker/price*100:.4f}%)')
print(f'盈亏平衡所需价格变动 (Taker): ${break_even_taker:.2f} ({break_even_taker/price*100:.4f}%)')
