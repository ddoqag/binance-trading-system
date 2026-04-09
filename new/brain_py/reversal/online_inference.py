"""
online_inference.py - 在线推断引擎

实现实时反转信号推断，延迟 < 1ms
1. 特征实时计算
2. 模型推理
3. 信号分级输出
4. 共享内存写入
"""

import time
import threading
import logging
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass
from datetime import datetime
import numpy as np

from .shm_bridge import SharedMemoryBridge, ReversalFeaturesSHM, ReversalSignalSHM
from .reversal_model import ReversalAlphaModel
from .feature_engineer import ReversalFeatureEngineer

logger = logging.getLogger(__name__)


@dataclass
class InferenceConfig:
    """推断配置"""
    # 模型配置
    model_path: str = "checkpoints/reversal_model.pkl"

    # 推断频率
    inference_interval_ms: float = 10.0  # 每10ms推断一次

    # 信号阈值
    min_confidence: float = 0.6
    min_signal_strength: float = 0.3

    # 分级阈值
    level1_threshold: float = 0.3  # 轻度信号
    level2_threshold: float = 0.5  # 中度信号
    level3_threshold: float = 0.7  # 强烈信号

    # 信号有效期
    signal_ttl_ms: int = 500

    # 共享内存路径
    shm_path: str = "/tmp/hft_reversal_shm"


@dataclass
class MarketData:
    """市场数据快照"""
    timestamp_ms: int
    symbol: str

    # 价格数据
    best_bid: float
    best_ask: float
    mid_price: float
    micro_price: float

    # 订单簿数据
    bid_size: float
    ask_size: float
    spread: float

    # 订单流数据
    ofi: float  # Order Flow Imbalance
    trade_imbalance: float

    # 成交数据
    last_price: float
    last_volume: float

    # 历史数据 (用于计算特征)
    price_history: list = None
    volume_history: list = None


