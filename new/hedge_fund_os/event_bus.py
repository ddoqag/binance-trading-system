"""
Hedge Fund OS - Event Bus (事件总线)

组件间通信的基础设施，支持发布-订阅模式
用于解耦各组件间的直接依赖
"""

import time
import logging
import threading
from typing import Dict, List, Callable, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from queue import Queue, Empty


logger = logging.getLogger(__name__)


class EventPriority(Enum):
    """事件优先级"""
    CRITICAL = 0    # 紧急事件（如停机信号）
    HIGH = 1        # 高优先级（如风险告警）
    NORMAL = 2      # 普通事件
    LOW = 3         # 低优先级（如日志）


class EventType(Enum):
    """系统事件类型"""
    # 系统级事件
    SYSTEM_START = auto()
    SYSTEM_STOP = auto()
    SYSTEM_MODE_CHANGE = auto()
    EMERGENCY_SHUTDOWN = auto()

    # 市场数据事件
    MARKET_DATA_UPDATE = auto()
    REGIME_CHANGE = auto()

    # 决策事件
    DECISION_MADE = auto()
    STRATEGY_SELECTED = auto()

    # 资金分配事件
    ALLOCATION_UPDATED = auto()
    REBALANCE_TRIGGERED = auto()

    # 风险事件
    RISK_CHECK_PASSED = auto()
    RISK_CHECK_FAILED = auto()
    DRAWDOWN_THRESHOLD_HIT = auto()

    # 执行事件
    ORDER_SUBMITTED = auto()
    ORDER_FILLED = auto()
    ORDER_REJECTED = auto()

    # 进化事件
    STRATEGY_BORN = auto()
    STRATEGY_PROMOTED = auto()
    STRATEGY_DEMOTED = auto()
    STRATEGY_KILLED = auto()
    EVOLUTION_CYCLE_COMPLETE = auto()


@dataclass
class Event:
    """事件对象"""
    event_type: EventType
    data: Any = None
    timestamp: datetime = field(default_factory=datetime.now)
    priority: EventPriority = EventPriority.NORMAL
    source: str = "unknown"
    event_id: str = field(default_factory=lambda: str(time.time_ns()))


@dataclass
class EventBusConfig:
    """事件总线配置"""
    max_queue_size: int = 10000
    worker_threads: int = 2
    drop_on_overflow: bool = True  # 队列满时丢弃低优先级事件
    enable_async: bool = True


