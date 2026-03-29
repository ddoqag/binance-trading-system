#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
原子配置更新器 - Atomic Config Updater
实现：先校验、再切换、失败回滚
"""

import os
import copy
import time
import json
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import logging

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


@dataclass
class UpdateResult:
    """配置更新结果"""
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


@dataclass
class RollbackResult:
    """配置回滚结果"""
    success: bool = False
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error: Optional[str] = None


class ConfigMismatchError(Exception):
    """配置不匹配错误"""
    pass


class ConfigValidator:
    """配置校验器"""

    def __init__(self, schema: Optional[Dict] = None):
        """初始化校验器"""
        self.schema = schema
        self.validation_rules: Dict[str, Callable] = {}

    def add_validation_rule(self, key: str, validator: Callable):
        """添加自定义校验规则"""
        self.validation_rules[key] = validator

    def validate(self, config: Dict) -> Optional[str]:
        """
        校验配置

        Returns:
            如果校验失败返回错误信息，校验通过返回None
        """
        # 使用Pydantic校验
        try:
            from pydantic import BaseModel, ValidationError
            if self.schema and issubclass(self.schema, BaseModel):
                self.schema(**config)
        except ValidationError as e:
            return f"Schema validation failed: {e}"
        except ImportError:
            pass

        # 自定义校验规则
        for key, validator in self.validation_rules.items():
            if key in config:
                try:
                    if not validator(config[key]):
                        return f"Validation failed for {key}"
                except Exception as e:
                    return f"Validation error for {key}: {e}"

        return None


class AtomicConfigUpdater:
    """
    原子配置更新器
    实现：先校验、再切换、失败回滚
    """

    def __init__(self, config_path: Path, validator: Optional[ConfigValidator] = None):
        """
        初始化原子配置更新器

        Args:
            config_path: 配置文件路径
            validator: 配置校验器
        """
        self.config_path = config_path
        self.validator = validator or ConfigValidator()
        self._backup_path = config_path.with_suffix('.bak')
        self._change_log_path = config_path.parent / 'config_changes.log'
        self._current_config: Optional[Dict] = None
        self.logger = logging.getLogger('AtomicConfigUpdater')

    def update_config(self, updates: Dict[str, Any],
                     author: str,
                     reason: str) -> UpdateResult:
        """
        原子更新配置

        Args:
            updates: 要更新的键值对
            author: 更新者
            reason: 更新原因

        Returns:
            UpdateResult: 更新结果
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
            validation_error = self.validator.validate(new_config)
            if validation_error:
                result.success = False
                result.error = f"Validation failed: {validation_error}"
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
            self.logger.info(f"Config update successful: {reason}")
            return result

        except Exception as e:
            # 失败时回滚
            result.success = False
            result.error = str(e)
            self.logger.error(f"Config update failed: {e}")

            if self._backup_path.exists():
                rollback_result = self.rollback()
                result.rollback_performed = True
                result.rollback_result = rollback_result

            result.end_time = datetime.utcnow()
            return result

    def rollback(self) -> RollbackResult:
        """
        回滚到备份配置

        Returns:
            RollbackResult: 回滚结果
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
            self.logger.info("Config rollback successful")
            return result

        except Exception as e:
            result.success = False
            result.error = str(e)
            result.end_time = datetime.utcnow()
            self.logger.error(f"Config rollback failed: {e}")
            return result

    def _read_config(self) -> Dict:
        """读取配置文件"""
        if not self.config_path.exists():
            return {}

        # 根据文件扩展名选择读取方式
        ext = self.config_path.suffix.lower()

        if ext in ('.yaml', '.yml'):
            if not YAML_AVAILABLE:
                raise ImportError("PyYAML not available")
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        elif ext == '.json':
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            raise ValueError(f"Unsupported config format: {ext}")

    def _write_config(self, config: Dict):
        """写入配置文件（原子操作）"""
        # 先写入临时文件，再重命名（原子操作）
        temp_path = self.config_path.with_suffix('.tmp')

        ext = self.config_path.suffix.lower()

        if ext in ('.yaml', '.yml'):
            if not YAML_AVAILABLE:
                raise ImportError("PyYAML not available")
            with open(temp_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        elif ext == '.json':
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        else:
            raise ValueError(f"Unsupported config format: {ext}")

        # 原子重命名
        os.replace(temp_path, self.config_path)

    def _create_backup(self, config: Dict):
        """创建备份"""
        ext = self._backup_path.suffix.lower()

        if ext in ('.yaml', '.yml'):
            if not YAML_AVAILABLE:
                return
            with open(self._backup_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        elif ext == '.json':
            with open(self._backup_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

    def _read_backup(self) -> Dict:
        """读取备份"""
        ext = self._backup_path.suffix.lower()

        if ext in ('.yaml', '.yml'):
            if not YAML_AVAILABLE:
                raise ImportError("PyYAML not available")
            with open(self._backup_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        elif ext == '.json':
            with open(self._backup_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            return {}

    def _apply_updates(self, config: Dict, updates: Dict) -> Dict:
        """应用更新（递归）"""
        result = copy.deepcopy(config)

        for key, value in updates.items():
            if isinstance(value, dict) and key in result and isinstance(result[key], dict):
                result[key] = self._apply_updates(result[key], value)
            else:
                result[key] = value

        return result

    def _configs_equal(self, a: Dict, b: Dict) -> bool:
        """比较两个配置是否相同"""
        return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def _log_change(self, result: UpdateResult):
        """记录配置变更"""
        log_entry = {
            "timestamp": result.end_time.isoformat() if result.end_time else datetime.utcnow().isoformat(),
            "author": result.author,
            "reason": result.reason,
            "success": result.success,
            "duration_ms": (result.end_time - result.start_time).total_seconds() * 1000 if result.start_time and result.end_time else 0,
        }

        # 简单的日志记录
        try:
            if not self._change_log_path.exists():
                self._change_log_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self._change_log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        except Exception as e:
            self.logger.warning(f"Failed to log config change: {e}")

    def get_change_history(self, limit: int = 100) -> List[Dict]:
        """获取配置变更历史"""
        if not self._change_log_path.exists():
            return []

        history = []
        try:
            with open(self._change_log_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        history.append(json.loads(line))
        except Exception as e:
            self.logger.error(f"Failed to read change history: {e}")

        return history[-limit:]
