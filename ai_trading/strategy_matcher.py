#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略匹配器 - 根据市场状态匹配最优策略
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any
from enum import Enum
import logging
from dataclasses import dataclass
from pathlib import Path

from strategy.base import BaseStrategy
from strategy.dual_ma import DualMAStrategy
from strategy.rsi_strategy import RSIStrategy
from ai_trading.market_analyzer import TrendType, MarketRegime


class StrategyPriority(Enum):
    """策略优先级"""
    PRIMARY = "primary"
    SECONDARY = "secondary"
    FALLBACK = "fallback"


@dataclass
class StrategyConfig:
    """策略配置"""
    name: str
    strategy_class: type
    params: Dict[str, Any]
    suitable_trends: List[TrendType]
    suitable_regimes: List[MarketRegime]
    priority: StrategyPriority
    min_confidence: float = 0.5
    description: str = ""


class StrategyMatcher:
    """策略匹配器"""

    def __init__(self):
        """初始化策略匹配器"""
        self.logger = logging.getLogger('StrategyMatcher')
        self.strategy_configs: Dict[str, StrategyConfig] = {}
        self._register_default_strategies()

    def _register_default_strategies(self):
        """注册默认策略"""
        # 双均线策略 - 趋势跟踪
        self.register_strategy(StrategyConfig(
            name="dual_ma",
            strategy_class=DualMAStrategy,
            params={"short_window": 10, "long_window": 30},
            suitable_trends=[TrendType.UPTREND, TrendType.DOWNTREND],
            suitable_regimes=[MarketRegime.BULL, MarketRegime.BEAR],
            priority=StrategyPriority.PRIMARY,
            description="双均线趋势跟踪策略，适合明确的上涨或下跌趋势"
        ))

        # RSI策略 - 均值回归
        self.register_strategy(StrategyConfig(
            name="rsi",
            strategy_class=RSIStrategy,
            params={"period": 14, "oversold": 30, "overbought": 70},
            suitable_trends=[TrendType.SIDEWAYS, TrendType.VOLATILE],
            suitable_regimes=[MarketRegime.NEUTRAL, MarketRegime.HIGH_VOLATILITY],
            priority=StrategyPriority.PRIMARY,
            description="RSI均值回归策略，适合震荡和高波动市场"
        ))

        # 双均线保守版 - 趋势跟踪
        self.register_strategy(StrategyConfig(
            name="dual_ma_conservative",
            strategy_class=DualMAStrategy,
            params={"short_window": 20, "long_window": 60},
            suitable_trends=[TrendType.UPTREND, TrendType.DOWNTREND],
            suitable_regimes=[MarketRegime.BULL, MarketRegime.BEAR],
            priority=StrategyPriority.SECONDARY,
            min_confidence=0.7,
            description="保守版双均线策略，信号更可靠但交易频率更低"
        ))

        # RSI保守版 - 均值回归
        self.register_strategy(StrategyConfig(
            name="rsi_conservative",
            strategy_class=RSIStrategy,
            params={"period": 21, "oversold": 20, "overbought": 80},
            suitable_trends=[TrendType.SIDEWAYS, TrendType.VOLATILE],
            suitable_regimes=[MarketRegime.NEUTRAL, MarketRegime.HIGH_VOLATILITY],
            priority=StrategyPriority.SECONDARY,
            min_confidence=0.7,
            description="保守版RSI策略，减少假信号"
        ))

    def register_strategy(self, config: StrategyConfig):
        """
        注册策略

        Args:
            config: 策略配置
        """
        self.strategy_configs[config.name] = config
        self.logger.info(f"Registered strategy: {config.name}")

    def match_strategies(self, trend_analysis: Dict[str, Any],
                        max_strategies: int = 3) -> List[StrategyConfig]:
        """
        匹配适合当前市场状态的策略

        Args:
            trend_analysis: 趋势分析结果
            max_strategies: 返回的最大策略数量

        Returns:
            按优先级排序的策略配置列表
        """
        current_trend = trend_analysis.get('trend')
        current_regime = trend_analysis.get('regime')
        confidence = trend_analysis.get('confidence', 0.5)

        self.logger.info(f"Matching strategies for trend={current_trend}, "
                        f"regime={current_regime}, confidence={confidence:.2f}")

        # 评分和筛选策略
        scored_strategies = []
        for name, config in self.strategy_configs.items():
            # 检查是否满足最低置信度要求
            if confidence < config.min_confidence:
                continue

            # 计算匹配分数
            score = self._calculate_match_score(config, current_trend, current_regime, confidence)

            if score > 0:
                scored_strategies.append((score, config))

        # 按分数排序
        scored_strategies.sort(key=lambda x: (-x[0], x[1].priority.value))

        # 返回顶部N个策略
        matched = [config for _, config in scored_strategies[:max_strategies]]

        self.logger.info(f"Matched {len(matched)} strategies: "
                        f"{[c.name for c in matched]}")

        return matched

    def _calculate_match_score(self, config: StrategyConfig,
                              trend: TrendType,
                              regime: MarketRegime,
                              confidence: float) -> float:
        """
        计算策略匹配分数

        Args:
            config: 策略配置
            trend: 当前趋势
            regime: 当前市场状态
            confidence: 趋势置信度

        Returns:
            匹配分数（0-1）
        """
        score = 0.0

        # 趋势匹配
        if trend in config.suitable_trends:
            score += 0.4

        # 市场状态匹配
        if regime in config.suitable_regimes:
            score += 0.3

        # 优先级加分
        if config.priority == StrategyPriority.PRIMARY:
            score += 0.2
        elif config.priority == StrategyPriority.SECONDARY:
            score += 0.1

        # 置信度因子
        score *= confidence

        return score

    def create_strategy(self, config: StrategyConfig) -> BaseStrategy:
        """
        创建策略实例

        Args:
            config: 策略配置

        Returns:
            策略实例
        """
        return config.strategy_class(**config.params)

    def get_strategy_by_name(self, name: str) -> Optional[StrategyConfig]:
        """
        根据名称获取策略配置

        Args:
            name: 策略名称

        Returns:
            策略配置，不存在则返回None
        """
        return self.strategy_configs.get(name)

    def get_all_strategies(self) -> Dict[str, StrategyConfig]:
        """获取所有注册的策略"""
        return self.strategy_configs.copy()

    def select_best_strategy(self, trend_analysis: Dict[str, Any],
                            historical_performance: Optional[Dict[str, float]] = None) -> StrategyConfig:
        """
        选择最优策略（考虑历史表现）

        Args:
            trend_analysis: 趋势分析结果
            historical_performance: 历史表现字典 {策略名: 收益率}

        Returns:
            最优策略配置
        """
        matched = self.match_strategies(trend_analysis, max_strategies=5)

        if not matched:
            # 返回默认策略
            fallback = self.strategy_configs.get("dual_ma")
            if fallback:
                return fallback
            raise ValueError("No strategies available")

        # 如果有历史表现，结合历史表现选择
        if historical_performance:
            scored = []
            for i, config in enumerate(matched):
                # 当前匹配分数
                match_score = 1.0 - i * 0.15
                # 历史表现分数
                perf_score = historical_performance.get(config.name, 0.0)
                # 综合分数
                total_score = match_score * 0.6 + perf_score * 0.4
                scored.append((total_score, config))

            scored.sort(key=lambda x: -x[0])
            return scored[0][1]

        return matched[0]
