#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
事件总线 - Event Bus
"""

from typing import Dict, Callable, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import logging
import threading
from queue import Queue, Empty
import time


@dataclass
class Event:
    """事件数据类"""
    event_type: str
    data: Dict[str, Any]
    source: str
    timestamp: float
    seq_num: int = 0
    correlation_id: Optional[str] = None


class EventHandler:
    """事件处理器基类"""

    def __init__(self, handler: Callable, source_filter: Optional[str] = None):
        """
        初始化事件处理器

        Args:
            handler: 事件处理函数
            source_filter: 源过滤器（只处理来自特定源的事件）
        """
        self.handler = handler
        self.source_filter = source_filter

    def handle_event(self, event: Event):
        """
        处理事件

        Args:
            event: 事件对象
        """
        try:
            if self.source_filter is None or event.source == self.source_filter:
                self.handler(event)
        except Exception as e:
            logging.error(f"Failed to handle event {event.event_type}: {e}")


class EventBus:
    """事件总线 - 实现模块间通信"""

    def __init__(self, name: str = "main", max_queue_size: int = 10000):
        """
        初始化事件总线

        Args:
            name: 事件总线名称
            max_queue_size: 最大队列大小
        """
        self.name = name
        self.logger = logging.getLogger(f'EventBus.{name}')
        self._subscribers: Dict[str, List[EventHandler]] = {}
        self._event_queue = Queue(maxsize=max_queue_size)
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._seq_num = 0
        self._lock = threading.RLock()

    @property
    def is_running(self) -> bool:
        """事件总线是否正在运行"""
        return self._running

    def start(self):
        """启动事件总线"""
        if self._running:
            return

        self._running = True
        self._worker_thread = threading.Thread(
            target=self._event_worker,
            name=f"EventBusWorker-{self.name}"
        )
        self._worker_thread.daemon = True
        self._worker_thread.start()
        self.logger.info(f"Event bus started: {self.name}")

    def stop(self):
        """停止事件总线"""
        if not self._running:
            return

        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5.0)
            self._worker_thread = None
        self.logger.info(f"Event bus stopped: {self.name}")

    def emit(self, event_type: str, data: Dict[str, Any],
             source: str = "unknown", correlation_id: Optional[str] = None) -> int:
        """
        发送事件

        Args:
            event_type: 事件类型
            data: 事件数据
            source: 事件源
            correlation_id: 关联ID

        Returns:
            事件序列号
        """
        if not self._running:
            raise RuntimeError("Event bus is not running")

        self._seq_num += 1
        event = Event(
            event_type=event_type,
            data=data,
            source=source,
            timestamp=time.time(),
            seq_num=self._seq_num,
            correlation_id=correlation_id
        )

        try:
            self._event_queue.put_nowait(event)
            self.logger.debug(
                f"Event emitted: {event_type} "
                f"from {source} (seq: {self._seq_num})"
            )
            return self._seq_num
        except Exception as e:
            self.logger.error(f"Failed to emit event {event_type}: {e}")
            raise

    def subscribe(self, event_type: str, handler: Callable,
                  source_filter: Optional[str] = None):
        """
        订阅事件

        Args:
            event_type: 事件类型
            handler: 事件处理函数
            source_filter: 源过滤器（只处理来自特定源的事件）
        """
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []

            # 检查是否已存在相同的处理器
            for existing_handler in self._subscribers[event_type]:
                if (existing_handler.handler == handler and
                        existing_handler.source_filter == source_filter):
                    return

            self._subscribers[event_type].append(
                EventHandler(handler, source_filter)
            )

            self.logger.debug(
                f"Subscribed to event: {event_type} "
                f"with source filter: {source_filter}"
            )

    def unsubscribe(self, event_type: str, handler: Callable,
                    source_filter: Optional[str] = None):
        """
        取消订阅事件

        Args:
            event_type: 事件类型
            handler: 事件处理函数
            source_filter: 源过滤器
        """
        with self._lock:
            if event_type not in self._subscribers:
                return

            self._subscribers[event_type] = [
                h for h in self._subscribers[event_type]
                if not (h.handler == handler and h.source_filter == source_filter)
            ]

            self.logger.debug(
                f"Unsubscribed from event: {event_type} "
                f"with source filter: {source_filter}"
            )

    def _event_worker(self):
        """事件处理工作线程"""
        while self._running:
            try:
                event = self._event_queue.get(timeout=1.0)
                self._dispatch_event(event)
                self._event_queue.task_done()
            except Empty:
                continue
            except Exception as e:
                self.logger.error(f"Event worker error: {e}")

    def _dispatch_event(self, event: Event):
        """
        分发事件

        Args:
            event: 事件对象
        """
        # 分发到特定事件类型的订阅者
        if event.event_type in self._subscribers:
            self._dispatch_to_subscribers(event.event_type, event)

        # 分发到通配符订阅者
        if "*" in self._subscribers:
            self._dispatch_to_subscribers("*", event)

        self.logger.debug(
            f"Event dispatched: {event.event_type} "
            f"from {event.source} (seq: {event.seq_num})"
        )

    def _dispatch_to_subscribers(self, event_type: str, event: Event):
        """
        向特定事件类型的订阅者分发事件

        Args:
            event_type: 事件类型
            event: 事件对象
        """
        with self._lock:
            for handler in list(self._subscribers[event_type]):
                try:
                    handler.handle_event(event)
                except Exception as e:
                    self.logger.error(
                        f"Handler error for event {event.event_type}: {e}"
                    )

    def get_subscriber_count(self, event_type: Optional[str] = None) -> int:
        """
        获取订阅者数量

        Args:
            event_type: 事件类型，None 表示全部

        Returns:
            订阅者数量
        """
        with self._lock:
            if event_type is None:
                return sum(len(subscribers) for subscribers in self._subscribers.values())
            return len(self._subscribers.get(event_type, []))

    def get_queue_size(self) -> int:
        """获取队列大小"""
        return self._event_queue.qsize()

    def get_stats(self) -> Dict[str, Any]:
        """获取事件总线统计信息"""
        with self._lock:
            event_type_counts = {}
            for event_type, handlers in self._subscribers.items():
                event_type_counts[event_type] = len(handlers)

        return {
            "name": self.name,
            "running": self._running,
            "total_events": self._seq_num,
            "queue_size": self.get_queue_size(),
            "subscribers": self.get_subscriber_count(),
            "subscribers_per_type": event_type_counts
        }
