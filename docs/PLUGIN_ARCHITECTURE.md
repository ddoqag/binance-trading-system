# 插件化量化交易系统架构设计

## 一、架构概述

本文档描述了一个**生产级、插件化、事件驱动**的币安量化交易系统架构。基于用户的专业反馈，将从"可用"升级到"生产级"。

### 核心设计原则

1. **插件化架构** - 所有业务模块都是可插拔的
2. **事件驱动通信** - 模块间通过事件总线松耦合
3. **高可靠性** - 具备重试、死信队列、确认机制
4. **完整可观测性** - 结构化日志、分布式追踪、业务指标
5. **强安全性** - 插件签名、资源限制、加密配置

---

## 二、完整架构图

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                        配置与部署层 (Configuration)                     │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐    │
│  │ YAML 主配置    │  │ 环境变量覆盖    │  │ Vault 密钥管理 │    │
│  │ + Pydantic校验 │  │ + 多环境        │  │ (敏感配置)      │    │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘    │
│           │                     │                     │             │
│           └─────────────────────┼─────────────────────┘             │
│                                 │                                   │
└─────────────────────────────────┼───────────────────────────────────┘
                                  │
┌─────────────────────────────────┼───────────────────────────────────┐
│                        监控与告警层 (Monitoring)                      │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐    │
│  │ 结构化日志      │  │ OpenTelemetry   │  │ 多渠道告警      │    │
│  │ (JSON格式)      │  │ 分布式追踪      │  │ (邮件/钉钉)     │    │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘    │
│           │                     │                     │             │
│           └─────────────────────┼─────────────────────┘             │
└─────────────────────────────────┼───────────────────────────────────┘
                                  │
┌─────────────────────────────────┼───────────────────────────────────┐
│                      插件系统与事件总线 (Core)                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                  插件管理器 (Plugin Manager)                    │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │  │
│  │  │ 自动发现     │  │ 依赖解析     │  │ 版本管理     │    │  │
│  │  │ (目录扫描)   │  │ (DAG拓扑)    │  │ (兼容性检查) │    │  │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘    │  │
│  └─────────┼───────────────────┼───────────────────┼────────────┘  │
│            │                   │                   │               │
│  ┌─────────▼───────────────────▼───────────────────▼────────────┐  │
│  │                事件总线 (Event Bus)                          │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │  │
│  │  │ 消息路由     │  │ 重试机制     │  │ 死信队列     │    │  │
│  │  │ (Redis/Rabbit)│  │ (指数退避)   │  │ (DLQ)        │    │  │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘    │  │
│  └─────────┼───────────────────┼───────────────────┼────────────┘  │
│            │                   │                   │               │
│  ┌─────────▼───────────────────▼───────────────────▼────────────┐  │
│  │              插件沙箱与隔离层 (Sandbox)                        │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │  │
│  │  │ 资源限制     │  │ 健康检查     │  │ 生命周期钩子 │    │  │
│  │  │ (CPU/内存)   │  │ (health)     │  │ (pre_start)   │    │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘    │  │
│  └────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────┼───────────────────────────────────┘
                                  │
┌─────────────────────────────────┼───────────────────────────────────┐
│                        核心服务层 (Services)                        │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐    │
│  │ 数据服务 (Node) │  │ 策略引擎 (Python)│  │ 风险控制 (Python)│    │
│  │ - Binance API   │  │ - 策略插件      │  │ - 风控插件      │    │
│  │ - WebSocket     │  │ - 因子插件      │  │ - 熔断机制      │    │
│  │ - TimescaleDB   │  │ - 回测引擎      │  │ - Kill Switch   │    │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘    │
│           │                     │                     │             │
│  ┌────────▼────────┐  ┌────────▼────────┐  ┌────────▼────────┐    │
│  │ 执行引擎 (Python)│  │ 回测系统 (Python)│  │ 因子库 (Python)  │    │
│  │ - 订单管理      │  │ - 事件驱动回测  │  │ - 30+ Alpha因子 │    │
│  │ - 实盘/模拟盘   │  │ - 性能指标计算  │  │ - 因子评估      │    │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘    │
└───────────┼─────────────────────┼─────────────────────┼─────────────┘
            │                     │                     │
┌───────────▼─────────────────────▼─────────────────────▼─────────────┐
│                      数据存储层 (Data Storage)                        │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐    │
│  │ TimescaleDB     │  │ MongoDB         │  │ Redis           │    │
│  │ - 时序数据(K线) │  │ - 订单日志      │  │ - 缓存/队列     │    │
│  │ - 因子数据      │  │ - 系统日志      │  │ - 会话状态      │    │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 三、事件总线可靠性设计

### 3.1 核心架构

```python
# event_bus/reliable_bus.py

class ReliableEventBus:
    """
    可靠事件总线实现
    特性：
    - 事件序列号/时间戳
    - 重试机制（指数退避）
    - 死信队列（DLQ）
    - 持久化与确认机制
    """

    def __init__(self, config: BusConfig):
        self.queue_manager = QueueManager(config.redis_url)
        self.dlq_manager = DeadLetterQueue(config.dlq_config)
        self.retry_engine = RetryEngine(config.retry_config)
        self.sequence_manager = SequenceManager()

    def publish(self, event: Event) -> str:
        """
        发布事件，返回事件ID
        """
        # 分配序列号
        event.seq_num = self.sequence_manager.next_seq()
        event.timestamp = datetime.utcnow()
        event.id = str(uuid.uuid4())

        # 持久化到队列
        self.queue_manager.persist(event)

        return event.id

    def subscribe(self, topic: str, handler: Callable) -> Subscription:
        """
        订阅事件，支持自动确认和重试
        """
        subscription = Subscription(
            topic=topic,
            handler=handler,
            ack_mode="auto",  # auto | manual
            retry_policy=RetryPolicy(
                max_attempts=5,
                backoff="exponential",  # linear | exponential
                initial_delay=1.0,
                max_delay=30.0
            )
        )

        return self.queue_manager.subscribe(subscription)
```

### 3.2 事件结构

```python
# event_bus/models.py

from pydantic import BaseModel, Field
from typing import Any, Dict, Optional
from datetime import datetime
import uuid

class Event(BaseModel):
    """
    事件数据结构
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    seq_num: int = Field(description="事件序列号，用于检测丢失或乱序")
    timestamp: datetime = Field(description="事件发生时间（UTC）")
    topic: str = Field(description="事件主题")
    type: str = Field(description="事件类型")
    source: str = Field(description="事件源（插件名称）")
    payload: Dict[str, Any] = Field(description="事件载荷")

    # 可靠性字段
    delivery_attempts: int = Field(default=0, description="投递尝试次数")
    last_attempt_time: Optional[datetime] = None
    ack_required: bool = Field(default=True, description="是否需要确认")

class EventAck(BaseModel):
    """
    事件确认结构
    """
    event_id: str
    seq_num: int
    status: str  # "success" | "failed" | "retry"
    error_message: Optional[str] = None
    processed_at: datetime
```

