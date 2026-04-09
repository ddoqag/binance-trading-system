"""
MVP HFT 交易系统入口

核心原则：
1. 可解释性 > 复杂性
2. 确定性 > 随机性
3. 防御 > 进攻
4. 可测量 > 黑箱

只保留三个核心模块：
- 队列位置优化器
- 毒流检测器
- 点差捕获器

加上必要的支持模块：
- PnL归因
- 实时校准
- 约束框架
"""

import numpy as np
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict, deque
import logging

# MVP核心模块
from mvp import SimpleQueueOptimizer, ToxicFlowDetector, SpreadCapture
from performance.pnl_attribution import PnLAttribution, Trade, TradeSide, OrderType
from queue_dynamics.calibration import LiveFillCalibrator
from agents.constrained_sac import ActionConstraintLayer, ConstraintConfig


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('MVPTrader')


@dataclass
class MVPTrade:
    """MVP简化交易记录"""
    trade_id: str
    symbol: str
    side: str
    qty: float
    entry_price: float
    target_price: float
    spread_bps: float
    timestamp: float
    order_type: str = "limit"


@dataclass
class MVPState:
    """MVP状态"""
    is_running: bool = True
    current_position: float = 0.0
    total_pnl: float = 0.0
    daily_pnl: float = 0.0
    trades_today: int = 0
    last_trade_time: float = 0.0
    kill_switched: bool = False


