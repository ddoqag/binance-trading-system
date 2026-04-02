"""
live_integrator.py - Python AI Brain Integration for Live Trading
整合 Meta-Agent + MoE + SAC + 共享内存通信

工作流程：
1. 从 Go 引擎共享内存读取市场快照
2. Meta-Agent 分析市场状态，选择专家策略
3. MoE 混合专家生成共识动作
4. SAC 执行优化生成最终下单指令
5. 写入订单命令到共享内存，Go 引擎执行
"""

import time
import mmap
import struct
import argparse
from typing import Optional, Tuple
from dataclasses import dataclass

import numpy as np

from .meta_agent import MetaAgent, MetaAgentConfig
from .moe.mixture_of_experts import MixtureOfExperts
from .agents.execution_sac import ExecutionSACAgent
from .ab_testing import ABTestIntegrator, ModelABTest, ModelABTestConfig, StrategyABTest
from shared.protocol import (
    MarketSnapshot,
    OrderCommand,
    OrderType,
    OrderSide,
    unpack_market_snapshot,
    pack_order_command,
    HEADER_SIZE,
    HFT_SHM_SIZE_DEFAULT,
)
from shared.shm_reader import SharedMemoryReader
from shared.shm_writer import SharedMemoryOrderWriter


@dataclass
class IntegratorConfig:
    """实盘集成配置"""
    symbol: str = "BTCUSDT"
    shm_name: str = "hft_shared_memory"
    polling_interval_ms: int = 1  # 轮询间隔 (ms)
    min_confidence: float = 0.5
    dry_run: bool = True
    log_level: int = 1  # 0=quiet, 1=info, 2=debug
    ab_test_enabled: bool = False
    ab_test_result_dir: str = "./ab_test_results"
    base_order_size: float = 0.01


