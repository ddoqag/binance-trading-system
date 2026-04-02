"""
Hedge Fund OS - Meta Brain (决策大脑)

系统"前额叶皮层" - 决定"做什么"
- 市场状态检测 (Regime Detection)
- 策略选择 (Strategy Selection)
- 风险偏好决策 (Risk Appetite)
- 模式切换触发 (Mode Switching)
"""

import time
import logging
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import numpy as np

from .types import (
    SystemMode, RiskLevel, MarketRegime, MarketState, MetaDecision,
    TrendDirection, LiquidityState
)
from .risk_kernel import RiskThresholds


logger = logging.getLogger(__name__)


class StrategyType(Enum):
    """策略类型"""
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"
    MOMENTUM = "momentum"
    VOLATILITY = "volatility"
    BREAKOUT = "breakout"


@dataclass
class StrategyScore:
    """策略评分"""
    strategy: StrategyType
    score: float  # 0-1
    expected_return: float
    risk_level: RiskLevel
    regime_suitability: Dict[MarketRegime, float]


@dataclass
class MetaBrainConfig:
    """Meta Brain 配置"""
    # 状态检测参数
    lookback_window: int = 100  # 回看窗口
    volatility_threshold_low: float = 0.15  # 15% 年化波动率以下为低波动
    volatility_threshold_high: float = 0.30  # 30% 以上为高波动
    
    # 策略选择参数
    min_strategy_score: float = 0.3
    max_active_strategies: int = 3
    strategy_switch_cooldown: float = 60.0  # 60秒冷却期
    
    # 风险偏好映射
    conservative_drawdown_threshold: float = 0.03  # 3% 回撤触发保守
    aggressive_drawdown_threshold: float = 0.10   # 10% 回撤仍可激进


class SimpleRegimeDetector:
    """
    简化版市场状态检测器
    
    基于波动率和趋势方向判断市场状态
    """
    
    def __init__(self, config: MetaBrainConfig):
        self.config = config
        self._price_history: List[float] = []
        self._volatility_history: List[float] = []
        
    def update(self, price: float) -> None:
        """更新价格数据"""
        self._price_history.append(price)
        if len(self._price_history) > self.config.lookback_window:
            self._price_history.pop(0)
            
        # 计算滚动波动率
        if len(self._price_history) >= 20:
            returns = np.diff(np.log(self._price_history[-20:]))
            vol = np.std(returns) * np.sqrt(252)  # 年化波动率
            self._volatility_history.append(vol)
            if len(self._volatility_history) > 100:
                self._volatility_history.pop(0)
                
    def detect_regime(self) -> Tuple[MarketRegime, float]:
        """
        检测市场状态
        
        Returns:
            (regime, confidence)
        """
        if len(self._price_history) < 20:
            return MarketRegime.RANGE_BOUND, 0.5
            
        # 计算趋势
        returns = np.diff(self._price_history)
        trend_score = np.sum(returns) / (np.std(returns) * np.sqrt(len(returns)) + 1e-6)
        
        # 判断趋势方向
        if trend_score > 1.0:
            trend = TrendDirection.UP
        elif trend_score < -1.0:
            trend = TrendDirection.DOWN
        else:
            trend = TrendDirection.NEUTRAL
            
        # 判断波动率状态
        if self._volatility_history:
            current_vol = self._volatility_history[-1]
            if current_vol < self.config.volatility_threshold_low:
                vol_regime = MarketRegime.LOW_VOL
            elif current_vol > self.config.volatility_threshold_high:
                vol_regime = MarketRegime.HIGH_VOL
            else:
                vol_regime = MarketRegime.RANGE_BOUND
        else:
            vol_regime = MarketRegime.RANGE_BOUND
            
        # 综合判断
        if vol_regime == MarketRegime.HIGH_VOL:
            if abs(trend_score) > 2.0:
                return MarketRegime.TRENDING, min(abs(trend_score) / 3.0, 1.0)
            return MarketRegime.HIGH_VOL, 0.7
        elif trend != TrendDirection.NEUTRAL and vol_regime == MarketRegime.LOW_VOL:
            return MarketRegime.TRENDING, min(abs(trend_score) / 2.0, 0.9)
        else:
            return MarketRegime.RANGE_BOUND, 0.6
            
    def get_volatility_forecast(self) -> float:
        """预测未来波动率（简单指数平均）"""
        if len(self._volatility_history) < 10:
            return 0.20  # 默认 20%
        # 指数加权平均
        weights = np.exp(np.linspace(-1, 0, len(self._volatility_history)))
        weights /= weights.sum()
        return float(np.dot(self._volatility_history, weights))


