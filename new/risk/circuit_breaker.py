"""
风控熔断模块 - Circuit Breaker

提供日内最大回撤和连续亏损的熔断保护机制。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreakerState:
    """熔断状态"""
    daily_start_balance: float = 0.0
    current_balance: float = 0.0
    max_drawdown_limit: float = 0.05  # 默认5%最大回撤
    consecutive_losses: int = 0
    max_consecutive_losses: int = 5   # 默认连续5次亏损暂停
    trading_halted: bool = False
    halt_reason: Optional[str] = None
    halt_time: Optional[datetime] = None
    total_trades_today: int = 0
    winning_trades_today: int = 0


@dataclass
class CircuitBreakerConfig:
    """熔断配置 - 支持热更新"""
    max_drawdown_pct: float = 5.0      # 最大回撤百分比
    max_consecutive_losses: int = 5     # 最大连续亏损次数
    daily_loss_limit_pct: float = 3.0   # 日内亏损限制
    cooldown_minutes: int = 30          # 熔断后冷却时间（分钟）
    auto_reset_on_new_day: bool = True  # 是否每日自动重置


class CircuitBreaker:
    """
    风控熔断器

    触发条件：
    1. 日内最大回撤超过阈值
    2. 连续亏损次数超过阈值
    3. 日内总亏损超过阈值
    """

    def __init__(
        self,
        config: Optional[CircuitBreakerConfig] = None,
        notify_fn: Optional[Callable[[str, str], Awaitable[None]]] = None
    ):
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitBreakerState()
        self.notify_fn = notify_fn
        self._last_trade_result: Optional[bool] = None

        logger.info(
            f"[CircuitBreaker] Initialized: max_drawdown={self.config.max_drawdown_pct}%, "
            f"max_consecutive_losses={self.config.max_consecutive_losses}"
        )

    def update_config(self, config: CircuitBreakerConfig):
        """热更新配置"""
        old_drawdown = self.config.max_drawdown_pct
        old_losses = self.config.max_consecutive_losses

        self.config = config

        logger.info(
            f"[CircuitBreaker] Config updated: "
            f"max_drawdown={old_drawdown}% -> {config.max_drawdown_pct}%, "
            f"max_consecutive={old_losses} -> {config.max_consecutive_losses}"
        )

    def initialize_balance(self, balance: float):
        """初始化每日起始余额"""
        self.state.daily_start_balance = balance
        self.state.current_balance = balance
        logger.info(f"[CircuitBreaker] Daily balance initialized: {balance:.2f} USDT")

    async def check(self, current_balance: Optional[float] = None) -> bool:
        """
        检查熔断状态

        Returns:
            True: 允许交易
            False: 熔断触发，禁止交易
        """
        if current_balance is not None:
            self.state.current_balance = current_balance

        # 如果已经熔断，检查是否可以恢复
        if self.state.trading_halted:
            return False

        # 检查最大回撤
        if self.state.daily_start_balance > 0:
            drawdown = (
                self.state.daily_start_balance - self.state.current_balance
            ) / self.state.daily_start_balance

            if drawdown >= self.config.max_drawdown_pct / 100:
                await self._trigger_halt(
                    f"[ALERT] Max drawdown reached: {drawdown:.2%} "
                    f"(limit: {self.config.max_drawdown_pct}%)"
                )
                return False

        # 检查连续亏损
        if self.state.consecutive_losses >= self.config.max_consecutive_losses:
            await self._trigger_halt(
                f"[ALERT] Consecutive losses: {self.state.consecutive_losses} "
                f"(limit: {self.config.max_consecutive_losses})"
            )
            return False

        return True

    async def _trigger_halt(self, reason: str):
        """触发熔断"""
        if not self.state.trading_halted:
            self.state.trading_halted = True
            self.state.halt_reason = reason
            self.state.halt_time = datetime.now()

            logger.critical(f"[CircuitBreaker] HALT TRIGGERED: {reason}")

            if self.notify_fn:
                await self.notify_fn(reason, "CRITICAL")

    def record_trade_result(self, realized_pnl: float):
        """记录交易结果，更新连续亏损计数"""
        self.state.total_trades_today += 1

        if realized_pnl > 0:
            # 盈利，重置连续亏损计数
            if self.state.consecutive_losses > 0:
                logger.info(
                    f"[CircuitBreaker] Win! Reset consecutive losses: "
                    f"{self.state.consecutive_losses} -> 0"
                )
            self.state.consecutive_losses = 0
            self.state.winning_trades_today += 1
            self._last_trade_result = True
        else:
            # 亏损，增加连续亏损计数
            self.state.consecutive_losses += 1
            logger.warning(
                f"[CircuitBreaker] Loss! Consecutive losses: "
                f"{self.state.consecutive_losses}/{self.config.max_consecutive_losses}"
            )
            self._last_trade_result = False

    def can_place_order(self) -> bool:
        """快速检查是否可以下单（不触发通知）"""
        return not self.state.trading_halted

    async def try_resume(self) -> bool:
        """
        尝试恢复交易（冷却时间过后）

        Returns:
            True: 恢复成功
            False: 仍在冷却中
        """
        if not self.state.trading_halted:
            return True

        if self.state.halt_time and self.config.cooldown_minutes > 0:
            elapsed = (datetime.now() - self.state.halt_time).total_seconds() / 60

            if elapsed >= self.config.cooldown_minutes:
                logger.info(f"[CircuitBreaker] Cooldown expired ({elapsed:.1f}m), resuming trading")
                await self.reset()
                return True
            else:
                remaining = self.config.cooldown_minutes - elapsed
                logger.debug(f"[CircuitBreaker] Cooldown: {remaining:.1f}m remaining")

        return False

    async def reset(self):
        """重置熔断状态（每日调用或手动恢复）"""
        was_halted = self.state.trading_halted

        self.state.trading_halted = False
        self.state.halt_reason = None
        self.state.halt_time = None
        self.state.consecutive_losses = 0
        self.state.total_trades_today = 0
        self.state.winning_trades_today = 0

        # 保持当前余额作为新的起始余额
        if self.state.current_balance > 0:
            self.state.daily_start_balance = self.state.current_balance

        if was_halted:
            msg = "[OK] Circuit breaker reset. Trading resumed."
            logger.info(f"[CircuitBreaker] {msg}")

            if self.notify_fn:
                await self.notify_fn(msg, "INFO")

    def get_status(self) -> dict:
        """获取熔断器状态"""
        drawdown = 0.0
        if self.state.daily_start_balance > 0:
            drawdown = (
                self.state.daily_start_balance - self.state.current_balance
            ) / self.state.daily_start_balance

        return {
            "trading_halted": self.state.trading_halted,
            "halt_reason": self.state.halt_reason,
            "halt_time": self.state.halt_time.isoformat() if self.state.halt_time else None,
            "daily_start_balance": self.state.daily_start_balance,
            "current_balance": self.state.current_balance,
            "drawdown_pct": drawdown * 100,
            "drawdown_limit_pct": self.config.max_drawdown_pct,
            "consecutive_losses": self.state.consecutive_losses,
            "max_consecutive_losses": self.config.max_consecutive_losses,
            "total_trades_today": self.state.total_trades_today,
            "winning_trades_today": self.state.winning_trades_today,
            "win_rate_today": (
                self.state.winning_trades_today / max(1, self.state.total_trades_today)
            ),
        }
