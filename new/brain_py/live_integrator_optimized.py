"""
live_integrator_optimized.py - 优化版Python AI Brain

核心优化:
1. 交易过滤器 - 评估期望价值，过滤无效交易
2. 强制Maker策略 - 优先使用限价单降低手续费
3. 成本控制 - 4bps手续费模型
"""

import time
import argparse
from typing import Optional, Tuple
from dataclasses import dataclass

import numpy as np

from .meta_agent import MetaAgent, MetaAgentConfig
from .moe.mixture_of_experts import MixtureOfExperts
from .agents.execution_sac import ExecutionSACAgent
from shared.protocol import MarketSnapshot, OrderType, OrderSide
from shared.shm_reader import SharedMemoryReader
from shared.shm_writer import SharedMemoryOrderWriter


@dataclass
class IntegratorConfig:
    """优化版配置"""
    symbol: str = "BTCUSDT"
    shm_name: str = "hft_shared_memory"
    polling_interval_ms: int = 1
    min_confidence: float = 0.5
    dry_run: bool = True
    log_level: int = 1

    # 新增: 成本控制参数
    fee_bps: float = 4.0  # 4bps双边手续费
    min_expected_value_bps: float = 2.0  # 最小期望价值2bps
    force_maker: bool = True  # 强制maker单
    max_trades_per_min: int = 3  # 每分钟最大交易数


