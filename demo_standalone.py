#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独立演示脚本 - 不依赖外部库
展示策略逻辑和系统架构
"""

import json
from datetime import datetime, timedelta
import math


class SimpleDataGenerator:
    """简单数据生成器 - 生成模拟价格数据"""

    def __init__(self, start_price: float = 50000, volatility: float = 0.005):
        self.start_price = start_price
        self.volatility = volatility

    def generate(self, hours: int = 500) -> list:
        """生成模拟 K 线数据"""
        data = []
        current_time = datetime.now() - timedelta(hours=hours)
        price = self.start_price

        for i in range(hours):
            # 随机游走 + 轻微趋势
            change = (math.sin(i / 50) * 0.001 +
                     (i * 0.00001) +
                     (math.random() if hasattr(math, 'random') else 0) * self.volatility * 2 - self.volatility)
            price = price * (1 + change)

            open_p = price * (1 - self.volatility / 4)
            high_p = price * (1 + self.volatility / 2)
            low_p = price * (1 - self.volatility / 2)
            close_p = price
            volume = 1000 + (math.random() if hasattr(math, 'random') else 0) * 5000

            data.append({
                'open_time': current_time.isoformat(),
                'open': open_p,
                'high': high_p,
                'low': low_p,
                'close': close_p,
                'volume': volume
            })

            current_time += timedelta(hours=1)

        return data


class MovingAverage:
    """简单移动平均计算"""

    @staticmethod
    def sma(data: list, window: int, key: str = 'close') -> list:
        """计算简单移动平均"""
        result = []
        for i in range(len(data)):
            if i < window - 1:
                result.append(None)
            else:
                total = sum(item[key] for item in data[i - window + 1:i + 1])
                result.append(total / window)
        return result


class DualMAStrategy:
    """双均线策略"""

    def __init__(self, short_window: int = 10, long_window: int = 30):
        self.short_window = short_window
        self.long_window = long_window

    def generate_signals(self, data: list) -> list:
        """生成交易信号"""
        # 计算均线
        ma_short = MovingAverage.sma(data, self.short_window)
        ma_long = MovingAverage.sma(data, self.long_window)

        signals = []
        position = 0  # 0 = 空仓, 1 = 持仓

        for i in range(len(data)):
            item = data[i].copy()
            item['ma_short'] = ma_short[i]
            item['ma_long'] = ma_long[i]
            item['signal'] = 0
            item['position_change'] = 0

            if ma_short[i] is not None and ma_long[i] is not None:
                # 金叉：短期均线上穿长期均线
                if ma_short[i] > ma_long[i] and position == 0:
                    item['signal'] = 1
                    item['position_change'] = 1
                    position = 1
                # 死叉：短期均线下穿长期均线
                elif ma_short[i] < ma_long[i] and position == 1:
                    item['signal'] = -1
                    item['position_change'] = -1
                    position = 0
                # 持仓中
                elif position == 1:
                    item['signal'] = 1

            signals.append(item)

        return signals


class BacktestEngine:
    """简单回测引擎"""

    def __init__(self, initial_capital: float = 10000, commission: float = 0.001):
        self.initial_capital = initial_capital
        self.commission = commission

    def run(self, data: list) -> dict:
        """运行回测"""
        cash = self.initial_capital
        position = 0
        entry_price = 0
        trades = []
        portfolio_history = []

        for item in data:
            price = item['close']
            signal = item.get('signal', 0)
            position_change = item.get('position_change', 0)

            # 记录组合价值
            current_value = cash + position * price
            portfolio_history.append({
                'date': item['open_time'],
                'price': price,
                'cash': cash,
                'position': position,
                'total_value': current_value
            })

            # 交易逻辑
            if position_change == 1:  # 买入
                shares = cash * (1 - self.commission) / price
                cost = shares * price
                comm_fee = cost * self.commission
                cash -= (cost + comm_fee)
                position = shares
                entry_price = price
                trades.append({
                    'date': item['open_time'],
                    'action': 'BUY',
                    'price': price,
                    'shares': shares
                })

            elif position_change == -1:  # 卖出
                revenue = position * price
                comm_fee = revenue * self.commission
                cash += (revenue - comm_fee)
                trades.append({
                    'date': item['open_time'],
                    'action': 'SELL',
                    'price': price,
                    'shares': position,
                    'pnl': (price - entry_price) * position
                })
                position = 0

        # 计算最终结果
        final_price = data[-1]['close'] if data else 0
        final_value = cash + position * final_price
        total_return = (final_value - self.initial_capital) / self.initial_capital if self.initial_capital > 0 else 0

        return {
            'initial_capital': self.initial_capital,
            'final_value': final_value,
            'total_return': total_return,
            'total_trades': len(trades) // 2,
            'trades': trades,
            'portfolio_history': portfolio_history
        }


def print_header(text: str):
    """打印标题"""
    print("\n" + "="*60)
    print(f"  {text}")
    print("="*60)


def main():
    """主函数"""
    print_header("币安量化交易系统 - 独立演示")

    # 1. 生成模拟数据
    print_header("1. 生成模拟数据")
    generator = SimpleDataGenerator(start_price=50000, volatility=0.005)
    data = generator.generate(hours=500)
    print(f"  数据点数: {len(data)}")
    print(f"  起始价格: {data[0]['close']:.2f}")
    print(f"  结束价格: {data[-1]['close']:.2f}")

    # 2. 创建策略
    print_header("2. 创建双均线策略")
    strategy = DualMAStrategy(short_window=10, long_window=30)
    print(f"  短期均线: {strategy.short_window} 周期")
    print(f"  长期均线: {strategy.long_window} 周期")

    # 3. 生成信号
    print_header("3. 生成交易信号")
    signals = strategy.generate_signals(data)

    buy_count = sum(1 for s in signals if s.get('position_change') == 1)
    sell_count = sum(1 for s in signals if s.get('position_change') == -1)
    print(f"  买入信号: {buy_count}")
    print(f"  卖出信号: {sell_count}")

    # 4. 运行回测
    print_header("4. 运行回测")
    engine = BacktestEngine(initial_capital=10000, commission=0.001)
    results = engine.run(signals)

    # 5. 打印结果
    print_header("5. 回测结果")
    print(f"  初始资金: ${results['initial_capital']:,.2f}")
    print(f"  最终资金: ${results['final_value']:,.2f}")
    print(f"  总收益率: {results['total_return']*100:+.2f}%")
    print(f"  交易次数: {results['total_trades']}")

    # 6. 打印交易记录
    if results['trades']:
        print_header("6. 交易记录")
        for i, trade in enumerate(results['trades'][:10]):  # 只显示前10笔
            print(f"  {i+1}. {trade['date'][:19]} {trade['action']:4s} @ ${trade['price']:,.2f}")
        if len(results['trades']) > 10:
            print(f"  ... 还有 {len(results['trades']) - 10} 笔交易")

    # 7. 模块架构说明
    print_header("7. 系统架构说明")
    print("""
  项目已创建以下模块:

  trading/      - 交易执行模块
    ├── order.py        - 订单类型和状态
    └── execution.py    - 交易执行器

  strategy/     - 策略模块
    ├── base.py         - 策略基类
    ├── dual_ma.py      - 双均线策略
    ├── rsi_strategy.py - RSI 策略
    └── ml_strategy.py  - ML 策略

  risk/         - 风险控制模块
    ├── manager.py      - 综合风险管理
    ├── position.py     - 仓位管理
    └── stop_loss.py    - 止损止盈

  models/       - ML 模型模块
    ├── features.py     - 特征工程
    ├── predictor.py    - 价格预测
    └── model_trainer.py - 模型训练

  utils/        - 工具模块
    ├── helpers.py      - 工具函数
    └── database.py     - 数据库客户端
    """)

    print_header("演示完成")


if __name__ == '__main__':
    # 为了不依赖 random 模块，我们添加一个简单的随机函数
    if not hasattr(math, 'random'):
        import time
        def simple_random():
            t = time.time()
            return (t * 1000 % 1000) / 1000
        math.random = simple_random

    main()
