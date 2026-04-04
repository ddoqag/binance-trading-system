# Cancel / Reprice 与 Queue Tracking 升级指南

> 目标：在信号消失、排队过深、市场状态剧变或队列位置恶化时，自动撤单并智能重挂，降低机会成本和 adverse selection 风险。

---

## 一、为什么必须做 Cancel / Reprice

当前 Execution Engine 的订单一旦提交就"放任自流"，存在以下问题：
- ❌ **信号消失后订单仍挂在那里**：策略方向已反转，但老订单还在排队
- ❌ **排队位置持续恶化**：大量新单涌入，你被越挤越靠后，成交概率趋近于零
- ❌ **市场状态剧变**：Regime Detector 识别出高波动/毒流状态，但订单未撤
- ❌ **手动管理成本高**：高频场景下人工判断撤/重挂完全不现实

> **没有 Cancel 策略的系统，会把本金和时间都浪费在"无效排队"上。**

---

## 二、架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                   SelfEvolvingTrader                        │
├─────────────────────────────────────────────────────────────┤
│  触发源：                                                    │
│  ├─ Signal Change          (策略方向改变)                   │
│  ├─ Regime Change          (市场状态剧变)                   │
│  ├─ Queue Position Time-Out (排队过久未成交)                │
│  ├─ Adverse Selection Alert (毒流检测触发)                  │
│  └─ Price Drift            (挂单价偏离当前 best 太远)       │
│                            ↓                                │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              CancelManager                             │  │
│  │  - 评估每个 OPEN / PARTIALLY_FILLED 订单的留存价值     │  │
│  │  - 生成 cancel 决策                                    │  │
│  │  - 调用 Binance REST 撤单接口                          │  │
│  └────────────────────┬──────────────────────────────────┘  │
│                       ↓                                     │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              RepriceEngine                             │  │
│  │  - 对撤单后的剩余数量重新定价                          │  │
│  │  - 选择新的 limit price（更优/更激进/被动）            │  │
│  │  - 生成新订单并重新注册到 OSM + QueueModel             │  │
│  └────────────────────┬──────────────────────────────────┘  │
│                       ↓                                     │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              QueueTracker                              │  │
│  │  - 实时估算每个活跃订单的当前队列位置                  │  │
│  │  - 基于 L2 diff + Trade Stream 更新前方数量            │  │
│  │  - 提供 "队列生存率" 指标                              │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、模块实现

### 3.1 QueueTracker（队列位置实时跟踪）

创建文件 `core/queue_tracker.py`：

