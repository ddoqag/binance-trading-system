"""
Order Book Strategies - 订单簿策略模块
基于订单簿微观结构的高频交易策略
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Callable
from datetime import datetime, timedelta
from collections import deque
from enum import Enum
import logging

logger = logging.getLogger('OrderBookStrategy')


class SignalStrength(Enum):
    """信号强度"""
    WEAK = 0.3
    MODERATE = 0.6
    STRONG = 1.0


class OrderBookSignal(Enum):
    """订单簿信号类型"""
    BUY = 1
    SELL = -1
    HOLD = 0


@dataclass
class OrderBookLevel:
    """订单簿价格级别"""
    price: float
    quantity: float
    order_count: int = 0


@dataclass
class OrderBook:
    """订单簿数据结构"""
    symbol: str
    bids: List[OrderBookLevel] = field(default_factory=list)
    asks: List[OrderBookLevel] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    @property
    def mid_price(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return None

    @property
    def spread(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None

    @property
    def spread_bps(self) -> Optional[float]:
        """价差（基点）"""
        if self.spread and self.mid_price:
            return (self.spread / self.mid_price) * 10000
        return None

    def get_volume_at_price(self, price: float, side: str) -> float:
        """获取指定价格的成交量"""
        levels = self.bids if side == 'bid' else self.asks
        for level in levels:
            if abs(level.price - price) < 0.0001:
                return level.quantity
        return 0.0

    def get_cumulative_volume(self, side: str, depth: int = 5) -> float:
        """获取累计成交量"""
        levels = self.bids if side == 'bid' else self.asks
        return sum(level.quantity for level in levels[:depth])


@dataclass
class MicrostructureFeatures:
    """市场微观结构特征"""
    timestamp: datetime

    # 基础特征
    mid_price: float = 0.0
    spread: float = 0.0
    spread_bps: float = 0.0

    # 深度特征
    bid_volume_5: float = 0.0  # 前5档买单总量
    ask_volume_5: float = 0.0  # 前5档卖单总量
    total_volume_5: float = 0.0

    # 不平衡特征
    imbalance_5: float = 0.0   # 5档订单簿不平衡度 (-1 to 1)
    imbalance_10: float = 0.0  # 10档订单簿不平衡度

    # 压力特征
    bid_pressure: float = 0.0  # 买方压力
    ask_pressure: float = 0.0  # 卖方压力

    # 流动性特征
    liquidity_score: float = 0.0  # 流动性评分
    depth_imbalance: float = 0.0

    # 动态特征
    order_flow_imbalance: float = 0.0  # 订单流不平衡
    price_velocity: float = 0.0        # 价格速度
    trade_intensity: float = 0.0       # 交易强度

    @classmethod
    def from_orderbook(cls, orderbook: OrderBook, prev_features: Optional['MicrostructureFeatures'] = None) -> 'MicrostructureFeatures':
        """从订单簿计算特征"""
        features = cls(timestamp=orderbook.timestamp)

        if not orderbook.mid_price:
            return features

        # 基础特征
        features.mid_price = orderbook.mid_price
        features.spread = orderbook.spread or 0.0
        features.spread_bps = orderbook.spread_bps or 0.0

        # 深度特征
        features.bid_volume_5 = orderbook.get_cumulative_volume('bid', 5)
        features.ask_volume_5 = orderbook.get_cumulative_volume('ask', 5)
        features.total_volume_5 = features.bid_volume_5 + features.ask_volume_5

        # 不平衡特征
        if features.total_volume_5 > 0:
            features.imbalance_5 = (features.bid_volume_5 - features.ask_volume_5) / features.total_volume_5

        bid_vol_10 = orderbook.get_cumulative_volume('bid', 10)
        ask_vol_10 = orderbook.get_cumulative_volume('ask', 10)
        total_vol_10 = bid_vol_10 + ask_vol_10
        if total_vol_10 > 0:
            features.imbalance_10 = (bid_vol_10 - ask_vol_10) / total_vol_10

        # 压力特征 (基于订单簿深度)
        features.bid_pressure = features.imbalance_5 * np.log1p(features.bid_volume_5)
        features.ask_pressure = -features.imbalance_5 * np.log1p(features.ask_volume_5)

        # 流动性评分
        if features.spread > 0:
            features.liquidity_score = np.log1p(features.total_volume_5) / features.spread

        # 动态特征 (需要历史数据)
        if prev_features:
            dt = (features.timestamp - prev_features.timestamp).total_seconds()
            if dt > 0:
                features.price_velocity = (features.mid_price - prev_features.mid_price) / dt

        return features


class OrderBookStrategy:
    """
    订单簿策略基类

    基于订单簿微观结构生成交易信号
    """

    def __init__(self, name: str = "OrderBookStrategy"):
        self.name = name
        self.features_history = deque(maxlen=1000)
        self.last_signal = OrderBookSignal.HOLD
        self.signal_count = 0

    def generate_signal(
        self,
        orderbook: OrderBook,
        trade_history: Optional[List[Dict]] = None
    ) -> Tuple[OrderBookSignal, float]:
        """
        生成交易信号

        Args:
            orderbook: 当前订单簿
            trade_history: 近期交易历史

        Returns:
            (信号方向, 信号强度 0-1)
        """
        raise NotImplementedError

    def _update_features(self, features: MicrostructureFeatures):
        """更新特征历史"""
        self.features_history.append(features)


class ImbalanceStrategy(OrderBookStrategy):
    """
    订单簿不平衡策略

    利用订单簿买卖不平衡预测短期价格走势
    """

    def __init__(
        self,
        imbalance_threshold: float = 0.3,
        confirmation_periods: int = 2,
        min_liquidity_score: float = 100.0
    ):
        super().__init__("ImbalanceStrategy")
        self.imbalance_threshold = imbalance_threshold
        self.confirmation_periods = confirmation_periods
        self.min_liquidity_score = min_liquidity_score

    def generate_signal(
        self,
        orderbook: OrderBook,
        trade_history: Optional[List[Dict]] = None
    ) -> Tuple[OrderBookSignal, float]:
        """基于订单簿不平衡生成信号"""
        prev_features = self.features_history[-1] if self.features_history else None
        features = MicrostructureFeatures.from_orderbook(orderbook, prev_features)
        self._update_features(features)

        # 检查流动性
        if features.liquidity_score < self.min_liquidity_score:
            return OrderBookSignal.HOLD, 0.0

        # 检查价差
        if features.spread_bps and features.spread_bps > 10:  # 价差大于10bps
            return OrderBookSignal.HOLD, 0.0

        # 计算信号
        signal = OrderBookSignal.HOLD
        strength = 0.0

        # 基于不平衡度
        if features.imbalance_5 > self.imbalance_threshold:
            signal = OrderBookSignal.BUY
            strength = min(abs(features.imbalance_5), 1.0)
        elif features.imbalance_5 < -self.imbalance_threshold:
            signal = OrderBookSignal.SELL
            strength = min(abs(features.imbalance_5), 1.0)

        # 确认信号 (检查历史)
        if len(self.features_history) >= self.confirmation_periods:
            recent_imbalances = [f.imbalance_5 for f in list(self.features_history)[-self.confirmation_periods:]]

            if signal == OrderBookSignal.BUY:
                # 需要连续买方压力
                if not all(i > 0 for i in recent_imbalances):
                    signal = OrderBookSignal.HOLD
                    strength = 0.0
            elif signal == OrderBookSignal.SELL:
                # 需要连续卖方压力
                if not all(i < 0 for i in recent_imbalances):
                    signal = OrderBookSignal.HOLD
                    strength = 0.0

        self.last_signal = signal
        if signal != OrderBookSignal.HOLD:
            self.signal_count += 1

        return signal, strength


class SpreadCaptureStrategy(OrderBookStrategy):
    """
    价差捕捉策略

    利用大价差进行做市/套利
    """

    def __init__(
        self,
        min_spread_bps: float = 5.0,
        max_spread_bps: float = 50.0,
        mean_reversion_factor: float = 0.5
    ):
        super().__init__("SpreadCaptureStrategy")
        self.min_spread_bps = min_spread_bps
        self.max_spread_bps = max_spread_bps
        self.mean_reversion_factor = mean_reversion_factor
        self.spread_history = deque(maxlen=100)

    def generate_signal(
        self,
        orderbook: OrderBook,
        trade_history: Optional[List[Dict]] = None
    ) -> Tuple[OrderBookSignal, float]:
        """基于价差生成信号"""
        if not orderbook.spread_bps:
            return OrderBookSignal.HOLD, 0.0

        self.spread_history.append(orderbook.spread_bps)

        if len(self.spread_history) < 20:
            return OrderBookSignal.HOLD, 0.0

        current_spread = orderbook.spread_bps
        avg_spread = np.mean(list(self.spread_history))

        # 价差过大，可能回归
        if current_spread > self.max_spread_bps:
            # 价差过大，观望
            return OrderBookSignal.HOLD, 0.0

        # 价差在可交易范围内
        if current_spread > self.min_spread_bps:
            # 价差扩大，可能有趋势
            # 简化为不交易，实际可以复杂化
            return OrderBookSignal.HOLD, 0.3

        return OrderBookSignal.HOLD, 0.0


class MomentumImbalanceStrategy(OrderBookStrategy):
    """
    动量+不平衡混合策略

    结合订单流和订单簿不平衡
    """

    def __init__(
        self,
        imbalance_weight: float = 0.5,
        flow_weight: float = 0.5,
        threshold: float = 0.4
    ):
        super().__init__("MomentumImbalanceStrategy")
        self.imbalance_weight = imbalance_weight
        self.flow_weight = flow_weight
        self.threshold = threshold
        self.trade_history_buffer = deque(maxlen=100)

    def generate_signal(
        self,
        orderbook: OrderBook,
        trade_history: Optional[List[Dict]] = None
    ) -> Tuple[OrderBookSignal, float]:
        """综合动量和不平衡信号"""
        prev_features = self.features_history[-1] if self.features_history else None
        features = MicrostructureFeatures.from_orderbook(orderbook, prev_features)

        # 更新交易历史
        if trade_history:
            self.trade_history_buffer.extend(trade_history)

        # 计算订单流不平衡
        flow_imbalance = self._calculate_flow_imbalance()
        features.order_flow_imbalance = flow_imbalance

        self._update_features(features)

        # 综合评分
        score = (
            self.imbalance_weight * features.imbalance_5 +
            self.flow_weight * flow_imbalance
        )

        # 生成信号
        if score > self.threshold:
            signal = OrderBookSignal.BUY
            strength = min(score, 1.0)
        elif score < -self.threshold:
            signal = OrderBookSignal.SELL
            strength = min(abs(score), 1.0)
        else:
            signal = OrderBookSignal.HOLD
            strength = 0.0

        return signal, strength

    def _calculate_flow_imbalance(self) -> float:
        """计算订单流不平衡"""
        if len(self.trade_history_buffer) < 10:
            return 0.0

        buy_volume = sum(
            t.get('volume', 0) for t in self.trade_history_buffer
            if t.get('side') == 'buy'
        )
        sell_volume = sum(
            t.get('volume', 0) for t in self.trade_history_buffer
            if t.get('side') == 'sell'
        )

        total = buy_volume + sell_volume
        if total > 0:
            return (buy_volume - sell_volume) / total
        return 0.0


class OrderBookStrategyManager:
    """
    订单簿策略管理器

    管理多个订单簿策略，综合生成信号
    """

    def __init__(self):
        self.strategies: Dict[str, OrderBookStrategy] = {}
        self.weights: Dict[str, float] = {}
        self.signals_history = deque(maxlen=1000)

    def register_strategy(
        self,
        name: str,
        strategy: OrderBookStrategy,
        weight: float = 1.0
    ):
        """注册策略"""
        self.strategies[name] = strategy
        self.weights[name] = weight
        logger.info(f"Registered orderbook strategy: {name}")

    def generate_combined_signal(
        self,
        orderbook: OrderBook,
        trade_history: Optional[List[Dict]] = None
    ) -> Tuple[OrderBookSignal, float, Dict[str, Any]]:
        """
        生成综合信号

        Returns:
            (信号, 强度, 详细信息)
        """
        weighted_score = 0.0
        total_weight = 0.0
        individual_signals = {}

        for name, strategy in self.strategies.items():
            signal, strength = strategy.generate_signal(orderbook, trade_history)
            weight = self.weights.get(name, 1.0)

            # 转换为数值
            signal_value = signal.value * strength

            weighted_score += signal_value * weight
            total_weight += weight

            individual_signals[name] = {
                'signal': signal.name,
                'strength': strength,
                'weight': weight
            }

        if total_weight == 0:
            return OrderBookSignal.HOLD, 0.0, individual_signals

        # 归一化
        final_score = weighted_score / total_weight

        # 确定最终信号
        if final_score > 0.2:
            final_signal = OrderBookSignal.BUY
            final_strength = min(final_score, 1.0)
        elif final_score < -0.2:
            final_signal = OrderBookSignal.SELL
            final_strength = min(abs(final_score), 1.0)
        else:
            final_signal = OrderBookSignal.HOLD
            final_strength = 0.0

        result = {
            'individual_signals': individual_signals,
            'weighted_score': final_score,
            'total_weight': total_weight,
            'features': self._extract_features(orderbook)
        }

        self.signals_history.append({
            'timestamp': datetime.now(),
            'signal': final_signal.name,
            'strength': final_strength
        })

        return final_signal, final_strength, result

    def _extract_features(self, orderbook: OrderBook) -> Dict[str, float]:
        """提取关键特征"""
        return {
            'mid_price': orderbook.mid_price or 0.0,
            'spread_bps': orderbook.spread_bps or 0.0,
            'bid_volume_5': orderbook.get_cumulative_volume('bid', 5),
            'ask_volume_5': orderbook.get_cumulative_volume('ask', 5),
        }

    def update_strategy_weight(self, name: str, weight: float):
        """更新策略权重"""
        if name in self.weights:
            self.weights[name] = weight

    def get_strategy_performance(self) -> Dict[str, Any]:
        """获取策略表现"""
        performance = {}
        for name, strategy in self.strategies.items():
            performance[name] = {
                'signal_count': strategy.signal_count,
                'last_signal': strategy.last_signal.name
            }
        return performance


def create_default_orderbook_manager() -> OrderBookStrategyManager:
    """创建默认的订单簿策略管理器"""
    manager = OrderBookStrategyManager()

    # 注册不平衡策略
    manager.register_strategy(
        "imbalance",
        ImbalanceStrategy(imbalance_threshold=0.25),
        weight=1.0
    )

    # 注册动量不平衡策略
    manager.register_strategy(
        "momentum_imbalance",
        MomentumImbalanceStrategy(threshold=0.3),
        weight=0.8
    )

    return manager
