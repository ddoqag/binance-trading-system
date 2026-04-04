# User Data Stream 与 Order State Machine 升级指南

> 目标：接入 Binance `executionReport` 和 `outboundAccountPosition`，建立精确的订单生命周期追踪，替代基于 Trade Stream 的估算成交逻辑。

---

## 一、为什么必须做 User Data Stream + OSM

当前 Execution Engine 的问题：
- ❌ 通过公共 Trade Stream 估算自己的成交，误差大
- ❌ 不知道订单的真实状态（NEW / PARTIALLY_FILLED / FILLED / CANCELED）
- ❌ 无法精确计算持仓、可用余额、平均成交价格
- ❌ 部分成交场景完全丢失

> **没有 User Data Stream 的系统，是在"盲打"。**

---

## 二、架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                  Binance User Data Stream                    │
│           (WebSocket: wss://stream.binance.com:9443/ws/<key>)│
├─────────────────────────────────────────────────────────────┤
│  Event Type:                                                │
│  - executionReport    → 订单状态变化（成交/部分成交/撤单）    │
│  - outboundAccountPosition → 账户余额变化                   │
└────────────────────┬────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────┐
│                  OrderStateMachine (OSM)                     │
├─────────────────────────────────────────────────────────────┤
│  状态流转：                                                  │
│  SUBMITTED → NEW → OPEN → PARTIALLY_FILLED → FILLED        │
│                       ↓                                      │
│                   CANCELED / REJECTED / EXPIRED             │
├─────────────────────────────────────────────────────────────┤
│  职责：                                                      │
│  - 精确维护每个订单的当前状态                                │
│  - 累计已成交数量和均价                                      │
│  - 触发回调（on_fill, on_partial_fill, on_cancel）         │
│  - 与 PositionManager 双向同步                               │
└────────────────────┬────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────┐
│                  PositionManager (账户层)                    │
├─────────────────────────────────────────────────────────────┤
│  - 跟踪 symbol 级别的持仓（base/free/locked）                │
│  - 根据 outboundAccountPosition 更新余额                    │
│  - 计算持仓 PnL、持仓成本                                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、模块实现

### 3.1 核心数据结构扩展

在 `core/execution_models.py` 中新增：

```python
from enum import auto

class OrderStatus(Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    NEW = "NEW"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

@dataclass
class FillEvent:
    """单笔成交事件"""
    order_id: str
    symbol: str
    price: float
    size: float
    side: OrderSide
    commission: float
    commission_asset: str
    trade_id: int
    timestamp: float

@dataclass
class Position:
    """单个交易对的持仓状态"""
    symbol: str
    base_asset: str
    quote_asset: str
    free: float = 0.0      # 可用
    locked: float = 0.0    # 挂单冻结
    total: float = 0.0     # 总持仓
    avg_cost: float = 0.0  # 平均成本
```

---

### 3.2 Binance User Data Stream 客户端

创建文件 `core/binance_user_data_client.py`：

```python
import json
import threading
import time
import requests
import websocket
from typing import Callable, Optional

class BinanceUserDataClient:
    """
    Binance User Data Stream 客户端
    负责 listenKey 的申请、续期和 WebSocket 连接管理
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = "https://api.binance.com",
        ws_url: str = "wss://stream.binance.com:9443/ws"
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.ws_url = ws_url
        self.listen_key: Optional[str] = None
        self.ws: Optional[websocket.WebSocketApp] = None
        self._stop_event = threading.Event()

        # 回调注册
        self.on_execution_report: Optional[Callable[[dict], None]] = None
        self.on_account_position: Optional[Callable[[dict], None]] = None

    def _request(self, method: str, endpoint: str, params: dict = None) -> dict:
        import hmac
        import hashlib
        from urllib.parse import urlencode

        params = params or {}
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode(),
            query.encode(),
            hashlib.sha256
        ).hexdigest()
        params["signature"] = signature

        resp = requests.request(
            method,
            f"{self.base_url}{endpoint}",
            headers={"X-MBX-APIKEY": self.api_key},
            params=params,
            timeout=10
        )
        return resp.json()

    def _get_listen_key(self) -> str:
        data = self._request("POST", "/api/v3/userDataStream")
        return data["listenKey"]

    def _keepalive(self):
        while not self._stop_event.is_set():
            time.sleep(1800)  # 30分钟续期
            if self.listen_key:
                try:
                    self._request("PUT", "/api/v3/userDataStream", {"listenKey": self.listen_key})
                except Exception as e:
                    print(f"[UserData] keepalive failed: {e}")

    def _on_message(self, ws, message):
        data = json.loads(message)
        event_type = data.get("e")

        if event_type == "executionReport":
            if self.on_execution_report:
                self.on_execution_report(data)
        elif event_type == "outboundAccountPosition":
            if self.on_account_position:
                self.on_account_position(data)

    def start(self):
        self.listen_key = self._get_listen_key()
        url = f"{self.ws_url}/{self.listen_key}"

        self.ws = websocket.WebSocketApp(
            url,
            on_message=self._on_message,
            on_error=lambda ws, e: print(f"[UserData WS Error] {e}"),
            on_close=lambda ws, s, m: print("[UserData WS Closed]")
        )

        def run():
            while not self._stop_event.is_set():
                try:
                    self.ws.run_forever()
                except Exception as e:
                    print(f"[UserData Reconnect] {e}")
                time.sleep(2)

        threading.Thread(target=run, daemon=True).start()
        threading.Thread(target=self._keepalive, daemon=True).start()

    def stop(self):
        self._stop_event.set()
        if self.ws:
            self.ws.close()
        if self.listen_key:
            try:
                self._request("DELETE", "/api/v3/userDataStream", {"listenKey": self.listen_key})
            except Exception:
                pass
```

---

### 3.3 Order State Machine

创建文件 `core/order_state_machine.py`：

```python
from typing import Dict, Callable, Optional, List
from core.execution_models import Order, OrderStatus, FillEvent, OrderSide

class OrderStateMachine:
    """
    基于 Binance executionReport 维护订单的完整生命周期。
    """

    def __init__(self):
        self.orders: Dict[str, Order] = {}
        self.fills: Dict[str, List[FillEvent]] = {}

        # 回调
        self.on_fill: Optional[Callable[[FillEvent], None]] = None
        self.on_partial_fill: Optional[Callable[[Order, FillEvent], None]] = None
        self.on_cancel: Optional[Callable[[Order], None]] = None
        self.on_reject: Optional[Callable[[Order], None]] = None

    def register_order(self, order: Order):
        """在 REST 下单成功后注册订单"""
        order.status = OrderStatus.SUBMITTED.value
        self.orders[order.id] = order
        self.fills[order.id] = []

    def handle_execution_report(self, report: dict):
        """
        处理 Binance executionReport 事件
        """
        order_id = report.get("c")  # clientOrderId
        if not order_id or order_id not in self.orders:
            return

        order = self.orders[order_id]
        event_status = report.get("X")  # Current order status
        exec_type = report.get("x")     # Execution type

        # 更新已成交数量和均价
        last_exec_qty = float(report.get("l", 0))
        last_exec_price = float(report.get("L", 0))
        cumulated_qty = float(report.get("z", 0))
        avg_price = float(report.get("ap", 0))

        order.filled_size = cumulated_qty
        order.avg_fill_price = avg_price if avg_price > 0 else order.avg_fill_price

        # 状态映射
        status_map = {
            "NEW": OrderStatus.NEW.value,
            "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED.value,
            "FILLED": OrderStatus.FILLED.value,
            "CANCELED": OrderStatus.CANCELED.value,
            "REJECTED": OrderStatus.REJECTED.value,
            "EXPIRED": OrderStatus.EXPIRED.value,
        }
        order.status = status_map.get(event_status, order.status)

        # 生成 FillEvent
        if last_exec_qty > 0:
            fill = FillEvent(
                order_id=order_id,
                symbol=report.get("s", order.symbol),
                price=last_exec_price,
                size=last_exec_qty,
                side=OrderSide.BUY if report.get("S") == "BUY" else OrderSide.SELL,
                commission=float(report.get("n", 0)),
                commission_asset=report.get("N", ""),
                trade_id=report.get("t", 0),
                timestamp=report.get("T", 0) / 1000.0
            )
            self.fills[order_id].append(fill)

            if event_status == "PARTIALLY_FILLED" and self.on_partial_fill:
                self.on_partial_fill(order, fill)
            elif event_status == "FILLED" and self.on_fill:
                self.on_fill(fill)

        if event_status in ("CANCELED", "EXPIRED") and self.on_cancel:
            self.on_cancel(order)

        if event_status == "REJECTED" and self.on_reject:
            self.on_reject(order)

    def get_order(self, order_id: str) -> Optional[Order]:
        return self.orders.get(order_id)

    def get_open_orders(self) -> List[Order]:
        return [
            o for o in self.orders.values()
            if o.status in (OrderStatus.NEW.value, OrderStatus.OPEN.value, OrderStatus.PARTIALLY_FILLED.value)
        ]

    def get_fills(self, order_id: str) -> List[FillEvent]:
        return self.fills.get(order_id, [])
```

---

### 3.4 Position Manager

创建文件 `core/position_manager.py`：

```python
from typing import Dict
from core.execution_models import Position

class PositionManager:
    """
    基于 outboundAccountPosition 维护账户持仓。
    """

    def __init__(self):
        self.positions: Dict[str, Position] = {}

    def handle_account_position(self, payload: dict):
        """
        处理 outboundAccountPosition 事件
        """
        for bal in payload.get("B", []):
            asset = bal.get("a")
            free = float(bal.get("f", 0))
            locked = float(bal.get("l", 0))

            # 简化：用户需要自行把 asset 映射到 symbol
            # 实际场景中通常会维护 symbol -> (base, quote) 的映射表
            if asset not in self.positions:
                continue

            pos = self.positions[asset]
            pos.free = free
            pos.locked = locked
            pos.total = free + locked

    def update_position_from_fill(self, fill_event):
        """
        根据成交事件微调持仓（作为 User Stream 的后备校验）
        """
        symbol = fill_event.symbol
        if symbol not in self.positions:
            base = symbol[:-4] if symbol.endswith("USDT") else symbol[:3]
            self.positions[symbol] = Position(symbol=symbol, base_asset=base, quote_asset="USDT")

        pos = self.positions[symbol]
        if fill_event.side.value == "BUY":
            # 更新平均成本
            total_cost = pos.avg_cost * pos.total + fill_event.price * fill_event.size
            pos.total += fill_event.size
            pos.avg_cost = total_cost / pos.total if pos.total > 0 else 0
        else:
            pos.total -= fill_event.size
            if pos.total <= 0:
                pos.avg_cost = 0

    def get_position(self, symbol: str) -> Position:
        return self.positions.get(symbol, Position(symbol=symbol, base_asset="", quote_asset=""))
```

---

## 四、与 SelfEvolvingTrader 集成

### 4.1 初始化

修改 `self_evolving_trader.py`：

```python
class SelfEvolvingTrader:
    def __init__(self, config: TraderConfig):
        # ... existing code ...
        self.user_data_client: Optional[BinanceUserDataClient] = None
        self.order_fsm = OrderStateMachine()
        self.position_manager = PositionManager()

    async def initialize(self):
        # ... existing code ...

        # 初始化 User Data Stream
        if self.config.api_key and self.config.api_secret:
            self.user_data_client = BinanceUserDataClient(
                api_key=self.config.api_key,
                api_secret=self.config.api_secret
            )
            self.user_data_client.on_execution_report = self.order_fsm.handle_execution_report
            self.user_data_client.on_account_position = self.position_manager.handle_account_position
            self.order_fsm.on_fill = self._on_order_filled
            self.order_fsm.on_partial_fill = self._on_partial_fill
            self.user_data_client.start()
            logger.info("[SelfEvolvingTrader] User Data Stream started")

    async def stop(self):
        # ... existing code ...
        if self.user_data_client:
            self.user_data_client.stop()

    def _on_order_filled(self, fill: FillEvent):
        logger.info(f"[Fill] {fill.side.value} {fill.size} @ {fill.price}")
        self.position_manager.update_position_from_fill(fill)
        # 通知 Meta-Agent 归因
        # self.meta_agent.record_trade(...)

    def _on_partial_fill(self, order: Order, fill: FillEvent):
        logger.info(f"[Partial Fill] {order.id}: {fill.size} @ {fill.price}")
        self.position_manager.update_position_from_fill(fill)
```

### 4.2 交易周期中的精确下单

```python
async def _trading_cycle(self):
    signal = await self._generate_signal()

    if self.execution_policy and self.ws_client and self.ws_client.book:
        action, price = self.execution_policy.decide(
            signal_strength=signal["confidence"],
            book=self.ws_client.book,
            estimated_size=signal["size"]
        )

        if action != ExecutionAction.WAIT:
            order_type = OrderType.MARKET if action == ExecutionAction.MARKET else OrderType.LIMIT
            client_order_id = f"evt_{uuid.uuid4().hex[:16]}"
            order = Order(
                id=client_order_id,
                symbol=self.config.symbol,
                side=OrderSide.BUY if signal["direction"] > 0 else OrderSide.SELL,
                order_type=order_type,
                size=signal["size"],
                price=price
            )

            # 1. 先注册到 OSM
            self.order_fsm.register_order(order)

            # 2. 再发 REST 下单
            res = self.rest_client.place_order(
                symbol=order.symbol,
                side=order.side.value,
                quantity=order.size,
                price=order.price,
                order_type=order.order_type.value
            )

            if res.get("status") in ("NEW", "PARTIALLY_FILLED", "FILLED"):
                # 更新 exchange order id 等可选
                pass
            else:
                logger.error(f"[Order Failed] {res}")
                order.status = OrderStatus.REJECTED.value
```

---

## 五、生产 Checklist

| # | 检查项 | 状态 |
|---|--------|------|
| 1 | User Data Stream 的 listenKey 续期机制已验证 | ☐ |
| 2 | WebSocket 断线后自动重连 + 重新申请 listenKey | ☐ |
| 3 | OSM 状态流转覆盖了所有 Binance `X` 字段状态 | ☐ |
| 4 | `clientOrderId` 生成策略唯一且可追踪 | ☐ |
| 5 | 部分成交场景下持仓和 PnL 计算正确 | ☐ |
| 6 | `outboundAccountPosition` 与执行结果交叉验证 | ☐ |
| 7 | Reject / Expired 订单有告警和日志记录 | ☐ |

---

## 六、已知问题和下一步

1. **当前简化处理**：`PositionManager` 中 asset -> symbol 的映射是简化版，生产环境应维护完整的交易对元数据表。
2. **多币种持仓**：目前主要聚焦 spot 单交易对，多币种组合持仓需要更复杂的 PnL 归因。
3. **下一步**：接入 Cancel / Reprice 引擎，实现自动撤单重挂。

---

*文档版本: v1.0*
*适用项目: binance/new Self-Evolving Trader*
*创建日期: 2026-04-02*