class StrategySelector:
    """
    策略选择器
    
    根据市场状态和策略历史表现选择最优策略组合
    """
    
    def __init__(self, config: MetaBrainConfig):
        self.config = config
        self._strategy_scores: Dict[StrategyType, float] = {}
        self._last_switch_time = 0.0
        
        # 策略-状态适应性矩阵
        self._regime_suitability = {
            StrategyType.TREND_FOLLOWING: {
                MarketRegime.TRENDING: 0.9,
                MarketRegime.HIGH_VOL: 0.6,
                MarketRegime.RANGE_BOUND: 0.3,
                MarketRegime.LOW_VOL: 0.7,
            },
            StrategyType.MEAN_REVERSION: {
                MarketRegime.TRENDING: 0.2,
                MarketRegime.HIGH_VOL: 0.4,
                MarketRegime.RANGE_BOUND: 0.9,
                MarketRegime.LOW_VOL: 0.8,
            },
            StrategyType.MOMENTUM: {
                MarketRegime.TRENDING: 0.8,
                MarketRegime.HIGH_VOL: 0.5,
                MarketRegime.RANGE_BOUND: 0.4,
                MarketRegime.LOW_VOL: 0.6,
            },
            StrategyType.VOLATILITY: {
                MarketRegime.TRENDING: 0.3,
                MarketRegime.HIGH_VOL: 0.9,
                MarketRegime.RANGE_BOUND: 0.5,
                MarketRegime.LOW_VOL: 0.2,
            },
            StrategyType.BREAKOUT: {
                MarketRegime.TRENDING: 0.7,
                MarketRegime.HIGH_VOL: 0.7,
                MarketRegime.RANGE_BOUND: 0.6,
                MarketRegime.LOW_VOL: 0.4,
            },
        }
        
    def can_switch(self) -> bool:
        """检查是否满足切换冷却期"""
        elapsed = time.time() - self._last_switch_time
        return elapsed >= self.config.strategy_switch_cooldown
        
    def select_strategies(
        self,
        regime: MarketRegime,
        confidence: float,
        current_drawdown: float
    ) -> Tuple[List[StrategyType], Dict[str, float]]:
        """
        选择策略组合
        
        Returns:
            (selected_strategies, strategy_weights)
        """
        if not self.can_switch():
            # 冷却期内保持现有策略
            return list(self._strategy_scores.keys()), self._get_weights_from_scores()
            
        # 根据回撤调整风险偏好
        if current_drawdown > self.config.conservative_drawdown_threshold:
            risk_adjustment = 0.5  # 保守
        elif current_drawdown < self.config.aggressive_drawdown_threshold:
            risk_adjustment = 1.0  # 激进
        else:
            risk_adjustment = 0.8  # 适中
            
        # 计算每个策略的得分
        scores = {}
        for strategy, suitability in self._regime_suitability.items():
            base_score = suitability.get(regime, 0.5)
            # 调整得分
            adjusted_score = base_score * confidence * risk_adjustment
            scores[strategy] = adjusted_score
            
        # 排序并选择 top N
        sorted_strategies = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        selected = [s for s, score in sorted_strategies[:self.config.max_active_strategies] 
                   if score >= self.config.min_strategy_score]
        
        if not selected:
            # 默认选择 Breakout（最稳健）
            selected = [StrategyType.BREAKOUT]
            
        self._strategy_scores = {s: scores[s] for s in selected}
        self._last_switch_time = time.time()
        
        weights = self._get_weights_from_scores()
        return selected, weights
        
    def _get_weights_from_scores(self) -> Dict[str, float]:
        """根据得分计算权重"""
        if not self._strategy_scores:
            return {}
        total = sum(self._strategy_scores.values())
        if total == 0:
            # 等权重
            n = len(self._strategy_scores)
            return {s.value: 1.0/n for s in self._strategy_scores}
        return {s.value: score/total for s, score in self._strategy_scores.items()}