### 3.3 死信队列（DLQ）

```python
# event_bus/dlq.py

class DeadLetterQueue:
    """
    死信队列管理
    """

    def __init__(self, config: DLQConfig):
        self.storage = DLQStorage(config.storage_path)
        self.max_attempts = config.max_attempts
        self.retry_intervals = config.retry_intervals

    def enqueue(self, event: Event, error: Exception):
        """
        将失败事件放入死信队列
        """
        dlq_event = DLQEvent(
            original_event=event,
            error=str(error),
            error_traceback=traceback.format_exc(),
            enqueued_at=datetime.utcnow(),
            retry_count=0
        )

        self.storage.store(dlq_event)

    def retry(self, event_id: str) -> bool:
        """
        重试处理死信事件
        """
        dlq_event = self.storage.get(event_id)
        if not dlq_event:
            return False

        # 重试逻辑
        try:
            self.bus.republish(dlq_event.original_event)
            dlq_event.retry_count += 1
            self.storage.update(dlq_event)
            return True
        except Exception as e:
            logger.error(f"Retry failed: {e}")
            return False
```

---

## 四、插件系统稳定性设计

### 4.1 插件接口（含生命周期）

```python
# plugin_system/interfaces.py

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from pydantic import BaseModel

class PluginHealthStatus(BaseModel):
    """
    插件健康状态
    """
    is_healthy: bool
    status: str  # "starting" | "running" | "stopping" | "error"
    last_heartbeat: datetime
    metrics: Dict[str, Any] = {}
    error_message: Optional[str] = None

class PluginBase(ABC):
    """
    插件基类 - 包含完整生命周期和健康检查
    """

    # 插件元数据（必须由子类定义）
    name: str
    version: str
    description: str
    author: str
    dependencies: Dict[str, str] = {}  # plugin_name -> version_range

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._state = "initialized"
        self._health = PluginHealthStatus(
            is_healthy=False,
            status="initialized",
            last_heartbeat=datetime.utcnow()
        )

    # ==================== 生命周期钩子 ====================

    def pre_initialize(self) -> None:
        """
        预初始化钩子 - 在依赖注入前调用
        """
        pass

    @abstractmethod
    def initialize(self) -> None:
        """
        初始化插件 - 子类必须实现
        """
        pass

    def post_initialize(self) -> None:
        """
        后初始化钩子 - 在初始化完成后调用
        """
        pass

    def pre_start(self) -> None:
        """
        启动前钩子
        """
        pass

    @abstractmethod
    def start(self) -> None:
        """
        启动插件 - 子类必须实现
        """
        pass

    def post_start(self) -> None:
        """
        启动后钩子
        """
        self._state = "running"
        self._health.status = "running"
        self._health.is_healthy = True

    def pre_stop(self) -> None:
        """
        停止前钩子
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """
        停止插件 - 子类必须实现
        """
        pass

    def post_stop(self) -> None:
        """
        停止后钩子
        """
        self._state = "stopped"
        self._health.status = "stopped"

    def cleanup(self) -> None:
        """
        清理资源
        """
        pass

    # ==================== 健康检查 ====================

    def health_check(self) -> PluginHealthStatus:
        """
        健康检查 - 子类可以重写
        """
        self._health.last_heartbeat = datetime.utcnow()
        return self._health

    def report_error(self, error: Exception) -> None:
        """
        报告错误
        """
        self._health.is_healthy = False
        self._health.status = "error"
        self._health.error_message = str(error)

    # ==================== 版本兼容性 ====================

    @classmethod
    def is_compatible_with(cls, plugin_system_version: str) -> bool:
        """
        检查与插件系统版本的兼容性
        """
        # 简单实现：检查主版本号
        system_major = plugin_system_version.split(".")[0]
        plugin_major = cls.__plugin_system_version__.split(".")[0]
        return system_major == plugin_major

    # ==================== 状态管理 ====================

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state == "running"
```

### 4.2 插件沙箱与隔离

```python
# plugin_system/sandbox.py

import importlib.util
import sys
from typing import Dict, Any, Optional
from pathlib import Path
import threading
import resource

class PluginSandbox:
    """
    插件沙箱 - 提供资源限制和隔离
    """

    def __init__(self, config: SandboxConfig):
        self.config = config
        self._plugins: Dict[str, SandboxedPlugin] = {}
        self._resource_monitor = ResourceMonitor()

    def load_plugin(self, plugin_path: Path, plugin_name: str) -> SandboxedPlugin:
        """
        在沙箱中加载插件
        """
        # 1. 验证插件签名
        if self.config.verify_signature:
            self._verify_signature(plugin_path)

        # 2. 创建独立的模块命名空间
        module_name = f"sandboxed.{plugin_name}"
        spec = importlib.util.spec_from_file_location(module_name, plugin_path)
        module = importlib.util.module_from_spec(spec)

        # 3. 注入受限的 globals
        restricted_globals = self._create_restricted_globals()
        module.__dict__.update(restricted_globals)

        # 4. 执行模块
        spec.loader.exec_module(module)

        # 5. 创建沙箱化插件实例
        plugin = SandboxedPlugin(
            module=module,
            name=plugin_name,
            config=self.config,
            resource_limits=self._get_resource_limits(plugin_name)
        )

        self._plugins[plugin_name] = plugin
        return plugin

    def _create_restricted_globals(self) -> Dict[str, Any]:
        """
        创建受限的全局环境
        """
        # 只允许安全的模块
        allowed_modules = {
            'math': __import__('math'),
            'datetime': __import__('datetime'),
            'json': __import__('json'),
            # ... 其他安全模块
        }

        # 禁止危险操作
        restricted_builtins = {
            name: __builtins__[name]
            for name in __builtins__
            if name not in ['eval', 'exec', 'compile', '__import__', 'open']
        }

        return {
            '__builtins__': restricted_builtins,
            **allowed_modules
        }

    def _get_resource_limits(self, plugin_name: str) -> ResourceLimits:
        """
        获取插件资源限制
        """
        return ResourceLimits(
            cpu_time=self.config.default_cpu_limit,  # 秒
            memory=self.config.default_memory_limit,  # MB
            file_descriptors=self.config.default_fd_limit,
            network_access=self.config.allow_network_access
        )

class SandboxedPlugin:
    """
    沙箱化的插件实例
    """

    def __init__(self, module, name: str, config, resource_limits):
        self.module = module
        self.name = name
        self.resource_limits = resource_limits
        self._thread: Optional[threading.Thread] = None
        self._is_running = False

    def execute(self, method: str, *args, **kwargs):
        """
        在沙箱中执行插件方法
        """
        if not self._is_running:
            raise RuntimeError("Plugin not running")

        # 应用资源限制
        self._apply_resource_limits()

        # 执行方法
        try:
            func = getattr(self.module, method)
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Plugin execution error: {e}")
            raise
        finally:
            self._release_resource_limits()

    def _apply_resource_limits(self):
        """
        应用资源限制
        """
        if self.resource_limits.cpu_time:
            resource.setrlimit(resource.RLIMIT_CPU,
                             (self.resource_limits.cpu_time,
                              self.resource_limits.cpu_time))

        if self.resource_limits.memory:
            memory_bytes = self.resource_limits.memory * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
```

