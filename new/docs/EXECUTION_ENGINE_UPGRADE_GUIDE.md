# Execution Engine 升级指南

> 目标：将现有的 Self-Evolving Trader 从"信号系统"升级为"信号 + 执行系统"，支持 Binance 实盘接入。

---

## 一、为什么必须做 Execution Engine

当前系统状态：
- ✅ 多策略信号生成 (DualMA / Momentum / RSI)
- ✅ Meta-Agent 权重分配
- ✅ Regime Detector 市场状态识别
- ✅ PBT 策略进化
- ✅ Checkpoint 状态持久化
- ❌ **没有执行层优化**

> **没有 Execution Engine 的系统，Alpha 会在滑点和排队中全部消失。**

Execution Engine 解决的核心问题：
1. **订单类型选择**：Limit (passive) vs Market (aggressive)
2. **排队位置建模**：你在 OrderBook 队列中的位置
3. **成交概率估计**：挂单多久能被吃掉
4. **滑点与冲击成本**：大单对市场的影响

---

## 二、架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                    SelfEvolvingTrader                        │
├─────────────────────────────────────────────────────────────┤
│  Phase 1-9: Signal Generation (已有)                        │
│     ↓                                                        │
│  ┌───────────────────────────────────────────────────────┐   │
│  │         Execution Engine (新增)                        │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │ Queue    │  │ Fill     │  │ Slippage │          │   │
│  │  │ Model    │  │ Model    │  │ Model    │          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  │  ┌───────────────────────────────────────────────┐  │   │
│  │  │         ExecutionPolicy                        │  │   │
│  │  │  (决定将信号转化为 LIMIT/MARKET/WAIT)          │  │   │
│  │  └───────────────────────────────────────────────┘  │   │
│  └───────────────────────────────────────────────────────┘   │
│     ↓                                                        │
│  ┌───────────────────────────────────────────────────────┐   │
│  │         Binance Live (新增)                            │   │
│  │  WebSocket(L2+Trade) → REST(Order+Account)           │   │
│  └───────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、模块实现

### 3.1 核心数据结构

创建文件 `core/execution_models.py`：

```python
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional
from enum import Enum
import time

class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderType(Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"

@dataclass
class Order:
    """标准化订单"""
    id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    size: float
    price: Optional[float] = None
    timestamp: float = field(default_factory=time.time)
    filled_size: float = 0.0
    avg_fill_price: float = 0.0
    status: str = "PENDING"  # PENDING, OPEN, PARTIALLY_FILLED, FILLED, CANCELLED

@dataclass
class OrderBook:
    """L2 订单簿快照"""
    bids: List[Tuple[float, float]]  # (price, size)
    asks: List[Tuple[float, float]]
    timestamp: float = field(default_factory=time.time)

    def best_bid(self) -> Optional[float]:
        return self.bids[0][0] if self.bids else None

    def best_ask(self) -> Optional[float]:
        return self.asks[0][0] if self.asks else None

    def mid_price(self) -> Optional[float]:
        bb = self.best_bid()
        ba = self.best_ask()
        return (bb + ba) / 2 if bb and ba else None

    def spread(self) -> Optional[float]:
        ba = self.best_ask()
        bb = self.best_bid()
        return ba - bb if ba and bb else None
```

---

### 3.2 Queue Model（排队模型）

创建文件 `core/queue_model.py`：

```python
from typing import Dict, Optional
from core.execution_models import Order, OrderBook

class QueueModel:
    """
    模拟订单在 Level 2 队列中的位置。
    核心假设：同价位订单 FIFO。
    """

    def __init__(self):
        # order_id -> 前面还有多少数量排队
        self.positions: Dict[str, float] = {}

    def estimate_position(self, order: Order, book: OrderBook) -> Optional[float]:
        """估算新订单进入队列时的前方数量"""
        if order.order_type == OrderType.MARKET:
            return 0.0

        if order.side.value == "BUY":
            best_bid = book.best_bid()
            if best_bid and order.price and order.price >= best_bid:
                # 挂在买单队列末尾（或插队到同价位末尾）
                bid_size = sum(size for price, size in book.bids if price == order.price)
                return bid_size
            else:
                # 如果是 maker 且价格更优，挂在新价位队首
                return 0.0
        else:
            best_ask = book.best_ask()
            if best_ask and order.price and order.price <= best_ask:
                ask_size = sum(size for price, size in book.asks if price == order.price)
                return ask_size
            else:
                return 0.0

    def register_order(self, order: Order, book: OrderBook):
        """记录订单进入队列时的位置"""
        pos = self.estimate_position(order, book)
        if pos is not None:
            self.positions[order.id] = pos

    def update_on_trade(self, order_id: str, traded_volume: float) -> bool:
        """
        根据市场成交更新队列位置。
        返回 True 表示该订单已完全成交。
        """
        if order_id not in self.positions:
            return False

        self.positions[order_id] -= traded_volume
        return self.positions[order_id] <= 0

    def remove_order(self, order_id: str):
        self.positions.pop(order_id, None)
```

