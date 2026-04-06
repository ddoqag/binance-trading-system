"""
Hedge Fund OS - Meta Brain Enhanced (增强版决策大脑)

集成现有的 meta_agent.py 和 regime_detector.py 组件
提供更强大的市场状态检测和策略选择能力
"""

import time
import logging
import asyncio
from typing import Dict, List, Optional, Callable, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from collections import deque

import numpy as np

# 导入 Hedge Fund OS 类型
from .hf_types import (
    SystemMode, RiskLevel, MarketRegime, MarketState, MetaDecision,
    TrendDirection, LiquidityState, PerformanceRecord
)
from .risk_kernel import RiskThresholds

# 尝试导入现有的 regime_detector 和 meta_agent
try:
    import sys
    sys.path.insert(0, 'D:/binance/new/brain_py')
    from regime_detector import MarketRegimeDetector, Regime, RegimePrediction
    from meta_agent import MetaAgent, MetaAgentConfig, StrategyType, BaseStrategy
    EXISTING_COMPONENTS_AVAILABLE = True
except ImportError as e:
    logging.warning(f"[MetaBrainEnhanced] Could not import existing components: {e}")
    EXISTING_COMPONENTS_AVAILABLE = False
    MarketRegimeDetector = None
    MetaAgent = None


logger = logging.getLogger(__name__)


class RegimeMapper:
    """
    将 regime_detector.Regime 映射到 hf_types.MarketRegime
    """

    @staticmethod
    def to_market_regime(regime: Regime) -> MarketRegime:
        """将 Regime 转换为 MarketRegime"""
        mapping = {
            Regime.TRENDING: MarketRegime.TRENDING,
            Regime.MEAN_REVERTING: MarketRegime.RANGE_BOUND,
            Regime.HIGH_VOLATILITY: MarketRegime.HIGH_VOL,
            Regime.UNKNOWN: MarketRegime.RANGE_BOUND,
        }
        return mapping.get(regime, MarketRegime.RANGE_BOUND)

    @staticmethod
    def from_market_regime(regime: MarketRegime) -> Regime:
        """将 MarketRegime 转换为 Regime"""
        mapping = {
            MarketRegime.TRENDING: Regime.TRENDING,
            MarketRegime.RANGE_BOUND: Regime.MEAN_REVERTING,
            MarketRegime.HIGH_VOL: Regime.HIGH_VOLATILITY,
            MarketRegime.LOW_VOL: Regime.MEAN_REVERTING,
            MarketRegime.CRASH: Regime.HIGH_VOLATILITY,
        }
        return mapping.get(regime, Regime.UNKNOWN)


@dataclass
class EnhancedMetaBrainConfig:
    """增强版 Meta Brain 配置"""

    # 状态检测参数
    lookback_window: int = 100
    volatility_threshold_low: float = 0.15
    volatility_threshold_high: float = 0.30

    # 策略选择参数
    min_strategy_score: float = 0.3
    max_active_strategies: int = 3
    strategy_switch_cooldown: float = 60.0

    # 风险偏好映射
    conservative_drawdown_threshold: float = 0.03
    aggressive_drawdown_threshold: float = 0.10

    # 集成配置
    use_production_regime_detector: bool = True  # 使用 production 级 regime_detector
    use_meta_agent: bool = True  # 使用 meta_agent 进行策略选择
    async_detection: bool = True  # 使用异步检测

    # HMM 参数 (用于 regime_detector)
    hmm_n_states: int = 3
    hmm_feature_window: int = 100
    hmm_fit_interval: int = 1000


