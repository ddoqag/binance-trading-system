"""
live_integrator.py - Python AI Brain Integration for Live Trading
整合 Meta-Agent + MoE + SAC + 共享内存通信

工作流程：
1. 从 Go 引擎共享内存读取市场快照
2. Meta-Agent 分析市场状态，选择/过滤专家策略
3. MoE 混合专家生成共识动作（监督学习融合）
4. SAC 执行优化生成最终下单指令
5. 写入订单命令到共享内存，Go 引擎执行
"""

import time
import mmap
import struct
import argparse
from typing import Optional, Tuple, List
from dataclasses import dataclass, field

import numpy as np

from .meta_agent import (
    MetaAgent, MetaAgentConfig, ExpertAdapter,
    create_meta_agent_with_experts
)
from .agent_registry import AgentRegistry
from .regime_detector import MarketRegimeDetector
from .moe.mixture_of_experts import (
    MixtureOfExperts, TradingExpert, GatingConfig, SoftmaxGatingNetwork
)
from .agents.execution_sac import ExecutionSACAgent
from .agents import MarketRegime, ActionType
from .ab_testing import ABTestIntegrator, ModelABTest, StrategyABTest

from .qlib_models.adapters import QlibExpert, QlibExpertConfig
from .qlib_models.neural.tcn_model import TCNModel
from .qlib_models.gbdt.lightgbm_model import LightGBMModel
from .qlib_models.features import HFTFeatureMapper
from .qlib_models.historical_trainer import load_pretrained_experts

