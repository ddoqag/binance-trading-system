"""
inference_engine.py - Real-time Inference Engine for Reversal Detection

实时推断引擎 - 提供低延迟（<1ms）的模型推理和信号输出
支持模型热更新
"""

import os
import time
import json
import logging
import threading
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np

from .shm_bridge import (
    ReversalFeaturesSHM,
    ReversalSignalSHM,
    SharedMemoryBridge,
    REVERSAL_SHM_MAGIC
)

logger = logging.getLogger(__name__)


@dataclass
class InferenceConfig:
    """推断引擎配置"""
    # 模型配置
    model_path: str = "brain_py/reversal/checkpoints/reversal_model.pkl"
    model_type: str = "lightgbm"  # lightgbm, xgboost, onnx

    # 性能配置
    max_latency_us: int = 1000  # 最大允许延迟 (微秒)
    batch_size: int = 1  # 批处理大小 (1=实时模式)
    inference_interval_ms: int = 10  # 推断间隔 (毫秒)

    # 特征配置
    feature_lookback: int = 20  # 特征回看周期
    feature_dim: int = 32  # 特征维度

    # 信号阈值
    min_confidence: float = 0.6  # 最小置信度
    min_signal_strength: float = 0.3  # 最小信号强度
    max_signals_per_second: int = 5  # 每秒最大信号数

    # 热更新配置
    hot_reload_enabled: bool = True
    model_watch_interval_ms: int = 5000  # 模型文件监控间隔

    # SHM 配置
    shm_path: str = "/tmp/hft_reversal_shm"
    use_shm: bool = True

    # 调试配置
    debug_mode: bool = False
    log_predictions: bool = False


@dataclass
class ReversalSignal:
    """反转信号数据类"""
    timestamp_ns: int = 0
    signal_strength: float = 0.0  # -1.0 to 1.0
    confidence: float = 0.0  # 0.0 to 1.0
    probability: float = 0.0  # 0.0 to 1.0
    expected_return: float = 0.0
    time_horizon_ms: int = 1000
    model_version: int = 0
    inference_latency_us: int = 0
    feature_timestamp_ns: int = 0
    market_regime: int = 0
    risk_score: float = 0.0
    top_features: Dict[str, float] = field(default_factory=dict)

    def is_valid(self) -> bool:
        """检查信号是否有效"""
        return (
            self.confidence >= 0.0 and self.confidence <= 1.0 and
            self.signal_strength >= -1.0 and self.signal_strength <= 1.0 and
            self.inference_latency_us > 0
        )

    def to_shm(self) -> ReversalSignalSHM:
        """转换为共享内存格式"""
        shm = ReversalSignalSHM()
        shm.timestamp_ns = self.timestamp_ns
        shm.signal_strength = self.signal_strength
        shm.confidence = self.confidence
        shm.probability = self.probability
        shm.expected_return = self.expected_return
        shm.time_horizon_ms = self.time_horizon_ms
        shm.model_version = self.model_version
        shm.inference_latency_us = self.inference_latency_us
        shm.feature_timestamp_ns = self.feature_timestamp_ns
        shm.market_regime = self.market_regime
        shm.risk_score = self.risk_score

        # 填充 top features
        features = list(self.top_features.values())[:8]
        for i, val in enumerate(features):
            setattr(shm, f'top_feature_{i+1}', val)

        # 执行建议
        shm.suggested_urgency = abs(self.signal_strength) * self.confidence
        shm.suggested_ttl_ms = self.time_horizon_ms
        shm.execution_priority = 2 if self.confidence > 0.8 else 1 if self.confidence > 0.6 else 0

        return shm


