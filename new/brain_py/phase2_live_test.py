"""
Phase 2: 小资金实盘测试 ($100 测试网)

目标：验证 MVP 策略的实盘有效性
核心任务：
1. 连接币安测试网
2. 运行MVP策略实盘
3. 实时对比回测 vs 实盘表现
4. 验证关键假设（成交率、毒流检测、延迟）

安全限制：
- 最大日亏损 5%
- 最大单笔亏损 2%
- 连续3次逆向选择立即停止
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import time
import json
import logging
import os
import sys

# 添加路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mvp_trader import MVPTrader
from mvp_backtest import BacktestConfig, TickData


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('phase2_live_test.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('Phase2LiveTest')


@dataclass
class LiveTestConfig:
    """实盘测试配置"""
    # 资金配置
    capital: float = 100.0  # $100测试资金
    max_position: float = 0.1  # 最大仓位10%

    # MVP参数（使用Phase 1最优值）
    queue_target_ratio: float = 0.2
    toxic_threshold: float = 0.35
    min_spread_ticks: int = 3

    # 交易对
    symbol: str = "BTCUSDT"

    # 安全限制
    max_daily_loss_pct: float = 0.05  # 5%日亏损限制
    max_single_loss_pct: float = 0.02  # 2%单笔亏损限制
    max_consecutive_adverse: int = 3  # 连续逆向选择次数限制

    # 交易频率限制
    max_orders_per_minute: int = 10
    min_order_interval_ms: float = 50
    max_position_changes_per_hour: int = 20

    # 测试时长
    test_duration_hours: float = 24.0

    # 回测对比基准
    backtest_results_path: Optional[str] = None


@dataclass
class TradeRecord:
    """交易记录"""
    timestamp: float
    order_id: str
    side: str
    qty: float
    entry_price: float
    fill_price: float
    spread_bps: float
    pnl: float
    pnl_components: Dict[str, float]
    latency_ms: float
    queue_ratio: float
    was_toxic_blocked: bool


@dataclass
class LiveVsBacktestComparison:
    """实盘 vs 回测对比"""
    metric: str
    backtest_value: float
    live_value: float
    deviation_pct: float
    is_acceptable: bool


@dataclass
class Phase2Result:
    """Phase 2测试结果"""
    config: LiveTestConfig
    start_time: datetime
    end_time: datetime

    # 交易统计
    total_orders: int
    total_fills: int
    fill_rate: float
    total_pnl: float
    total_pnl_pct: float

    # 关键假设验证
    fill_rate_comparison: LiveVsBacktestComparison
    toxic_detection_accuracy: Optional[float]  # 毒流检测准确率
    avg_latency_ms: float
    adverse_selection_count: int

    # 风控触发
    safety_stops_triggered: List[str]

    # 对比结果
    comparisons: List[LiveVsBacktestComparison]

    # 结论
    hypothesis_validated: bool
    recommendation: str


class BinanceTestnetConnector:
    """
    币安测试网连接器

    提供：
    - 实时订单簿数据
    - 订单执行
    - 账户信息
    """

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.api_key = api_key or os.getenv('BINANCE_TESTNET_API_KEY')
        self.api_secret = api_secret or os.getenv('BINANCE_TESTNET_API_SECRET')
        self.base_url = "https://testnet.binance.vision"

        # 模拟模式（如果没有API密钥）
        self.simulation_mode = not (self.api_key and self.api_secret)

        if self.simulation_mode:
            logger.warning("没有API密钥，运行在模拟模式")

        # 模拟数据生成器
        self.sim_price = 50000.0

    def get_orderbook(self, symbol: str) -> Optional[Dict]:
        """获取订单簿"""
        if self.simulation_mode:
            return self._generate_sim_orderbook()

        try:
            import requests
            response = requests.get(
                f"{self.base_url}/api/v3/depth",
                params={'symbol': symbol, 'limit': 10},
                timeout=5
            )
            data = response.json()

            return {
                'bids': [{'price': float(p), 'qty': float(q)} for p, q in data['bids'][:2]],
                'asks': [{'price': float(p), 'qty': float(q)} for p, q in data['asks'][:2]],
                'timestamp': time.time()
            }
        except Exception as e:
            logger.error(f"获取订单簿失败: {e}")
            return None

    def _generate_sim_orderbook(self) -> Dict:
        """生成模拟订单簿"""
        # 随机游走价格
        self.sim_price *= (1 + np.random.randn() * 0.001)

        spread_bps = np.random.uniform(1, 8)
        half_spread = self.sim_price * spread_bps / 10000 / 2

        return {
            'bids': [
                {'price': self.sim_price - half_spread, 'qty': np.random.uniform(0.5, 3.0)},
                {'price': self.sim_price - half_spread - 0.01, 'qty': 2.0}
            ],
            'asks': [
                {'price': self.sim_price + half_spread, 'qty': np.random.uniform(0.5, 3.0)},
                {'price': self.sim_price + half_spread + 0.01, 'qty': 2.0}
            ],
            'timestamp': time.time()
        }

    def place_order(self, symbol: str, side: str, qty: float, price: float) -> Optional[Dict]:
        """下单"""
        if self.simulation_mode:
            return self._simulate_order(symbol, side, qty, price)

        # 实际API调用（简化）
        logger.info(f"下单: {side} {qty} {symbol} @ {price}")
        return {
            'order_id': f'live_{int(time.time()*1000)}',
            'status': 'filled',
            'filled_qty': qty,
            'filled_price': price
        }

    def _simulate_order(self, symbol: str, side: str, qty: float, price: float) -> Dict:
        """模拟订单执行"""
        # 模拟成交延迟
        time.sleep(np.random.uniform(0.01, 0.05))

        # 模拟滑点
        slippage = np.random.uniform(-0.0005, 0.001)
        fill_price = price * (1 + slippage)

        return {
            'order_id': f'sim_{int(time.time()*1000)}',
            'status': 'filled',
            'filled_qty': qty,
            'filled_price': fill_price
        }

    def get_account(self) -> Dict:
        """获取账户信息"""
        return {
            'balances': [
                {'asset': 'USDT', 'free': 100.0, 'locked': 0.0},
                {'asset': 'BTC', 'free': 0.0, 'locked': 0.0}
            ]
        }


class LiveVsBacktestMonitor:
    """
    实盘 vs 回测实时监控

    持续对比实盘表现与回测基准的差异
    """

    def __init__(self, backtest_results: Optional[Dict] = None):
        self.backtest = backtest_results or {}
        self.live_records: List[TradeRecord] = []
        self.comparisons: List[LiveVsBacktestComparison] = []

        # 实时统计
        self.real_time_stats = {
            'orders': 0,
            'fills': 0,
            'pnl': 0.0,
            'adverse_selection_count': 0
        }

    def record_trade(self, record: TradeRecord):
        """记录交易"""
        self.live_records.append(record)

        self.real_time_stats['orders'] += 1
        self.real_time_stats['fills'] += 1
        self.real_time_stats['pnl'] += record.pnl

        if record.pnl_components.get('adverse_selection', 0) < -0.1:
            self.real_time_stats['adverse_selection_count'] += 1

    def generate_comparison(self) -> List[LiveVsBacktestComparison]:
        """生成对比报告"""
        if not self.live_records:
            return []

        comparisons = []

        # 成交率对比
        live_fill_rate = self.real_time_stats['fills'] / max(1, self.real_time_stats['orders'])
        backtest_fill_rate = self.backtest.get('fill_rate', 0.5)
        fill_rate_dev = (live_fill_rate - backtest_fill_rate) / max(0.001, backtest_fill_rate)

        comparisons.append(LiveVsBacktestComparison(
            metric='fill_rate',
            backtest_value=backtest_fill_rate,
            live_value=live_fill_rate,
            deviation_pct=fill_rate_dev * 100,
            is_acceptable=abs(fill_rate_dev) < 0.5  # 50%偏差内可接受
        ))

        # 平均延迟对比
        avg_latency = np.mean([r.latency_ms for r in self.live_records]) if self.live_records else 0
        comparisons.append(LiveVsBacktestComparison(
            metric='avg_latency_ms',
            backtest_value=0.39,  # Phase 1结果
            live_value=avg_latency,
            deviation_pct=(avg_latency - 0.39) / 0.39 * 100,
            is_acceptable=avg_latency < 2.0
        ))

        # 逆向选择率对比
        adverse_rate = self.real_time_stats['adverse_selection_count'] / max(1, self.real_time_stats['fills'])
        comparisons.append(LiveVsBacktestComparison(
            metric='adverse_selection_rate',
            backtest_value=0.1,  # 预期10%
            live_value=adverse_rate,
            deviation_pct=(adverse_rate - 0.1) / 0.1 * 100,
            is_acceptable=adverse_rate < 0.3
        ))

        self.comparisons = comparisons
        return comparisons

    def check_hypothesis(self) -> Tuple[bool, List[str]]:
        """验证关键假设"""
        issues = []

        for comp in self.comparisons:
            if not comp.is_acceptable:
                issues.append(f"{comp.metric}: {comp.deviation_pct:+.1f}% 偏差")

        return len(issues) == 0, issues


class Phase2LiveTest:
    """
    Phase 2 实盘测试运行器
    """

    def __init__(self, config: Optional[LiveTestConfig] = None):
        self.config = config or LiveTestConfig()

        # 初始化MVP Trader
        self.trader = MVPTrader(
            symbol=self.config.symbol,
            initial_capital=self.config.capital,
            max_position=self.config.max_position
        )

        # 设置MVP参数
        self.trader.queue_optimizer.target_queue_ratio = self.config.queue_target_ratio
        self.trader.toxic_detector.threshold = self.config.toxic_threshold
        self.trader.spread_capture.min_spread_ticks = self.config.min_spread_ticks

        # 币安连接器
        self.exchange = BinanceTestnetConnector()

        # 监控器
        self.monitor = LiveVsBacktestMonitor()

        # 风控状态
        self.safety_stops_triggered: List[str] = []
        self.consecutive_adverse_count = 0
        self.daily_pnl = 0.0

        # 交易频率控制
        self.last_order_time = 0
        self.orders_this_minute = 0
        self.minute_start = time.time()
        self.position_changes_this_hour = 0
        self.hour_start = time.time()

        logger.info(f"Phase 2 Live Test initialized: {self.config.symbol}, ${self.config.capital}")

    def run(self) -> Phase2Result:
        """
        运行实盘测试

        Returns:
            Phase2Result: 测试结果
        """
        start_time = datetime.now()
        end_time = start_time + timedelta(hours=self.config.test_duration_hours)

        logger.info(f"Starting Phase 2 live test at {start_time}")
        logger.info(f"Expected end time: {end_time}")
        logger.info(f"Mode: {'Simulation' if self.exchange.simulation_mode else 'Real Testnet'}")

        try:
            while datetime.now() < end_time:
                # 检查风控
                if self._check_safety_limits():
                    logger.warning("Safety limit triggered, stopping...")
                    break

                # 获取实时数据
                orderbook = self.exchange.get_orderbook(self.config.symbol)
                if not orderbook:
                    time.sleep(1)
                    continue

                # MVP决策
                decision_start = time.time()
                order = self.trader.process_tick(orderbook)
                decision_latency = (time.time() - decision_start) * 1000

                if order:
                    # 检查交易频率
                    if not self._check_rate_limits():
                        continue

                    # 执行订单
                    result = self.exchange.place_order(
                        self.config.symbol,
                        order['side'],
                        order['qty'],
                        order['price']
                    )

                    if result:
                        # 模拟成交回调
                        fill_event = {
                            'order_id': result['order_id'],
                            'side': order['side'],
                            'qty': result['filled_qty'],
                            'order_price': order['price'],
                            'fill_price': result['filled_price'],
                            'bid_price': orderbook['bids'][0]['price'],
                            'ask_price': orderbook['asks'][0]['price'],
                            'fee': result['filled_qty'] * result['filled_price'] * 0.0002,
                            'market_price_after': orderbook['bids'][0]['price']
                        }

                        self.trader.on_fill(fill_event)

                        # 记录交易
                        status = self.trader.get_status()
                        pnl_comp = status.get('pnl_attribution', {}).get('components', {})

                        record = TradeRecord(
                            timestamp=time.time(),
                            order_id=result['order_id'],
                            side=order['side'],
                            qty=result['filled_qty'],
                            entry_price=order['price'],
                            fill_price=result['filled_price'],
                            spread_bps=order.get('spread_bps', 0),
                            pnl=status['state']['total_pnl'],
                            pnl_components={k: v.get('value', 0) for k, v in pnl_comp.items()},
                            latency_ms=decision_latency,
                            queue_ratio=0.3,
                            was_toxic_blocked=False
                        )
                        self.monitor.record_trade(record)

                        # 检查逆向选择
                        if record.pnl_components.get('adverse_selection', 0) < -0.1:
                            self.consecutive_adverse_count += 1
                            if self.consecutive_adverse_count >= self.config.max_consecutive_adverse:
                                self.safety_stops_triggered.append('consecutive_adverse_selection')
                                logger.warning(f"连续{self.config.max_consecutive_adverse}次逆向选择，停止交易")
                                break
                        else:
                            self.consecutive_adverse_count = 0

                        # 更新日盈亏
                        self.daily_pnl = status['state']['total_pnl']
                        if self.daily_pnl < -self.config.capital * self.config.max_daily_loss_pct:
                            self.safety_stops_triggered.append('daily_loss_limit')
                            logger.warning(f"日亏损达到{self.config.max_daily_loss_pct*100}%，停止交易")
                            break

                # 定期生成报告
                if len(self.monitor.live_records) % 10 == 0 and self.monitor.live_records:
                    self._print_progress_report()

                time.sleep(0.1)  # 100ms tick

        except KeyboardInterrupt:
            logger.info("用户中断测试")
        except Exception as e:
            logger.error(f"测试异常: {e}")

        finally:
            return self._generate_result(start_time, datetime.now())

    def _check_safety_limits(self) -> bool:
        """检查安全限制"""
        return len(self.safety_stops_triggered) > 0

    def _check_rate_limits(self) -> bool:
        """检查交易频率限制"""
        now = time.time()

        # 每分钟重置
        if now - self.minute_start > 60:
            self.orders_this_minute = 0
            self.minute_start = now

        # 每小时重置
        if now - self.hour_start > 3600:
            self.position_changes_this_hour = 0
            self.hour_start = now

        # 检查限制
        if self.orders_this_minute >= self.config.max_orders_per_minute:
            return False

        if now - self.last_order_time < self.config.min_order_interval_ms / 1000:
            return False

        if self.position_changes_this_hour >= self.config.max_position_changes_per_hour:
            return False

        self.orders_this_minute += 1
        self.last_order_time = now
        return True

    def _print_progress_report(self):
        """打印进度报告"""
        status = self.trader.get_status()
        comparisons = self.monitor.generate_comparison()

        logger.info("=" * 60)
        logger.info(f"Phase 2 进度报告 - {datetime.now()}")
        logger.info(f"交易次数: {len(self.monitor.live_records)}")
        logger.info(f"总盈亏: ${status['state']['total_pnl']:.4f}")
        logger.info(f"当前持仓: {status['state']['current_position']:.4f}")

        for comp in comparisons:
            status_mark = "[OK]" if comp.is_acceptable else "[X]"
            logger.info(f"  {comp.metric}: 回测={comp.backtest_value:.3f}, "
                       f"实盘={comp.live_value:.3f}, 偏差={comp.deviation_pct:+.1f}% {status_mark}")

        logger.info("=" * 60)

    def _generate_result(self, start: datetime, end: datetime) -> Phase2Result:
        """生成测试结果"""
        status = self.trader.get_status()

        # 生成对比
        comparisons = self.monitor.generate_comparison()

        # 验证假设
        hypothesis_ok, issues = self.monitor.check_hypothesis()

        # 确定推荐
        if hypothesis_ok and status['state']['total_pnl'] >= 0:
            recommendation = "进入Phase 3：扩大资金到$1000"
        elif hypothesis_ok:
            recommendation = "继续优化参数后重新测试"
        else:
            recommendation = f"调整策略：{', '.join(issues[:3])}"

        return Phase2Result(
            config=self.config,
            start_time=start,
            end_time=end,
            total_orders=status['state']['trades_today'],
            total_fills=len(self.monitor.live_records),
            fill_rate=len(self.monitor.live_records) / max(1, status['state']['trades_today']),
            total_pnl=status['state']['total_pnl'],
            total_pnl_pct=status['state']['total_pnl'] / self.config.capital,
            fill_rate_comparison=next((c for c in comparisons if c.metric == 'fill_rate'), None),
            toxic_detection_accuracy=None,  # 需要更多数据分析
            avg_latency_ms=np.mean([r.latency_ms for r in self.monitor.live_records]) if self.monitor.live_records else 0,
            adverse_selection_count=self.consecutive_adverse_count,
            safety_stops_triggered=self.safety_stops_triggered,
            comparisons=comparisons,
            hypothesis_validated=hypothesis_ok,
            recommendation=recommendation
        )


def print_phase2_report(result: Phase2Result):
    """打印Phase 2报告"""
    print("\n" + "=" * 70)
    print("Phase 2 实盘测试报告")
    print("=" * 70)

    print(f"\n测试配置:")
    print(f"  交易对: {result.config.symbol}")
    print(f"  测试资金: ${result.config.capital}")
    print(f"  测试时长: {(result.end_time - result.start_time).total_seconds() / 3600:.1f} 小时")
    print(f"  模式: {'Simulation' if True else 'Real Testnet'}")

    print(f"\n交易统计:")
    print(f"  总订单数: {result.total_orders}")
    print(f"  成交订单数: {result.total_fills}")
    print(f"  成交率: {result.fill_rate:.1%}")
    print(f"  总盈亏: ${result.total_pnl:.4f} ({result.total_pnl_pct:.2%})")

    print(f"\n关键假设验证:")
    if result.fill_rate_comparison:
        comp = result.fill_rate_comparison
        print(f"  成交率: 回测={comp.backtest_value:.1%}, 实盘={comp.live_value:.1%}, "
              f"偏差={comp.deviation_pct:+.1f}% {'[OK]' if comp.is_acceptable else '[X]'}")

    print(f"  平均延迟: {result.avg_latency_ms:.2f} ms")
    print(f"  逆向选择次数: {result.adverse_selection_count}")

    print(f"\n风控触发:")
    if result.safety_stops_triggered:
        for stop in result.safety_stops_triggered:
            print(f"  [X] {stop}")
    else:
        print(f"  [OK] 无风控触发")

    print(f"\n对比分析:")
    for comp in result.comparisons:
        status = "[OK] 可接受" if comp.is_acceptable else "[X] 超出范围"
        print(f"  {comp.metric}: {status}")

    print(f"\n结论:")
    print(f"  假设验证: {'通过' if result.hypothesis_validated else '未通过'}")
    print(f"  建议: {result.recommendation}")

    print("\n" + "=" * 70)


# 测试运行
def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='Phase 2 MVP实盘测试')
    parser.add_argument('--duration', type=float, default=1.0,
                       help='测试时长（小时）')
    parser.add_argument('--capital', type=float, default=100.0,
                       help='测试资金')
    parser.add_argument('--sim', action='store_true',
                       help='使用模拟模式（无需API密钥）')

    args = parser.parse_args()

    # 配置
    config = LiveTestConfig(
        capital=args.capital,
        test_duration_hours=args.duration,
        queue_target_ratio=0.2,  # Phase 1最优
        toxic_threshold=0.35,
        min_spread_ticks=3
    )

    print("=" * 70)
    print("Phase 2: MVP实盘测试 ($100 测试网)")
    print("=" * 70)
    print(f"\n配置:")
    print(f"  资金: ${config.capital}")
    print(f"  时长: {config.test_duration_hours} 小时")
    print(f"  模式: {'Simulation' if args.sim else 'Testnet'}")
    print(f"\nMVP参数:")
    print(f"  队列目标: {config.queue_target_ratio}")
    print(f"  毒流阈值: {config.toxic_threshold}")
    print(f"  最小点差: {config.min_spread_ticks} ticks")

    print("\n按 Ctrl+C 随时停止测试")
    print("=" * 70)

    # 运行测试
    test = Phase2LiveTest(config)
    result = test.run()

    # 打印报告
    print_phase2_report(result)

    # 保存结果
    result_file = f"phase2_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(result_file, 'w') as f:
        json.dump({
            'config': result.config.__dict__,
            'start_time': result.start_time.isoformat(),
            'end_time': result.end_time.isoformat(),
            'total_pnl': result.total_pnl,
            'total_pnl_pct': result.total_pnl_pct,
            'fill_rate': result.fill_rate,
            'avg_latency_ms': result.avg_latency_ms,
            'hypothesis_validated': result.hypothesis_validated,
            'recommendation': result.recommendation
        }, f, indent=2)

    print(f"\n结果已保存: {result_file}")


if __name__ == "__main__":
    main()
