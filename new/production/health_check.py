"""
系统健康检查模块
检查系统各组件状态
"""

import asyncio
import time
import logging
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import psutil
import os

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """健康状态"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    """组件健康状态"""
    name: str
    status: HealthStatus
    message: str
    last_check: float
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SystemHealth:
    """系统整体健康状态"""
    timestamp: float
    overall_status: HealthStatus
    components: List[ComponentHealth]
    system_metrics: Dict[str, Any]


class HealthChecker:
    """
    系统健康检查器

    检查项目:
    - 内存使用
    - CPU使用
    - 磁盘空间
    - 网络连接
    - 数据库连接
    - API响应
    """

    def __init__(self, check_interval: float = 30.0):
        self.check_interval = check_interval
        self.components: Dict[str, Callable] = {}
        self.last_results: Dict[str, ComponentHealth] = {}
        self._running = False
        self._check_task: Optional[asyncio.Task] = None

        # 阈值配置
        self.thresholds = {
            'memory_max': 85.0,      # 内存使用阈值 (%)
            'cpu_max': 80.0,         # CPU使用阈值 (%)
            'disk_max': 90.0,        # 磁盘使用阈值 (%)
            'latency_max': 1000.0,   # 最大延迟 (ms)
        }

        logger.info("[HealthChecker] Initialized")

    def register_component(self, name: str, check_func: Callable):
        """注册组件检查函数"""
        self.components[name] = check_func
        logger.info(f"[HealthChecker] Registered component: {name}")

    async def start(self):
        """启动健康检查循环"""
        if self._running:
            return

        self._running = True
        self._check_task = asyncio.create_task(self._check_loop())
        logger.info("[HealthChecker] Started")

    async def stop(self):
        """停止健康检查"""
        self._running = False
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
        logger.info("[HealthChecker] Stopped")

    async def _check_loop(self):
        """健康检查循环"""
        while self._running:
            try:
                await self.run_checks()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"[HealthChecker] Check loop error: {e}")
                await asyncio.sleep(self.check_interval)

    async def run_checks(self) -> SystemHealth:
        """运行所有健康检查"""
        components = []

        # 系统资源检查
        components.append(self._check_memory())
        components.append(self._check_cpu())
        components.append(self._check_disk())

        # 注册组件检查
        for name, check_func in self.components.items():
            try:
                if asyncio.iscoroutinefunction(check_func):
                    result = await check_func()
                else:
                    result = check_func()

                if isinstance(result, ComponentHealth):
                    components.append(result)
                else:
                    components.append(ComponentHealth(
                        name=name,
                        status=HealthStatus.HEALTHY if result else HealthStatus.UNHEALTHY,
                        message="OK" if result else "Check failed",
                        last_check=time.time()
                    ))
            except Exception as e:
                components.append(ComponentHealth(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    message=str(e),
                    last_check=time.time()
                ))

        # 确定整体状态
        unhealthy_count = sum(1 for c in components if c.status == HealthStatus.UNHEALTHY)
        degraded_count = sum(1 for c in components if c.status == HealthStatus.DEGRADED)

        if unhealthy_count > 0:
            overall = HealthStatus.UNHEALTHY
        elif degraded_count > 0:
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY

        # 系统指标
        system_metrics = {
            'memory_percent': psutil.virtual_memory().percent,
            'cpu_percent': psutil.cpu_percent(),
            'disk_percent': psutil.disk_usage('/').percent,
            'process_memory_mb': psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
        }

        health = SystemHealth(
            timestamp=time.time(),
            overall_status=overall,
            components=components,
            system_metrics=system_metrics
        )

        # 保存结果
        for comp in components:
            self.last_results[comp.name] = comp

        # 记录不健康状态
        if overall != HealthStatus.HEALTHY:
            logger.warning(f"[HealthChecker] System health: {overall.value}")
            for comp in components:
                if comp.status != HealthStatus.HEALTHY:
                    logger.warning(f"  - {comp.name}: {comp.message}")

        return health

    def _check_memory(self) -> ComponentHealth:
        """检查内存使用"""
        memory = psutil.virtual_memory()
        status = HealthStatus.HEALTHY
        message = f"Memory usage: {memory.percent:.1f}%"

        if memory.percent > self.thresholds['memory_max']:
            status = HealthStatus.UNHEALTHY
            message = f"Memory usage critical: {memory.percent:.1f}%"
        elif memory.percent > self.thresholds['memory_max'] * 0.8:
            status = HealthStatus.DEGRADED
            message = f"Memory usage high: {memory.percent:.1f}%"

        return ComponentHealth(
            name="memory",
            status=status,
            message=message,
            last_check=time.time(),
            details={'percent': memory.percent, 'available_mb': memory.available / 1024 / 1024}
        )

    def _check_cpu(self) -> ComponentHealth:
        """检查CPU使用"""
        cpu_percent = psutil.cpu_percent(interval=0.1)
        status = HealthStatus.HEALTHY
        message = f"CPU usage: {cpu_percent:.1f}%"

        if cpu_percent > self.thresholds['cpu_max']:
            status = HealthStatus.DEGRADED
            message = f"CPU usage high: {cpu_percent:.1f}%"

        return ComponentHealth(
            name="cpu",
            status=status,
            message=message,
            last_check=time.time(),
            details={'percent': cpu_percent}
        )

    def _check_disk(self) -> ComponentHealth:
        """检查磁盘空间"""
        disk = psutil.disk_usage('/')
        percent = disk.percent
        status = HealthStatus.HEALTHY
        message = f"Disk usage: {percent:.1f}%"

        if percent > self.thresholds['disk_max']:
            status = HealthStatus.UNHEALTHY
            message = f"Disk usage critical: {percent:.1f}%"
        elif percent > self.thresholds['disk_max'] * 0.8:
            status = HealthStatus.DEGRADED
            message = f"Disk usage high: {percent:.1f}%"

        return ComponentHealth(
            name="disk",
            status=status,
            message=message,
            last_check=time.time(),
            details={'percent': percent, 'free_gb': disk.free / 1024 / 1024 / 1024}
        )

    def get_health_report(self) -> Dict[str, Any]:
        """获取健康报告"""
        return {
            'timestamp': datetime.now().isoformat(),
            'components': {
                name: {
                    'status': comp.status.value,
                    'message': comp.message,
                    'last_check': comp.last_check
                }
                for name, comp in self.last_results.items()
            }
        }

    def is_healthy(self) -> bool:
        """检查系统是否健康"""
        if not self.last_results:
            return False
        return all(
            comp.status == HealthStatus.HEALTHY
            for comp in self.last_results.values()
        )
