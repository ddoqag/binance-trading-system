"""
Predictive Microprice Alpha - 预测性微观价格Alpha

核心功能：
1. 基于订单簿失衡、价格速度、成交量压力预测短期价格方向
2. 生成非对称报价（skew quotes）捕获更多点差
3. 与FillQualityAnalyzer集成，验证预测有效性
"""

import time
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from collections import deque
import logging

logger = logging.getLogger('PredictiveMicropriceAlpha')


@dataclass
class AlphaSignal:
    """Alpha信号"""
    value: float  # -1.0 to +1.0, 正值表示看涨
    confidence: float  # 0.0 to 1.0
    components: Dict[str, float]  # 各组成部分
    timestamp: float


@dataclass
class SkewQuote:
    """非对称报价"""
    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float
    alpha_value: float
    reasoning: str


class PredictiveMicropriceAlpha:
    """
    预测性微观价格Alpha生成器

    核心逻辑：
    - 订单簿失衡 (60%): 买卖盘力量对比
    - 价格速度 (30%): 近期价格变化方向
    - 成交量压力 (10%): 大单压力方向
    """

    def __init__(self,
                 imbalance_weight: float = 0.6,
                 velocity_weight: float = 0.3,
                 pressure_weight: float = 0.1,
                 history_window: int = 20):

        self.weights = {
            'imbalance': imbalance_weight,
            'velocity': velocity_weight,
            'pressure': pressure_weight
        }

        self.price_history = deque(maxlen=history_window)
        self.volume_history = deque(maxlen=history_window)
        self.alpha_history = deque(maxlen=100)

        # 统计指标
        self.prediction_accuracy = {'correct': 0, 'total': 0}

    def calculate_predictive_alpha(self, orderbook: Dict) -> AlphaSignal:
        """
        计算预测性Alpha值

        Returns:
            AlphaSignal: 包含alpha值、置信度和组成成分
        """
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if not bids or not asks:
            return AlphaSignal(0.0, 0.0, {}, time.time())

        best_bid = bids[0].get('price', 0)
        best_ask = asks[0].get('price', 0)
        mid_price = (best_bid + best_ask) / 2

        # 1. 订单簿失衡 (60%)
        imbalance_alpha = self._calculate_imbalance(bids, asks)

        # 2. 价格速度 (30%)
        velocity_alpha = self._calculate_velocity(mid_price)

        # 3. 成交量压力 (10%)
        pressure_alpha = self._calculate_pressure(bids, asks)

        # 加权组合
        alpha_value = (
            imbalance_alpha * self.weights['imbalance'] +
            velocity_alpha * self.weights['velocity'] +
            pressure_alpha * self.weights['pressure']
        )

        # 置信度基于数据质量
        confidence = self._calculate_confidence(
            imbalance_alpha, velocity_alpha, pressure_alpha
        )

        # 记录历史
        self.price_history.append(mid_price)
        signal = AlphaSignal(
            value=alpha_value,
            confidence=confidence,
            components={
                'imbalance': imbalance_alpha,
                'velocity': velocity_alpha,
                'pressure': pressure_alpha
            },
            timestamp=time.time()
        )
        self.alpha_history.append(signal)

        return signal

    def _calculate_imbalance(self, bids: List[Dict], asks: List[Dict]) -> float:
        """计算订单簿失衡 (-1 to +1)"""
        # L1-L3加权
        bid_volume = sum(b.get('qty', 0) / (i + 1) for i, b in enumerate(bids[:3]))
        ask_volume = sum(a.get('qty', 0) / (i + 1) for i, a in enumerate(asks[:3]))

        total = bid_volume + ask_volume
        if total == 0:
            return 0.0

        # 归一化到 [-1, 1]
        imbalance = (bid_volume - ask_volume) / total

        # 非线性压缩 (sigmoid-like)
        return np.tanh(imbalance * 2)

    def _calculate_velocity(self, mid_price: float) -> float:
        """计算价格速度 (-1 to +1)"""
        if len(self.price_history) < 5:
            return 0.0

        # 近期价格变化
        recent_prices = list(self.price_history)[-5:]
        if len(recent_prices) < 2:
            return 0.0

        # 线性回归斜率
        x = np.arange(len(recent_prices))
        y = np.array(recent_prices)
        slope = np.polyfit(x, y, 1)[0]

        # 归一化 (假设最大合理速度为0.1% per tick)
        max_slope = mid_price * 0.001
        normalized_slope = np.clip(slope / max_slope, -1, 1)

        return normalized_slope

    def _calculate_pressure(self, bids: List[Dict], asks: List[Dict]) -> float:
        """计算成交量压力 (-1 to +1)"""
        # 检查大单压力
        large_bid_pressure = sum(
            b.get('qty', 0) for b in bids[:2]
            if b.get('qty', 0) > 1.0  # 大于1个BTC的订单
        )
        large_ask_pressure = sum(
            a.get('qty', 0) for a in asks[:2]
            if a.get('qty', 0) > 1.0
        )

        total_pressure = large_bid_pressure + large_ask_pressure
        if total_pressure == 0:
            return 0.0

        pressure = (large_bid_pressure - large_ask_pressure) / total_pressure
        return np.tanh(pressure * 3)

    def _calculate_confidence(self, *components: float) -> float:
        """计算置信度"""
        # 基于信号强度和一致性
        abs_values = [abs(c) for c in components]
        avg_strength = np.mean(abs_values)

        # 方向一致性
        signs = [np.sign(c) for c in components if abs(c) > 0.1]
        if len(signs) > 1:
            consistency = abs(sum(signs)) / len(signs)
        else:
            consistency = 0.5

        return min(avg_strength * consistency * 2, 1.0)

    def get_skew_quotes(self,
                        orderbook: Dict,
                        base_spread_ticks: int = 2,
                        tick_size: float = 0.01,
                        max_skew_ticks: int = 2) -> Optional[SkewQuote]:
        """
        生成非对称报价

        Args:
            orderbook: 订单簿数据
            base_spread_ticks: 基础点差tick数
            tick_size: tick大小
            max_skew_ticks: 最大偏斜tick数

        Returns:
            SkewQuote: 非对称报价，如果alpha太弱返回None
        """
        signal = self.calculate_predictive_alpha(orderbook)

        # Alpha太弱，不做偏斜
        if abs(signal.value) < 0.3 or signal.confidence < 0.5:
            return None

        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if not bids or not asks:
            return None

        best_bid = bids[0].get('price', 0)
        best_ask = asks[0].get('price', 0)
        mid_price = (best_bid + best_ask) / 2

        # 计算偏斜量
        skew_ticks = int(abs(signal.value) * max_skew_ticks)
        skew_ticks = min(skew_ticks, max_skew_ticks)

        if signal.value > 0:  # 看涨信号
            # 抬高价差（更容易成交买单，更难成交卖单）
            bid_price = best_bid + skew_ticks * tick_size * 0.5
            ask_price = best_ask + skew_ticks * tick_size
            bid_size = 0.5  # 减少买单量
            ask_size = 1.0  # 增加卖单量
            reasoning = f"Bullish alpha={signal.value:.2f}, skew +{skew_ticks}ticks"
        else:  # 看跌信号
            # 降低价差（更容易成交卖单，更难成交买单）
            bid_price = best_bid - skew_ticks * tick_size
            ask_price = best_ask - skew_ticks * tick_size * 0.5
            bid_size = 1.0  # 增加买单量
            ask_size = 0.5  # 减少卖单量
            reasoning = f"Bearish alpha={signal.value:.2f}, skew -{skew_ticks}ticks"

        return SkewQuote(
            bid_price=bid_price,
            ask_price=ask_price,
            bid_size=bid_size,
            ask_size=ask_size,
            alpha_value=signal.value,
            reasoning=reasoning
        )

    def validate_predictions(self,
                            fill_analyzer,
                            lookback_seconds: int = 5) -> Dict:
        """
        验证Alpha预测准确性

        Args:
            fill_analyzer: FillQualityAnalyzer实例
            lookback_seconds: 验证窗口

        Returns:
            验证结果统计
        """
        if not fill_analyzer.trades:
            return {'status': 'NO_DATA'}

        correct_predictions = 0
        total_predictions = 0

        for trade in fill_analyzer.trades:
            # 找到交易时的Alpha信号
            trade_alpha = None
            for alpha in self.alpha_history:
                if abs(alpha.timestamp - trade.timestamp) < 1.0:
                    trade_alpha = alpha
                    break

            if trade_alpha is None or lookback_seconds not in trade.post_fill_prices:
                continue

            # 验证预测
            predicted_direction = np.sign(trade_alpha.value)
            price_change = trade.post_fill_prices[lookback_seconds] - trade.mid_price_at_fill
            actual_direction = np.sign(price_change)

            if predicted_direction == actual_direction and predicted_direction != 0:
                correct_predictions += 1
            total_predictions += 1

        if total_predictions == 0:
            return {'status': 'INSUFFICIENT_DATA'}

        accuracy = correct_predictions / total_predictions

        return {
            'status': 'OK',
            'accuracy': accuracy,
            'correct': correct_predictions,
            'total': total_predictions,
            'is_predictive': accuracy > 0.55  # 超过随机水平
        }

    def get_signal_summary(self) -> str:
        """获取信号摘要"""
        if not self.alpha_history:
            return "[No Alpha Data]"

        latest = self.alpha_history[-1]
        direction = "BULLISH" if latest.value > 0.3 else "BEARISH" if latest.value < -0.3 else "NEUTRAL"

        return f"[{direction}] α={latest.value:+.2f}, conf={latest.confidence:.2f}"