---

### 3.3 Fill Model（成交概率模型）

创建文件 `core/fill_model.py`：

```python
class FillModel:
    """
    基于队列位置和市场流速估算成交概率。
    """

    def __init__(self):
        self.recent_trade_volume = 0.0  # 最近 1s 成交量
        self.recent_cancel_volume = 0.0

    def update_market_flow(self, trade_vol: float, cancel_vol: float):
        self.recent_trade_volume = trade_vol
        self.recent_cancel_volume = cancel_vol

    def fill_probability(self, queue_position: float, time_horizon_s: float = 1.0) -> float:
        """
        简化版 Hazard Rate 模型：
        P(fill) = 1 - exp(-lambda * t)
        lambda = effective_flow / (queue_position + epsilon)
        """
        effective_flow = self.recent_trade_volume + self.recent_cancel_volume * 0.3
        if effective_flow <= 0:
            return 0.0

        hazard_rate = effective_flow / (queue_position + 1e-6)
        prob = 1.0 - pow(2.71828, -hazard_rate * time_horizon_s)
        return min(1.0, max(0.0, prob))
```

---

### 3.4 Slippage Model（滑点模型）

创建文件 `core/slippage_model.py`：

```python
from typing import Optional
from core.execution_models import Order, OrderBook, OrderSide

class SlippageModel:
    """
    估算市场单（Market Order）的执行均价。
    """

    def estimate_execution_price(self, order: Order, book: OrderBook) -> Optional[float]:
        if not book.bids or not book.asks:
            return None

        remaining = order.size
        total_cost = 0.0

        if order.side == OrderSide.BUY:
            levels = book.asks
        else:
            levels = book.bids

        for price, size in levels:
            take = min(size, remaining)
            total_cost += take * price
            remaining -= take
            if remaining <= 1e-9:
                break

        if remaining > 1e-9:
            # 流动性不足，深度不够
            return None

        return total_cost / order.size

    def estimate_slippage_bps(self, order: Order, book: OrderBook) -> Optional[float]:
        exec_price = self.estimate_execution_price(order, book)
        mid = book.mid_price()
        if not exec_price or not mid:
            return None

        slippage = abs(exec_price - mid) / mid
        return slippage * 10000  # convert to bps
```

---

### 3.5 Execution Policy（执行策略核心）

创建文件 `core/execution_policy.py`：

