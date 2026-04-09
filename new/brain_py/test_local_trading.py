"""测试本地交易模块"""
import sys
sys.path.insert(0, '.')

from local_trading import LocalTrader, LocalTradingConfig

config = LocalTradingConfig(
    symbol='BTCUSDT',
    initial_capital=1000.0,
    queue_target_ratio=0.2,
    toxic_threshold=0.35,
    min_spread_ticks=3
)

trader = LocalTrader(config)
trader.load_data(n_ticks=200)

print('='*60)
print('本地交易模块测试')
print('='*60)
print(f'数据加载: {len(trader.data_source.data)} ticks')

result = trader.run_backtest(progress_interval=50)

print(f'\n回测完成!')
print(f'总交易: {result.total_trades}')
print(f'盈利交易: {result.winning_trades}')
print(f'亏损交易: {result.losing_trades}')
print(f'总收益: {result.total_return_pct*100:.2f}%')
print(f'夏普比率: {result.sharpe_ratio:.2f}')

# 检查统计信息
print(f'\n详细统计:')
for k, v in result.statistics.items():
    print(f'  {k}: {v}')