```python
import time
from typing import Dict, Optional
from dataclasses import dataclass
from core.execution_models import Order, OrderBook, OrderSide

@dataclass
class QueueSnapshot:
    """某个订单在队列中的快照"""
    order_id: str
    initial_position: float      # 最初前方数量
    current_position: float      # 当前估算前方数量
    last_update_time: float
    entry_price: float
    side: OrderSide

class QueueTracker:
    """
    基于 OrderBook diff 和 Trade Stream，实时估算活跃订单的队列位置。
    核心逻辑：同价位前方数量被吃掉或被撤单，当前位置前移。
    """

    def __init__(self):
        self.snapshots: Dict[str, QueueSnapshot] = {}
        self._last_book: Optional[OrderBook] = None

    def register(self, order: Order, book: OrderBook):
        """订单进入 OSM 时同步注册到 QueueTracker"""
        if order.order_type.value == "MARKET":
            return

        front_size = self._estimate_front_size(order, book)
        self.snapshots[order.id] = QueueSnapshot(
            order_id=order.id,
            initial_position=front_size,
            current_position=front_size,
            last_update_time=time.time(),
            entry_price=order.price or 0.0,
            side=order.side
        )

    def _estimate_front_size(self, order: Order, book: OrderBook) -> float:
        """估算订单进入时，同价位前方有多少数量"""
        target_price = order.price
        if order.side == OrderSide.BUY:
            match_levels = book.bids
        else:
            match_levels = book.asks

        front = 0.0
        for price, size in match_levels:
            if abs(price - target_price) < 1e-9:
                # 假设新订单挂到同价位末尾
                front += size
            elif (order.side == OrderSide.BUY and price > target_price) or \
                 (order.side == OrderSide.SELL and price < target_price):
                # 更优价位订单会在你前面先成交，需累加
                front += size
            else:
                break
        return front

    def update_on_book(self, book: OrderBook):
        """
        每次收到新的 depth 更新时，重新估算队列位置。
        简化策略：如果同价位的总数量相比上一次下降了 delta，
        则假设你前方被消耗了 min(delta, current_position)。
        """
        for snap in self.snapshots.values():
            if snap.side == OrderSide.BUY:
                levels = book.bids
            else:
                levels = book.asks

            current_size_at_price = sum(
                size for price, size in levels
                if abs(price - snap.entry_price) < 1e-9
            )

            if self._last_book:
                if snap.side == OrderSide.BUY:
                    old_levels = self._last_book.bids
                else:
                    old_levels = self._last_book.asks
                old_size_at_price = sum(
                    size for price, size in old_levels
                    if abs(price - snap.entry_price) < 1e-9
                )
                delta = old_size_at_price - current_size_at_price
                if delta > 0:
                    snap.current_position = max(0.0, snap.current_position - delta)

            snap.last_update_time = time.time()

        self._last_book = book

    def update_on_trade(self, trade_payload: dict):
        """
        基于 Trade Stream 的成交方向，粗略调整队列位置。
        仅在同价位成交且方向匹配时前移。
        """
        trade_price = float(trade_payload.get("p", 0))
        trade_qty = float(trade_payload.get("q", 0))
        # 简化处理：所有在 trade_price 价位的挂单都减去一部分
        for snap in self.snapshots.values():
            if abs(snap.entry_price - trade_price) < 1e-9:
                snap.current_position = max(0.0, snap.current_position - trade_qty)

    def get_queue_ratio(self, order_id: str) -> float:
        """返回队列位置比率 (0=队首, 1=队尾或更差)"""
        snap = self.snapshots.get(order_id)
        if not snap:
            return 1.0
        if snap.initial_position <= 0:
            return 0.0
        return min(1.0, snap.current_position / snap.initial_position)

    def get_survival_rate(self, order_id: str) -> float:
        """返回队列生存率 (1=位置没变, 0=已到队首)"""
        return 1.0 - self.get_queue_ratio(order_id)

    def remove(self, order_id: str):
        self.snapshots.pop(order_id, None)
```

---

### 3.2 CancelManager（撤单决策器）

创建文件 `core/cancel_manager.py`：

