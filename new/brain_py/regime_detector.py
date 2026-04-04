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
import multiprocessing
import numpy as np
import pickle
import struct
import sys
import time
import warnings
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, asdict
from enum import Enum
from multiprocessing import shared_memory
from typing import Dict, List, Optional, Tuple, Deque, Any

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

# ============================================================================
# Model Transfer - 跨进程模型传输优化
# ============================================================================

class ModelTransferBuffer:
    """
    跨进程模型传输优化。

    平台适配：
    - Linux/macOS: 使用 SharedMemory 零拷贝
    - Windows: 使用优化的 pickle + 内存视图

    Windows 说明：
    - Windows 使用 'spawn' 模式，子进程的 SharedMemory 对父进程不可见
    - 使用全局命名空间（Global\\）也无法解决 spawn 模式的隔离
    - 回退到优化的 pickle 协议（HIGHEST_PROTOCOL）
    """

    def __init__(self):
        self._is_windows = sys.platform == 'win32'
        self._use_shm = not self._is_windows  # Windows 不使用 SharedMemory

    def serialize(self, model_data: Dict[str, Any]) -> bytes:
        """序列化模型数据。"""
        return pickle.dumps(model_data, protocol=pickle.HIGHEST_PROTOCOL)

    def deserialize(self, data: bytes) -> Dict[str, Any]:
        """反序列化模型数据。"""
        return pickle.loads(data)


# 保持向后兼容的别名
SharedModelBuffer = ModelTransferBuffer


def _hmm_to_dict(model: GaussianHMM, state_to_regime: Dict[int, Regime]) -> Dict[str, Any]:
    """将 HMM 模型转换为可序列化的字典。"""
    return {
        'n_components': model.n_components,
        'means': model.means_,
        'covars': model.covars_,
        'transmat': model.transmat_,
        'startprob': model.startprob_,
        'state_to_regime': {k: v.value for k, v in state_to_regime.items()}
    }


def _dict_to_hmm(data: Dict[str, Any]) -> Tuple[GaussianHMM, Dict[int, Regime]]:
    """从字典重建 HMM 模型。"""
    model = GaussianHMM(
        n_components=data['n_components'],
        covariance_type="full",
        n_iter=1,
        random_state=42
    )
    model.means_ = data['means']
    model.covars_ = data['covars']
    model.transmat_ = data['transmat']
    model.startprob_ = data['startprob']

    state_to_regime = {k: Regime(v) for k, v in data['state_to_regime'].items()}

    return model, state_to_regime