### 4.3 插件版本管理

```python
# plugin_system/versioning.py

from typing import Dict, List, Optional, Tuple
from semver import VersionInfo, parse

class PluginVersionManager:
    """
    插件版本管理器
    """

    def __init__(self):
        self._registry: Dict[str, List[PluginVersion]] = {}
        self._compatibility_rules: List[CompatibilityRule] = []

    def register_plugin(self, name: str, version: str,
                        plugin_class, dependencies: Dict[str, str]):
        """
        注册插件版本
        """
        semver = parse(version)

        plugin_version = PluginVersion(
            name=name,
            version=semver,
            plugin_class=plugin_class,
            dependencies=dependencies,
            registered_at=datetime.utcnow()
        )

        if name not in self._registry:
            self._registry[name] = []

        self._registry[name].append(plugin_version)
        # 按版本降序排序
        self._registry[name].sort(key=lambda x: x.version, reverse=True)

    def get_latest_compatible(self, name: str,
                             constraint: str) -> Optional[PluginVersion]:
        """
        获取符合约束的最新兼容版本
        """
        if name not in self._registry:
            return None

        for plugin_version in self._registry[name]:
            if self._version_matches(plugin_version.version, constraint):
                if self._check_dependencies(plugin_version):
                    return plugin_version

        return None

    def _version_matches(self, version: VersionInfo, constraint: str) -> bool:
        """
        检查版本是否匹配约束
        """
        # 支持的约束格式: ">=1.0.0,<2.0.0", "~1.0.0", "^1.0.0"
        # 这里简化实现
        if constraint.startswith("^"):
            # 兼容更新：主版本相同
            min_version = parse(constraint[1:])
            return (version.major == min_version.major and
                   version >= min_version)
        elif constraint.startswith("~"):
            # 补丁更新：主+次版本相同
            min_version = parse(constraint[1:])
            return (version.major == min_version.major and
                   version.minor == min_version.minor and
                   version >= min_version)
        else:
            # 简单范围
            return version >= parse(constraint)

class PluginVersion(BaseModel):
    name: str
    version: VersionInfo
    plugin_class: Any
    dependencies: Dict[str, str]  # plugin_name -> version_constraint
    registered_at: datetime
    is_deprecated: bool = False
    deprecation_message: Optional[str] = None
```

---

## 五、监控与可观测性设计

### 5.1 结构化日志

```python
# monitoring/structured_logger.py

import structlog
from typing import Dict, Any
from datetime import datetime

class StructuredLogger:
    """
    结构化日志记录器（JSON格式）
    """

    def __init__(self, service_name: str):
        self.logger = structlog.get_logger(service_name)
        self.service_name = service_name

        # 配置结构化日志
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer()
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )

    def _add_context(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        添加通用上下文
        """
        event.update({
            "service": self.service_name,
            "timestamp": datetime.utcnow().isoformat(),
            "env": os.getenv("ENVIRONMENT", "development"),
            "version": os.getenv("VERSION", "unknown")
        })
        return event

    # ==================== 插件日志 ====================

    def plugin_event(self, plugin_name: str, event_type: str,
                    details: Dict[str, Any] = None):
        """
        记录插件相关事件
        """
        event = {
            "event": "plugin",
            "plugin_name": plugin_name,
            "event_type": event_type,
            "details": details or {}
        }
        self.logger.info(**self._add_context(event))

    def plugin_metrics(self, plugin_name: str, metrics: Dict[str, float]):
        """
        记录插件指标
        """
        event = {
            "event": "plugin_metrics",
            "plugin_name": plugin_name,
            "metrics": metrics
        }
        self.logger.info(**self._add_context(event))

    # ==================== 交易日志 ====================

    def trading_signal(self, strategy: str, symbol: str,
                      signal: str, price: float, confidence: float):
        """
        记录交易信号
        """
        event = {
            "event": "trading_signal",
            "strategy": strategy,
            "symbol": symbol,
            "signal": signal,  # "BUY" | "SELL" | "HOLD"
            "price": price,
            "confidence": confidence
        }
        self.logger.info(**self._add_context(event))

    def order_executed(self, order_id: str, symbol: str, side: str,
                      qty: float, price: float, pnl: Optional[float] = None):
        """
        记录订单执行
        """
        event = {
            "event": "order_executed",
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "pnl": pnl
        }
        self.logger.info(**self._add_context(event))

    # ==================== 风险日志 ====================

    def risk_check_passed(self, check_type: str, details: Dict[str, Any]):
        """
        记录风险检查通过
        """
        event = {
            "event": "risk_check",
            "check_type": check_type,
            "result": "passed",
            "details": details
        }
        self.logger.info(**self._add_context(event))

    def risk_triggered(self, check_type: str, reason: str,
                      action_taken: str, details: Dict[str, Any]):
        """
        记录风险触发
        """
        event = {
            "event": "risk_triggered",
            "check_type": check_type,
            "reason": reason,
            "action_taken": action_taken,
            "details": details
        }
        self.logger.warning(**self._add_context(event))

    # ==================== 业务指标 ====================

    def strategy_performance(self, strategy: str, returns: float,
                           sharpe: float, max_drawdown: float,
                           win_rate: float, total_trades: int):
        """
        记录策略绩效
        """
        event = {
            "event": "strategy_performance",
            "strategy": strategy,
            "returns": returns,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_drawdown,
            "win_rate": win_rate,
            "total_trades": total_trades
        }
        self.logger.info(**self._add_context(event))

    def portfolio_metrics(self, total_value: float, cash: float,
                        position_value: float, exposure: float):
        """
        记录投资组合指标
        """
        event = {
            "event": "portfolio_metrics",
            "total_value": total_value,
            "cash": cash,
            "position_value": position_value,
            "exposure": exposure
        }
        self.logger.info(**self._add_context(event))
```

### 5.2 分布式链路追踪

