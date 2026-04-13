"""
点差捕获器 (MVP版本)

核心逻辑：
- spread ≥ 2 ticks 时挂被动单
- 赚 maker rebate
- 最稳定的alpha来源
"""

import numpy as np
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from collections import deque
import time


@dataclass
class SpreadOpportunity:
    """点差机会"""
    is_profitable: bool
    side: str  # 'buy' or 'sell'
    entry_price: float
    target_price: float
    spread_bps: float
    net_profit_bps: float
    confidence: float
    reason: str


class SpreadCapture:
    """
    点差捕获器

    最简单的盈利逻辑：在点差足够大时挂被动单，赚取maker返佣
    """

    def __init__(self,
                 min_spread_ticks: int = 2,  # 最小点差（tick数）
                 tick_size: float = 0.01,    # tick大小
                 maker_rebate: float = 0.0002,  # maker返佣 0.02%
                 taker_fee: float = 0.0005,     # taker手续费 0.05%
                 min_confidence: float = 0.7):   # 最小置信度

        self.min_spread_ticks = min_spread_ticks
        self.tick_size = tick_size
        self.maker_rebate = maker_rebate
        self.taker_fee = taker_fee
        self.min_confidence = min_confidence

        # 点差历史
        self.spread_history = deque(maxlen=1000)
        self.profit_history = deque(maxlen=100)

        # 统计
        self.stats = {
            'checks': 0,
            'profitable_opportunities': 0,
            'executed_trades': 0,
            'total_profit_bps': 0.0,
            'avg_spread_bps': 0.0
        }

        # 当前持仓方向（避免重复开仓）
        self.current_position = 0.0  # 正数=多头，负数=空头

    def analyze(self,
                orderbook: Dict,
                current_position: Optional[float] = None) -> SpreadOpportunity:
        """
        分析点差机会

        Args:
            orderbook: 订单簿数据
            current_position: 当前持仓

        Returns:
            SpreadOpportunity: 点差机会分析
        """
        self.stats['checks'] += 1

        if current_position is not None:
            self.current_position = current_position

        # 获取订单簿数据
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if len(bids) == 0 or len(asks) == 0:
            return SpreadOpportunity(
                is_profitable=False,
                side='',
                entry_price=0,
                target_price=0,
                spread_bps=0,
                net_profit_bps=0,
                confidence=0,
                reason="empty_orderbook"
            )

        best_bid = bids[0].get('price', 0)
        best_ask = asks[0].get('price', float('inf'))
        bid_qty = bids[0].get('qty', 0)
        ask_qty = asks[0].get('qty', 0)

        # 计算点差
        spread = best_ask - best_bid
        mid_price = (best_ask + best_bid) / 2
        spread_bps = (spread / mid_price) * 10000  # 转换为基点

        self.spread_history.append(spread_bps)

        # 检查最小点差要求（允许微小浮点误差）
        min_spread_value = self.min_spread_ticks * self.tick_size
        if spread < min_spread_value - 1e-12:
            return SpreadOpportunity(
                is_profitable=False,
                side='',
                entry_price=0,
                target_price=0,
                spread_bps=spread_bps,
                net_profit_bps=0,
                confidence=0,
                reason=f"spread {spread_bps:.2f}bps < min {self.min_spread_ticks * self.tick_size / mid_price * 10000:.2f}bps"
            )

        # 计算净收益（考虑真实手续费，不是返佣）
        # 假设 maker 双边手续费约 0.04%（4bps），taker 约 0.10%（10bps）
        maker_fee_cost = 0.0004  # 双边 maker 手续费

        # 买单场景：以best_bid买入，理想平仓在best_ask
        buy_immediate_profit = (best_ask - best_bid) / mid_price
        buy_net_profit = buy_immediate_profit - maker_fee_cost

        # 卖单场景：以best_ask卖出，理想平仓在best_bid
        sell_immediate_profit = (best_ask - best_bid) / mid_price
        sell_net_profit = sell_immediate_profit - maker_fee_cost

        # 选择更优的方向
        if buy_net_profit > sell_net_profit:
            chosen_side = 'buy'
            chosen_profit = buy_net_profit
            entry_price = best_bid
            target_price = best_ask  # 理想退出价格
        else:
            chosen_side = 'sell'
            chosen_profit = sell_net_profit
            entry_price = best_ask
            target_price = best_bid  # 理想退出价格

        # 持仓限制由上层约束层处理，此处不再硬编码限制
        pass

        # 计算置信度
        confidence = self._calculate_confidence(
            spread_bps, bid_qty, ask_qty, chosen_side
        )

        # 检查净收益必须为正（否则每笔都稳定亏损手续费）
        if chosen_profit <= 0:
            return SpreadOpportunity(
                is_profitable=False,
                side='',
                entry_price=0,
                target_price=0,
                spread_bps=spread_bps,
                net_profit_bps=chosen_profit * 10000,
                confidence=confidence,
                reason=f"net_profit_negative {chosen_profit*10000:.2f}bps"
            )

        # 检查置信度
        if confidence < self.min_confidence:
            return SpreadOpportunity(
                is_profitable=False,
                side='',
                entry_price=0,
                target_price=0,
                spread_bps=spread_bps,
                net_profit_bps=chosen_profit * 10000,
                confidence=confidence,
                reason=f"low_confidence {confidence:.2f} < {self.min_confidence}"
            )

        # 有利可图的机会
        self.stats['profitable_opportunities'] += 1

        return SpreadOpportunity(
            is_profitable=True,
            side=chosen_side,
            entry_price=entry_price,
            target_price=target_price,
            spread_bps=spread_bps,
            net_profit_bps=chosen_profit * 10000,  # 转换为基点
            confidence=confidence,
            reason=f"spread={spread_bps:.2f}bps, profit={chosen_profit*10000:.2f}bps, conf={confidence:.2f}"
        )

    def _calculate_confidence(self,
                             spread_bps: float,
                             bid_qty: float,
                             ask_qty: float,
                             side: str) -> float:
        """
        计算交易置信度

        基于：
        1. 点差大小（越大越好）
        2. 流动性深度（越深越好）
        3. 点差历史（相对于近期平均）
        """
        confidence = 0.5  # 基础置信度

        # 1. 点差评分（0-0.3）
        spread_score = min(spread_bps / 10.0, 0.3)  # 10bps以上得满分
        confidence += spread_score

        # 2. 流动性评分（0-0.2）
        if side == 'buy':
            # 买入时关注卖盘深度
            liquidity_score = min(ask_qty / 2.0, 0.2)
        else:
            # 卖出时关注买盘深度
            liquidity_score = min(bid_qty / 2.0, 0.2)
        confidence += liquidity_score

        # 3. 历史比较评分（0-0.3）
        if len(self.spread_history) > 10:
            avg_spread = np.mean(list(self.spread_history)[-10:])
            if avg_spread > 0:
                relative_score = min((spread_bps / avg_spread - 1) * 0.5, 0.3)
                confidence += max(0, relative_score)

        return min(confidence, 1.0)

    def on_fill(self, side: str, qty: float, price: float):
        """处理成交"""
        self.stats['executed_trades'] += 1

        # 更新持仓
        if side == 'buy':
            self.current_position += qty
        else:
            self.current_position -= qty

        # 记录利润（简化：假设我们以entry_price成交，目标是点差的一半）
        # 实际利润需要在平仓后计算

    def get_expected_profit(self, opportunity: SpreadOpportunity, qty: float = 1.0) -> float:
        """
        计算预期利润

        Args:
            opportunity: 点差机会
            qty: 交易数量

        Returns:
            float: 预期利润（以计价货币计）
        """
        if not opportunity.is_profitable:
            return 0.0

        # 净利润 = 点差收益 + maker返佣
        net_return = opportunity.net_profit_bps / 10000  # 从bps转换
        return opportunity.entry_price * qty * net_return

    def get_stats(self) -> Dict:
        """获取统计信息"""
        stats = self.stats.copy()

        if self.spread_history:
            stats['avg_spread_bps'] = np.mean(list(self.spread_history))
            stats['max_spread_bps'] = np.max(list(self.spread_history))
            stats['min_spread_bps'] = np.min(list(self.spread_history))

        if self.stats['checks'] > 0:
            stats['opportunity_rate'] = self.stats['profitable_opportunities'] / self.stats['checks']

        stats['current_position'] = self.current_position

        return stats

    def reset(self):
        """重置状态"""
        self.spread_history.clear()
        self.profit_history.clear()
        self.current_position = 0.0
        for key in self.stats:
            self.stats[key] = 0 if isinstance(self.stats[key], int) else 0.0


