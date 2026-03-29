# trading_system/monitor.py
"""
实时权益监控器。

功能：
  - 记录每次账户净值更新 → 生成权益曲线
  - 计算最大回撤（相对历史峰值）
  - 记录单日盈亏（可由 Trader 在每笔交易后调用）
  - 超过阈值时 should_alert() 返回 True，由调用方决定如何处理

使用方式：
    monitor = EquityMonitor(initial_equity=10000.0)

    # 每次交易结算后
    monitor.update(new_equity)
    monitor.record_trade_pnl(pnl)

    if monitor.should_alert():
        logger.critical("风控警报: %s", monitor.summary())

    # 每天结束时
    monitor.reset_daily()
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class EquityMonitor:
    """
    实时权益与风险监控器。

    Args:
        initial_equity:    初始账户净值（用于建立起点）。
        drawdown_alert:    回撤警报阈值，负数（默认 -0.10 = -10%）。
        daily_loss_alert:  日亏损警报阈值，负数（默认 -0.05 = -5%）。
    """

    def __init__(
        self,
        initial_equity: float,
        drawdown_alert: float = -0.10,
        daily_loss_alert: float = -0.05,
    ) -> None:
        self.current_equity: float = initial_equity
        self.peak_equity: float = initial_equity
        self.equity_curve: list[float] = [initial_equity]

        self._daily_pnl: float = 0.0
        self.drawdown_alert = drawdown_alert
        self.daily_loss_alert = daily_loss_alert

    # ── 更新接口 ──────────────────────────────────────────────────────────────

    def update(self, equity: float) -> None:
        """记录新的账户净值（每个交易周期结束后调用）。"""
        self.current_equity = equity
        if equity > self.peak_equity:
            self.peak_equity = equity
        self.equity_curve.append(equity)

        if self.should_alert():
            logger.warning(
                "风控警报 | 净值=%.2f 回撤=%.2f%% 日盈亏=%.2f",
                equity,
                self.max_drawdown() * 100,
                self._daily_pnl,
            )

    def record_trade_pnl(self, pnl: float) -> None:
        """记录单笔交易盈亏（用于计算当日累计盈亏）。"""
        self._daily_pnl += pnl

    def reset_daily(self) -> None:
        """每日收盘时重置日盈亏计数器。"""
        self._daily_pnl = 0.0

    # ── 指标计算 ──────────────────────────────────────────────────────────────

    def max_drawdown(self) -> float:
        """当前相对峰值的回撤（负数，0 表示在历史高点）。"""
        if self.peak_equity <= 0:
            return 0.0
        return (self.current_equity - self.peak_equity) / self.peak_equity

    def daily_pnl(self) -> float:
        """当日累计盈亏（绝对金额）。"""
        return self._daily_pnl

    # ── 警报判断 ──────────────────────────────────────────────────────────────

    def should_alert(self) -> bool:
        """
        是否需要触发风控警报。

        Returns:
            True = 需要人工介入或自动降仓。
        """
        if self.max_drawdown() <= self.drawdown_alert:
            return True
        if self.peak_equity > 0:
            daily_pct = self._daily_pnl / self.peak_equity
            if daily_pct <= self.daily_loss_alert:
                return True
        return False

    # ── 摘要 ─────────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        """返回当前状态摘要（供日志和监控系统使用）。"""
        return {
            "equity":    round(self.current_equity, 2),
            "peak":      round(self.peak_equity, 2),
            "drawdown":  round(self.max_drawdown(), 4),
            "daily_pnl": round(self._daily_pnl, 2),
            "alert":     self.should_alert(),
        }
