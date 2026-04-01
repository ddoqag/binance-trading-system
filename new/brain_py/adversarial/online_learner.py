"""
Layer C: 自适应在线进化
- 自动收集被收割样本
- 置信度过滤，只学高置信度样本
- Experience Replay 混合新旧样本，防止灾难性遗忘
- 版本快照 + 自动回滚
- 样本老化：旧样本权重指数衰减
"""

import numpy as np
import logging
import time
from typing import List, Tuple, Optional, Deque
from collections import deque

from .types import TrapFeatures, HarvestEvent, ModelSnapshot
from .detector import TrapDetector
from .utils import calculate_confidence

logger = logging.getLogger(__name__)


class ExperienceReplay:
    """经验回放缓冲区，存储历史经典样本防止遗忘"""

    def __init__(self, capacity: int = 10000):
        self.capacity = capacity
        self.buffer: Deque[Tuple[np.ndarray, int, float]] = deque(maxlen=capacity)
        # (features, label, weight)

    def extend(self, samples: List[Tuple[np.ndarray, int, float]]) -> None:
        """添加新样本到回放缓冲区"""
        for sample in samples:
            self.buffer.append(sample)

    def sample(self, batch_size: int) -> List[Tuple[np.ndarray, int, float]]:
        """随机采样一批"""
        if len(self.buffer) < batch_size:
            return list(self.buffer)
        indices = np.random.choice(len(self.buffer), batch_size, replace=False)
        return [list(self.buffer)[i] for i in indices]

    def __len__(self) -> int:
        return len(self.buffer)


class OnlineAdversarialLearner:
    """
    在线对抗学习器：
    - 收集被收割样本
    - 置信度过滤
    - Experience Replay 防止遗忘
    - 版本快照 + 性能回滚
    """

    def __init__(
        self,
        detector: TrapDetector,
        batch_size: int = 32,
        min_confidence: float = 0.5,
        max_snapshots: int = 5,
        replay_capacity: int = 10000,
        replay_ratio: float = 0.2,  # 80% 新样本 + 20% 回放
        decay_rate_daily: float = 0.02,  # 每天衰减 2%
        performance_drop_threshold: float = 0.1,  # 准确率下降 10% 触发回滚
    ):
        self.detector = detector
        self.batch_size = batch_size
        self.min_confidence = min_confidence
        self.max_snapshots = max_snapshots
        self.replay_ratio = replay_ratio
        self.decay_rate_daily = decay_rate_daily
        self.performance_drop_threshold = performance_drop_threshold

        # 在线缓冲区攒新样本
        self.buffer: List[Tuple[np.ndarray, int, float, float]] = []
        # (features, label, confidence, timestamp)

        # Experience Replay
        self.replay_buffer = ExperienceReplay(replay_capacity)

        # 版本快照
        self.version_snapshots: List[ModelSnapshot] = []
        self.performance_history: List[float] = []

        # 初始化时快照一次
        if self.detector.is_fitted:
            self.snapshot(1.0)

    def update(
        self,
        features: TrapFeatures,
        entry_price: float,
        current_price: float,
        entry_time: float,
        current_time: float,
        threshold: float = 0.001
    ) -> bool:
        """
        处理一个交易结果，判断是否被收割，如果置信度足够加入缓冲区。
        缓冲区满 → 触发更新。

        Returns:
            updated: 是否触发了模型更新
        """
        # 判断是否被收割
        duration = current_time - entry_time
        adverse_move = abs(current_price - entry_price) / entry_price
        is_harvested = duration < 60.0 and adverse_move > threshold  # 短窗口

        confidence = calculate_confidence(adverse_move, threshold)

        if confidence >= self.min_confidence:
            label = 1 if is_harvested else 0
            X = features.to_numpy()
            timestamp = time.time()
            self.buffer.append((X, label, confidence, timestamp))

        # 如果缓冲区攒够了 → 更新
        if len(self.buffer) >= self.batch_size:
            self._update_model()
            self.buffer.clear()
            return True

        return False

    def _update_model(self) -> None:
        """执行模型更新"""
        # 计算带衰减的权重 + 准备数据
        current_time = time.time()
        X_batch: List[np.ndarray] = []
        y_batch: List[int] = []
        weights_batch: List[float] = []

        # 处理新缓冲区样本（带老化衰减）
        for X, y, conf, ts in self.buffer:
            age_days = (current_time - ts) / (60 * 60 * 24)
            decay = (1.0 - self.decay_rate_daily) ** age_days
            weight = conf * decay
            X_batch.append(X)
            y_batch.append(y)
            weights_batch.append(weight)

        # 从 Experience Replay 采样
        n_replay = int(self.batch_size * self.replay_ratio)
        if len(self.replay_buffer) >= n_replay and n_replay > 0:
            replay_samples = self.replay_buffer.sample(n_replay)
            for X, y, weight in replay_samples:
                X_batch.append(X)
                y_batch.append(y)
                weights_batch.append(weight)

        # 转换为 numpy
        X = np.stack(X_batch, axis=0)
        y = np.array(y_batch, dtype=int)
        weights = np.array(weights_batch, dtype=float)

        # 增量更新
        if self.detector.is_fitted:
            self.detector.partial_fit(X, y, sample_weight=weights)
        else:
            self.detector.partial_fit(X, y, classes=np.array([0, 1]), sample_weight=weights)

        # 新样本加入回放缓冲区
        new_replay_samples = [
            (X, y, conf * ((1 - self.decay_rate_daily) ** ((current_time - ts) / (60*60*24))))
            for X, y, conf, ts in self.buffer
        ]
        self.replay_buffer.extend(new_replay_samples)

        # 更新特征统计量用于异常检测
        if self.detector.anomaly_detection:
            # 收集所有回放样本做统计
            all_X = []
            for X, _, _ in self.replay_buffer.buffer:
                all_X.append(X)
            if len(all_X) >= 50:  # 至少有足够样本
                all_X_np = np.stack(all_X, axis=0)
                self.detector.update_feature_statistics(all_X_np)

        logger.info(f"[OnlineAdversarialLearner] Model updated with {len(X)} samples")

    def snapshot(self, performance: float) -> None:
        """保存当前模型快照"""
        weights = self.detector.get_weights()
        snapshot = ModelSnapshot(
            model_weights=weights,
            performance=performance,
            timestamp=time.time()
        )
        self.version_snapshots.append(snapshot)

        # 只保留最近 N 个
        if len(self.version_snapshots) > self.max_snapshots:
            self.version_snapshots.pop(0)

        self.performance_history.append(performance)
        logger.info(f"[OnlineAdversarialLearner] Snapshot saved, performance={performance:.3f}")

    def check_and_rollback(self) -> bool:
        """
        检查当前性能，如果下降太多回滚到最佳版本。

        Returns:
            rolled_back: 是否执行了回滚
        """
        if len(self.version_snapshots) < 2:
            return False

        # 获取最佳版本
        best = max(self.version_snapshots, key=lambda x: x.performance)
        current_perf = self.version_snapshots[-1].performance

        if current_perf < best.performance - self.performance_drop_threshold:
            # 触发回滚
            self.detector.set_weights(best.model_weights)
            logger.warning(
                f"[OnlineAdversarialLearner] Rollback: current={current_perf:.3f}, "
                f"best={best.performance:.3f}, rolled back to best"
            )
            return True

        return False

    def get_best_performance(self) -> float:
        """获取最佳历史性能"""
        if not self.version_snapshots:
            return 0.0
        return max(snap.performance for snap in self.version_snapshots)

    def get_current_buffer_size(self) -> int:
        """当前缓冲区大小"""
        return len(self.buffer)