class OnlineInferenceEngine:
    """
    在线推断引擎

    实时计算特征、执行模型推理、输出分级信号
    """

    def __init__(self, config: Optional[InferenceConfig] = None):
        self.config = config or InferenceConfig()

        # 组件初始化
        self.model: Optional[ReversalAlphaModel] = None
        self.feature_engineer = ReversalFeatureEngineer()
        self.shm_bridge = SharedMemoryBridge(shm_path=self.config.shm_path)

        # 状态
        self._running = False
        self._inference_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # 最新市场数据
        self._latest_market_data: Optional[MarketData] = None

        # 最新信号
        self._latest_signal: Optional[ReversalSignalSHM] = None
        self._signal_timestamp_ms: int = 0

        # 统计
        self.inference_count = 0
        self.inference_errors = 0
        self.avg_latency_us = 0.0

    def load_model(self) -> bool:
        """加载模型"""
        try:
            self.model = ReversalAlphaModel()
            success = self.model.load_model(self.config.model_path)
            if success:
                logger.info(f"Model loaded from {self.config.model_path}")
                return True
            else:
                logger.error(f"Failed to load model from {self.config.model_path}")
                return False
        except Exception as e:
            logger.error(f"Error loading model: {e}")
            return False

    def connect_shm(self) -> bool:
        """连接共享内存"""
        return self.shm_bridge.connect()

    def start(self) -> bool:
        """启动推断引擎"""
        if self._running:
            logger.warning("Inference engine already running")
            return False

        # 加载模型
        if not self.load_model():
            logger.error("Failed to load model, cannot start")
            return False

        # 连接共享内存
        if not self.connect_shm():
            logger.error("Failed to connect to SHM, cannot start")
            return False

        self._running = True
        self._inference_thread = threading.Thread(target=self._inference_loop, daemon=True)
        self._inference_thread.start()

        logger.info("Online inference engine started")
        return True

    def stop(self):
        """停止推断引擎"""
        self._running = False
        if self._inference_thread:
            self._inference_thread.join(timeout=1.0)
        self.shm_bridge.disconnect()
        logger.info("Online inference engine stopped")

    def update_market_data(self, data: MarketData):
        """更新市场数据"""
        with self._lock:
            self._latest_market_data = data

    def _inference_loop(self):
        """推断主循环"""
        interval_sec = self.config.inference_interval_ms / 1000.0

        while self._running:
            start_time = time.time()

            try:
                self._perform_inference()
            except Exception as e:
                self.inference_errors += 1
                logger.error(f"Inference error: {e}")

            # 控制推断频率
            elapsed = time.time() - start_time
            sleep_time = max(0, interval_sec - elapsed)
            time.sleep(sleep_time)

    def _perform_inference(self):
        """执行单次推断"""
        with self._lock:
            market_data = self._latest_market_data

        if market_data is None:
            return

        start_ns = time.time_ns()

        # 1. 计算特征
        features = self._calculate_features(market_data)

        # 2. 写入特征到共享内存
        features_shm = self._create_features_shm(features, market_data)
        self.shm_bridge.write_features(features_shm)

        # 3. 模型推理
        signal_shm = self._run_inference(features, market_data)

        # 4. 写入信号到共享内存
        if signal_shm:
            self.shm_bridge.write_signal(signal_shm)

            with self._lock:
                self._latest_signal = signal_shm
                self._signal_timestamp_ms = int(time.time_ns() / 1_000_000)

        # 5. 更新统计
        latency_us = (time.time_ns() - start_ns) / 1000.0
        self.avg_latency_us = 0.9 * self.avg_latency_us + 0.1 * latency_us
        self.inference_count += 1

    def _calculate_features(self, data: MarketData) -> Dict[str, float]:
        """计算特征"""
        return self.feature_engineer.calculate_features(
            ofi=data.ofi,
            mid_price=data.mid_price,
            micro_price=data.micro_price,
            spread=data.spread,
            bid_size=data.bid_size,
            ask_size=data.ask_size,
            timestamp_ms=data.timestamp_ms
        )

    def _create_features_shm(
        self,
        features: Dict[str, float],
        data: MarketData
    ) -> ReversalFeaturesSHM:
        """创建特征SHM结构"""
        shm = ReversalFeaturesSHM()

        # 价格特征
        shm.price_momentum_1m = features.get('price_return_50ms', 0.0)
        shm.price_zscore = features.get('pressure_ofi_ratio', 0.0)
        shm.price_velocity = features.get('price_return_50ms', 0.0)

        # 成交量特征
        shm.volume_surge = features.get('liquidity_trade_intensity', 0.0)

        # 波动率特征
        shm.volatility_current = features.get('price_volatility_20', 0.0)

        # 订单流特征
        shm.ofi_signal = features.get('pressure_ofi', 0.0)
        shm.trade_imbalance = data.trade_imbalance
        shm.bid_ask_pressure = features.get('liquidity_bid_ask_imbalance', 0.0)

        # 微观结构
        shm.spread_percentile = features.get('liquidity_spread', 0.0)
        shm.queue_imbalance = features.get('liquidity_bid_ask_imbalance', 0.0)
        shm.trade_intensity = features.get('liquidity_trade_intensity', 0.0)

        # 时间特征
        now = datetime.now()
        shm.time_of_day = (now.hour * 3600 + now.minute * 60 + now.second) / 86400.0
        shm.day_of_week = now.weekday()

        return shm

    def _run_inference(
        self,
        features: Dict[str, float],
        data: MarketData
    ) -> Optional[ReversalSignalSHM]:
        """执行模型推理"""
        if self.model is None or not self.model.is_fitted:
            return None

        # 准备特征向量
        feature_vector = np.array(list(features.values())).reshape(1, -1)

        # 模型推理
        try:
            probability = self.model.predict_proba(feature_vector)[0]
            signal_strength = self.model.predict_signal_strength(feature_vector)[0]
        except Exception as e:
            logger.error(f"Model inference error: {e}")
            return None

        # 计算置信度
        confidence = abs(probability - 0.5) * 2  # 映射到 [0, 1]

        # 检查阈值
        if confidence < self.config.min_confidence:
            return None

        if abs(signal_strength) < self.config.min_signal_strength:
            return None

        # 创建信号
        signal = ReversalSignalSHM()
        signal.signal_strength = signal_strength
        signal.confidence = confidence
        signal.probability = probability

        # 预期收益 (基于信号强度估计)
        signal.expected_return = signal_strength * 0.001  # 假设0.1%每单位强度
        signal.time_horizon_ms = 500  # 500ms

        # 模型信息
        signal.model_version = 1
        signal.model_type = 0  # LightGBM
        signal.inference_latency_us = int(self.avg_latency_us)

        # 风险指标
        signal.prediction_uncertainty = 1.0 - confidence
        signal.risk_score = 0.5 - abs(signal_strength) * 0.5

        # 执行建议 (分级)
        signal.suggested_urgency = self._calculate_urgency(signal_strength, confidence)
        signal.suggested_ttl_ms = self.config.signal_ttl_ms
        signal.execution_priority = self._determine_priority(signal_strength, confidence)

        return signal

    def _calculate_urgency(self, signal_strength: float, confidence: float) -> float:
        """计算建议紧急度"""
        return min(1.0, abs(signal_strength) * confidence * 1.5)

    def _determine_priority(self, signal_strength: float, confidence: float) -> int:
        """确定执行优先级 (0=normal, 1=high, 2=critical)"""
        strength_abs = abs(signal_strength)

        if strength_abs >= self.config.level3_threshold and confidence >= 0.8:
            return 2  # Critical
        elif strength_abs >= self.config.level2_threshold and confidence >= 0.7:
            return 1  # High
        else:
            return 0  # Normal

    def get_latest_signal(self) -> Optional[ReversalSignalSHM]:
        """获取最新信号"""
        with self._lock:
            return self._latest_signal

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            'inference_count': self.inference_count,
            'inference_errors': self.inference_errors,
            'avg_latency_us': self.avg_latency_us,
            'latest_signal': self._latest_signal,
            'shm_stats': self.shm_bridge.get_stats()
        }


