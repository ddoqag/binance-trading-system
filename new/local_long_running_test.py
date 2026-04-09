"""
本地长时间实盘测试脚本 - 无需API密钥

监控指标:
1. 交易稳定性 - 交易周期执行情况
2. 收益曲线 - PnL变化
3. 风控触发情况 - 熔断器、止损等
4. 系统性能 - 内存、CPU使用

使用合成数据模拟真实市场环境
"""

import asyncio
import json
import time
import logging
import os
import sys
import psutil
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict
from collections import deque
import numpy as np

# 配置日志
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/local_long_running_test.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

sys.path.insert(0, 'D:/binance/new')
sys.path.insert(0, 'D:/binance/new/brain_py')

from local_trading import LocalTrader, LocalTradingConfig
from local_trading.data_source import SyntheticDataSource


@dataclass
class SystemMetrics:
    """系统性能指标"""
    timestamp: float = field(default_factory=time.time)
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_mb: float = 0.0


@dataclass
class TestMetrics:
    """测试指标"""
    start_time: float = field(default_factory=time.time)
    test_duration_hours: float = 1.0

    # 交易统计
    total_cycles: int = 0
    total_trades: int = 0
    total_pnl: float = 0.0
    win_count: int = 0
    loss_count: int = 0

    # 稳定性指标
    cycle_times: deque = field(default_factory=lambda: deque(maxlen=1000))
    errors: List[Dict] = field(default_factory=list)

    # 风控触发
    circuit_breaker_triggers: int = 0
    risk_limits_hit: int = 0
    max_drawdown_hit: int = 0

    # 收益曲线
    pnl_history: deque = field(default_factory=lambda: deque(maxlen=5000))
    equity_curve: deque = field(default_factory=lambda: deque(maxlen=5000))

    # 系统性能
    system_metrics: deque = field(default_factory=lambda: deque(maxlen=500))

    def record_cycle(self, cycle_time: float, pnl: float, equity: float):
        """记录一个交易周期"""
        self.total_cycles += 1
        self.cycle_times.append(cycle_time)
        self.pnl_history.append({
            'timestamp': time.time(),
            'pnl': pnl
        })
        self.equity_curve.append({
            'timestamp': time.time(),
            'equity': equity
        })

    def record_trade(self, pnl: float):
        """记录一笔交易"""
        self.total_trades += 1
        self.total_pnl += pnl
        if pnl > 0:
            self.win_count += 1
        else:
            self.loss_count += 1

    def record_error(self, error_type: str, message: str):
        """记录错误"""
        self.errors.append({
            'timestamp': time.time(),
            'type': error_type,
            'message': message
        })

    def record_system_metrics(self):
        """记录系统指标"""
        try:
            process = psutil.Process()
            metrics = SystemMetrics(
                cpu_percent=process.cpu_percent(),
                memory_percent=process.memory_percent(),
                memory_mb=process.memory_info().rss / 1024 / 1024
            )
            self.system_metrics.append(asdict(metrics))
        except Exception as e:
            logger.warning(f"[SystemMetrics] Failed to record: {e}")

    def get_summary(self) -> Dict:
        """获取测试摘要"""
        runtime = time.time() - self.start_time
        avg_cycle_time = sum(self.cycle_times) / len(self.cycle_times) if self.cycle_times else 0
        max_cycle_time = max(self.cycle_times) if self.cycle_times else 0

        # 计算收益曲线统计
        equity_values = [e['equity'] for e in self.equity_curve] if self.equity_curve else [10000]
        max_equity = max(equity_values) if equity_values else 10000
        min_equity = min(equity_values) if equity_values else 10000
        current_equity = equity_values[-1] if equity_values else 10000

        # 计算最大回撤
        max_drawdown = 0
        peak = equity_values[0] if equity_values else 10000
        for equity in equity_values:
            if equity > peak:
                peak = equity
            drawdown = (peak - equity) / peak
            max_drawdown = max(max_drawdown, drawdown)

        return {
            'runtime_hours': runtime / 3600,
            'target_hours': self.test_duration_hours,
            'total_cycles': self.total_cycles,
            'total_trades': self.total_trades,
            'total_pnl': self.total_pnl,
            'win_rate': self.win_count / max(1, self.total_trades),
            'avg_cycle_time': avg_cycle_time,
            'max_cycle_time': max_cycle_time,
            'error_count': len(self.errors),
            'circuit_breaker_triggers': self.circuit_breaker_triggers,
            'max_drawdown_pct': max_drawdown * 100,
            'current_equity': current_equity,
            'peak_equity': max_equity,
            'trough_equity': min_equity
        }