```python
# monitoring/tracing.py

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from typing import Dict, Any, Optional

class DistributedTracer:
    """
    分布式链路追踪（OpenTelemetry）
    """

    def __init__(self, service_name: str, config: TracingConfig):
        self.service_name = service_name
        self.config = config

        # 初始化 OpenTelemetry
        provider = TracerProvider()

        # 配置导出器
        if config.enable_export:
            otlp_exporter = OTLPSpanExporter(
                endpoint=config.otlp_endpoint
            )
            processor = BatchSpanProcessor(otlp_exporter)
            provider.add_span_processor(processor)

        trace.set_tracer_provider(provider)
        self.tracer = trace.get_tracer(service_name)

    def trace_plugin_execution(self, plugin_name: str, method: str,
                              input_data: Dict[str, Any]):
        """
        追踪插件执行
        """
        return self.tracer.start_as_current_span(
            name=f"plugin.{plugin_name}.{method}",
            attributes={
                "plugin.name": plugin_name,
                "plugin.method": method,
                "input.size": len(str(input_data))
            }
        )

    def trace_trading_decision(self, strategy: str, symbol: str,
                              signal: str, factors: Dict[str, float]):
        """
        追踪交易决策
        """
        return self.tracer.start_as_current_span(
            name=f"trading.{strategy}.decision",
            attributes={
                "strategy": strategy,
                "symbol": symbol,
                "signal": signal,
                **{f"factor.{k}": v for k, v in factors.items()}
            }
        )

    def trace_order_flow(self, order_id: str, stages: List[str]):
        """
        追踪订单流程
        """
        spans = []
        for i, stage in enumerate(stages):
            span = self.tracer.start_span(
                name=f"order.{stage}",
                attributes={
                    "order.id": order_id,
                    "order.stage": stage,
                    "order.stage_index": i
                }
            )
            spans.append(span)

        return spans
```

### 5.3 业务指标与告警

```python
# monitoring/metrics.py

from prometheus_client import (
    Counter, Gauge, Histogram, Summary,
    start_http_server
)
from typing import Dict, Optional
import time

class TradingMetrics:
    """
    交易业务指标（Prometheus格式）
    """

    def __init__(self, config: MetricsConfig):
        self.config = config

        # ==================== 策略指标 ====================

        self.strategy_returns = Gauge(
            'trading_strategy_returns',
            '策略收益率',
            ['strategy']
        )

        self.strategy_sharpe = Gauge(
            'trading_strategy_sharpe_ratio',
            '策略夏普比率',
            ['strategy']
        )

        self.strategy_max_drawdown = Gauge(
            'trading_strategy_max_drawdown',
            '策略最大回撤',
            ['strategy']
        )

        self.strategy_win_rate = Gauge(
            'trading_strategy_win_rate',
            '策略胜率',
            ['strategy']
        )

        # ==================== 交易指标 ====================

        self.trades_total = Counter(
            'trading_trades_total',
            '总交易次数',
            ['strategy', 'symbol', 'side']
        )

        self.trading_volume = Counter(
            'trading_volume_total',
            '总交易量',
            ['strategy', 'symbol']
        )

        self.open_positions = Gauge(
            'trading_open_positions',
            '当前持仓数量',
            ['strategy', 'symbol']
        )

        self.order_latency = Histogram(
            'trading_order_latency_seconds',
            '订单执行延迟',
            ['stage']
        )

        # ==================== 风险指标 ====================

        self.portfolio_value = Gauge(
            'trading_portfolio_value',
            '投资组合总价值'
        )

        self.portfolio_exposure = Gauge(
            'trading_portfolio_exposure',
            '投资组合风险暴露'
        )

        self.risk_checks_total = Counter(
            'trading_risk_checks_total',
            '风险检查次数',
            ['check_type', 'result']
        )

        self.kill_switch_activated = Gauge(
            'trading_kill_switch_activated',
            '紧急停止开关是否激活'
        )

        # ==================== 插件指标 ====================

        self.plugin_executions = Counter(
            'plugin_executions_total',
            '插件执行次数',
            ['plugin_name', 'method', 'status']
        )

        self_plugin_execution_time = Histogram(
            'plugin_execution_duration_seconds',
            '插件执行耗时',
            ['plugin_name', 'method']
        )

        self.plugin_health = Gauge(
            'plugin_health_status',
            '插件健康状态 (1=健康, 0=不健康)',
            ['plugin_name']
        )

        if config.enable_http_server:
            start_http_server(config.http_port)

    # ==================== 指标更新方法 ====================

    def update_strategy_performance(self, strategy: str,
                                   returns: float, sharpe: float,
                                   max_drawdown: float, win_rate: float):
        """
        更新策略绩效指标
        """
        self.strategy_returns.labels(strategy).set(returns)
        self.strategy_sharpe.labels(strategy).set(sharpe)
        self.strategy_max_drawdown.labels(strategy).set(max_drawdown)
        self.strategy_win_rate.labels(strategy).set(win_rate)

    def record_trade(self, strategy: str, symbol: str,
                    side: str, qty: float, price: float):
        """
        记录交易
        """
        self.trades_total.labels(strategy, symbol, side).inc()
        self.trading_volume.labels(strategy, symbol).inc(qty * price)

    def update_portfolio(self, total_value: float, exposure: float):
        """
        更新投资组合指标
        """
        self.portfolio_value.set(total_value)
        self.portfolio_exposure.set(exposure)

    def record_risk_check(self, check_type: str, passed: bool):
        """
        记录风险检查
        """
        result = "passed" if passed else "failed"
        self.risk_checks_total.labels(check_type, result).inc()

    def set_kill_switch(self, activated: bool):
        """
        设置紧急停止开关状态
        """
        self.kill_switch_activated.set(1 if activated else 0)

    def record_plugin_execution(self, plugin_name: str, method: str,
                               status: str, duration: float):
        """
        记录插件执行
        """
        self.plugin_executions.labels(plugin_name, method, status).inc()
        self_plugin_execution_time.labels(plugin_name, method).observe(duration)

    def update_plugin_health(self, plugin_name: str, is_healthy: bool):
        """
        更新插件健康状态
        """
        self.plugin_health.labels(plugin_name).set(1 if is_healthy else 0)


# monitoring/alerts.py

class AlertManager:
    """
    多渠道告警管理
    """

    def __init__(self, config: AlertConfig):
        self.config = config
        self.channels = self._init_channels()

    def _init_channels(self) -> Dict[str, AlertChannel]:
        """
        初始化告警渠道
        """
        channels = {}

        if self.config.email_enabled:
            channels['email'] = EmailChannel(self.config.email_config)

        if self.config.dingtalk_enabled:
            channels['dingtalk'] = DingTalkChannel(self.config.dingtalk_config)

        if self.config.slack_enabled:
            channels['slack'] = SlackChannel(self.config.slack_config)

        if self.config.pagerduty_enabled:
            channels['pagerduty'] = PagerDutyChannel(self.config.pagerduty_config)

        return channels

    def send_alert(self, alert: Alert) -> List[AlertResult]:
        """
        发送告警到所有启用的渠道
        """
        results = []

        for channel_name, channel in self.channels.items():
            if alert.level in self.config.channel_levels[channel_name]:
                try:
                    result = channel.send(alert)
                    results.append(result)
                except Exception as e:
                    logger.error(f"Failed to send alert to {channel_name}: {e}")
                    results.append(AlertResult(
                        channel=channel_name,
                        success=False,
                        error=str(e)
                    ))

        return results

    def send_risk_alert(self, check_type: str, reason: str,
                       action_taken: str, severity: str = "warning"):
        """
        发送风险告警
        """
        alert = Alert(
            title=f"风险告警: {check_type}",
            message=f"风险检查触发: {reason}\\n采取行动: {action_taken}",
            level=severity,
            tags=["risk", check_type],
            metadata={
                "check_type": check_type,
                "reason": reason,
                "action_taken": action_taken
            }
        )
        return self.send_alert(alert)

    def send_performance_alert(self, strategy: str, metric: str,
                              current: float, threshold: float,
                              direction: str):
        """
        发送绩效告警
        """
        alert = Alert(
            title=f"绩效告警: {strategy} {metric}",
            message=f"策略 {strategy} 的 {metric} {direction} 阈值\\n"
                   f"当前: {current}, 阈值: {threshold}",
            level="warning" if direction == "接近" else "critical",
            tags=["performance", strategy, metric],
            metadata={
                "strategy": strategy,
                "metric": metric,
                "current": current,
                "threshold": threshold
            }
        )
        return self.send_alert(alert)

    def send_system_alert(self, component: str, error: str,
                         severity: str = "critical"):
        """
        发送系统告警
        """
        alert = Alert(
            title=f"系统告警: {component}",
            message=f"组件 {component} 发生错误: {error}",
            level=severity,
            tags=["system", component],
            metadata={"component": component, "error": error}
        )
        return self.send_alert(alert)
```

