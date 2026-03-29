#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
插件管理器 - Plugin Manager
"""

import os
import sys
import importlib.util
from typing import Dict, List, Optional, Any, Type
from dataclasses import dataclass
from datetime import datetime
import logging
import threading

from .base import PluginBase, PluginType, PluginMetadata
from .event_bus import EventBus


@dataclass
class PluginInstance:
    """插件实例信息"""
    plugin: PluginBase
    metadata: PluginMetadata
    instance_id: str
    loaded_at: float
    started_at: Optional[float] = None


class PluginManager:
    """插件管理器 - 负责插件的发现、加载和管理"""

    def __init__(self, event_bus: EventBus, plugin_paths: Optional[List[str]] = None):
        """
        初始化插件管理器

        Args:
            event_bus: 事件总线
            plugin_paths: 插件搜索路径列表
        """
        self.event_bus = event_bus
        self.plugin_paths = plugin_paths or []
        self.logger = logging.getLogger('PluginManager')

        # 存储已加载的插件
        self._plugins: Dict[str, PluginInstance] = {}
        # 存储插件类型索引
        self._plugins_by_type: Dict[PluginType, List[str]] = {}
        # 锁
        self._lock = threading.RLock()

        # 添加默认插件路径
        self._init_default_paths()

    def _init_default_paths(self):
        """初始化默认插件路径"""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)

        # 添加项目插件目录
        default_paths = [
            os.path.join(project_root, "plugins"),
            os.path.join(project_root, "plugin_examples"),
        ]

        for path in default_paths:
            if os.path.exists(path) and path not in self.plugin_paths:
                self.plugin_paths.append(path)

        self.logger.debug(f"Plugin paths: {self.plugin_paths}")

    def discover_plugins(self) -> List[str]:
        """
        发现可用的插件

        Returns:
            发现的插件模块名称列表
        """
        discovered = []

        for plugin_path in self.plugin_paths:
            if not os.path.exists(plugin_path):
                continue

            for filename in os.listdir(plugin_path):
                if filename.startswith('_'):
                    continue

                file_path = os.path.join(plugin_path, filename)

                # Python 模块文件
                if filename.endswith('.py') and filename != '__init__.py':
                    module_name = filename[:-3]
                    discovered.append(module_name)

                # 子目录（包含 __init__.py）
                elif (os.path.isdir(file_path) and
                      os.path.exists(os.path.join(file_path, '__init__.py'))):
                    discovered.append(filename)

        self.logger.info(f"Discovered {len(discovered)} potential plugins")
        return discovered

    def load_plugin(self, module_name: str,
                    config: Optional[Dict[str, Any]] = None) -> str:
        """
        加载插件

        Args:
            module_name: 插件模块名称
            config: 插件配置

        Returns:
            插件实例 ID
        """
        with self._lock:
            if module_name in self._plugins:
                self.logger.warning(f"Plugin already loaded: {module_name}")
                return self._plugins[module_name].instance_id

            try:
                plugin_class = self._find_plugin_class(module_name)
                if plugin_class is None:
                    raise ValueError(f"Plugin class not found in module: {module_name}")

                # 创建插件实例
                plugin = plugin_class(config)
                plugin.set_event_bus(self.event_bus)

                # 初始化插件
                plugin.full_initialize()

                # 创建插件实例信息
                instance_id = f"{module_name}_{int(datetime.now().timestamp())}"
                plugin_instance = PluginInstance(
                    plugin=plugin,
                    metadata=plugin.metadata,
                    instance_id=instance_id,
                    loaded_at=datetime.now().timestamp()
                )

                # 存储插件信息
                self._plugins[module_name] = plugin_instance

                # 更新类型索引
                plugin_type = plugin.metadata.type
                if plugin_type not in self._plugins_by_type:
                    self._plugins_by_type[plugin_type] = []
                self._plugins_by_type[plugin_type].append(module_name)

                self.logger.info(
                    f"Loaded plugin: {module_name} "
                    f"type: {plugin_type.value} "
                    f"v{plugin.metadata.version}"
                )

                # 发送插件加载事件
                self.event_bus.emit(
                    event_type="plugin.loaded",
                    data={
                        "plugin_name": module_name,
                        "plugin_type": plugin_type.value,
                        "version": plugin.metadata.version
                    },
                    source="PluginManager"
                )

                return instance_id

            except Exception as e:
                self.logger.error(f"Failed to load plugin {module_name}: {e}")
                raise

    def _find_plugin_class(self, module_name: str) -> Optional[Type[PluginBase]]:
        """
        在模块中查找插件类

        Args:
            module_name: 模块名称

        Returns:
            插件类（如果找到）
        """
        # 尝试从插件路径导入
        for plugin_path in self.plugin_paths:
            module_path = os.path.join(plugin_path, f"{module_name}.py")
            if not os.path.exists(module_path):
                module_path = os.path.join(plugin_path, module_name, "__init__.py")
                if not os.path.exists(module_path):
                    continue

            try:
                # 动态导入模块
                spec = importlib.util.spec_from_file_location(module_name, module_path)
                if spec is None or spec.loader is None:
                    continue

                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                # 查找 PluginBase 的子类
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and
                            issubclass(attr, PluginBase) and
                            attr is not PluginBase):
                        return attr

            except Exception as e:
                self.logger.warning(
                    f"Error loading module {module_name} from {module_path}: {e}"
                )
                continue

        return None

    def start_plugin(self, module_name: str):
        """
        启动插件

        Args:
            module_name: 插件模块名称
        """
        with self._lock:
            if module_name not in self._plugins:
                raise ValueError(f"Plugin not loaded: {module_name}")

            plugin_instance = self._plugins[module_name]
            if plugin_instance.plugin.is_running:
                self.logger.warning(f"Plugin already running: {module_name}")
                return

            plugin_instance.plugin.full_start()
            plugin_instance.started_at = datetime.now().timestamp()

            self.logger.info(f"Started plugin: {module_name}")

            # 发送插件启动事件
            self.event_bus.emit(
                event_type="plugin.started",
                data={
                    "plugin_name": module_name,
                    "plugin_type": plugin_instance.metadata.type.value
                },
                source="PluginManager"
            )

    def stop_plugin(self, module_name: str):
        """
        停止插件

        Args:
            module_name: 插件模块名称
        """
        with self._lock:
            if module_name not in self._plugins:
                raise ValueError(f"Plugin not loaded: {module_name}")

            plugin_instance = self._plugins[module_name]
            if not plugin_instance.plugin.is_running:
                self.logger.warning(f"Plugin not running: {module_name}")
                return

            plugin_instance.plugin.full_stop()

            self.logger.info(f"Stopped plugin: {module_name}")

            # 发送插件停止事件
            self.event_bus.emit(
                event_type="plugin.stopped",
                data={
                    "plugin_name": module_name,
                    "plugin_type": plugin_instance.metadata.type.value
                },
                source="PluginManager"
            )

    def unload_plugin(self, module_name: str):
        """
        卸载插件

        Args:
            module_name: 插件模块名称
        """
        with self._lock:
            if module_name not in self._plugins:
                raise ValueError(f"Plugin not loaded: {module_name}")

            plugin_instance = self._plugins[module_name]

            # 停止插件（如果正在运行）
            if plugin_instance.plugin.is_running:
                self.stop_plugin(module_name)

            # 关闭插件
            plugin_instance.plugin.full_shutdown()

            # 从索引中移除
            plugin_type = plugin_instance.metadata.type
            if plugin_type in self._plugins_by_type:
                self._plugins_by_type[plugin_type].remove(module_name)
                if not self._plugins_by_type[plugin_type]:
                    del self._plugins_by_type[plugin_type]

            # 从存储中移除
            del self._plugins[module_name]

            self.logger.info(f"Unloaded plugin: {module_name}")

            # 发送插件卸载事件
            self.event_bus.emit(
                event_type="plugin.unloaded",
                data={
                    "plugin_name": module_name,
                    "plugin_type": plugin_type.value
                },
                source="PluginManager"
            )

    def get_plugin(self, module_name: str) -> Optional[PluginBase]:
        """
        获取插件实例

        Args:
            module_name: 插件模块名称

        Returns:
            插件实例
        """
        with self._lock:
            plugin_instance = self._plugins.get(module_name)
            return plugin_instance.plugin if plugin_instance else None

    def get_plugins_by_type(self, plugin_type: PluginType) -> List[PluginBase]:
        """
        获取指定类型的所有插件

        Args:
            plugin_type: 插件类型

        Returns:
            插件实例列表
        """
        with self._lock:
            module_names = self._plugins_by_type.get(plugin_type, [])
            return [self._plugins[name].plugin for name in module_names]

    def get_all_plugins(self) -> Dict[str, PluginBase]:
        """
        获取所有已加载的插件

        Returns:
            插件字典 {模块名: 插件实例}
        """
        with self._lock:
            return {name: instance.plugin for name, instance in self._plugins.items()}

    def get_plugin_info(self, module_name: str) -> Optional[Dict[str, Any]]:
        """
        获取插件信息

        Args:
            module_name: 插件模块名称

        Returns:
            插件信息字典
        """
        with self._lock:
            instance = self._plugins.get(module_name)
            if instance is None:
                return None

            health_status = instance.plugin.health_check()

            return {
                "name": instance.metadata.name,
                "version": instance.metadata.version,
                "type": instance.metadata.type.value,
                "description": instance.metadata.description,
                "author": instance.metadata.author,
                "instance_id": instance.instance_id,
                "loaded_at": instance.loaded_at,
                "started_at": instance.started_at,
                "initialized": instance.plugin.is_initialized,
                "running": instance.plugin.is_running,
                "healthy": health_status.healthy,
                "health_message": health_status.message,
                "health_metrics": health_status.metrics
            }

    def get_all_plugin_info(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有插件的信息

        Returns:
            插件信息字典 {模块名: 插件信息}
        """
        with self._lock:
            return {name: self.get_plugin_info(name) for name in self._plugins}

    def start_all_plugins(self):
        """启动所有已加载的插件"""
        with self._lock:
            for module_name in self._plugins:
                try:
                    self.start_plugin(module_name)
                except Exception as e:
                    self.logger.error(f"Failed to start plugin {module_name}: {e}")

    def stop_all_plugins(self):
        """停止所有正在运行的插件"""
        with self._lock:
            for module_name in list(self._plugins.keys()):
                try:
                    if self._plugins[module_name].plugin.is_running:
                        self.stop_plugin(module_name)
                except Exception as e:
                    self.logger.error(f"Failed to stop plugin {module_name}: {e}")

    def unload_all_plugins(self):
        """卸载所有插件"""
        with self._lock:
            for module_name in list(self._plugins.keys()):
                try:
                    self.unload_plugin(module_name)
                except Exception as e:
                    self.logger.error(f"Failed to unload plugin {module_name}: {e}")

    def shutdown(self):
        """关闭插件管理器"""
        self.logger.info("Shutting down plugin manager")
        self.unload_all_plugins()