class ModelWrapper:
    """模型包装器 - 统一接口支持多种模型类型"""

    def __init__(self, model_path: str, model_type: str):
        self.model_path = model_path
        self.model_type = model_type
        self.model: Optional[Any] = None
        self.version = 0
        self.last_modified = 0.0
        self.feature_importance: Dict[str, float] = {}
        self._load_model()

    def _load_model(self) -> bool:
        """加载模型"""
        try:
            if not os.path.exists(self.model_path):
                logger.warning(f"Model file not found: {self.model_path}")
                return False

            if self.model_type == "lightgbm":
                return self._load_lightgbm()
            elif self.model_type == "xgboost":
                return self._load_xgboost()
            elif self.model_type == "onnx":
                return self._load_onnx()
            elif self.model_type == "sklearn":
                return self._load_sklearn()
            else:
                logger.error(f"Unknown model type: {self.model_type}")
                return False

        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            return False

    def _load_lightgbm(self) -> bool:
        """加载 LightGBM 模型"""
        try:
            import lightgbm as lgb
            self.model = lgb.Booster(model_file=self.model_path)
            self.version += 1
            self.last_modified = os.path.getmtime(self.model_path)

            # 获取特征重要性
            importance = self.model.feature_importance(importance_type='gain')
            feature_names = self.model.feature_name()
            self.feature_importance = dict(zip(feature_names, importance))

            logger.info(f"Loaded LightGBM model v{self.version} from {self.model_path}")
            return True
        except ImportError:
            logger.error("lightgbm not installed")
            return False

    def _load_xgboost(self) -> bool:
        """加载 XGBoost 模型"""
        try:
            import xgboost as xgb
            self.model = xgb.Booster()
            self.model.load_model(self.model_path)
            self.version += 1
            self.last_modified = os.path.getmtime(self.model_path)
            logger.info(f"Loaded XGBoost model v{self.version}")
            return True
        except ImportError:
            logger.error("xgboost not installed")
            return False

    def _load_onnx(self) -> bool:
        """加载 ONNX 模型"""
        try:
            import onnxruntime as ort
            self.model = ort.InferenceSession(self.model_path)
            self.version += 1
            self.last_modified = os.path.getmtime(self.model_path)
            logger.info(f"Loaded ONNX model v{self.version}")
            return True
        except ImportError:
            logger.error("onnxruntime not installed")
            return False

    def _load_sklearn(self) -> bool:
        """加载 sklearn 模型"""
        try:
            import joblib
            self.model = joblib.load(self.model_path)
            self.version += 1
            self.last_modified = os.path.getmtime(self.model_path)
            logger.info(f"Loaded sklearn model v{self.version}")
            return True
        except ImportError:
            logger.error("joblib not installed")
            return False

    def predict(self, features: np.ndarray) -> tuple:
        """
        执行预测

        Returns:
            (prediction, probability, confidence)
        """
        if self.model is None:
            return 0.0, 0.5, 0.0

        try:
            if self.model_type == "lightgbm":
                pred = self.model.predict(features.reshape(1, -1))
                prob = pred[0] if len(pred.shape) > 0 else pred
                # 二分类: 0-1 概率转换为信号强度
                signal = (prob - 0.5) * 2  # 映射到 -1, 1
                confidence = abs(prob - 0.5) * 2  # 距离0.5越远越 confident
                return signal, prob, confidence

            elif self.model_type == "xgboost":
                import xgboost as xgb
                dmatrix = xgb.DMatrix(features.reshape(1, -1))
                pred = self.model.predict(dmatrix)
                prob = pred[0]
                signal = (prob - 0.5) * 2
                confidence = abs(prob - 0.5) * 2
                return signal, prob, confidence

            elif self.model_type == "onnx":
                input_name = self.model.get_inputs()[0].name
                pred = self.model.run(None, {input_name: features.reshape(1, -1).astype(np.float32)})
                prob = pred[0][0][1] if len(pred[0][0]) > 1 else pred[0][0][0]
                signal = (prob - 0.5) * 2
                confidence = abs(prob - 0.5) * 2
                return signal, prob, confidence

            elif self.model_type == "sklearn":
                if hasattr(self.model, 'predict_proba'):
                    prob = self.model.predict_proba(features.reshape(1, -1))[0]
                    prob_class1 = prob[1] if len(prob) > 1 else prob[0]
                    signal = (prob_class1 - 0.5) * 2
                    confidence = abs(prob_class1 - 0.5) * 2
                    return signal, prob_class1, confidence
                else:
                    pred = self.model.predict(features.reshape(1, -1))[0]
                    return float(pred), 0.5, 0.5

            return 0.0, 0.5, 0.0

        except Exception as e:
            logger.error(f"Prediction error: {e}")
            return 0.0, 0.5, 0.0

    def check_for_update(self) -> bool:
        """检查模型文件是否有更新"""
        try:
            if not os.path.exists(self.model_path):
                return False

            current_mtime = os.path.getmtime(self.model_path)
            if current_mtime > self.last_modified:
                logger.info(f"Model file updated, reloading...")
                return self._load_model()

            return False
        except Exception as e:
            logger.error(f"Error checking model update: {e}")
            return False