---

## 六、安全性设计

### 6.1 插件签名与白名单

```python
# security/plugin_signature.py

import hashlib
from pathlib import Path
from typing import Dict, Optional, Set
import ed25519  # 使用 Ed25519 签名算法

class PluginSignatureVerifier:
    """
    插件签名验证器
    """

    def __init__(self, config: SecurityConfig):
        self.config = config
        self.trusted_keys: Dict[str, bytes] = {}  # key_id -> public_key
        self.plugin_whitelist: Set[str] = set()
        self._load_trusted_keys()
        self._load_whitelist()

    def _load_trusted_keys(self):
        """
        加载受信任的公钥
        """
        for key_id, key_path in self.config.trusted_keys.items():
            with open(key_path, 'rb') as f:
                self.trusted_keys[key_id] = f.read()

    def _load_whitelist(self):
        """
        加载插件白名单
        """
        if self.config.whitelist_path:
            with open(self.config.whitelist_path, 'r') as f:
                for line in f:
                    plugin_hash = line.strip()
                    if plugin_hash:
                        self.plugin_whitelist.add(plugin_hash)

    def calculate_plugin_hash(self, plugin_path: Path) -> str:
        """
        计算插件文件哈希（SHA-256）
        """
        hasher = hashlib.sha256()
        with open(plugin_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hasher.update(chunk)
        return hasher.hexdigest()

    def verify_signature(self, plugin_path: Path,
                        signature_path: Path) -> VerificationResult:
        """
        验证插件签名
        """
        result = VerificationResult()

        # 1. 如果启用白名单，先检查白名单
        if self.config.enforce_whitelist:
            plugin_hash = self.calculate_plugin_hash(plugin_path)
            if plugin_hash not in self.plugin_whitelist:
                result.verified = False
                result.error = "Plugin not in whitelist"
                return result

        # 2. 读取签名文件
        try:
            with open(signature_path, 'rb') as f:
                signature_data = f.read()

            # 签名文件格式: key_id (16 bytes) + signature (64 bytes)
            key_id = signature_data[:16].hex()
            signature = signature_data[16:80]

            # 3. 检查公钥是否受信任
            if key_id not in self.trusted_keys:
                result.verified = False
                result.error = f"Unknown key ID: {key_id}"
                return result

            # 4. 验证签名
            public_key = ed25519.VerifyingKey(self.trusted_keys[key_id])
            plugin_content = plugin_path.read_bytes()
            public_key.verify(signature, plugin_content)

            result.verified = True
            result.key_id = key_id
            return result

        except Exception as e:
            result.verified = False
            result.error = str(e)
            return result


class VerificationResult(BaseModel):
    verified: bool = False
    key_id: Optional[str] = None
    error: Optional[str] = None
```

### 6.2 敏感配置加密

```python
# security/secret_manager.py

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import os
from typing import Dict, Any, Optional
import hvac  # HashiCorp Vault 客户端

class SecretManager:
    """
    敏感配置管理器
    支持：本地加密文件 + HashiCorp Vault
    """

    def __init__(self, config: SecurityConfig):
        self.config = config
        self._local_encryptor: Optional[LocalEncryptor] = None
        self._vault_client: Optional[hvac.Client] = None

        if config.use_local_encryption:
            self._local_encryptor = LocalEncryptor(config.local_key_path)

        if config.use_vault:
            self._vault_client = hvac.Client(
                url=config.vault_url,
                token=config.vault_token
            )

    def get_secret(self, key: str, default: Any = None) -> Any:
        """
        获取敏感配置
        """
        # 优先级 1: 环境变量
        if key in os.environ:
            return os.environ[key]

        # 优先级 2: Vault
        if self._vault_client:
            try:
                secret = self._vault_client.secrets.kv.read_secret_version(
                    path=key
                )
                return secret['data']['data']['value']
            except Exception:
                pass

        # 优先级 3: 本地加密文件
        if self._local_encryptor:
            try:
                return self._local_encryptor.decrypt(key)
            except Exception:
                pass

        return default

    def set_secret(self, key: str, value: Any):
        """
        设置敏感配置
        """
        if self._vault_client:
            self._vault_client.secrets.kv.create_or_update_secret(
                path=key,
                secret={'value': value}
            )

        if self._local_encryptor:
            self._local_encryptor.encrypt(key, value)


class LocalEncryptor:
    """
    本地加密器（基于 Fernet）
    """

    def __init__(self, key_path: str):
        self.key_path = key_path
        self._load_or_generate_key()
        self._secrets: Dict[str, bytes] = {}
        self._load_secrets()

    def _load_or_generate_key(self):
        """
        加载或生成加密密钥
        """
        if os.path.exists(self.key_path):
            with open(self.key_path, 'rb') as f:
                self.key = f.read()
        else:
            self.key = Fernet.generate_key()
            os.makedirs(os.path.dirname(self.key_path), exist_ok=True)
            with open(self.key_path, 'wb') as f:
                f.write(self.key)

        self.fernet = Fernet(self.key)

    def encrypt(self, key: str, value: Any):
        """
        加密并存储配置
        """
        value_str = str(value)
        encrypted = self.fernet.encrypt(value_str.encode())
        self._secrets[key] = encrypted
        self._save_secrets()

    def decrypt(self, key: str) -> Any:
        """
        解密配置
        """
        if key not in self._secrets:
            raise KeyError(f"Secret not found: {key}")

        encrypted = self._secrets[key]
        decrypted = self.fernet.decrypt(encrypted)
        return decrypted.decode()

    def _load_secrets(self):
        """
        加载加密的配置文件
        """
        secrets_path = os.path.join(
            os.path.dirname(self.key_path),
            'secrets.enc'
        )

        if os.path.exists(secrets_path):
            with open(secrets_path, 'rb') as f:
                # 简单实现：实际应该用更安全的格式
                import pickle
                self._secrets = pickle.load(f)

    def _save_secrets(self):
        """
        保存加密的配置文件
        """
        secrets_path = os.path.join(
            os.path.dirname(self.key_path),
            'secrets.enc'
        )

        import pickle
        with open(secrets_path, 'wb') as f:
            pickle.dump(self._secrets, f)
```

