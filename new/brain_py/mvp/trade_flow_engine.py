"""
Trade Flow Alpha v3 - 成交流特征引擎

基于已执行交易的高置信度Alpha生成器

核心特征：
1. Trade Imbalance (0.50): 买卖成交不平衡
2. Trade Intensity (0.30): 成交密度/强度
3. Price Impact (0.20): 成交价对中间价的影响

理论依据：
- 成交流代表已执行的资金流动（真实成本）
- 操纵成本高，信息"纯度"高
- 在ETH等高效市场仍可能有效
"""
import numpy as np
from collections import deque
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Trade:
    """成交记录"""
    timestamp: float
    price: float
    qty: float
    side: str  # 'buy' 或 'sell' (taker perspective)
    is_buyer_maker: bool  # True=买方挂单方（即卖方taker）


@dataclass
class TradeFlowState:
    """成交流状态"""
    imbalance: float        # [-1, 1] 买卖不平衡
    intensity: float        # [0, ∞) 成交强度
    price_impact: float     # [-1, 1] 价格影响
    trade_count: int        # 窗口内成交笔数
    buy_volume: float       # 买方主动成交量
    sell_volume: float      # 卖方主动成交量


class TradeFlowEngine:
    """
    成交流Alpha引擎 v3

    通过分析近期成交数据生成交易信号
    """

    def __init__(self,
                 window_seconds: float = 3.0,      # 3秒观察窗口
                 intensity_threshold: float = 0.5,  # 强度阈值
                 min_trades: int = 3):              # 最小成交笔数

        self.window_seconds = window_seconds
        self.intensity_threshold = intensity_threshold
        self.min_trades = min_trades

        # 成交历史
        self.trade_history: deque = deque(maxlen=1000)

        # 统计历史（用于归一化）
        self.imbalance_history: deque = deque(maxlen=100)
        self.intensity_history: deque = deque(maxlen=100)
        self.impact_history: deque = deque(maxlen=100)

        # 权重配置
        self.weights = {
            'imbalance': 0.50,
            'intensity': 0.30,
            'impact': 0.20
        }

    def add_trade(self, trade: Trade):
        """添加一笔成交记录"""
        self.trade_history.append(trade)

    def add_trade_from_binance(self, trade_data: dict, current_mid_price: float):
        """
        从币安成交数据创建Trade对象

        Args:
            trade_data: 币安trade/aggTrade数据
            current_mid_price: 当前中间价（用于计算price impact）
        """
        try:
            # 解析币安数据格式
            price = float(trade_data.get('p', trade_data.get('price', 0)))
            qty = float(trade_data.get('q', trade_data.get('quantity', 0)))

            # isBuyerMaker: True表示买方是挂单方（即卖方主动吃单）
            is_buyer_maker = trade_data.get('m', trade_data.get('isBuyerMaker', False))

            # side: 从taker perspective
            # is_buyer_maker=True → 卖方taker → side='sell'
            # is_buyer_maker=False → 买方taker → side='buy'
            side = 'sell' if is_buyer_maker else 'buy'

            trade = Trade(
                timestamp=datetime.now().timestamp(),
                price=price,
                qty=qty,
                side=side,
                is_buyer_maker=is_buyer_maker
            )

            self.add_trade(trade)

        except Exception as e:
            print(f"[WARN] Failed to parse trade: {e}")

    def compute_trade_flow(self, current_mid_price: float) -> TradeFlowState:
        """
        计算当前成交流状态

        Args:
            current_mid_price: 当前中间价（用于计算price impact）

        Returns:
            TradeFlowState: 成交流状态
        """
        now = datetime.now().timestamp()
        cutoff_time = now - self.window_seconds

        # 获取窗口内的成交
        recent_trades = [
            t for t in self.trade_history
            if t.timestamp >= cutoff_time
        ]

        if len(recent_trades) < self.min_trades:
            # 成交太少，返回中性状态
            return TradeFlowState(
                imbalance=0.0,
                intensity=0.0,
                price_impact=0.0,
                trade_count=0,
                buy_volume=0.0,
                sell_volume=0.0
            )

        # 1. 计算Trade Imbalance
        buy_volume = sum(t.qty for t in recent_trades if t.side == 'buy')
        sell_volume = sum(t.qty for t in recent_trades if t.side == 'sell')
        total_volume = buy_volume + sell_volume

        if total_volume > 0:
            imbalance = (buy_volume - sell_volume) / total_volume
        else:
            imbalance = 0.0

        # 2. 计算Trade Intensity
        # 单位时间内的成交笔数 + 成交量
        trades_per_second = len(recent_trades) / self.window_seconds
        volume_per_second = total_volume / self.window_seconds

        # 归一化强度（使用历史数据）
        raw_intensity = trades_per_second * np.log1p(volume_per_second)

        # 3. 计算Price Impact
        # 成交价vs中间价的加权偏差
        weighted_price = sum(t.price * t.qty for t in recent_trades) / total_volume
        impact = (weighted_price - current_mid_price) / current_mid_price * 10000  # 转换为bps

        # 归一化impact
        impact = np.clip(impact / 10.0, -1, 1)  # 10bps = 最大影响

        # 记录历史
        self.imbalance_history.append(abs(imbalance))
        self.intensity_history.append(raw_intensity)
        self.impact_history.append(abs(impact))

        return TradeFlowState(
            imbalance=imbalance,
            intensity=raw_intensity,
            price_impact=impact,
            trade_count=len(recent_trades),
            buy_volume=buy_volume,
            sell_volume=sell_volume
        )

    def compute_alpha(self, current_mid_price: float) -> Tuple[float, TradeFlowState]:
        """
        计算Trade Flow Alpha分数

        Returns:
            (alpha_score, trade_flow_state)
        """
        state = self.compute_trade_flow(current_mid_price)

        if state.trade_count < self.min_trades:
            return 0.0, state

        # 归一化各特征
        def normalize_with_history(value, history, default_scale=1.0):
            if len(history) < 20:
                return np.tanh(value)  # 早期使用tanh
            scale = np.percentile(list(history), 75)
            if scale < 0.001:
                scale = default_scale
            return np.clip(value / scale, -1, 1)

        imbalance_norm = state.imbalance  # 已经在[-1, 1]
        intensity_norm = normalize_with_history(
            state.intensity, self.intensity_history, default_scale=5.0
        )
        impact_norm = state.price_impact  # 已经在[-1, 1]

        # 加权融合
        alpha_score = (
            self.weights['imbalance'] * imbalance_norm +
            self.weights['intensity'] * intensity_norm +
            self.weights['impact'] * impact_norm
        )

        return alpha_score, state

    def get_feature_stats(self) -> Dict:
        """获取特征统计信息"""
        return {
            'imbalance_mean': np.mean(list(self.imbalance_history)) if self.imbalance_history else 0,
            'imbalance_std': np.std(list(self.imbalance_history)) if self.imbalance_history else 0,
            'intensity_mean': np.mean(list(self.intensity_history)) if self.intensity_history else 0,
            'intensity_std': np.std(list(self.intensity_history)) if self.intensity_history else 0,
            'impact_mean': np.mean(list(self.impact_history)) if self.impact_history else 0,
            'impact_std': np.std(list(self.impact_history)) if self.impact_history else 0,
            'total_trades_recorded': len(self.trade_history)
        }

    def reset(self):
        """重置引擎"""
        self.trade_history.clear()
        self.imbalance_history.clear()
        self.intensity_history.clear()
        self.impact_history.clear()


