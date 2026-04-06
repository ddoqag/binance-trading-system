import os
import websocket
import json
import threading
import time
import ssl
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
        self.ws: Optional[websocket.WebSocket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def _connect(self) -> websocket.WebSocket:
        """建立 WebSocket 连接"""
        streams = f"{self.symbol}@depth5@100ms/{self.symbol}@trade"
        url = f"wss://stream.binance.com:9443/stream?streams={streams}"

        proxy_host, proxy_port = _get_ws_proxy()

        ws = websocket.WebSocket()

        kwargs = {"timeout": 10}
        if proxy_host and proxy_port:
            kwargs["http_proxy_host"] = proxy_host
            kwargs["http_proxy_port"] = proxy_port
            kwargs["proxy_type"] = "http"

        ws.connect(url, **kwargs)
        return ws

    def _run(self):
        """主循环"""
        while self._running:
            try:
                self.ws = self._connect()
                print(f"[BinanceWSClient] Connected to {self.symbol} stream")

                while self._running:
                    try:
                        self.ws.settimeout(1.0)
                        message = self.ws.recv()
                        self._on_message(message)
                    except websocket.WebSocketTimeoutException:
                        continue
                    except Exception as e:
                        print(f"[BinanceWSClient] Receive error: {e}")
                        break

            except Exception as e:
                print(f"[BinanceWSClient] Connection error: {e}")

            finally:
                if self.ws:
                    try:
                        self.ws.close()
                    except:
                        pass
                    self.ws = None

            if self._running:
                print("[BinanceWSClient] Reconnecting in 2 seconds...")
                time.sleep(2)

    def _on_message(self, message: str):
        """处理消息"""
        try:
            data = json.loads(message)
            stream = data.get("stream", "")
            payload = data.get("data", {})

            if "depth" in stream:
                # 合并流使用 'bids'/'asks'，直接流使用 'b'/'a'
                bids_data = payload.get("bids", payload.get("b", []))
                asks_data = payload.get("asks", payload.get("a", []))
                bids = [(float(p), float(s)) for p, s in bids_data[:5]]
                asks = [(float(p), float(s)) for p, s in asks_data[:5]]
                self.book = OrderBook(bids=bids, asks=asks)
                if self.on_book_callback:
                    self.on_book_callback(self.book)

            elif "trade" in stream:
                self.last_price = float(payload.get("p", 0))
                if self.on_trade_callback:
                    self.on_trade_callback(payload)

        except Exception as e:
            print(f"[BinanceWSClient] Message processing error: {e}")

    def start(self):
        """启动 WebSocket 客户端"""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """停止 WebSocket 客户端"""
        self._running = False
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
        if self._thread:
            self._thread.join(timeout=2)