class MVPTrader:
    """
    MVP HFT交易系统

    只做三件事：
    1. 队列位置优化 - 永远在队列前30%
    2. 毒流检测 - 马氏距离检测，阈值0.3
    3. 点差捕获 - spread ≥ 2 ticks时挂被动单
    """

    def __init__(self,
                 symbol: str = "BTCUSDT",
                 initial_capital: float = 1000.0,
                 max_position: float = 0.5,
                 tick_size: float = 0.01):

        self.symbol = symbol
        self.initial_capital = initial_capital
        self.max_position = max_position
        self.tick_size = tick_size

        # MVP核心三模块
        self.queue_optimizer = SimpleQueueOptimizer(
            target_queue_ratio=0.3,
            calibration_factor=3.14  # 从测试发现的校准系数
        )
        self.toxic_detector = ToxicFlowDetector(
            threshold=0.3,
            mahalanobis_threshold=5.0
        )
        self.spread_capture = SpreadCapture(
            min_spread_ticks=2,
            tick_size=tick_size,
            maker_rebate=0.0002
        )

        # 支持模块
        self.pnl_attributor = PnLAttribution(
            maker_rebate_rate=0.0002,
            taker_fee_rate=0.0005
        )
        self.calibrator = LiveFillCalibrator(window_size=500)
        self.constraints = ActionConstraintLayer(
            ConstraintConfig(
                max_order_rate=10.0,         # 每秒最多10单（测试用）
                max_cancel_ratio=0.5,        # 撤单率不超过50%
                min_rest_time_ms=50.0,       # 最小间隔50ms（测试用）
                max_position_change=0.1,     # 单笔不超过10%
                max_daily_trades=200,        # 每日最多200笔
                max_drawdown_pct=0.05,       # 最大回撤5%
                kill_switch_loss=-50.0       # 累计亏损达到$50停止
            )
        )

        # 状态
        self.state = MVPState()
        self.order_id_counter = 0
        self.pending_orders = {}
        self.trade_history = deque(maxlen=1000)

        # 性能监控
        self.latency_history = deque(maxlen=100)
        self.decision_history = deque(maxlen=100)

        logger.info(f"MVP Trader initialized: {symbol}, capital=${initial_capital}")

    def process_tick(self, orderbook: Dict) -> Optional[Dict]:
        """
        处理每个tick

        Args:
            orderbook: 订单簿数据

        Returns:
            Optional[Dict]: 交易指令或None
        """
        start_time = time.time()

        # 0. 检查熔断
        if self.state.kill_switched:
            return None

        if self.constraints.check_kill_switch(self.state.total_pnl):
            self.state.kill_switched = True
            logger.critical(f"Kill switch triggered! PnL: {self.state.total_pnl:.2f}")
            return None

        # 1. 毒流检测
        recent_fills = list(self.trade_history)[-20:] if len(self.trade_history) > 0 else None
        toxic_alert = self.toxic_detector.detect(orderbook, recent_fills)

        if toxic_alert.is_toxic:
            self.decision_history.append({
                'timestamp': time.time(),
                'action': 'blocked',
                'reason': f"toxic_flow: {toxic_alert.reason}"
            })
            logger.warning(f"Toxic flow detected: {toxic_alert.reason}, blocking trade")
            return None

        # 2. 点差捕获分析
        spread_opp = self.spread_capture.analyze(orderbook, self.state.current_position)

        if not spread_opp.is_profitable:
            self.decision_history.append({
                'timestamp': time.time(),
                'action': 'skip',
                'reason': spread_opp.reason
            })
            return None

        # 3. 队列位置优化
        current_orders = {
            f"order_{k}": v for k, v in enumerate(self.pending_orders.values())
        }
        queue_action = self.queue_optimizer.decide(orderbook, current_orders)

        # 4. 构建原始动作
        # size_scale=1.0 表示使用 max_position 的全部仓位
        raw_action = np.array([
            1.0 if spread_opp.side == 'buy' else -1.0,  # direction
            0.3,  # aggression (被动挂单)
            1.0  # size_scale (使用全部max_position)
        ])

        # 5. 应用约束
        constrained_action, constraint_info = self.constraints.apply_constraints(
            raw_action, self.state.current_position, self.state.total_pnl
        )

        if constraint_info['blocked']:
            self.decision_history.append({
                'timestamp': time.time(),
                'action': 'blocked',
                'reason': f"constraint: {constraint_info['constraints_applied']}"
            })
            logger.info(f"Action blocked by constraints: {constraint_info['constraints_applied']}")
            return None

        # 6. 创建订单
        self.order_id_counter += 1
        order_id = f"mvp_{self.order_id_counter}"

        order = {
            'id': order_id,
            'symbol': self.symbol,
            'side': spread_opp.side,
            'type': 'limit',
            'qty': abs(constrained_action[2]) * self.max_position,
            'price': spread_opp.entry_price,
            'timestamp': time.time(),
            'target_price': spread_opp.target_price,
            'spread_bps': spread_opp.spread_bps,
            'expected_profit': spread_opp.net_profit_bps
        }

        # 记录预测用于校准
        self.calibrator.record_prediction(
            order_id=order_id,
            symbol=self.symbol,
            side=spread_opp.side,
            queue_ratio=0.3,  # MVP简化
            predicted_rate=1.0,  # 简化预测
            ofi=0.0,
            spread_bps=spread_opp.spread_bps
        )

        self.pending_orders[order_id] = order

        # 记录延迟
        latency_ms = (time.time() - start_time) * 1000
        self.latency_history.append(latency_ms)

        self.decision_history.append({
            'timestamp': time.time(),
            'action': 'order',
            'side': spread_opp.side,
            'spread_bps': spread_opp.spread_bps,
            'latency_ms': latency_ms
        })

        logger.info(f"Order created: {order_id}, side={spread_opp.side}, "
                   f"spread={spread_opp.spread_bps:.2f}bps, latency={latency_ms:.2f}ms")

        return order

    def on_fill(self, fill_event: Dict):
        """
        处理成交

        Args:
            fill_event: 成交事件
        """
        order_id = fill_event.get('order_id')

        # 创建PnL归因用的Trade对象
        trade = Trade(
            trade_id=order_id or f"fill_{time.time()}",
            symbol=self.symbol,
            side=TradeSide.BUY if fill_event.get('side') == 'buy' else TradeSide.SELL,
            order_type=OrderType.LIMIT,
            qty=fill_event.get('qty', 0),
            order_price=fill_event.get('order_price', 0),
            fill_price=fill_event.get('fill_price', 0),
            bid_price=fill_event.get('bid_price', 0),
            ask_price=fill_event.get('ask_price', 0),
            timestamp=time.time(),
            fee=fill_event.get('fee', 0),
            market_price_after=fill_event.get('market_price_after')
        )

        # PnL归因
        attribution = self.pnl_attributor.analyze_trade(trade)

        # 更新状态
        fill_qty = fill_event.get('qty', 0)
        if fill_event.get('side') == 'buy':
            self.state.current_position += fill_qty
        else:
            self.state.current_position -= fill_qty

        self.state.total_pnl += attribution.total_pnl
        self.state.daily_pnl += attribution.total_pnl
        self.state.trades_today += 1
        self.state.last_trade_time = time.time()

        # 记录校准
        self.calibrator.record_fill(order_id, time.time())

        # 更新队列优化器
        self.queue_optimizer.on_fill(order_id, fill_qty)

        # 更新点差捕获器
        self.spread_capture.on_fill(
            fill_event.get('side', 'buy'),
            fill_qty,
            fill_event.get('fill_price', 0)
        )

        # 记录交易历史
        self.trade_history.append({
            'timestamp': time.time(),
            'pnl': attribution.total_pnl,
            'components': attribution.components
        })

        logger.info(f"Fill: side={fill_event.get('side')}, qty={fill_qty}, "
                   f"pnl=${attribution.total_pnl:.4f}, "
                   f"spread_capture=${attribution.components.get('spread_capture', 0):.4f}")

        # 检查逆向选择损失
        adverse_loss = attribution.components.get('adverse_selection', 0)
        if adverse_loss < -0.5:
            logger.warning(f"High adverse selection loss: ${adverse_loss:.4f}")

    def on_cancel(self, order_id: str):
        """处理撤单"""
        if order_id in self.pending_orders:
            del self.pending_orders[order_id]
            self.queue_optimizer.on_cancel(order_id)
            self.constraints.record_cancel()

    def get_status(self) -> Dict:
        """获取系统状态"""
        pnl_report = self.pnl_attributor.get_cumulative_report()
        calibration_report = self.calibrator.get_calibration_report(self.symbol)

        return {
            'state': {
                'is_running': self.state.is_running,
                'kill_switched': self.state.kill_switched,
                'current_position': self.state.current_position,
                'total_pnl': self.state.total_pnl,
                'daily_pnl': self.state.daily_pnl,
                'trades_today': self.state.trades_today,
                'pending_orders': len(self.pending_orders)
            },
            'pnl_attribution': pnl_report,
            'calibration': calibration_report,
            'performance': {
                'avg_latency_ms': np.mean(list(self.latency_history)) if self.latency_history else 0,
                'max_latency_ms': np.max(list(self.latency_history)) if self.latency_history else 0,
            },
            'queue_optimizer': self.queue_optimizer.get_stats(),
            'toxic_detector': self.toxic_detector.get_stats(),
            'spread_capture': self.spread_capture.get_stats(),
            'constraints': self.constraints.get_constraint_report()
        }

    def get_health_check(self) -> Tuple[bool, str]:
        """健康检查"""
        checks = []

        # 1. PnL结构健康度
        is_healthy, reason = self.pnl_attributor.is_profitable_structure()
        checks.append(('pnl_structure', is_healthy, reason))

        # 2. 延迟检查
        if self.latency_history:
            avg_latency = np.mean(list(self.latency_history))
            checks.append(('latency', avg_latency < 2.0, f"avg={avg_latency:.2f}ms"))

        # 3. 校准可靠性
        is_calibrated = self.calibrator.is_calibration_reliable(self.symbol)
        checks.append(('calibration', is_calibrated, "reliable" if is_calibrated else "insufficient_data"))

        # 4. 毒流检测
        stats = self.toxic_detector.get_stats()
        checks.append(('toxic_detection', stats['block_count'] > 0, f"blocked={stats['block_count']}"))

        # 汇总
        all_passed = all(check[1] for check in checks)
        summary = "; ".join([f"{name}={'OK' if ok else 'FAIL'}({reason})" for name, ok, reason in checks])

        return all_passed, summary

    def reset_daily(self):
        """重置每日统计"""
        self.state.daily_pnl = 0.0
        self.state.trades_today = 0
        self.constraints.reset_daily_stats()

    def shutdown(self):
        """关闭系统"""
        logger.info("MVP Trader shutting down...")
        self.state.is_running = False

        # 输出最终报告
        status = self.get_status()
        logger.info("=" * 60)
        logger.info("Final Report")
        logger.info("=" * 60)
        logger.info(f"Total PnL: ${status['state']['total_pnl']:.4f}")
        logger.info(f"Total Trades: {status['state']['trades_today']}")
        logger.info(f"Final Position: {status['state']['current_position']:.4f}")
        logger.info("=" * 60)


