"""
极简队列位置优化器 (MVP版本)

核心规则：永远在队列前30%，否则撤单重排
"""

import numpy as np
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from collections import deque


@dataclass
class QueueAction:
    """队列动作"""
    action: str  # 'hold', 'post', 'cancel_and_repost'
    side: Optional[str] = None  # 'buy' or 'sell'
    target_price: Optional[float] = None
    target_queue_pos: float = 0.1  # 目标队列位置（0=队首）
    reason: str = ""


class SimpleQueueOptimizer:
    """
    极简队列优化器

    只遵循一条规则：保持在队列前30%
    """

    def __init__(self,
                 target_queue_ratio: float = 0.3,  # 目标队列位置比率
                 calibration_factor: float = 3.14,  # 校准系数（从测试中发现）
                 tick_size: float = 0.01,  # tick大小
                 max_repost_attempts: int = 3):  # 最大重排次数

        self.target_queue_ratio = target_queue_ratio
        self.calibration_factor = calibration_factor
        self.tick_size = tick_size
        self.max_repost_attempts = max_repost_attempts

        # 状态跟踪
        self.current_orders = {}  # order_id -> 订单信息
        self.repost_counts = {}  # order_id -> 重排次数
        self.queue_history = deque(maxlen=100)

        # 统计
        self.stats = {
            'total_decisions': 0,
            'hold_count': 0,
            'post_count': 0,
            'repost_count': 0,
            'avg_queue_position': 0.0
        }

    def decide(self,
               orderbook: Dict,
               current_orders: Optional[Dict] = None) -> QueueAction:
        """
        决定队列动作

        Args:
            orderbook: 订单簿数据 {'bids': [...], 'asks': [...]}
            current_orders: 当前挂单

        Returns:
            QueueAction: 队列动作
        """
        self.stats['total_decisions'] += 1

        if current_orders:
            self.current_orders = current_orders

        # 检查现有订单的队列位置
        if self.current_orders:
            worst_queue_ratio, worst_order = self._check_existing_orders(orderbook)

            # 如果队列位置不好，撤单重排
            if worst_queue_ratio > self.target_queue_ratio:
                # 检查重排次数限制
                order_id = worst_order.get('id', 'unknown')
                if self.repost_counts.get(order_id, 0) < self.max_repost_attempts:
                    self.stats['repost_count'] += 1
                    self.repost_counts[order_id] = self.repost_counts.get(order_id, 0) + 1

                    return QueueAction(
                        action='cancel_and_repost',
                        side=worst_order['side'],
                        target_price=self._calculate_optimal_price(orderbook, worst_order['side']),
                        target_queue_pos=0.1,  # 更靠前的位置
                        reason=f"queue_ratio {worst_queue_ratio:.2f} > target {self.target_queue_ratio}"
                    )
                else:
                    # 重排次数过多，观望
                    return QueueAction(
                        action='hold',
                        reason=f"max repost reached for {order_id}"
                    )

            # 队列位置良好，持有
            self.stats['hold_count'] += 1
            return QueueAction(
                action='hold',
                reason=f"queue_ratio {worst_queue_ratio:.2f} <= target"
            )

        # 没有挂单，新建订单
        self.stats['post_count'] += 1

        # 决定买卖方向（简化：根据点差方向）
        side = self._decide_side(orderbook)

        return QueueAction(
            action='post',
            side=side,
            target_price=self._calculate_optimal_price(orderbook, side),
            target_queue_pos=0.1,
            reason="new order"
        )

    def _check_existing_orders(self, orderbook: Dict) -> Tuple[float, Dict]:
        """
        检查现有订单的队列位置

        Returns:
            (最坏队列比率, 该订单信息)
        """
        worst_ratio = 0.0
        worst_order = None

        for order_id, order in self.current_orders.items():
            ratio = self._calculate_queue_ratio(orderbook, order)
            self.queue_history.append(ratio)

            if ratio > worst_ratio:
                worst_ratio = ratio
                worst_order = order

        # 更新平均队列位置统计
        if self.queue_history:
            self.stats['avg_queue_position'] = np.mean(list(self.queue_history))

        return worst_ratio, worst_order or {}

    def _calculate_queue_ratio(self, orderbook: Dict, order: Dict) -> float:
        """
        计算队列位置比率

        0.0 = 队首（最好）
        1.0 = 队尾（最差）
        """
        side = order.get('side', 'buy')
        price = order.get('price', 0)
        qty = order.get('qty', 0)

        # 获取对应方向的订单簿
        levels = orderbook.get('bids' if side == 'buy' else 'asks', [])

        if not levels:
            return 0.5  # 默认中间位置

        # 找到订单所在档位
        total_ahead = 0.0  # 前面有多少量
        total_in_level = 0.0  # 当前档位总量

        for level in levels:
            level_price = level.get('price', 0)
            level_qty = level.get('qty', 0)

            if (side == 'buy' and level_price >= price) or \
               (side == 'sell' and level_price <= price):
                # 在我们的价格或更好
                if abs(level_price - price) < self.tick_size / 2:
                    # 同一档位
                    total_in_level = level_qty
                    # 假设我们在该档位的末尾（保守估计）
                    total_ahead += level_qty
                else:
                    # 更好的档位
                    total_ahead += level_qty

        if total_in_level == 0:
            return 0.5

        # 队列位置比率
        # 考虑校准因子：实际成交率更高，意味着前面的人更快成交
        # 所以我们可以接受更靠后的位置
        adjusted_ahead = total_ahead / self.calibration_factor

        queue_ratio = adjusted_ahead / (adjusted_ahead + qty)

        return min(queue_ratio, 1.0)

    def _decide_side(self, orderbook: Dict) -> str:
        """决定买卖方向（简化版本）"""
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if not bids or not asks:
            return 'buy'

        # 简单的订单簿倾斜判断
        bid_volume = sum(b.get('qty', 0) for b in bids[:5])
        ask_volume = sum(a.get('qty', 0) for a in asks[:5])

        # 如果买方更强，我们挂买单（吃maker rebate）
        if bid_volume > ask_volume * 1.2:
            return 'buy'
        elif ask_volume > bid_volume * 1.2:
            return 'sell'

        # 默认买单
        return 'buy'

    def _calculate_optimal_price(self, orderbook: Dict, side: str) -> float:
        """计算最优挂单价格"""
        if side == 'buy':
            best_bid = orderbook.get('bids', [{}])[0].get('price', 0)
            # 排在第一档前面一个tick
            return best_bid + self.tick_size
        else:
            best_ask = orderbook.get('asks', [{}])[0].get('price', float('inf'))
            # 排在第一档前面一个tick
            return best_ask - self.tick_size

    def on_fill(self, order_id: str, fill_qty: float):
        """处理成交"""
        if order_id in self.current_orders:
            self.current_orders[order_id]['filled'] = \
                self.current_orders[order_id].get('filled', 0) + fill_qty

            # 如果完全成交，清理
            if self.current_orders[order_id]['filled'] >= \
               self.current_orders[order_id].get('qty', 0):
                del self.current_orders[order_id]
                if order_id in self.repost_counts:
                    del self.repost_counts[order_id]

    def on_cancel(self, order_id: str):
        """处理撤单"""
        if order_id in self.current_orders:
            del self.current_orders[order_id]

    def get_stats(self) -> Dict:
        """获取统计信息"""
        total = self.stats['total_decisions']
        if total == 0:
            return self.stats

        return {
            **self.stats,
            'hold_rate': self.stats['hold_count'] / total,
            'post_rate': self.stats['post_count'] / total,
            'repost_rate': self.stats['repost_count'] / total,
            'current_orders': len(self.current_orders)
        }

    def reset(self):
        """重置状态"""
        self.current_orders.clear()
        self.repost_counts.clear()
        self.queue_history.clear()
        for key in self.stats:
            if key == 'avg_queue_position':
                self.stats[key] = 0.0
            else:
                self.stats[key] = 0


