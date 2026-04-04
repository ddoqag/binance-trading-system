import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from typing import Optional


class BinanceRESTClient:
    def __init__(self, api_key: str, api_secret: str, base_url: str = "https://api.binance.com"):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url

    def _sign(self, params: dict) -> str:
        query_string = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode(),
            query_string.encode(),
            hashlib.sha256
        ).hexdigest()
        return signature

    def _headers(self) -> dict:
        return {"X-MBX-APIKEY": self.api_key}

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: Optional[float] = None,
        order_type: str = "LIMIT"
    ) -> dict:
        params = {
            "symbol": symbol.upper(),
            "side": side,
            "type": order_type,
            "quantity": f"{quantity:.6f}",
            "timestamp": int(time.time() * 1000)
        }
        if order_type == "LIMIT" and price is not None:
            params["price"] = f"{price:.2f}"
            params["timeInForce"] = "GTC"

        params["signature"] = self._sign(params)

        resp = requests.post(
            f"{self.base_url}/api/v3/order",
            headers=self._headers(),
            params=params,
            timeout=10
        )
        return resp.json()

    def get_account(self) -> dict:
        params = {"timestamp": int(time.time() * 1000)}
        params["signature"] = self._sign(params)
        resp = requests.get(
            f"{self.base_url}/api/v3/account",
            headers=self._headers(),
            params=params,
            timeout=10
        )
        return resp.json()

    def cancel_order(self, symbol: str, order_id: str) -> dict:
        params = {
            "symbol": symbol.upper(),
            "origClientOrderId": order_id,
            "timestamp": int(time.time() * 1000)
        }
        params["signature"] = self._sign(params)
        resp = requests.delete(
            f"{self.base_url}/api/v3/order",
            headers=self._headers(),
            params=params,
            timeout=10
        )
        return resp.json()

    def get_open_orders(self, symbol: str) -> list:
        params = {
            "symbol": symbol.upper(),
            "timestamp": int(time.time() * 1000)
        }
        params["signature"] = self._sign(params)
        resp = requests.get(
            f"{self.base_url}/api/v3/openOrders",
            headers=self._headers(),
            params=params,
            timeout=10
        )
        return resp.json()
