"""
模拟Go引擎 v2 - 完整HTTP API实现
无需网络连接，支持纸交易测试
"""
import time
import json
import random
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class Order:
    order_id: str
    type: str  # 'limit' or 'market'
    side: str  # 'BUY' or 'SELL'
    size: float
    price: Optional[float]
    status: str = 'open'  # 'open', 'filled', 'cancelled'
    timestamp: float = field(default_factory=time.time)
    fill_price: Optional[float] = None
    fee: float = 0.0
    is_maker: bool = True


class PaperTradingEngine:
    """纸交易引擎 - 模拟完整交易环境。"""

    def __init__(self, symbol: str = "BTCUSDT", initial_price: float = 70000.0):
        self.symbol = symbol
        self.price = initial_price
        self.tick_size = 0.01

        # 仓位和资金
        self.position = 0.0
        self.cash = 10000.0  # 初始资金
        self.initial_capital = 10000.0

        # 订单管理
        self.orders: Dict[str, Order] = {}
        self.order_counter = 0
        self.fills: list = []

        # 市场数据
        self.bid = self.price - 0.5
        self.ask = self.price + 0.5
        self.bid_size = random.uniform(0.5, 2.0)
        self.ask_size = random.uniform(0.5, 2.0)

        # 统计
        self.total_fees = 0.0
        self.trade_count = 0

        # 风控
        self.kill_switch = False
        self.max_position = 0.02

    def update_market(self):
        """模拟市场价格波动。"""
        if self.kill_switch:
            return

        # 随机游走
        change = random.uniform(-10, 10)
        self.price += change
        self.bid = self.price - random.uniform(0.3, 0.8)
        self.ask = self.price + random.uniform(0.3, 0.8)
        self.bid_size = random.uniform(0.5, 3.0)
        self.ask_size = random.uniform(0.5, 3.0)

        # 检查订单成交
        self._match_orders()

    def _match_orders(self):
        """撮合订单。"""
        for order in self.orders.values():
            if order.status != 'open':
                continue

            if order.type == 'market':
                # 市价单立即成交
                fill_price = self.ask if order.side == 'BUY' else self.bid
                self._execute_fill(order, fill_price, is_maker=False)
            elif order.type == 'limit':
                # 限价单检查价格
                if order.side == 'BUY' and order.price >= self.ask * 0.998:
                    if random.random() < 0.5:  # 50%成交概率
                        self._execute_fill(order, order.price, is_maker=True)
                elif order.side == 'SELL' and order.price <= self.bid * 1.002:
                    if random.random() < 0.5:
                        self._execute_fill(order, order.price, is_maker=True)

    def _execute_fill(self, order: Order, fill_price: float, is_maker: bool):
        """执行成交。"""
        order.status = 'filled'
        order.fill_price = fill_price
        order.is_maker = is_maker

        # 计算费用
        fee_rate = 0.0002 if is_maker else 0.0005  # Maker 0.02%, Taker 0.05%
        order.fee = fill_price * order.size * fee_rate
        self.total_fees += order.fee

        # 更新仓位和资金
        if order.side == 'BUY':
            self.position += order.size
            self.cash -= (fill_price * order.size + order.fee)
        else:
            self.position -= order.size
            self.cash += (fill_price * order.size - order.fee)

        self.trade_count += 1

        # 记录成交
        self.fills.append({
            'order_id': order.order_id,
            'side': order.side,
            'size': order.size,
            'price': fill_price,
            'fee': order.fee,
            'is_maker': is_maker,
            'timestamp': time.time()
        })

        # 风控检查
        if abs(self.position) > self.max_position:
            print(f"[RISK] Position limit exceeded: {self.position:.4f} > {self.max_position}")
            self.kill_switch = True

    def place_order(self, order_type: str, side: str, size: float, price: float = None) -> Order:
        """下单。"""
        if self.kill_switch:
            raise Exception("Kill switch activated")

        self.order_counter += 1
        order_id = f"order_{self.order_counter}"

        order = Order(
            order_id=order_id,
            type=order_type,
            side=side,
            size=size,
            price=price
        )
        self.orders[order_id] = order

        # 立即尝试撮合
        if order.type == 'market':
            fill_price = self.ask if order.side == 'BUY' else self.bid
            self._execute_fill(order, fill_price, is_maker=False)

        return order

    def cancel_order(self, order_id: str) -> bool:
        """取消订单。"""
        if order_id in self.orders:
            order = self.orders[order_id]
            if order.status == 'open':
                order.status = 'cancelled'
                return True
        return False

    def cancel_all_orders(self):
        """取消所有未成交订单。"""
        for order in self.orders.values():
            if order.status == 'open':
                order.status = 'cancelled'

    def get_open_orders(self) -> list:
        """获取未成交订单。"""
        return [self._order_to_dict(o) for o in self.orders.values() if o.status == 'open']

    def get_fills(self) -> list:
        """获取成交记录。"""
        return self.fills

    def _order_to_dict(self, order: Order) -> dict:
        return {
            'order_id': order.order_id,
            'type': order.type,
            'side': order.side,
            'size': order.size,
            'price': order.price,
            'status': order.status,
            'timestamp': order.timestamp
        }

    def get_position(self) -> Dict[str, Any]:
        """获取持仓。"""
        unrealized_pnl = 0.0
        if self.position != 0:
            avg_price = self.price  # 简化计算
            unrealized_pnl = self.position * (self.price - avg_price)

        return {
            'symbol': self.symbol,
            'position': self.position,
            'entry_price': self.price if self.position != 0 else 0.0,
            'unrealized_pnl': unrealized_pnl,
            'cash': self.cash,
            'total_value': self.cash + self.position * self.price
        }

    def get_order_book(self) -> Dict[str, Any]:
        """获取订单簿。"""
        return {
            'symbol': self.symbol,
            'bids': [[self.bid, self.bid_size], [self.bid - 0.5, self.bid_size * 2]],
            'asks': [[self.ask, self.ask_size], [self.ask + 0.5, self.ask_size * 2]],
            'last_price': self.price,
            'timestamp': time.time()
        }

    def get_status(self) -> Dict[str, Any]:
        """获取引擎状态。"""
        pnl = self.cash + self.position * self.price - self.initial_capital
        return {
            'status': 'running' if not self.kill_switch else 'stopped',
            'symbol': self.symbol,
            'price': self.price,
            'position': self.position,
            'cash': self.cash,
            'total_value': self.cash + self.position * self.price,
            'pnl': pnl,
            'pnl_pct': (pnl / self.initial_capital) * 100,
            'total_fees': self.total_fees,
            'trade_count': self.trade_count,
            'open_orders': len(self.get_open_orders()),
            'timestamp': time.time()
        }


