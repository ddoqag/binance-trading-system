"""
regime_detector.py - Market Regime Detection using HMM and GARCH.

Production级实现：
- 异步非阻塞 HMM 训练（ProcessPool）
- 双缓冲模型切换（原子替换）
- fit 节流 + coalescing（防爆）
- fallback 降级机制
- < 1ms 检测延迟

Author: P10 Trading System
"""

import asyncio
import numpy as np
import time
import warnings
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple, Deque

# Suppress sklearn warnings
warnings.filterwarnings('ignore', category=FutureWarning)

# Optional imports - will use fallback if not available
try:
    from hmmlearn.hmm import GaussianHMM
    HMMLEARN_AVAILABLE = True
except ImportError:
    HMMLEARN_AVAILABLE = False
    GaussianHMM = None

try:
    from .features.regime_features import RegimeFeatureExtractor, RegimeFeatures
except ImportError:
    from features.regime_features import RegimeFeatureExtractor, RegimeFeatures


class Regime(Enum):
    """Market regime types."""
    TRENDING = "trending"
    MEAN_REVERTING = "mean_reverting"
    HIGH_VOLATILITY = "high_volatility"
    UNKNOWN = "unknown"


@dataclass
class RegimePrediction:
    """Output of regime detection."""
    regime: Regime
    confidence: float
    probabilities: Dict[Regime, float]
    volatility_forecast: float
    timestamp: float
    latency_ms: float = 0.0  # 新增：检测延迟


# ============================================================================
# 子进程执行函数（必须是顶层函数！）
# ============================================================================

def _train_hmm_worker(prices: np.ndarray, n_states: int = 3) -> Optional[Tuple]:
    """
    在子进程中训练 HMM。
    
    ⚠️ 关键：不能使用 self，所有参数通过函数参数传递
    返回：(model, state_to_regime_map) 或 None
    
    Args:
        prices: 价格历史数组
        n_states: HMM 隐藏状态数
    
    Returns:
        (trained_model, state_mapping) 或 None（失败时）
    """
    try:
        if not HMMLEARN_AVAILABLE or len(prices) < 50:
            return None
        
        # 计算对数收益率
        log_returns = np.diff(np.log(prices))
        log_returns = log_returns[np.isfinite(log_returns)]
        
        if len(log_returns) < 30:
            return None
        
        # 准备特征：returns 和 squared returns
        features = np.column_stack([log_returns, log_returns ** 2])
        
        # 训练 HMM
        model = GaussianHMM(
            n_components=n_states,
            covariance_type="full",
            n_iter=50,  # 减少迭代次数，加速训练
            random_state=42,
            init_params='stmc'
        )
        
        model.fit(features)
        
        # 构建 state 到 regime 的映射
        state_to_regime = {}
        for state in range(n_states):
            mean_return = model.means_[state][0]
            mean_vol_proxy = model.means_[state][1]
            
            # 基于收益和波动率分类
            if mean_vol_proxy > np.percentile(model.means_[:, 1], 66):
                state_to_regime[state] = Regime.HIGH_VOLATILITY
            elif np.abs(mean_return) > np.std(model.means_[:, 0]):
                state_to_regime[state] = Regime.TRENDING
            else:
                state_to_regime[state] = Regime.MEAN_REVERTING
        
        return (model, state_to_regime)
        
    except Exception as e:
        print(f"[HMM TRAIN ERROR] {e}")
        return None


# ============================================================================
# 主类：Production级 Regime Detector
# ============================================================================

