#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qwen3.5-7B 驱动的 AI 交易系统（MVP）
"""

import logging
from typing import Optional, Dict, Any, List
from pathlib import Path

# Import existing modules
from config.settings import get_settings
from plugins.base import PluginBase


class TradingSystem:
    """Qwen3.5-7B 驱动的 AI 交易系统（MVP）"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.logger = logging.getLogger('TradingSystem')
        self._running = False
        self._plugins: Dict[str, PluginBase] = {}
        self.settings = get_settings()

    def initialize(self) -> bool:
        """系统初始化（同步版本）"""
        try:
            self.logger.info("Initializing TradingSystem")

            # 初始化插件
            plugins_to_load = self.config.get('plugins', [
                'qwen_trend_analyzer',
                'strategy_matcher',
                'risk_control'
            ])

            # 逐个初始化插件（同步版本）
            for plugin_name in plugins_to_load:
                try:
                    self._initialize_plugin(plugin_name)
                except Exception as e:
                    self.logger.warning(f"Failed to load plugin {plugin_name}: {e}")

            self.logger.info("TradingSystem initialized successfully")
            return True
        except Exception as e:
            self.logger.error(f"System initialization failed: {e}")
            return False

    def _initialize_plugin(self, plugin_name: str):
        """初始化单个插件"""
        if plugin_name == 'qwen_trend_analyzer':
            from plugins.qwen_trend_analyzer import QwenTrendAnalyzerPlugin
            plugin = QwenTrendAnalyzerPlugin()
            self._plugins[plugin_name] = plugin
        elif plugin_name == 'strategy_matcher':
            from plugins.strategy_matcher import StrategyMatcherPlugin
            plugin = StrategyMatcherPlugin()
            plugin.initialize()
            self._plugins[plugin_name] = plugin
        elif plugin_name == 'risk_control':
            from plugins.risk_control import RiskControlPlugin
            plugin = RiskControlPlugin()
            self._plugins[plugin_name] = plugin

    def start(self):
        """启动系统"""
        self.logger.info("Starting TradingSystem")
        self._running = True

    def stop(self):
        """停止系统"""
        self.logger.info("Stopping TradingSystem")
        self._running = False

    def run_single_cycle(self, market_data=None) -> Dict[str, Any]:
        """运行单个交易周期"""
        result = {
            'timestamp': 0,
            'status': 'success',
            'message': 'Single cycle executed',
            'trend_analysis': None,
            'matched_strategies': None,
            'risk_check': None
        }

        try:
            # 趋势分析
            if 'qwen_trend_analyzer' in self._plugins and market_data is not None:
                try:
                    analyzer = self._plugins['qwen_trend_analyzer']
                    if hasattr(analyzer, 'analyze_trend'):
                        result['trend_analysis'] = analyzer.analyze_trend(market_data)
                except Exception as e:
                    self.logger.warning(f"Trend analysis failed: {e}")

            # 策略匹配
            if 'strategy_matcher' in self._plugins and result['trend_analysis']:
                try:
                    matcher = self._plugins['strategy_matcher']
                    if hasattr(matcher, 'match_strategies'):
                        result['matched_strategies'] = matcher.match_strategies(result['trend_analysis'])
                except Exception as e:
                    self.logger.warning(f"Strategy matching failed: {e}")

            # 风险检查
            if 'risk_control' in self._plugins:
                try:
                    risk_control = self._plugins['risk_control']
                    if hasattr(risk_control, 'check_risk_constraints'):
                        portfolio = {'position_ratio': 0.0, 'daily_pnl': 0.0}
                        result['risk_check'] = risk_control.check_risk_constraints({}, portfolio)
                except Exception as e:
                    self.logger.warning(f"Risk check failed: {e}")

        except Exception as e:
            result['status'] = 'failed'
            result['message'] = str(e)

        return result

    def get_plugin(self, name: str) -> Optional[PluginBase]:
        """获取插件实例"""
        return self._plugins.get(name)

    @property
    def is_running(self) -> bool:
        """系统是否运行中"""
        return self._running