class EnhancedRegimeDetector:
    """
    增强版市场状态检测器

    包装 production 级的 MarketRegimeDetector，提供 Hedge Fund OS 兼容接口
    """

    def __init__(self, config: EnhancedMetaBrainConfig):
        self.config = config
        self._price_history: deque = deque(maxlen=config.lookback_window)
        self._volatility_history: deque = deque(maxlen=100)

        # 初始化 production 级检测器
        self._prod_detector: Optional[MarketRegimeDetector] = None
        if EXISTING_COMPONENTS_AVAILABLE and config.use_production_regime_detector:
            try:
                self._prod_detector = MarketRegimeDetector(
                    n_states=config.hmm_n_states,
                    feature_window=config.hmm_feature_window,
                    fit_interval_ticks=config.hmm_fit_interval,
                )
                logger.info("[EnhancedRegimeDetector] Production detector initialized")
            except Exception as e:
                logger.warning(f"[EnhancedRegimeDetector] Failed to init production detector: {e}")

        self._last_prediction: Optional[RegimePrediction] = None
        self._detection_count = 0

    def update(self, price: float) -> None:
        """更新价格数据"""
        self._price_history.append(price)

        # 计算滚动波动率
        if len(self._price_history) >= 20:
            returns = np.diff(np.log(list(self._price_history)[-20:]))
            vol = np.std(returns) * np.sqrt(252)
            self._volatility_history.append(vol)

        # 更新 production 检测器
        if self._prod_detector is not None:
            try:
                if self.config.async_detection and asyncio.get_event_loop().is_running():
                    # 异步更新
                    asyncio.create_task(self._async_update(price))
                else:
                    # 同步更新
                    self._last_prediction = self._prod_detector.detect(price)
            except Exception as e:
                logger.debug(f"[EnhancedRegimeDetector] Production detect error: {e}")

    async def _async_update(self, price: float) -> None:
        """异步更新 production 检测器"""
        if self._prod_detector is not None:
            try:
                self._last_prediction = await self._prod_detector.detect_async(price)
            except Exception as e:
                logger.debug(f"[EnhancedRegimeDetector] Async detect error: {e}")

    def detect_regime(self) -> Tuple[MarketRegime, float]:
        """
        检测市场状态

        Returns:
            (regime, confidence)
        """
        # 优先使用 production 检测器的结果
        if self._last_prediction is not None:
            regime = RegimeMapper.to_market_regime(self._last_prediction.regime)
            confidence = self._last_prediction.confidence
            return regime, confidence

        # 回退到简化版检测逻辑
        return self._detect_fallback()

    def _detect_fallback(self) -> Tuple[MarketRegime, float]:
        """简化版检测逻辑"""
        if len(self._price_history) < 20:
            return MarketRegime.RANGE_BOUND, 0.5

        # 计算趋势
        prices = list(self._price_history)
        returns = np.diff(prices)
        trend_score = np.sum(returns) / (np.std(returns) * np.sqrt(len(returns)) + 1e-6)

        # 判断波动率状态
        if self._volatility_history:
            current_vol = self._volatility_history[-1]
            if current_vol > self.config.volatility_threshold_high:
                if abs(trend_score) > 2.0:
                    return MarketRegime.TRENDING, min(abs(trend_score) / 3.0, 1.0)
                return MarketRegime.HIGH_VOL, 0.7
            elif current_vol < self.config.volatility_threshold_low:
                if abs(trend_score) > 1.5:
                    return MarketRegime.TRENDING, min(abs(trend_score) / 2.0, 0.9)
                return MarketRegime.LOW_VOL, 0.6

        return MarketRegime.RANGE_BOUND, 0.6

    def get_volatility_forecast(self) -> float:
        """预测未来波动率"""
        # 优先使用 production 检测器的 GARCH 预测
        if self._last_prediction is not None:
            return self._last_prediction.volatility_forecast

        # 回退到指数加权平均
        if len(self._volatility_history) < 10:
            return 0.20

        vols = list(self._volatility_history)
        weights = np.exp(np.linspace(-1, 0, len(vols)))
        weights /= weights.sum()
        return float(np.dot(vols, weights))

    def get_regime_probabilities(self) -> Dict[MarketRegime, float]:
        """获取各市场状态的概率分布"""
        if self._last_prediction is not None and self._last_prediction.probabilities:
            return {
                RegimeMapper.to_market_regime(r): p
                for r, p in self._last_prediction.probabilities.items()
            }

        # 回退到当前状态
        regime, confidence = self.detect_regime()
        return {
            MarketRegime.TRENDING: confidence if regime == MarketRegime.TRENDING else (1 - confidence) / 3,
            MarketRegime.RANGE_BOUND: confidence if regime == MarketRegime.RANGE_BOUND else (1 - confidence) / 3,
            MarketRegime.HIGH_VOL: confidence if regime == MarketRegime.HIGH_VOL else (1 - confidence) / 3,
            MarketRegime.LOW_VOL: confidence if regime == MarketRegime.LOW_VOL else (1 - confidence) / 3,
        }

    def fit(self, prices: np.ndarray) -> bool:
        """冷启动训练"""
        if self._prod_detector is not None and len(prices) >= self.config.hmm_feature_window * 2:
            try:
                result = self._prod_detector.fit(prices)
                if result:
                    return True
                # Production fit 失败，回退到简化模式
            except Exception as e:
                logger.warning(f"[EnhancedRegimeDetector] Fit error: {e}")

        # 填充历史数据（简化模式或回退）
        self._price_history.clear()
        for p in prices:
            self._price_history.append(float(p))
        return True

    def get_detection_stats(self) -> Dict[str, Any]:
        """获取检测统计信息"""
        stats = {
            'detection_count': self._detection_count,
            'history_length': len(self._price_history),
        }

        if self._prod_detector is not None:
            try:
                stats['production'] = self._prod_detector.get_performance_stats()
            except Exception:
                pass

        return stats


