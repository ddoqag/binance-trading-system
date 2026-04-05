"""
灾难恢复模块
提供系统故障恢复机制
"""

import json
import pickle
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import shutil

logger = logging.getLogger(__name__)


@dataclass
class SystemState:
    """系统状态快照"""
    timestamp: float
    capital: float
    positions: Dict[str, Any]
    active_orders: List[Dict]
    strategy_weights: Dict[str, float]
    risk_metrics: Dict[str, float]
    metadata: Dict[str, Any]


class DisasterRecovery:
    """
    灾难恢复管理器

    功能:
    - 定期保存系统状态
    - 从故障中恢复
    - 数据备份和还原
    """

    def __init__(self, backup_dir: str = "./backups"):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.max_backups = 10

    def save_state(self, state: SystemState, name: Optional[str] = None) -> str:
        """
        保存系统状态

        Returns:
            备份文件路径
        """
        if name is None:
            name = f"state_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        filepath = self.backup_dir / f"{name}.json"

        # 转换为字典
        data = asdict(state)
        data['saved_at'] = datetime.now().isoformat()

        # 保存为JSON
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)

        # 清理旧备份
        self._cleanup_old_backups()

        logger.info(f"[DisasterRecovery] State saved: {filepath}")
        return str(filepath)

    def load_state(self, name: Optional[str] = None) -> Optional[SystemState]:
        """
        加载系统状态

        Args:
            name: 备份名称，None表示加载最新的

        Returns:
            SystemState或None
        """
        if name:
            filepath = self.backup_dir / f"{name}.json"
        else:
            # 找到最新的备份
            backups = sorted(self.backup_dir.glob("state_*.json"))
            if not backups:
                logger.warning("[DisasterRecovery] No backups found")
                return None
            filepath = backups[-1]

        if not filepath.exists():
            logger.error(f"[DisasterRecovery] Backup not found: {filepath}")
            return None

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            state = SystemState(
                timestamp=data['timestamp'],
                capital=data['capital'],
                positions=data['positions'],
                active_orders=data['active_orders'],
                strategy_weights=data['strategy_weights'],
                risk_metrics=data['risk_metrics'],
                metadata=data['metadata']
            )

            logger.info(f"[DisasterRecovery] State loaded: {filepath}")
            return state

        except Exception as e:
            logger.error(f"[DisasterRecovery] Failed to load state: {e}")
            return None

    def create_emergency_backup(self, reason: str = "emergency") -> str:
        """创建紧急备份"""
        name = f"emergency_{reason}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # 备份配置文件
        config_backup = self.backup_dir / f"{name}_config"
        if Path("config").exists():
            shutil.copytree("config", config_backup, dirs_exist_ok=True)

        # 备份日志
        log_backup = self.backup_dir / f"{name}_logs"
        if Path("logs").exists():
            shutil.copytree("logs", log_backup, dirs_exist_ok=True)

        logger.info(f"[DisasterRecovery] Emergency backup created: {name}")
        return name

    def list_backups(self) -> List[Dict[str, Any]]:
        """列出所有备份"""
        backups = []
        for filepath in sorted(self.backup_dir.glob("state_*.json")):
            stat = filepath.stat()
            backups.append({
                'name': filepath.stem,
                'created': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                'size_kb': stat.st_size / 1024
            })
        return backups

    def _cleanup_old_backups(self):
        """清理旧备份"""
        backups = sorted(self.backup_dir.glob("state_*.json"))
        if len(backups) > self.max_backups:
            for old_backup in backups[:-self.max_backups]:
                old_backup.unlink()
                logger.info(f"[DisasterRecovery] Old backup removed: {old_backup}")

    def verify_backup(self, name: str) -> bool:
        """验证备份完整性"""
        filepath = self.backup_dir / f"{name}.json"

        if not filepath.exists():
            return False

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            required_fields = ['timestamp', 'capital', 'positions']
            return all(field in data for field in required_fields)

        except Exception:
            return False