```python
from enum import Enum
from typing import Optional, Tuple
from core.execution_models import Order, OrderSide, OrderType, OrderBook
from core.queue_model import QueueModel
from core.fill_model import FillModel
from core.slippage_model import SlippageModel

class ExecutionAction(Enum):
    LIMIT_PASSIVE = "LIMIT_PASSIVE"   # 挂限价单，吃 rebate
    LIMIT_AGGRESSIVE = "LIMIT_AGGRESSIVE"  # 扫一挂单
    MARKET = "MARKET"                  # 市价立即成交
    WAIT = "WAIT"                      # 等待

class ExecutionPolicy:
    """
    根据信号强度、市场状态和排队情况，决定最优执行方式。
    """

    def __init__(
        self,
        queue_model: QueueModel,
        fill_model: FillModel,
        slippage_model: SlippageModel,
        max_slippage_bps: float = 5.0,
        min_fill_prob: float = 0.3,
        latency_ms: float = 50.0
    ):
        self.queue_model = queue_model
        self.fill_model = fill_model
        self.slippage_model = slippage_model
        self.max_slippage_bps = max_slippage_bps
        self.min_fill_prob = min_fill_prob
        self.latency_ms = latency_ms

    def decide(
        self,
        signal_strength: float,  # -1.0 ~ +1.0
        book: OrderBook,
        estimated_size: float
    ) -> Tuple[ExecutionAction, Optional[float]]:
        """
        返回：(执行动作, 建议价格)
        """
        if abs(signal_strength) < 0.2:
            return ExecutionAction.WAIT, None

        side = OrderSide.BUY if signal_strength > 0 else OrderSide.SELL

        # 1. 估算市价单滑点
        market_order = Order(
            id="estimate",
            symbol="",
            side=side,
            order_type=OrderType.MARKET,
            size=estimated_size
        )
        slip_bps = self.slippage_model.estimate_slippage_bps(market_order, book)

        # 2. 估算限价单排队位置和成交概率
        if side == OrderSide.BUY:
            limit_price = book.best_bid()
        else:
            limit_price = book.best_ask()

        if limit_price is None:
            return ExecutionAction.MARKET, None

        limit_order = Order(
            id="estimate",
            symbol="",
            side=side,
            order_type=OrderType.LIMIT,
            size=estimated_size,
            price=limit_price
        )
        queue_pos = self.queue_model.estimate_position(limit_order, book) or 0.0
        fill_prob = self.fill_model.fill_probability(queue_pos, time_horizon_s=1.0)

        # 3. 决策逻辑
        urgency = abs(signal_strength) - (self.latency_ms / 1000.0)

        if urgency > 0.8:
            # 信号极强，立即成交
            return ExecutionAction.MARKET, None

        if slip_bps is not None and slip_bps > self.max_slippage_bps:
            # 滑点太大，尝试 passive limit
            return ExecutionAction.LIMIT_PASSIVE, limit_price

        if fill_prob > 0.7:
            # 成交概率高，挂单
            return ExecutionAction.LIMIT_AGGRESSIVE, limit_price

        if queue_pos < estimated_size * 2:
            # 排队位置靠前，值得挂
            return ExecutionAction.LIMIT_PASSIVE, limit_price

        return ExecutionAction.WAIT, None
```

---

## 四、Binance 实盘接入（最小可用版）

### 4.1 REST 客户端

创建文件 `core/binance_rest_client.py`：

```python
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode

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
```

---

### 4.2 WebSocket 客户端

创建文件 `core/binance_ws_client.py`：

```python
import websocket
import json
import threading
import time
from typing import Callable, Optional
from core.execution_models import OrderBook

class BinanceWSClient:
    """
    订阅 Binance 合并流：L2 OrderBook + Trade Stream
    """

    def __init__(self, symbol: str):
        self.symbol = symbol.lower()
        self.book: Optional[OrderBook] = None
        self.last_price: Optional[float] = None
        self.on_trade_callback: Optional[Callable] = None

    def on_message(self, ws, message):
        data = json.loads(message)
        stream = data.get("stream", "")
        payload = data.get("data", {})

        if "depth" in stream:
            bids = [(float(p), float(s)) for p, s in payload.get("b", [])[:5]]
            asks = [(float(p), float(s)) for p, s in payload.get("a", [])[:5]]
            self.book = OrderBook(bids=bids, asks=asks)

        elif "trade" in stream:
            self.last_price = float(payload.get("p", 0))
            if self.on_trade_callback:
                self.on_trade_callback(payload)

    def start(self):
        streams = f"{self.symbol}@depth5@100ms/{self.symbol}@trade"
        url = f"wss://stream.binance.com:9443/stream?streams={streams}"

        ws = websocket.WebSocketApp(
            url,
            on_message=self.on_message,
            on_error=lambda ws, e: print(f"[WS Error] {e}"),
            on_close=lambda ws, status, msg: print("[WS Closed]")
        )

        def run():
            while True:
                try:
                    ws.run_forever()
                except Exception as e:
                    print(f"[WS Reconnect] {e}")
                time.sleep(2)

        threading.Thread(target=run, daemon=True).start()
```

---

## 五、与现有 SelfEvolvingTrader 集成

### 5.1 集成点

修改 `self_evolving_trader.py`：

