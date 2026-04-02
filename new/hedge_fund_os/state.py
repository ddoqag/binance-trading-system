"""
Hedge Fund OS - 系统状态机

管理 Growth / Survival / Crisis / Shutdown 等模式切换
"""

import time
import logging
from typing import Optional, Callable, List
from dataclasses import dataclass

from .types import SystemMode


logger = logging.getLogger(__name__)


@dataclass
class ModeTransition:
    """模式转换记录"""
    from_mode: SystemMode
    to_mode: SystemMode
    reason: str
    timestamp: float


class StateMachine:
    """
    系统状态机

    管理 Hedge Fund OS 的全局运行模式，支持：
    - 模式查询
    - 受控模式切换
    - 切换冷却期
    - 切换回调
    """

    # 合法转换路径
    VALID_TRANSITIONS: dict = {
        SystemMode.INITIALIZING: {SystemMode.GROWTH, SystemMode.SHUTDOWN, SystemMode.RECOVERY},
        SystemMode.GROWTH: {SystemMode.SURVIVAL, SystemMode.CRISIS, SystemMode.SHUTDOWN, SystemMode.RECOVERY},
        SystemMode.SURVIVAL: {SystemMode.GROWTH, SystemMode.CRISIS, SystemMode.SHUTDOWN, SystemMode.RECOVERY},
        SystemMode.CRISIS: {SystemMode.SURVIVAL, SystemMode.SHUTDOWN, SystemMode.RECOVERY},
        SystemMode.RECOVERY: {SystemMode.GROWTH, SystemMode.SURVIVAL, SystemMode.SHUTDOWN},
        SystemMode.SHUTDOWN: set(),
    }

    def __init__(
        self,
        initial_mode: SystemMode = SystemMode.INITIALIZING,
        cooldown_seconds: float = 10.0,
    ):
        self._mode = initial_mode
        self._cooldown = cooldown_seconds
        self._last_switch_time = time.time()
        self._history: List[ModeTransition] = []
        self._callbacks: List[Callable[[SystemMode, SystemMode, str], None]] = []

    @property
    def mode(self) -> SystemMode:
        return self._mode

    @property
    def history(self) -> List[ModeTransition]:
        return list(self._history)

    def can_switch_to(self, target_mode: SystemMode) -> bool:
        """检查是否可以切换到目标模式"""
        if target_mode == self._mode:
            return True

        if target_mode not in self.VALID_TRANSITIONS.get(self._mode, set()):
            return False

        elapsed = time.time() - self._last_switch_time
        if elapsed < self._cooldown:
            return False

        return True

    def switch(self, target_mode: SystemMode, reason: str = "") -> bool:
        """尝试切换模式"""
        if target_mode == self._mode:
            return True

        if not self.can_switch_to(target_mode):
            logger.warning(
                "Mode switch rejected: %s -> %s (reason: %s)",
                self._mode.name, target_mode.name, reason
            )
            return False

        old_mode = self._mode
        self._mode = target_mode
        self._last_switch_time = time.time()

        transition = ModeTransition(
            from_mode=old_mode,
            to_mode=target_mode,
            reason=reason,
            timestamp=self._last_switch_time,
        )
        self._history.append(transition)

        logger.info(
            "Mode switched: %s -> %s (reason: %s)",
            old_mode.name, target_mode.name, reason
        )

        for cb in self._callbacks:
            try:
                cb(old_mode, target_mode, reason)
            except Exception as e:
                logger.error("Mode switch callback error: %s", e)

        return True

    def force_switch(self, target_mode: SystemMode, reason: str = "") -> bool:
        """强制切换模式（绕过冷却期和路径检查）"""
        if target_mode == self._mode:
            return True

        old_mode = self._mode
        self._mode = target_mode
        self._last_switch_time = time.time()

        transition = ModeTransition(
            from_mode=old_mode,
            to_mode=target_mode,
            reason=f"[FORCE] {reason}",
            timestamp=self._last_switch_time,
        )
        self._history.append(transition)

        logger.warning(
            "Mode FORCED: %s -> %s (reason: %s)",
            old_mode.name, target_mode.name, reason
        )

        for cb in self._callbacks:
            try:
                cb(old_mode, target_mode, reason)
            except Exception as e:
                logger.error("Mode switch callback error: %s", e)

        return True

    def register_callback(self, callback: Callable[[SystemMode, SystemMode, str], None]) -> None:
        """注册模式切换回调"""
        self._callbacks.append(callback)

    def time_since_last_switch(self) -> float:
        """距离上次模式切换的时间（秒）"""
        return time.time() - self._last_switch_time

    def is_in_crisis(self) -> bool:
        return self._mode == SystemMode.CRISIS

    def is_shutdown(self) -> bool:
        return self._mode == SystemMode.SHUTDOWN
