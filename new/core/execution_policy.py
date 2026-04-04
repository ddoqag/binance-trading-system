from enum import Enum
from typing import Optional, Tuple
from core.execution_models import Order, OrderSide, OrderType, OrderBook
from core.queue_model import QueueModel
from core.fill_model import FillModel
from core.slippage_model import SlippageModel


class ExecutionAction(Enum):
    LIMIT_PASSIVE = "LIMIT_PASSIVE"   # 挂限价单，吃 rebate
    LIMIT_AGGRESSIVE = "LIMIT_AGGRESSIVE"  # 扫一挂单
    MARKET = "MARKET"                  # 市价立即成交
    WAIT = "WAIT"                      # 等待


class ExecutionPolicy:
    """
    根据信号强度、市场状态和排队情况，决定最优执行方式。
    """

    def __init__(
        self,
        queue_model: QueueModel,
        fill_model: FillModel,
        slippage_model: SlippageModel,
        max_slippage_bps: float = 5.0,
        min_fill_prob: float = 0.3,
        latency_ms: float = 50.0
    ):
        self.queue_model = queue_model
        self.fill_model = fill_model
        self.slippage_model = slippage_model
        self.max_slippage_bps = max_slippage_bps
        self.min_fill_prob = min_fill_prob
        self.latency_ms = latency_ms

    def decide(
        self,
        signal_strength: float,  # -1.0 ~ +1.0
        book: OrderBook,
        estimated_size: float
    ) -> Tuple[ExecutionAction, Optional[float]]:
        """
        返回：(执行动作, 建议价格)
        """
        if abs(signal_strength) < 0.2:
            return ExecutionAction.WAIT, None

        side = OrderSide.BUY if signal_strength > 0 else OrderSide.SELL

        # 1. 估算市价单滑点
        market_order = Order(
            id="estimate",
            symbol="",
            side=side,
            order_type=OrderType.MARKET,
            size=estimated_size
        )
        slip_bps = self.slippage_model.estimate_slippage_bps(market_order, book)

        # 2. 估算限价单排队位置和成交概率
        if side == OrderSide.BUY:
            limit_price = book.best_bid()
        else:
            limit_price = book.best_ask()

        if limit_price is None:
            return ExecutionAction.MARKET, None

        limit_order = Order(
            id="estimate",
            symbol="",
            side=side,
            order_type=OrderType.LIMIT,
            size=estimated_size,
            price=limit_price
        )
        queue_pos = self.queue_model.estimate_position(limit_order, book) or 0.0
        fill_prob = self.fill_model.fill_probability(queue_pos, time_horizon_s=1.0)

        # 3. 决策逻辑
        urgency = abs(signal_strength) - (self.latency_ms / 1000.0)

        if urgency > 0.8:
            # 信号极强，立即成交
            return ExecutionAction.MARKET, None

        if slip_bps is not None and slip_bps > self.max_slippage_bps:
            # 滑点太大，尝试 passive limit
            return ExecutionAction.LIMIT_PASSIVE, limit_price

        if fill_prob > 0.7:
            # 成交概率高，挂单
            return ExecutionAction.LIMIT_AGGRESSIVE, limit_price

        if queue_pos < estimated_size * 2:
            # 排队位置靠前，值得挂
            return ExecutionAction.LIMIT_PASSIVE, limit_price

        return ExecutionAction.WAIT, None
