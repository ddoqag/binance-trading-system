#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可靠事件总线实现 - Reliable Event Bus
包含序列号、重试机制、死信队列等可靠性增强功能
"""

import uuid
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import time
from enum import Enum

from plugins.event_bus import Event, EventHandler, EventBus


class RetryPolicyType(Enum):
    """重试策略类型"""
    LINEAR = "linear"
    EXPONENTIAL = "exponential"


@dataclass
class RetryPolicy:
    """重试策略配置"""
    max_attempts: int = 5
    backoff_type: RetryPolicyType = RetryPolicyType.EXPONENTIAL
    initial_delay: float = 1.0  # 秒
    max_delay: float = 30.0  # 秒

    def calculate_delay(self, attempt: int) -> float:
        """计算第n次重试的延迟"""
        if attempt >= self.max_attempts:
            return 0.0

        if self.backoff_type == RetryPolicyType.LINEAR:
            delay = self.initial_delay * attempt
        else:  # 指数退避
            delay = self.initial_delay * (2 ** (attempt - 1))

        return min(delay, self.max_delay)


@dataclass
class DeadLetterEvent:
    """死信事件数据类"""
    original_event: Event
    error: str
    error_traceback: str
    retry_count: int = 0
    enqueued_at: datetime = field(default_factory=datetime.utcnow)
    last_retry_at: Optional[datetime] = None


class DeadLetterQueue:
    """死信队列管理"""

    def __init__(self, max_retries: int = 5, storage_path: str = "data/dlq"):
        """初始化死信队列"""
        self.max_retries = max_retries
        self.storage_path = storage_path
        self.dlq_events: Dict[str, DeadLetterEvent] = {}
        self.logger = logging.getLogger('DeadLetterQueue')

    def enqueue(self, event: Event, error: Exception, traceback_str: str):
        """将失败事件放入死信队列"""
        dlq_event = DeadLetterEvent(
            original_event=event,
            error=str(error),
            error_traceback=traceback_str,
        )
        self.dlq_events[event.id] = dlq_event
        self.logger.warning(f"Event {event.id} added to DLQ: {error}")

    def retry(self, event_id: str) -> bool:
        """重试处理死信事件"""
        if event_id not in self.dlq_events:
            return False

        dlq_event = self.dlq_events[event_id]

        if dlq_event.retry_count >= self.max_retries:
            self.logger.error(f"Event {event_id} exceeded max retries ({self.max_retries})")
            return False

        dlq_event.retry_count += 1
        dlq_event.last_retry_at = datetime.utcnow()
        self.logger.info(f"Retrying event {event_id} (attempt {dlq_event.retry_count})")

        return True

    def get_event(self, event_id: str) -> Optional[DeadLetterEvent]:
        """获取死信事件"""
        return self.dlq_events.get(event_id)

    def get_all_events(self) -> List[DeadLetterEvent]:
        """获取所有死信事件"""
        return list(self.dlq_events.values())

    def remove(self, event_id: str):
        """从死信队列中移除事件"""
        if event_id in self.dlq_events:
            del self.dlq_events[event_id]
            self.logger.info(f"Event {event_id} removed from DLQ")


class SequenceManager:
    """事件序列号管理"""

    def __init__(self):
        """初始化序列号管理器"""
        self._seq_num = 0

    def next_seq(self) -> int:
        """获取下一个序列号"""
        self._seq_num += 1
        return self._seq_num


@dataclass
class Subscription:
    """事件订阅配置"""
    topic: str
    handler: Callable
    ack_mode: str = "auto"  # auto | manual
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    last_ack_seq: int = -1


class ReliableEventBus(EventBus):
    """可靠事件总线 - 增强的事件总线实现"""

    def __init__(self, name: str = "main", max_queue_size: int = 10000):
        """初始化可靠事件总线"""
        super().__init__(name, max_queue_size)
        self.sequence_manager = SequenceManager()
        self.dlq = DeadLetterQueue()
        self._acknowledged_events: Dict[str, int] = {}
        self._pending_events: Dict[str, Event] = {}
        self._subscriptions: Dict[str, List[Subscription]] = {}

    def publish(self, event: Event) -> str:
        """发布事件，分配序列号和ID"""
        if not self._running:
            raise RuntimeError("Event bus is not running")

        event.seq_num = self.sequence_manager.next_seq()
        event.id = str(uuid.uuid4())
        event.timestamp = time.time()

        try:
            self._event_queue.put_nowait(event)
            self._pending_events[event.id] = event
            self.logger.debug(
                f"Event published: {event.event_type} "
                f"from {event.source} (seq: {event.seq_num}, id: {event.id})"
            )
            return event.id
        except Exception as e:
            self.logger.error(f"Failed to publish event {event.event_type}: {e}")
            raise

    def subscribe(self, event_type: str, handler: Callable,
                  source_filter: Optional[str] = None,
                  retry_policy: Optional[RetryPolicy] = None) -> Subscription:
        """订阅事件，支持确认模式和重试策略"""
        if retry_policy is None:
            retry_policy = RetryPolicy()

        subscription = Subscription(
            topic=event_type,
            handler=EventHandler(handler, source_filter),
            retry_policy=retry_policy
        )

        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []

            self._subscribers[event_type].append(subscription)

            self.logger.debug(
                f"Subscribed to event: {event_type} "
                f"with source filter: {source_filter}"
            )

        return subscription

    def acknowledge(self, event_id: str, seq_num: int):
        """确认事件处理成功"""
        if event_id in self._pending_events:
            del self._pending_events[event_id]

        self._acknowledged_events[event_id] = seq_num
        self.logger.debug(f"Event acknowledged: {event_id}")

    def _dispatch_event(self, event: Event):
        """分发事件，支持重试和死信队列"""
        dispatch_success = False

        try:
            # 分发到特定事件类型的订阅者
            if event.event_type in self._subscribers:
                self._dispatch_to_subscribers(event.event_type, event)

            # 分发到通配符订阅者
            if "*" in self._subscribers:
                self._dispatch_to_subscribers("*", event)

            dispatch_success = True

            if event.ack_required:
                self.acknowledge(event.id, event.seq_num)

        except Exception as e:
            self.logger.error(f"Event dispatch failed: {e}")

            # 处理失败逻辑
            import traceback

            self.dlq.enqueue(event, e, traceback.format_exc())

            if event.delivery_attempts >= 5:
                self.acknowledge(event.id, event.seq_num)
                self.logger.error(f"Event {event.id} exceeded max delivery attempts")

        self.logger.debug(
            f"Event dispatched: {event.event_type} "
            f"from {event.source} (seq: {event.seq_num})"
        )

    def _dispatch_to_subscribers(self, event_type: str, event: Event):
        """向特定事件类型的订阅者分发事件"""
        with self._lock:
            for sub in list(self._subscribers[event_type]):
                try:
                    self._handle_single_subscriber(event, sub)
                except Exception as e:
                    self.logger.error(
                        f"Handler error for event {event.event_type}: {e}"
                    )

    def _handle_single_subscriber(self, event: Event, subscription: Subscription):
        """处理单个订阅者"""
        attempt = 0
        last_error = None

        while attempt < subscription.retry_policy.max_attempts:
            try:
                subscription.handler.handle_event(event)
                return
            except Exception as e:
                last_error = e
                attempt += 1

                if attempt < subscription.retry_policy.max_attempts:
                    delay = subscription.retry_policy.calculate_delay(attempt)
                    time.sleep(delay)
                else:
                    import traceback
                    self.dlq.enqueue(event, e, traceback.format_exc())

        raise last_error

    def get_acknowledged_events(self) -> List[Dict[str, Any]]:
        """获取已确认的事件列表"""
        return [
            {"id": event_id, "seq_num": seq_num}
            for event_id, seq_num in self._acknowledged_events.items()
        ]

    def get_pending_events(self) -> List[Dict[str, Any]]:
        """获取待处理的事件列表"""
        return [
            {
                "id": event.id,
                "seq_num": event.seq_num,
                "event_type": event.event_type,
                "source": event.source,
                "timestamp": event.timestamp
            }
            for event in self._pending_events.values()
        ]

    def get_dlq_events(self) -> List[Dict[str, Any]]:
        """获取死信队列中的事件列表"""
        return [
            {
                "id": event.original_event.id,
                "seq_num": event.original_event.seq_num,
                "event_type": event.original_event.event_type,
                "source": event.original_event.source,
                "error": event.error,
                "retry_count": event.retry_count,
                "enqueued_at": event.enqueued_at
            }
            for event in self.dlq.get_all_events()
        ]

    def process_dlq_events(self):
        """处理死信队列中的事件"""
        for event_id in list(self.dlq.dlq_events.keys()):
            if self.dlq.retry(event_id):
                dlq_event = self.dlq.dlq_events[event_id]
                try:
                    self._event_queue.put_nowait(dlq_event.original_event)
                    del self.dlq.dlq_events[event_id]
                    self.logger.info(f"Event {event_id} requeued from DLQ")
                except Exception as e:
                    self.logger.error(f"Failed to requeue event {event_id}: {e}")
            else:
                self.logger.warning(f"Event {event_id} not eligible for retry")
