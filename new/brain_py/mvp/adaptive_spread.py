"""
动态点差自适应模块

根据市场微观结构实时调整策略参数
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import deque
import time


@dataclass
class MarketMicrostructure:
    """市场微观结构数据"""
    spread_bps: float
    spread_ticks: int
    imbalance: float  # 订单簿不平衡 [-1, 1]
    queue_depth_bid: float
    queue_depth_ask: float
    trade_flow_ratio: float  # 买卖成交比
    volatility: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class AdaptiveParameters:
    """自适应参数"""
    min_spread_ticks: int
    min_confidence: float
    max_position: float
    quote_aggression: float  # 0=被动, 1=主动
    reason: str = ""


class AdaptiveSpreadManager:
    """
    动态点差管理器

    核心逻辑：
    1. 监控实际成交的PnL结构
    2. 动态调整最小点差阈值
    3. 根据市场状态切换策略模式
    """

    def __init__(self,
                 base_min_spread: int = 2,
                 adaptation_window: int = 50,  # 基于最近50次检查调整
                 min_spread_floor: int = 1,    # 最小不能低于1 tick
                 max_spread_ceil: int = 5):    # 最大不能超过5 ticks

        self.base_min_spread = base_min_spread
        self.current_min_spread = base_min_spread
        self.adaptation_window = adaptation_window
        self.min_spread_floor = min_spread_floor
        self.max_spread_ceil = max_spread_ceil

        # 历史数据
        self.spread_history = deque(maxlen=adaptation_window)
        self.trade_history = deque(maxlen=adaptation_window)
        self.microstructure_history = deque(maxlen=adaptation_window)

        # 性能统计
        self.performance_metrics = {
            'opportunities_seen': 0,
            'opportunities_taken': 0,
            'estimated_edge_bps': 0.0,
            'realized_edge_bps': 0.0,
            'regime': 'unknown'
        }

    def analyze_market(self, orderbook: Dict, recent_trades: List[Dict] = None) -> MarketMicrostructure:
        """
        分析市场微观结构
        """
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if not bids or not asks:
            return MarketMicrostructure(0, 0, 0, 0, 0, 0, 0)

        best_bid = bids[0].get('price', 0)
        best_ask = asks[0].get('price', 0)
        mid_price = (best_bid + best_ask) / 2

        # 计算点差
        spread = best_ask - best_bid
        spread_bps = (spread / mid_price) * 10000

        # 计算tick大小（根据价格推断）
        if mid_price > 10000:
            tick_size = 0.01  # BTC/ETH
        elif mid_price > 100:
            tick_size = 0.01  # 中等价格
        else:
            tick_size = 0.001  # 低价币

        spread_ticks = int(round(spread / tick_size))

        # 计算订单簿不平衡
        bid_volume = sum(b.get('qty', 0) for b in bids[:5])
        ask_volume = sum(a.get('qty', 0) for a in asks[:5])
        total_volume = bid_volume + ask_volume

        if total_volume > 0:
            imbalance = (bid_volume - ask_volume) / total_volume
        else:
            imbalance = 0

        # 计算成交流比率
        trade_flow_ratio = self._calculate_trade_flow_ratio(recent_trades)

        # 计算波动率（基于点差历史）
        volatility = self._estimate_volatility()

        micro = MarketMicrostructure(
            spread_bps=spread_bps,
            spread_ticks=spread_ticks,
            imbalance=imbalance,
            queue_depth_bid=bid_volume,
            queue_depth_ask=ask_volume,
            trade_flow_ratio=trade_flow_ratio,
            volatility=volatility
        )

        self.microstructure_history.append(micro)
        self.spread_history.append(spread_bps)

        return micro

    def calculate_adaptive_parameters(self,
                                     microstructure: MarketMicrostructure,
                                     current_pnl: float = 0,
                                     trade_count: int = 0) -> AdaptiveParameters:
        """
        计算自适应参数

        核心逻辑：
        1. 如果市场点差持续 < min_spread，提高阈值或切换模式
        2. 如果有成交但PnL为负，提高阈值
        3. 如果检测到高波动/毒流，提高置信度要求
        """
        self.performance_metrics['opportunities_seen'] += 1

        # 基础参数
        min_spread = self.current_min_spread
        min_confidence = 0.7
        max_position = 0.5
        quote_aggression = 0.0  # 默认被动
        reasons = []

        # 规则1: 点差压缩检测
        if microstructure.spread_ticks < self.current_min_spread:
            # 市场点差太紧，我们的阈值可能太高
            if len(self.spread_history) >= 10:
                avg_spread = np.mean(list(self.spread_history)[-10:])
                if avg_spread < microstructure.spread_bps * 1.5:
                    # 点差持续压缩，降低阈值或切换为主动模式
                    if self.current_min_spread > self.min_spread_floor:
                        min_spread = self.current_min_spread - 1
                        reasons.append(f"spread_compression: {microstructure.spread_ticks}ticks < {self.current_min_spread}")
                    else:
                        # 已经无法再降低，切换为主动报价模式
                        quote_aggression = 0.3
                        reasons.append("spread_compressed_switching_to_aggressive")

        # 规则2: 基于PnL的调整
        if trade_count > 10 and current_pnl < 0:
            # 最近亏损，提高要求
            min_spread = min(self.current_min_spread + 1, self.max_spread_ceil)
            min_confidence = 0.8
            reasons.append(f"negative_pnl: ${current_pnl:.2f}")

        # 规则3: 订单簿不平衡
        if abs(microstructure.imbalance) > 0.6:
            # 严重不平衡，可能是单边行情
            min_confidence = 0.85
            max_position = 0.3  # 降低仓位
            reasons.append(f"high_imbalance: {microstructure.imbalance:.2f}")

        # 规则4: 毒流检测
        if abs(microstructure.trade_flow_ratio) > 0.7:
            # 成交流向一边倒
            min_confidence = 0.9
            quote_aggression = 0.5  # 更主动
            reasons.append(f"toxic_flow: ratio={microstructure.trade_flow_ratio:.2f}")

        # 规则5: 高波动
        if microstructure.volatility > 20:  # 20 bps
            min_confidence = 0.8
            max_position = 0.3
            reasons.append(f"high_vol: {microstructure.volatility:.1f}bps")

        # 更新当前阈值（渐进调整）
        if min_spread != self.current_min_spread:
            # 渐进调整，不要跳变
            if min_spread > self.current_min_spread:
                self.current_min_spread = min(self.current_min_spread + 1, min_spread)
            else:
                self.current_min_spread = max(self.current_min_spread - 1, min_spread)

        # 确定市场状态
        self.performance_metrics['regime'] = self._classify_regime(microstructure)

        return AdaptiveParameters(
            min_spread_ticks=self.current_min_spread,
            min_confidence=min_confidence,
            max_position=max_position,
            quote_aggression=quote_aggression,
            reason="; ".join(reasons) if reasons else "default"
        )

    def _calculate_trade_flow_ratio(self, recent_trades: List[Dict]) -> float:
        """计算成交流向比率"""
        if not recent_trades or len(recent_trades) < 5:
            return 0.0

        buy_volume = sum(t.get('qty', 0) for t in recent_trades if t.get('side') == 'buy')
        sell_volume = sum(t.get('qty', 0) for t in recent_trades if t.get('side') == 'sell')
        total = buy_volume + sell_volume

        if total == 0:
            return 0.0

        return (buy_volume - sell_volume) / total

    def _estimate_volatility(self) -> float:
        """估算波动率"""
        if len(self.spread_history) < 10:
            return 0.0

        recent = list(self.spread_history)[-10:]
        return np.std(recent)

    def _classify_regime(self, micro: MarketMicrostructure) -> str:
        """分类市场状态"""
        if micro.spread_ticks <= 1 and micro.volatility < 10:
            return "hft_compressed"
        elif abs(micro.imbalance) > 0.6:
            return "trending"
        elif micro.volatility > 30:
            return "volatile"
        elif micro.spread_ticks >= 3:
            return "profitable_mm"
        else:
            return "normal"

    def get_recommended_strategy(self, regime: str) -> str:
        """根据市场状态推荐策略"""
        recommendations = {
            'hft_compressed': 'aggressive_micro_alpha',
            'trending': 'momentum_following',
            'volatile': ' defensive_quoting',
            'profitable_mm': 'passive_market_making',
            'normal': 'mixed_strategy'
        }
        return recommendations.get(regime, 'hold')

    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            'current_min_spread': self.current_min_spread,
            'base_min_spread': self.base_min_spread,
            'performance': self.performance_metrics,
            'history_size': len(self.microstructure_history)
        }


class MicropriceAlpha:
    """
    Microprice Alpha 生成器

    基于订单簿微观结构预测短期价格方向
    """

    def __init__(self,
                 imbalance_weight: float = 0.5,
                 trade_flow_weight: float = 0.3,
                 momentum_weight: float = 0.2):

        self.weights = {
            'imbalance': imbalance_weight,
            'trade_flow': trade_flow_weight,
            'momentum': momentum_weight
        }

        self.price_history = deque(maxlen=20)
        self.alpha_history = deque(maxlen=100)

    def calculate_microprice(self, orderbook: Dict) -> Tuple[float, float]:
        """
        计算微观价格和置信度

        Returns:
            (microprice, confidence)
        """
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if not bids or not asks:
            return 0.0, 0.0

        best_bid = bids[0].get('price', 0)
        best_ask = asks[0].get('price', 0)
        mid_price = (best_bid + best_ask) / 2

        # 计算订单簿不平衡
        bid_volume = sum(b.get('qty', 0) for b in bids[:5])
        ask_volume = sum(a.get('qty', 0) for a in asks[:5])
        total_volume = bid_volume + ask_volume

        if total_volume == 0:
            return mid_price, 0.0

        imbalance = (bid_volume - ask_volume) / total_volume

        # 计算microprice
        # 如果买方更强，microprice偏向ask
        # 如果卖方更强，microprice偏向bid
        half_spread = (best_ask - best_bid) / 2
        microprice = mid_price + half_spread * imbalance * self.weights['imbalance']

        # 计算置信度（基于数据质量）
        confidence = min(abs(imbalance) * 2, 1.0)  # 不平衡越大，置信度越高

        # 记录
        self.price_history.append(microprice)
        self.alpha_history.append({
            'microprice': microprice,
            'mid_price': mid_price,
            'imbalance': imbalance,
            'confidence': confidence
        })

        return microprice, confidence

    def generate_signal(self, orderbook: Dict) -> Dict:
        """
        生成交易信号

        Returns:
            {
                'direction': 1 (buy), -1 (sell), or 0 (hold)
                'strength': 0.0-1.0
                'expected_edge_bps': float
                'reason': str
            }
        """
        microprice, confidence = self.calculate_microprice(orderbook)

        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if not bids or not asks:
            return {'direction': 0, 'strength': 0, 'expected_edge_bps': 0, 'reason': 'no_data'}

        best_bid = bids[0].get('price', 0)
        best_ask = asks[0].get('price', 0)
        mid_price = (best_bid + best_ask) / 2

        # 计算预期边缘
        edge = microprice - mid_price
        edge_bps = (edge / mid_price) * 10000

        # 信号方向
        if edge_bps > 0.5 and confidence > 0.6:
            return {
                'direction': 1,  # buy
                'strength': confidence,
                'expected_edge_bps': edge_bps,
                'reason': f'microprice_above_mid: {edge_bps:.2f}bps'
            }
        elif edge_bps < -0.5 and confidence > 0.6:
            return {
                'direction': -1,  # sell
                'strength': confidence,
                'expected_edge_bps': abs(edge_bps),
                'reason': f'microprice_below_mid: {edge_bps:.2f}bps'
            }
        else:
            return {
                'direction': 0,
                'strength': 0,
                'expected_edge_bps': abs(edge_bps),
                'reason': f'weak_signal: edge={edge_bps:.2f}bps, conf={confidence:.2f}'
            }


# 测试代码
if __name__ == "__main__":
    print("=" * 60)
    print("Adaptive Spread Manager Test")
    print("=" * 60)

    # 测试自适应管理器
    manager = AdaptiveSpreadManager(base_min_spread=2)

    # 模拟点差压缩的市场
    print("\n测试1: 点差压缩场景")
    print("-" * 60)

    for i in range(20):
        # 模拟BTC市场，点差始终为1 tick
        ob = {
            'bids': [{'price': 50000.0, 'qty': 1.0}],
            'asks': [{'price': 50000.01, 'qty': 1.0}]
        }

        micro = manager.analyze_market(ob)
        params = manager.calculate_adaptive_parameters(micro)

        if i % 5 == 0:
            print(f"Tick {i}: spread={micro.spread_ticks}ticks, "
                  f"min_spread={params.min_spread_ticks}, "
                  f"regime={manager.performance_metrics['regime']}")

    print(f"\n最终参数: min_spread={params.min_spread_ticks}, "
          f"aggression={params.quote_aggression:.2f}")

    # 测试microprice alpha
    print("\n测试2: Microprice Alpha")
    print("-" * 60)

    alpha_gen = MicropriceAlpha()

    # 场景1: 买方强势
    ob_imbalanced = {
        'bids': [
            {'price': 50000.0, 'qty': 10.0},  # 大量买盘
            {'price': 49999.0, 'qty': 5.0},
        ],
        'asks': [
            {'price': 50001.0, 'qty': 1.0},   # 少量卖盘
            {'price': 50002.0, 'qty': 2.0},
        ]
    }

    signal = alpha_gen.generate_signal(ob_imbalanced)
    print(f"买方强势场景:")
    print(f"  方向: {signal['direction']} (1=buy, -1=sell, 0=hold)")
    print(f"  强度: {signal['strength']:.2f}")
    print(f"  预期边缘: {signal['expected_edge_bps']:.2f} bps")
    print(f"  原因: {signal['reason']}")

    # 场景2: 平衡市场
    ob_balanced = {
        'bids': [
            {'price': 50000.0, 'qty': 2.0},
            {'price': 49999.0, 'qty': 2.0},
        ],
        'asks': [
            {'price': 50001.0, 'qty': 2.0},
            {'price': 50002.0, 'qty': 2.0},
        ]
    }

    signal = alpha_gen.generate_signal(ob_balanced)
    print(f"\n平衡市场场景:")
    print(f"  方向: {signal['direction']}")
    print(f"  强度: {signal['strength']:.2f}")
    print(f"  原因: {signal['reason']}")

    print("\n" + "=" * 60)
    print("测试完成")
