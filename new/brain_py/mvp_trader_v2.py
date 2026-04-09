"""
MVP Trader V2 - Alpha V2 升级版

集成：
1. FeatureEngine - 时序特征计算
2. RewardEngine - 即时奖励计算
3. IcMonitor - IC监控
4. SAC Agent - 强化学习决策

这是从"被动做市"到"自适应混合交易"的核心升级。
"""
import os
import sys
import time
import json
import logging
import numpy as np
from datetime import datetime
from typing import Dict, Optional, Tuple
from collections import deque

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv('../.env')

# MVP核心模块
from mvp import SimpleQueueOptimizer, ToxicFlowDetector, SpreadCapture
from mvp.feature_engine import FeatureEngine
from mvp.reward_engine import RewardEngine, TradeOutcome
from performance.ic_monitor import IcMonitor
from performance.pnl_attribution import PnLAttribution, Trade, TradeSide, OrderType

# SAC模块（需要单独安装）
try:
    from rl.sac_agent import SACAgent
    SAC_AVAILABLE = True
except ImportError:
    SAC_AVAILABLE = False
    logging.warning("SAC not available, using rule-based fallback")


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('MVPTraderV2')


class MVPTraderV2:
    """
    MVP Trader V2 - 具有时间序列预测能力的智能交易系统

    核心改进：
    1. 从静态快照到动态时序（FeatureEngine）
    2. 从结果奖励到过程奖励（RewardEngine）
    3. 从固定策略到自适应学习（SAC Agent）
    4. 从盲目交易到信号监控（IcMonitor）
    """

    def __init__(self,
                 symbol: str = "BTCUSDT",
                 initial_capital: float = 1000.0,
                 max_position: float = 0.1,
                 tick_size: float = 0.01,
                 use_sac: bool = True,
                 shadow_mode: bool = True):
        """
        初始化V2交易系统

        Args:
            symbol: 交易对
            initial_capital: 初始资金
            max_position: 最大仓位
            tick_size: 最小价格单位
            use_sac: 是否使用SAC（否则使用规则策略）
            shadow_mode: 影子模式（只学习不下单）
        """
        self.symbol = symbol
        self.initial_capital = initial_capital
        self.max_position = max_position
        self.tick_size = tick_size
        self.shadow_mode = shadow_mode

        logger.info(f"=" * 70)
        logger.info(f"MVP Trader V2 Initialized")
        logger.info(f"  Symbol: {symbol}")
        logger.info(f"  Capital: ${initial_capital}")
        logger.info(f"  Max Position: {max_position}")
        logger.info(f"  Shadow Mode: {shadow_mode}")
        logger.info(f"  SAC Enabled: {use_sac and SAC_AVAILABLE}")
        logger.info(f"=" * 70)

        # ========== 核心引擎 ==========

        # 1. 特征引擎（新增）
        self.feature_engine = FeatureEngine(ema_alpha=0.3, history_len=10)

        # 2. 奖励引擎（新增）
        self.reward_engine = RewardEngine(
            horizon_seconds=3.0,
            w_dir=0.5,
            w_micro=0.3,
            w_adv=0.4,
            w_pos=0.1
        )

        # 3. IC监控器（新增）
        self.ic_monitor = IcMonitor(window=500)

        # 4. SAC智能体（新增）
        self.use_sac = use_sac and SAC_AVAILABLE
        if self.use_sac:
            self.sac_agent = SACAgent(state_dim=10, action_dim=4)
            logger.info("[OK] SAC Agent initialized")
        else:
            self.sac_agent = None
            logger.info("[INFO] Using rule-based strategy (SAC disabled)")

        # ========== 原有模块 ==========

        self.queue_optimizer = SimpleQueueOptimizer(
            target_queue_ratio=0.3,
            calibration_factor=3.14
        )
        self.toxic_detector = ToxicFlowDetector(threshold=0.3)
        self.spread_capture = SpreadCapture(min_spread_ticks=2, tick_size=tick_size)
        self.pnl_attributor = PnLAttribution()

        # ========== 状态跟踪 ==========

        self.current_position = 0.0
        self.current_pnl = 0.0
        self.last_state = None
        self.last_action = None
        self.last_mid_price = None
        self.pending_trades = []  # 待计算奖励的交易

        # 统计
        self.tick_count = 0
        self.trade_count = 0
        self.start_time = time.time()

        # 性能监控
        self.latency_history = deque(maxlen=100)

    def process_tick(self, orderbook: Dict) -> Optional[Dict]:
        """
        处理每个tick（核心交易循环）

        Args:
            orderbook: 订单簿数据

        Returns:
            交易指令或None
        """
        start_time = time.time()
        self.tick_count += 1

        # 0. 解析订单簿
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])
        if not bids or not asks:
            return None

        best_bid = bids[0]['price'] if isinstance(bids[0], dict) else bids[0][0]
        best_ask = asks[0]['price'] if isinstance(asks[0], dict) else asks[0][0]
        mid_price = (best_bid + best_ask) / 2.0

        # 1. 计算交易压力（简化版）
        trade_pressure = self._estimate_trade_pressure(orderbook)

        # 2. 毒流检测
        toxic_alert = self.toxic_detector.detect(orderbook, None)
        toxic_score = 1.0 if toxic_alert.is_toxic else 0.0

        # 3. 构建状态向量（使用FeatureEngine）
        state = self.feature_engine.compute_state(
            orderbook=orderbook,
            inventory=self.current_position,
            toxic_score=toxic_score,
            trade_pressure=trade_pressure
        )

        # 4. 记录IC监控（在决策前）
        self.ic_monitor.record_signal(state[0], mid_price)  # 使用OFI作为信号
        if self.last_mid_price is not None:
            self.ic_monitor.record_price(mid_price)

        # 5. SAC决策或规则决策
        if self.use_sac and self.sac_agent is not None:
            action = self.sac_agent.select_action(state, evaluate=self.shadow_mode)
            decision = self._decode_sac_action(action, state, orderbook)
        else:
            decision = self._rule_based_decision(state, orderbook)

        # 6. 处理延迟奖励（如果有完成的交易）
        self._process_delayed_rewards(mid_price)

        # 7. 执行交易（如果不是影子模式）
        order = None
        if not self.shadow_mode and decision['action'] != 'HOLD':
            order = self._execute_decision(decision, orderbook)
            if order:
                self.trade_count += 1

        # 8. SAC学习更新
        if self.use_sac and self.last_state is not None and self.last_action is not None:
            reward = self._compute_step_reward(state, decision, mid_price)
            done = False
            self.sac_agent.replay_buffer.push(
                self.last_state, self.last_action, reward, state, done
            )
            if len(self.sac_agent.replay_buffer) > 256:
                self.sac_agent.update(256)

        # 9. 保存状态
        self.last_state = state.copy()
        self.last_action = action if self.use_sac else None
        self.last_mid_price = mid_price

        # 10. 记录延迟
        latency_ms = (time.time() - start_time) * 1000
        self.latency_history.append(latency_ms)

        return order

    def _estimate_trade_pressure(self, orderbook: Dict) -> float:
        """估算交易压力 [-1, 1]"""
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])
        if not bids or not asks:
            return 0.0

        bid_size = sum(b['qty'] if isinstance(b, dict) else b[1] for b in bids[:3])
        ask_size = sum(a['qty'] if isinstance(a, dict) else a[1] for a in asks[:3])

        if bid_size + ask_size == 0:
            return 0.0

        # 买盘压力大 → 看涨信号
        return (bid_size - ask_size) / (bid_size + ask_size)

    def _decode_sac_action(self, action: np.ndarray, state: np.ndarray, orderbook: Dict) -> Dict:
        """
        解码SAC动作

        Args:
            action: [weight_adj, threshold_adj, pos_scale, aggressiveness]

        Returns:
            决策字典
        """
        weight_adj, threshold_adj, pos_scale_raw, agg_raw = action

        # 映射到实际范围
        alpha_weight = 1.0 + weight_adj * 0.5  # [0.5, 1.5]
        threshold = 0.001 * (1.0 + threshold_adj * 0.5)  # [0.0005, 0.0015]
        pos_scale = (pos_scale_raw + 1) / 2  # [0, 1]
        aggressiveness = (agg_raw + 1) / 2  # [0, 1]

        # 计算Alpha得分
        alpha_score = state[0] * alpha_weight  # OFI * weight

        return self._three_stage_decision(
            alpha_score, threshold, aggressiveness, state[9], orderbook, pos_scale
        )

    def _rule_based_decision(self, state: np.ndarray, orderbook: Dict) -> Dict:
        """基于规则的决策（SAC不可用时使用）"""
        ofi = state[0]
        toxic = state[9]

        threshold = 0.001
        aggressiveness = 0.3 if abs(ofi) > 0.5 else 0.0

        return self._three_stage_decision(
            ofi, threshold, aggressiveness, toxic, orderbook, 1.0
        )

    def _three_stage_decision(self,
                              alpha_score: float,
                              threshold: float,
                              aggressiveness: float,
                              toxic_score: float,
                              orderbook: Dict,
                              pos_scale: float) -> Dict:
        """
        三段式决策

        Returns:
            {'action': 'HOLD'/'LIMIT'/'MARKET', 'side': ..., 'size': ..., 'price': ...}
        """
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])
        best_bid = bids[0]['price'] if isinstance(bids[0], dict) else bids[0][0]
        best_ask = asks[0]['price'] if isinstance(asks[0], dict) else asks[0][0]

        order_size = self.max_position * pos_scale * (0.5 if not self.use_sac else 1.0)

        # 阶段1: 观望
        if abs(alpha_score) < threshold or toxic_score > 0.3:
            return {'action': 'HOLD'}

        side = 'BUY' if alpha_score > 0 else 'SELL'

        # 阶段2: 被动挂单
        if aggressiveness < 0.5:
            return {
                'action': 'LIMIT',
                'side': side,
                'size': order_size,
                'price': best_bid if side == 'SELL' else best_ask
            }

        # 阶段3: 主动吃单
        return {
            'action': 'MARKET',
            'side': side,
            'size': order_size
        }

    def _execute_decision(self, decision: Dict, orderbook: Dict) -> Optional[Dict]:
        """执行决策"""
        action = decision.get('action')
        if action == 'HOLD':
            return None

        order = {
            'id': f"v2_{int(time.time() * 1000)}",
            'symbol': self.symbol,
            'action': action,
            'side': decision.get('side'),
            'qty': decision.get('size', 0),
            'price': decision.get('price'),
            'timestamp': time.time()
        }

        logger.info(f"[ORDER] {action} {order['side']} {order['qty']:.4f} @ {order.get('price', 'MARKET')}")

        # 记录待处理交易（用于延迟奖励计算）
        if action in ['LIMIT', 'MARKET']:
            self.pending_trades.append({
                'order': order,
                'timestamp': time.time(),
                'mid_price': self.last_mid_price,
                'alpha_score': self.last_state[0] if self.last_state is not None else 0
            })

        return order

    def _process_delayed_rewards(self, current_mid_price: float):
        """处理延迟奖励（3秒后计算）"""
        now = time.time()
        completed = []

        for trade in self.pending_trades:
            elapsed = now - trade['timestamp']
            if elapsed >= 3.0:  # 3秒后计算奖励
                # 计算奖励
                reward = self.reward_engine.compute(
                    alpha_score=trade['alpha_score'],
                    mid_price_now=trade['mid_price'],
                    mid_price_future=current_mid_price,
                    fill_price=trade['order'].get('price'),
                    position=self.current_position,
                    side=trade['order'].get('side')
                )

                logger.debug(f"[REWARD] Delayed reward computed: {reward:.4f}")
                completed.append(trade)

        for c in completed:
            self.pending_trades.remove(c)

    def _compute_step_reward(self, state: np.ndarray, decision: Dict, mid_price: float) -> float:
        """计算单步奖励（简化版，实际应使用延迟奖励）"""
        # 如果有实际成交，使用RewardEngine
        if self.pending_trades:
            last_trade = self.pending_trades[-1]
            if time.time() - last_trade['timestamp'] < 1.0:  # 刚成交
                return self.reward_engine.compute(
                    alpha_score=last_trade['alpha_score'],
                    mid_price_now=last_trade['mid_price'],
                    mid_price_future=mid_price,
                    fill_price=last_trade['order'].get('price'),
                    position=self.current_position,
                    side=last_trade['order'].get('side')
                )

        # 否则给予小惩罚（鼓励交易）
        return -0.01

    def get_status(self) -> Dict:
        """获取系统状态"""
        runtime = time.time() - self.start_time

        # IC统计
        ic_decay = self.ic_monitor.get_ic_decay()
        ic_stats = self.ic_monitor.get_ic_statistics('1s')

        # 奖励统计
        reward_stats = self.reward_engine.get_statistics()

        return {
            'runtime_seconds': runtime,
            'tick_count': self.tick_count,
            'trade_count': self.trade_count,
            'current_position': self.current_position,
            'current_pnl': self.current_pnl,
            'shadow_mode': self.shadow_mode,
            'use_sac': self.use_sac,

            'ic_metrics': {
                'ic_1s': ic_decay.get('IC_1s', 0),
                'ic_3s': ic_decay.get('IC_3s', 0),
                'ic_mean': ic_stats.get('mean', 0),
                'ic_ir': ic_stats.get('ir', 0),
                'signal_effective': self.ic_monitor.is_signal_effective('1s')
            },

            'reward_metrics': reward_stats,

            'performance': {
                'avg_latency_ms': np.mean(self.latency_history) if self.latency_history else 0,
                'max_latency_ms': np.max(self.latency_history) if self.latency_history else 0
            }
        }

    def print_report(self):
        """打印运行报告"""
        status = self.get_status()

        print("\n" + "=" * 70)
        print("MVP Trader V2 - Report")
        print("=" * 70)

        print(f"\n[Runtime]")
        print(f"  Duration: {status['runtime_seconds']:.1f}s")
        print(f"  Ticks: {status['tick_count']}")
        print(f"  Trades: {status['trade_count']}")

        print(f"\n[IC Metrics]")
        ic = status['ic_metrics']
        print(f"  IC 1s: {ic['ic_1s']:.4f}")
        print(f"  IC 3s: {ic['ic_3s']:.4f}")
        print(f"  IC Mean: {ic['ic_mean']:.4f}")
        print(f"  IC IR: {ic['ic_ir']:.4f}")
        print(f"  Signal Effective: {ic['signal_effective']}")

        print(f"\n[Reward Metrics]")
        rm = status['reward_metrics']
        print(f"  Mean: {rm.get('mean', 0):.4f}")
        print(f"  Total: {rm.get('total', 0):.4f}")
        print(f"  Positive Ratio: {rm.get('positive_ratio', 0):.2%}")

        print("\n" + "=" * 70)