# 测试/演示代码
if __name__ == "__main__":
    print("=" * 60)
    print("MVP Trader Test")
    print("=" * 60)

    # 创建MVP交易者
    trader = MVPTrader(
        symbol="BTCUSDT",
        initial_capital=1000.0,
        max_position=0.1  # 保守仓位
    )

    print("\n模拟交易流程:")
    print("-" * 60)

    np.random.seed(42)

    # 模拟100个tick
    for i in range(100):
        # 生成随机订单簿
        base_price = 50000.0
        spread = np.random.uniform(1, 8)  # 1-8 bps点差

        mid = base_price + np.random.randn() * 10
        half_spread = mid * spread / 10000 / 2

        bid_qty = np.random.uniform(0.5, 3.0)
        ask_qty = np.random.uniform(0.5, 3.0)

        # 偶尔制造毒流条件
        if i % 20 == 15:  # 每20个tick制造一次异常
            ask_qty = 0.1  # 卖盘稀少
            bid_qty = 10.0  # 买盘大单压盘

        orderbook = {
            'bids': [
                {'price': mid - half_spread, 'qty': bid_qty},
                {'price': mid - half_spread - 1, 'qty': 2.0},
            ],
            'asks': [
                {'price': mid + half_spread, 'qty': ask_qty},
                {'price': mid + half_spread + 1, 'qty': 2.0},
            ]
        }

        # 处理tick
        order = trader.process_tick(orderbook)

        if order:
            print(f"Tick {i+1}: Created {order['side']} order, "
                  f"spread={order['spread_bps']:.2f}bps, qty={order['qty']:.4f}")

            # 模拟50%成交率
            if np.random.random() < 0.5:
                fill_event = {
                    'order_id': order['id'],
                    'side': order['side'],
                    'qty': order['qty'],
                    'order_price': order['price'],
                    'fill_price': order['price'],
                    'bid_price': orderbook['bids'][0]['price'],
                    'ask_price': orderbook['asks'][0]['price'],
                    'fee': order['qty'] * order['price'] * 0.0002,
                    'market_price_after': mid + np.random.randn() * 5
                }
                trader.on_fill(fill_event)

            # 添加小延迟以通过频率限制检查 (60ms > 50ms min_rest_time)
            time.sleep(0.06)

    print("\n" + "=" * 60)
    print("Final Status")
    print("=" * 60)

    status = trader.get_status()

    print(f"\n交易状态:")
    print(f"  总盈亏: ${status['state']['total_pnl']:.4f}")
    print(f"  今日交易: {status['state']['trades_today']}")
    print(f"  当前持仓: {status['state']['current_position']:.4f}")
    print(f"  熔断状态: {status['state']['kill_switched']}")

    print(f"\n性能指标:")
    print(f"  平均延迟: {status['performance']['avg_latency_ms']:.3f}ms")
    print(f"  最大延迟: {status['performance']['max_latency_ms']:.3f}ms")

    print(f"\nPnL归因:")
    if 'components' in status['pnl_attribution']:
        for comp, data in status['pnl_attribution']['components'].items():
            print(f"  {comp}: ${data['value']:.4f}")

    print(f"\n毒流检测:")
    print(f"  告警次数: {status['toxic_detector']['alert_count']}")
    print(f"  阻止次数: {status['toxic_detector']['block_count']}")

    print(f"\n队列优化:")
    print(f"  持有率: {status['queue_optimizer'].get('hold_rate', 0):.1%}")
    print(f"  重排率: {status['queue_optimizer'].get('repost_rate', 0):.1%}")

    print(f"\n点差捕获:")
    print(f"  检查次数: {status['spread_capture']['checks']}")
    print(f"  机会率: {status['spread_capture'].get('opportunity_rate', 0):.1%}")

    print(f"\n约束状态:")
    print(f"  每日交易: {status['constraints']['daily_trades']}")
    print(f"  撤单率: {status['constraints']['cancel_ratio']:.1%}")

    print("\n健康检查:")
    is_healthy, reason = trader.get_health_check()
    print(f"  状态: {'[OK] 健康' if is_healthy else '[X] 异常'}")
    print(f"  详情: {reason}")

    print("\n" + "=" * 60)
    print("测试完成")

    trader.shutdown()
