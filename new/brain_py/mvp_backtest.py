"""
MVP HFT 回测引擎

专为MVP三模块设计的回测系统：
1. 队列位置优化器
2. 毒流检测器
3. 点差捕获器

特性：
- 基于真实历史数据tick级回测
- PnL归因分析
- 与完整系统对比
- 参数敏感性分析
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import time
import logging

from mvp import SimpleQueueOptimizer, ToxicFlowDetector, SpreadCapture
from mvp_trader import MVPTrader
from performance.pnl_attribution import PnLAttribution, Trade, TradeSide, OrderType


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('MVPBacktest')


@dataclass
class TickData:
    """Tick数据"""
    timestamp: float
    symbol: str
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float
    mid_price: float
    spread_bps: float
    volume_24h: float = 0.0


@dataclass
class BacktestConfig:
    """回测配置"""
    symbol: str = "BTCUSDT"
    initial_capital: float = 1000.0
    max_position: float = 0.1
    tick_size: float = 0.01

    # 手续费率
    maker_rebate: float = 0.0002  # 0.02%
    taker_fee: float = 0.0005     # 0.05%

    # 滑点模拟
    slippage_bps: float = 0.5     # 0.5 bps

    # 数据参数
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    # MVP参数调优范围
    queue_target_ratio: float = 0.3
    toxic_threshold: float = 0.3
    min_spread_ticks: int = 2


@dataclass
class MVPBacktestResult:
    """MVP回测结果"""
    config: BacktestConfig

    # 时间范围
    start_time: datetime
    end_time: datetime
    duration_hours: float

    # 盈亏指标
    initial_capital: float
    final_capital: float
    total_pnl: float
    total_pnl_pct: float

    # 交易统计
    total_orders: int
    total_fills: int
    fill_rate: float
    avg_order_size: float

    # 毒流检测统计
    toxic_alerts: int
    toxic_blocks: int
    toxic_alert_rate: float

    # 队列优化统计
    queue_hold_rate: float
    queue_repost_rate: float
    avg_queue_ratio: float

    # 点差捕获统计
    spread_opportunities: int
    spread_captures: int
    avg_spread_bps: float
    avg_capture_bps: float

    # 性能指标
    avg_latency_ms: float
    max_latency_ms: float

    # 风险指标
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    win_rate: float
    profit_factor: float

    # PnL归因（带默认值，放后面）
    pnl_components: Dict[str, float] = field(default_factory=dict)

    # 对比基准（如果有）
    baseline_pnl: Optional[float] = None
    alpha_vs_baseline: Optional[float] = None

    # 详细记录
    trades: List[Dict] = field(default_factory=list)
    equity_curve: List[Dict] = field(default_factory=list)
    daily_stats: List[Dict] = field(default_factory=list)


class HistoricalDataLoader:
    """历史数据加载器"""

    def __init__(self, data_path: Optional[str] = None):
        self.data_path = data_path

    def load_from_klines(self, df: pd.DataFrame) -> List[TickData]:
        """
        从K线数据生成模拟tick数据

        实际应用中应该从Level 2订单簿数据加载
        这里用K线数据模拟tick级订单簿
        """
        ticks = []

        for idx, row in df.iterrows():
            # 从K线生成模拟订单簿
            mid = (row['high'] + row['low']) / 2

            # 模拟点差 (1-10 bps)
            spread_pct = np.random.uniform(1, 10) / 10000
            half_spread = mid * spread_pct / 2

            tick = TickData(
                timestamp=idx if isinstance(idx, (int, float)) else time.mktime(idx.timetuple()),
                symbol="BTCUSDT",
                bid_price=mid - half_spread,
                bid_qty=np.random.uniform(0.5, 5.0),
                ask_price=mid + half_spread,
                ask_qty=np.random.uniform(0.5, 5.0),
                mid_price=mid,
                spread_bps=spread_pct * 10000,
                volume_24h=row.get('volume', 0)
            )
            ticks.append(tick)

        return ticks

    def load_from_orderbook(self, df: pd.DataFrame) -> List[TickData]:
        """
        从订单簿数据加载tick

        期望列：timestamp, bid_price, bid_qty, ask_price, ask_qty
        """
        ticks = []

        for idx, row in df.iterrows():
            bid = row.get('bid_price', row.get('bids_0_price', 0))
            ask = row.get('ask_price', row.get('asks_0_price', 0))
            mid = (bid + ask) / 2 if bid > 0 and ask > 0 else row.get('close', 0)
            spread_bps = ((ask - bid) / mid * 10000) if mid > 0 else 0

            tick = TickData(
                timestamp=row.get('timestamp', idx),
                symbol=row.get('symbol', 'BTCUSDT'),
                bid_price=bid,
                bid_qty=row.get('bid_qty', row.get('bids_0_qty', 1.0)),
                ask_price=ask,
                ask_qty=row.get('ask_qty', row.get('asks_0_qty', 1.0)),
                mid_price=mid,
                spread_bps=spread_bps,
                volume_24h=row.get('volume_24h', 0)
            )
            ticks.append(tick)

        return ticks

    def generate_synthetic_data(self,
                                 n_ticks: int = 1000,
                                 base_price: float = 50000.0,
                                 volatility: float = 0.001) -> List[TickData]:
        """生成合成数据用于测试"""
        ticks = []
        price = base_price

        for i in range(n_ticks):
            # 随机游走价格
            price *= (1 + np.random.randn() * volatility)

            # 模拟点差
            spread_bps = np.random.uniform(1, 8)
            half_spread = price * spread_bps / 10000 / 2

            # 偶尔制造毒流条件
            bid_qty = np.random.uniform(1.0, 5.0)
            ask_qty = np.random.uniform(1.0, 5.0)

            if i % 50 == 25:  # 每50个tick制造一次异常
                ask_qty = 0.2  # 卖盘稀少
                bid_qty = 8.0  # 买盘大单

            tick = TickData(
                timestamp=time.time() + i,
                symbol="BTCUSDT",
                bid_price=price - half_spread,
                bid_qty=bid_qty,
                ask_price=price + half_spread,
                ask_qty=ask_qty,
                mid_price=price,
                spread_bps=spread_bps
            )
            ticks.append(tick)

        return ticks


class MVPBacktestEngine:
    """
    MVP回测引擎

    模拟MVP交易系统在历史数据上的表现
    """

    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()

        # 初始化MVP Trader
        self.trader = MVPTrader(
            symbol=self.config.symbol,
            initial_capital=self.config.initial_capital,
            max_position=self.config.max_position,
            tick_size=self.config.tick_size
        )

        # 覆盖MVP参数
        self.trader.queue_optimizer.target_queue_ratio = self.config.queue_target_ratio
        self.trader.toxic_detector.threshold = self.config.toxic_threshold
        self.trader.spread_capture.min_spread_ticks = self.config.min_spread_ticks

        # 回测状态
        self.ticks: List[TickData] = []
        self.current_idx = 0
        self.pending_orders: Dict[str, Dict] = {}
        self.fills: List[Dict] = []

        # 记录
        self.equity_curve: List[Dict] = []
        self.daily_stats: List[Dict] = []
        self.trade_log: List[Dict] = []

        # 延迟模拟
        self.latency_model = self._default_latency_model

        logger.info(f"MVP Backtest Engine initialized: {self.config.symbol}")

    def _default_latency_model(self) -> float:
        """默认延迟模型 (ms)"""
        # 模拟网络延迟 20-50ms + 处理延迟 1-5ms
        return np.random.uniform(21, 55)

    def set_latency_model(self, model: Callable[[], float]):
        """设置自定义延迟模型"""
        self.latency_model = model

    def load_data(self, ticks: List[TickData]):
        """加载tick数据"""
        self.ticks = ticks
        logger.info(f"Loaded {len(ticks)} ticks")

    def _tick_to_orderbook(self, tick: TickData) -> Dict:
        """Tick转换为订单簿格式"""
        return {
            'bids': [
                {'price': tick.bid_price, 'qty': tick.bid_qty},
                {'price': tick.bid_price - self.config.tick_size, 'qty': 2.0}
            ],
            'asks': [
                {'price': tick.ask_price, 'qty': tick.ask_qty},
                {'price': tick.ask_price + self.config.tick_size, 'qty': 2.0}
            ],
            'timestamp': tick.timestamp,
            'mid_price': tick.mid_price
        }

    def _simulate_fill(self,
                       order: Dict,
                       tick: TickData,
                       next_tick: Optional[TickData]) -> Optional[Dict]:
        """
        模拟订单成交

        基于队列动力学模型模拟成交概率
        """
        # 计算Hazard Rate
        queue_ratio = 0.3  # MVP假设我们在队列前30%

        # 基础成交率
        base_rate = 2.0  # 每秒2次机会

        # 点差影响 (点差越小成交越快)
        spread_factor = max(0.5, 1.0 - tick.spread_bps / 20)

        # OFI影响
        ofi = (tick.bid_qty - tick.ask_qty) / (tick.bid_qty + tick.ask_qty + 0.001)
        ofi_factor = 1.0 + ofi * 0.5

        # 校准后的成交率
        calibration_factor = self.trader.calibrator.get_calibration_factor(self.config.symbol)
        hazard_rate = base_rate * np.exp(-2 * queue_ratio) * spread_factor * ofi_factor
        hazard_rate *= calibration_factor

        # 模拟时间间隔 (假设tick间隔100ms)
        dt = 0.1
        fill_prob = 1 - np.exp(-hazard_rate * dt)

        # 判断是否成交
        if np.random.random() < fill_prob:
            # 计算成交价格（带滑点）
            side = order['side']
            base_price = order['price']
            slippage = self.config.slippage_bps / 10000 * np.random.uniform(0.5, 1.5)

            if side == 'buy':
                fill_price = base_price * (1 + slippage)
            else:
                fill_price = base_price * (1 - slippage)

            return {
                'order_id': order['id'],
                'side': side,
                'qty': order['qty'],
                'order_price': order['price'],
                'fill_price': fill_price,
                'bid_price': tick.bid_price,
                'ask_price': tick.ask_price,
                'fee': order['qty'] * fill_price * self.config.maker_rebate,
                'market_price_after': next_tick.mid_price if next_tick else tick.mid_price,
                'timestamp': tick.timestamp
            }

        return None

    def run(self, progress_interval: int = 100) -> MVPBacktestResult:
        """
        运行回测

        Args:
            progress_interval: 进度报告间隔

        Returns:
            MVPBacktestResult
        """
        if not self.ticks:
            raise ValueError("No data loaded. Call load_data() first.")

        start_time = datetime.now()
        logger.info(f"Starting backtest with {len(self.ticks)} ticks")

        for i, tick in enumerate(self.ticks):
            self.current_idx = i

            # 转换订单簿
            orderbook = self._tick_to_orderbook(tick)

            # 处理pending订单的成交
            next_tick = self.ticks[i + 1] if i < len(self.ticks) - 1 else None
            filled_orders = []

            for order_id, order in list(self.pending_orders.items()):
                fill = self._simulate_fill(order, tick, next_tick)
                if fill:
                    self.trader.on_fill(fill)
                    self.fills.append(fill)
                    filled_orders.append(order_id)

                    self.trade_log.append({
                        'timestamp': tick.timestamp,
                        'side': fill['side'],
                        'qty': fill['qty'],
                        'price': fill['fill_price'],
                        'pnl': self.trader.state.total_pnl
                    })

            # 移除已成交订单
            for oid in filled_orders:
                self.pending_orders.pop(oid, None)

            # 运行MVP决策
            order = self.trader.process_tick(orderbook)

            if order:
                # 模拟延迟
                latency_ms = self.latency_model()
                time.sleep(latency_ms / 1000)  # 模拟延迟

                # 记录订单
                self.pending_orders[order['id']] = order

                # 模拟一定比例的立即成交（如果价格合适）
                if np.random.random() < 0.1:  # 10%立即成交
                    fill = self._simulate_fill(order, tick, next_tick)
                    if fill:
                        self.trader.on_fill(fill)
                        self.pending_orders.pop(order['id'], None)

            # 记录权益曲线
            status = self.trader.get_status()
            self.equity_curve.append({
                'timestamp': tick.timestamp,
                'equity': self.config.initial_capital + status['state']['total_pnl'],
                'pnl': status['state']['total_pnl'],
                'position': status['state']['current_position']
            })

            # 进度报告
            if (i + 1) % progress_interval == 0:
                progress = (i + 1) / len(self.ticks) * 100
                logger.info(f"Progress: {progress:.1f}% | PnL: ${status['state']['total_pnl']:.2f}")

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds() / 3600

        logger.info(f"Backtest completed in {duration:.2f} hours")

        return self._generate_result()

    def _generate_result(self) -> MVPBacktestResult:
        """生成回测结果"""
        status = self.trader.get_status()
        state = status['state']

        # 基础盈亏
        total_pnl = state['total_pnl']
        total_pnl_pct = total_pnl / self.config.initial_capital

        # 计算回撤
        equity_df = pd.DataFrame(self.equity_curve)
        if not equity_df.empty:
            equity_df['peak'] = equity_df['equity'].cummax()
            equity_df['drawdown'] = equity_df['equity'] - equity_df['peak']
            equity_df['drawdown_pct'] = equity_df['drawdown'] / equity_df['peak']

            max_drawdown = equity_df['drawdown'].min()
            max_drawdown_pct = equity_df['drawdown_pct'].min()

            # 夏普比率
            returns = equity_df['equity'].pct_change().dropna()
            if len(returns) > 1 and returns.std() > 0:
                sharpe = (returns.mean() / returns.std()) * np.sqrt(252 * 24 * 60)
            else:
                sharpe = 0
        else:
            max_drawdown = 0
            max_drawdown_pct = 0
            sharpe = 0

        # 胜率
        profits = [t['pnl'] for t in self.trade_log if t.get('pnl', 0) > 0]
        losses = [t['pnl'] for t in self.trade_log if t.get('pnl', 0) <= 0]
        win_rate = len(profits) / (len(profits) + len(losses)) if (profits or losses) else 0

        # 盈亏比
        total_profit = sum(profits) if profits else 0
        total_loss = abs(sum(losses)) if losses else 1
        profit_factor = total_profit / total_loss if total_loss > 0 else 0

        # PnL归因
        pnl_report = status.get('pnl_attribution', {})
        components = pnl_report.get('components', {})

        result = MVPBacktestResult(
            config=self.config,
            start_time=datetime.fromtimestamp(self.ticks[0].timestamp) if self.ticks else datetime.now(),
            end_time=datetime.fromtimestamp(self.ticks[-1].timestamp) if self.ticks else datetime.now(),
            duration_hours=len(self.ticks) * 0.1 / 3600,  # 假设tick间隔100ms
            initial_capital=self.config.initial_capital,
            final_capital=self.config.initial_capital + total_pnl,
            total_pnl=total_pnl,
            total_pnl_pct=total_pnl_pct,
            total_orders=status['state']['trades_today'],
            total_fills=len(self.fills),
            fill_rate=len(self.fills) / max(1, status['state']['trades_today']),
            avg_order_size=0.05,  # 简化
            pnl_components={k: v.get('value', 0) for k, v in components.items()},
            toxic_alerts=status['toxic_detector']['alert_count'],
            toxic_blocks=status['toxic_detector']['block_count'],
            toxic_alert_rate=status['toxic_detector']['alert_count'] / max(1, len(self.ticks)),
            queue_hold_rate=status['queue_optimizer'].get('hold_rate', 0),
            queue_repost_rate=status['queue_optimizer'].get('repost_rate', 0),
            avg_queue_ratio=0.3,  # MVP目标
            spread_opportunities=status['spread_capture']['checks'],
            spread_captures=status['spread_capture'].get('profitable_opportunities', 0),
            avg_spread_bps=status['spread_capture'].get('avg_spread_bps', 0),
            avg_capture_bps=0,  # 简化
            avg_latency_ms=status['performance']['avg_latency_ms'],
            max_latency_ms=status['performance']['max_latency_ms'],
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            sharpe_ratio=sharpe,
            win_rate=win_rate,
            profit_factor=profit_factor,
            trades=self.trade_log,
            equity_curve=self.equity_curve
        )

        return result


class MVPParameterOptimizer:
    """
    MVP参数优化器

    对关键参数进行网格搜索/随机搜索
    """

    def __init__(self, engine: MVPBacktestEngine):
        self.engine = engine
        self.results: List[Tuple[Dict, MVPBacktestResult]] = []

    def grid_search(self,
                    param_grid: Dict[str, List],
                    data: List[TickData]) -> Dict:
        """
        网格搜索最优参数

        Args:
            param_grid: 参数网格，如 {'queue_target_ratio': [0.2, 0.3, 0.4]}
            data: 回测数据

        Returns:
            最优参数组合
        """
        from itertools import product

        keys = list(param_grid.keys())
        values = list(param_grid.values())

        best_sharpe = -np.inf
        best_params = {}

        logger.info(f"Starting grid search: {len(list(product(*values)))} combinations")

        for combo in product(*values):
            params = dict(zip(keys, combo))

            # 更新配置
            config = BacktestConfig(**{**self.engine.config.__dict__, **params})
            test_engine = MVPBacktestEngine(config)
            test_engine.load_data(data)

            try:
                result = test_engine.run(progress_interval=10000)
                self.results.append((params, result))

                if result.sharpe_ratio > best_sharpe:
                    best_sharpe = result.sharpe_ratio
                    best_params = params
                    logger.info(f"New best Sharpe: {best_sharpe:.2f} with {params}")

            except Exception as e:
                logger.error(f"Error with params {params}: {e}")

        logger.info(f"Grid search complete. Best params: {best_params}, Sharpe: {best_sharpe:.2f}")
        return best_params

    def get_top_results(self, n: int = 5) -> List[Tuple[Dict, MVPBacktestResult]]:
        """获取前N个最佳结果"""
        sorted_results = sorted(self.results, key=lambda x: x[1].sharpe_ratio, reverse=True)
        return sorted_results[:n]


def print_backtest_report(result: MVPBacktestResult):
    """打印回测报告"""
    print("\n" + "=" * 70)
    print("MVP HFT 回测报告")
    print("=" * 70)

    print(f"\n回测配置:")
    print(f"  交易对: {result.config.symbol}")
    print(f"  初始资金: ${result.config.initial_capital:.2f}")
    print(f"  时间范围: {result.start_time} -> {result.end_time}")
    print(f"  持续时间: {result.duration_hours:.2f} 小时")

    print(f"\n盈亏表现:")
    print(f"  最终资金: ${result.final_capital:.2f}")
    print(f"  总盈亏: ${result.total_pnl:.4f} ({result.total_pnl_pct:.2%})")
    print(f"  最大回撤: ${result.max_drawdown:.2f} ({result.max_drawdown_pct:.2%})")
    print(f"  夏普比率: {result.sharpe_ratio:.2f}")
    print(f"  胜率: {result.win_rate:.1%}")
    print(f"  盈亏比: {result.profit_factor:.2f}")

    print(f"\n交易统计:")
    print(f"  总订单数: {result.total_orders}")
    print(f"  成交订单数: {result.total_fills}")
    print(f"  成交率: {result.fill_rate:.1%}")

    print(f"\nPnL归因:")
    for component, value in result.pnl_components.items():
        print(f"  {component}: ${value:.4f}")

    print(f"\n毒流检测:")
    print(f"  告警次数: {result.toxic_alerts}")
    print(f"  阻止次数: {result.toxic_blocks}")
    print(f"  告警率: {result.toxic_alert_rate:.2%}")

    print(f"\n队列优化:")
    print(f"  持有率: {result.queue_hold_rate:.1%}")
    print(f"  重排率: {result.queue_repost_rate:.1%}")

    print(f"\n点差捕获:")
    print(f"  检查次数: {result.spread_opportunities}")
    print(f"  捕获次数: {result.spread_captures}")
    print(f"  机会率: {result.spread_captures / max(1, result.spread_opportunities):.1%}")
    print(f"  平均点差: {result.avg_spread_bps:.2f} bps")

    print(f"\n性能指标:")
    print(f"  平均延迟: {result.avg_latency_ms:.3f} ms")
    print(f"  最大延迟: {result.max_latency_ms:.3f} ms")

    if result.baseline_pnl is not None:
        print(f"\n对比基准:")
        print(f"  基准盈亏: ${result.baseline_pnl:.4f}")
        print(f"  Alpha: ${result.alpha_vs_baseline:.4f}")

    print("\n" + "=" * 70)


# 测试代码
if __name__ == "__main__":
    print("=" * 70)
    print("MVP Backtest Engine Test")
    print("=" * 70)

    # 生成合成数据
    loader = HistoricalDataLoader()
    ticks = loader.generate_synthetic_data(n_ticks=5000, base_price=50000.0)

    print(f"\n生成合成数据: {len(ticks)} ticks")
    print(f"价格范围: ${ticks[0].mid_price:.2f} -> ${ticks[-1].mid_price:.2f}")

    # 创建回测引擎
    config = BacktestConfig(
        symbol="BTCUSDT",
        initial_capital=1000.0,
        max_position=0.1,
        queue_target_ratio=0.3,
        toxic_threshold=0.3,
        min_spread_ticks=2
    )

    engine = MVPBacktestEngine(config)
    engine.load_data(ticks)

    # 运行回测
    print("\n运行回测...")
    result = engine.run(progress_interval=500)

    # 打印报告
    print_backtest_report(result)

    # 参数优化示例（小规模）
    print("\n" + "-" * 70)
    print("参数优化示例 (小规模)")
    print("-" * 70)

    optimizer = MVPParameterOptimizer(engine)
    param_grid = {
        'queue_target_ratio': [0.2, 0.3],
        'toxic_threshold': [0.25, 0.3]
    }

    # 只用前1000个tick做快速优化示例
    best_params = optimizer.grid_search(param_grid, ticks[:1000])
    print(f"\n最优参数: {best_params}")

    print("\n" + "=" * 70)
    print("测试完成")
