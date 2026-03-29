#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理器 - Configuration Manager
支持 YAML + JSON Schema / Pydantic + 环境变量
"""

import os
import copy
from typing import Dict, Any, Optional
from pathlib import Path
import logging
from dataclasses import dataclass, field
from enum import Enum

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

try:
    from pydantic import BaseModel, ValidationError
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False


class ConfigSource(Enum):
    """配置来源"""
    DEFAULT = "default"
    YAML_FILE = "yaml_file"
    ENVIRONMENT = "environment"
    OVERRIDE = "override"


@dataclass
class ConfigValue:
    """配置值，包含来源信息"""
    value: Any
    source: ConfigSource
    source_path: Optional[str] = None


class ConfigManager:
    """
    配置管理器
    支持：YAML文件 + 环境变量覆盖 + Pydantic验证
    """

    def __init__(self, config_path: Optional[Path] = None,
                 env_prefix: str = "BINANCE_",
                 schema_model: Optional[type] = None):
        """
        初始化配置管理器

        Args:
            config_path: YAML配置文件路径
            env_prefix: 环境变量前缀
            schema_model: Pydantic验证模型
        """
        self.config_path = config_path
        self.env_prefix = env_prefix
        self.schema_model = schema_model
        self.logger = logging.getLogger('ConfigManager')

        self._config: Dict[str, ConfigValue] = {}
        self._default_config: Dict[str, Any] = {}

    def set_defaults(self, defaults: Dict[str, Any]):
        """设置默认配置"""
        self._default_config = copy.deepcopy(defaults)

        for key, value in defaults.items():
            self._config[key] = ConfigValue(
                value=value,
                source=ConfigSource.DEFAULT
            )

    def load(self) -> Dict[str, Any]:
        """
        加载配置
        优先级：环境变量 > YAML文件 > 默认值
        """
        # 从YAML文件加载
        if self.config_path and self.config_path.exists():
            self._load_from_yaml()

        # 从环境变量加载
        self._load_from_env()

        # 验证配置
        if self.schema_model and PYDANTIC_AVAILABLE:
            self._validate_config()

        self.logger.info(f"Config loaded from {len(self._config)} sources")
        return self.get_config()

    def _load_from_yaml(self):
        """从YAML文件加载配置"""
        if not YAML_AVAILABLE:
            self.logger.warning("PyYAML not available, skipping YAML load")
            return

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                yaml_config = yaml.safe_load(f)

            if yaml_config and isinstance(yaml_config, dict):
                for key, value in yaml_config.items():
                    self._config[key] = ConfigValue(
                        value=value,
                        source=ConfigSource.YAML_FILE,
                        source_path=str(self.config_path)
                    )

            self.logger.info(f"Loaded config from {self.config_path}")

        except Exception as e:
            self.logger.error(f"Failed to load YAML config: {e}")

    def _load_from_env(self):
        """从环境变量加载配置"""
        for key, value in os.environ.items():
            if key.startswith(self.env_prefix):
                config_key = key[len(self.env_prefix):].lower()

                # 尝试类型转换
                converted_value = self._convert_env_value(value)

                self._config[config_key] = ConfigValue(
                    value=converted_value,
                    source=ConfigSource.ENVIRONMENT,
                    source_path=key
                )

    def _convert_env_value(self, value: str) -> Any:
        """转换环境变量值类型"""
        # 布尔值
        if value.lower() in ('true', 'false', 'yes', 'no', '1', '0'):
            return value.lower() in ('true', 'yes', '1')

        # 整数
        try:
            return int(value)
        except ValueError:
            pass

        # 浮点数
        try:
            return float(value)
        except ValueError:
            pass

        # 保持字符串
        return value

    def _validate_config(self):
        """使用Pydantic验证配置"""
        if not self.schema_model:
            return

        try:
            config_dict = self.get_config()
            self.schema_model(**config_dict)
            self.logger.info("Config validation passed")
        except ValidationError as e:
            self.logger.error(f"Config validation failed: {e}")
            raise

    def get_config(self) -> Dict[str, Any]:
        """获取完整的配置字典"""
        return {
            key: config_value.value
            for key, config_value in self._config.items()
        }

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        config_value = self._config.get(key)
        if config_value is None:
            return default
        return config_value.value

    def get_with_source(self, key: str) -> Optional[ConfigValue]:
        """获取配置值及其来源信息"""
        return self._config.get(key)

    def override(self, key: str, value: Any):
        """临时覆盖配置值"""
        self._config[key] = ConfigValue(
            value=value,
            source=ConfigSource.OVERRIDE
        )
        self.logger.debug(f"Config overridden: {key}")

    def get_source_info(self) -> Dict[str, ConfigSource]:
        """获取所有配置项的来源信息"""
        return {
            key: config_value.source
            for key, config_value in self._config.items()
        }


def load_config(config_path: Optional[Path] = None,
                env_prefix: str = "BINANCE_",
                schema_model: Optional[type] = None,
                defaults: Optional[Dict[str, Any]] = None) -> ConfigManager:
    """
    便捷函数：创建并加载配置管理器

    Args:
        config_path: YAML配置文件路径
        env_prefix: 环境变量前缀
        schema_model: Pydantic验证模型
        defaults: 默认配置字典

    Returns:
        ConfigManager实例
    """
    manager = ConfigManager(config_path, env_prefix, schema_model)

    if defaults:
        manager.set_defaults(defaults)

    manager.load()
    return manager