class SpreadCaptureMonitor:
    """
    点差捕获监控器

    持续监控点差机会，提供实时统计
    """

    def __init__(self, spread_capture: SpreadCapture):
        self.spread_capture = spread_capture
        self.opportunity_log = deque(maxlen=100)

    def log_opportunity(self, opportunity: SpreadOpportunity):
        """记录机会"""
        self.opportunity_log.append({
            'timestamp': time.time(),
            'is_profitable': opportunity.is_profitable,
            'spread_bps': opportunity.spread_bps,
            'net_profit_bps': opportunity.net_profit_bps,
            'confidence': opportunity.confidence
        })

    def get_recent_opportunities(self, n: int = 10) -> list:
        """获取最近的机会"""
        return list(self.opportunity_log)[-n:]

    def calculate_capture_rate(self) -> float:
        """计算捕获率（实际交易 / 机会）"""
        stats = self.spread_capture.get_stats()
        if stats['profitable_opportunities'] == 0:
            return 0.0
        return stats['executed_trades'] / stats['profitable_opportunities']


# 测试代码
if __name__ == "__main__":
    print("=" * 60)
    print("Spread Capture Test (MVP)")
    print("=" * 60)

    capture = SpreadCapture(
        min_spread_ticks=2,
        tick_size=0.01,
        maker_rebate=0.0002
    )

    # 测试1: 点差太小
    print("\n测试1: 点差太小")
    print("-" * 60)

    orderbook_small_spread = {
        'bids': [{'price': 50000.00, 'qty': 1.0}],
        'asks': [{'price': 50000.01, 'qty': 1.0}]  # 1 tick点差
    }

    opp = capture.analyze(orderbook_small_spread)
    print(f"点差: {opp.spread_bps:.2f} bps")
    print(f"是否可盈利: {opp.is_profitable}")
    print(f"原因: {opp.reason}")

    # 测试2: 点差足够大
    print("\n测试2: 点差足够大")
    print("-" * 60)

    orderbook_good_spread = {
        'bids': [{'price': 50000.00, 'qty': 2.0}],
        'asks': [{'price': 50000.05, 'qty': 2.0}]  # 5 ticks点差
    }

    opp = capture.analyze(orderbook_good_spread)
    print(f"点差: {opp.spread_bps:.2f} bps")
    print(f"是否可盈利: {opp.is_profitable}")
    print(f"方向: {opp.side}")
    print(f"入场价格: {opp.entry_price}")
    print(f"净利润: {opp.net_profit_bps:.2f} bps")
    print(f"置信度: {opp.confidence:.2f}")

    if opp.is_profitable:
        expected_profit = capture.get_expected_profit(opp, qty=0.1)
        print(f"预期利润 (0.1 BTC): ${expected_profit:.4f}")

    # 测试3: 持仓限制
    print("\n测试3: 持仓限制")
    print("-" * 60)

    # 模拟已有大量多头持仓
    opp = capture.analyze(orderbook_good_spread, current_position=0.8)
    print(f"当前持仓: 0.8")
    print(f"是否可盈利: {opp.is_profitable}")
    print(f"原因: {opp.reason}")

    # 测试4: 统计信息
    print("\n测试4: 统计信息")
    print("-" * 60)

    # 模拟多次检查
    for _ in range(50):
        import random
        spread = random.uniform(1, 15)  # 随机点差 1-15 bps
        mid = 50000
        bid = mid - spread / 2 / 10000 * mid
        ask = mid + spread / 2 / 10000 * mid

        ob = {
            'bids': [{'price': bid, 'qty': random.uniform(0.5, 3.0)}],
            'asks': [{'price': ask, 'qty': random.uniform(0.5, 3.0)}]
        }
        capture.analyze(ob)

    stats = capture.get_stats()
    print(f"总检查次数: {stats['checks']}")
    print(f"有利机会: {stats['profitable_opportunities']}")
    print(f"机会率: {stats.get('opportunity_rate', 0):.1%}")
    print(f"平均点差: {stats.get('avg_spread_bps', 0):.2f} bps")
    print(f"最大点差: {stats.get('max_spread_bps', 0):.2f} bps")
    print(f"最小点差: {stats.get('min_spread_bps', 0):.2f} bps")

    print("\n" + "=" * 60)
    print("测试完成")