# 集成到现有系统的适配器
class TradeFlowFeatureAdapter:
    """
    Trade Flow特征适配器

    将TradeFlowEngine集成到现有的MVPTraderV2系统中
    """

    def __init__(self, trade_flow_engine: TradeFlowEngine):
        self.trade_flow = trade_flow_engine

    def process_with_trades(self,
                           orderbook: Dict,
                           recent_trades: List[dict],
                           current_mid_price: float) -> Dict:
        """
        处理订单簿+成交数据，生成增强特征

        Args:
            orderbook: 订单簿数据
            recent_trades: 近期成交列表（币安格式）
            current_mid_price: 当前中间价

        Returns:
            包含trade flow特征的字典
        """
        # 添加成交记录
        for trade_data in recent_trades:
            self.trade_flow.add_trade_from_binance(trade_data, current_mid_price)

        # 计算Alpha
        alpha_score, flow_state = self.trade_flow.compute_alpha(current_mid_price)

        return {
            'alpha_score': alpha_score,
            'trade_imbalance': flow_state.imbalance,
            'trade_intensity': flow_state.intensity,
            'price_impact': flow_state.price_impact,
            'trade_count': flow_state.trade_count,
            'buy_volume': flow_state.buy_volume,
            'sell_volume': flow_state.sell_volume
        }


# 测试代码
if __name__ == "__main__":
    print("="*60)
    print("Trade Flow Engine v3 Test")
    print("="*60)

    engine = TradeFlowEngine(window_seconds=3.0, min_trades=3)

    # 模拟成交数据
    import time
    base_price = 2180.0

    for i in range(20):
        # 模拟主动买单压力
        if i < 10:
            side = 'buy'
            price_offset = 0.01
        else:
            side = 'sell'
            price_offset = -0.01

        trade = Trade(
            timestamp=time.time(),
            price=base_price + price_offset * (i % 3),
            qty=0.5 + i * 0.1,
            side=side,
            is_buyer_maker=(side == 'sell')
        )

        engine.add_trade(trade)
        time.sleep(0.1)

    # 计算Alpha
    alpha, state = engine.compute_alpha(base_price)

    print(f"\nTrade Flow State:")
    print(f"  Imbalance: {state.imbalance:+.3f}")
    print(f"  Intensity: {state.intensity:.3f}")
    print(f"  Price Impact: {state.price_impact:+.3f}bps")
    print(f"  Trade Count: {state.trade_count}")
    print(f"  Buy Volume: {state.buy_volume:.2f}")
    print(f"  Sell Volume: {state.sell_volume:.2f}")

    print(f"\nAlpha Score: {alpha:+.3f}")

    print("\n" + "="*60)
    print("Test completed!")
    print("="*60)
