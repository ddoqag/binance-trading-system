#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全仓杠杆交易风控控制器

提供针对杠杆交易的风险控制功能：
- 杠杆限制执行
- 每日亏损限制跟踪
- 清算警告和阻止
- 仓位大小验证
- 动态杠杆计算
"""

import logging
from dataclasses import dataclass
from datetime import datetime, date
from enum import Enum
from typing import Dict, Optional, Any, Tuple


class RiskStatus(Enum):
    """风险状态枚举"""
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class LeverageRiskConfig:
    """
    杠杆风险配置

    Attributes:
        max_position_size: 最大总仓位比例 (默认 0.8 = 80%)
        max_single_position: 单笔最大仓位比例 (默认 0.2 = 20%)
        max_leverage: 最大杠杆倍数 (默认 5.0)
        daily_loss_limit: 每日亏损限制比例 (默认 -0.05 = -5%)
        liquidation_warning_threshold: 清算警告阈值 (默认 1.3)
        liquidation_stop_threshold: 清算停止阈值 (默认 1.1)
        total_capital: 总资金 (默认 10000.0)
    """
    max_position_size: float = 0.8
    max_single_position: float = 0.2
    max_leverage: float = 5.0
    daily_loss_limit: float = -0.05
    liquidation_warning_threshold: float = 1.3
    liquidation_stop_threshold: float = 1.1
    total_capital: float = 10000.0


class StandardRiskController:
    """
    标准杠杆交易风控控制器

    提供完整的风险控制功能，包括：
    - 交易前风险检查 (can_trade)
    - 清算风险评估
    - 仓位大小验证
    - 动态杠杆计算
    - 每日亏损跟踪
    - 风险事件记录
    """

    def __init__(
        self,
        config: Optional[LeverageRiskConfig] = None,
        account_manager: Optional[Any] = None,
        position_manager: Optional[Any] = None
    ):
        """
        初始化风控控制器

        Args:
            config: 风险配置，使用默认配置如果未提供
            account_manager: 账户管理器，用于获取保证金水平
            position_manager: 仓位管理器，用于获取仓位信息
        """
        self.config = config or LeverageRiskConfig()
        self.account_manager = account_manager
        self.position_manager = position_manager
        self.logger = logging.getLogger('StandardRiskController')

        # 状态跟踪
        self.daily_pnl: float = 0.0
        self.total_trades: int = 0
        self.trading_enabled: bool = True
        self.last_reset_date: Optional[date] = datetime.now().date()

        # 仓位暴露跟踪 {symbol: exposure_value}
        self.position_exposure: Dict[str, float] = {}

        # 总资金（可以从账户管理器获取，也可以手动设置）
        self.total_capital: float = self.config.total_capital

        # 风险事件记录
        self.risk_events: list = []

        self.logger.info("StandardRiskController initialized")

    def _reset_daily_counters(self):
        """重置每日计数器（如果日期改变）"""
        today = datetime.now().date()
        if self.last_reset_date != today:
            self.daily_pnl = 0.0
            self.total_trades = 0
            self.last_reset_date = today
            self.trading_enabled = True  # 重置时重新启用交易
            self.logger.info(f"Daily counters reset for {today}")

    def can_trade(
        self,
        symbol: str,
        side: str,
        size: float,
        leverage: float,
        margin_level: Optional[float] = None
    ) -> Tuple[bool, str]:
        """
        检查是否可以执行交易

        Args:
            symbol: 交易对
            side: 交易方向 ("LONG" 或 "SHORT")
            size: 仓位大小（名义价值）
            leverage: 杠杆倍数
            margin_level: 保证金水平（可选，如果不提供将尝试从账户管理器获取）

        Returns:
            (是否可以交易, 原因说明)
        """
        # 重置每日计数器
        self._reset_daily_counters()

        # 检查交易是否被禁用
        if not self.trading_enabled:
            return False, "Trading disabled due to risk limits"

        # 检查杠杆限制
        if leverage > self.config.max_leverage:
            self._log_risk_event(
                "LEVERAGE_LIMIT",
                f"Leverage {leverage}x exceeds max {self.config.max_leverage}x"
            )
            return False, f"Leverage {leverage}x exceeds maximum {self.config.max_leverage}x"

        # 检查单笔仓位限制
        single_position_pct = size / self.total_capital
        if single_position_pct > self.config.max_single_position:
            self._log_risk_event(
                "SINGLE_POSITION_LIMIT",
                f"Position size {single_position_pct:.2%} exceeds max single {self.config.max_single_position:.2%}"
            )
            return False, f"Position size {single_position_pct:.2%} exceeds single limit {self.config.max_single_position:.2%}"

        # 检查总仓位限制
        current_exposure = self.get_total_exposure()
        new_total_exposure = current_exposure + size
        total_position_pct = new_total_exposure / self.total_capital

        if total_position_pct > self.config.max_position_size:
            self._log_risk_event(
                "POSITION_LIMIT",
                f"Total position {total_position_pct:.2%} would exceed max {self.config.max_position_size:.2%}"
            )
            return False, f"Total position {total_position_pct:.2%} would exceed limit {self.config.max_position_size:.2%}"

        # 检查每日亏损限制
        daily_loss_limit = self.config.daily_loss_limit * self.total_capital
        if self.daily_pnl < daily_loss_limit:
            self._log_risk_event(
                "DAILY_LOSS_LIMIT",
                f"Daily loss {self.daily_pnl:.2f} exceeds limit {daily_loss_limit:.2f}"
            )
            self.trading_enabled = False
            return False, f"Daily loss limit reached: {self.daily_pnl:.2f}"

        # 检查清算风险
        if margin_level is None:
            margin_level = self.get_margin_level()

        if margin_level is not None:
            liquidation_status = self.check_liquidation_risk(margin_level)
            if liquidation_status == RiskStatus.CRITICAL:
                return False, f"Critical margin level {margin_level:.2f}, trading stopped"

        return True, "OK"

    def check_liquidation_risk(self, margin_level: float) -> RiskStatus:
        """
        检查清算风险

        Args:
            margin_level: 当前保证金水平

        Returns:
            RiskStatus: 风险状态 (NORMAL, WARNING, CRITICAL)
        """
        if margin_level <= self.config.liquidation_stop_threshold:
            # 严重风险 - 停止交易
            self.trading_enabled = False
            self._log_risk_event(
                "LIQUIDATION_STOP",
                f"Margin level {margin_level:.2f} below stop threshold {self.config.liquidation_stop_threshold}",
                margin_level=margin_level
            )
            return RiskStatus.CRITICAL

        elif margin_level <= self.config.liquidation_warning_threshold:
            # 警告风险
            self._log_risk_event(
                "LIQUIDATION_WARNING",
                f"Margin level {margin_level:.2f} below warning threshold {self.config.liquidation_warning_threshold}",
                margin_level=margin_level
            )
            return RiskStatus.WARNING

        return RiskStatus.NORMAL

    def validate_position_size(
        self,
        symbol: str,
        size: float,
        current_exposure: float
    ) -> bool:
        """
        验证仓位大小

        Args:
            symbol: 交易对
            size: 新仓位大小
            current_exposure: 当前总暴露

        Returns:
            是否有效
        """
        # 检查单笔限制
        single_pct = size / self.total_capital
        if single_pct > self.config.max_single_position:
            return False

        # 检查总仓位限制
        total_pct = (current_exposure + size) / self.total_capital
        if total_pct > self.config.max_position_size:
            return False

        return True

    def calculate_dynamic_leverage(
        self,
        base_leverage: float,
        confidence: float,
        volatility: float,
        regime: str
    ) -> float:
        """
        计算动态杠杆

        公式: L = base_leverage × confidence × volatility_factor × regime_factor

        Args:
            base_leverage: 基础杠杆
            confidence: 置信度 (0.0 - 1.0)
            volatility: 波动率 (0.0 - 1.0)，越高风险越大
            regime: 市场状态 ("trending", "ranging", "volatile")

        Returns:
            计算后的杠杆倍数（不超过最大值）
        """
        # 波动率因子：低波动增加杠杆，高波动降低杠杆
        # 使用 (1.5 - volatility) 作为因子，范围 0.5 - 1.5
        volatility_factor = 1.5 - volatility
        volatility_factor = max(0.5, min(1.5, volatility_factor))

        # 市场状态因子
        regime_factors = {
            "trending": 1.2,  # 趋势市场增加杠杆
            "ranging": 0.8,   # 震荡市场降低杠杆
            "volatile": 0.6,  # 高波动市场大幅降低杠杆
            "normal": 1.0
        }
        regime_factor = regime_factors.get(regime, 1.0)

        # 计算动态杠杆
        dynamic_leverage = base_leverage * confidence * volatility_factor * regime_factor

        # 限制在最大杠杆内
        final_leverage = min(dynamic_leverage, self.config.max_leverage)
        final_leverage = max(1.0, final_leverage)  # 最小杠杆为 1

        self.logger.debug(
            f"Dynamic leverage: base={base_leverage}, conf={confidence}, "
            f"vol_factor={volatility_factor:.2f}, regime_factor={regime_factor}, "
            f"result={final_leverage:.2f}"
        )

        return final_leverage

    def on_trade_executed(
        self,
        symbol: str,
        side: str,
        size: float,
        leverage: float,
        pnl: float = 0.0
    ):
        """
        交易执行后的回调

        Args:
            symbol: 交易对
            side: 交易方向 ("LONG" 或 "SHORT")
            size: 仓位大小
            leverage: 杠杆倍数
            pnl: 已实现盈亏
        """
        # 重置每日计数器
        self._reset_daily_counters()

        # 更新交易计数
        self.total_trades += 1

        # 更新盈亏
        self.daily_pnl += pnl

        # 更新仓位暴露
        if side == "LONG":
            self.position_exposure[symbol] = self.position_exposure.get(symbol, 0) + size
        elif side == "SHORT":
            # 做空也增加暴露（绝对值）
            self.position_exposure[symbol] = self.position_exposure.get(symbol, 0) + size

        self.logger.debug(
            f"Trade executed: {symbol} {side} size={size}, leverage={leverage}, pnl={pnl:.2f}"
        )

    def get_total_exposure(self) -> float:
        """
        获取总仓位暴露

        Returns:
            总暴露价值
        """
        return sum(self.position_exposure.values())

    def get_exposure_pct(self) -> float:
        """
        获取仓位暴露比例

        Returns:
            暴露比例 (0.0 - 1.0)
        """
        if self.total_capital <= 0:
            return 0.0
        return self.get_total_exposure() / self.total_capital

    def get_margin_level(self) -> Optional[float]:
        """
        获取保证金水平

        Returns:
            保证金水平，如果无法获取则返回 None
        """
        if self.account_manager:
            try:
                return self.account_manager.get_margin_level()
            except Exception as e:
                self.logger.warning(f"Failed to get margin level from account manager: {e}")
        return None

    def get_positions(self) -> Dict[str, Any]:
        """
        获取仓位信息

        Returns:
            仓位信息字典
        """
        if self.position_manager:
            try:
                return self.position_manager.get_all_positions()
            except Exception as e:
                self.logger.warning(f"Failed to get positions from position manager: {e}")
        return {}

    def get_risk_summary(self) -> Dict[str, Any]:
        """
        获取风险摘要

        Returns:
            风险摘要字典
        """
        total_exposure = self.get_total_exposure()
        exposure_pct = self.get_exposure_pct()

        # 获取保证金水平
        margin_level = self.get_margin_level()

        # 确定风险状态
        if margin_level:
            if margin_level <= self.config.liquidation_stop_threshold:
                risk_status = RiskStatus.CRITICAL.value
            elif margin_level <= self.config.liquidation_warning_threshold:
                risk_status = RiskStatus.WARNING.value
            else:
                risk_status = RiskStatus.NORMAL.value
        else:
            risk_status = RiskStatus.NORMAL.value

        # 计算每日盈亏百分比
        daily_pnl_pct = self.daily_pnl / self.total_capital if self.total_capital > 0 else 0.0

        return {
            'trading_enabled': self.trading_enabled,
            'daily_pnl': self.daily_pnl,
            'daily_pnl_pct': daily_pnl_pct,
            'total_trades': self.total_trades,
            'total_exposure': total_exposure,
            'total_exposure_pct': exposure_pct,
            'margin_level': margin_level,
            'risk_status': risk_status,
            'position_count': len(self.position_exposure),
            'recent_events': self.risk_events[-10:]  # 最近 10 条事件
        }

    def _log_risk_event(self, event_type: str, message: str, **kwargs):
        """
        记录风险事件

        Args:
            event_type: 事件类型
            message: 事件消息
            **kwargs: 额外的事件数据
        """
        event = {
            'timestamp': datetime.now().isoformat(),
            'type': event_type,
            'message': message
        }
        event.update(kwargs)

        self.risk_events.append(event)
        self.logger.warning(f"RISK EVENT [{event_type}]: {message}")

    def enable_trading(self):
        """重新启用交易"""
        self.trading_enabled = True
        self.logger.info("Trading enabled")

    def disable_trading(self):
        """禁用交易"""
        self.trading_enabled = False
        self.logger.info("Trading disabled")

    def reset_daily_stats(self):
        """手动重置每日统计"""
        self.daily_pnl = 0.0
        self.total_trades = 0
        self.last_reset_date = datetime.now().date()
        self.logger.info("Daily stats manually reset")
