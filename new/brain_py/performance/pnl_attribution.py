"""
PnL 归因系统 - 分解盈利来源

将总盈利分解为可解释的成分，帮助识别真正的alpha来源
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Deque
from collections import deque
from enum import Enum
import time


class TradeSide(Enum):
    BUY = 1
    SELL = -1


class OrderType(Enum):
    LIMIT = "limit"
    MARKET = "market"


@dataclass
class Trade:
    """交易记录"""
    trade_id: str
    symbol: str
    side: TradeSide
    order_type: OrderType
    qty: float
    order_price: float
    fill_price: float
    bid_price: float  # 下单时的买一价
    ask_price: float  # 下单时的卖一价
    timestamp: float
    fee: float = 0.0
    market_price_after: Optional[float] = None  # 成交后市场价格
    funding_rate: float = 0.0


@dataclass
class PnLAttributionResult:
    """PnL归因结果"""
    total_pnl: float
    components: Dict[str, float]
    confidence: float  # 归因置信度
    timestamp: float

    def __post_init__(self):
        # 验证归因总和
        component_sum = sum(self.components.values())
        if abs(component_sum - self.total_pnl) > 0.01:
            self.confidence *= 0.8  # 降低置信度


class PnLAttribution:
    """
    PnL归因系统

    分解单笔交易的PnL为以下成分：
    - spread_capture: 点差收益（核心alpha）
    - adverse_selection: 逆向选择损失（毒流成本）
    - queue_slippage: 队列滑点（执行成本）
    - fee_rebate: 手续费/返佣
    - funding_rate: 资金费率（持仓成本）
    - market_movement: 市场方向收益（beta，非alpha）
    """

    def __init__(self,
                 maker_rebate_rate: float = 0.0002,  # 0.02%返佣
                 taker_fee_rate: float = 0.0005,     # 0.05%手续费
                 adverse_lookback_ms: int = 100):    # 逆向选择观察窗口
        self.maker_rebate_rate = maker_rebate_rate
        self.taker_fee_rate = taker_fee_rate
        self.adverse_lookback_ms = adverse_lookback_ms

        # 历史归因记录
        self.attribution_history: Deque[PnLAttributionResult] = deque(maxlen=10000)

        # 累计统计
        self.cumulative_stats = {
            'total_trades': 0,
            'total_pnl': 0.0,
            'spread_capture': 0.0,
            'adverse_selection': 0.0,
            'queue_slippage': 0.0,
            'fee_rebate': 0.0,
            'funding_rate': 0.0,
            'market_movement': 0.0,
        }

    def analyze_trade(self, trade: Trade) -> PnLAttributionResult:
        """
        分析单笔交易的PnL归因

        Args:
            trade: 交易记录

        Returns:
            PnLAttributionResult: 归因结果
        """
        components = {}

        # 1. 点差收益 Spread Capture (核心Alpha)
        # 买单：点差 = 卖一 - 买一，捕获负点差
        # 卖单：点差 = 卖一 - 买一，捕获正点差
        spread = trade.ask_price - trade.bid_price
        mid_price = (trade.ask_price + trade.bid_price) / 2

        if trade.side == TradeSide.BUY:
            # 买入：以ask成交，相对于mid的成本
            # 点差收益 = -spread/2 (相对于mid)
            components['spread_capture'] = -spread * trade.qty / 2
        else:
            # 卖出：以bid成交，相对于mid的收益
            # 点差收益 = +spread/2 (相对于mid)
            components['spread_capture'] = spread * trade.qty / 2

        # 2. 队列滑点 Queue Slippage
        # 限价单实际成交价格与挂单价格的差异
        if trade.order_type == OrderType.LIMIT:
            if trade.side == TradeSide.BUY:
                # 买限单价应该 <= 挂单价
                queue_slippage = max(0, trade.fill_price - trade.order_price)
            else:
                # 卖限单价应该 >= 挂单价
                queue_slippage = max(0, trade.order_price - trade.fill_price)
            components['queue_slippage'] = -queue_slippage * trade.qty
        else:
            components['queue_slippage'] = 0.0

        # 3. 逆向选择损失 Adverse Selection
        # 成交后价格反向移动 = 被毒流收割
        if trade.market_price_after is not None:
            if trade.side == TradeSide.BUY:
                # 买入后价格下跌 = 被套在高点
                adverse = max(0, trade.fill_price - trade.market_price_after)
            else:
                # 卖出后价格上涨 = 被洗在低点
                adverse = max(0, trade.market_price_after - trade.fill_price)
            components['adverse_selection'] = -adverse * trade.qty
        else:
            # 无法计算，设为0但降低置信度
            components['adverse_selection'] = 0.0

        # 4. 手续费/返佣 Fee/Rebate
        if trade.order_type == OrderType.LIMIT:
            # Maker返佣
            components['fee_rebate'] = trade.fill_price * trade.qty * self.maker_rebate_rate
        else:
            # Taker手续费
            components['fee_rebate'] = -trade.fill_price * trade.qty * self.taker_fee_rate

        # 5. 资金费率 Funding Rate
        components['funding_rate'] = -trade.funding_rate * trade.fill_price * trade.qty

        # 6. 市场方向收益 Market Movement (Beta)
        # 这部分不是alpha，是承担方向风险的结果
        if trade.market_price_after is not None:
            price_change = trade.market_price_after - mid_price
            if trade.side == TradeSide.BUY:
                # 多头方向收益
                components['market_movement'] = price_change * trade.qty
            else:
                # 空头方向收益
                components['market_movement'] = -price_change * trade.qty
        else:
            components['market_movement'] = 0.0

        # 计算总PnL
        total_pnl = sum(components.values())

        # 验证与原始PnL的一致性
        confidence = 1.0
        if hasattr(trade, 'actual_pnl'):
            diff = abs(total_pnl - trade.actual_pnl)
            if diff > 0.001:  # 差异大于0.1%
                confidence = max(0.0, 1.0 - diff / abs(trade.actual_pnl))

        result = PnLAttributionResult(
            total_pnl=total_pnl,
            components=components,
            confidence=confidence,
            timestamp=time.time()
        )

        # 更新历史记录和统计
        self._update_stats(result)

        return result

    def _update_stats(self, result: PnLAttributionResult):
        """更新累计统计"""
        self.attribution_history.append(result)
        self.cumulative_stats['total_trades'] += 1
        self.cumulative_stats['total_pnl'] += result.total_pnl

        for component, value in result.components.items():
            if component in self.cumulative_stats:
                self.cumulative_stats[component] += value

    def get_cumulative_report(self) -> Dict:
        """
        获取累计归因报告

        Returns:
            Dict: 包含各成分累计值和占比的报告
        """
        if self.cumulative_stats['total_trades'] == 0:
            return {"error": "No trades analyzed yet"}

        total = self.cumulative_stats['total_pnl']
        if abs(total) < 1e-10:
            total = 1e-10  # 避免除零

        report = {
            'total_trades': self.cumulative_stats['total_trades'],
            'total_pnl': total,
            'components': {},
            'alpha_score': 0.0,  # alpha / total
            'execution_quality': 0.0,  # 执行相关成分的占比
        }

        # 各成分绝对值和占比
        for component, value in self.cumulative_stats.items():
            if component in ['total_trades', 'total_pnl']:
                continue

            report['components'][component] = {
                'value': value,
                'percentage': value / total * 100,
                'per_trade': value / self.cumulative_stats['total_trades']
            }

        # Alpha分数 = 点差收益 / 总PnL
        # 理想情况下应该接近1（所有收益来自点差捕获）
        spread_capture = self.cumulative_stats.get('spread_capture', 0)
        report['alpha_score'] = spread_capture / total if total != 0 else 0

        # 执行质量 = (点差收益 - 逆向选择 - 滑点) / |点差收益|
        adverse = self.cumulative_stats.get('adverse_selection', 0)
        slippage = self.cumulative_stats.get('queue_slippage', 0)
        if abs(spread_capture) > 1e-10:
            report['execution_quality'] = (spread_capture + adverse + slippage) / abs(spread_capture)

        return report

    def get_recent_report(self, n: int = 100) -> Dict:
        """
        获取最近N笔交易的归因报告

        Args:
            n: 最近交易笔数

        Returns:
            Dict: 最近交易的归因统计
        """
        recent = list(self.attribution_history)[-n:]
        if not recent:
            return {"error": "No trades in history"}

        # 计算最近N笔的统计
        total_pnl = sum(r.total_pnl for r in recent)
        component_sums = {}

        for r in recent:
            for comp, val in r.components.items():
                component_sums[comp] = component_sums.get(comp, 0) + val

        report = {
            'window_size': len(recent),
            'total_pnl': total_pnl,
            'avg_pnl_per_trade': total_pnl / len(recent),
            'win_rate': sum(1 for r in recent if r.total_pnl > 0) / len(recent),
            'components': component_sums,
        }

        return report

    def is_profitable_structure(self) -> tuple[bool, str]:
        """
        判断当前交易结构是否健康盈利

        Returns:
            (bool, str): (是否健康, 原因说明)
        """
        report = self.get_cumulative_report()

        if 'error' in report:
            return False, "Not enough data"

        # 检查1: Alpha分数应该为正
        if report['alpha_score'] < 0.3:
            return False, f"Low alpha score: {report['alpha_score']:.2f} - PnL mostly from luck, not skill"

        # 检查2: 逆向选择损失不应过大
        adverse = self.cumulative_stats.get('adverse_selection', 0)
        spread = self.cumulative_stats.get('spread_capture', 0)
        if abs(spread) > 1e-10 and abs(adverse) > abs(spread) * 0.5:
            return False, f"High adverse selection: {adverse/spread:.1%} of spread - being harvested by toxic flow"

        # 检查3: 执行质量
        if report['execution_quality'] < 0.5:
            return False, f"Poor execution quality: {report['execution_quality']:.2f} - high slippage/cancellation cost"

        return True, f"Healthy: alpha={report['alpha_score']:.2f}, quality={report['execution_quality']:.2f}"

    def reset(self):
        """重置所有统计"""
        self.attribution_history.clear()
        for key in self.cumulative_stats:
            self.cumulative_stats[key] = 0.0 if key != 'total_trades' else 0


# 便捷函数
def create_sample_trade(
    side: str = "buy",
    order_type: str = "limit",
    qty: float = 0.01,
    fill_price: float = 50000.0,
    spread_bps: float = 1.0
) -> Trade:
    """创建示例交易用于测试"""
    spread = fill_price * spread_bps / 10000

    return Trade(
        trade_id=f"test_{time.time()}",
        symbol="BTCUSDT",
        side=TradeSide.BUY if side == "buy" else TradeSide.SELL,
        order_type=OrderType.LIMIT if order_type == "limit" else OrderType.MARKET,
        qty=qty,
        order_price=fill_price,
        fill_price=fill_price,
        bid_price=fill_price - spread/2,
        ask_price=fill_price + spread/2,
        timestamp=time.time(),
        market_price_after=fill_price + (spread if side == "buy" else -spread) * 0.5
    )


if __name__ == "__main__":
    # 测试PnL归因系统
    print("=" * 60)
    print("PnL Attribution System Test")
    print("=" * 60)

    attributor = PnLAttribution()

    # 模拟一些交易
    print("\n模拟交易分析:")
    print("-" * 60)

    # 交易1: 健康的Maker买单（捕获点差）
    trade1 = create_sample_trade("buy", "limit", 0.01, 50000.0, 1.0)
    result1 = attributor.analyze_trade(trade1)
    print(f"\n交易1 - 健康Maker买单:")
    print(f"  总PnL: ${result1.total_pnl:.4f}")
    print(f"  点差捕获: ${result1.components['spread_capture']:.4f}")
    print(f"  逆向选择: ${result1.components['adverse_selection']:.4f}")
    print(f"  手续费: ${result1.components['fee_rebate']:.4f}")

    # 交易2: 被毒流击中的交易
    trade2 = create_sample_trade("buy", "limit", 0.01, 50000.0, 1.0)
    trade2.market_price_after = 49950.0  # 买入后大跌
    result2 = attributor.analyze_trade(trade2)
    print(f"\n交易2 - 被毒流击中:")
    print(f"  总PnL: ${result2.total_pnl:.4f}")
    print(f"  点差捕获: ${result2.components['spread_capture']:.4f}")
    print(f"  逆向选择: ${result2.components['adverse_selection']:.4f} (警告)")

    # 交易3: Taker单（支付手续费）
    trade3 = create_sample_trade("sell", "market", 0.01, 50100.0, 1.0)
    result3 = attributor.analyze_trade(trade3)
    print(f"\n交易3 - Taker卖单:")
    print(f"  总PnL: ${result3.total_pnl:.4f}")
    print(f"  点差捕获: ${result3.components['spread_capture']:.4f}")
    print(f"  手续费: ${result3.components['fee_rebate']:.4f}")

    # 累计报告
    print("\n" + "=" * 60)
    print("累计归因报告:")
    print("=" * 60)
    report = attributor.get_cumulative_report()
    print(f"总交易数: {report['total_trades']}")
    print(f"总PnL: ${report['total_pnl']:.4f}")
    print(f"Alpha分数: {report['alpha_score']:.2f}")
    print(f"执行质量: {report['execution_quality']:.2f}")
    print("\n各成分占比:")
    for comp, data in report['components'].items():
        print(f"  {comp}: ${data['value']:.4f} ({data['percentage']:+.1f}%)")

    # 健康检查
    print("\n" + "=" * 60)
    is_healthy, reason = attributor.is_profitable_structure()
    print(f"交易结构健康度: {'[OK] 健康' if is_healthy else '[X] 不健康'}")
    print(f"原因: {reason}")
