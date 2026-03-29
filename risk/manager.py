#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险管理器 - 综合风险管理
"""

import logging
from typing import Dict, Optional, List, Any
from dataclasses import dataclass
from datetime import datetime

from .position import PositionManager
from .stop_loss import StopLossManager, StopType


@dataclass
class RiskConfig:
    """风险配置"""
    # 仓位限制
    max_position_size: float = 0.8  # 最大总仓位
    max_single_position: float = 0.2  # 单个币种最大仓位
    max_daily_loss: float = 0.05  # 单日最大亏损比例
    max_drawdown: float = 0.15  # 最大回撤

    # 止损参数
    default_stop_loss_pct: float = 0.02  # 默认止损百分比
    default_take_profit_pct: float = 0.04  # 默认止盈百分比
    use_trailing_stop: bool = True  # 是否使用移动止损
    trailing_stop_pct: float = 0.015  # 移动止损百分比

    # 交易限制
    max_trades_per_day: int = 50  # 每日最大交易次数
    max_concurrent_trades: int = 5  # 最大并发持仓数

    # 资金
    total_capital: float = 10000.0
    commission_rate: float = 0.001  # 佣金率 (0.1%)


class RiskManager:
    """综合风险管理器"""

    def __init__(self, config: Optional[RiskConfig] = None):
        """
        初始化风险管理器

        Args:
            config: 风险配置
        """
        self.config = config or RiskConfig()
        self.position_manager = PositionManager(
            max_position_size=self.config.max_position_size,
            max_single_position=self.config.max_single_position,
            total_capital=self.config.total_capital
        )
        self.stop_loss_manager = StopLossManager()
        self.logger = logging.getLogger('RiskManager')

        # 状态追踪
        self.daily_trades: int = 0
        self.daily_pnl: float = 0.0
        self.peak_capital: float = self.config.total_capital
        self.current_drawdown: float = 0.0
        self.trading_enabled: bool = True
        self.last_reset_date: Optional[datetime] = None

        # 历史记录
        self.risk_events: List[Dict] = []

    def _reset_daily_counters(self):
        """重置每日计数器"""
        today = datetime.now().date()
        if self.last_reset_date != today:
            self.daily_trades = 0
            self.daily_pnl = 0.0
            self.last_reset_date = today
            self.logger.debug("Reset daily counters")

    def can_trade(self, symbol: str, side: str, quantity: float,
                  price: float) -> tuple[bool, str]:
        """
        检查是否可以交易

        Args:
            symbol: 交易对
            side: 买卖方向
            quantity: 数量
            price: 价格

        Returns:
            (是否可以交易, 原因)
        """
        if not self.trading_enabled:
            return False, "Trading disabled due to risk limits"

        self._reset_daily_counters()

        # 检查每日交易次数
        if side == "BUY" and self.daily_trades >= self.config.max_trades_per_day:
            self._log_risk_event("DAILY_LIMIT", f"Max trades per day: {self.config.max_trades_per_day}")
            return False, f"Max daily trades reached: {self.config.max_trades_per_day}"

        # 检查每日亏损
        if self.daily_pnl < -self.config.max_daily_loss * self.config.total_capital:
            self._log_risk_event("DAILY_LOSS", f"Daily loss limit hit: {self.daily_pnl:.2f}")
            self.trading_enabled = False
            return False, f"Daily loss limit reached: {self.daily_pnl:.2f}"

        # 检查最大回撤
        if self.current_drawdown >= self.config.max_drawdown:
            self._log_risk_event("DRAWDOWN", f"Max drawdown hit: {self.current_drawdown:.2%}")
            self.trading_enabled = False
            return False, f"Max drawdown reached: {self.current_drawdown:.2%}"

        # 检查并发持仓数
        if side == "BUY":
            current_positions = len(self.position_manager.positions)
            if current_positions >= self.config.max_concurrent_trades:
                return False, f"Max concurrent positions: {self.config.max_concurrent_trades}"

        # 检查仓位限制
        if side == "BUY":
            if not self.position_manager.can_open_position(symbol, quantity, price):
                return False, "Position size limits exceeded"

        return True, "OK"

    def on_trade_executed(self, symbol: str, side: str, quantity: float,
                         price: float, pnl: float = 0.0):
        """
        交易执行后的回调

        Args:
            symbol: 交易对
            side: 买卖方向
            quantity: 数量
            price: 价格
            pnl: 已实现盈亏
        """
        self._reset_daily_counters()

        if side == "BUY":
            self.daily_trades += 1
            self.position_manager.open_position(symbol, quantity, price)

            # 自动设置止损止盈
            if self.config.default_stop_loss_pct > 0:
                sl_price = price * (1 - self.config.default_stop_loss_pct)
                self.stop_loss_manager.add_stop_loss(
                    symbol, sl_price, quantity,
                    stop_type=StopType.TRAILING if self.config.use_trailing_stop
                    else StopType.FIXED,
                    trailing_amount=price * self.config.trailing_stop_pct if self.config.use_trailing_stop else None
                )

            if self.config.default_take_profit_pct > 0:
                tp_price = price * (1 + self.config.default_take_profit_pct)
                self.stop_loss_manager.add_take_profit(symbol, tp_price, quantity)

        elif side == "SELL":
            realized_pnl = self.position_manager.close_position(symbol, price, quantity)
            self.daily_pnl += realized_pnl
            self.stop_loss_manager.cancel_all(symbol)

        # 更新资金峰值和回撤
        current_value = self.get_portfolio_value({'price': price})
        if current_value > self.peak_capital:
            self.peak_capital = current_value
        self.current_drawdown = (self.peak_capital - current_value) / self.peak_capital

    def update_market_prices(self, prices: Dict[str, float]):
        """
        更新市场价格

        Args:
            prices: 价格字典 {symbol: price}
        """
        # 更新持仓盈亏
        self.position_manager.update_all_pnl(prices)

        # 更新移动止损
        for symbol, price in prices.items():
            self.stop_loss_manager.update_trailing_stop(symbol, price)

            # 检查止损止盈触发
            triggered = self.stop_loss_manager.check_triggers(symbol, price)
            for order in triggered:
                self._log_risk_event(
                    order.side,
                    f"{order.side} triggered for {symbol} @ {price:.4f}"
                )

    def get_portfolio_value(self, prices: Dict[str, float]) -> float:
        """
        获取投资组合总价值

        Args:
            prices: 价格字典

        Returns:
            总价值
        """
        exposure = self.position_manager.get_total_exposure(prices)
        return self.position_manager.cash_available + exposure

    def _log_risk_event(self, event_type: str, message: str):
        """记录风险事件"""
        event = {
            'timestamp': datetime.now().isoformat(),
            'type': event_type,
            'message': message
        }
        self.risk_events.append(event)
        self.logger.warning(f"RISK EVENT [{event_type}]: {message}")

    def get_risk_summary(self) -> Dict[str, Any]:
        """
        获取风险摘要

        Returns:
            风险摘要字典
        """
        return {
            'trading_enabled': self.trading_enabled,
            'daily_trades': self.daily_trades,
            'daily_pnl': self.daily_pnl,
            'current_drawdown': self.current_drawdown,
            'peak_capital': self.peak_capital,
            'position_summary': self.position_manager.get_position_summary({}),
            'active_stop_orders': len(self.stop_loss_manager.get_active_orders()),
            'recent_risk_events': self.risk_events[-10:]
        }

    def enable_trading(self):
        """启用交易"""
        self.trading_enabled = True
        self.logger.info("Trading enabled")

    def emergency_stop(self):
        """紧急停止 - 关闭所有持仓和订单"""
        self.logger.warning("EMERGENCY STOP ACTIVATED")
        self.trading_enabled = False
        self.stop_loss_manager.cancel_all()
        self._log_risk_event("EMERGENCY_STOP", "Emergency stop activated")

    def record_trade_pnl(self, pnl: float):
        """
        记录交易盈亏（用于测试和外部触发熔断）

        Args:
            pnl: 盈亏金额
        """
        self._reset_daily_counters()
        self.daily_pnl += pnl

        # 检查是否触发每日亏损限制
        daily_loss_limit = -self.config.max_daily_loss * self.config.total_capital
        if self.daily_pnl < daily_loss_limit:
            self._log_risk_event("DAILY_LOSS", f"Daily loss limit hit: {self.daily_pnl:.2f}")
            self.trading_enabled = False
