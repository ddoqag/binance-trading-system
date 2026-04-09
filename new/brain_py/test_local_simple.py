"""简化测试本地交易模块"""
import sys
sys.path.insert(0, '.')

from local_trading.data_source import SyntheticDataSource
from local_trading.execution_engine import LocalExecutionEngine
from local_trading.portfolio import LocalPortfolio
from datetime import datetime

print('='*60)
print('简化本地交易测试')
print('='*60)

# 创建数据
data_source = SyntheticDataSource(n_ticks=50)
ticks = data_source.get_ticks()
print(f'数据: {len(ticks)} ticks')

# 创建执行引擎和投资组合
engine = LocalExecutionEngine()
portfolio = LocalPortfolio(initial_capital=1000.0)

# 模拟几个交易
for i, tick in enumerate(ticks[:20]):
    # 每5个tick尝试一次买入
    if i % 5 == 0:
        print(f'\nTick {i}: 价格=${tick.mid_price:.2f}')

        # 尝试买入
        result = engine.execute_limit_order(
            side='buy',
            qty=0.01,
            price=tick.bid_price,
            tick=tick,
            queue_position=0.3
        )

        print(f'  执行结果: success={result.success}, qty={result.filled_qty}')

        if result.success and result.filled_qty > 0:
            # 更新投资组合
            trade = portfolio.execute_trade(
                symbol='BTCUSDT',
                side='buy',
                qty=result.filled_qty,
                price=result.filled_price,
                fee=result.fee,
                timestamp=tick.timestamp
            )
            if trade:
                print(f'  交易记录: {trade.side} {trade.qty} @ ${trade.price:.2f}')

    # 更新价格
    portfolio.update(tick.timestamp, tick.mid_price)

print('\n' + '='*60)
print('最终报告')
print('='*60)
stats = portfolio.get_statistics()
print(f'总交易: {stats["total_trades"]}')
print(f'持仓: {portfolio.positions}')
print(f'现金: ${portfolio.cash:.2f}')
print(f'权益: ${portfolio.get_total_equity():.2f}')