class LiveAIIntegratorOptimized:
    """优化版实盘AI集成器"""

    def __init__(self, config: IntegratorConfig = None):
        self.config = config or IntegratorConfig()
        self.reader: Optional[SharedMemoryReader] = None
        self.writer: Optional[SharedMemoryOrderWriter] = None
        self.meta_agent: Optional[MetaAgent] = None
        self.moe: Optional[MixtureOfExperts] = None
        self.execution_agent: Optional[ExecutionSACAgent] = None
        self.running = False
        self.last_sequence = 0
        self.last_trade_time = 0.0
        self.trade_count_minute = 0
        self.minute_start = time.time()

        self.stats = {
            'total_cycles': 0,
            'actions_executed': 0,
            'filtered_signals': 0,
            'filtered_by_value': 0,
            'filtered_by_rate': 0,
            'maker_orders': 0,
            'taker_orders': 0,
            'start_time': 0.0,
        }

    def _should_execute_trade(self, meta_position: float,
                              result, snapshot) -> Tuple[bool, str]:
        """
        交易过滤器 - 核心优化

        Returns:
            (should_trade, reason)
        """
        # 1. 检查频率限制
        current_time = time.time()
        if current_time - self.minute_start > 60:
            self.trade_count_minute = 0
            self.minute_start = current_time

        if self.trade_count_minute >= self.config.max_trades_per_min:
            self.stats['filtered_by_rate'] += 1
            return False, "rate_limit"

        # 2. 计算成本
        fee_cost = self.config.fee_bps / 10000  # 4bps = 0.0004

        # 3. 逆向选择风险
        toxic_prob = getattr(snapshot, 'toxic_probability', 0.0)
        adverse_risk = toxic_prob * 0.0001  # 1bps per 10% toxic prob

        # 4. Alpha强度
        alpha_strength = abs(meta_position) * result.confidence

        # 5. 期望价值
        expected_value = alpha_strength - fee_cost - adverse_risk
        min_value = self.config.min_expected_value_bps / 10000

        if expected_value < min_value:
            self.stats['filtered_by_value'] += 1
            return False, f"expected_value_{expected_value:.4f}"

        return True, "passed"

    def _place_maker_order(self, side: int, price: float,
                          quantity: float, snapshot: MarketSnapshot) -> bool:
        """
        强制Maker策略 - 使用限价单降低手续费
        """
        if self.config.force_maker and price > 0:
            # 确保价格能挂在盘口
            if side == OrderSide.BUY:
                # 买单挂在买一或更低
                price = min(price, snapshot.best_bid)
            else:
                # 卖单挂在卖一或更高
                price = max(price, snapshot.best_ask)

            order_type = OrderType.LIMIT
            self.stats['maker_orders'] += 1
        else:
            order_type = OrderType.MARKET
            self.stats['taker_orders'] += 1

        # 写入订单
        if order_type == OrderType.MARKET:
            cmd_id = self.writer.write_market_order(
                side, quantity, max_slippage_bps=10.0, dry_run=self.config.dry_run
            )
        else:
            cmd_id = self.writer.write_limit_order(
                side, price, quantity, expires_after_ms=5000, dry_run=self.config.dry_run
            )

        if cmd_id > 0:
            self.trade_count_minute += 1
            self.last_trade_time = time.time()

        return cmd_id > 0

    def run_cycle(self) -> bool:
        """优化版决策循环"""
        if not self.running:
            return False

        # 读取市场数据
        try:
            header = self.reader.read_header()
        except Exception as e:
            print(f"[ERROR] Failed to read header: {e}")
            return False

        # 检查新数据
        if header.last_market_snapshot.sequence == self.last_sequence:
            return False

        self.last_sequence = header.last_market_snapshot.sequence
        snapshot = header.last_market_snapshot

        # Meta-Agent决策
        try:
            observation = self._convert_to_observation(snapshot)
            result = self.meta_agent.execute(observation)
        except Exception as e:
            print(f"[ERROR] Meta-Agent execution failed: {e}")
            return False

        if result.confidence < self.config.min_confidence:
            self.stats['total_cycles'] += 1
            return False

        # 获取MoE融合位置
        meta_position = 0.0
        if self.config.moe_enabled and self.moe is not None:
            try:
                fused_pred, weights = self.moe.predict(observation)
                meta_position = float(np.clip(fused_pred[0], -1.0, 1.0))
            except Exception as e:
                print(f"[ERROR] MoE prediction failed: {e}")
                if result.action is not None:
                    meta_position = float(np.clip(result.action.position_size, -1.0, 1.0))
        else:
            if result.action is not None:
                meta_position = float(np.clip(result.action.position_size, -1.0, 1.0))

        if abs(meta_position) < 0.05:
            self.stats['total_cycles'] += 1
            return False

        # ===== 核心优化: 交易过滤器 =====
        should_trade, filter_reason = self._should_execute_trade(
            meta_position, result, snapshot
        )

        if not should_trade:
            if self.config.log_level >= 1:
                print(f"[FILTER] Trade blocked: {filter_reason}")
            self.stats['filtered_signals'] += 1
            self.stats['total_cycles'] += 1
            return False

        # SAC执行优化
        execution_state = self._convert_to_execution_state(snapshot, meta_position)
        try:
            execution_action = self.execution_agent.act(execution_state, deterministic=False)
        except Exception as e:
            print(f"[ERROR] Execution agent failed: {e}")
            return False

        # 解析动作
        side, order_type, price, quantity = self._convert_execution_to_order(
            meta_position, execution_action, snapshot
        )

        if quantity <= 0:
            self.stats['total_cycles'] += 1
            return False

        # ===== 核心优化: 强制Maker =====
        success = self._place_maker_order(side, price, quantity, snapshot)

        if success:
            self.stats['actions_executed'] += 1
            if self.config.log_level >= 1:
                side_name = "BUY" if side == OrderSide.BUY else "SELL"
                type_name = "MAKER" if self.config.force_maker else "TAKER"
                print(f"[EXEC] {type_name} {side_name}: qty={quantity:.4f}, price={price:.2f}")

        self.stats['total_cycles'] += 1
        return True

    def _convert_to_observation(self, snapshot: MarketSnapshot) -> np.ndarray:
        """转换市场快照为观察向量"""
        spread = snapshot.best_ask - snapshot.best_bid
        obs = np.array([
            snapshot.best_bid,
            snapshot.best_ask,
            snapshot.micro_price,
            spread,
            snapshot.order_flow_imbalance,
            snapshot.trade_imbalance,
            snapshot.bid_queue_position,
            snapshot.ask_queue_position,
            snapshot.volatility_estimate,
        ], dtype=np.float32)
        return obs

    def _convert_to_execution_state(self, snapshot: MarketSnapshot,
                                    meta_position: float) -> np.ndarray:
        """转换为SAC执行状态"""
        ofi = snapshot.order_flow_imbalance
        queue_ratio = (snapshot.bid_queue_position + snapshot.ask_queue_position) / 2
        hazard_rate = 0.1
        adverse_score = snapshot.adverse_score
        toxic_prob = snapshot.toxic_probability
        spread = snapshot.best_ask - snapshot.best_bid
        micro_momentum = np.sign(snapshot.order_flow_imbalance + snapshot.trade_imbalance)
        volatility = snapshot.volatility_estimate
        trade_flow = snapshot.trade_imbalance
        inventory = float(np.clip(meta_position, -1.0, 1.0))

        state = np.array([
            ofi, queue_ratio, hazard_rate, adverse_score, toxic_prob,
            spread, micro_momentum, volatility, trade_flow, inventory
        ], dtype=np.float32)
        return state

    def _convert_execution_to_order(self, meta_position: float,
                                    execution_action: np.ndarray,
                                    snapshot: MarketSnapshot):
        """将AI动作转换为订单参数"""
        _direction, aggression, size_scale = execution_action

        combined_direction = float(np.sign(meta_position))
        if abs(combined_direction) < 0.1:
            return 0, 0, 0, 0

        side = OrderSide.BUY if combined_direction > 0 else OrderSide.SELL

        # 根据aggression决定订单类型和价格
        aggression = float(np.clip(aggression, -1.0, 1.0))
        if aggression > 0.5 and not self.config.force_maker:
            order_type = OrderType.MARKET
            price = 0.0
        else:
            order_type = OrderType.LIMIT
            if side == OrderSide.BUY:
                price = snapshot.best_bid
            else:
                price = snapshot.best_ask

        # 计算数量
        size_scale = float(np.clip(size_scale, -1.0, 1.0))
        base_size = 0.01
        size_factor = (size_scale + 1.0) / 2.0
        quantity = base_size * size_factor * abs(combined_direction)
        quantity = max(0.001, min(quantity, 1.0))

        return side, order_type, price, quantity

    def print_stats(self):
        """打印优化后统计"""
        elapsed = time.time() - self.stats['start_time']
        cps = self.stats['total_cycles'] / elapsed if elapsed > 0 else 0

        print("\n" + "=" * 70)
        print("OPTIMIZED Live Integrator Statistics")
        print("=" * 70)
        print(f"Total cycles: {self.stats['total_cycles']}")
        print(f"Actions executed: {self.stats['actions_executed']}")
        print(f"Filtered signals: {self.stats['filtered_signals']}")
        print(f"  - By value: {self.stats.get('filtered_by_value', 0)}")
        print(f"  - By rate: {self.stats.get('filtered_by_rate', 0)}")
        print(f"Maker orders: {self.stats['maker_orders']}")
        print(f"Taker orders: {self.stats['taker_orders']}")
        print(f"Cycles per second: {cps:.1f}")
        print("=" * 70)


