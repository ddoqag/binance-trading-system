"""
确定性规则做市策略 (Rule-based Market Maker V1)。
目标：在主流币（BTC/ETH）上实现稳定、不亏损的流动性提供。
"""
import time
import numpy as np
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from execution.client import ExecutorClient


@dataclass
class MarketState:
    """市场状态快照。"""
    timestamp: float
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    last_price: float
    spread: float  # (ask - bid) / mid
    mid_price: float
    toxic_score: float = 0.0  # 从您的风控模块获取
    volatility: float = 0.0   # 短期波动率估计
    trade_imbalance: float = 0.0  # 近期成交方向，1为强烈买压，-1为强烈卖压


class MarketMakerV1:
    """
    三段式做市策略引擎。
    模式: HOLD (观望) | MAKER (被动做市) | TAKER (主动调整)
    """

    def __init__(
        self,
        executor: ExecutorClient,
        symbol: str = "BTCUSDT",
        max_position: float = 0.02,  # 最大允许净头寸
        base_order_size: float = 0.001,
        min_spread_ticks: int = 2,
        tick_size: float = 0.01,  # BTC 1 tick = $0.01
        toxic_threshold: float = 0.6,
        inventory_skew_factor: float = 1.0
    ):
        self.executor = executor
        self.symbol = symbol
        self.max_position = max_position
        self.base_order_size = base_order_size
        self.min_spread_ticks = min_spread_ticks
        self.tick_size = tick_size
        self.toxic_threshold = toxic_threshold
        self.inventory_skew_factor = inventory_skew_factor

        # 状态
        self.current_position = 0.0
        self.current_pnl = 0.0
        self.active_orders = {}  # order_id -> order_info
        self.last_tick_time = 0
        self.mode = "HOLD"

        # 性能跟踪
        self.metrics = {
            "ticks_processed": 0,
            "orders_placed": 0,
            "orders_filled": 0,
            "orders_cancelled": 0,
            "total_fill_value": 0.0,
        }

    def update_state(self, market: MarketState, position_info: Dict[str, Any]):
        """更新内部状态（市场数据和仓位）。应在每个tick调用。"""
        self.current_position = position_info.get("position", 0.0)
        self.last_tick_time = market.timestamp
        self.metrics["ticks_processed"] += 1

    def decide_mode(self, market: MarketState) -> str:
        """
        核心决策：根据当前市场状态和仓位，决定进入哪种模式。
        遵循: 1) 安全第一 2) 控制风险 3) 提供流动性
        """
        # 1. 安全与风控优先：毒性高或波动过大时观望
        if market.toxic_score > self.toxic_threshold:
            return "HOLD"
        if market.volatility > 0.05:  # 示例阈值，需根据币种调整
            return "HOLD"

        # 2. 市场质量不足：点差过窄时观望
        if market.spread < (self.min_spread_ticks * self.tick_size / market.mid_price):
            return "HOLD"

        # 3. 风险控制：仓位超过限值时，主动调整
        if abs(self.current_position) >= self.max_position * 0.8:  # 达到80%上限即开始调整
            return "TAKER"

        # 4. 默认情况：在健康市场中提供流动性
        return "MAKER"

    def run_maker_mode(self, market: MarketState):
        """被动做市模式：在买卖两侧挂限价单，赚取点差。"""
        # 1. 计算基础报价
        raw_bid = market.bid
        raw_ask = market.ask
        # 确保点差至少满足最小要求
        effective_spread = max(market.spread, self.min_spread_ticks * self.tick_size)
        target_mid = market.mid_price
        bid_price = target_mid - effective_spread / 2
        ask_price = target_mid + effective_spread / 2

        # 2. 库存偏置 (Inventory Skew)：持仓偏多时调低卖单价/调高买单价，促进平仓
        skew = (self.current_position / self.max_position) * self.inventory_skew_factor
        # 偏置单位也用tick，更符合交易所规则
        bias_ticks = round(skew * 5)  # 例如，满仓偏置5个tick
        bid_price -= bias_ticks * self.tick_size
        ask_price -= bias_ticks * self.tick_size  # 注意：减号对卖单是调低价格，有利于卖出

        # 3. 挂单前检查：避免重复挂单（关键优化）
        existing_bid, existing_ask = self._get_existing_quote_prices()
        price_tolerance = self.tick_size * 0.5  # 半个tick内视为重复

        # 4. 计算挂单量（可根据库存动态调整）
        order_size = self._compute_order_size()

        # 5. 执行挂单
        if order_size > 0:
            if existing_bid is None or abs(bid_price - existing_bid) > price_tolerance:
                self._place_limit_order_if_safe("BUY", bid_price, order_size, market)
            if existing_ask is None or abs(ask_price - existing_ask) > price_tolerance:
                self._place_limit_order_if_safe("SELL", ask_price, order_size, market)

    def run_taker_mode(self, market: MarketState):
        """主动调整模式：通过市价单快速减少风险头寸。"""
        # 立即撤销所有未成交的限价单，避免干扰
        self.executor.cancel_all_orders(self.symbol)
        time.sleep(0.05)  # 短暂等待撤单确认

        # 根据持仓方向决定市价平仓
        close_size = min(abs(self.current_position), self.max_position * 0.5)  # 一次平一半，避免冲击
        if self.current_position > 0:
            # 持有多头，市价卖出
            self.executor.place_order("market", "SELL", close_size)
        elif self.current_position < 0:
            # 持有空头，市价买入
            self.executor.place_order("market", "BUY", close_size)
        # 平仓后策略会因仓位下降，在下一个tick可能切换回MAKER或HOLD模式

    def on_market_tick(self, market: MarketState, position_info: Dict[str, Any]):
        """
        主处理函数：处理每一个市场tick。
        1. 更新状态
        2. 决策模式
        3. 执行对应操作
        """
        # 1. 更新
        self.update_state(market, position_info)

        # 2. 决策
        new_mode = self.decide_mode(market)
        mode_changed = (new_mode != self.mode)
        self.mode = new_mode

        # 3. 执行
        if mode_changed and self.mode != "MAKER":
            # 模式切换为非MAKER时，先清除所有旧订单
            self.executor.cancel_all_orders(self.symbol)

        if self.mode == "HOLD":
            # 观望模式：不挂新单，已有订单已在切换时取消
            pass
        elif self.mode == "MAKER":
            self.run_maker_mode(market)
        elif self.mode == "TAKER":
            self.run_taker_mode(market)

        # 4. 记录
        self._cleanup_old_orders()

    # --- 辅助函数 ---
    def _compute_order_size(self) -> float:
        """根据当前仓位和风险计算本次挂单量。"""
        # 基础风控：仓位越重，挂单量越小
        position_ratio = abs(self.current_position) / self.max_position
        size_multiplier = max(0.1, 1.0 - position_ratio)  # 仓位越重，乘数越小，最低0.1
        return self.base_order_size * size_multiplier

    def _get_existing_quote_prices(self) -> Tuple[Optional[float], Optional[float]]:
        """获取当前已挂买单和卖单的价格。"""
        buy_price, sell_price = None, None
        for order in self.active_orders.values():
            if order.get("side") == "BUY":
                buy_price = order.get("price", buy_price)
            elif order.get("side") == "SELL":
                sell_price = order.get("price", sell_price)
        return buy_price, sell_price

    def _place_limit_order_if_safe(self, side: str, price: float, size: float, market: MarketState):
        """安全挂单检查，并记录订单。"""
        # 极简安全检查：价格不能太偏离市场（例如超过10个tick）
        if side == "BUY" and price > market.ask + 10 * self.tick_size:
            return
        if side == "SELL" and price < market.bid - 10 * self.tick_size:
            return

        resp = self.executor.place_order("limit", side, size, price)
        if resp and resp.get("order_id"):
            self.active_orders[resp["order_id"]] = {
                "order_id": resp["order_id"],
                "side": side,
                "price": price,
                "size": size,
                "timestamp": time.time()
            }
            self.metrics["orders_placed"] += 1

    def _cleanup_old_orders(self):
        """清理已成交或已取消的订单记录。"""
        current_open_ids = {o["order_id"] for o in self.executor.get_open_orders(self.symbol)}
        to_remove = [oid for oid in self.active_orders if oid not in current_open_ids]
        for oid in to_remove:
            if oid in self.active_orders:
                # 如果是卖单成交，仓位应减少；买单成交，仓位应增加。此处应由Go引擎的持仓回调准确更新。
                # 此处仅做记录清理
                del self.active_orders[oid]

    def get_performance_report(self) -> Dict[str, Any]:
        """获取策略性能快照。"""
        return {
            "current_mode": self.mode,
            "current_position": self.current_position,
            "active_orders": len(self.active_orders),
            **self.metrics
        }
