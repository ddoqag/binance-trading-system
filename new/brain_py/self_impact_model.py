"""
自我影响建模

建模我的订单如何改变市场行为
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
import time


@dataclass
class MarketResponse:
    """市场对我的订单的反应"""
    price_impact: float
    queue_jump_probability: float
    spoofing_probability: float
    cancellation_rate_change: float
    spread_widening: float


class SelfImpactModel:
    """
    自我影响建模

    建模我的订单如何改变市场：
    1. 价格冲击（大额订单推动价格）
    2. 队列跳跃（别人在我前面插队）
    3. 诱骗检测（频繁撤单被识别）
    4. 撤单率变化（我的存在改变市场行为）
    5. 点差扩大（市场对我的反应）
    """

    def __init__(self, market_sensitivity: float = 0.3):
        """
        初始化自我影响模型

        Args:
            market_sensitivity: 市场对我的订单的敏感度 (0-1)
                              0 = 完全忽略我的订单
                              1 = 高度关注我的订单
        """
        self.market_sensitivity = market_sensitivity
        self.my_order_history: List[Dict] = []
        self.market_response_history: List[MarketResponse] = []

    def add_my_order(self, order: Dict):
        """记录我的订单"""
        self.my_order_history.append({
            'timestamp': order.get('timestamp', time.time()),
            'side': order['side'],
            'price': order['price'],
            'size': order['size'],
            'order_id': order.get('order_id')
        })

    def predict_market_response(self, my_order: Dict, current_market: Dict) -> MarketResponse:
        """
        预测市场对我的订单的反应

        Args:
            my_order: 我的订单信息
            current_market: 当前市场状态

        Returns:
            MarketResponse: 市场反应预测
        """
        response = MarketResponse(
            price_impact=0.0,
            queue_jump_probability=0.0,
            spoofing_probability=0.0,
            cancellation_rate_change=0.0,
            spread_widening=0.0
        )

        # 1. 价格冲击
        response.price_impact = self._calculate_price_impact(my_order, current_market)

        # 2. 队列跳跃概率
        response.queue_jump_probability = self._calculate_queue_jump_prob(my_order, current_market)

        # 3. 诱骗概率
        response.spoofing_probability = self._calculate_spoofing_prob(my_order)

        # 4. 撤单率变化
        response.cancellation_rate_change = self._calculate_cancel_rate_change(my_order)

        # 5. 点差扩大
        response.spread_widening = self._calculate_spread_widening(my_order, current_market)

        return response

    def _calculate_price_impact(self, my_order: Dict, market: Dict) -> float:
        """计算价格冲击"""
        # 获取平均交易大小
        avg_trade_size = market.get('avg_trade_size', 1.0)

        # 如果我的订单远大于平均，会产生价格冲击
        size_ratio = my_order['size'] / avg_trade_size if avg_trade_size > 0 else 1.0

        if size_ratio > 3:
            # 大额订单产生价格冲击
            impact = 0.0001 * size_ratio * self.market_sensitivity  # 0.01% * 倍数

            if my_order['side'] == 'buy':
                return impact  # 买入推高价格
            else:
                return -impact  # 卖出压低价格

        return 0.0

    def _calculate_queue_jump_prob(self, my_order: Dict, market: Dict) -> float:
        """计算队列跳跃概率（别人在我前面插队的概率）"""
        # 估算我的队列位置
        queue_pos = self._estimate_queue_position(my_order, market)

        if queue_pos < 0.2:
            # 我在很前面，别人可能插队
            base_prob = 0.15
        elif queue_pos < 0.5:
            base_prob = 0.08
        else:
            base_prob = 0.03

        # 根据订单大小调整
        size_factor = min(1.0, my_order['size'] / 1.0)

        return base_prob * size_factor * self.market_sensitivity

    def _calculate_spoofing_prob(self, my_order: Dict) -> float:
        """计算被识别为诱骗（spoofing）的概率"""
        # 检查我最近10个订单的撤单率
        recent_orders = [o for o in self.my_order_history
                        if o['timestamp'] > time.time() - 60]  # 最近1分钟

        if len(recent_orders) < 3:
            return 0.0

        # 简单模型：如果订单频繁更换，可能被识别为spoofing
        recent_cancels = len([o for o in recent_orders
                             if o.get('cancelled', False)])

        cancel_rate = recent_cancels / len(recent_orders)

        if cancel_rate > 0.7 and len(recent_orders) > 5:
            return 0.2 * self.market_sensitivity

        return 0.0

    def _calculate_cancel_rate_change(self, my_order: Dict) -> float:
        """计算我的订单对市场撤单率的影响"""
        # 如果我挂大单，市场可能增加撤单
        avg_size = np.mean([o['size'] for o in self.my_order_history[-10:]]) \
                   if len(self.my_order_history) >= 10 else 1.0

        if my_order['size'] > avg_size * 2:
            return 0.1 * self.market_sensitivity  # 撤单率增加10%

        return 0.0

    def _calculate_spread_widening(self, my_order: Dict, market: Dict) -> float:
        """计算点差扩大"""
        current_spread = market.get('spread', 0)

        # 大额订单可能导致点差扩大
        avg_trade_size = market.get('avg_trade_size', 1.0)
        size_ratio = my_order['size'] / avg_trade_size if avg_trade_size > 0 else 1.0

        if size_ratio > 2:
            widening = 0.00005 * size_ratio * self.market_sensitivity  # 0.005 bps
            return min(widening, current_spread * 0.5)  # 最多扩大50%

        return 0.0

    def _estimate_queue_position(self, my_order: Dict, market: Dict) -> float:
        """估算我的队列位置"""
        side = 'bids' if my_order['side'] == 'buy' else 'asks'

        orders = market.get(side, [])
        if not orders:
            return 0.5

        # 计算价格优于我的订单数量
        better_count = 0
        for price, size, _ in orders:
            if my_order['side'] == 'buy' and price > my_order['price']:
                better_count += 1
            elif my_order['side'] == 'sell' and price < my_order['price']:
                better_count += 1

        total = len(orders)
        if total == 0:
            return 0.0

        return better_count / total

    def apply_market_response(self, orderbook: Dict, response: MarketResponse) -> Dict:
        """
        应用市场反应到订单簿

        Args:
            orderbook: 当前订单簿
            response: 市场反应

        Returns:
            Dict: 更新后的订单簿
        """
        orderbook = orderbook.copy()

        # 1. 价格冲击
        if response.price_impact != 0:
            impact_factor = 1 + response.price_impact

            # 调整所有价格
            orderbook['bids'] = [
                (price * impact_factor, size, order_id)
                for price, size, order_id in orderbook['bids']
            ]
            orderbook['asks'] = [
                (price * impact_factor, size, order_id)
                for price, size, order_id in orderbook['asks']
            ]

        # 2. 队列跳跃
        if np.random.rand() < response.queue_jump_probability:
            self._add_queue_jump(orderbook)

        # 3. 点差扩大
        if response.spread_widening > 0 and orderbook['bids'] and orderbook['asks']:
            best_bid = orderbook['bids'][0][0]
            best_ask = orderbook['asks'][0][0]

            # 扩大点差
            orderbook['bids'][0] = (
                best_bid * (1 - response.spread_widening),
                orderbook['bids'][0][1],
                orderbook['bids'][0][2]
            )
            orderbook['asks'][0] = (
                best_ask * (1 + response.spread_widening),
                orderbook['asks'][0][1],
                orderbook['asks'][0][2]
            )

        return orderbook

    def _add_queue_jump(self, orderbook: Dict):
        """添加插队订单"""
        # 随机选择在bid或ask插队
        if np.random.rand() < 0.5 and orderbook.get('bids'):
            # 在买单前插队
            best_bid_price = orderbook['bids'][0][0]
            jump_price = best_bid_price * 1.0001  # 高一点点
            jump_size = np.random.uniform(0.1, 1.0)

            orderbook['bids'].insert(0, (
                jump_price,
                jump_size,
                f"jump_{int(time.time() * 1000)}"
            ))

        elif orderbook.get('asks'):
            # 在卖单前插队
            best_ask_price = orderbook['asks'][0][0]
            jump_price = best_ask_price * 0.9999  # 低一点点
            jump_size = np.random.uniform(0.1, 1.0)

            orderbook['asks'].insert(0, (
                jump_price,
                jump_size,
                f"jump_{int(time.time() * 1000)}"
            ))

    def calculate_impact_score(self, trades: List[Dict]) -> float:
        """
        计算自我影响分数（0-100，越高影响越大）

        Args:
            trades: 交易列表

        Returns:
            float: 影响分数
        """
        if not trades:
            return 0.0

        impacts = []
        for trade in trades:
            response = self.predict_market_response(trade, {})
            impacts.append(response)

        # 价格冲击分数
        price_impacts = [abs(i.price_impact) for i in impacts]
        price_score = min(100, np.mean(price_impacts) * 10000) if price_impacts else 0

        # 队列跳跃分数
        jump_probs = [i.queue_jump_probability for i in impacts]
        jump_score = min(100, np.mean(jump_probs) * 200) if jump_probs else 0

        # 点差扩大分数
        spread_widening = [i.spread_widening for i in impacts]
        spread_score = min(100, np.mean(spread_widening) * 10000) if spread_widening else 0

        # 综合分数
        total_score = 0.5 * price_score + 0.3 * jump_score + 0.2 * spread_score

        return min(100, total_score)

    def get_impact_summary(self) -> Dict:
        """获取影响汇总"""
        if not self.market_response_history:
            return {
                'status': 'No data',
                'total_orders': len(self.my_order_history),
                'impact_score': 0.0
            }

        price_impacts = [r.price_impact for r in self.market_response_history]
        jump_probs = [r.queue_jump_probability for r in self.market_response_history]

        return {
            'avg_price_impact': np.mean(price_impacts),
            'max_price_impact': np.max(price_impacts),
            'avg_queue_jump_prob': np.mean(jump_probs),
            'total_orders': len(self.my_order_history),
            'impact_score': self.calculate_impact_score(self.my_order_history)
        }


if __name__ == "__main__":
    # 测试自我影响模型
    print("=" * 70)
    print("Self-Impact Model Test")
    print("=" * 70)

    model = SelfImpactModel(market_sensitivity=0.5)

    # 模拟几个订单
    orders = [
        {'side': 'buy', 'price': 50000, 'size': 0.5, 'timestamp': time.time()},
        {'side': 'buy', 'price': 50000, 'size': 2.0, 'timestamp': time.time() + 1},  # 大订单
        {'side': 'sell', 'price': 50010, 'size': 0.3, 'timestamp': time.time() + 2},
        {'side': 'buy', 'price': 50000, 'size': 3.0, 'timestamp': time.time() + 3},  # 超大订单
    ]

    market = {
        'bids': [(49995, 1.0, 'bid1'), (49990, 2.0, 'bid2')],
        'asks': [(50010, 1.0, 'ask1'), (50015, 2.0, 'ask2')],
        'avg_trade_size': 0.5,
        'spread': 15
    }

    print("\nPredicting market responses:")
    for i, order in enumerate(orders):
        model.add_my_order(order)
        response = model.predict_market_response(order, market)

        print(f"\nOrder {i+1}: {order['side']} {order['size']} @ {order['price']}")
        print(f"  Price impact: {response.price_impact:.6f}")
        print(f"  Queue jump prob: {response.queue_jump_probability:.3f}")
        print(f"  Spoofing prob: {response.spoofing_probability:.3f}")
        print(f"  Spread widening: {response.spread_widening:.6f}")

    # 汇总
    summary = model.get_impact_summary()
    print(f"\n{'=' * 70}")
    print("Summary:")
    print(f"  Total orders: {summary['total_orders']}")
    print(f"  Avg price impact: {summary['avg_price_impact']:.6f}")
    print(f"  Impact score: {summary['impact_score']:.1f}/100")

    print("\nTest complete!")