# 测试代码
if __name__ == "__main__":
    print("=" * 70)
    print("MVP Trader V2 - Test")
    print("=" * 70)

    # 创建V2交易器（影子模式）
    trader = MVPTraderV2(
        symbol='BTCUSDT',
        initial_capital=1000.0,
        max_position=0.1,
        use_sac=False,  # 测试时使用规则策略
        shadow_mode=True
    )

    # 模拟100个tick
    print("\n模拟100个ticks...")
    np.random.seed(42)
    base_price = 50000.0

    for i in range(100):
        # 生成订单簿
        spread = np.random.uniform(0.5, 2.0)
        bid = base_price - spread / 2
        ask = base_price + spread / 2

        # 添加趋势
        trend = np.random.randn() * 0.5
        base_price *= (1 + trend * 0.0001)

        orderbook = {
            'bids': [{'price': bid, 'qty': np.random.uniform(1, 3)}],
            'asks': [{'price': ask, 'qty': np.random.uniform(1, 3)}]
        }

        # 处理tick
        order = trader.process_tick(orderbook)

        if order:
            print(f"  Tick {i+1}: {order['action']} {order.get('side', '')}")

        time.sleep(0.01)  # 模拟延迟

    # 打印报告
    trader.print_report()

    print("\n" + "=" * 70)
    print("Test completed!")
    print("=" * 70)