# 测试代码
if __name__ == "__main__":
    import time

    print("="*70)
    print("Predictive Microprice Alpha Test")
    print("="*70)

    alpha_gen = PredictiveMicropriceAlpha()

    # 测试1: 买方强势场景
    print("\n测试1: 买方强势（大量买盘，价格上升）")
    print("-"*70)

    ob_bullish = {
        'bids': [
            {'price': 50000.0, 'qty': 5.0},   # 大量买盘
            {'price': 49999.5, 'qty': 3.0},
            {'price': 49999.0, 'qty': 2.0},
        ],
        'asks': [
            {'price': 50001.0, 'qty': 0.5},   # 少量卖盘
            {'price': 50002.0, 'qty': 0.3},
        ]
    }

    # 模拟价格上升趋势
    for price in [49990, 49995, 49998, 50000]:
        alpha_gen.price_history.append(price)

    signal = alpha_gen.calculate_predictive_alpha(ob_bullish)
    print(f"Alpha Value: {signal.value:+.3f}")
    print(f"Confidence: {signal.confidence:.3f}")
    print(f"Components: {signal.components}")

    skew = alpha_gen.get_skew_quotes(ob_bullish, base_spread_ticks=2, tick_size=0.01)
    if skew:
        print(f"\nSkew Quote:")
        print(f"  Bid: {skew.bid_price:.2f} x {skew.bid_size}")
        print(f"  Ask: {skew.ask_price:.2f} x {skew.ask_size}")
        print(f"  Reasoning: {skew.reasoning}")

    # 测试2: 卖方强势场景
    print("\n测试2: 卖方强势（大量卖盘，价格下跌）")
    print("-"*70)

    alpha_gen2 = PredictiveMicropriceAlpha()

    ob_bearish = {
        'bids': [
            {'price': 50000.0, 'qty': 0.5},   # 少量买盘
            {'price': 49999.0, 'qty': 0.3},
        ],
        'asks': [
            {'price': 50001.0, 'qty': 5.0},   # 大量卖盘
            {'price': 50002.0, 'qty': 3.0},
            {'price': 50003.0, 'qty': 2.0},
        ]
    }

    # 模拟价格下降趋势
    for price in [50010, 50005, 50002, 50000]:
        alpha_gen2.price_history.append(price)

    signal2 = alpha_gen2.calculate_predictive_alpha(ob_bearish)
    print(f"Alpha Value: {signal2.value:+.3f}")
    print(f"Confidence: {signal2.confidence:.3f}")
    print(f"Components: {signal2.components}")

    skew2 = alpha_gen2.get_skew_quotes(ob_bearish, base_spread_ticks=2, tick_size=0.01)
    if skew2:
        print(f"\nSkew Quote:")
        print(f"  Bid: {skew2.bid_price:.2f} x {skew2.bid_size}")
        print(f"  Ask: {skew2.ask_price:.2f} x {skew2.ask_size}")
        print(f"  Reasoning: {skew2.reasoning}")

    # 测试3: 平衡市场
    print("\n测试3: 平衡市场")
    print("-"*70)

    alpha_gen3 = PredictiveMicropriceAlpha()

    ob_neutral = {
        'bids': [
            {'price': 50000.0, 'qty': 1.0},
            {'price': 49999.0, 'qty': 1.0},
        ],
        'asks': [
            {'price': 50001.0, 'qty': 1.0},
            {'price': 50002.0, 'qty': 1.0},
        ]
    }

    signal3 = alpha_gen3.calculate_predictive_alpha(ob_neutral)
    print(f"Alpha Value: {signal3.value:+.3f}")
    print(f"Confidence: {signal3.confidence:.3f}")
    print(f"Skew generated: {alpha_gen3.get_skew_quotes(ob_neutral) is not None}")

    print("\n" + "="*70)
    print("Test completed")