class EnhancedStrategySelector:
    """
    增强版策略选择器

    集成 meta_agent 的策略选择逻辑
    """

    def __init__(self, config: EnhancedMetaBrainConfig):
        self.config = config
        self._strategy_scores: Dict[str, float] = {}
        self._last_switch_time = 0.0
        self._strategy_performance: Dict[str, deque] = {}

        # 策略-状态适应性矩阵
        self._regime_suitability = self._init_suitability_matrix()

        # 初始化 meta_agent (如果可用)
        self._meta_agent: Optional[MetaAgent] = None
        if EXISTING_COMPONENTS_AVAILABLE and config.use_meta_agent:
            try:
                from brain_py.agent_registry import AgentRegistry
                from brain_py.regime_detector import MarketRegimeDetector as RegDet

                registry = AgentRegistry()
                regime_det = RegDet()
                meta_config = MetaAgentConfig(
                    min_regime_confidence=0.6,
                    strategy_switch_cooldown=config.strategy_switch_cooldown,
                    max_strategies_active=config.max_active_strategies,
                )
                self._meta_agent = MetaAgent(registry, regime_det, meta_config)
                logger.info("[EnhancedStrategySelector] MetaAgent initialized")
            except Exception as e:
                logger.warning(f"[EnhancedStrategySelector] Failed to init MetaAgent: {e}")

    def _init_suitability_matrix(self) -> Dict[str, Dict[MarketRegime, float]]:
        """初始化策略-状态适应性矩阵"""
        return {
            'trend_following': {
                MarketRegime.TRENDING: 0.9,
                MarketRegime.HIGH_VOL: 0.6,
                MarketRegime.RANGE_BOUND: 0.3,
                MarketRegime.LOW_VOL: 0.7,
            },
            'mean_reversion': {
                MarketRegime.TRENDING: 0.2,
                MarketRegime.HIGH_VOL: 0.4,
                MarketRegime.RANGE_BOUND: 0.9,
                MarketRegime.LOW_VOL: 0.8,
            },
            'momentum': {
                MarketRegime.TRENDING: 0.8,
                MarketRegime.HIGH_VOL: 0.5,
                MarketRegime.RANGE_BOUND: 0.4,
                MarketRegime.LOW_VOL: 0.6,
            },
            'volatility': {
                MarketRegime.TRENDING: 0.3,
                MarketRegime.HIGH_VOL: 0.9,
                MarketRegime.RANGE_BOUND: 0.5,
                MarketRegime.LOW_VOL: 0.2,
            },
            'breakout': {
                MarketRegime.TRENDING: 0.7,
                MarketRegime.HIGH_VOL: 0.7,
                MarketRegime.RANGE_BOUND: 0.6,
                MarketRegime.LOW_VOL: 0.4,
            },
            'ml_ensemble': {
                MarketRegime.TRENDING: 0.75,
                MarketRegime.HIGH_VOL: 0.55,
                MarketRegime.RANGE_BOUND: 0.65,
                MarketRegime.LOW_VOL: 0.70,
            },
        }

    def can_switch(self) -> bool:
        """检查是否满足切换冷却期"""
        elapsed = time.time() - self._last_switch_time
        return elapsed >= self.config.strategy_switch_cooldown

    def update_strategy_performance(self, strategy: str, pnl: float) -> None:
        """更新策略表现历史"""
        if strategy not in self._strategy_performance:
            self._strategy_performance[strategy] = deque(maxlen=100)
        self._strategy_performance[strategy].append(pnl)

    def get_strategy_sharpe(self, strategy: str) -> float:
        """计算策略的夏普比率"""
        if strategy not in self._strategy_performance:
            return 0.0

        pnls = list(self._strategy_performance[strategy])
        if len(pnls) < 10:
            return 0.0

        returns = np.array(pnls)
        if np.std(returns) == 0:
            return 0.0

        return np.mean(returns) / (np.std(returns) + 1e-6) * np.sqrt(252)

    def select_strategies(
        self,
        regime: MarketRegime,
        confidence: float,
        current_drawdown: float,
        available_strategies: Optional[List[str]] = None
    ) -> Tuple[List[str], Dict[str, float]]:
        """
        选择策略组合

        Returns:
            (selected_strategies, strategy_weights)
        """
        if not self.can_switch():
            return list(self._strategy_scores.keys()), self._get_weights_from_scores()

        # 确定可用策略
        strategies = available_strategies or list(self._regime_suitability.keys())

        # 根据回撤调整风险偏好
        if current_drawdown > self.config.conservative_drawdown_threshold:
            risk_adjustment = 0.5
        elif current_drawdown < self.config.aggressive_drawdown_threshold:
            risk_adjustment = 1.0
        else:
            risk_adjustment = 0.8

        # 计算每个策略的综合得分
        scores = {}
        for strategy in strategies:
            if strategy not in self._regime_suitability:
                continue

            # 基础适应性得分
            base_score = self._regime_suitability[strategy].get(regime, 0.5)

            # 历史表现得分 (夏普比率归一化)
            sharpe = self.get_strategy_sharpe(strategy)
            performance_score = min(max(sharpe / 3.0, -0.5), 0.5) + 0.5  # 归一化到 [0, 1]

            # 综合得分
            adjusted_score = (0.6 * base_score + 0.3 * performance_score + 0.1 * confidence) * risk_adjustment
            scores[strategy] = adjusted_score

        # 排序并选择 top N
        sorted_strategies = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        selected = [s for s, score in sorted_strategies[:self.config.max_active_strategies]
                   if score >= self.config.min_strategy_score]

        if not selected:
            # 默认选择 breakout
            selected = ['breakout']

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
            n = len(self._strategy_scores)
            return {s: 1.0/n for s in self._strategy_scores}

        return {s: score/total for s, score in self._strategy_scores.items()}