class LocalLongRunningTest:
    """本地长时间运行测试"""

    def __init__(self, duration_hours: float = 1.0):
        self.duration_hours = duration_hours
        self.metrics = TestMetrics(test_duration_hours=duration_hours)
        self.trader = None
        self.data_source = None
        self._running = False
        self._shutdown_event = asyncio.Event()

    async def initialize(self):
        """初始化交易系统"""
        logger.info("[LocalLongRunningTest] 初始化本地交易系统...")

        # 创建配置
        config = LocalTradingConfig(
            symbol='BTCUSDT',
            initial_capital=10000.0,
            max_position=0.1,
            queue_target_ratio=0.2,
            toxic_threshold=0.35,
            min_spread_ticks=3,
            maker_fee=0.0002,
            taker_fee=0.0005
        )

        # 创建交易者
        self.trader = LocalTrader(config)

        # 创建合成数据源 - 模拟真实市场波动
        self.data_source = SyntheticDataSource(
            symbol='BTCUSDT',
            n_ticks=100000,  # 大量数据支持长时间运行
            base_price=50000.0,
            volatility=0.001
        )

        self.trader.set_data_source(self.data_source)
        self.trader.load_data()

        logger.info("[LocalLongRunningTest] 本地交易系统初始化完成")
        logger.info(f"  - 初始资金: {config.initial_capital} USDT")
        logger.info(f"  - 最大仓位: {config.max_position * 100}%")
        logger.info(f"  - 数据点: 100000 ticks")

    async def run(self):
        """运行长时间测试"""
        if not self.trader:
            raise RuntimeError("Trader not initialized")

        self._running = True
        logger.info(f"[LocalLongRunningTest] 开始 {self.duration_hours} 小时长时间测试...")

        # 启动监控任务
        monitor_task = asyncio.create_task(self._monitor_loop())
        stats_task = asyncio.create_task(self._stats_reporter())
        system_task = asyncio.create_task(self._system_metrics_loop())

        # 运行回测（模拟实时交易）
        backtest_task = asyncio.create_task(self._run_backtest())

        # 等待指定时长或任务完成
        try:
            await asyncio.wait_for(
                self._shutdown_event.wait(),
                timeout=self.duration_hours * 3600
            )
        except asyncio.TimeoutError:
            logger.info("[LocalLongRunningTest] 测试时长到达，正在停止...")
        except KeyboardInterrupt:
            logger.info("[LocalLongRunningTest] 收到中断信号，正在停止...")

        # 停止
        self._running = False
        monitor_task.cancel()
        stats_task.cancel()
        system_task.cancel()
        backtest_task.cancel()

        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        try:
            await stats_task
        except asyncio.CancelledError:
            pass
        try:
            await system_task
        except asyncio.CancelledError:
            pass
        try:
            await backtest_task
        except asyncio.CancelledError:
            pass

        # 生成报告
        self._generate_report()

    async def _run_backtest(self):
        """运行回测模拟实时交易"""
        try:
            result = self.trader.run_backtest(progress_interval=500)

            # 更新最终统计
            self.metrics.total_trades = result.total_trades
            self.metrics.total_pnl = result.total_return_pct * 10000  # 简化计算

            logger.info(f"[LocalLongRunningTest] 回测完成:")
            logger.info(f"  总交易: {result.total_trades}")
            logger.info(f"  收益率: {result.total_return_pct:.2%}")
            logger.info(f"  夏普比率: {result.sharpe_ratio:.2f}")

        except Exception as e:
            logger.error(f"[LocalLongRunningTest] 回测错误: {e}")
            self.metrics.record_error('backtest', str(e))

    async def _monitor_loop(self):
        """监控循环"""
        last_check = time.time()

        while self._running:
            try:
                await asyncio.sleep(5)  # 每5秒检查一次

                current_time = time.time()
                cycle_time = current_time - last_check

                # 获取当前权益
                equity = 10000.0
                if hasattr(self.trader, 'portfolio') and self.trader.portfolio:
                    equity = self.trader.portfolio.total_equity

                # 记录周期
                self.metrics.record_cycle(cycle_time, self.metrics.total_pnl, equity)

                last_check = current_time

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[LocalLongRunningTest] 监控循环错误: {e}")
                self.metrics.record_error('monitor_loop', str(e))

    async def _system_metrics_loop(self):
        """系统性能监控循环"""
        while self._running:
            try:
                await asyncio.sleep(30)  # 每30秒记录一次
                self.metrics.record_system_metrics()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[LocalLongRunningTest] 系统指标记录错误: {e}")

    async def _stats_reporter(self):
        """定期报告统计信息 (每5分钟)"""
        while self._running:
            try:
                await asyncio.sleep(300)  # 5分钟

                summary = self.metrics.get_summary()

                logger.info("=" * 70)
                logger.info("[LocalLongRunningTest] 5分钟统计报告")
                logger.info(f"  运行时间: {summary['runtime_hours']:.2f} / {self.duration_hours} 小时")
                logger.info(f"  总周期数: {summary['total_cycles']}")
                logger.info(f"  总交易数: {summary['total_trades']}")
                logger.info(f"  总盈亏: {summary['total_pnl']:.4f} USDT")
                logger.info(f"  当前权益: {summary['current_equity']:.2f} USDT")
                logger.info(f"  最大回撤: {summary['max_drawdown_pct']:.2f}%")
                logger.info(f"  胜率: {summary['win_rate']:.2%}")
                logger.info(f"  平均周期时间: {summary['avg_cycle_time']:.3f}s")
                logger.info(f"  最大周期时间: {summary['max_cycle_time']:.3f}s")
                logger.info(f"  错误数: {summary['error_count']}")
                logger.info(f"  熔断器触发: {summary['circuit_breaker_triggers']}")

                # 系统性能
                if self.metrics.system_metrics:
                    latest = self.metrics.system_metrics[-1]
                    logger.info(f"  CPU使用率: {latest['cpu_percent']:.1f}%")
                    logger.info(f"  内存使用: {latest['memory_mb']:.1f} MB")

                logger.info("=" * 70)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[LocalLongRunningTest] 统计报告错误: {e}")

    def _generate_report(self):
        """生成最终测试报告"""
        summary = self.metrics.get_summary()

        # 计算收益曲线数据
        equity_data = list(self.metrics.equity_curve)

        report = {
            'test_name': '本地长时间实盘测试',
            'duration_hours': self.duration_hours,
            'actual_runtime_hours': summary['runtime_hours'],
            'start_time': datetime.fromtimestamp(self.metrics.start_time).isoformat(),
            'end_time': datetime.now().isoformat(),
            'trading_mode': 'LOCAL_PAPER',
            'results': {
                'total_cycles': summary['total_cycles'],
                'total_trades': summary['total_trades'],
                'total_pnl': summary['total_pnl'],
                'win_rate': summary['win_rate'],
                'avg_cycle_time_seconds': summary['avg_cycle_time'],
                'max_cycle_time_seconds': summary['max_cycle_time'],
                'current_equity': summary['current_equity'],
                'peak_equity': summary['peak_equity'],
                'trough_equity': summary['trough_equity']
            },
            'risk_metrics': {
                'max_drawdown_pct': summary['max_drawdown_pct'],
                'circuit_breaker_triggers': summary['circuit_breaker_triggers'],
                'risk_limits_hit': self.metrics.risk_limits_hit,
                'error_count': summary['error_count']
            },
            'system_metrics': {
                'avg_cpu_percent': np.mean([m['cpu_percent'] for m in self.metrics.system_metrics]) if self.metrics.system_metrics else 0,
                'avg_memory_mb': np.mean([m['memory_mb'] for m in self.metrics.system_metrics]) if self.metrics.system_metrics else 0,
                'max_memory_mb': max([m['memory_mb'] for m in self.metrics.system_metrics]) if self.metrics.system_metrics else 0
            },
            'errors': list(self.metrics.errors)[-50:]  # 最近50个错误
        }

        # 保存报告
        report_file = f"logs/local_long_running_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        # 保存收益曲线
        if equity_data:
            equity_file = f"logs/local_long_running_equity_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(equity_file, 'w', encoding='utf-8') as f:
                json.dump(equity_data, f, indent=2)

        # 打印摘要
        logger.info("\n" + "=" * 70)
        logger.info("本地长时间实盘测试 - 最终报告")
        logger.info("=" * 70)
        logger.info(f"测试时长: {summary['runtime_hours']:.2f} / {self.duration_hours} 小时")
        logger.info(f"交易周期: {summary['total_cycles']}")
        logger.info(f"成交笔数: {summary['total_trades']}")
        logger.info(f"总盈亏: {summary['total_pnl']:.4f} USDT")
        logger.info(f"当前权益: {summary['current_equity']:.2f} USDT")
        logger.info(f"最大回撤: {summary['max_drawdown_pct']:.2f}%")
        logger.info(f"胜率: {summary['win_rate']:.2%}")
        logger.info(f"平均周期: {summary['avg_cycle_time']:.3f}s")
        logger.info(f"最大周期: {summary['max_cycle_time']:.3f}s")
        logger.info(f"错误次数: {summary['error_count']}")
        logger.info(f"熔断器触发: {summary['circuit_breaker_triggers']}")
        logger.info(f"报告保存: {report_file}")
        if equity_data:
            logger.info(f"权益曲线: {equity_file}")
        logger.info("=" * 70)

        # 评估结果
        self._evaluate_results(report)

    def _evaluate_results(self, report: Dict):
        """评估测试结果"""
        logger.info("\n测试结果评估:")

        # 稳定性评分
        stability_score = 100
        if report['risk_metrics']['error_count'] > 10:
            stability_score -= 20
        if report['results']['max_cycle_time_seconds'] > 10:
            stability_score -= 15

        logger.info(f"  稳定性评分: {stability_score}/100")

        # 收益评分
        pnl_score = min(100, max(0, 50 + report['results']['total_pnl'] / 100))
        logger.info(f"  收益评分: {pnl_score:.0f}/100")

        # 风控评分
        risk_score = 100
        if report['risk_metrics']['max_drawdown_pct'] > 10:
            risk_score -= 20
        if report['risk_metrics']['circuit_breaker_triggers'] > 0:
            risk_score -= 10
        logger.info(f"  风控评分: {risk_score}/100")

        # 综合评分
        overall = (stability_score + pnl_score + risk_score) / 3
        logger.info(f"  综合评分: {overall:.0f}/100")

        if overall >= 80:
            logger.info("  ✅ 系统表现优秀")
        elif overall >= 60:
            logger.info("  ⚠️ 系统表现良好，有改进空间")
        else:
            logger.info("  ❌ 系统需要优化")

        if report['results']['total_trades'] > 0:
            logger.info(f"  ✅ 交易系统正常运行，共执行 {report['results']['total_trades']} 笔交易")
        else:
            logger.info("  ⚠️ 测试期间未产生交易")


async def main():
    """主函数"""
    logger.info("[Main] 启动本地长时间实盘测试")

    # 创建测试实例 (1小时测试)
    test = LocalLongRunningTest(duration_hours=1.0)

    try:
        # 初始化
        await test.initialize()

        # 运行测试
        await test.run()

    except Exception as e:
        logger.error(f"[Main] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("[Main] 用户中断测试")
    except Exception as e:
        logger.error(f"[Main] 异常: {e}")
        sys.exit(1)