---

## 七、数据一致性与跨语言桥接

### 7.1 统一币安 API 入口

```python
# bridge/binance_gateway.py

"""
统一币安 API 网关
建议仅保留 Python 执行引擎调用币安 API
Node.js 数据服务通过 Python 网关获取数据
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import asyncio
import aiohttp

class BinanceGateway:
    """
    统一的币安 API 网关
    所有数据获取和交易执行都通过这里
    """

    def __init__(self, config: GatewayConfig):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self._rate_limiter = RateLimiter(config.rate_limit_config)

    async def initialize(self):
        """
        初始化会话
        """
        self.session = aiohttp.ClientSession()

    # ==================== 市场数据 API ====================

    async def get_klines(self, symbol: str, interval: str,
                        start_time: Optional[datetime] = None,
                        end_time: Optional[datetime] = None,
                        limit: int = 500) -> List[Dict]:
        """
        获取 K 线数据
        """
        await self._rate_limiter.acquire()

        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': limit
        }
        if start_time:
            params['startTime'] = int(start_time.timestamp() * 1000)
        if end_time:
            params['endTime'] = int(end_time.timestamp() * 1000)

        return await self._make_request('GET', '/api/v3/klines', params)

    async def get_ticker(self, symbol: str) -> Dict:
        """
        获取 24 小时行情
        """
        await self._rate_limiter.acquire()
        return await self._make_request(
            'GET', '/api/v3/ticker/24hr',
            {'symbol': symbol}
        )

    async def get_order_book(self, symbol: str, limit: int = 100) -> Dict:
        """
        获取订单簿
        """
        await self._rate_limiter.acquire()
        return await self._make_request(
            'GET', '/api/v3/depth',
            {'symbol': symbol, 'limit': limit}
        )

    # ==================== 交易 API ====================

    async def place_order(self, symbol: str, side: str, order_type: str,
                        qty: float, price: Optional[float] = None,
                        client_order_id: Optional[str] = None) -> Dict:
        """
        下单
        """
        await self._rate_limiter.acquire()

        params = {
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'quantity': qty
        }
        if price:
            params['price'] = price
        if client_order_id:
            params['newClientOrderId'] = client_order_id

        return await self._make_signed_request('POST', '/api/v3/order', params)

    async def cancel_order(self, symbol: str, order_id: Optional[int] = None,
                         client_order_id: Optional[str] = None) -> Dict:
        """
        取消订单
        """
        await self._rate_limiter.acquire()

        params = {'symbol': symbol}
        if order_id:
            params['orderId'] = order_id
        if client_order_id:
            params['origClientOrderId'] = client_order_id

        return await self._make_signed_request('DELETE', '/api/v3/order', params)

    async def get_open_orders(self, symbol: str) -> List[Dict]:
        """
        获取当前挂单
        """
        await self._rate_limiter.acquire()
        return await self._make_signed_request(
            'GET', '/api/v3/openOrders',
            {'symbol': symbol}
        )

    # ==================== 内部方法 ====================

    async def _make_request(self, method: str, path: str,
                           params: Dict = None) -> Any:
        """
        发送公开请求
        """
        url = self.config.base_url + path

        async with self.session.request(method, url, params=params) as resp:
            data = await resp.json()
            if resp.status != 200:
                raise BinanceAPIError(
                    status_code=resp.status,
                    error_code=data.get('code'),
                    error_message=data.get('msg')
                )
            return data

    async def _make_signed_request(self, method: str, path: str,
                                  params: Dict = None) -> Any:
        """
        发送签名请求
        """
        import hmac
        import hashlib
        import time

        params = params or {}
        params['timestamp'] = int(time.time() * 1000)

        # 构建查询字符串
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])

        # 计算签名
        signature = hmac.new(
            self.config.api_secret.encode(),
            query_string.encode(),
            hashlib.sha256
        ).hexdigest()

        params['signature'] = signature

        # 添加 API Key 到 headers
        headers = {'X-MBX-APIKEY': self.config.api_key}

        url = self.config.base_url + path

        async with self.session.request(method, url, params=params, headers=headers) as resp:
            data = await resp.json()
            if resp.status != 200:
                raise BinanceAPIError(
                    status_code=resp.status,
                    error_code=data.get('code'),
                    error_message=data.get('msg')
                )
            return data

    async def close(self):
        """
        关闭会话
        """
        if self.session:
            await self.session.close()


class BinanceAPIError(Exception):
    def __init__(self, status_code: int, error_code: int, error_message: str):
        self.status_code = status_code
        self.error_code = error_code
        self.error_message = error_message
        super().__init__(f"Binance API Error [{error_code}]: {error_message}")
```

### 7.2 数据存储层设计