def main():
    """主入口"""
    parser = argparse.ArgumentParser(description='Optimized HFT Python AI Brain')
    parser.add_argument('--symbol', default='BTCUSDT')
    parser.add_argument('--interval-ms', type=int, default=1)
    parser.add_argument('--min-confidence', type=float, default=0.5)
    parser.add_argument('--no-dry-run', action='store_true')
    parser.add_argument('--force-maker', action='store_true', default=True)
    parser.add_argument('--max-trades-per-min', type=int, default=3)

    args = parser.parse_args()

    config = IntegratorConfig(
        symbol=args.symbol,
        polling_interval_ms=args.interval_ms,
        min_confidence=args.min_confidence,
        dry_run=not args.no_dry_run,
        force_maker=args.force_maker,
        max_trades_per_min=args.max_trades_per_min,
    )

    print("=" * 70)
    print("OPTIMIZED Live Integrator")
    print("=" * 70)
    print(f"Force Maker: {config.force_maker}")
    print(f"Fee Model: {config.fee_bps}bps")
    print(f"Min Expected Value: {config.min_expected_value_bps}bps")
    print(f"Max Trades/Min: {config.max_trades_per_min}")
    print("=" * 70)

    # Note: Full implementation requires SHM setup
    print("\n[NOTE] This is the optimized version with cost controls.")
    print("Integrate with existing SHM setup to run.")


if __name__ == '__main__':
    main()