```python
import time
from typing import List, Optional
from dataclasses import dataclass
from enum import Enum
from core.execution_models import Order, OrderStatus
from core.queue_tracker import QueueTracker

class CancelReason(Enum):
    SIGNAL_REVERSED = "SIGNAL_REVERSED"
    REGIME_CHANGED = "REGIME_CHANGED"
    QUEUE_TIMEOUT = "QUEUE_TIMEOUT"
    ADVERSE_SELECTION = "ADVERSE_SELECTION"
    PRICE_DRIFT = "PRICE_DRIFT"

@dataclass
class CancelDecision:
    order_id: str
    should_cancel: bool
    reason: CancelReason
    detail: str

class CancelManager:
    """
    评估每个活跃订单是否应该被撤销。
    """

    def __init__(
        self,
        queue_tracker: QueueTracker,
        max_queue_wait_seconds: float = 10.0,
        max_queue_ratio: float = 0.8,
        price_drift_ticks: int = 2,
        tick_size: float = 0.01
    ):
        self.queue_tracker = queue_tracker
        self.max_queue_wait_seconds = max_queue_wait_seconds
        self.max_queue_ratio = max_queue_ratio
        self.price_drift_ticks = price_drift_ticks
        self.tick_size = tick_size

    def evaluate(
        self,
        order: Order,
        current_signal: Optional[dict] = None,
        current_regime: Optional[str] = None,
        order_regime: Optional[str] = None,
        adverse_alert: bool = False,
        current_best_bid: Optional[float] = None,
        current_best_ask: Optional[float] = None
    ) -> CancelDecision:
        order_id = order.id

        # 1. 信号反转
        if current_signal is not None:
            direction = 1 if order.side.value == "BUY" else -1
            signal_dir = 1 if current_signal.get("direction", 0) > 0 else -1
            if direction != signal_dir:
                return CancelDecision(
                    order_id=order_id,
                    should_cancel=True,
                    reason=CancelReason.SIGNAL_REVERSED,
                    detail="Signal direction reversed"
                )

        # 2. 市场状态剧变
        if current_regime and order_regime and current_regime != order_regime:
            volatile_regimes = {"high_volatility", "crash", "panic"}
            if current_regime in volatile_regimes:
                return CancelDecision(
                    order_id=order_id,
                    should_cancel=True,
                    reason=CancelReason.REGIME_CHANGED,
                    detail=f"Regime changed from {order_regime} to {current_regime}"
                )

        # 3. 排队超时 / 位置过差
        snapshot = self.queue_tracker.snapshots.get(order_id)
        if snapshot:
            wait_time = time.time() - snapshot.last_update_time
            queue_ratio = self.queue_tracker.get_queue_ratio(order_id)

            if wait_time > self.max_queue_wait_seconds and queue_ratio > self.max_queue_ratio:
                return CancelDecision(
                    order_id=order_id,
                    should_cancel=True,
                    reason=CancelReason.QUEUE_TIMEOUT,
                    detail=f"Queue timeout {wait_time:.1f}s, ratio {queue_ratio:.2f}"
                )

        # 4. 毒流警报
        if adverse_alert:
            return CancelDecision(
                order_id=order_id,
                should_cancel=True,
                reason=CancelReason.ADVERSE_SELECTION,
                detail="Adverse selection alert triggered"
            )

        # 5. 价格偏离
        if order.side.value == "BUY" and current_best_bid is not None:
            if order.price and (current_best_bid - order.price) > self.price_drift_ticks * self.tick_size:
                return CancelDecision(
                    order_id=order_id,
                    should_cancel=True,
                    reason=CancelReason.PRICE_DRIFT,
                    detail=f"Bid drifted away from order price"
                )
        if order.side.value == "SELL" and current_best_ask is not None:
            if order.price and (order.price - current_best_ask) > self.price_drift_ticks * self.tick_size:
                return CancelDecision(
                    order_id=order_id,
                    should_cancel=True,
                    reason=CancelReason.PRICE_DRIFT,
                    detail=f"Ask drifted away from order price"
                )

        return CancelDecision(
            order_id=order_id,
            should_cancel=False,
            reason=CancelReason.SIGNAL_REVERSED,  # dummy
            detail="No cancel condition met"
        )
```

---

### 3.3 RepriceEngine（重挂定价引擎）

创建文件 `core/reprice_engine.py`：