```python
# data/database.py

"""
数据存储层设计
- TimescaleDB: 时序数据（K线、因子）
- MongoDB: 订单日志、系统日志
- Redis: 缓存、队列
"""

import asyncpg
from typing import List, Dict, Any, Optional
from datetime import datetime
import pandas as pd

class TimescaleDBStore:
    """
    TimescaleDB 时序数据存储
    """

    def __init__(self, config: DatabaseConfig):
        self.config = config
        self.pool: Optional[asyncpg.Pool] = None

    async def initialize(self):
        """
        初始化连接池
        """
        self.pool = await asyncpg.create_pool(
            host=self.config.host,
            port=self.config.port,
            database=self.config.database,
            user=self.config.user,
            password=self.config.password
        )

        await self._create_hypertables()

    async def _create_hypertables(self):
        """
        创建时序表（Hypertable）
        """
        async with self.pool.acquire() as conn:
            # K线表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS klines (
                    time TIMESTAMPTZ NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    open DOUBLE PRECISION,
                    high DOUBLE PRECISION,
                    low DOUBLE PRECISION,
                    close DOUBLE PRECISION,
                    volume DOUBLE PRECISION,
                    quote_volume DOUBLE PRECISION,
                    trade_count INTEGER,
                    taker_buy_base DOUBLE PRECISION,
                    taker_buy_quote DOUBLE PRECISION
                )
            """)

            # 转换为 Hypertable
            await conn.execute("""
                SELECT create_hypertable(
                    'klines', 'time',
                    if_not_exists => TRUE
                )
            """)

            # 因子数据表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS factors (
                    time TIMESTAMPTZ NOT NULL,
                    symbol TEXT NOT NULL,
                    factor_name TEXT NOT NULL,
                    value DOUBLE PRECISION,
                    metadata JSONB
                )
            """)

            await conn.execute("""
                SELECT create_hypertable(
                    'factors', 'time',
                    if_not_exists => TRUE
                )
            """)

            # 添加索引
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_klines_symbol_interval
                ON klines (symbol, interval, time DESC)
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_factors_symbol_name
                ON factors (symbol, factor_name, time DESC)
            """)

    async def insert_klines(self, symbol: str, interval: str,
                           klines: List[Dict]) -> int:
        """
        批量插入 K 线数据
        """
        async with self.pool.acquire() as conn:
            result = await conn.executemany("""
                INSERT INTO klines (
                    time, symbol, interval,
                    open, high, low, close,
                    volume, quote_volume, trade_count,
                    taker_buy_base, taker_buy_quote
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7,
                    $8, $9, $10, $11, $12
                )
                ON CONFLICT (time, symbol, interval)
                DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    quote_volume = EXCLUDED.quote_volume,
                    trade_count = EXCLUDED.trade_count,
                    taker_buy_base = EXCLUDED.taker_buy_base,
                    taker_buy_quote = EXCLUDED.taker_buy_quote
            """, [
                (
                    datetime.fromtimestamp(k['time'] / 1000),
                    symbol,
                    interval,
                    k['open'],
                    k['high'],
                    k['low'],
                    k['close'],
                    k['volume'],
                    k.get('quote_volume'),
                    k.get('trade_count'),
                    k.get('taker_buy_base'),
                    k.get('taker_buy_quote')
                )
                for k in klines
            ])
            return len(klines)

    async def get_klines(self, symbol: str, interval: str,
                        start_time: datetime,
                        end_time: datetime) -> pd.DataFrame:
        """
        获取 K 线数据并返回 DataFrame
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM klines
                WHERE symbol = $1
                  AND interval = $2
                  AND time >= $3
                  AND time <= $4
                ORDER BY time
            """, symbol, interval, start_time, end_time)

            return pd.DataFrame([dict(r) for r in rows])

    async def insert_factors(self, symbol: str, time: datetime,
                            factors: Dict[str, float]) -> int:
        """
        批量插入因子数据
        """
        async with self.pool.acquire() as conn:
            await conn.executemany("""
                INSERT INTO factors (time, symbol, factor_name, value)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (time, symbol, factor_name)
                DO UPDATE SET value = EXCLUDED.value
            """, [
                (time, symbol, name, value)
                for name, value in factors.items()
            ])
            return len(factors)


class MongoDBStore:
    """
    MongoDB 文档存储（订单日志、系统日志）
    """

    def __init__(self, config: DatabaseConfig):
        self.config = config
        self.client: Optional[pymongo.MongoClient] = None
        self.db = None

    def initialize(self):
        """
        初始化连接
        """
        import pymongo
        self.client = pymongo.MongoClient(self.config.mongodb_uri)
        self.db = self.client[self.config.mongodb_database]

        # 创建索引
        self.db.orders.create_index([
            ('symbol', 1),
            ('created_at', -1)
        ])
        self.db.orders.create_index('order_id', unique=True)

        self.db.trades.create_index([
            ('strategy', 1),
            ('timestamp', -1)
        ])

        self.db.system_logs.create_index([
            ('level', 1),
            ('timestamp', -1)
        ])

    def insert_order(self, order: Dict) -> str:
        """
        插入订单记录
        """
        result = self.db.orders.insert_one(order)
        return str(result.inserted_id)

    def insert_trade(self, trade: Dict) -> str:
        """
        插入交易记录
        """
        result = self.db.trades.insert_one(trade)
        return str(result.inserted_id)

    def get_order_history(self, symbol: str,
                         start_time: datetime,
                         end_time: datetime) -> List[Dict]:
        """
        获取订单历史
        """
        cursor = self.db.orders.find({
            'symbol': symbol,
            'created_at': {
                '$gte': start_time,
                '$lte': end_time
            }
        }).sort('created_at', -1)
        return list(cursor)
```

---

## 八、配置热更新的原子性与回滚

### 8.1 原子配置更新