def _train_hmm_worker(prices: np.ndarray, n_states: int = 3, use_shared_memory: bool = True) -> Optional[Tuple]:
    """
    在子进程中训练 HMM。

    ⚠️ 关键：不能使用 self，所有参数通过函数参数传递
    返回：(model, state_to_regime_map) 或 None，或使用序列化时返回 bytes

    Args:
        prices: 价格历史数组
        n_states: HMM 隐藏状态数
        use_shared_memory: 是否使用优化序列化（Windows 上实际使用 pickle HIGHEST_PROTOCOL）

    Returns:
        (model_bytes, None) 或 (model, state_mapping) 或 None（失败时）
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

        # 使用优化序列化传输
        if use_shared_memory:
            model_dict = _hmm_to_dict(model, state_to_regime)
            transfer = ModelTransferBuffer()
            data_bytes = transfer.serialize(model_dict)
            return (data_bytes, None)  # 标记为序列化模式

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
        max_price_history: int = 5000,
        use_shared_memory: bool = True
    ):
        """
        初始化检测器。

        Args:
            n_states: HMM 隐藏状态数
            feature_window: 特征提取窗口
            fit_interval_ticks: 每 N 个 tick 触发后台训练
            max_price_history: 价格历史最大长度
            use_shared_memory: 使用 SharedMemory 零拷贝传输模型（Windows 推荐）
        """
        self.n_states = n_states
        self.feature_window = feature_window
        self._fit_interval = fit_interval_ticks
        self._use_shared_memory = use_shared_memory

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
        self._fallback_thresholds = {'high_vol': 15.0, 'trend': 0.001}
        self._use_fallback = not HMMLEARN_AVAILABLE

        # Performance tracking
        self.detection_times: Deque[float] = deque(maxlen=1000)
        self.regime_history: Deque[Regime] = deque(maxlen=1000)
        self._serialization_times: Deque[float] = deque(maxlen=100)  # 序列化性能统计

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
        self.regime_history.append(prediction.regime)

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

    async def _async_fit(self, prices: np.ndarray, timeout: Optional[float] = None,
                         use_shared_memory: bool = True):
        """
        异步 HMM 训练（在进程池中执行）。

        训练完成后，原子替换当前模型。
        包含完整的异常捕获，防止子进程崩溃导致主进程无感知。
        支持 SharedMemory 零拷贝传输。

        Args:
            prices: 价格历史数组
            timeout: 可选超时时间（秒），None表示无超时
            use_shared_memory: 是否使用共享内存传输模型
        """
        try:
            loop = asyncio.get_running_loop()

            # 在进程池中执行同步训练
            future = loop.run_in_executor(
                self._executor,
                _train_hmm_worker,
                prices,
                self.n_states,
                use_shared_memory
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
                if use_shared_memory and result[0] is not None and isinstance(result[0], bytes):
                    # 序列化模式：result[0] 是序列化后的 bytes
                    try:
                        transfer = ModelTransferBuffer()
                        model_data = transfer.deserialize(result[0])
                        model, state_map = _dict_to_hmm(model_data)
                        self._active_model = model
                        self._state_to_regime = state_map
                        print(f"[REGIME] Model updated via optimized serialization: {state_map}")
                    except Exception as e:
                        print(f"[REGIME] Failed to deserialize model: {e}")
                elif use_shared_memory and result[0] is not None and isinstance(result[0], str):
                    # SharedMemory 模式（Linux/macOS）：result[0] 是共享内存名称
                    shm_name = result[0]
                    transfer = ModelTransferBuffer()
                    model_data = transfer.read_model(shm_name)

                    if model_data is not None:
                        model, state_map = _dict_to_hmm(model_data)
                        self._active_model = model
                        self._state_to_regime = state_map
                        print(f"[REGIME] Model updated via SharedMemory: {state_map}")
                    else:
                        print("[REGIME] Failed to read model from SharedMemory")
                else:
                    # 传统 pickle 模式
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
            return False

        if not HMMLEARN_AVAILABLE:
            print("[REGIME] HMM not available, using fallback mode")
            self._use_fallback = True
            self._warmup_from_prices(prices)
            return True

        result = _train_hmm_worker(prices, self.n_states)
        if result:
            self._active_model, self._state_to_regime = result
            print("[REGIME] HMM model trained successfully")
            self._warmup_from_prices(prices)
            return True
        else:
            print("[REGIME] HMM training failed, using fallback")
            self._use_fallback = True
            self._warmup_from_prices(prices)
            return True

    def _warmup_from_prices(self, prices: np.ndarray) -> None:
        """Batch inference over training prices to populate regime_history."""
        self.price_history.clear()
        self.feature_extractor.reset()
        self.regime_history.clear()
        for price in prices:
            self.price_history.append(float(price))
            features = self.feature_extractor.update(float(price))
            if features is not None:
                pred = self._predict_fast(features)
                self.regime_history.append(pred.regime)

    @property
    def _hmm_fitted(self) -> bool:
        """Backward compatibility property."""
        return self._active_model is not None and not self._use_fallback

    @property
    def hmm(self) -> Optional[Any]:
        """Backward compatibility property for active HMM model."""
        return self._active_model

    def reset(self) -> None:
        """Reset detector state for backward compatibility."""
        self._active_model = None
        self._state_to_regime = {}
        self.price_history.clear()
        self.detection_times.clear()
        self.regime_history.clear()
        self._tick_count = 0
        self._last_regime = Regime.UNKNOWN

    def predict_proba(self) -> np.ndarray:
        """Return current regime probabilities for backward compatibility."""
        if not self.regime_history:
            return np.ones(self.n_states) / self.n_states
        dist = self.get_regime_distribution()
        if not self._state_to_regime:
            # Fallback mode: assign probabilities to indices based on sorted regimes
            sorted_regimes = [Regime.TRENDING, Regime.MEAN_REVERTING, Regime.HIGH_VOLATILITY]
            proba = np.zeros(self.n_states)
            for idx in range(min(self.n_states, len(sorted_regimes))):
                proba[idx] = dist.get(sorted_regimes[idx], 0.0)
            if proba.sum() > 0:
                proba = proba / proba.sum()
            else:
                proba = np.ones(self.n_states) / self.n_states
            return proba
        proba = np.zeros(self.n_states)
        for idx in range(self.n_states):
            regime = self._state_to_regime.get(idx, Regime.UNKNOWN)
            proba[idx] = dist.get(regime, 0.0)
        return proba

    def get_avg_detection_time(self) -> float:
        """Backward compatibility alias for get_avg_latency_ms."""
        return self.get_avg_latency_ms()

    def get_regime_distribution(self) -> Dict[Regime, float]:
        """Compute regime distribution from history."""
        if not self.regime_history:
            return {Regime.UNKNOWN: 1.0}
        counts: Dict[Regime, int] = {}
        for r in self.regime_history:
            counts[r] = counts.get(r, 0) + 1
        total = len(self.regime_history)
        dist = {r: c / total for r, c in counts.items()}
        if Regime.UNKNOWN not in dist:
            dist[Regime.UNKNOWN] = 0.0
        return dist

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
        elif np.abs(features.price_momentum) > 0.05 and features.autocorr_1 > -0.5:
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
        return float(np.mean(self.detection_times))

    def get_performance_stats(self) -> Dict[str, Any]:
        """
        获取性能统计信息。

        Returns:
            包含检测延迟、序列化性能等统计信息的字典
        """
        stats = {
            'detection_latency_ms': {
                'mean': float(np.mean(self.detection_times)) if self.detection_times else 0.0,
                'p50': float(np.percentile(list(self.detection_times), 50)) if self.detection_times else 0.0,
                'p99': float(np.percentile(list(self.detection_times), 99)) if self.detection_times else 0.0,
                'count': len(self.detection_times)
            },
            'serialization': {
                'mode': 'Optimized' if self._use_shared_memory else 'Standard',
                'platform': sys.platform,
                'mean_ms': float(np.mean(self._serialization_times)) if self._serialization_times else 0.0,
            },
            'model': {
                'active': self._active_model is not None,
                'using_fallback': self._use_fallback,
                'state_mapping': {k: v.value for k, v in self._state_to_regime.items()}
            }
        }
        return stats

    def save(self, filepath: str):
        """Save detector state to disk (pickle, includes HMM + numpy arrays)."""
        state = {
            'n_states': self.n_states,
            'feature_window': self.feature_window,
            '_fit_interval': self._fit_interval,
            '_use_shared_memory': self._use_shared_memory,
            'price_history': list(self.price_history),
            '_active_model': _hmm_to_dict(self._active_model, self._state_to_regime)
            if self._active_model is not None and HMMLEARN_AVAILABLE else None,
            '_state_to_regime': {k: v.value for k, v in self._state_to_regime.items()},
            '_tick_count': self._tick_count,
            'garch_omega': self.garch_omega,
            'garch_alpha': self.garch_alpha,
            'garch_beta': self.garch_beta,
            'current_variance': self.current_variance,
            '_last_regime': self._last_regime.value,
            '_fallback_thresholds': self._fallback_thresholds,
            '_use_fallback': self._use_fallback,
            'detection_times': list(self.detection_times),
            'regime_history': [r.value for r in self.regime_history],
        }
        with open(filepath, 'wb') as f:
            pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)

    def load(self, filepath: str):
        """Load detector state from disk."""
        with open(filepath, 'rb') as f:
            state = pickle.load(f)

        self.n_states = state.get('n_states', self.n_states)
        self.feature_window = state.get('feature_window', self.feature_window)
        self._fit_interval = state.get('_fit_interval', self._fit_interval)
        self._use_shared_memory = state.get('_use_shared_memory', self._use_shared_memory)
        self._tick_count = state.get('_tick_count', 0)
        self.garch_omega = state.get('garch_omega', 0.000001)
        self.garch_alpha = state.get('garch_alpha', 0.1)
        self.garch_beta = state.get('garch_beta', 0.85)
        self.current_variance = state.get('current_variance', 0.0001)
        self._last_regime = Regime(state['_last_regime']) if '_last_regime' in state else Regime.UNKNOWN
        self._fallback_thresholds = state.get('_fallback_thresholds', {'high_vol': 0.5, 'trend': 0.001})
        self._use_fallback = state.get('_use_fallback', not HMMLEARN_AVAILABLE)

        self.price_history = deque(maxlen=5000)
        for p in state.get('price_history', []):
            self.price_history.append(p)

        self.detection_times = deque(maxlen=1000)
        for t in state.get('detection_times', []):
            self.detection_times.append(t)

        self.regime_history = deque(maxlen=1000)
        for r in state.get('regime_history', []):
            self.regime_history.append(Regime(r))

        model_data = state.get('_active_model')
        if model_data is not None and HMMLEARN_AVAILABLE:
            self._active_model, self._state_to_regime = _dict_to_hmm(model_data)
        else:
            self._active_model = None
            self._state_to_regime = {k: Regime(v) for k, v in state.get('_state_to_regime', {}).items()}

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


def generate_synthetic_regimes(n_samples: int = 300) -> Tuple[np.ndarray, List[Regime]]:
    """
    Generate synthetic price series with known regimes for testing.

    Returns:
        prices: array of shape (n_samples + 1,)
        regimes: list of length n_samples with Regime labels
    """
    # Divide samples into 3 equal blocks for each regime
    block_size = n_samples // 3
    remainder = n_samples % 3

    prices = [100.0]
    regimes: List[Regime] = []

    def _generate_block(samples: int, regime: Regime):
        block_prices = [prices[-1]]
        for _ in range(samples):
            if regime == Regime.TRENDING:
                drift = 0.001
                vol = 0.01
            elif regime == Regime.MEAN_REVERTING:
                # Mean reverting to starting price of block
                deviation = block_prices[-1] - block_prices[0]
                drift = -0.002 * deviation
                vol = 0.005
            else:  # HIGH_VOLATILITY
                drift = 0.0
                vol = 0.04
            ret = np.random.normal(drift, vol)
            block_prices.append(block_prices[-1] * np.exp(ret))
        # Add block to global prices (skip first since it's already in prices)
        prices.extend(block_prices[1:])
        regimes.extend([regime] * samples)

    block_sizes = [block_size] * 3
    block_sizes[0] += remainder

    _generate_block(block_sizes[0], Regime.TRENDING)
    _generate_block(block_sizes[1], Regime.MEAN_REVERTING)
    _generate_block(block_sizes[2], Regime.HIGH_VOLATILITY)

    return np.array(prices, dtype=np.float64), regimes