# 测试代码
if __name__ == "__main__":
    print("=" * 60)
    print("Simple Queue Optimizer Test (MVP)")
    print("=" * 60)

    optimizer = SimpleQueueOptimizer(
        target_queue_ratio=0.3,
        calibration_factor=3.14
    )

    # 测试1: 新建订单
    print("\n测试1: 新建订单")
    print("-" * 60)

    orderbook = {
        'bids': [
            {'price': 50000.0, 'qty': 1.5},
            {'price': 49999.0, 'qty': 2.0},
        ],
        'asks': [
            {'price': 50001.0, 'qty': 1.0},
            {'price': 50002.0, 'qty': 2.5},
        ]
    }

    action = optimizer.decide(orderbook)
    print(f"动作: {action.action}")
    print(f"方向: {action.side}")
    print(f"目标价格: {action.target_price}")
    print(f"原因: {action.reason}")

    # 测试2: 队列位置良好的情况
    print("\n测试2: 队列位置良好（持有）")
    print("-" * 60)

    optimizer.current_orders = {
        'order_1': {
            'id': 'order_1',
            'side': 'buy',
            'price': 50000.0,
            'qty': 0.1,
            'filled': 0
        }
    }

    # 模拟我们排在很前面
    action = optimizer.decide(orderbook)
    print(f"动作: {action.action}")
    print(f"原因: {action.reason}")

    # 测试3: 队列位置不好（撤单重排）
    print("\n测试3: 队列位置不好（撤单重排）")
    print("-" * 60)

    # 创建一个很大的订单簿，让我们排在后面
    orderbook_large = {
        'bids': [
            {'price': 50000.0, 'qty': 10.0},  # 我们前面有10个BTC的量
            {'price': 49999.0, 'qty': 5.0},
        ],
        'asks': [
            {'price': 50001.0, 'qty': 1.0},
        ]
    }

    action = optimizer.decide(orderbook_large)
    print(f"动作: {action.action}")
    print(f"方向: {action.side}")
    print(f"原因: {action.reason}")

    # 测试4: 统计信息
    print("\n测试4: 统计信息")
    print("-" * 60)

    stats = optimizer.get_stats()
    print(f"总决策数: {stats['total_decisions']}")
    print(f"持有次数: {stats['hold_count']} ({stats['hold_rate']:.1%})")
    print(f"新建订单: {stats['post_count']} ({stats['post_rate']:.1%})")
    print(f"撤单重排: {stats['repost_count']} ({stats['repost_rate']:.1%})")
    print(f"平均队列位置: {stats['avg_queue_position']:.3f}")

    print("\n" + "=" * 60)
    print("测试完成")
