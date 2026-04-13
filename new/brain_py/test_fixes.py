"""
快速验证修复后的核心逻辑
"""
from mvp import SpreadCapture
from mvp_trader import MVPTrader

print("=== Test 1: SpreadCapture net profit check ===")
sc = SpreadCapture(min_spread_ticks=1, tick_size=0.00001, maker_rebate=0.0002)

# DOGEUSDT-like: price ~0.0916, spread = 1 tick = 0.00001
orderbook = {
    'bids': [{'price': 0.09160, 'qty': 1000}],
    'asks': [{'price': 0.09161, 'qty': 1000}]
}
opp = sc.analyze(orderbook, current_position=0)
print(f"1-tick spread: is_profitable={opp.is_profitable}, profit={opp.net_profit_bps:.2f}bps, reason={opp.reason}")
assert not opp.is_profitable, "1-tick should NOT be profitable after fee fix!"

# 5-tick spread = 0.00005
orderbook2 = {
    'bids': [{'price': 0.09160, 'qty': 1000}],
    'asks': [{'price': 0.09165, 'qty': 1000}]
}
opp2 = sc.analyze(orderbook2, current_position=0)
print(f"5-tick spread: is_profitable={opp2.is_profitable}, profit={opp2.net_profit_bps:.2f}bps, reason={opp2.reason}")

print("\n=== Test 2: Pending orders clear on sync ===")
trader = MVPTrader(symbol="DOGEUSDT", initial_capital=10.0, max_position=100.0, tick_size=0.00001, step_size=1.0)
trader.pending_orders['test_1'] = {'side': 'buy', 'qty': 10}
trader.pending_orders['test_2'] = {'side': 'sell', 'qty': 10}
assert len(trader.pending_orders) == 2
# Sync with same position should still clear pending orders
trader.update_account_info(current_position=0.0)
assert len(trader.pending_orders) == 0, "Pending orders should be cleared on every sync!"
print("Pending orders correctly cleared on sync (even position unchanged)")

print("\n=== Test 3: Constraint config ===")
assert trader.constraints.config.max_daily_trades == 50
assert trader.constraints.config.kill_switch_loss == -5.0
assert trader.constraints.config.max_order_rate == 2.0
print("Constraint config correctly updated: max_daily_trades=50, kill_switch=-5, order_rate=2/sec")

print("\nAll tests passed")