class MarketRegimeDetector:
    """
    Production级市场状态检测器。
    
    特性：
    - 异步非阻塞 HMM 训练（后台进程池）
    - 双缓冲模型切换（原子替换，无锁）
    - fit 节流（避免任务堆积）
    - fallback 降级机制
    - < 1ms 检测延迟
    
    Usage:
        detector = MarketRegimeDetector()
        
        # 冷启动：同步训练初始模型
        detector.fit(initial_prices)
        
        # 主循环：异步检测（不阻塞）
        async for price in market_stream:
            pred = await detector.detect_async(price)
            print(f"Regime: {pred.regime}, Latency: {pred.latency_ms:.2f}ms")
    """

    def __init__(
        self,
        n_states: int = 3,
        feature_window: int = 100,
        fit_interval_ticks: int = 1000,
        max_price_history: int = 5000
    ):
        """
        初始化检测器。
        
        Args:
            n_states: HMM 隐藏状态数
            feature_window: 特征提取窗口
            fit_interval_ticks: 每 N 个 tick 触发后台训练
            max_price_history: 价格历史最大长度
        """
        self.n_states = n_states
        self.feature_window = feature_window
        self._fit_interval = fit_interval_ticks
        
        # Data storage
        self.price_history: Deque[float] = deque(maxlen=max_price_history)

        # Feature extractor
        self.feature_extractor = RegimeFeatureExtractor(
            window=feature_window,
            min_samples=30
        )

        # Model double buffering
        self._active_model: Optional[GaussianHMM] = None
        self._state_to_regime: Dict[int, Regime] = {}

        # Async control
        self._executor = ProcessPoolExecutor(max_workers=1)
        self._fit_task: Optional[asyncio.Task] = None
        self._fit_in_progress = False
        self._tick_count = 0

        # GARCH parameters
        self.garch_omega = 0.000001
        self.garch_alpha = 0.1
        self.garch_beta = 0.85
        self.current_variance = 0.0001
        
        # Fallback state
        self._last_regime = Regime.UNKNOWN
        self._fallback_thresholds = {'high_vol': 0.5, 'trend': 0.001}
        self._use_fallback = not HMMLEARN_AVAILABLE

        # Performance tracking
        self.detection_times: Deque[float] = deque(maxlen=1000)
        self.regime_history: Deque[Regime] = deque(maxlen=1000)

    # Fast path: async detection (for main loop)

    async def detect_async(self, price: float) -> RegimePrediction:
        """
        异步检测当前市场状态（非阻塞，< 1ms）。
        
        这是主循环应该使用的方法。它会：
        1. 快速提取特征
        2. 使用当前模型预测（仅 predict，无训练）
        3. 触发后台训练（每 N tick，非阻塞）
        
        Args:
            price: 当前价格
        
        Returns:
            RegimePrediction 包含状态、置信度、延迟
        """
        start = time.perf_counter()
        
        # 1. 更新价格历史
        self.price_history.append(price)
        
        # 2. 特征提取（轻量，同步）
        features = self.feature_extractor.update(price)
        if features is None:
            return self._create_unknown_prediction(start)
        
        # 3. 触发后台训练（带节流）
        self._tick_count += 1
        if self._tick_count % self._fit_interval == 0:
            self._trigger_background_fit()
        
        # 4. 快路径：仅预测
        prediction = self._predict_fast(features)
        
        # 5. 记录性能
        latency = (time.perf_counter() - start) * 1000
        self.detection_times.append(latency)
        prediction.latency_ms = latency
        
        return prediction

    def _predict_fast(self, features) -> RegimePrediction:
        """
        极速预测路径（仅 decode，无训练）。
        
        使用当前激活的模型进行预测，如果模型未就绪则使用 fallback。
        """
        if self._use_fallback or self._active_model is None:
            return self._detect_fallback(features)
        
        try:
            # 准备观测值
            obs = np.array([[features.mean_return, features.volatility ** 2]])
            
            # Viterbi 解码（极速）
            log_prob, states = self._active_model.decode(obs, algorithm="viterbi")
            state = states[0]
            
            # 获取状态概率
            state_probs = self._get_state_probabilities(obs[0])
            
            # 映射到 regime
            regime = self._state_to_regime.get(state, Regime.UNKNOWN)
            confidence = float(np.max(state_probs))
            
            # 构建概率分布
            regime_probs = {r: 0.0 for r in Regime if r != Regime.UNKNOWN}
            for s, prob in enumerate(state_probs):
                r = self._state_to_regime.get(s, Regime.UNKNOWN)
                if r != Regime.UNKNOWN:
                    regime_probs[r] += prob
            
            # 更新 GARCH 波动率预测
            vol_forecast = self._update_garch(features)
            
            self._last_regime = regime
            
            return RegimePrediction(
                regime=regime,
                confidence=confidence,
                probabilities=regime_probs,
                volatility_forecast=vol_forecast,
                timestamp=time.time(),
                latency_ms=0.0
            )
            
        except Exception as e:
            print(f"[REGIME] Fast predict failed: {e}")
            return self._detect_fallback(features)

    # Background training control

    def _trigger_background_fit(self):
        """
        触发后台 HMM 训练（带节流保护）。
        
        如果已有训练在进行中，则跳过（避免任务堆积）。
        如果 HMM 不可用，直接跳过。
        """
        if self._fit_in_progress:
            return
        
        # HMM 不可用时，跳过训练
        if not HMMLEARN_AVAILABLE or self._use_fallback:
            return
        
        if len(self.price_history) < self.feature_window * 2:
            return
        
        try:
            loop = asyncio.get_event_loop()
            prices = np.array(self.price_history, dtype=np.float64)
            
            self._fit_in_progress = True
            self._fit_task = loop.create_task(
                self._async_fit(prices)
            )
        except Exception as e:
            print(f"[REGIME] Failed to trigger background fit: {e}")
            self._fit_in_progress = False

    async def _async_fit(self, prices: np.ndarray, timeout: Optional[float] = None):
        """
        异步 HMM 训练（在进程池中执行）。

        训练完成后，原子替换当前模型。
        包含完整的异常捕获，防止子进程崩溃导致主进程无感知。

        Args:
            prices: 价格历史数组
            timeout: 可选超时时间（秒），None表示无超时
        """
        try:
            loop = asyncio.get_running_loop()

            # 在进程池中执行同步训练
            future = loop.run_in_executor(
                self._executor,
                _train_hmm_worker,
                prices,
                self.n_states
            )

            # 等待结果，带可选超时
            try:
                if timeout is not None:
                    result = await asyncio.wait_for(future, timeout=timeout)
                else:
                    result = await future
            except asyncio.TimeoutError:
                print(f"[REGIME] Training timeout after {timeout}s")
                if self._fit_task and not self._fit_task.done():
                    self._fit_task.cancel()
                    try:
                        await self._fit_task
                    except asyncio.CancelledError:
                        pass
                return
            except Exception as e:
                print(f"[REGIME] Subprocess training failed: {type(e).__name__}: {e}")
                result = None

            # 主进程接收模型
            if result is not None:
                model, state_map = result
                self._active_model = model
                self._state_to_regime = state_map
                print(f"[REGIME] Model updated: {state_map}")
            else:
                print("[REGIME] Model update skipped (training returned None)")

        except Exception as e:
            print(f"[REGIME] Background fit error: {type(e).__name__}: {e}")

        finally:
            self._fit_in_progress = False

    # Sync API (backward compatibility)

    def detect(self, price: float) -> RegimePrediction:
        """
        同步检测（兼容旧代码）。
        
        自动创建临时事件循环运行异步版本。
        新代码建议直接使用 detect_async。
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return asyncio.run_coroutine_threadsafe(
                    self.detect_async(price), loop
                ).result(timeout=0.01)
            else:
                return loop.run_until_complete(self.detect_async(price))
        except RuntimeError:
            return asyncio.run(self.detect_async(price))

    def fit(self, prices: np.ndarray) -> bool:
        """
        同步训练（冷启动使用）。

        在初始化时调用一次，确保首次有可用模型。
        如果 HMM 不可用，使用 fallback 模式（返回 True）。
        """
        if len(prices) < self.feature_window * 2:
            print(f"[REGIME] Insufficient data: {len(prices)}")
            self._use_fallback = True
            return True

        if not HMMLEARN_AVAILABLE:
            print("[REGIME] HMM not available, using fallback mode")
            self._use_fallback = True
            return True

        result = _train_hmm_worker(prices, self.n_states)
        if result:
            self._active_model, self._state_to_regime = result
            print("[REGIME] HMM model trained successfully")
            return True
        else:
            print("[REGIME] HMM training failed, using fallback")
            self._use_fallback = True
            return True

    # Fallback detection

    def _detect_fallback(self, features) -> RegimePrediction:
        """
        启发式降级检测（当 HMM 不可用时）。
        
        使用简单阈值判断 regime，确保系统始终可用。
        """
        annualized_vol = features.volatility * np.sqrt(252 * 24 * 60)
        
        if annualized_vol > self._fallback_thresholds['high_vol']:
            regime = Regime.HIGH_VOLATILITY
            confidence = min(annualized_vol / (self._fallback_thresholds['high_vol'] * 2), 1.0)
        elif np.abs(features.price_momentum) > 0.5 and features.autocorr_1 > 0.1:
            regime = Regime.TRENDING
            confidence = min(np.abs(features.price_momentum), 1.0)
        else:
            regime = Regime.MEAN_REVERTING
            confidence = 0.5 + 0.5 * np.abs(features.autocorr_1)
        
        probs = {r: 0.1 for r in Regime if r != Regime.UNKNOWN}
        probs[regime] = confidence
        total = sum(probs.values())
        probs = {k: v / total for k, v in probs.items()}
        
        self._last_regime = regime
        
        return RegimePrediction(
            regime=regime,
            confidence=confidence,
            probabilities=probs,
            volatility_forecast=annualized_vol,
            timestamp=time.time(),
            latency_ms=0.0
        )

    def _create_unknown_prediction(self, start_time: float) -> RegimePrediction:
        """创建未知状态预测（数据不足时）。"""
        latency = (time.perf_counter() - start_time) * 1000
        return RegimePrediction(
            regime=Regime.UNKNOWN,
            confidence=0.0,
            probabilities={r: 0.33 for r in Regime if r != Regime.UNKNOWN},
            volatility_forecast=np.sqrt(self.current_variance),
            timestamp=time.time(),
            latency_ms=latency
        )

    # Helper methods

    def _get_state_probabilities(self, obs: np.ndarray) -> np.ndarray:
        """计算隐藏状态概率分布。"""
        if self._active_model is None:
            return np.ones(self.n_states) / self.n_states
        
        log_probs = np.zeros(self.n_states)
        for state in range(self.n_states):
            mean = self._active_model.means_[state]
            cov = self._active_model.covars_[state]
            diff = obs - mean
            
            try:
                log_prob = -0.5 * (
                    np.log(np.linalg.det(cov)) +
                    diff @ np.linalg.inv(cov) @ diff.T +
                    len(obs) * np.log(2 * np.pi)
                )
                log_probs[state] = log_prob
            except np.linalg.LinAlgError:
                log_probs[state] = -1e10
        
        log_probs -= np.max(log_probs)
        probs = np.exp(log_probs)
        probs /= np.sum(probs)
        return probs

    def _update_garch(self, features) -> float:
        """更新 GARCH(1,1) 波动率预测。"""
        ret_sq = features.mean_return ** 2
        self.current_variance = (
            self.garch_omega +
            self.garch_alpha * ret_sq +
            self.garch_beta * self.current_variance
        )
        return float(np.sqrt(self.current_variance * 252 * 24 * 60))

    def get_avg_latency_ms(self) -> float:
        """获取平均检测延迟（毫秒）。"""
        if not self.detection_times:
            return 0.0
        return np.mean(self.detection_times)

    def shutdown(self):
        """
        优雅关闭，释放资源。

        在程序退出前调用，避免僵尸进程。
        """
        if self._fit_task and not self._fit_task.done():
            self._fit_task.cancel()
        self._executor.shutdown(wait=True)
        print("[REGIME] Shutdown complete")

    def __del__(self):
        """析构时自动清理资源。"""
        try:
            if hasattr(self, '_executor') and self._executor:
                self._executor.shutdown(wait=False)
        except Exception:
            pass
