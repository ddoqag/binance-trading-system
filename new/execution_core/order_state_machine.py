from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class OrderStateMachine:
    """
    订单状态机 - 系统的 Source of Truth
    基于 Binance executionReport 维护订单完整生命周期
    """

    def __init__(self):
        self.orders: Dict[str, dict] = {}

    def create(self, order_id: str, side: str, size: float, price: Optional[float]):
        self.orders[order_id] = {
            "side": side,
            "size": size,
            "price": price,
            "filled": 0.0,
            "status": "NEW",
            "canceled": False,
            "reprice_count": 0,
        }
        logger.debug(f"[OSM] Created order {order_id}")

    def on_execution(self, event: dict):
        oid = event.get("order_id")

        if oid not in self.orders:
            logger.warning(f"[OSM] Unknown order execution: {oid}")
            return

        o = self.orders[oid]
        qty = event.get("qty", 0.0)
        if qty > 0:
            o["filled"] += qty

        status = event.get("status")
        if status:
            o["status"] = status

        if o["status"] == "FILLED":
            logger.info(f"[OSM] ✅ Order FILLED: {oid} | filled={o['filled']:.6f}")
        elif o["status"] == "PARTIALLY_FILLED":
            logger.info(f"[OSM] 🟡 Partial fill: {oid} | filled={o['filled']:.6f}")
        elif o["status"] == "CANCELED":
            o["canceled"] = True
            logger.info(f"[OSM] ❌ Canceled: {oid}")
        elif o["status"] == "REJECTED":
            logger.warning(f"[OSM] 🔴 Rejected: {oid}")
        elif o["status"] == "EXPIRED":
            logger.warning(f"[OSM] ⚪ Expired: {oid}")

    def get_order(self, order_id: str) -> Optional[dict]:
        return self.orders.get(order_id)

    def is_active(self, order_id: str) -> bool:
        o = self.orders.get(order_id)
        if not o:
            return False
        return o["status"] in ("NEW", "PARTIALLY_FILLED")

    def get_active_orders(self) -> Dict[str, dict]:
        return {
            oid: o for oid, o in self.orders.items()
            if o["status"] in ("NEW", "PARTIALLY_FILLED")
        }

    def remove(self, order_id: str):
        self.orders.pop(order_id, None)