class GradedExecutionLogic:
    """
    分级执行逻辑

    根据信号强度分级执行：
    - Level 1 (轻度): 调整挂单位置
    - Level 2 (中度): 调整积极性和TTL
    - Level 3 (强烈): 可能反转仓位
    """

    def __init__(self, config: Optional[InferenceConfig] = None):
        self.config = config or InferenceConfig()

    def process_signal(
        self,
        signal: ReversalSignalSHM,
        current_urgency: float,
        current_side: int  # 1=buy, -1=sell
    ) -> Dict[str, Any]:
        """
        处理信号并返回执行建议

        Returns:
            Dict with execution recommendations
        """
        strength = abs(signal.signal_strength)
        confidence = signal.confidence
        direction = 1 if signal.signal_strength > 0 else -1

        recommendation = {
            'adjust_urgency': False,
            'new_urgency': current_urgency,
            'adjust_position': False,
            'reverse_side': False,
            'adjust_ttl': False,
            'new_ttl_ms': 5000,
            'reason': ''
        }

        # Level 3: 强烈信号 - 考虑反转
        if strength >= self.config.level3_threshold and confidence >= 0.8:
            if direction != current_side:
                recommendation['reverse_side'] = True
                recommendation['reason'] = f"Strong reversal signal: {signal.signal_strength:.3f}"
            else:
                recommendation['adjust_urgency'] = True
                recommendation['new_urgency'] = min(1.0, current_urgency + 0.3)
                recommendation['reason'] = f"Strong confirm signal: {signal.signal_strength:.3f}"

        # Level 2: 中度信号 - 调整积极性和TTL
        elif strength >= self.config.level2_threshold and confidence >= 0.7:
            recommendation['adjust_urgency'] = True

            if direction == current_side:
                # 同向信号 - 增加积极性
                recommendation['new_urgency'] = min(1.0, current_urgency + 0.2)
                recommendation['adjust_ttl'] = True
                recommendation['new_ttl_ms'] = 3000
                recommendation['reason'] = f"Medium confirm signal: {signal.signal_strength:.3f}"
            else:
                # 反向信号 - 降低积极性
                recommendation['new_urgency'] = max(0.0, current_urgency - 0.2)
                recommendation['adjust_ttl'] = True
                recommendation['new_ttl_ms'] = 2000
                recommendation['reason'] = f"Medium reversal signal: {signal.signal_strength:.3f}"

        # Level 1: 轻度信号 - 微调
        elif strength >= self.config.level1_threshold:
            if direction == current_side:
                recommendation['adjust_urgency'] = True
                recommendation['new_urgency'] = min(1.0, current_urgency + 0.1)
                recommendation['reason'] = f"Weak confirm signal: {signal.signal_strength:.3f}"

        return recommendation


def create_inference_engine(
    model_path: str = "checkpoints/reversal_model.pkl",
    shm_path: str = "/tmp/hft_reversal_shm"
) -> OnlineInferenceEngine:
    """创建推断引擎便捷函数"""
    config = InferenceConfig(
        model_path=model_path,
        shm_path=shm_path
    )
    return OnlineInferenceEngine(config)
