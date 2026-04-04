import websocket
import threading
import json
import time
import logging
from typing import Callable, List

logger = logging.getLogger(__name__)


class BinanceUserDataClient:
    """
    Binance User Data Stream 客户端
    监听 executionReport 和 outboundAccountPosition
    """

    def __init__(self, listen_key: str):
        self.listen_key = listen_key
        self.callbacks: List[Callable[[dict], None]] = []
        self._ws: websocket.WebSocketApp | None = None
        self._stop_event = threading.Event()

    def subscribe(self, cb: Callable[[dict], None]):
        self.callbacks.append(cb)

    def _broadcast(self, event: dict):
        for cb in self.callbacks:
            try:
                cb(event)
            except Exception as e:
                logger.error(f"[UserDataClient] Callback error: {e}")

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return

        event_type = data.get("e")

        if event_type == "executionReport":
            self._handle_execution(data)
        elif event_type == "outboundAccountPosition":
            self._handle_account(data)
        elif event_type == "listenKeyExpired":
            logger.warning("[UserDataClient] listenKey expired")

    def _handle_execution(self, d: dict):
        event = {
            "type": "execution",
            "order_id": str(d.get("c", "")),
            "exchange_order_id": d.get("i"),
            "status": d.get("X"),        # NEW / FILLED / PARTIALLY_FILLED / CANCELED
            "side": d.get("S"),
            "price": float(d.get("L")) if d.get("L") not in (None, "0") else 0.0,
            "qty": float(d.get("l", 0)),
            "cumulated_qty": float(d.get("z", 0)),
            "commission": float(d.get("n", 0)),
            "commission_asset": d.get("N", ""),
            "symbol": d.get("s", ""),
            "time": d.get("T", int(time.time() * 1000)),
        }
        self._broadcast(event)

    def _handle_account(self, d: dict):
        balances = {
            b["a"]: {"free": float(b["f"]), "locked": float(b["l"]), "total": float(b["f"]) + float(b["l"])}
            for b in d.get("B", [])
        }

        event = {
            "type": "account",
            "balances": balances,
            "time": d.get("E", int(time.time() * 1000)),
        }
        self._broadcast(event)

    def start(self):
        url = f"wss://stream.binance.com:9443/ws/{self.listen_key}"

        self._ws = websocket.WebSocketApp(
            url,
            on_message=self._on_message,
            on_error=lambda _ws, e: logger.error(f"[UserDataClient] WS error: {e}"),
            on_close=lambda _ws, *_: logger.info("[UserDataClient] WS closed"),
            on_open=lambda _ws: logger.info("[UserDataClient] WS connected"),
        )

        def run():
            while not self._stop_event.is_set():
                try:
                    self._ws.run_forever()
                except Exception as e:
                    logger.error(f"[UserDataClient] Reconnect: {e}")
                if not self._stop_event.is_set():
                    time.sleep(2)

        threading.Thread(target=run, daemon=True).start()
        logger.info("[UserDataClient] Started")

    def stop(self):
        self._stop_event.set()
        if self._ws:
            self._ws.close()
        logger.info("[UserDataClient] Stopped")