class MetaBrain:
    """
    Meta Brain - 决策大脑
    
    核心职责：
    1. 感知市场 (perceive)
    2. 做出决策 (decide)
    """
    
    def __init__(self, config: Optional[MetaBrainConfig] = None):
        self.config = config or MetaBrainConfig()
        self.regime_detector = SimpleRegimeDetector(self.config)
        self.strategy_selector = StrategySelector(self.config)
        
        # 状态
        self._current_price: Optional[float] = None
        self._current_drawdown: float = 0.0
        self._last_decision: Optional[MetaDecision] = None
        
        # 回调
        self._decision_callbacks: List[Callable[[MetaDecision], None]] = []
        
    def register_decision_callback(self, callback: Callable[[MetaDecision], None]) -> None:
        """注册决策回调"""
        self._decision_callbacks.append(callback)
        
    def update_market_data(
        self,
        price: float,
        drawdown: float = 0.0,
        **kwargs
    ) -> None:
        """更新市场数据"""
        self._current_price = price
        self._current_drawdown = drawdown
        self.regime_detector.update(price)
        
    def perceive(self) -> MarketState:
        """
        感知市场状态
        
        Returns:
            MarketState
        """
        regime, confidence = self.regime_detector.detect_regime()
        volatility = self.regime_detector.get_volatility_forecast()
        
        # 判断趋势方向
        if self.regime_detector._price_history:
            returns = np.diff(self.regime_detector._price_history[-20:])
            trend_score = np.sum(returns)
            if trend_score > 0:
                trend = TrendDirection.UP
            elif trend_score < 0:
                trend = TrendDirection.DOWN
            else:
                trend = TrendDirection.NEUTRAL
        else:
            trend = TrendDirection.NEUTRAL
            
        # 流动性状态（简化）
        if volatility > 0.30:
            liquidity = LiquidityState.LOW
        elif volatility < 0.15:
            liquidity = LiquidityState.HIGH
        else:
            liquidity = LiquidityState.NORMAL
            
        return MarketState(
            regime=regime,
            volatility=volatility,
            trend=trend,
            liquidity=liquidity,
            timestamp=datetime.now(),
        )
        
    def decide(self, market_state: MarketState) -> MetaDecision:
        """
        做出决策
        
        Args:
            market_state: 市场状态
            
        Returns:
            MetaDecision
        """
        # 1. 确定风险偏好
        if self._current_drawdown > 0.05:
            risk_appetite = RiskLevel.CONSERVATIVE
            target_mode = SystemMode.SURVIVAL
        elif self._current_drawdown > 0.10:
            risk_appetite = RiskLevel.EXTREME
            target_mode = SystemMode.CRISIS
        elif market_state.regime == MarketRegime.HIGH_VOL:
            risk_appetite = RiskLevel.MODERATE
            target_mode = SystemMode.GROWTH
        else:
            risk_appetite = RiskLevel.AGGRESSIVE
            target_mode = SystemMode.GROWTH
            
        # 2. 选择策略
        strategies, weights = self.strategy_selector.select_strategies(
            regime=market_state.regime,
            confidence=0.7,  # 简化
            current_drawdown=self._current_drawdown,
        )
        
        # 3. 计算目标敞口
        if risk_appetite == RiskLevel.CONSERVATIVE:
            target_exposure = 0.3
        elif risk_appetite == RiskLevel.MODERATE:
            target_exposure = 0.6
        elif risk_appetite == RiskLevel.AGGRESSIVE:
            target_exposure = 0.9
        else:  # EXTREME - 实际上应该是减仓
            target_exposure = 0.1
            
        decision = MetaDecision(
            selected_strategies=[s.value for s in strategies],
            strategy_weights=weights,
            risk_appetite=risk_appetite,
            target_exposure=target_exposure,
            mode=target_mode,
            timestamp=datetime.now(),
        )
        
        self._last_decision = decision
        
        # 触发回调
        for cb in self._decision_callbacks:
            try:
                cb(decision)
            except Exception as e:
                logger.error(f"Decision callback error: {e}")
                
        return decision
        
    def get_latest_decision(self) -> Optional[MetaDecision]:
        """获取最新决策"""
        return self._last_decision