```python
from typing import Tuple, Optional
from core.execution_models import Order, OrderBook, OrderSide, OrderType

class RepriceEngine:
    """
    对撤单后的剩余未成交数量，智能定价并生成新订单。
    """

    def __init__(
        self,
        tick_size: float = 0.01,
        max_reprice_attempts: int = 3
    ):
        self.tick_size = tick_size
        self.max_reprice_attempts = max_reprice_attempts

    def reprice(
        self,
        original_order: Order,
        book: OrderBook,
        signal_strength: float,
        attempt: int = 1
    ) -> Tuple[Optional[float], str]:
        """
        返回：(新价格, 策略描述)
        """
        remaining = original_order.size - original_order.filled_size
        if remaining <= 1e-9:
            return None, "nothing_to_reprice"

        side = original_order.side
        urgency = abs(signal_strength)

        bb = book.best_bid()
        ba = book.best_ask()
        if not bb or not ba:
            return None, "no_book"

        # 策略1：信号强 → 更激进（买 higher，卖 lower）
        if urgency > 0.8:
            if side == OrderSide.BUY:
                new_price = ba
            else:
                new_price = bb
            return new_price, "aggressive_immediate"

        # 策略2：排队太深或重挂次数多 → 轻微改善
        if attempt >= self.max_reprice_attempts // 2:
            if side == OrderSide.BUY:
                new_price = bb + self.tick_size
            else:
                new_price = ba - self.tick_size
            return new_price, "improved_limit"

        # 策略3：默认挂回 best 价
        if side == OrderSide.BUY:
            new_price = bb
        else:
            new_price = ba
        return new_price, "best_price_passive"
```

---

### 3.4 Cancel + Reprice 执行器

创建文件 `core/order_lifecycle_manager.py`：

```python
import uuid
from typing import Optional
from core.execution_models import Order, OrderStatus, OrderSide, OrderType
from core.order_state_machine import OrderStateMachine
from core.queue_tracker import QueueTracker
from core.cancel_manager import CancelManager
from core.reprice_engine import RepriceEngine
from core.binance_rest_client import BinanceRESTClient

class OrderLifecycleManager:
    """
    统一封装 Cancel / Reprice 的完整流程。
    """

    def __init__(
        self,
        rest_client: BinanceRESTClient,
        order_fsm: OrderStateMachine,
        queue_tracker: QueueTracker,
        cancel_manager: CancelManager,
        reprice_engine: RepriceEngine
    ):
        self.rest_client = rest_client
        self.order_fsm = order_fsm
        self.queue_tracker = queue_tracker
        self.cancel_manager = cancel_manager
        self.reprice_engine = reprice_engine

    def check_and_cancel(
        self,
        order: Order,
        current_signal: Optional[dict],
        current_regime: str,
        order_regime: str,
        adverse_alert: bool,
        current_best_bid: Optional[float],
        current_best_ask: Optional[float]
    ) -> bool:
        """
        检查并执行撤单。返回 True 表示已发起撤单。
        """
        decision = self.cancel_manager.evaluate(
            order=order,
            current_signal=current_signal,
            current_regime=current_regime,
            order_regime=order_regime,
            adverse_alert=adverse_alert,
            current_best_bid=current_best_bid,
            current_best_ask=current_best_ask
        )

        if decision.should_cancel:
            print(f"[Cancel] {order.id}: {decision.reason.value} | {decision.detail}")
            res = self.rest_client.cancel_order(order.symbol, order.id)
            # OSM 会在收到 executionReport 时自动更新为 CANCELED
            return True
        return False

    def reprice_order(
        self,
        original_order: Order,
        book,
        signal_strength: float,
        attempt: int = 1
    ) -> Optional[Order]:
        """
        对撤单订单生成新订单。返回 None 表示无需重挂。
        """
        new_price, strategy = self.reprice_engine.reprice(
            original_order, book, signal_strength, attempt
        )
        if new_price is None:
            return None

        remaining = original_order.size - original_order.filled_size
        new_order = Order(
            id=f"repr_{uuid.uuid4().hex[:12]}",
            symbol=original_order.symbol,
            side=original_order.side,
            order_type=OrderType.LIMIT,
            size=remaining,
            price=new_price
        )
        print(f"[Reprice] {original_order.id} -> {new_order.id} @ {new_price} ({strategy})")
        return new_order
```

---

## 四、与 SelfEvolvingTrader 集成

### 4.1 初始化

修改 `self_evolving_trader.py`：