```python
class SelfEvolvingTrader:
    def __init__(self, config: TraderConfig):
        # ... existing code ...

        # Execution components
        self.execution_policy: Optional[ExecutionPolicy] = None
        self.queue_model = QueueModel()
        self.fill_model = FillModel()
        self.slippage_model = SlippageModel()

    async def initialize(self):
        # ... existing code ...

        # 初始化 Execution Engine
        self.execution_policy = ExecutionPolicy(
            queue_model=self.queue_model,
            fill_model=self.fill_model,
            slippage_model=self.slippage_model,
            max_slippage_bps=5.0,
            min_fill_prob=0.3,
            latency_ms=50.0
        )
        logger.info("[SelfEvolvingTrader] Execution Engine initialized")
```

### 5.2 交易周期中引入执行层

在 `_trading_cycle()` 的信号生成之后插入：

```python
async def _trading_cycle(self):
    # ... Phase 1-3: 生成策略信号 ...
    signal = await self._generate_signal()

    # NEW: Execution Layer
    if self.execution_policy and self.ws_client and self.ws_client.book:
        action, price = self.execution_policy.decide(
            signal_strength=signal["confidence"],
            book=self.ws_client.book,
            estimated_size=signal["size"]
        )

        if action != ExecutionAction.WAIT:
            order_type = OrderType.MARKET if action == ExecutionAction.MARKET else OrderType.LIMIT
            order = Order(
                id=str(uuid.uuid4()),
                symbol=self.config.symbol,
                side=OrderSide.BUY if signal["direction"] > 0 else OrderSide.SELL,
                order_type=order_type,
                size=signal["size"],
                price=price
            )
            # 提交到 Binance
            res = self.rest_client.place_order(...)
            # 记录到 QueueModel
            self.queue_model.register_order(order, self.ws_client.book)
```

---

## 六、生产 Checklist

在接入实盘前，必须完成以下检查：

| # | 检查项 | 状态 |
|---|--------|------|
| 1 | API Key 权限仅开启 **SPOT + MARGIN 交易**，禁止提现 | ☐ |
| 2 | 订单数量精度已对齐 Binance `LOT_SIZE` 过滤规则 | ☐ |
| 3 | 订单价格精度已对齐 Binance `PRICE_FILTER` 规则 | ☐ |
| 4 | 已接入 **User Data Stream** 监听成交回报 | ☐ |
| 5 | Kill Switch 已测试（日亏损 > X% 自动停止） | ☐ |
| 6 | 网络断连时，WebSocket 自动重连已验证 | ☐ |
| 7 | 已用最小仓位（如 $10 等值）完成沙盒测试 | ☐ |
| 8 | REST 请求已加 rate limit（Binance 112 req/10s per IP） | ☐ |

---

## 七、已知问题和限制

1. **当前 QueueModel 是简化 FIFO**： Binance 撮合引擎实际上是 Price-Time Priority，但队列内部可能受冰山订单、事件优先级等影响，精确建模需要 Level 3 数据。
2. **User Data Stream 未接入**： 当前版本依赖 WebSocket Trade Stream 估算成交，不如 User Stream 精确。生产环境必须接入 `/api/v3/userDataStream`。
3. **FillModel 参数需要校准**： `recent_trade_volume` 和 `recent_cancel_volume` 的估计需要基于历史数据拟合，当前使用经验值。

---

## 八、下一步升级路线

完成本阶段后，建议按以下优先级继续：

1. **User Data Stream**：精确监听个人订单的成交、部分成交、撤单事件。
2. **Order State Machine**：追踪每个订单从 SUBMIT → OPEN → PARTIAL → FILLED / CANCELLED 的完整生命周期。
3. **Cancel Strategy**：当信号消失、排队过深或市场状态剧变时自动撤单重挂。
4. **Latency Model**：量化网络延迟 + 交易所处理延迟 + 本地处理延迟。
5. **Execution RL**：将 Execution Engine 封装为 Gym 环境，使用 SAC 训练最优执行策略。

---

## 九、设计原则

> **Execution Alpha 的核心不是预测价格，而是优化"成交成本"。**

* **Passive Limit**（被动挂单）：吃 rebate，成本低，但成交不确定
* **Aggressive Market**（市价 aggressively）：立即成交，确定性高，但付 spread + taker fee
* **Smart Router**（智能路由）：根据 urgency、queue depth、fill prob 动态选择

---

*文档版本: v1.0*
*适用项目: binance/new Self-Evolving Trader*
*创建日期: 2026-04-02*
