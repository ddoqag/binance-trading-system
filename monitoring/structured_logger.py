#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
结构化日志系统 - Structured Logger
支持 JSON 格式的结构化日志输出
"""

import logging
import structlog
from typing import Dict, Any
from datetime import datetime
import sys
import os
from enum import Enum


class LogLevel(Enum):
    """日志级别"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class StructuredLogger:
    """
    结构化日志记录器（JSON格式）
    """

    def __init__(self, service_name: str = "trading_system",
                 log_level: LogLevel = LogLevel.INFO,
                 output_file: str = "logs/trading_system.log",
                 enable_console: bool = True,
                 enable_file: bool = True):
        """
        初始化结构化日志记录器

        Args:
            service_name: 服务名称
            log_level: 日志级别
            output_file: 输出文件路径
            enable_console: 是否启用控制台输出
            enable_file: 是否启用文件输出
        """
        self.service_name = service_name
        self.log_level = log_level
        self.output_file = output_file
        self.enable_console = enable_console
        self.enable_file = enable_file

        # 确保日志目录存在
        if enable_file:
            os.makedirs(os.path.dirname(output_file), exist_ok=True)

        # 配置 structlog
        self._configure_structlog()

        self.logger = structlog.get_logger(service_name)

    def _configure_structlog(self):
        """配置 structlog """
        processors = [
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ]

        structlog.configure(
            processors=processors,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )

        # 配置根 logger
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, self.log_level.value.upper()))
        root_logger.handlers = []

        # 控制台输出
        if self.enable_console:
            console_handler = logging.StreamHandler(sys.stdout)
            root_logger.addHandler(console_handler)

        # 文件输出
        if self.enable_file:
            file_handler = logging.FileHandler(self.output_file)
            root_logger.addHandler(file_handler)

    def _add_context(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """添加通用上下文信息"""
        event.update({
            "service": self.service_name,
            "timestamp": datetime.utcnow().isoformat(),
            "env": os.getenv("ENVIRONMENT", "development"),
            "version": os.getenv("VERSION", "unknown")
        })
        return event

    # ==================== 插件日志 ====================

    def plugin_event(self, plugin_name: str, event_type: str,
                    details: Dict[str, Any] = None):
        """
        记录插件相关事件

        Args:
            plugin_name: 插件名称
            event_type: 事件类型
            details: 事件详细信息
        """
        event = {
            "event": "plugin",
            "plugin_name": plugin_name,
            "event_type": event_type,
            "details": details or {}
        }
        self.logger.info(**self._add_context(event))

    def plugin_metrics(self, plugin_name: str, metrics: Dict[str, float]):
        """
        记录插件指标

        Args:
            plugin_name: 插件名称
            metrics: 指标字典
        """
        event = {
            "event": "plugin_metrics",
            "plugin_name": plugin_name,
            "metrics": metrics
        }
        self.logger.info(**self._add_context(event))

    # ==================== 交易日志 ====================

    def trading_signal(self, strategy: str, symbol: str,
                      signal: str, price: float, confidence: float):
        """
        记录交易信号

        Args:
            strategy: 策略名称
            symbol: 交易对
            signal: 信号类型 (BUY/SELL/HOLD)
            price: 价格
            confidence: 置信度 (0-1)
        """
        event = {
            "event": "trading_signal",
            "strategy": strategy,
            "symbol": symbol,
            "signal": signal,
            "price": price,
            "confidence": confidence
        }
        self.logger.info(**self._add_context(event))

    def order_executed(self, order_id: str, symbol: str, side: str,
                      qty: float, price: float, pnl: float = 0.0):
        """
        记录订单执行

        Args:
            order_id: 订单ID
            symbol: 交易对
            side: 买卖方向
            qty: 数量
            price: 价格
            pnl: 已实现盈亏
        """
        event = {
            "event": "order_executed",
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "quantity": qty,
            "price": price,
            "pnl": pnl
        }
        self.logger.info(**self._add_context(event))

    # ==================== 风险日志 ====================

    def risk_check_passed(self, check_type: str, details: Dict[str, Any] = None):
        """
        记录风险检查通过

        Args:
            check_type: 检查类型
            details: 详细信息
        """
        event = {
            "event": "risk_check",
            "check_type": check_type,
            "result": "passed",
            "details": details or {}
        }
        self.logger.info(**self._add_context(event))

    def risk_triggered(self, check_type: str, reason: str,
                      action_taken: str, details: Dict[str, Any] = None):
        """
        记录风险触发

        Args:
            check_type: 检查类型
            reason: 触发原因
            action_taken: 采取的行动
            details: 详细信息
        """
        event = {
            "event": "risk_triggered",
            "check_type": check_type,
            "reason": reason,
            "action_taken": action_taken,
            "details": details or {}
        }
        self.logger.warning(**self._add_context(event))

    # ==================== 业务指标 ====================

    def strategy_performance(self, strategy: str, returns: float,
                           sharpe: float, max_drawdown: float,
                           win_rate: float, total_trades: int):
        """
        记录策略绩效

        Args:
            strategy: 策略名称
            returns: 收益率
            sharpe: 夏普比率
            max_drawdown: 最大回撤
            win_rate: 胜率
            total_trades: 总交易次数
        """
        event = {
            "event": "strategy_performance",
            "strategy": strategy,
            "returns": returns,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_drawdown,
            "win_rate": win_rate,
            "total_trades": total_trades
        }
        self.logger.info(**self._add_context(event))

    def portfolio_metrics(self, total_value: float, cash: float,
                        position_value: float, exposure: float):
        """
        记录投资组合指标

        Args:
            total_value: 总价值
            cash: 现金
            position_value: 持仓价值
            exposure: 风险暴露
        """
        event = {
            "event": "portfolio_metrics",
            "total_value": total_value,
            "cash": cash,
            "position_value": position_value,
            "exposure": exposure
        }
        self.logger.info(**self._add_context(event))

    # ==================== 系统日志 ====================

    def system_event(self, component: str, event_type: str,
                    message: str, details: Dict[str, Any] = None):
        """
        记录系统事件

        Args:
            component: 组件名称
            event_type: 事件类型
            message: 事件消息
            details: 详细信息
        """
        event = {
            "event": "system",
            "component": component,
            "event_type": event_type,
            "message": message,
            "details": details or {}
        }
        self.logger.info(**self._add_context(event))

    def system_error(self, component: str, error: str,
                    traceback_str: str = None,
                    details: Dict[str, Any] = None):
        """
        记录系统错误

        Args:
            component: 组件名称
            error: 错误消息
            traceback_str: 堆栈跟踪信息
            details: 详细信息
        """
        event = {
            "event": "system_error",
            "component": component,
            "error": error,
            "traceback": traceback_str,
            "details": details or {}
        }
        self.logger.error(**self._add_context(event))

    # ==================== 通用方法 ====================

    def debug(self, message: str, **kwargs):
        """记录调试信息"""
        self.logger.debug(**self._add_context({"message": message, **kwargs}))

    def info(self, message: str, **kwargs):
        """记录信息"""
        self.logger.info(**self._add_context({"message": message, **kwargs}))

    def warning(self, message: str, **kwargs):
        """记录警告"""
        self.logger.warning(**self._add_context({"message": message, **kwargs}))

    def error(self, message: str, **kwargs):
        """记录错误"""
        self.logger.error(**self._add_context({"message": message, **kwargs}))

    def critical(self, message: str, **kwargs):
        """记录严重错误"""
        self.logger.critical(**self._add_context({"message": message, **kwargs}))


# 全局 logger 实例
_global_logger = None


def get_structured_logger(service_name: str = "trading_system") -> StructuredLogger:
    """
    获取全局结构化日志记录器实例

    Args:
        service_name: 服务名称

    Returns:
        StructuredLogger: 日志记录器实例
    """
    global _global_logger

    if _global_logger is None:
        _global_logger = StructuredLogger(service_name)

    return _global_logger
