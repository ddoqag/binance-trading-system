"""
与Go执行引擎通信的HTTP客户端。
"""
import requests
import time
from typing import Dict, Any, List, Optional


class ExecutorClient:
    """封装与Go执行引擎（HTTP API）的所有通信。"""

    def __init__(self, base_url: str = "http://localhost:8080", timeout: float = 2.0):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.session = requests.Session()

    def place_order(self, order_type: str, side: str, size: float, price: Optional[float] = None) -> Dict[str, Any]:
        """
        下订单。
        :param order_type: 'limit' 或 'market'
        :param side: 'BUY' 或 'SELL'
        :param size: 订单数量
        :param price: 限价单价格，市价单可忽略
        :return: 订单响应字典
        """
        payload = {
            "type": order_type,
            "side": side,
            "size": size
        }
        if order_type == 'limit' and price is not None:
            payload["price"] = price
        elif order_type == 'limit':
            raise ValueError("Limit orders require a price.")

        try:
            resp = self.session.post(
                f"{self.base_url}/api/v1/order",
                json=payload,
                timeout=self.timeout
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            # 此处应集成到您的日志系统
            print(f"[ExecutorClient] Failed to place order: {e}")
            return {"error": str(e), "order_id": None}

    def cancel_order(self, order_id: str) -> bool:
        """取消指定订单。"""
        try:
            resp = self.session.post(f"{self.base_url}/api/v1/cancel", json={"order_id": order_id})
            return resp.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def cancel_all_orders(self, symbol: Optional[str] = None) -> bool:
        """取消所有订单（或指定交易对的所有订单）。"""
        try:
            payload = {}
            if symbol:
                payload["symbol"] = symbol
            resp = self.session.post(f"{self.base_url}/api/v1/cancel_all", json=payload)
            return resp.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取当前挂单列表。"""
        try:
            params = {}
            if symbol:
                params["symbol"] = symbol
            resp = self.session.get(f"{self.base_url}/api/v1/orders/open", params=params, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json().get("orders", [])
        except requests.exceptions.RequestException:
            return []

    def get_position(self, symbol: str) -> Dict[str, Any]:
        """获取指定交易对持仓。"""
        try:
            resp = self.session.get(f"{self.base_url}/api/v1/position", params={"symbol": symbol}, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException:
            return {"symbol": symbol, "position": 0.0, "entry_price": 0.0}