```python
class SelfEvolvingTrader:
    def __init__(self, config: TraderConfig):
        # ... existing code ...
        self.queue_tracker = QueueTracker()
        self.cancel_manager = CancelManager(
            queue_tracker=self.queue_tracker,
            max_queue_wait_seconds=10.0,
            max_queue_ratio=0.8,
            price_drift_ticks=2,
            tick_size=0.01
        )
        self.reprice_engine = RepriceEngine(tick_size=0.01)
        self.lifecycle_manager = OrderLifecycleManager(
            rest_client=self.rest_client,
            order_fsm=self.order_fsm,
            queue_tracker=self.queue_tracker,
            cancel_manager=self.cancel_manager,
            reprice_engine=self.reprice_engine
        )
```

### 4.2 交易周期中的 Cancel / Reprice

在 `_trading_cycle()` 中，**下单之前**，先检查已有活跃订单：

```python
async def _trading_cycle(self):
    signal = await self._generate_signal()
    current_regime = self.regime_detector.current_regime if self.regime_detector else "unknown"

    # 1. Cancel / Reprice 已有订单
    open_orders = self.order_fsm.get_open_orders()
    for order in open_orders:
        best_bid = self.ws_client.book.best_bid() if self.ws_client and self.ws_client.book else None
        best_ask = self.ws_client.book.best_ask() if self.ws_client and self.ws_client.book else None

        cancelled = self.lifecycle_manager.check_and_cancel(
            order=order,
            current_signal=signal,
            current_regime=current_regime,
            order_regime=getattr(order, "regime", current_regime),
            adverse_alert=False,  # TODO: 从毒流检测器接入
            current_best_bid=best_bid,
            current_best_ask=best_ask
        )

        if cancelled and self.ws_client and self.ws_client.book:
            new_order = self.lifecycle_manager.reprice_order(
                original_order=order,
                book=self.ws_client.book,
                signal_strength=signal["confidence"]
            )
            if new_order:
                # 注册并发单
                self.order_fsm.register_order(new_order)
                self.queue_tracker.register(new_order, self.ws_client.book)
                res = self.rest_client.place_order(
                    symbol=new_order.symbol,
                    side=new_order.side.value,
                    quantity=new_order.size,
                    price=new_order.price,
                    order_type="LIMIT"
                )

    # 2. 如果已经没有同方向订单，再考虑下新单
    # ... (原有下单逻辑)
```

### 4.3 WebSocket 事件绑定

在 `initialize()` 中把 QueueTracker 绑定到数据流：

```python
# Book updates
async def on_book_update(book: OrderBook):
    self.queue_tracker.update_on_book(book)

# Trade updates (已通过 BinanceWSClient.on_trade_callback)
def on_trade_callback(trade_payload):
    self.fill_model.update_market_flow(float(trade_payload.get("q", 0)), 0)
    self.queue_tracker.update_on_trade(trade_payload)
```

---

## 五、生产 Checklist

| # | 检查项 | 状态 |
|---|--------|------|
| 1 | Cancel 接口响应时间 < 200ms | ☐ |
| 2 | 被撤订单在 OSM 中正确流转到 CANCELED 状态 | ☐ |
| 3 | Reprice 次数有限制，防止无限撤挂循环 | ☐ |
| 4 | 部分成交订单重挂时，quantity 减去已成交部分 | ☐ |
| 5 | Binance `RATELIMIT` 未因频繁 cancel 触发 | ☐ |
| 6 | QueueTracker 的 `current_position` 不会变成负数 | ☐ |
| 7 | 高波动期间 Cancel 策略已降级测试 | ☐ |

---

## 六、已知问题和下一步

1. **QueueTracker 是概率估算**：无法看到 Level 3 的精确队列，极端情况下位置估算会偏。
2. **Reprice 的 attempt 追踪需持久化**：当前简化为局部变量，建议将 `reprice_count` 挂载到订单对象上。
3. **下一步**：接入 Execution RL (SAC)，让 reprice / cancel / aggression 的决策由模型自动学习。

---

*文档版本: v1.0*
*适用项目: binance/new Self-Evolving Trader*
*创建日期: 2026-04-02*
