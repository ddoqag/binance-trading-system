import os
import websocket
import json
import threading
import time
from typing import Callable, Optional
from urllib.parse import urlparse
from core.execution_models import OrderBook


def _get_ws_proxy():
    """从环境变量读取代理配置，供 websocket-client 使用。"""
    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    if not proxy_url:
        return None, None
    parsed = urlparse(proxy_url)
    return parsed.hostname, parsed.port


class BinanceWSClient:
    """
    订阅 Binance 合并流：L2 OrderBook + Trade Stream
    自动读取 HTTP_PROXY / HTTPS_PROXY 环境变量走代理
    """

    def __init__(self, symbol: str):
        self.symbol = symbol.lower()
        self.book: Optional[OrderBook] = None
        self.last_price: Optional[float] = None
        self.on_trade_callback: Optional[Callable] = None
        self.on_book_callback: Optional[Callable[[OrderBook], None]] = None

    def on_message(self, ws, message):
        data = json.loads(message)
        stream = data.get("stream", "")
        payload = data.get("data", {})

        if "depth" in stream:
            bids = [(float(p), float(s)) for p, s in payload.get("b", [])[:5]]
            asks = [(float(p), float(s)) for p, s in payload.get("a", [])[:5]]
            self.book = OrderBook(bids=bids, asks=asks)
            if self.on_book_callback:
                self.on_book_callback(self.book)

        elif "trade" in stream:
            self.last_price = float(payload.get("p", 0))
            if self.on_trade_callback:
                self.on_trade_callback(payload)

    def start(self):
        streams = f"{self.symbol}@depth5@100ms/{self.symbol}@trade"
        url = f"wss://stream.binance.com:9443/stream?streams={streams}"

        self.ws = websocket.WebSocketApp(
            url,
            on_message=self.on_message,
            on_error=lambda ws, e: print(f"[WS Error] {e}"),
            on_close=lambda ws, status, msg: print("[WS Closed]")
        )

        proxy_host, proxy_port = _get_ws_proxy()

        def run():
            while getattr(self, "_running", True):
                try:
                    kwargs = {}
                    if proxy_host and proxy_port:
                        kwargs["http_proxy_host"] = proxy_host
                        kwargs["http_proxy_port"] = proxy_port
                        kwargs["proxy_type"] = "http"
                    self.ws.run_forever(**kwargs)
                except Exception as e:
                    print(f"[WS Reconnect] {e}")
                time.sleep(2)

        self._running = True
        threading.Thread(target=run, daemon=True).start()

    def stop(self):
        self._running = False
        if hasattr(self, "ws") and self.ws:
            self.ws.close()
