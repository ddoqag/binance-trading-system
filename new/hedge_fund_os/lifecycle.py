"""
Hedge Fund OS - Component Lifecycle Management (组件生命周期管理)

管理所有组件的初始化、启动、停止、健康检查
"""

import time
import logging
from typing import Dict, List, Optional, Callable, Any, Protocol
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from abc import ABC, abstractmethod


logger = logging.getLogger(__name__)


class ComponentState(Enum):
    """组件状态"""
    CREATED = auto()       # 已创建
    INITIALIZING = auto()  # 初始化中
    READY = auto()         # 就绪
    STARTING = auto()      # 启动中
    RUNNING = auto()       # 运行中
    PAUSED = auto()        # 暂停
    STOPPING = auto()      # 停止中
    STOPPED = auto()       # 已停止
    ERROR = auto()         # 错误状态


class ComponentHealth(Enum):
    """组件健康状态"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthStatus:
    """健康状态详情"""
    status: ComponentHealth = ComponentHealth.UNKNOWN
    message: str = ""
    last_check: datetime = field(default_factory=datetime.now)
    latency_ms: float = 0.0
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ComponentInfo:
    """组件信息"""
    name: str
    state: ComponentState = ComponentState.CREATED
    health: HealthStatus = field(default_factory=HealthStatus)
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    error_count: int = 0
    last_error: Optional[str] = None


class LifecycleComponent(ABC):
    """
    生命周期组件接口

    所有需要生命周期管理的组件都应实现此接口
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """组件名称"""
        pass

    @abstractmethod
    def initialize(self) -> bool:
        """
        初始化组件

        Returns:
            初始化是否成功
        """
        pass

    @abstractmethod
    def start(self) -> bool:
        """
        启动组件

        Returns:
            启动是否成功
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """停止组件"""
        pass

    @abstractmethod
    def health_check(self) -> HealthStatus:
        """
        健康检查

        Returns:
            健康状态
        """
        pass

    def pause(self) -> bool:
        """暂停组件（可选）"""
        return False

    def resume(self) -> bool:
        """恢复组件（可选）"""
        return False


class LifecycleManager:
    """
    生命周期管理器

    管理所有组件的生命周期，包括：
    - 依赖顺序管理
    - 批量启动/停止
    - 健康监控
    - 故障恢复
    """

    def __init__(self):
        self._components: Dict[str, LifecycleComponent] = {}
        self._info: Dict[str, ComponentInfo] = {}
        self._dependencies: Dict[str, List[str]] = {}  # component -> [dependencies]

        # 状态变更回调
        self._state_callbacks: List[Callable[[str, ComponentState, ComponentState], None]] = []

        # 健康检查配置
        self._health_check_interval = 30.0  # 30秒
        self._last_health_check: Dict[str, float] = {}

    def register(
        self,
        component: LifecycleComponent,
        dependencies: Optional[List[str]] = None
    ) -> None:
        """
        注册组件

        Args:
            component: 组件实例
            dependencies: 依赖的组件名称列表
        """
        name = component.name

        if name in self._components:
            logger.warning(f"Component {name} already registered, replacing")

        self._components[name] = component
        self._info[name] = ComponentInfo(name=name)
        self._dependencies[name] = dependencies or []

        logger.info(f"Component registered: {name}")

    def unregister(self, name: str) -> bool:
        """注销组件"""
        if name not in self._components:
            return False

        # 先停止组件
        self.stop_component(name)

        del self._components[name]
        del self._info[name]
        del self._dependencies[name]

        logger.info(f"Component unregistered: {name}")
        return True

    def initialize_all(self, timeout_seconds: float = 30.0) -> Dict[str, bool]:
        """
        按依赖顺序初始化所有组件

        Args:
            timeout_seconds: 超时时间

        Returns:
            各组件初始化结果
        """
        results = {}
        ordered = self._get_init_order()

        logger.info(f"Initializing {len(ordered)} components in order: {ordered}")

        for name in ordered:
            component = self._components[name]
            info = self._info[name]

            try:
                info.state = ComponentState.INITIALIZING
                self._emit_state_change(name, ComponentState.CREATED, ComponentState.INITIALIZING)

                start_time = time.time()
                success = component.initialize()
                elapsed = time.time() - start_time

                if success:
                    info.state = ComponentState.READY
                    self._emit_state_change(name, ComponentState.INITIALIZING, ComponentState.READY)
                    logger.info(f"Component {name} initialized in {elapsed:.2f}s")
                else:
                    info.state = ComponentState.ERROR
                    info.error_count += 1
                    info.last_error = "Initialize returned False"
                    self._emit_state_change(name, ComponentState.INITIALIZING, ComponentState.ERROR)
                    logger.error(f"Component {name} initialization failed")

                results[name] = success

            except Exception as e:
                info.state = ComponentState.ERROR
                info.error_count += 1
                info.last_error = str(e)
                self._emit_state_change(name, ComponentState.INITIALIZING, ComponentState.ERROR)
                logger.exception(f"Component {name} initialization error: {e}")
                results[name] = False

        return results

    def start_all(self, timeout_seconds: float = 30.0) -> Dict[str, bool]:
        """
        按依赖顺序启动所有组件

        Args:
            timeout_seconds: 超时时间

        Returns:
            各组件启动结果
        """
        results = {}
        ordered = self._get_init_order()

        logger.info(f"Starting {len(ordered)} components")

        for name in ordered:
            component = self._components[name]
            info = self._info[name]

            # 检查依赖是否已启动
            deps_ready = all(
                self._info[dep].state == ComponentState.RUNNING
                for dep in self._dependencies[name]
            )
            if not deps_ready:
                logger.error(f"Component {name} dependencies not ready")
                results[name] = False
                continue

            try:
                info.state = ComponentState.STARTING
                self._emit_state_change(name, ComponentState.READY, ComponentState.STARTING)

                start_time = time.time()
                success = component.start()
                elapsed = time.time() - start_time

                if success:
                    info.state = ComponentState.RUNNING
                    info.started_at = datetime.now()
                    self._emit_state_change(name, ComponentState.STARTING, ComponentState.RUNNING)
                    logger.info(f"Component {name} started in {elapsed:.2f}s")
                else:
                    info.state = ComponentState.ERROR
                    info.error_count += 1
                    info.last_error = "Start returned False"
                    self._emit_state_change(name, ComponentState.STARTING, ComponentState.ERROR)
                    logger.error(f"Component {name} start failed")

                results[name] = success

            except Exception as e:
                info.state = ComponentState.ERROR
                info.error_count += 1
                info.last_error = str(e)
                self._emit_state_change(name, ComponentState.STARTING, ComponentState.ERROR)
                logger.exception(f"Component {name} start error: {e}")
                results[name] = False

        return results

    def stop_all(self, timeout_seconds: float = 30.0) -> None:
        """
        按依赖逆序停止所有组件
        """
        ordered = self._get_init_order()
        reverse_order = reversed(ordered)

        logger.info(f"Stopping {len(ordered)} components")

        for name in reverse_order:
            self.stop_component(name)

    def stop_component(self, name: str) -> None:
        """停止单个组件"""
        if name not in self._components:
            return

        component = self._components[name]
        info = self._info[name]

        if info.state in (ComponentState.STOPPED, ComponentState.CREATED):
            return

        try:
            info.state = ComponentState.STOPPING
            self._emit_state_change(name, ComponentState.RUNNING, ComponentState.STOPPING)

            component.stop()

            info.state = ComponentState.STOPPED
            info.stopped_at = datetime.now()
            self._emit_state_change(name, ComponentState.STOPPING, ComponentState.STOPPED)
            logger.info(f"Component {name} stopped")

        except Exception as e:
            info.state = ComponentState.ERROR
            info.error_count += 1
            info.last_error = str(e)
            self._emit_state_change(name, ComponentState.STOPPING, ComponentState.ERROR)
            logger.exception(f"Component {name} stop error: {e}")

    def check_health(self, force: bool = False) -> Dict[str, HealthStatus]:
        """
        检查所有组件健康状态

        Args:
            force: 强制检查（忽略间隔）

        Returns:
            各组件健康状态
        """
        now = time.time()
        results = {}

        for name, component in self._components.items():
            # 检查间隔
            last_check = self._last_health_check.get(name, 0)
            if not force and now - last_check < self._health_check_interval:
                results[name] = self._info[name].health
                continue

            try:
                start_time = time.time()
                health = component.health_check()
                health.latency_ms = (time.time() - start_time) * 1000

                self._info[name].health = health
                self._last_health_check[name] = now
                results[name] = health

                if health.status != ComponentHealth.HEALTHY:
                    logger.warning(
                        f"Component {name} health check: {health.status.value} - {health.message}"
                    )

            except Exception as e:
                health = HealthStatus(
                    status=ComponentHealth.UNHEALTHY,
                    message=f"Health check error: {e}"
                )
                self._info[name].health = health
                self._info[name].error_count += 1
                results[name] = health
                logger.exception(f"Component {name} health check error: {e}")

        return results

    def get_overall_health(self) -> ComponentHealth:
        """获取整体健康状态"""
        healths = self.check_health()

        if any(h.status == ComponentHealth.UNHEALTHY for h in healths.values()):
            return ComponentHealth.UNHEALTHY
        if any(h.status == ComponentHealth.DEGRADED for h in healths.values()):
            return ComponentHealth.DEGRADED
        if all(h.status == ComponentHealth.HEALTHY for h in healths.values()):
            return ComponentHealth.HEALTHY
        return ComponentHealth.UNKNOWN

    def _get_init_order(self) -> List[str]:
        """
        获取按依赖排序的组件初始化顺序

        使用拓扑排序算法
        """
        # 构建依赖图
        in_degree = {name: 0 for name in self._components}
        graph = {name: [] for name in self._components}

        for name, deps in self._dependencies.items():
            for dep in deps:
                if dep in self._components:
                    graph[dep].append(name)
                    in_degree[name] += 1

        # 拓扑排序
        queue = [name for name, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            name = queue.pop(0)
            result.append(name)

            for dependent in graph[name]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        # 检查是否有循环依赖
        if len(result) != len(self._components):
            remaining = set(self._components.keys()) - set(result)
            logger.error(f"Circular dependency detected for components: {remaining}")
            # 添加剩余组件（顺序不确定）
            result.extend(remaining)

        return result

    def _emit_state_change(
        self,
        name: str,
        old_state: ComponentState,
        new_state: ComponentState
    ) -> None:
        """触发状态变更回调"""
        for callback in self._state_callbacks:
            try:
                callback(name, old_state, new_state)
            except Exception as e:
                logger.error(f"State change callback error: {e}")

    def register_state_callback(
        self,
        callback: Callable[[str, ComponentState, ComponentState], None]
    ) -> None:
        """注册状态变更回调"""
        self._state_callbacks.append(callback)

    def get_component_info(self, name: str) -> Optional[ComponentInfo]:
        """获取组件信息"""
        return self._info.get(name)

    def get_all_info(self) -> Dict[str, ComponentInfo]:
        """获取所有组件信息"""
        return dict(self._info)

    def get_running_components(self) -> List[str]:
        """获取运行中的组件列表"""
        return [
            name for name, info in self._info.items()
            if info.state == ComponentState.RUNNING
        ]

    def get_component_count(self) -> int:
        """获取组件总数"""
        return len(self._components)

    def is_all_healthy(self) -> bool:
        """检查所有组件是否健康"""
        return self.get_overall_health() == ComponentHealth.HEALTHY


# 便捷函数
def create_lifecycle_manager() -> LifecycleManager:
    """创建生命周期管理器"""
    return LifecycleManager()