```python
# config/atomic_updater.py

from typing import Dict, Any, Optional, Callable
from datetime import datetime
import copy
import yaml
from pathlib import Path

class AtomicConfigUpdater:
    """
    原子配置更新器
    实现：先校验、再切换、失败回滚
    """

    def __init__(self, config_path: Path, validator: ConfigValidator):
        self.config_path = config_path
        self.validator = validator
        self._backup_path = config_path.with_suffix('.bak')
        self._change_log_path = config_path.parent / 'config_changes.log'
        self._current_config: Optional[Dict] = None

    def update_config(self, updates: Dict[str, Any],
                     author: str,
                     reason: str) -> UpdateResult:
        """
        原子更新配置
        """
        result = UpdateResult()
        result.start_time = datetime.utcnow()
        result.author = author
        result.reason = reason

        try:
            # 1. 读取当前配置
            current_config = self._read_config()
            result.old_config = copy.deepcopy(current_config)

            # 2. 应用更新（创建副本，不修改原配置）
            new_config = self._apply_updates(current_config, updates)
            result.new_config = copy.deepcopy(new_config)

            # 3. 校验新配置
            validation_errors = self.validator.validate(new_config)
            if validation_errors:
                result.success = False
                result.error = f"Validation failed: {validation_errors}"
                return result

            # 4. 创建备份
            self._create_backup(current_config)

            # 5. 写入新配置
            self._write_config(new_config)

            # 6. 验证写入
            verify_config = self._read_config()
            if not self._configs_equal(verify_config, new_config):
                raise ConfigMismatchError("Written config doesn't match")

            # 7. 记录变更
            self._log_change(result)

            result.success = True
            result.end_time = datetime.utcnow()
            return result

        except Exception as e:
            # 失败时回滚
            result.success = False
            result.error = str(e)

            if self._backup_path.exists():
                rollback_result = self.rollback()
                result.rollback_performed = True
                result.rollback_result = rollback_result

            result.end_time = datetime.utcnow()
            return result

    def rollback(self) -> RollbackResult:
        """
        回滚到备份配置
        """
        result = RollbackResult()
        result.start_time = datetime.utcnow()

        try:
            if not self._backup_path.exists():
                raise FileNotFoundError("No backup found")

            # 读取备份
            backup_config = self._read_backup()

            # 写入备份
            self._write_config(backup_config)

            # 验证
            verify_config = self._read_config()
            if not self._configs_equal(verify_config, backup_config):
                raise ConfigMismatchError("Rollback verification failed")

            # 删除备份
            self._backup_path.unlink()

            result.success = True
            result.end_time = datetime.utcnow()
            return result

        except Exception as e:
            result.success = False
            result.error = str(e)
            result.end_time = datetime.utcnow()
            return result

    def _read_config(self) -> Dict:
        """
        读取配置文件
        """
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def _write_config(self, config: Dict):
        """
        写入配置文件
        """
        # 先写入临时文件，再重命名（原子操作）
        temp_path = self.config_path.with_suffix('.tmp')

        with open(temp_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

        # 原子重命名
        temp_path.rename(self.config_path)

    def _create_backup(self, config: Dict):
        """
        创建备份
        """
        with open(self._backup_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    def _read_backup(self) -> Dict:
        """
        读取备份
        """
        with open(self._backup_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def _apply_updates(self, config: Dict, updates: Dict) -> Dict:
        """
        应用更新（递归）
        """
        result = copy.deepcopy(config)

        for key, value in updates.items():
            if isinstance(value, dict) and key in result and isinstance(result[key], dict):
                result[key] = self._apply_updates(result[key], value)
            else:
                result[key] = value

        return result

    def _configs_equal(self, a: Dict, b: Dict) -> bool:
        """
        比较两个配置是否相同
        """
        import json
        return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def _log_change(self, result: UpdateResult):
        """
        记录配置变更
        """
        log_entry = {
            "timestamp": result.end_time.isoformat(),
            "author": result.author,
            "reason": result.reason,
            "old_config": result.old_config,
            "new_config": result.new_config,
            "duration_ms": (result.end_time - result.start_time).total_seconds() * 1000
        }

        with open(self._change_log_path, 'a', encoding='utf-8') as f:
            yaml.dump([log_entry], f, default_flow_style=False, allow_unicode=True)


class UpdateResult(BaseModel):
    success: bool = False
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    author: Optional[str] = None
    reason: Optional[str] = None
    old_config: Optional[Dict] = None
    new_config: Optional[Dict] = None
    error: Optional[str] = None
    rollback_performed: bool = False
    rollback_result: Optional['RollbackResult'] = None


class RollbackResult(BaseModel):
    success: bool = False
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error: Optional[str] = None


class ConfigMismatchError(Exception):
    pass
```

---

## 九、实施计划（更新版）

### 阶段一：最小可运行原型（MVP）

**目标**：1个数据源插件 + 1个因子插件 + 1个策略插件 + 1个执行插件 的端到端测试

**时间估计**：2-3 周

**任务清单**：
- [ ] 搭建插件系统基础框架（PluginBase、PluginManager）
- [ ] 实现基础事件总线（无可靠性增强）
- [ ] 实现配置系统基础（YAML + Pydantic）
- [ ] 开发示例数据源插件（Binance K线）
- [ ] 开发示例因子插件（简单动量因子）
- [ ] 开发示例策略插件（双均线策略）
- [ ] 开发示例执行插件（模拟执行）
- [ ] 端到端集成测试

### 阶段二：可靠性增强

**时间估计**：2-3 周

**任务清单**：
- [ ] 事件总线可靠性增强（序列号、重试、DLQ）
- [ ] 插件热插拔稳定性（沙箱、生命周期、健康检查）
- [ ] 配置热更新原子性（校验、回滚）
- [ ] 结构化日志系统
- [ ] 基础告警系统

### 阶段三：插件迁移

**时间估计**：3-4 周

**任务清单**：
- [ ] 插件兼容性验证框架
- [ ] 渐进式灰度上线机制
- [ ] 30+ Alpha 因子插件化
- [ ] 现有策略插件化
- [ ] 数据源插件开发
- [ ] 风险控制插件化

### 阶段四：强化学习重构

**时间估计**：2-3 周

**任务清单**：
- [ ] RL 智能体插件与回测环境解耦
- [ ] Docker 隔离训练/实盘环境
- [ ] DQN 智能体插件化
- [ ] PPO 智能体插件化
- [ ] RL 训练器插件化

### 阶段五：监控与安全性

**时间估计**：2-3 周

**任务清单**：
- [ ] 分布式链路追踪（OpenTelemetry）
- [ ] 业务指标监控（Prometheus）
- [ ] 多渠道告警集成
- [ ] 插件签名与白名单
- [ ] 敏感配置加密
- [ ] 插件资源限制

### 阶段六：数据层与微服务

**时间估计**：3-4 周

**任务清单**：
- [ ] TimescaleDB 时序数据存储
- [ ] MongoDB 文档存储
- [ ] Redis 缓存与队列
- [ ] Python-Node 桥接层
- [ ] 统一币安 API 网关

---

## 十、关键技术栈总结

| 层级 | 技术选型 | 说明 |
|------|---------|------|
| **编程语言** | Python 3.10+, Node.js 18+ | 核心用 Python，数据层保留 Node.js |
| **配置管理** | YAML + Pydantic + HashiCorp Vault | 主配置 YAML，校验 Pydantic，密钥 Vault |
| **事件总线** | Redis Stream / RabbitMQ | 可靠性队列、死信队列 |
| **时序数据** | TimescaleDB (PostgreSQL 扩展) | K 线、因子等时序数据 |
| **文档数据** | MongoDB | 订单日志、系统日志 |
| **缓存队列** | Redis | 缓存、会话、轻量级队列 |
| **结构化日志** | structlog + ELK Stack | JSON 格式日志，可查询 |
| **链路追踪** | OpenTelemetry + Jaeger | 分布式追踪 |
| **指标监控** | Prometheus + Grafana | 业务指标、系统指标 |
| **告警系统** | AlertManager + 多渠道 | 邮件、钉钉、Slack、PagerDuty |
| **插件隔离** | 模块沙箱 + 资源限制 | importlib、resource 模块 |
| **配置加密** | Fernet (AES) + ed25519 | 本地加密、插件签名 |
| **容器化** | Docker + Docker Compose | 开发、测试环境 |

---

## 十一、总结

本文档详细描述了一个**生产级、插件化、事件驱动**的币安量化交易系统架构，包含：

1. **事件总线可靠性** - 序列号、重试、死信队列、持久化
2. **插件系统稳定性** - 沙箱隔离、完整生命周期、健康检查、版本管理
3. **完整可观测性** - 结构化日志、分布式追踪、业务指标、多渠道告警
4. **强安全性** - 插件签名、白名单、敏感配置加密、资源限制
5. **数据一致性** - 统一 API 网关、TimescaleDB 时序存储、MongoDB 文档存储
6. **原子配置更新** - 先校验、再切换、失败回滚

实施分为 6 个阶段，从最小可运行原型开始，逐步增强可靠性、迁移现有功能、强化监控安全，最终达到生产级标准。
