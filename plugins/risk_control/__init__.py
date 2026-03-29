#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险控制插件（MVP 版本）
"""

from typing import Dict, Any, Optional
from plugins.base import PluginBase, PluginType, PluginMetadata


class RiskControlPlugin(PluginBase):
    """风险控制插件（MVP 版本）"""

    def _get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="risk_control",
            version="0.1.0",
            type=PluginType.RISK,
            interface_version="1.0.0",
            description="简单的风险控制插件",
            author="AI Trading System"
        )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.max_position_size = self.config.get('max_position_size', 0.8)
        self.max_daily_loss = self.config.get('max_daily_loss', 0.05)

    def initialize(self):
        """初始化插件"""
        self.logger.info("Initializing RiskControl plugin")

    def start(self):
        """启动插件"""
        self.logger.info("Starting RiskControl plugin")

    def stop(self):
        """停止插件"""
        self.logger.info("Stopping RiskControl plugin")

    def check_risk_constraints(self, order: Dict, portfolio: Dict) -> Dict:
        """检查风险约束"""
        result = {
            'passed': True,
            'reason': 'OK'
        }

        # 简单检查：总仓位限制
        if portfolio.get('position_ratio', 0) > self.max_position_size:
            result['passed'] = False
            result['reason'] = f"Position ratio exceeds max: {self.max_position_size}"

        # 简单检查：每日亏损限制
        if portfolio.get('daily_pnl', 0) < -self.max_daily_loss:
            result['passed'] = False
            result['reason'] = f"Daily loss exceeds max: {self.max_daily_loss}"

        return result