class MetaBrainEnhanced:
    """
    增强版 Meta Brain - 决策大脑

    集成现有的 meta_agent.py 和 regime_detector.py 组件
    提供更强大的市场状态感知和策略决策能力
    """

    def __init__(self, config: Optional[EnhancedMetaBrainConfig] = None):
        self.config = config or EnhancedMetaBrainConfig()
        self.regime_detector = EnhancedRegimeDetector(self.config)
        self.strategy_selector = EnhancedStrategySelector(self.config)

        # 状态
        self._current_price: Optional[float] = None
        self._current_drawdown: float = 0.0
        self._last_decision: Optional[MetaDecision] = None
        self._decision_history: deque = deque(maxlen=1000)

        # 回调
        self._decision_callbacks: List[Callable[[MetaDecision], None]] = []

        # 统计
        self._perceive_count = 0
        self._decide_count = 0

        logger.info("[MetaBrainEnhanced] Initialized")

    def register_decision_callback(self, callback: Callable[[MetaDecision], None]) -> None:
        """注册决策回调"""
        self._decision_callbacks.append(callback)

    def unregister_decision_callback(self, callback: Callable[[MetaDecision], None]) -> None:
        """注销决策回调"""
        if callback in self._decision_callbacks:
            self._decision_callbacks.remove(callback)

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

    def fit(self, prices: np.ndarray) -> bool:
        """冷启动训练"""
        return self.regime_detector.fit(prices)

    def perceive(self, **kwargs) -> MarketState:
        """
        感知市场状态

        Args:
            **kwargs: 可选的额外参数
                - correlation_matrix: 资产相关性矩阵
                - macro_signals: 宏观信号字典

        Returns:
            MarketState
        """
        self._perceive_count += 1

        regime, confidence = self.regime_detector.detect_regime()
        volatility = self.regime_detector.get_volatility_forecast()

        # 判断趋势方向
        if hasattr(self.regime_detector, '_price_history'):
            prices = list(self.regime_detector._price_history)
            if len(prices) >= 20:
                returns = np.diff(prices[-20:])
                trend_score = np.sum(returns)
                if trend_score > 0:
                    trend = TrendDirection.UP
                elif trend_score < 0:
                    trend = TrendDirection.DOWN
                else:
                    trend = TrendDirection.NEUTRAL
            else:
                trend = TrendDirection.NEUTRAL
        else:
            trend = TrendDirection.NEUTRAL

        # 流动性状态
        if volatility > 0.30:
            liquidity = LiquidityState.LOW
        elif volatility < 0.15:
            liquidity = LiquidityState.HIGH
        else:
            liquidity = LiquidityState.NORMAL

        # 获取概率分布
        probabilities = self.regime_detector.get_regime_probabilities()

        return MarketState(
            regime=regime,
            volatility=volatility,
            trend=trend,
            liquidity=liquidity,
            correlation_matrix=kwargs.get('correlation_matrix'),
            macro_signals=kwargs.get('macro_signals', {}),
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
        self._decide_count += 1

        # 1. 确定风险偏好和系统模式
        if self._current_drawdown > 0.10:
            risk_appetite = RiskLevel.EXTREME
            target_mode = SystemMode.CRISIS
        elif self._current_drawdown > 0.05:
            risk_appetite = RiskLevel.CONSERVATIVE
            target_mode = SystemMode.SURVIVAL
        elif market_state.regime == MarketRegime.HIGH_VOL:
            risk_appetite = RiskLevel.MODERATE
            target_mode = SystemMode.GROWTH
        elif market_state.regime == MarketRegime.TRENDING:
            risk_appetite = RiskLevel.AGGRESSIVE
            target_mode = SystemMode.GROWTH
        else:
            risk_appetite = RiskLevel.MODERATE
            target_mode = SystemMode.GROWTH

        # 2. 获取状态置信度
        probabilities = self.regime_detector.get_regime_probabilities()
        confidence = probabilities.get(market_state.regime, 0.5)

        # 3. 选择策略
        strategies, weights = self.strategy_selector.select_strategies(
            regime=market_state.regime,
            confidence=confidence,
            current_drawdown=self._current_drawdown,
        )

        # 4. 计算目标敞口
        exposure_map = {
            RiskLevel.CONSERVATIVE: 0.3,
            RiskLevel.MODERATE: 0.6,
            RiskLevel.AGGRESSIVE: 0.9,
            RiskLevel.EXTREME: 0.1,  # 危机时减仓
        }
        target_exposure = exposure_map.get(risk_appetite, 0.5)

        # 根据波动率调整敞口
        if market_state.volatility > 0.40:
            target_exposure *= 0.5
        elif market_state.volatility < 0.10:
            target_exposure *= 1.1

        target_exposure = min(target_exposure, 1.0)

        decision = MetaDecision(
            selected_strategies=strategies,
            strategy_weights=weights,
            risk_appetite=risk_appetite,
            target_exposure=target_exposure,
            mode=target_mode,
            timestamp=datetime.now(),
        )

        self._last_decision = decision
        self._decision_history.append((time.time(), decision))

        # 触发回调
        for cb in self._decision_callbacks:
            try:
                cb(decision)
            except Exception as e:
                logger.error(f"[MetaBrainEnhanced] Decision callback error: {e}")

        return decision

    def get_latest_decision(self) -> Optional[MetaDecision]:
        """获取最新决策"""
        return self._last_decision

    def get_decision_history(self, n: int = 100) -> List[Tuple[float, MetaDecision]]:
        """获取决策历史"""
        return list(self._decision_history)[-n:]

    def update_strategy_performance(self, strategy: str, pnl: float) -> None:
        """更新策略表现"""
        self.strategy_selector.update_strategy_performance(strategy, pnl)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            'perceive_count': self._perceive_count,
            'decide_count': self._decide_count,
            'current_drawdown': self._current_drawdown,
            'regime_detector': self.regime_detector.get_detection_stats(),
            'strategy_sharpes': {
                s: self.strategy_selector.get_strategy_sharpe(s)
                for s in self.strategy_selector._strategy_performance.keys()
            },
        }

    def reset(self) -> None:
        """重置状态"""
        self._current_price = None
        self._current_drawdown = 0.0
        self._last_decision = None
        self._decision_history.clear()
        self._perceive_count = 0
        self._decide_count = 0
        self.strategy_selector._strategy_scores.clear()
        self.strategy_selector._strategy_performance.clear()


# 兼容旧接口的别名
MetaBrain = MetaBrainEnhanced