from shared.protocol import (
    MarketSnapshot,
    OrderType,
    OrderSide,
    HFT_SHM_SIZE_DEFAULT,
    AIContext,
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

    # MoE 融合控制
    moe_enabled: bool = True
    moe_temperature: float = 1.0
    moe_min_weight: float = 0.05

    # SAC 权重路径（空字符串表示不加载）
    sac_checkpoint: str = ""

    # 内部测试用：跳过共享内存连接
    skip_shm: bool = False


class MockSharedMemoryReader:
    """Mock reader for testing without Go engine."""

    def __init__(self, shm_name: str = "mock", size: int = HFT_SHM_SIZE_DEFAULT):
        self.shm_name = shm_name
        self.size = size
        self._seq = 0

    def connect(self) -> bool:
        return True

    def close(self):
        pass

    def read_header(self):
        self._seq += 1
        price = 50000.0 + np.random.randn() * 10
        spread = 0.5 + np.random.rand() * 0.5
        best_bid = price - spread / 2
        best_ask = price + spread / 2
        return type(
            "Header",
            (object,),
            {
                "last_market_snapshot": MarketSnapshot(
                    timestamp_ns=int(time.time() * 1e9),
                    sequence=self._seq,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    last_price=price,
                    micro_price=price,
                    order_flow_imbalance=np.random.randn() * 0.1,
                    trade_imbalance=np.random.randn() * 0.1,
                    bid_queue_position=np.random.rand() * 0.3,
                    ask_queue_position=np.random.rand() * 0.3,
                    spread=spread,
                    volatility_estimate=0.01 + np.random.rand() * 0.005,
                    trade_intensity=5.0 + np.random.rand() * 5.0,
                    adverse_score=np.random.randn() * 0.05,
                    toxic_probability=max(0.0, np.random.randn() * 0.1),
                    bids=[],
                    asks=[],
                )
            },
        )()


class MockSharedMemoryWriter:
    """Mock writer for testing without Go engine."""

    def __init__(self, shm_name: str = "mock", size: int = HFT_SHM_SIZE_DEFAULT):
        self.shm_name = shm_name
        self.size = size
        self.orders = []

    def connect(self) -> bool:
        return True

    def close(self):
        pass

    def write_market_order(self, side: int, quantity: float,
                           max_slippage_bps: float = 10.0, dry_run: bool = True) -> int:
        self.orders.append({"type": "market", "side": side, "quantity": quantity, "dry_run": dry_run})
        return len(self.orders)

    def write_limit_order(self, side: int, price: float, quantity: float,
                          expires_after_ms: int = 5000, dry_run: bool = True) -> int:
        self.orders.append({"type": "limit", "side": side, "price": price,
                           "quantity": quantity, "dry_run": dry_run})
        return len(self.orders)

    def write_ai_context(self, ctx):
        self.orders.append({"type": "ai_context", "ai_position": ctx.ai_position,
                           "ai_confidence": ctx.ai_confidence,
                           "regime_code": ctx.regime_code,
                           "moe_weights": [ctx.moe_weight_0, ctx.moe_weight_1, ctx.moe_weight_2, ctx.moe_weight_3]})
        return True

    def update_ai_heartbeat(self, running: bool = True):
        pass


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
        self._mock_prices: List[float] = []
        self.stats = {
            'total_cycles': 0,
            'actions_executed': 0,
            'errors': 0,
            'ab_tests_active': 0,
            'start_time': 0.0,
            'moe_weights': {},
        }

    def _create_mock_shm(self):
        """When skip_shm=True, use mock objects."""
        self.reader = MockSharedMemoryReader(self.config.shm_name)
        self.writer = MockSharedMemoryWriter(self.config.shm_name)
        return self.reader.connect() and self.writer.connect()

    def _build_qlib_experts(self):
        """构造 QlibExpert 实例。优先加载基于真实历史数据预训练的模型，否则回退到合成数据训练。"""
        # Attempt 1: load real-history pretrained experts
        try:
            hist_experts = load_pretrained_experts(
                checkpoint_dir="brain_py/qlib_models/checkpoints",
                fallback_to_random=True,
                symbol=self.config.symbol,
                interval="1m",
            )
            if len(hist_experts) >= 2:
                print(f"[INFO] Using {len(hist_experts)} historically-pretrained Qlib experts")
                return hist_experts
        except Exception as e:
            print(f"[WARN] Failed to load historical pretrained experts: {e}")

        # Attempt 2: fast synthetic training fallback
        print("[INFO] Falling back to synthetic-data Qlib experts")
        experts = []

        # LightGBM expert (tabular, requires flat 400-dim)
        try:
            lgb_model = LightGBMModel(config=None)
            lgb_model.config.input_dim = 400
            tab_x = np.random.randn(200, 400).astype(np.float32) * 0.1
            tab_y = np.random.randn(200).astype(np.float32) * 0.01
            lgb_model.fit(tab_x, tab_y)
            experts.append(
                QlibExpert(
                    QlibExpertConfig(
                        name="qlib_lightgbm",
                        model=lgb_model,
                        suitable_regimes=[MarketRegime.TREND_UP, MarketRegime.TREND_DOWN],
                    )
                )
            )
        except Exception as e:
            print(f"[WARN] Failed to build LightGBM expert: {e}")

        # TCN expert (sequence, requires (20, 20))
        try:
            tcn_model = TCNModel(config=None)
            tcn_model.config.input_dim = 20
            tcn_model.config.extra["d_feat"] = 20
            seq_x = np.random.randn(120, 20, 20).astype(np.float32) * 0.1
            seq_y = np.random.randn(120).astype(np.float32) * 0.01
            tcn_model.fit(seq_x, seq_y)
            experts.append(
                QlibExpert(
                    QlibExpertConfig(
                        name="qlib_tcn",
                        model=tcn_model,
                        suitable_regimes=[
                            MarketRegime.TREND_UP,
                            MarketRegime.RANGE,
                            MarketRegime.HIGH_VOL,
                        ],
                    )
                )
            )
        except Exception as e:
            print(f"[WARN] Failed to build TCN expert: {e}")

        return experts

    def initialize(self) -> bool:
        """初始化所有组件"""
        print("[INFO] Initializing Live AI Integrator...")

        # 连接共享内存
        try:
            if self.config.skip_shm:
                if not self._create_mock_shm():
                    print("[ERROR] Failed to create mock shared memory")
                    return False
            else:
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

        # 初始化 Meta-Agent（使用辅助函数，自动包含 registry + regime_detector）
        try:
            meta_config = MetaAgentConfig(
                min_regime_confidence=self.config.min_confidence,
                strategy_switch_cooldown=1.0,
                max_strategies_active=3,
            )
            qlib_experts = self._build_qlib_experts()
            self.meta_agent = create_meta_agent_with_experts(qlib_experts, meta_config)

            # fit regime detector with synthetic prices so it can detect immediately
            prices = np.cumsum(np.random.randn(300) * 0.01) + 100
            self.meta_agent.regime_detector.fit(prices)
            print(f"[INFO] Meta-Agent initialized with {len(qlib_experts)} Qlib experts")
        except Exception as e:
            print(f"[ERROR] Failed to initialize Meta-Agent: {e}")
            return False

        # 初始化 MoE（包装所有已注册的策略 expert + SAC）
        try:
            if self.config.moe_enabled:
                self._setup_moe()
                print("[INFO] Mixture of Experts initialized")
        except Exception as e:
            print(f"[ERROR] Failed to initialize MoE: {e}")
            return False

        # 初始化执行优化 SAC
        try:
            from .agents.execution_sac import SACConfig
            sac_config = SACConfig(state_dim=10)
            self.execution_agent = ExecutionSACAgent(sac_config)
            if self.config.sac_checkpoint:
                ok = self.execution_agent.load(self.config.sac_checkpoint)
                print(f"[INFO] SAC checkpoint load: {ok}")
            else:
                print("[INFO] Execution SAC Agent initialized (no checkpoint loaded)")
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

    def _setup_moe(self):
        """从 Meta-Agent 的策略构建 MoE 专家池。"""
        trading_experts: List[TradingExpert] = []

        # 包装所有 Meta-Agent 已注册的策略 expert
        for name, strategy in self.meta_agent._strategies.items():
            if hasattr(strategy, "expert"):
                te = TradingExpert(strategy.expert, expert_id=name)
                trading_experts.append(te)

        if len(trading_experts) < 2:
            print("[WARN] Not enough experts for MoE, disabling MoE")
            self.config.moe_enabled = False
            return

        gating_config = GatingConfig(
            input_dim=9,
            temperature=self.config.moe_temperature,
            min_weight=self.config.moe_min_weight,
            use_performance_weighting=True,
            performance_window=100,
        )
        self.moe = MixtureOfExperts(
            experts=trading_experts,
            gating_network=SoftmaxGatingNetwork(gating_config),
            config=gating_config,
        )

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

        # Meta-Agent 执行（获取 regime + 选中的策略）
        try:
            result = self.meta_agent.execute(observation)
        except Exception as e:
            print(f"[ERROR] Meta-Agent execution failed: {e}")
            self.stats['errors'] += 1
            return False

        if self.config.log_level >= 1:
            print(f"[INFO] Meta-Agent: regime={result.regime.value}, "
                  f"selected={result.selected_strategy}, "
                  f"confidence={result.confidence:.2f}")

        # 如果置信度太低，不行动
        if result.confidence < self.config.min_confidence:
            if self.config.log_level >= 2:
                print(f"[DEBUG] Confidence too low ({result.confidence:.2f}), skipping")
            self.stats['total_cycles'] += 1
            return False

        # 获取 Meta-Agent 推荐的仓位（MoE 融合 或 单一策略）
        meta_position = 0.0
        if self.config.moe_enabled and self.moe is not None:
            try:
                fused_pred, weights = self.moe.predict(observation)
                # fused_pred = [position_size, confidence, action_value]
                meta_position = float(np.clip(fused_pred[0], -1.0, 1.0))
                self.stats['moe_weights'] = self.moe.get_expert_weights_dict()
                if self.config.log_level >= 1:
                    print(f"[INFO] MoE fused position={meta_position:.3f}, weights={self.stats['moe_weights']}")
            except Exception as e:
                print(f"[ERROR] MoE prediction failed: {e}")
                self.stats['errors'] += 1
                # fallback to single strategy action
                if result.action is not None:
                    meta_position = float(np.clip(result.action.position_size, -1.0, 1.0))
        else:
            if result.action is not None:
                meta_position = float(np.clip(result.action.position_size, -1.0, 1.0))

        if abs(meta_position) < 0.05:
            if self.config.log_level >= 2:
                print("[DEBUG] Position too small, skipping")
            self.stats['total_cycles'] += 1
            return False

        # SAC 执行优化
        execution_state = self._convert_to_execution_state(snapshot, meta_position)
        try:
            execution_action = self.execution_agent.act(execution_state, deterministic=False)
        except Exception as e:
            print(f"[ERROR] Execution agent failed: {e}")
            self.stats['errors'] += 1
            return False

        # 解析动作并下单
        side, order_type, price, quantity = self._convert_execution_to_order(
            meta_position, execution_action, snapshot
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

            # 写入 AI 决策上下文到共享内存固定偏移，供 Go 引擎读取
            try:
                weights = self.stats.get('moe_weights', {})
                w_list = [weights.get(eid, 0.0) for eid in (self.moe.get_expert_ids() if self.moe else [])]
                while len(w_list) < 4:
                    w_list.append(0.0)
                regime_map = {
                    "unknown": 0, "trending": 1, "mean_reverting": 2,
                    "high_volatility": 3, "low_volatility": 4,
                }
                ctx = AIContext(
                    ai_position=float(meta_position),
                    ai_confidence=float(result.confidence),
                    moe_weight_0=float(w_list[0]),
                    moe_weight_1=float(w_list[1]),
                    moe_weight_2=float(w_list[2]),
                    moe_weight_3=float(w_list[3]),
                    regime_code=regime_map.get(str(result.regime.value).lower(), 0),
                    num_active_experts=len(weights),
                )
                self.writer.write_ai_context(ctx)
            except Exception as e:
                if self.config.log_level >= 2:
                    print(f"[DEBUG] Failed to write AI context: {e}")

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

    def _convert_to_execution_state(self, snapshot: MarketSnapshot, meta_position: float) -> np.ndarray:
        """转换为 SAC 执行状态 (10维)

        状态: [ofi, queue_ratio, hazard_rate, adverse_score, toxic_prob,
              spread, micro_momentum, volatility, trade_flow, inventory]
        """
        ofi = snapshot.order_flow_imbalance
        queue_ratio = (snapshot.bid_queue_position + snapshot.ask_queue_position) / 2
        hazard_rate = 0.1  # placeholder
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
                                    snapshot: MarketSnapshot) -> Tuple[int, int, float, float]:
        """将 AI 动作转换为订单参数

        Args:
            meta_position: MoE / Meta-Agent 推荐仓位 (-1 to +1)
            execution_action: [direction_unused, aggression, size_scale] from SAC
            snapshot: 当前市场快照

        Returns:
            (side, order_type, price, quantity)
        """
        _direction, aggression, size_scale = execution_action

        combined_direction = float(np.sign(meta_position))
        if abs(combined_direction) < 0.1:
            return 0, 0, 0, 0

        side = OrderSide.BUY if combined_direction > 0 else OrderSide.SELL

        # 根据 aggression 决定订单类型
        aggression = float(np.clip(aggression, -1.0, 1.0))
        if aggression > 0.5:
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
        base_size = self.config.base_order_size
        # 映射 size_scale 从 [-1,1] -> [0,1]
        size_factor = (size_scale + 1.0) / 2.0
        quantity = base_size * size_factor * abs(combined_direction)
        quantity = max(0.001, min(quantity, 1.0))

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

        if self.meta_agent:
            self.meta_agent.shutdown()

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
    parser.add_argument('--moe', action='store_true', help='Enable MoE fusion (default: True)')
    parser.add_argument('--no-moe', action='store_true', help='Disable MoE fusion')
    parser.add_argument('--sac-checkpoint', default='', help='SAC checkpoint file to load')
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
        moe_enabled=not args.no_moe,
        sac_checkpoint=args.sac_checkpoint,
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