class LiveAIIntegrator:
    """实盘 AI 集成器

    从 Go 引擎读取市场数据，运行 AI 决策，写回订单命令
    Supports A/B testing of models and strategies
    """

    def __init__(self, integrator_config: IntegratorConfig = None):
        self.config = integrator_config or IntegratorConfig()
        self.reader: Optional[SharedMemoryReader] = None
        self.writer: Optional[SharedMemoryOrderWriter] = None
        self.meta_agent: Optional[MetaAgent] = None
        self.moe: Optional[MixtureOfExperts] = None
        self.execution_agent: Optional[ExecutionSACAgent] = None
        self.ab_integrator: Optional[ABTestIntegrator] = None
        self.running = False
        self.last_sequence = 0
        self.stats = {
            'total_cycles': 0,
            'actions_executed': 0,
            'errors': 0,
            'ab_tests_active': 0,
            'start_time': 0.0,
        }

    def initialize(self) -> bool:
        """初始化所有组件"""
        print("[INFO] Initializing Live AI Integrator...")

        # 连接共享内存
        try:
            self.reader = SharedMemoryReader(self.config.shm_name, HFT_SHM_SIZE_DEFAULT)
            if not self.reader.connect():
                print("[ERROR] Failed to connect to shared memory reader")
                return False

            self.writer = SharedMemoryOrderWriter(self.config.shm_name, HFT_SHM_SIZE_DEFAULT)
            if not self.writer.connect():
                print("[ERROR] Failed to connect to shared memory writer")
                return False

            print("[INFO] Connected to shared memory successfully")
        except Exception as e:
            print(f"[ERROR] Shared memory connection failed: {e}")
            return False

        # 初始化 Meta-Agent
        try:
            meta_config = MetaAgentConfig(
                min_regime_confidence=self.config.min_confidence,
                strategy_switch_cooldown=1.0,
                max_strategies_active=3,
            )
            self.meta_agent = MetaAgent(meta_config)
            print("[INFO] Meta-Agent initialized")
        except Exception as e:
            print(f"[ERROR] Failed to initialize Meta-Agent: {e}")
            return False

        # 初始化混合专家
        try:
            # MoE 已经在 Meta-Agent 中集成
            print("[INFO] Mixture of Experts ready")
        except Exception as e:
            print(f"[ERROR] Failed to initialize MoE: {e}")
            return False

        # 初始化执行优化 SAC
        try:
            self.execution_agent = ExecutionSACAgent()
            # 这里应该加载训练好的权重
            print("[INFO] Execution SAC Agent initialized")
        except Exception as e:
            print(f"[ERROR] Failed to initialize Execution SAC: {e}")
            return False

        # Initialize A/B testing integrator if enabled
        if self.config.ab_test_enabled:
            try:
                self.ab_integrator = ABTestIntegrator(result_dir=self.config.ab_test_result_dir)
                self.stats['ab_tests_active'] = len(self.ab_integrator.get_all_conclusions())
                print(f"[INFO] A/B Testing integrator initialized, result dir: {self.config.ab_test_result_dir}")
            except Exception as e:
                print(f"[ERROR] Failed to initialize A/B Testing: {e}")
                return False

        self.stats['start_time'] = time.time()
        self.running = True
        print("[INFO] All components initialized successfully")
        return True

    def run_cycle(self) -> bool:
        """运行一个决策循环

        Returns:
            True if a decision was made, False if no new data
        """
        if not self.running:
            return False

        # 读取头部
        try:
            header = self.reader.read_header()
        except Exception as e:
            print(f"[ERROR] Failed to read header: {e}")
            self.stats['errors'] += 1
            return False

        # 检查是否有新数据
        if header.last_market_snapshot.sequence == self.last_sequence:
            return False

        self.last_sequence = header.last_market_snapshot.sequence
        snapshot = header.last_market_snapshot

        # 提取特征
        observation = self._convert_to_observation(snapshot)
        if self.config.log_level >= 2:
            print(f"[DEBUG] New snapshot: seq={snapshot.sequence}, best_bid={snapshot.best_bid:.2f}, best_ask={snapshot.best_ask:.2f}")

        # Meta-Agent 执行
        try:
            result = self.meta_agent.execute(observation)
        except Exception as e:
            print(f"[ERROR] Meta-Agent execution failed: {e}")
            self.stats['errors'] += 1
            return False

        if self.config.log_level >= 1:
            print(f"[INFO] Meta-Agent: regime={result.market_regime}, "
                  f"selected={[s.name for s in result.selected_strategies]}, "
                  f"confidence={result.overall_confidence:.2f}")

        # 如果置信度太低，不行动
        if result.overall_confidence < self.config.min_confidence:
            if self.config.log_level >= 2:
                print(f"[DEBUG] Confidence too low ({result.overall_confidence:.2f}), skipping")
            self.stats['total_cycles'] += 1
            return False

        # 获取最终动作（这里已经整合了专家投票）
        action = result.final_action
        if action is None:
            if self.config.log_level >= 2:
                print("[DEBUG] No action generated, skipping")
            self.stats['total_cycles'] += 1
            return False

        # SAC 执行优化
        # 调整 aggression 和 size 基于当前市场条件
        execution_state = self._convert_to_execution_state(snapshot, result)
        try:
            execution_action = self.execution_agent.select_action(execution_state, evaluate=True)
        except Exception as e:
            print(f"[ERROR] Execution agent failed: {e}")
            self.stats['errors'] += 1
            return False

        # 解析动作并下单
        side, order_type, price, quantity = self._convert_execution_to_order(
            action.position_size, execution_action, snapshot
        )

        if quantity <= 0:
            self.stats['total_cycles'] += 1
            return False

        # 写入订单命令
        success = self._place_order(side, order_type, price, quantity, self.config.dry_run)
        if success:
            self.stats['actions_executed'] += 1
            if self.config.log_level >= 1:
                side_name = "BUY" if side == OrderSide.BUY else "SELL"
                type_name = "MARKET" if order_type == OrderType.MARKET else "LIMIT"
                print(f"[EXEC] Placed {side_name} {type_name}: qty={quantity:.4f}, price={price:.2f}")

        self.stats['total_cycles'] += 1
        return True

    def _convert_to_observation(self, snapshot: MarketSnapshot) -> np.ndarray:
        """转换市场快照为观察向量

        特征顺序 (9维):
        0: best_bid
        1: best_ask
        2: micro_price
        3: spread
        4: order_flow_imbalance
        5: trade_imbalance
        6: bid_queue_position
        7: ask_queue_position
        8: volatility_estimate
        """
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

    def _convert_to_execution_state(self, snapshot: MarketSnapshot, meta_result) -> np.ndarray:
        """转换为 SAC 执行状态 (10维)

        状态: [ofi, queue_ratio, hazard_rate, adverse_score, toxic_prob,
              spread, micro_momentum, volatility, trade_flow, inventory]
        """
        # 简化版本，使用已有信息
        ofi = snapshot.order_flow_imbalance
        queue_ratio = (snapshot.bid_queue_position + snapshot.ask_queue_position) / 2
        hazard_rate = 0.1  # 需要计算，这里占位
        adverse_score = snapshot.adverse_score
        toxic_prob = snapshot.toxic_probability
        spread = snapshot.best_ask - snapshot.best_bid
        micro_momentum = np.sign(snapshot.order_flow_imbalance + snapshot.trade_imbalance)
        volatility = snapshot.volatility_estimate
        trade_flow = snapshot.trade_imbalance
        inventory = 0.0  # 需要从账户信息读取

        state = np.array([
            ofi, queue_ratio, hazard_rate, adverse_score, toxic_prob,
            spread, micro_momentum, volatility, trade_flow, inventory
        ], dtype=np.float32)
        return state

    def _convert_execution_to_order(self, meta_position: float,
                                    execution_action: np.ndarray,
                                    snapshot: MarketSnapshot) -> Tuple[int, int, float, float]:
        """将 AI 动作转换为订单参数

        Args:
            meta_position: Meta-Agent 推荐仓位 (-1 to +1)
            execution_action: [direction, aggression, size_scale] from SAC
            snapshot: 当前市场快照

        Returns:
            (side, order_type, price, quantity)
        """
        direction, aggression, size_scale = execution_action

        # 结合方向
        combined_direction = np.sign(meta_position + direction)
        if abs(combined_direction) < 0.1:
            # 没有明确方向，不下单
            return 0, 0, 0, 0

        side = OrderSide.BUY if combined_direction > 0 else OrderSide.SELL

        # 根据 aggression 决定订单类型
        if aggression > 0.5:
            # 激进 - 市价单
            order_type = OrderType.MARKET
            price = 0.0  # 市价单价格为 0
        else:
            # 被动 - 限价单
            order_type = OrderType.LIMIT
            if side == OrderSide.BUY:
                price = snapshot.best_bid  # 挂在买一
            else:
                price = snapshot.best_ask  # 挂在卖一

        # 计算数量 = base size * size_scale * abs(combined_direction)
        base_size = self.config.base_order_size
        quantity = base_size * size_scale * abs(combined_direction)
        quantity = max(0.001, min(quantity, 1.0))  # 限制范围

        return side, order_type, price, quantity

    def _place_order(self, side: int, order_type: int, price: float,
                     quantity: float, dry_run: bool) -> bool:
        """下单到共享内存"""
        if order_type == OrderType.MARKET:
            cmd_id = self.writer.write_market_order(
                side, quantity, max_slippage_bps=10.0, dry_run=dry_run
            )
        else:
            cmd_id = self.writer.write_limit_order(
                side, price, quantity, expires_after_ms=5000, dry_run=dry_run
            )

        return cmd_id > 0

    def run_loop(self):
        """主循环"""
        print("[INFO] Starting main loop...")
        try:
            while self.running:
                self.run_cycle()
                time.sleep(self.config.polling_interval_ms / 1000.0)
                self.writer.update_ai_heartbeat(running=True)
        except KeyboardInterrupt:
            print("\n[INFO] Received interrupt, stopping...")
            self.stop()

    def stop(self):
        """停止"""
        self.running = False
        if self.reader:
            self.reader.close()
        if self.writer:
            self.writer.close()

        # Stop all A/B tests if any
        if self.ab_integrator:
            self.ab_integrator.stop_all()
            conclusions = self.ab_integrator.get_all_conclusions()
            for name, conclusion in conclusions.items():
                print(f"\n[AB TEST] {name} Conclusion:")
                print(conclusion)

        elapsed = time.time() - self.stats['start_time']
        print(f"[STATS] Total cycles: {self.stats['total_cycles']}")
        print(f"[STATS] Actions executed: {self.stats['actions_executed']}")
        print(f"[STATS] Errors: {self.stats['errors']}")
        if self.ab_integrator:
            status = self.ab_integrator.get_status()
            print(f"[STATS] Active A/B tests: {status['active_model_tests'] + status['active_strategy_tests']}")
        print(f"[STATS] Elapsed: {elapsed:.2f}s")

    def print_stats(self):
        """打印统计信息"""
        elapsed = time.time() - self.stats['start_time']
        cps = self.stats['total_cycles'] / elapsed if elapsed > 0 else 0
        print(f"\n=== Statistics ===")
        print(f"Total cycles: {self.stats['total_cycles']}")
        print(f"Actions executed: {self.stats['actions_executed']}")
        print(f"Errors: {self.stats['errors']}")
        print(f"Cycles per second: {cps:.1f}")
        print(f"=================\n")