class InferenceEngine:
    """
    实时推断引擎

    核心功能:
    1. 实时特征接收 (通过 SHM 或 ZMQ)
    2. 低延迟模型推理 (<1ms)
    3. 信号输出 (写入 SHM)
    4. 模型热更新
    5. 性能监控
    """

    def __init__(self, config: Optional[InferenceConfig] = None):
        self.config = config or InferenceConfig()
        self.model: Optional[ModelWrapper] = None
        self.shm_bridge: Optional[SharedMemoryBridge] = None

        # 运行状态
        self._running = False
        self._inference_thread: Optional[threading.Thread] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

        # 特征缓存
        self._feature_buffer: List[np.ndarray] = []
        self._last_signal_time = 0
        self._signal_count = 0

        # 统计
        self.stats = {
            'inference_count': 0,
            'inference_errors': 0,
            'avg_latency_us': 0.0,
            'max_latency_us': 0,
            'signals_generated': 0,
            'model_reloads': 0,
            'start_time': 0
        }

        # 回调
        self._signal_callbacks: List[Callable[[ReversalSignal], None]] = []

    def add_signal_callback(self, callback: Callable[[ReversalSignal], None]):
        """添加信号回调"""
        self._signal_callbacks.append(callback)

    def initialize(self) -> bool:
        """初始化引擎"""
        logger.info("Initializing InferenceEngine...")

        # 1. 加载模型
        self.model = ModelWrapper(self.config.model_path, self.config.model_type)
        if self.model.model is None:
            logger.warning("No model loaded, using dummy predictions")

        # 2. 连接共享内存
        if self.config.use_shm:
            self.shm_bridge = SharedMemoryBridge(
                shm_path=self.config.shm_path,
                use_shm=True
            )
            if not self.shm_bridge.connect():
                logger.error("Failed to connect to SHM")
                return False

        self.stats['start_time'] = time.time_ns()
        logger.info("InferenceEngine initialized successfully")
        return True

    def start(self):
        """启动推断引擎"""
        if self._running:
            return

        self._running = True

        # 启动推断循环
        self._inference_thread = threading.Thread(target=self._inference_loop, daemon=True)
        self._inference_thread.start()

        # 启动模型监控
        if self.config.hot_reload_enabled:
            self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
            self._watchdog_thread.start()

        logger.info("InferenceEngine started")

    def stop(self):
        """停止推断引擎"""
        self._running = False

        if self._inference_thread:
            self._inference_thread.join(timeout=2.0)

        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=2.0)

        if self.shm_bridge:
            self.shm_bridge.disconnect()

        logger.info("InferenceEngine stopped")

    def _inference_loop(self):
        """推断主循环"""
        while self._running:
            try:
                # 读取特征
                features_shm = self._read_features_from_shm()
                if features_shm is None:
                    time.sleep(self.config.inference_interval_ms / 1000.0)
                    continue

                # 执行推断
                signal = self._infer(features_shm)

                # 输出信号
                if signal and signal.is_valid():
                    self._output_signal(signal)

                # 控制频率
                time.sleep(self.config.inference_interval_ms / 1000.0)

            except Exception as e:
                logger.error(f"Inference loop error: {e}")
                self.stats['inference_errors'] += 1
                time.sleep(0.001)  # 1ms 错误恢复

    def _watchdog_loop(self):
        """模型监控循环"""
        while self._running:
            try:
                if self.model and self.model.check_for_update():
                    self.stats['model_reloads'] += 1
                    logger.info(f"Model hot-reloaded to v{self.model.version}")

                time.sleep(self.config.model_watch_interval_ms / 1000.0)

            except Exception as e:
                logger.error(f"Watchdog error: {e}")
                time.sleep(1.0)

    def _read_features_from_shm(self) -> Optional[ReversalFeaturesSHM]:
        """从共享内存读取特征"""
        if not self.shm_bridge:
            return None

        try:
            return self.shm_bridge.read_features()
        except Exception as e:
            logger.error(f"Error reading features: {e}")
            return None

    def _extract_features(self, features_shm: ReversalFeaturesSHM) -> np.ndarray:
        """从 SHM 特征提取模型输入向量"""
        # 构建特征向量 (32维)
        features = np.array([
            # 价格特征
            features_shm.price_momentum_1m,
            features_shm.price_momentum_5m,
            features_shm.price_momentum_15m,
            features_shm.price_zscore,
            features_shm.price_percentile,
            features_shm.price_velocity,
            features_shm.price_acceleration,
            features_shm.price_mean_reversion,

            # 成交量特征
            features_shm.volume_surge,
            features_shm.volume_momentum,
            features_shm.volume_zscore,
            features_shm.relative_volume,

            # 波动率特征
            features_shm.volatility_current,
            features_shm.volatility_regime,
            features_shm.atr_ratio,
            features_shm.bollinger_position,

            # 订单流特征
            features_shm.ofi_signal,
            features_shm.trade_imbalance,
            features_shm.bid_ask_pressure,
            features_shm.order_book_slope,
            features_shm.micro_price_drift,

            # 微观结构
            features_shm.spread_percentile,
            features_shm.tick_pressure,
            features_shm.queue_imbalance,
            features_shm.trade_intensity,

            # 时间特征
            features_shm.time_of_day,
            float(features_shm.day_of_week),
            float(features_shm.is_market_open),
            float(features_shm.session_type),
        ], dtype=np.float32)

        return features

    def _infer(self, features_shm: ReversalFeaturesSHM) -> Optional[ReversalSignal]:
        """执行模型推断"""
        start_ns = time.time_ns()

        try:
            # 提取特征
            features = self._extract_features(features_shm)

            # 模型预测
            if self.model and self.model.model:
                signal_strength, probability, confidence = self.model.predict(features)
            else:
                # 无模型时使用简单启发式
                signal_strength = self._heuristic_prediction(features_shm)
                probability = 0.5 + signal_strength * 0.5
                confidence = abs(signal_strength)

            # 计算延迟
            latency_us = (time.time_ns() - start_ns) // 1000

            # 检查阈值
            if confidence < self.config.min_confidence:
                return None

            if abs(signal_strength) < self.config.min_signal_strength:
                return None

            # 频率限制
            current_time = time.time_ns()
            time_since_last = (current_time - self._last_signal_time) / 1e9
            if time_since_last < (1.0 / self.config.max_signals_per_second):
                return None

            # 构建信号
            signal = ReversalSignal(
                timestamp_ns=current_time,
                signal_strength=signal_strength,
                confidence=confidence,
                probability=probability,
                expected_return=self._estimate_return(signal_strength, confidence),
                time_horizon_ms=self._estimate_time_horizon(features_shm),
                model_version=self.model.version if self.model else 0,
                inference_latency_us=latency_us,
                feature_timestamp_ns=features_shm.timestamp_ns,
                market_regime=self._detect_market_regime(features_shm),
                risk_score=self._calculate_risk(features_shm, signal_strength),
                top_features=self._get_top_features()
            )

            # 更新统计
            with self._lock:
                self.stats['inference_count'] += 1
                self.stats['signals_generated'] += 1
                self._last_signal_time = current_time

                # 更新延迟统计
                self.stats['avg_latency_us'] = (
                    self.stats['avg_latency_us'] * 0.99 + latency_us * 0.01
                )
                self.stats['max_latency_us'] = max(self.stats['max_latency_us'], latency_us)

            return signal

        except Exception as e:
            logger.error(f"Inference error: {e}")
            self.stats['inference_errors'] += 1
            return None

    def _heuristic_prediction(self, features_shm: ReversalFeaturesSHM) -> float:
        """启发式预测 (无模型时使用)"""
        score = 0.0

        # 价格动量反转
        if features_shm.price_momentum_1m > 0.5 and features_shm.price_zscore > 2.0:
            score -= 0.3  # 超买，看跌反转
        elif features_shm.price_momentum_1m < -0.5 and features_shm.price_zscore < -2.0:
            score += 0.3  # 超卖，看涨反转

        # 成交量确认
        if features_shm.volume_surge > 2.0:
            score *= 1.5  # 放量确认

        # 波动率状态
        if features_shm.volatility_regime > 0.7:
            score *= 0.8  # 高波动降低置信度

        return np.clip(score, -1.0, 1.0)

    def _estimate_return(self, signal_strength: float, confidence: float) -> float:
        """估计预期收益"""
        # 简化的收益估计
        base_return = abs(signal_strength) * 0.001  # 0.1% base
        confidence_adjusted = base_return * confidence
        return confidence_adjusted if signal_strength > 0 else -confidence_adjusted

    def _estimate_time_horizon(self, features_shm: ReversalFeaturesSHM) -> int:
        """估计时间范围 (毫秒)"""
        # 基于波动率和动量调整
        base_horizon = 1000  # 1 second
        vol_factor = 1.0 + features_shm.volatility_current
        return int(base_horizon * vol_factor)

    def _detect_market_regime(self, features_shm: ReversalFeaturesSHM) -> int:
        """检测市场状态"""
        if features_shm.volatility_current > 0.7:
            return 4  # high_vol
        elif features_shm.price_momentum_15m > 0.3:
            return 1  # trend_up
        elif features_shm.price_momentum_15m < -0.3:
            return 2  # trend_down
        else:
            return 3  # range

    def _calculate_risk(self, features_shm: ReversalFeaturesSHM, signal_strength: float) -> float:
        """计算风险分数"""
        risk = 0.0
        risk += features_shm.volatility_current * 0.3
        risk += abs(features_shm.price_velocity) * 0.2
        risk += (1 - abs(signal_strength)) * 0.3  # 弱信号风险高
        risk += features_shm.spread_percentile * 0.2
        return min(risk, 1.0)

    def _get_top_features(self) -> Dict[str, float]:
        """获取最重要的特征"""
        if self.model and self.model.feature_importance:
            sorted_features = sorted(
                self.model.feature_importance.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]
            return {k: v for k, v in sorted_features}
        return {}

    def _output_signal(self, signal: ReversalSignal):
        """输出信号"""
        # 1. 写入共享内存
        if self.shm_bridge:
            shm_signal = signal.to_shm()
            self.shm_bridge.write_signal(shm_signal)

        # 2. 调用回调
        for callback in self._signal_callbacks:
            try:
                callback(signal)
            except Exception as e:
                logger.error(f"Signal callback error: {e}")

        # 3. 日志记录
        if self.config.log_predictions:
            logger.info(
                f"Signal: strength={signal.signal_strength:.3f}, "
                f"confidence={signal.confidence:.3f}, "
                f"latency={signal.inference_latency_us}us"
            )

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            stats = self.stats.copy()

        if self.shm_bridge:
            stats['shm'] = self.shm_bridge.get_stats()

        if self.model:
            stats['model_version'] = self.model.version
            stats['model_type'] = self.model.model_type

        return stats

    def force_reload_model(self) -> bool:
        """强制重新加载模型"""
        if self.model:
            return self.model._load_model()
        return False

    def __enter__(self):
        self.initialize()
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False
