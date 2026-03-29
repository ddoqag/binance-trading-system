#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
插件基类 - Plugin Base Classes
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
import logging

try:
    from plugins.versioning import (
        get_version_manager,
        CompatibilityStatus
    )
    VERSIONING_AVAILABLE = True
except ImportError:
    VERSIONING_AVAILABLE = False


class PluginType(Enum):
    """插件类型"""
    DATA_SOURCE = "data_source"      # 数据源插件
    FACTOR = "factor"                # 因子插件
    STRATEGY = "strategy"            # 策略插件
    EXECUTION = "execution"          # 执行插件
    RISK = "risk"                    # 风险管理插件
    UTILITY = "utility"              # 工具插件


@dataclass
class PluginHealthStatus:
    """插件健康状态"""
    healthy: bool = True
    message: str = "OK"
    last_check: Optional[float] = None
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PluginMetadata:
    """插件元数据"""
    name: str
    version: str
    type: PluginType
    interface_version: str = "1.0.0"  # 插件接口版本
    description: str = ""
    author: str = ""
    dependencies: Dict[str, str] = field(default_factory=dict)
    config_schema: Dict[str, Any] = field(default_factory=dict)


class PluginBase(ABC):
    """插件基类 - 所有插件的基础类"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化插件

        Args:
            config: 插件配置
        """
        self.config = config or {}
        self.logger = logging.getLogger(f'Plugin.{self.__class__.__name__}')
        self._metadata = self._get_metadata()
        self._initialized = False
        self._running = False
        self._event_bus = None

    def _get_metadata(self) -> PluginMetadata:
        """获取插件元数据（子类应覆盖此方法）"""
        return PluginMetadata(
            name=self.__class__.__name__,
            version="0.1.0",
            type=PluginType.UTILITY,
            interface_version="1.0.0",
            description="Base plugin"
        )

    def check_compatibility(self) -> Optional[Dict[str, Any]]:
        """
        检查插件与系统的兼容性

        Returns:
            兼容性检查结果，如果版本管理不可用则返回 None
        """
        if not VERSIONING_AVAILABLE:
            return None

        version_manager = get_version_manager()
        result = version_manager.check_compatibility(
            plugin_name=self.metadata.name,
            plugin_interface_version=self.metadata.interface_version
        )

        return {
            "status": result.status.value,
            "message": result.message,
            "breaking_changes": result.breaking_changes,
            "deprecation_warnings": result.deprecation_warnings,
            "suggestions": result.suggestions,
            "is_compatible": result.status in [
                CompatibilityStatus.FULLY_COMPATIBLE,
                CompatibilityStatus.BACKWARD_COMPATIBLE
            ]
        }

    @property
    def metadata(self) -> PluginMetadata:
        """获取插件元数据"""
        return self._metadata

    @property
    def is_initialized(self) -> bool:
        """插件是否已初始化"""
        return self._initialized

    @property
    def is_running(self) -> bool:
        """插件是否正在运行"""
        return self._running

    def set_event_bus(self, event_bus):
        """设置事件总线"""
        self._event_bus = event_bus

    # ===== 生命周期钩子 =====

    def pre_initialize(self):
        """预初始化钩子 - 在 initialize 之前调用"""
        # 检查版本兼容性
        compatibility = self.check_compatibility()
        if compatibility:
            if not compatibility['is_compatible']:
                raise RuntimeError(
                    f"Plugin {self.metadata.name} v{self.metadata.version} is incompatible with "
                    f"the current system interface. {compatibility['message']}"
                )
            elif compatibility['status'] == 'backward_compatible':
                self.logger.warning(
                    f"Plugin {self.metadata.name} v{self.metadata.version} uses an older interface. "
                    f"{compatibility['message']}"
                )
                for warning in compatibility['deprecation_warnings']:
                    self.logger.warning(f"  - {warning}")
            else:
                self.logger.debug(
                    f"Plugin {self.metadata.name} v{self.metadata.version} is compatible "
                    f"with interface v{self.metadata.interface_version}"
                )

    @abstractmethod
    def initialize(self):
        """
        初始化插件

        子类必须实现此方法来执行实际的初始化逻辑
        """
        pass

    def post_initialize(self):
        """后初始化钩子 - 在 initialize 之后调用"""
        pass

    def pre_start(self):
        """预启动钩子 - 在 start 之前调用"""
        pass

    @abstractmethod
    def start(self):
        """
        启动插件

        子类必须实现此方法来执行实际的启动逻辑
        """
        pass

    def post_start(self):
        """后启动钩子 - 在 start 之后调用"""
        pass

    def pre_stop(self):
        """预停止钩子 - 在 stop 之前调用"""
        pass

    @abstractmethod
    def stop(self):
        """
        停止插件

        子类必须实现此方法来执行实际的停止逻辑
        """
        pass

    def post_stop(self):
        """后停止钩子 - 在 stop 之后调用"""
        pass

    def cleanup(self):
        """清理资源"""
        pass

    # ===== 健康检查 =====

    def health_check(self) -> PluginHealthStatus:
        """
        健康检查

        Returns:
            插件健康状态
        """
        return PluginHealthStatus(healthy=True, message="OK")

    # ===== 便捷方法 =====

    def emit_event(self, event_type: str, data: Dict[str, Any]):
        """发送事件"""
        if self._event_bus:
            self._event_bus.emit(event_type, data, source=self.metadata.name)

    def subscribe_event(self, event_type: str, handler):
        """订阅事件"""
        if self._event_bus:
            self._event_bus.subscribe(event_type, handler)

    # ===== 完整生命周期执行 =====

    def full_initialize(self):
        """执行完整的初始化流程"""
        self.logger.info(f"Initializing plugin: {self.metadata.name} v{self.metadata.version}")
        try:
            self.pre_initialize()
            self.initialize()
            self.post_initialize()
            self._initialized = True
            self.logger.info(f"Plugin initialized: {self.metadata.name}")
        except Exception as e:
            self.logger.error(f"Failed to initialize plugin {self.metadata.name}: {e}")
            raise

    def full_start(self):
        """执行完整的启动流程"""
        if not self._initialized:
            self.full_initialize()

        self.logger.info(f"Starting plugin: {self.metadata.name}")
        try:
            self.pre_start()
            self.start()
            self.post_start()
            self._running = True
            self.logger.info(f"Plugin started: {self.metadata.name}")
        except Exception as e:
            self.logger.error(f"Failed to start plugin {self.metadata.name}: {e}")
            raise

    def full_stop(self):
        """执行完整的停止流程"""
        if not self._running:
            return

        self.logger.info(f"Stopping plugin: {self.metadata.name}")
        try:
            self.pre_stop()
            self.stop()
            self.post_stop()
            self._running = False
            self.logger.info(f"Plugin stopped: {self.metadata.name}")
        except Exception as e:
            self.logger.error(f"Failed to stop plugin {self.metadata.name}: {e}")
            raise

    def full_shutdown(self):
        """执行完整的关闭流程"""
        self.full_stop()
        self.cleanup()
        self._initialized = False
        self.logger.info(f"Plugin shutdown complete: {self.metadata.name}")
