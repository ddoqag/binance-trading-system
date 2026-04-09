"""
毒流检测器 (MVP版本)

使用马氏距离检测异常订单流
阈值：toxic_prob > 0.3 → 停止交易
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from collections import deque
import time


@dataclass
class ToxicFlowAlert:
    """毒流告警"""
    is_toxic: bool
    toxic_probability: float
    mahalanobis_distance: float
    feature_vector: np.ndarray
    timestamp: float
    reason: str


class ToxicFlowDetector:
    """
    毒流检测器

    使用马氏距离检测异常市场状态，识别可能的做市商陷阱
    """

    def __init__(self,
                 threshold: float = 0.3,  # 毒流概率阈值
                 mahalanobis_threshold: float = 5.0,  # 马氏距离阈值
                 window_size: int = 100,  # 特征窗口大小
                 min_samples: int = 20):  # 最小样本数

        self.threshold = threshold
        self.mahalanobis_threshold = mahalanobis_threshold
        self.window_size = window_size
        self.min_samples = min_samples

        # 特征历史
        self.feature_history = deque(maxlen=window_size)
        self.fill_history = deque(maxlen=window_size)

        # 统计参数（用于马氏距离）
        self.mean_vector = None
        self.cov_matrix = None
        self.inv_cov_matrix = None

        # 告警统计
        self.alert_count = 0
        self.block_count = 0
        self.last_alert_time = 0

        # 连续告警计数（防止抖动）
        self.consecutive_alerts = 0
        self.consecutive_threshold = 3  # 连续3次才确认

    def detect(self, orderbook: Dict, recent_fills: Optional[List] = None) -> ToxicFlowAlert:
        """
        检测毒流

        Args:
            orderbook: 订单簿数据
            recent_fills: 最近成交记录

        Returns:
            ToxicFlowAlert: 检测结果
        """
        # 提取特征
        features = self._extract_features(orderbook, recent_fills)

        # 更新历史
        self.feature_history.append(features)

        # 样本不足时，不触发告警
        if len(self.feature_history) < self.min_samples:
            return ToxicFlowAlert(
                is_toxic=False,
                toxic_probability=0.0,
                mahalanobis_distance=0.0,
                feature_vector=features,
                timestamp=time.time(),
                reason="insufficient_samples"
            )

        # 更新统计参数
        self._update_statistics()

        # 计算马氏距离
        distance = self._mahalanobis_distance(features)

        # 转换为概率（指数衰减）
        toxic_prob = 1.0 - np.exp(-distance / self.mahalanobis_threshold)

        # 判断毒流
        is_toxic = toxic_prob > self.threshold

        if is_toxic:
            self.consecutive_alerts += 1
        else:
            self.consecutive_alerts = max(0, self.consecutive_alerts - 1)

        # 只有连续多次才确认
        confirmed_toxic = self.consecutive_alerts >= self.consecutive_threshold

        if confirmed_toxic:
            self.alert_count += 1
            self.block_count += 1
            self.last_alert_time = time.time()
            reason = f"consecutive_alerts_{self.consecutive_alerts}"
        else:
            reason = f"prob={toxic_prob:.2f}, distance={distance:.2f}"

        return ToxicFlowAlert(
            is_toxic=confirmed_toxic,
            toxic_probability=toxic_prob,
            mahalanobis_distance=distance,
            feature_vector=features,
            timestamp=time.time(),
            reason=reason
        )

    def _extract_features(self, orderbook: Dict, recent_fills: Optional[List]) -> np.ndarray:
        """
        提取毒流特征（8维）

        Returns:
            np.ndarray: 特征向量 [OFI, OBI, cancel_rate, trade_imbalance,
                                 spread_change, price_velocity, vpin, queue_imbalance]
        """
        features = []

        # 1. OFI (Order Flow Imbalance)
        ofi = self._calculate_ofi(orderbook)
        features.append(ofi)

        # 2. OBI (Order Book Imbalance)
        obi = self._calculate_obi(orderbook)
        features.append(obi)

        # 3. 撤单率 (Cancel Rate)
        cancel_rate = self._estimate_cancel_rate(orderbook)
        features.append(cancel_rate)

        # 4. 成交不平衡 (Trade Imbalance)
        trade_imbalance = self._calculate_trade_imbalance(recent_fills)
        features.append(trade_imbalance)

        # 5. 点差变化 (Spread Change)
        spread_change = self._calculate_spread_change(orderbook)
        features.append(spread_change)

        # 6. 价格速度 (Price Velocity)
        price_velocity = self._calculate_price_velocity(orderbook)
        features.append(price_velocity)

        # 7. VPIN (Volume-Synchronized Probability of Informed Trading)
        vpin = self._calculate_vpin(recent_fills)
        features.append(vpin)

        # 8. 队列不平衡 (Queue Imbalance)
        queue_imbalance = self._calculate_queue_imbalance(orderbook)
        features.append(queue_imbalance)

        return np.array(features)

    def _calculate_ofi(self, orderbook: Dict) -> float:
        """计算订单流不平衡"""
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if not bids or not asks:
            return 0.0

        bid_volume = sum(b.get('qty', 0) for b in bids[:5])
        ask_volume = sum(a.get('qty', 0) for a in asks[:5])

        total = bid_volume + ask_volume
        if total == 0:
            return 0.0

        return (bid_volume - ask_volume) / total

    def _calculate_obi(self, orderbook: Dict) -> float:
        """计算订单簿不平衡（前3档）"""
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if len(bids) < 3 or len(asks) < 3:
            return 0.0

        bid_volume = sum(b.get('qty', 0) for b in bids[:3])
        ask_volume = sum(a.get('qty', 0) for a in asks[:3])

        total = bid_volume + ask_volume
        if total == 0:
            return 0.0

        return (bid_volume - ask_volume) / total

    def _estimate_cancel_rate(self, orderbook: Dict) -> float:
        """估算撤单率（基于订单簿变化）"""
        # MVP简化：使用队列深度变化作为代理
        bids = orderbook.get('bids', [])

        if len(bids) < 2:
            return 0.0

        # 如果第一档量很少但有很多档位，可能有撤单
        first_level_qty = bids[0].get('qty', 0)
        total_qty = sum(b.get('qty', 0) for b in bids[:5])

        if total_qty == 0:
            return 0.0

        concentration = first_level_qty / total_qty

        # 集中度低可能意味着撤单
        return max(0, 0.5 - concentration)

    def _calculate_trade_imbalance(self, recent_fills: Optional[List]) -> float:
        """计算成交不平衡"""
        if not recent_fills:
            return 0.0

        buy_volume = sum(f.get('qty', 0) for f in recent_fills if f.get('side') == 'buy')
        sell_volume = sum(f.get('qty', 0) for f in recent_fills if f.get('side') == 'sell')

        total = buy_volume + sell_volume
        if total == 0:
            return 0.0

        return (buy_volume - sell_volume) / total

    def _calculate_spread_change(self, orderbook: Dict) -> float:
        """计算点差变化（相对于历史平均）"""
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if not bids or not asks:
            return 0.0

        current_spread = asks[0].get('price', 0) - bids[0].get('price', 0)

        # 与历史平均比较
        if len(self.feature_history) > 10:
            # 从历史特征中提取点差信息（简化）
            avg_spread = np.mean([h[4] for h in list(self.feature_history)[-10:]])
            if avg_spread > 0:
                return (current_spread - avg_spread) / avg_spread

        return 0.0

    def _calculate_price_velocity(self, orderbook: Dict) -> float:
        """计算价格速度"""
        # MVP简化：使用中间价变化
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if not bids or not asks:
            return 0.0

        mid_price = (bids[0].get('price', 0) + asks[0].get('price', 0)) / 2

        # 如果有历史数据，计算变化率
        if len(self.feature_history) > 1:
            prev_mid = list(self.feature_history)[-1][5]  # 简化：从特征中提取
            if prev_mid > 0:
                return (mid_price - prev_mid) / prev_mid

        return 0.0

    def _calculate_vpin(self, recent_fills: Optional[List]) -> float:
        """
        计算 VPIN (Volume-Synchronized Probability of Informed Trading)

        简化版本：高VPIN意味着知情交易者在活跃
        """
        if not recent_fills or len(recent_fills) < 5:
            return 0.0

        # 计算买卖不平衡的绝对值
        buy_volume = sum(f.get('qty', 0) for f in recent_fills if f.get('side') == 'buy')
        sell_volume = sum(f.get('qty', 0) for f in recent_fills if f.get('side') == 'sell')

        total = buy_volume + sell_volume
        if total == 0:
            return 0.0

        imbalance = abs(buy_volume - sell_volume) / total

        return imbalance

    def _calculate_queue_imbalance(self, orderbook: Dict) -> float:
        """计算队列不平衡"""
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if not bids or not asks:
            return 0.0

        # 第一档队列深度
        bid_depth = bids[0].get('qty', 0)
        ask_depth = asks[0].get('qty', 0)

        total = bid_depth + ask_depth
        if total == 0:
            return 0.0

        return (bid_depth - ask_depth) / total

    def _update_statistics(self):
        """更新统计参数（均值和协方差矩阵）"""
        if len(self.feature_history) < self.min_samples:
            return

        # 转换为numpy数组
        data = np.array(list(self.feature_history))

        # 计算均值
        self.mean_vector = np.mean(data, axis=0)

        # 计算协方差矩阵（使用正则化防止奇异）
        self.cov_matrix = np.cov(data, rowvar=False)

        # 添加小量正则化
        self.cov_matrix += np.eye(self.cov_matrix.shape[0]) * 1e-6

        # 计算逆矩阵
        try:
            self.inv_cov_matrix = np.linalg.inv(self.cov_matrix)
        except np.linalg.LinAlgError:
            # 如果不可逆，使用伪逆
            self.inv_cov_matrix = np.linalg.pinv(self.cov_matrix)

    def _mahalanobis_distance(self, features: np.ndarray) -> float:
        """计算马氏距离"""
        if self.mean_vector is None or self.inv_cov_matrix is None:
            return 0.0

        diff = features - self.mean_vector
        distance = np.sqrt(diff @ self.inv_cov_matrix @ diff)

        return float(distance)

    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            'alert_count': self.alert_count,
            'block_count': self.block_count,
            'sample_count': len(self.feature_history),
            'last_alert_time': self.last_alert_time,
            'consecutive_alerts': self.consecutive_alerts
        }

    def reset(self):
        """重置检测器"""
        self.feature_history.clear()
        self.fill_history.clear()
        self.mean_vector = None
        self.cov_matrix = None
        self.inv_cov_matrix = None
        self.alert_count = 0
        self.block_count = 0
        self.consecutive_alerts = 0


# 测试代码
if __name__ == "__main__":
    print("=" * 60)
    print("Toxic Flow Detector Test (MVP)")
    print("=" * 60)

    detector = ToxicFlowDetector(
        threshold=0.3,
        mahalanobis_threshold=5.0,
        min_samples=10
    )

    # 生成正常市场数据
    np.random.seed(42)

    print("\n填充初始样本（正常市场）...")
    for i in range(15):
        orderbook = {
            'bids': [
                {'price': 50000.0, 'qty': np.random.uniform(0.5, 2.0)},
                {'price': 49999.0, 'qty': np.random.uniform(1.0, 3.0)},
            ],
            'asks': [
                {'price': 50001.0, 'qty': np.random.uniform(0.5, 2.0)},
                {'price': 50002.0, 'qty': np.random.uniform(1.0, 3.0)},
            ]
        }

        alert = detector.detect(orderbook)
        if i >= 10:
            print(f"样本 {i+1}: distance={alert.mahalanobis_distance:.2f}, "
                  f"prob={alert.toxic_probability:.2f}, toxic={alert.is_toxic}")

    print("\n测试异常市场（毒流）...")
    print("-" * 60)

    # 生成异常数据（大单压盘）
    for i in range(5):
        orderbook = {
            'bids': [
                {'price': 50000.0, 'qty': 10.0},  # 异常大单
                {'price': 49999.0, 'qty': 2.0},
            ],
            'asks': [
                {'price': 50001.0, 'qty': 0.1},  # 卖盘稀少
                {'price': 50002.0, 'qty': 0.2},
            ]
        }

        recent_fills = [
            {'side': 'sell', 'qty': 5.0} for _ in range(10)  # 大量卖单成交
        ]

        alert = detector.detect(orderbook, recent_fills)
        print(f"异常检测 {i+1}: distance={alert.mahalanobis_distance:.2f}, "
              f"prob={alert.toxic_probability:.2f}, toxic={alert.is_toxic}, "
              f"reason={alert.reason}")

    print("\n恢复正常市场...")
    print("-" * 60)

    for i in range(5):
        orderbook = {
            'bids': [
                {'price': 50000.0, 'qty': np.random.uniform(0.5, 2.0)},
                {'price': 49999.0, 'qty': np.random.uniform(1.0, 3.0)},
            ],
            'asks': [
                {'price': 50001.0, 'qty': np.random.uniform(0.5, 2.0)},
                {'price': 50002.0, 'qty': np.random.uniform(1.0, 3.0)},
            ]
        }

        alert = detector.detect(orderbook)
        print(f"恢复检测 {i+1}: distance={alert.mahalanobis_distance:.2f}, "
              f"prob={alert.toxic_probability:.2f}, toxic={alert.is_toxic}")

    print("\n统计信息:")
    print("-" * 60)
    stats = detector.get_stats()
    print(f"总告警次数: {stats['alert_count']}")
    print(f"阻止次数: {stats['block_count']}")
    print(f"样本数: {stats['sample_count']}")

    print("\n" + "=" * 60)
    print("测试完成")
