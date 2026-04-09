"""
最小事件驱动回放引擎

替代snapshot回测，使用事件流进行更真实的回测
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
import heapq


@dataclass
class MarketEvent:
    """市场事件"""
    timestamp: int
    event_type: str  # 'trade', 'add', 'cancel', 'modify'
    side: str        # 'buy' or 'sell'
    price: float
    size: float
    order_id: Optional[str] = None


@dataclass
class Order:
    """订单"""
    order_id: str
    timestamp: int
    side: str
    price: float
    size: float
    filled_size: float = 0.0


@dataclass
class TradeResult:
    """交易结果"""
    timestamp: int
    order_id: str
    side: str
    price: float
    size: float
    slippage: float
    pnl: float = 0.0


class MinimalEventReplay:
    """
    最小事件驱动回放引擎

    特点：
    1. 基于事件流而非snapshot
    2. 维护完整订单簿状态
    3. 处理我的订单成交
    4. 支持Self-impact建模
    """

    def __init__(self):
        """初始化回放引擎"""
        self.events: List[MarketEvent] = []
        self.event_idx: int = 0

        # 订单簿状态
        self.orderbook = {
            'bids': [],  # [(price, size, order_id), ...]
            'asks': [],  # [(price, size, order_id), ...]
        }

        # 我的订单
        self.my_orders: Dict[str, Order] = {}
        self.my_trades: List[TradeResult] = []

        # 当前时间
        self.current_time: int = 0

        # 统计数据
        self.stats = {
            'events_processed': 0,
            'my_orders_submitted': 0,
            'my_orders_filled': 0,
            'my_orders_cancelled': 0
        }

    def load_events(self, events: List[MarketEvent]):
        """
        加载事件流

        Args:
            events: 市场事件列表
        """
        self.events = sorted(events, key=lambda x: x.timestamp)
        self.event_idx = 0
        print(f"Loaded {len(self.events)} events")

    def load_from_dataframe(self, df: pd.DataFrame):
        """
        从DataFrame加载事件

        期望列：timestamp, event_type, side, price, size, [order_id]
        """
        events = []
        for _, row in df.iterrows():
            event = MarketEvent(
                timestamp=int(row['timestamp']),
                event_type=row['event_type'],
                side=row['side'],
                price=float(row['price']),
                size=float(row['size']),
                order_id=row.get('order_id', f"market_{len(events)}")
            )
            events.append(event)

        self.load_events(events)

    def replay(self, strategy, max_events: Optional[int] = None) -> List[TradeResult]:
        """
        重放事件流

        Args:
            strategy: 策略对象，需实现on_event方法
            max_events: 最大处理事件数（用于测试）

        Returns:
            List[TradeResult]: 我的交易结果列表
        """
        self.my_trades = []
        self.event_idx = 0

        n_events = max_events or len(self.events)

        print(f"\nStarting replay: {n_events} events")

        while self.event_idx < n_events:
            event = self.events[self.event_idx]
            self.current_time = event.timestamp

            # 处理市场事件
            self._process_market_event(event)
            self.stats['events_processed'] += 1

            # 策略更新
            if hasattr(strategy, 'on_event'):
                action = strategy.on_event(self.orderbook, self.current_time)
                if action and action.get('action') in ['buy', 'sell']:
                    self._submit_order(action)
            elif hasattr(strategy, 'update'):
                signal = strategy.update(self.orderbook, self.current_time)
                if signal and signal.get('action') in ['buy', 'sell']:
                    self._submit_order(signal)

            self.event_idx += 1

            # 进度显示
            if self.event_idx % 10000 == 0:
                print(f"  Progress: {self.event_idx}/{n_events} events")

        print(f"\nReplay complete!")
        print(f"  Events processed: {self.stats['events_processed']}")
        print(f"  My orders submitted: {self.stats['my_orders_submitted']}")
        print(f"  My orders filled: {self.stats['my_orders_filled']}")

        return self.my_trades

    def _process_market_event(self, event: MarketEvent):
        """处理市场事件"""
        if event.event_type == 'add':
            self._add_order(event)
        elif event.event_type == 'cancel':
            self._cancel_order(event)
        elif event.event_type == 'trade':
            self._process_trade(event)
        elif event.event_type == 'modify':
            self._modify_order(event)

    def _add_order(self, event: MarketEvent):
        """添加订单到订单簿"""
        order = (event.price, event.size, event.order_id)

        if event.side == 'buy':
            self.orderbook['bids'].append(order)
            # 按价格降序排列
            self.orderbook['bids'].sort(key=lambda x: -x[0])
        else:
            self.orderbook['asks'].append(order)
            # 按价格升序排列
            self.orderbook['asks'].sort(key=lambda x: x[0])

    def _cancel_order(self, event: MarketEvent):
        """取消订单"""
        side = 'bids' if event.side == 'buy' else 'asks'

        for i, (price, size, order_id) in enumerate(self.orderbook[side]):
            if order_id == event.order_id:
                self.orderbook[side].pop(i)
                break

        # 检查是否是我的订单
        if event.order_id in self.my_orders:
            del self.my_orders[event.order_id]
            self.stats['my_orders_cancelled'] += 1

    def _process_trade(self, event: MarketEvent):
        """处理成交事件"""
        # 匹配订单簿中的订单
        if event.side == 'buy':
            # 买方成交，从asks中匹配
            self._match_order(event, 'asks')
        else:
            # 卖方成交，从bids中匹配
            self._match_order(event, 'bids')

        # 检查是否成交了我的订单
        self._check_my_order_fill(event)

    def _match_order(self, event: MarketEvent, side: str):
        """匹配订单"""
        remaining_size = event.size

        i = 0
        while i < len(self.orderbook[side]) and remaining_size > 0:
            price, size, order_id = self.orderbook[side][i]

            # 检查价格是否匹配
            if side == 'asks' and price <= event.price:
                fill_size = min(size, remaining_size)
                remaining_size -= fill_size

                # 更新订单大小
                if fill_size >= size:
                    # 完全成交，移除订单
                    self.orderbook[side].pop(i)
                else:
                    # 部分成交
                    self.orderbook[side][i] = (price, size - fill_size, order_id)
                    i += 1
            elif side == 'bids' and price >= event.price:
                fill_size = min(size, remaining_size)
                remaining_size -= fill_size

                if fill_size >= size:
                    self.orderbook[side].pop(i)
                else:
                    self.orderbook[side][i] = (price, size - fill_size, order_id)
                    i += 1
            else:
                i += 1

    def _check_my_order_fill(self, event: MarketEvent):
        """检查我的订单是否成交"""
        filled_orders = []

        for order_id, order in self.my_orders.items():
            # 检查价格和方向是否匹配
            if order.side == 'buy' and order.price >= event.price:
                fill_prob = self._calculate_fill_probability(order, event)
                if np.random.rand() < fill_prob:
                    filled_orders.append(order_id)

            elif order.side == 'sell' and order.price <= event.price:
                fill_prob = self._calculate_fill_probability(order, event)
                if np.random.rand() < fill_prob:
                    filled_orders.append(order_id)

        # 处理成交
        for order_id in filled_orders:
            if order_id in self.my_orders:
                order = self.my_orders[order_id]

                # 计算滑点
                slippage = abs(event.price - order.price)

                # 创建交易结果
                trade = TradeResult(
                    timestamp=self.current_time,
                    order_id=order_id,
                    side=order.side,
                    price=event.price,
                    size=order.size,
                    slippage=slippage
                )
                self.my_trades.append(trade)

                # 移除订单
                del self.my_orders[order_id]
                self.stats['my_orders_filled'] += 1

    def _calculate_fill_probability(self, my_order: Order, market_trade: MarketEvent) -> float:
        """计算我的订单成交概率"""
        # 基于队列位置计算
        queue_pos = self._get_queue_position(my_order)

        # 基础概率
        base_prob = 0.5

        # 队列位置惩罚（越靠后概率越低）
        queue_factor = 1.0 - (queue_pos * 0.5)

        # 时间衰减（挂单时间越长，概率越高，因为可能靠近队首）
        # time_factor = min(1.0, (self.current_time - my_order.timestamp) / 1000)

        return base_prob * queue_factor

    def _get_queue_position(self, my_order: Order) -> float:
        """获取我的订单在队列中的位置"""
        side = 'bids' if my_order.side == 'buy' else 'asks'

        # 计算价格优于我的订单数量
        better_count = 0
        my_index = -1

        for i, (price, size, order_id) in enumerate(self.orderbook[side]):
            if order_id == my_order.order_id:
                my_index = i
                break
            elif my_order.side == 'buy' and price > my_order.price:
                better_count += 1
            elif my_order.side == 'sell' and price < my_order.price:
                better_count += 1

        if my_index < 0:
            # 订单不在订单簿中（可能已被成交或取消）
            return 1.0

        # 队列位置 = 排在我前面的订单数 / 总订单数
        total_orders = len(self.orderbook[side])
        if total_orders == 0:
            return 0.0

        return better_count / total_orders

    def _modify_order(self, event: MarketEvent):
        """修改订单"""
        # 先取消原订单
        cancel_event = MarketEvent(
            timestamp=event.timestamp,
            event_type='cancel',
            side=event.side,
            price=event.price,
            size=0,
            order_id=event.order_id
        )
        self._cancel_order(cancel_event)

        # 添加新订单
        add_event = MarketEvent(
            timestamp=event.timestamp,
            event_type='add',
            side=event.side,
            price=event.price,
            size=event.size,
            order_id=event.order_id
        )
        self._add_order(add_event)

    def _submit_order(self, action: Dict):
        """提交我的订单"""
        order_id = f"my_{self.current_time}_{len(self.my_orders)}"

        # 创建订单
        order = Order(
            order_id=order_id,
            timestamp=self.current_time,
            side=action['action'],
            price=action.get('price', 50000),
            size=action.get('quantity', 0.01)
        )

        # 添加到我的订单簿
        self.my_orders[order_id] = order
        self.stats['my_orders_submitted'] += 1

        # 同时添加到市场订单簿（模拟self-impact）
        market_event = MarketEvent(
            timestamp=self.current_time,
            event_type='add',
            side=action['action'],
            price=action.get('price', 50000),
            size=action.get('quantity', 0.01),
            order_id=order_id
        )
        self._add_order(market_event)

        return order_id

    def get_orderbook_snapshot(self, depth: int = 5) -> Dict:
        """获取订单簿快照"""
        return {
            'bids': self.orderbook['bids'][:depth],
            'asks': self.orderbook['asks'][:depth],
            'timestamp': self.current_time
        }


class SimpleStrategy:
    """简单策略示例"""

    def __init__(self, threshold: float = 0.001):
        self.threshold = threshold
        self.last_price = None

    def on_event(self, orderbook: Dict, timestamp: int) -> Optional[Dict]:
        """响应事件"""
        # 获取最优买卖价
        if not orderbook['bids'] or not orderbook['asks']:
            return None

        best_bid = orderbook['bids'][0][0]
        best_ask = orderbook['asks'][0][0]
        mid_price = (best_bid + best_ask) / 2

        # 简单均值回归逻辑
        if self.last_price is not None:
            change = (mid_price - self.last_price) / self.last_price

            if change < -self.threshold:
                # 价格下跌，买入
                self.last_price = mid_price
                return {
                    'action': 'buy',
                    'price': best_bid,
                    'quantity': 0.01
                }
            elif change > self.threshold:
                # 价格上涨，卖出
                self.last_price = mid_price
                return {
                    'action': 'sell',
                    'price': best_ask,
                    'quantity': 0.01
                }

        self.last_price = mid_price
        return None


if __name__ == "__main__":
    # 测试事件驱动回放
    print("=" * 70)
    print("Event-Driven Replay Engine Test")
    print("=" * 70)

    # 创建模拟事件流
    np.random.seed(42)
    n_events = 1000

    events = []
    base_price = 50000

    for i in range(n_events):
        timestamp = i * 1000  # 毫秒

        # 随机价格变动
        price_change = np.random.normal(0, 10)
        price = base_price + price_change

        # 添加一些事件
        if i % 3 == 0:
            # 添加买单
            event = MarketEvent(
                timestamp=timestamp,
                event_type='add',
                side='buy',
                price=price - 5,
                size=np.random.uniform(0.1, 1.0),
                order_id=f"bid_{i}"
            )
            events.append(event)

        if i % 3 == 1:
            # 添加卖单
            event = MarketEvent(
                timestamp=timestamp,
                event_type='add',
                side='sell',
                price=price + 5,
                size=np.random.uniform(0.1, 1.0),
                order_id=f"ask_{i}"
            )
            events.append(event)

        if i % 10 == 0:
            # 成交事件
            event = MarketEvent(
                timestamp=timestamp,
                event_type='trade',
                side=np.random.choice(['buy', 'sell']),
                price=price,
                size=np.random.uniform(0.05, 0.5),
                order_id=f"trade_{i}"
            )
            events.append(event)

    # 创建回放引擎
    replay = MinimalEventReplay()
    replay.load_events(events)

    # 创建策略
    strategy = SimpleStrategy(threshold=0.0005)

    # 运行回放
    trades = replay.replay(strategy, max_events=500)

    print(f"\nTrades executed: {len(trades)}")
    if trades:
        print(f"Average slippage: {np.mean([t.slippage for t in trades]):.4f}")

    print("\nTest complete!")
