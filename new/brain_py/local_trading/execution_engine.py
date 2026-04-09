"""
本地执行引擎

模拟交易所执行行为:
- 订单簿撮合
- 滑点模拟
- 手续费计算
- 成交概率模型
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import logging

from .data_source import TickData

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """执行结果"""
    order_id: str
    success: bool
    filled_qty: float
    filled_price: float
    fee: float
    slippage_bps: float
    timestamp: datetime
    error_message: Optional[str] = None


class LocalExecutionEngine:
    """
    本地执行引擎

    模拟真实交易所的成交行为
    """

    def __init__(self,
                 maker_fee: float = 0.0002,    # 0.02%
                 taker_fee: float = 0.0005,    # 0.05%
                 slippage_model: str = "adaptive"):
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee
        self.slippage_model = slippage_model

        self.order_counter = 0
        self.executed_orders: List[Dict] = []

    def execute_limit_order(self,
                           side: str,
                           qty: float,
                           price: float,
                           tick: TickData,
                           queue_position: float = 0.3) -> ExecutionResult:
        """
        执行限价单

        Args:
            side: 'buy' 或 'sell'
            qty: 数量
            price: 限价价格
            tick: 当前tick数据
            queue_position: 队列位置 (0-1, 0=队首)

        Returns:
            ExecutionResult
        """
        self.order_counter += 1
        order_id = f"local_{self.order_counter}"

        # 检查价格是否满足条件
        if side == 'buy':
            if price < tick.bid_price:
                # 买单价格低于买一价，不会成交
                return ExecutionResult(
                    order_id=order_id,
                    success=False,
                    filled_qty=0,
                    filled_price=0,
                    fee=0,
                    slippage_bps=0,
                    timestamp=tick.timestamp,
                    error_message="Price below best bid"
                )
        else:  # sell
            if price > tick.ask_price:
                # 卖单价格高于卖一价，不会成交
                return ExecutionResult(
                    order_id=order_id,
                    success=False,
                    filled_qty=0,
                    filled_price=0,
                    fee=0,
                    slippage_bps=0,
                    timestamp=tick.timestamp,
                    error_message="Price above best ask"
                )

        # 模拟成交概率
        # 基于队列位置和流动性
        fill_probability = self._calculate_fill_probability(
            queue_position, tick.spread_bps, tick.bid_qty, tick.ask_qty, side
        )

        if np.random.random() > fill_probability:
            # 未成交
            return ExecutionResult(
                order_id=order_id,
                success=False,
                filled_qty=0,
                filled_price=0,
                fee=0,
                slippage_bps=0,
                timestamp=tick.timestamp,
                error_message="Not filled"
            )

        # 计算成交价格（带滑点）
        filled_price, slippage_bps = self._calculate_fill_price(
            side, price, tick, is_maker=True
        )

        # 计算手续费
        fee = qty * filled_price * self.maker_fee

        # 记录
        self.executed_orders.append({
            'order_id': order_id,
            'side': side,
            'qty': qty,
            'price': price,
            'filled_price': filled_price,
            'fee': fee,
            'timestamp': tick.timestamp
        })

        return ExecutionResult(
            order_id=order_id,
            success=True,
            filled_qty=qty,
            filled_price=filled_price,
            fee=fee,
            slippage_bps=slippage_bps,
            timestamp=tick.timestamp
        )

    def execute_market_order(self,
                            side: str,
                            qty: float,
                            tick: TickData) -> ExecutionResult:
        """执行市价单"""
        self.order_counter += 1
        order_id = f"local_market_{self.order_counter}"

        # 市价单立即成交
        base_price = tick.ask_price if side == 'buy' else tick.bid_price

        # 计算成交价格（带滑点）
        filled_price, slippage_bps = self._calculate_fill_price(
            side, base_price, tick, is_maker=False
        )

        # 计算手续费
        fee = qty * filled_price * self.taker_fee

        # 记录
        self.executed_orders.append({
            'order_id': order_id,
            'side': side,
            'qty': qty,
            'price': base_price,
            'filled_price': filled_price,
            'fee': fee,
            'timestamp': tick.timestamp
        })

        return ExecutionResult(
            order_id=order_id,
            success=True,
            filled_qty=qty,
            filled_price=filled_price,
            fee=fee,
            slippage_bps=slippage_bps,
            timestamp=tick.timestamp
        )

    def _calculate_fill_probability(self,
                                    queue_position: float,
                                    spread_bps: float,
                                    bid_qty: float,
                                    ask_qty: float,
                                    side: str) -> float:
        """
        计算成交概率

        基于:
        - 队列位置 (越靠前概率越高)
        - 点差大小 (点差越大概率越高)
        - 流动性深度
        """
        # 基础概率
        base_prob = 0.7

        # 队列位置影响
        queue_factor = 1.0 - queue_position  # 0=队首(1.0), 1=队尾(0.0)

        # 点差影响
        spread_factor = min(spread_bps / 10.0, 1.0)  # 10bps以上得满分

        # 流动性影响
        if side == 'buy':
            liquidity = ask_qty
        else:
            liquidity = bid_qty
        liquidity_factor = min(liquidity / 5.0, 1.0)

        # 综合概率
        prob = base_prob * (0.4 + 0.6 * queue_factor) * \
               (0.7 + 0.3 * spread_factor) * \
               (0.8 + 0.2 * liquidity_factor)

        return min(prob, 0.95)  # 最高95%

    def _calculate_fill_price(self,
                             side: str,
                             price: float,
                             tick: TickData,
                             is_maker: bool = True) -> Tuple[float, float]:
        """
        计算成交价格

        Returns:
            (filled_price, slippage_bps)
        """
        if self.slippage_model == "adaptive":
            # 自适应滑点模型
            base_slippage = tick.spread_bps * 0.1  # 点差的10%

            if not is_maker:
                # 市价单滑点更大
                base_slippage *= 2.0

            # 添加随机成分
            slippage = base_slippage * np.random.uniform(0.5, 1.5)

        else:  # fixed
            slippage = 0.5  # 固定0.5 bps

        # 应用滑点
        if side == 'buy':
            filled_price = price * (1 + slippage / 10000)
        else:
            filled_price = price * (1 - slippage / 10000)

        return filled_price, slippage

    def get_statistics(self) -> Dict:
        """获取执行统计"""
        if not self.executed_orders:
            return {
                'total_orders': 0,
                'total_volume': 0,
                'total_fees': 0,
                'avg_slippage_bps': 0
            }

        total_volume = sum(o['qty'] * o['filled_price'] for o in self.executed_orders)
        total_fees = sum(o['fee'] for o in self.executed_orders)

        return {
            'total_orders': len(self.executed_orders),
            'total_volume': total_volume,
            'total_fees': total_fees,
            'avg_slippage_bps': np.mean([o.get('slippage', 0) for o in self.executed_orders])
        }


# 测试代码
if __name__ == "__main__":
    print("=" * 60)
    print("本地执行引擎测试")
    print("=" * 60)

    from datetime import datetime

    # 创建测试tick
    tick = TickData(
        timestamp=datetime.now(),
        symbol="BTCUSDT",
        bid_price=50000.0,
        bid_qty=2.0,
        ask_price=50002.0,
        ask_qty=1.5,
        mid_price=50001.0,
        spread_bps=4.0
    )

    engine = LocalExecutionEngine()

    print("\n1. 限价单测试（买入）")
    result = engine.execute_limit_order(
        side='buy',
        qty=0.1,
        price=50000.0,  # 买一价
        tick=tick,
        queue_position=0.3
    )
    print(f"  成交: {result.success}")
    if result.success:
        print(f"  成交价格: ${result.filled_price:.2f}")
        print(f"  手续费: ${result.fee:.4f}")
        print(f"  滑点: {result.slippage_bps:.2f} bps")

    print("\n2. 市价单测试（卖出）")
    result = engine.execute_market_order(
        side='sell',
        qty=0.1,
        tick=tick
    )
    print(f"  成交: {result.success}")
    if result.success:
        print(f"  成交价格: ${result.filled_price:.2f}")
        print(f"  手续费: ${result.fee:.4f}")

    print("\n3. 统计信息")
    stats = engine.get_statistics()
    print(f"  总订单数: {stats['total_orders']}")
    print(f"  总成交量: ${stats['total_volume']:.2f}")
    print(f"  总手续费: ${stats['total_fees']:.4f}")

    print("\n" + "=" * 60)
    print("测试完成")