class EventBus:
    """
    Hedge Fund OS 事件总线

    职责：
    1. 组件间解耦通信
    2. 事件优先级管理
    3. 异步事件处理
    4. 事件持久化（可选）

    使用示例：
        bus = EventBus()

        # 订阅事件
        bus.subscribe(EventType.DECISION_MADE, on_decision)

        # 发布事件
        bus.publish(EventType.DECISION_MADE, data={'strategy': 'trend'})
    """

    def __init__(self, config: Optional[EventBusConfig] = None):
        self.config = config or EventBusConfig()

        # 订阅者字典: event_type -> [(handler, priority_filter), ...]
        self._subscribers: Dict[EventType, List[tuple]] = {
            event_type: [] for event_type in EventType
        }

        # 异步处理队列
        self._queue: Queue = Queue(maxsize=self.config.max_queue_size)

        # 运行状态
        self._running = False
        self._workers: List[threading.Thread] = []

        # 统计
        self._published_count = 0
        self._dropped_count = 0
        self._processed_count = 0

        # 锁
        self._lock = threading.RLock()

        # 全局处理器（接收所有事件）
        self._global_handlers: List[Callable[[Event], None]] = []

    def subscribe(
        self,
        event_type: EventType,
        handler: Callable[[Event], None],
        min_priority: EventPriority = EventPriority.LOW
    ) -> None:
        """
        订阅特定类型的事件

        Args:
            event_type: 事件类型
            handler: 处理函数 (event) -> None
            min_priority: 最低处理优先级（低于此优先级的事件不处理）
        """
        with self._lock:
            self._subscribers[event_type].append((handler, min_priority))
            logger.debug(f"Handler subscribed to {event_type.name}")

    def unsubscribe(
        self,
        event_type: EventType,
        handler: Callable[[Event], None]
    ) -> bool:
        """取消订阅"""
        with self._lock:
            subscribers = self._subscribers[event_type]
            for i, (h, _) in enumerate(subscribers):
                if h == handler:
                    subscribers.pop(i)
                    logger.debug(f"Handler unsubscribed from {event_type.name}")
                    return True
            return False

    def subscribe_all(self, handler: Callable[[Event], None]) -> None:
        """订阅所有事件（全局处理器）"""
        with self._lock:
            self._global_handlers.append(handler)

    def publish(
        self,
        event_type: EventType,
        data: Any = None,
        priority: EventPriority = EventPriority.NORMAL,
        source: str = "unknown"
    ) -> bool:
        """
        发布事件

        Args:
            event_type: 事件类型
            data: 事件数据
            priority: 事件优先级
            source: 事件来源

        Returns:
            是否成功发布
        """
        event = Event(
            event_type=event_type,
            data=data,
            priority=priority,
            source=source
        )

        # 同步处理高优先级事件
        if priority == EventPriority.CRITICAL:
            self._process_event(event)
            return True

        # 异步处理其他事件
        if self.config.enable_async and self._running:
            try:
                self._queue.put_nowait(event)
                self._published_count += 1
                return True
            except:
                # 队列满，根据配置决定是否丢弃
                if self.config.drop_on_overflow and priority == EventPriority.LOW:
                    self._dropped_count += 1
                    return False
                # 否则同步处理
                self._process_event(event)
                return True
        else:
            # 同步模式
            self._process_event(event)
            self._published_count += 1
            return True

    def _process_event(self, event: Event) -> None:
        """处理单个事件"""
        # 调用全局处理器
        for handler in self._global_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Global handler error for {event.event_type.name}: {e}")

        # 调用特定类型处理器
        with self._lock:
            handlers = list(self._subscribers[event.event_type])

        for handler, min_priority in handlers:
            # 检查优先级
            if event.priority.value > min_priority.value:
                continue

            try:
                handler(event)
            except Exception as e:
                logger.error(f"Handler error for {event.event_type.name}: {e}")

        self._processed_count += 1

    def _worker_loop(self) -> None:
        """工作线程循环"""
        while self._running:
            try:
                event = self._queue.get(timeout=0.1)
                self._process_event(event)
                self._queue.task_done()
            except Empty:
                continue
            except Exception as e:
                logger.error(f"Worker loop error: {e}")

    def start(self) -> None:
        """启动事件总线"""
        if self._running:
            return

        self._running = True

        if self.config.enable_async:
            for i in range(self.config.worker_threads):
                worker = threading.Thread(
                    target=self._worker_loop,
                    name=f"EventBus-Worker-{i}",
                    daemon=True
                )
                worker.start()
                self._workers.append(worker)

        logger.info(f"EventBus started (async={self.config.enable_async})")

    def stop(self) -> None:
        """停止事件总线"""
        self._running = False

        # 等待队列处理完成
        if self.config.enable_async:
            self._queue.join()

        # 等待工作线程结束
        for worker in self._workers:
            worker.join(timeout=1.0)

        self._workers.clear()
        logger.info("EventBus stopped")

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            'published': self._published_count,
            'processed': self._processed_count,
            'dropped': self._dropped_count,
            'queue_size': self._queue.qsize(),
            'subscriber_count': sum(
                len(subs) for subs in self._subscribers.values()
            ),
        }

    def clear(self) -> None:
        """清空所有订阅和队列"""
        with self._lock:
            for event_type in self._subscribers:
                self._subscribers[event_type].clear()
            self._global_handlers.clear()

        # 清空队列
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except:
                break


class EventBusAware:
    """
    事件总线感知基类

    组件可以继承此类以获得便捷的事件发布/订阅能力
    """

    def __init__(self, event_bus: Optional[EventBus] = None):
        self._event_bus = event_bus
        self._subscribed_handlers: List[tuple] = []

    def set_event_bus(self, event_bus: EventBus) -> None:
        """设置事件总线"""
        self._event_bus = event_bus

    def publish_event(
        self,
        event_type: EventType,
        data: Any = None,
        priority: EventPriority = EventPriority.NORMAL
    ) -> bool:
        """发布事件"""
        if self._event_bus:
            return self._event_bus.publish(
                event_type, data, priority, source=self.__class__.__name__
            )
        return False

    def subscribe_to(
        self,
        event_type: EventType,
        handler: Callable[[Event], None],
        min_priority: EventPriority = EventPriority.LOW
    ) -> None:
        """订阅事件"""
        if self._event_bus:
            self._event_bus.subscribe(event_type, handler, min_priority)
            self._subscribed_handlers.append((event_type, handler))

    def unsubscribe_all(self) -> None:
        """取消所有订阅"""
        if self._event_bus:
            for event_type, handler in self._subscribed_handlers:
                self._event_bus.unsubscribe(event_type, handler)
        self._subscribed_handlers.clear()


# 便捷函数
def create_event_bus(
    max_queue_size: int = 10000,
    worker_threads: int = 2,
    enable_async: bool = True
) -> EventBus:
    """创建事件总线"""
    config = EventBusConfig(
        max_queue_size=max_queue_size,
        worker_threads=worker_threads,
        enable_async=enable_async
    )
    return EventBus(config)
