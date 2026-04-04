import uuid
import logging
from typing import Optional

from execution_core.order_state_machine import OrderStateMachine
from execution_core.position_manager import PositionManager
from execution_core.queue_tracker import QueueTracker
from execution_core.cancel_manager import CancelManager, CancelReason
from execution_core.reprice_engine import RepriceEngine
from core.binance_rest_client import BinanceRESTClient

logger = logging.getLogger(__name__)


class LifecycleManager:
    """
    订单生命周期调度中枢
    连接 UserDataStream -> OSM -> PositionManager -> Cancel/Reprice -> REST
    """

    def __init__(
        self,
        osm: OrderStateMachine,
        pm: PositionManager,
        queue_tracker: QueueTracker,
        cancel_mgr: CancelManager,
        reprice_engine: RepriceEngine,
        rest: BinanceRESTClient,
        ws_book=None,
        symbol: str = "BTCUSDT",
    ):
        self.osm = osm
        self.pm = pm
        self.qt = queue_tracker
        self.cm = cancel_mgr
        self.re = reprice_engine
        self.rest = rest
        self.ws_book = ws_book
        self.symbol = symbol
        self._reprice_counts: dict = {}

    def on_event(self, event: dict):
        """处理来自 UserDataClient 的事件"""
        if event.get("type") == "execution":
            self._handle_execution(event)
        elif event.get("type") == "account":
            pass  # 账户余额变更，如需可扩展

    def _handle_execution(self, e: dict):
        self.osm.on_execution(e)

        if e.get("status") in ("FILLED", "PARTIALLY_FILLED"):
            self.pm.on_fill(
                side=e.get("side", "BUY"),
                qty=e.get("qty", 0.0),
                price=e.get("price", 0.0),
                commission=e.get("commission", 0.0),
            )

            # 从 queue tracker 中移除已完全成交的订单
            oid = e.get("order_id")
            order = self.osm.get_order(oid)
            if order and order.get("filled", 0) >= order.get("size", 0) - 1e-9:
                self.qt.remove(oid)

    def manage_orders(
        self,
        current_signal_side: Optional[str] = None,
        current_regime: Optional[str] = None,
        adverse_alert: bool = False,
        sac_urgency: Optional[float] = None,
    ):
        """
        遍历所有活跃订单，评估是否需要撤单重挂
        """
        active = list(self.osm.get_active_orders().items())

        bb = getattr(self.ws_book, "best_bid", lambda: None)() if self.ws_book else None
        ba = getattr(self.ws_book, "best_ask", lambda: None)() if self.ws_book else None

        for oid, o in active:
            queue_pos_ratio = self.qt.get_queue_ratio(oid)
            queue_pos = self.qt.get_queue_position(oid)
            fill_prob = min(1.0, 0.001 / (queue_pos + 1e-6)) if queue_pos else 0.0

            snap = self.qt.snapshots.get(oid)
            time_in_queue = 0.0
            if snap:
                import time
                time_in_queue = time.time() - snap.placed_at

            should_cancel, decision = self.cm.should_cancel(
                order_id=oid,
                queue_pos=queue_pos,
                fill_prob=fill_prob,
                current_signal_side=current_signal_side,
                order_side=o.get("side"),
                current_regime=current_regime,
                order_regime=o.get("regime"),
                adverse_alert=adverse_alert,
                current_best_bid=bb,
                current_best_ask=ba,
                order_price=o.get("price"),
                time_in_queue=time_in_queue,
                sac_urgency=sac_urgency,
            )

            if should_cancel:
                logger.info(f"[Lifecycle] Cancel {oid}: {decision.reason.name} | {decision.detail}")

                try:
                    self.rest.cancel_order(self.symbol, oid)
                except Exception as e:
                    logger.error(f"[Lifecycle] Cancel failed for {oid}: {e}")
                    continue

                # 尝试重挂
                remaining = o.get("size", 0.0) - o.get("filled", 0.0)
                reprice_count = self._reprice_counts.get(oid, 0) + 1
                self._reprice_counts[oid] = reprice_count

                new_price, strategy = self.re.reprice(
                    side=o.get("side", "BUY"),
                    remaining_size=remaining,
                    book=self.ws_book,
                    attempt=reprice_count,
                )

                if new_price is None:
                    logger.info(f"[Lifecycle] No reprice for {oid} ({strategy})")
                    continue

                # 防止无限重挂
                if reprice_count > self.re.max_attempts:
                    logger.warning(f"[Lifecycle] Max reprice reached for {oid}, skipping")
                    continue

                try:
                    res = self.rest.place_order(
                        symbol=self.symbol,
                        side=o.get("side", "BUY"),
                        quantity=remaining,
                        price=new_price,
                        order_type="LIMIT",
                    )
                except Exception as e:
                    logger.error(f"[Lifecycle] Reprice place_order failed: {e}")
                    continue

                if "orderId" in res or "clientOrderId" in res:
                    new_id = res.get("clientOrderId") or f"repr_{uuid.uuid4().hex[:12]}"
                    self.osm.create(
                        order_id=new_id,
                        side=o.get("side", "BUY"),
                        size=remaining,
                        price=new_price,
                    )
                    self.osm.orders[new_id]["regime"] = current_regime
                    self.qt.on_order_placed(new_id, o.get("side"), new_price, self.ws_book)
                    self.cm.register(new_id)
                    logger.info(f"[Lifecycle] Repriced {oid} -> {new_id} @ {new_price} ({strategy})")
                else:
                    logger.error(f"[Lifecycle] Reprice order failed: {res}")

    def place_new_order(self, side: str, size: float, price: Optional[float], order_type: str = "LIMIT") -> Optional[str]:
        """
        新订单统一入口
        """
        order_id = f"evt_{uuid.uuid4().hex[:16]}"

        try:
            res = self.rest.place_order(
                symbol=self.symbol,
                side=side,
                quantity=size,
                price=price,
                order_type=order_type,
            )
        except Exception as e:
            logger.error(f"[Lifecycle] place_new_order failed: {e}")
            return None

        if "orderId" not in res and "clientOrderId" not in res:
            logger.error(f"[Lifecycle] Order rejected: {res}")
            return None

        actual_id = res.get("clientOrderId") or order_id
        self.osm.create(actual_id, side, size, price)
        self.osm.orders[actual_id]["regime"] = getattr(res, "_regime", None)

        if order_type == "LIMIT" and price is not None:
            self.qt.on_order_placed(actual_id, side, price, self.ws_book)
            self.cm.register(actual_id)

        logger.info(f"[Lifecycle] New order {actual_id} | {side} {size} @ {price}")
        return actual_id