def main():
    """主入口"""
    parser = argparse.ArgumentParser(description='HFT Python AI Brain Live Integrator')
    parser.add_argument('--symbol', default='BTCUSDT', help='Trading symbol')
    parser.add_argument('--shm-name', default='hft_shared_memory', help='Shared memory name')
    parser.add_argument('--interval-ms', type=int, default=1, help='Polling interval (ms)')
    parser.add_argument('--min-confidence', type=float, default=0.5, help='Minimum confidence to act')
    parser.add_argument('--no-dry-run', action='store_true', help='Disable dry run (real trading)')
    parser.add_argument('--log-level', type=int, default=1, help='Log level (0=quiet, 1=info, 2=debug)')
    parser.add_argument('--enable-ab-test', action='store_true', help='Enable A/B testing framework')
    parser.add_argument('--ab-test-result-dir', default='./ab_test_results', help='Directory for A/B test results')
    args = parser.parse_args()

    config = IntegratorConfig(
        symbol=args.symbol,
        shm_name=args.shm_name,
        polling_interval_ms=args.interval_ms,
        min_confidence=args.min_confidence,
        dry_run=not args.no_dry_run,
        log_level=args.log_level,
        ab_test_enabled=args.enable_ab_test,
        ab_test_result_dir=args.ab_test_result_dir,
    )

    integrator = LiveAIIntegrator(config)
    if not integrator.initialize():
        print("[FATAL] Initialization failed")
        exit(1)

    try:
        integrator.run_loop()
    finally:
        integrator.print_stats()


if __name__ == '__main__':
    main()
