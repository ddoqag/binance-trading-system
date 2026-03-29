#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
插件版本管理与兼容性验证
支持插件接口版本管理、兼容性检查和迁移
"""

from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import logging
from semver import Version, parse


class CompatibilityStatus(Enum):
    """兼容性状态"""
    FULLY_COMPATIBLE = "fully_compatible"
    BACKWARD_COMPATIBLE = "backward_compatible"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


class MigrationStrategy(Enum):
    """迁移策略"""
    AUTOMATIC = "automatic"
    MANUAL = "manual"
    HYBRID = "hybrid"
    UNSUPPORTED = "unsupported"


@dataclass
class PluginInterfaceVersion:
    """插件接口版本"""
    major: int
    minor: int
    patch: int
    description: str = ""
    breaking_changes: List[str] = field(default_factory=list)
    new_features: List[str] = field(default_factory=list)
    deprecated_features: List[str] = field(default_factory=list)
    released_at: Optional[datetime] = None

    @property
    def version_str(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass
class MigrationStep:
    """迁移步骤"""
    from_version: str
    to_version: str
    strategy: MigrationStrategy
    migrator: Optional[Callable] = None
    description: str = ""


@dataclass
class CompatibilityResult:
    """兼容性检查结果"""
    plugin_name: str
    plugin_version: str
    interface_version: str
    status: CompatibilityStatus
    message: str = ""
    breaking_changes: List[str] = field(default_factory=list)
    deprecation_warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)


class PluginVersionManager:
    """
    插件版本管理器
    负责插件接口版本管理、兼容性检查和迁移
    """

    def __init__(self, current_interface_version: str = "1.0.0"):
        """
        初始化插件版本管理器

        Args:
            current_interface_version: 当前插件系统的接口版本
        """
        self.logger = logging.getLogger('PluginVersionManager')
        self.current_version = self._parse_version(current_interface_version)

        # 接口版本历史
        self._interface_versions: Dict[str, PluginInterfaceVersion] = {}

        # 迁移步骤
        self._migrations: Dict[str, List[MigrationStep]] = {}

        # 注册默认接口版本
        self._register_default_versions()

    def _parse_version(self, version_str: str) -> Version:
        """解析版本字符串"""
        return Version.parse(version_str)

    def _register_default_versions(self):
        """注册默认接口版本"""
        # 1.0.0 - 初始版本
        self.register_interface_version(
            major=1,
            minor=0,
            patch=0,
            description="Initial plugin system interface",
            breaking_changes=[],
            new_features=["Basic plugin interface", "Event bus integration"]
        )

        # 1.1.0 - 增强版本
        self.register_interface_version(
            major=1,
            minor=1,
            patch=0,
            description="Enhanced plugin interface with health checks",
            breaking_changes=[],
            new_features=["Health check API", "Extended metadata"]
        )

    def register_interface_version(self, major: int, minor: int, patch: int,
                                   description: str = "",
                                   breaking_changes: List[str] = None,
                                   new_features: List[str] = None,
                                   deprecated_features: List[str] = None) -> str:
        """
        注册接口版本

        Args:
            major: 主版本号
            minor: 次版本号
            patch: 补丁版本号
            description: 版本描述
            breaking_changes: 破坏性变更列表
            new_features: 新功能列表
            deprecated_features: 废弃功能列表

        Returns:
            版本字符串
        """
        version = PluginInterfaceVersion(
            major=major,
            minor=minor,
            patch=patch,
            description=description,
            breaking_changes=breaking_changes or [],
            new_features=new_features or [],
            deprecated_features=deprecated_features or [],
            released_at=datetime.utcnow()
        )

        version_str = version.version_str
        self._interface_versions[version_str] = version

        self.logger.info(f"Registered interface version: {version_str}")
        return version_str

    def check_compatibility(self, plugin_name: str,
                           plugin_interface_version: str,
                           plugin_system_version: Optional[str] = None) -> CompatibilityResult:
        """
        检查插件与系统的兼容性

        Args:
            plugin_name: 插件名称
            plugin_interface_version: 插件的接口版本要求
            plugin_system_version: 插件系统版本（可选，默认使用当前版本）

        Returns:
            兼容性检查结果
        """
        system_version = self._parse_version(plugin_system_version) if plugin_system_version else self.current_version
        plugin_version = self._parse_version(plugin_interface_version)

        result = CompatibilityResult(
            plugin_name=plugin_name,
            plugin_version=plugin_interface_version,
            interface_version=system_version,
            status=CompatibilityStatus.UNKNOWN
        )

        # 比较版本
        if plugin_version.major != system_version.major:
            # 主版本不同，不兼容
            result.status = CompatibilityStatus.INCOMPATIBLE
            result.message = f"Major version mismatch: plugin requires v{plugin_version.major}, system is v{system_version.major}"

            # 查找破坏性变更
            if plugin_interface_version in self._interface_versions:
                result.breaking_changes = self._interface_versions[plugin_interface_version].breaking_changes

            result.suggestions.append(f"Consider upgrading plugin to support interface v{system_version.major}")

        elif plugin_version.minor > system_version.minor:
            # 插件需要更新的次版本，系统较旧
            result.status = CompatibilityStatus.INCOMPATIBLE
            result.message = f"Plugin requires newer interface: v{plugin_version.minor} > v{system_version.minor}"
            result.suggestions.append(f"Upgrade plugin system to v{plugin_version.major}.{plugin_version.minor}.x")

        elif plugin_version.major == system_version.major:
            if plugin_version.minor == system_version.minor:
                # 版本完全匹配
                result.status = CompatibilityStatus.FULLY_COMPATIBLE
                result.message = "Plugin is fully compatible with the current interface"
            else:
                # 插件使用较旧的接口，但向后兼容
                result.status = CompatibilityStatus.BACKWARD_COMPATIBLE
                result.message = f"Plugin uses older interface v{plugin_version.minor}, but system is backward compatible"

                # 检查废弃功能警告
                if plugin_interface_version in self._interface_versions:
                    deprecated = self._interface_versions[plugin_interface_version].deprecated_features
                    result.deprecation_warnings = [
                        f"Feature '{f}' is deprecated" for f in deprecated
                    ]

        return result

    def register_migration(self, from_version: str, to_version: str,
                         strategy: MigrationStrategy,
                         migrator: Optional[Callable] = None,
                         description: str = ""):
        """
        注册迁移步骤

        Args:
            from_version: 源版本
            to_version: 目标版本
            strategy: 迁移策略
            migrator: 迁移函数
            description: 迁移描述
        """
        if from_version not in self._migrations:
            self._migrations[from_version] = []

        self._migrations[from_version].append(MigrationStep(
            from_version=from_version,
            to_version=to_version,
            strategy=strategy,
            migrator=migrator,
            description=description
        ))

        self.logger.info(f"Registered migration: {from_version} -> {to_version}")

    def get_migration_path(self, from_version: str, to_version: str) -> Optional[List[MigrationStep]]:
        """
        获取从一个版本到另一个版本的迁移路径

        Args:
            from_version: 源版本
            to_version: 目标版本

        Returns:
            迁移步骤列表，如果无法迁移则返回 None
        """
        from_ver = self._parse_version(from_version)
        to_ver = self._parse_version(to_version)

        if from_ver == to_ver:
            return []

        if from_ver > to_ver:
            self.logger.warning(f"Downgrading from {from_version} to {to_version} not supported")
            return None

        # 简单实现：查找直接迁移路径
        path = []
        current = from_version

        while current != to_version:
            if current not in self._migrations:
                break

            # 查找下一步迁移
            next_step = None
            for step in self._migrations[current]:
                if self._parse_version(step.to_version) <= to_ver:
                    next_step = step
                    break

            if not next_step:
                break

            path.append(next_step)
            current = next_step.to_version

        if current != to_version:
            self.logger.warning(f"Could not find migration path from {from_version} to {to_version}")
            return None

        return path

    def get_interface_version_info(self, version_str: str) -> Optional[PluginInterfaceVersion]:
        """获取接口版本信息"""
        return self._interface_versions.get(version_str)

    def get_all_interface_versions(self) -> List[PluginInterfaceVersion]:
        """获取所有接口版本"""
        return sorted(
            self._interface_versions.values(),
            key=lambda v: (v.major, v.minor, v.patch),
            reverse=True
        )


# 全局版本管理器实例
_version_manager: Optional[PluginVersionManager] = None


def get_version_manager() -> PluginVersionManager:
    """获取全局版本管理器实例"""
    global _version_manager
    if _version_manager is None:
        _version_manager = PluginVersionManager()
    return _version_manager


def set_version_manager(manager: PluginVersionManager):
    """设置全局版本管理器"""
    global _version_manager
    _version_manager = manager
