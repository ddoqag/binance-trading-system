import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class CancelReason(Enum):
    SIGNAL_REVERSED = auto()
    REGIME_CHANGED = auto()
    QUEUE_TIMEOUT = auto()
    ADVERSE_SELECTION = auto()
    PRICE_DRIFT = auto()
    UNKNOWN = auto()


@dataclass
class CancelDecision:
    order_id: str
    should_cancel: bool
    reason: CancelReason
    detail: str


class CancelManager:
    """
    撤单决策器
    评估每个活跃订单是否应被撤销
    """

    def __init__(
        self,
        max_queue_wait_seconds: float = 10.0,
        max_queue_ratio: float = 0.8,
        price_drift_ticks: int = 2,
        tick_size: float = 0.01,
    ):
        self.max_queue_wait_seconds = max_queue_wait_seconds
        self.max_queue_ratio = max_queue_ratio
        self.price_drift_ticks = price_drift_ticks
        self.tick_size = tick_size
        self._registry: set = set()

    def register(self, order_id: str):
        """注册新订单以便跟踪"""
        self._registry.add(order_id)

    def should_cancel(
        self,
        order_id: str,
        queue_pos: float,
        fill_prob: float,
        current_signal_side: Optional[str] = None,
        order_side: Optional[str] = None,
        current_regime: Optional[str] = None,
        order_regime: Optional[str] = None,
        adverse_alert: bool = False,
        current_best_bid: Optional[float] = None,
        current_best_ask: Optional[float] = None,
        order_price: Optional[float] = None,
        time_in_queue: float = 0.0,
        sac_urgency: Optional[float] = None,
    ) -> CancelDecision:
        urgency = sac_urgency if sac_urgency is not None else 0.0

        # 1. 信号反转（最高优先级，不受 SAC 干预）
        if current_signal_side and order_side and current_signal_side != order_side:
            return CancelDecision(
                order_id=order_id,
                should_cancel=True,
                reason=CancelReason.SIGNAL_REVERSED,
                detail=f"Signal reversed: order={order_side}, signal={current_signal_side}",
            )

        # 2. 市场状态剧变（次高优先级，不受 SAC 干预）
        if current_regime and order_regime and current_regime != order_regime:
            volatile = {"high_volatility", "crash", "panic"}
            if current_regime in volatile:
                return CancelDecision(
                    order_id=order_id,
                    should_cancel=True,
                    reason=CancelReason.REGIME_CHANGED,
                    detail=f"Regime changed: {order_regime} -> {current_regime}",
                )

        # 3. 排队超时 + 位置过差
        # SAC urgency 高时放宽条件：urgency 越接近 1.0，容忍倍数越大（最高 2x）
        timeout_multiplier = 1.0 + urgency
        pos_multiplier = 1.0 + urgency * 0.5
        if time_in_queue > self.max_queue_wait_seconds * timeout_multiplier and queue_pos > self.max_queue_ratio * 10 * pos_multiplier:
            return CancelDecision(
                order_id=order_id,
                should_cancel=True,
                reason=CancelReason.QUEUE_TIMEOUT,
                detail=f"Queue timeout {time_in_queue:.1f}s, pos={queue_pos:.2f}, fill_prob={fill_prob:.3f} (sac_urgency={urgency:.2f})",
            )

        # 4. 成交概率过低且排队过久
        if fill_prob < 0.05 and time_in_queue > self.max_queue_wait_seconds * 0.5 * timeout_multiplier:
            return CancelDecision(
                order_id=order_id,
                should_cancel=True,
                reason=CancelReason.QUEUE_TIMEOUT,
                detail=f"Low fill probability {fill_prob:.3f} after {time_in_queue:.1f}s (sac_urgency={urgency:.2f})",
            )

        # 5. 毒流警报
        # SAC urgency 高时降低敏感度：urgency > 0.8 时，仅在连续毒流或更严重情况下撤单
        if adverse_alert:
            if urgency >= 0.85:
                return CancelDecision(
                    order_id=order_id,
                    should_cancel=False,
                    reason=CancelReason.UNKNOWN,
                    detail=f"Adverse selection alert suppressed by high SAC urgency ({urgency:.2f})",
                )
            return CancelDecision(
                order_id=order_id,
                should_cancel=True,
                reason=CancelReason.ADVERSE_SELECTION,
                detail="Adverse selection alert",
            )

        # 6. 价格偏离
        if order_price is not None:
            if order_side == "BUY" and current_best_bid is not None:
                if (current_best_bid - order_price) > self.price_drift_ticks * self.tick_size:
                    return CancelDecision(
                        order_id=order_id,
                        should_cancel=True,
                        reason=CancelReason.PRICE_DRIFT,
                        detail=f"Bid drifted above order price",
                    )
            if order_side == "SELL" and current_best_ask is not None:
                if (order_price - current_best_ask) > self.price_drift_ticks * self.tick_size:
                    return CancelDecision(
                        order_id=order_id,
                        should_cancel=True,
                        reason=CancelReason.PRICE_DRIFT,
                        detail=f"Ask drifted below order price",
                    )

        return CancelDecision(
            order_id=order_id,
            should_cancel=False,
            reason=CancelReason.UNKNOWN,
            detail="No cancel condition met",
        )