class RequestHandler(BaseHTTPRequestHandler):
    """HTTP请求处理器。"""

    engine = PaperTradingEngine()

    def log_message(self, format, *args):
        pass  # 减少日志噪音

    def _send_json(self, data: Dict[str, Any], status: int = 200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def _read_json(self) -> Dict[str, Any]:
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > 0:
            body = self.rfile.read(content_length)
            return json.loads(body.decode())
        return {}

    def do_GET(self):
        if self.path.startswith('/api/v1/market/book'):
            self._send_json(self.engine.get_order_book())
        elif self.path.startswith('/api/v1/position'):
            self._send_json(self.engine.get_position())
        elif self.path.startswith('/api/v1/orders/open'):
            self._send_json({'orders': self.engine.get_open_orders()})
        elif self.path.startswith('/api/v1/orders/filled'):
            self._send_json({'fills': self.engine.get_fills()})
        elif self.path.startswith('/api/v1/status'):
            self._send_json(self.engine.get_status())
        elif self.path.startswith('/api/v1/risk/stats'):
            # 模拟风控数据
            self._send_json({
                'toxic_score': random.uniform(0, 0.3),
                'volatility': random.uniform(0.001, 0.005),
                'kill_switch': self.engine.kill_switch
            })
        else:
            self._send_json({'error': 'Not found'}, 404)

    def do_POST(self):
        if self.path.startswith('/api/v1/order'):
            try:
                data = self._read_json()
                order = self.engine.place_order(
                    order_type=data.get('type', 'limit'),
                    side=data.get('side', 'BUY'),
                    size=float(data.get('size', 0)),
                    price=data.get('price')
                )
                self._send_json(self.engine._order_to_dict(order))
            except Exception as e:
                self._send_json({'error': str(e)}, 400)
        elif self.path.startswith('/api/v1/cancel'):
            data = self._read_json()
            if 'order_id' in data:
                success = self.engine.cancel_order(data['order_id'])
                self._send_json({'success': success})
            else:
                self.engine.cancel_all_orders()
                self._send_json({'success': True})
        elif self.path.startswith('/api/v1/cancel_all'):
            self.engine.cancel_all_orders()
            self._send_json({'success': True})
        else:
            self._send_json({'error': 'Not found'}, 404)


def run_server(port: int = 8080):
    """启动服务器。"""
    server = HTTPServer(('localhost', port), RequestHandler)
    print(f'[PaperTradingEngine] HTTP server on http://localhost:{port}')
    print(f'  Endpoints: /api/v1/market/book, /api/v1/position, /api/v1/order, /api/v1/status')

    # 市场更新线程
    def update_loop():
        while True:
            time.sleep(0.5)
            RequestHandler.engine.update_market()

    threading.Thread(target=update_loop, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n[Shutdown] Saving state...')
        server.shutdown()


if __name__ == '__main__':
    run_server()
