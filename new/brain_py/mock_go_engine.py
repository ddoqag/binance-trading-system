"""
模拟Go引擎HTTP API服务器，用于测试MarketMakerV1策略。
无需真实币安API密钥，使用模拟数据运行。
"""
import time
import json
import random
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any


class MockGoEngine:
    """模拟Go引擎状态和逻辑。"""

    def __init__(self, symbol: str = "BTCUSDT", initial_price: float = 70000.0):
        self.symbol = symbol
        self.price = initial_price
        self.tick_size = 0.01
        self.position = 0.0
        self.orders = {}
        self.order_counter = 0
        self.pnl = 0.0
        self.fills = []

        # 模拟市场状态
        self.bid = self.price - 0.5
        self.ask = self.price + 0.5
        self.bid_size = random.uniform(0.5, 2.0)
        self.ask_size = random.uniform(0.5, 2.0)

    def update_market(self):
        """模拟市场价格波动。"""
        # 随机游走
        change = random.uniform(-5, 5)
        self.price += change
        self.bid = self.price - random.uniform(0.3, 0.8)
        self.ask = self.price + random.uniform(0.3, 0.8)
        self.bid_size = random.uniform(0.5, 3.0)
        self.ask_size = random.uniform(0.5, 3.0)

    def get_order_book(self) -> Dict[str, Any]:
        """获取模拟订单簿。"""
        return {
            "symbol": self.symbol,
            "bids": [[self.bid, self.bid_size], [self.bid - 0.5, self.bid_size * 2]],
            "asks": [[self.ask, self.ask_size], [self.ask + 0.5, self.ask_size * 2]],
            "last_price": self.price,
            "timestamp": time.time()
        }

    def get_position(self) -> Dict[str, Any]:
        """获取当前持仓。"""
        return {
            "symbol": self.symbol,
            "position": self.position,
            "entry_price": self.price if self.position != 0 else 0.0,
            "unrealized_pnl": 0.0
        }

    def place_order(self, order_type: str, side: str, size: float, price: float = None) -> Dict[str, Any]:
        """模拟下单。"""
        self.order_counter += 1
        order_id = f"mock_order_{self.order_counter}"

        order = {
            "order_id": order_id,
            "type": order_type,
            "side": side,
            "size": size,
            "price": price,
            "status": "open",
            "timestamp": time.time()
        }
        self.orders[order_id] = order

        # 模拟成交概率：Maker单有30%概率成交，Taker单立即成交
        if order_type == "market":
            # 市价单立即成交
            self._fill_order(order_id, is_maker=False)
        elif order_type == "limit":
            # 限价单根据价格判断是否可能成交
            if side == "BUY" and price >= self.ask * 0.999:  # 价格接近或超过卖一
                if random.random() < 0.3:
                    self._fill_order(order_id, is_maker=True)
            elif side == "SELL" and price <= self.bid * 1.001:  # 价格接近或低于买一
                if random.random() < 0.3:
                    self._fill_order(order_id, is_maker=True)

        return order

    def _fill_order(self, order_id: str, is_maker: bool):
        """模拟订单成交。"""
        order = self.orders.get(order_id)
        if not order or order["status"] == "filled":
            return

        fill_price = order.get("price", self.price)
        if not fill_price:
            fill_price = self.price

        fill_size = order["size"]
        side = order["side"]

        # 更新持仓
        if side == "BUY":
            self.position += fill_size
        else:
            self.position -= fill_size

        # 计算费用 (Maker 0.02%, Taker 0.05%)
        fee_rate = 0.0002 if is_maker else 0.0005
        fee = fill_price * fill_size * fee_rate

        order["status"] = "filled"
        order["fill_price"] = fill_price
        order["fill_time"] = time.time()
        order["fee"] = fee
        order["is_maker"] = is_maker

        self.fills.append({
            "order_id": order_id,
            "side": side,
            "size": fill_size,
            "price": fill_price,
            "fee": fee,
            "is_maker": is_maker
        })

    def cancel_order(self, order_id: str) -> bool:
        """取消订单。"""
        if order_id in self.orders:
            if self.orders[order_id]["status"] == "open":
                self.orders[order_id]["status"] = "cancelled"
                return True
        return False

    def cancel_all_orders(self):
        """取消所有未成交订单。"""
        for order in self.orders.values():
            if order["status"] == "open":
                order["status"] = "cancelled"

    def get_open_orders(self) -> list:
        """获取所有未成交订单。"""
        return [o for o in self.orders.values() if o["status"] == "open"]

    def get_status(self) -> Dict[str, Any]:
        """获取引擎状态。"""
        return {
            "status": "running",
            "symbol": self.symbol,
            "price": self.price,
            "position": self.position,
            "open_orders": len(self.get_open_orders()),
            "total_fills": len(self.fills),
            "timestamp": time.time()
        }


class RequestHandler(BaseHTTPRequestHandler):
    """HTTP请求处理器。"""

    engine = MockGoEngine()

    def log_message(self, format, *args):
        """简化日志输出。"""
        pass  # 减少噪音

    def _send_json(self, data: Dict[str, Any], status: int = 200):
        """发送JSON响应。"""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _read_json(self) -> Dict[str, Any]:
        """读取JSON请求体。"""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            body = self.rfile.read(content_length)
            return json.loads(body.decode())
        return {}

    def do_GET(self):
        """处理GET请求。"""
        if self.path.startswith("/api/v1/market/book"):
            self._send_json(self.engine.get_order_book())
        elif self.path.startswith("/api/v1/position"):
            self._send_json(self.engine.get_position())
        elif self.path.startswith("/api/v1/orders/open"):
            self._send_json({"orders": self.engine.get_open_orders()})
        elif self.path.startswith("/api/v1/orders/filled"):
            self._send_json({"fills": self.engine.fills})
        elif self.path.startswith("/api/v1/status"):
            self._send_json(self.engine.get_status())
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        """处理POST请求。"""
        if self.path.startswith("/api/v1/order"):
            data = self._read_json()
            result = self.engine.place_order(
                order_type=data.get("type", "limit"),
                side=data.get("side", "BUY"),
                size=float(data.get("size", 0)),
                price=data.get("price")
            )
            self._send_json(result)
        elif self.path.startswith("/api/v1/cancel"):
            data = self._read_json()
            if "order_id" in data:
                success = self.engine.cancel_order(data["order_id"])
                self._send_json({"success": success})
            else:
                self.engine.cancel_all_orders()
                self._send_json({"success": True})
        elif self.path.startswith("/api/v1/cancel_all"):
            self.engine.cancel_all_orders()
            self._send_json({"success": True})
        else:
            self._send_json({"error": "Not found"}, 404)


def run_mock_server(port: int = 8080):
    """启动模拟服务器。"""
    server = HTTPServer(("localhost", port), RequestHandler)
    print(f"[MockGoEngine] HTTP server started on http://localhost:{port}")
    print(f"[MockGoEngine] Endpoints:")
    print(f"  - GET  /api/v1/market/book")
    print(f"  - GET  /api/v1/position")
    print(f"  - GET  /api/v1/orders/open")
    print(f"  - POST /api/v1/order")
    print(f"  - POST /api/v1/cancel")
    print(f"  - POST /api/v1/cancel_all")

    # 启动市场价格更新线程
    def update_loop():
        while True:
            time.sleep(1)
            RequestHandler.engine.update_market()

    updater = threading.Thread(target=update_loop, daemon=True)
    updater.start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[MockGoEngine] Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    run_mock_server()
