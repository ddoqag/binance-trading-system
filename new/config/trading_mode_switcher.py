"""
交易模式切换器 - Trading Mode Switcher

安全地在实盘和模拟盘之间切换。
注意：模式切换需要重启 trader（安全第一）。
"""

import os
import logging
from pathlib import Path
from typing import Optional

from config.mode import TradingMode

logger = logging.getLogger(__name__)


class TradingModeSwitcher:
    """
    交易模式切换器

    通过环境变量和配置文件管理交易模式。
    模式切换需要重启才能生效（安全设计）。
    """

    ENV_VAR = "TRADING_MODE"
    CONFIG_FILE = ".trading_mode"

    def __init__(self, project_root: Optional[str] = None):
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self._mode_file = self.project_root / self.CONFIG_FILE

    def get_current_mode(self) -> TradingMode:
        """
        获取当前交易模式

        优先级：
        1. 环境变量 TRADING_MODE
        2. 配置文件 .trading_mode
        3. 默认: PAPER（安全默认）
        """
        # 1. 检查环境变量
        env_mode = os.getenv(self.ENV_VAR)
        if env_mode:
            try:
                mode = TradingMode.from_string(env_mode)
                logger.debug(f"[ModeSwitcher] Mode from env: {mode.value}")
                return mode
            except ValueError:
                logger.warning(f"[ModeSwitcher] Invalid env mode: {env_mode}")

        # 2. 检查配置文件
        if self._mode_file.exists():
            try:
                file_mode = self._mode_file.read_text().strip().lower()
                mode = TradingMode.from_string(file_mode)
                logger.debug(f"[ModeSwitcher] Mode from file: {mode.value}")
                return mode
            except (ValueError, IOError) as e:
                logger.warning(f"[ModeSwitcher] Failed to read mode file: {e}")

        # 3. 默认 PAPER（安全第一）
        logger.warning("[ModeSwitcher] No mode configured, defaulting to PAPER (safety)")
        return TradingMode.PAPER

    def set_mode(self, mode: TradingMode, persist: bool = True):
        """
        设置交易模式

        Args:
            mode: 目标模式
            persist: 是否持久化到配置文件

        Note:
            设置后需要重启 trader 才能生效
        """
        # 设置环境变量（当前进程）
        os.environ[self.ENV_VAR] = mode.value

        # 持久化到文件
        if persist:
            try:
                self._mode_file.write_text(mode.value)
                logger.info(f"[ModeSwitcher] Mode saved to {self._mode_file}: {mode.value}")
            except IOError as e:
                logger.error(f"[ModeSwitcher] Failed to save mode: {e}")

        # 安全提醒
        if mode.is_live():
            logger.warning("=" * 60)
            logger.warning("  ⚠️  TRADING MODE SET TO: LIVE")
            logger.warning("  Real money will be used!")
            logger.warning("  Please restart the trader to apply.")
            logger.warning("=" * 60)
        else:
            logger.info(f"[ModeSwitcher] Mode set to: {mode.value}")
            logger.info("[ModeSwitcher] Please restart the trader to apply.")

    def validate_mode_switch(self, from_mode: TradingMode, to_mode: TradingMode) -> bool:
        """
        验证模式切换是否安全

        PAPER -> LIVE: 需要确认
        LIVE -> PAPER: 总是允许
        """
        if from_mode == to_mode:
            return True

        if from_mode.is_paper() and to_mode.is_live():
            # PAPER -> LIVE 需要额外确认
            logger.warning("Switching from PAPER to LIVE requires confirmation!")
            return False

        return True

    def get_mode_status(self) -> dict:
        """获取模式状态"""
        current = self.get_current_mode()

        return {
            "current_mode": current.value,
            "is_live": current.is_live(),
            "is_paper": current.is_paper(),
            "env_mode": os.getenv(self.ENV_VAR),
            "file_exists": self._mode_file.exists(),
            "file_path": str(self._mode_file),
            "requires_restart": True  # 模式切换总是需要重启
        }


def create_exchange_for_mode(
    mode: TradingMode,
    api_key: str = "",
    api_secret: str = "",
    **kwargs
):
    """
    根据交易模式创建对应的交易所实例

    Args:
        mode: 交易模式
        api_key: API Key（实盘需要）
        api_secret: API Secret（实盘需要）
        **kwargs: 额外参数

    Returns:
        BaseExchange 实例
    """
    if mode.is_live():
        from core.live_order_manager import LiveOrderManager

        if not api_key or not api_secret:
            raise ValueError("LIVE mode requires API key and secret")

        return LiveOrderManager(
            api_key=api_key,
            api_secret=api_secret,
            use_testnet=kwargs.get("use_testnet", False),
            max_leverage=kwargs.get("max_leverage", 3),
        )
    else:
        from core.paper_exchange import PaperExchange

        return PaperExchange(
            initial_balance=kwargs.get("initial_capital", 10000.0),
            commission_rate=kwargs.get("commission_rate", 0.001),
            slippage_pct=kwargs.get("slippage_pct", 0.01),
        )
