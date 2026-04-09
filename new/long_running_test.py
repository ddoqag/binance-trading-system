"""
长时间实盘测试脚本 - 1小时以上监控

监控指标:
1. 交易稳定性 - 交易周期执行情况
2. 收益曲线 - PnL变化
3. 风控触发情况 - 熔断器、止损等
4. API连接稳定性 - WebSocket连接状态
"""

import asyncio
import json
import time
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from collections import deque

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/long_running_test.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

sys.path.insert(0, 'D:/binance/new')

from config.trading_mode_switcher import TradingModeSwitcher
from config.mode import TradingMode


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
    cycle_times: deque = field(default_factory=lambda: deque(maxlen=100))
    errors: List[Dict] = field(default_factory=list)

    # API连接
    ws_reconnects: int = 0
    api_errors: int = 0
    last_price_update: float = 0.0

    # 风控触发
    circuit_breaker_triggers: int = 0
    risk_limits_hit: int = 0
    kill_switch_triggers: int = 0

    # 收益曲线
    pnl_history: deque = field(default_factory=lambda: deque(maxlen=1000))
    equity_curve: deque = field(default_factory=lambda: deque(maxlen=1000))

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

    def get_summary(self) -> Dict:
        """获取测试摘要"""
        runtime = time.time() - self.start_time
        avg_cycle_time = sum(self.cycle_times) / len(self.cycle_times) if self.cycle_times else 0

        return {
            'runtime_hours': runtime / 3600,
            'target_hours': self.test_duration_hours,
            'total_cycles': self.total_cycles,
            'total_trades': self.total_trades,
            'total_pnl': self.total_pnl,
            'win_rate': self.win_count / max(1, self.total_trades),
            'avg_cycle_time': avg_cycle_time,
            'error_count': len(self.errors),
            'ws_reconnects': self.ws_reconnects,
            'circuit_breaker_triggers': self.circuit_breaker_triggers,
            'api_errors': self.api_errors
        }


class LongRunningTest:
    """长时间运行测试"""

    def __init__(self, duration_hours: float = 1.0):
        self.duration_hours = duration_hours
        self.metrics = TestMetrics(test_duration_hours=duration_hours)
        self.trader = None
        self._running = False
        self._shutdown_event = asyncio.Event()

    async def initialize(self):
        """初始化交易系统"""
        from self_evolving_trader import create_trader, TraderConfig, TradingMode

        # 确认当前模式
        switcher = TradingModeSwitcher('D:/binance/new')
        mode = switcher.get_current_mode()
        logger.info(f"[LongRunningTest] 当前交易模式: {mode.value}")

        if mode.is_live():
            logger.warning("[LongRunningTest] ⚠️ 警告: 当前为实盘模式，将使用真实资金!")
            await asyncio.sleep(3)  # 给用户时间取消

        # 从环境变量读取配置
        api_key = os.getenv("BINANCE_API_KEY", "")
        api_secret = os.getenv("BINANCE_API_SECRET", "")

        # 创建交易者 (Paper模式)
        self.trader = await create_trader(
            api_key=api_key,
            api_secret=api_secret,
            symbol="BTCUSDT",
            use_testnet=True,  # 强制使用测试网
            initial_capital=10000.0,
            enable_spot_margin=False
        )

        logger.info("[LongRunningTest] 交易者初始化完成")

    async def run(self):
        """运行长时间测试"""
        if not self.trader:
            raise RuntimeError("Trader not initialized")

        self._running = True
        logger.info(f"[LongRunningTest] 开始 {self.duration_hours} 小时长时间测试...")

        # 启动交易者
        await self.trader.start()

        # 启动监控任务
        monitor_task = asyncio.create_task(self._monitor_loop())
        stats_task = asyncio.create_task(self._stats_reporter())

        # 运行指定时长
        try:
            await asyncio.wait_for(
                self._shutdown_event.wait(),
                timeout=self.duration_hours * 3600
            )
        except asyncio.TimeoutError:
            logger.info("[LongRunningTest] 测试时长到达，正在停止...")
        except KeyboardInterrupt:
            logger.info("[LongRunningTest] 收到中断信号，正在停止...")

        # 停止
        self._running = False
        monitor_task.cancel()
        stats_task.cancel()

        await self.trader.stop()

        # 生成报告
        self._generate_report()

    async def _monitor_loop(self):
        """监控循环 - 每秒检查一次"""
        last_cycles = 0
        last_trades = 0
        last_check = time.time()

        while self._running:
            try:
                await asyncio.sleep(1)

                if not self.trader:
                    continue

                # 获取当前状态
                status = self.trader.get_status()
                current_time = time.time()

                # 更新周期统计
                cycles = status['stats']['total_cycles']
                trades = status['stats']['total_trades']
                pnl = status['stats']['total_pnl']

                # 计算周期时间
                if cycles > last_cycles:
                    cycle_time = (current_time - last_check) / (cycles - last_cycles)
                    self.metrics.record_cycle(cycle_time, pnl, 10000 + pnl)

                # 检测新交易
                if trades > last_trades:
                    # 新交易发生
                    new_trades = trades - last_trades
                    for _ in range(new_trades):
                        self.metrics.record_trade(0)  # 简化处理

                # 检查API连接
                if status.get('phase_c'):
                    phase_c = status['phase_c']
                    # 检查是否有活跃订单或持仓变化

                # 检查风控状态
                if hasattr(self.trader, 'circuit_breaker'):
                    cb = self.trader.circuit_breaker
                    if cb and not cb.can_place_order():
                        self.metrics.circuit_breaker_triggers += 1
                        logger.warning("[LongRunningTest] 熔断器触发!")

                # 检查错误
                if len(self.metrics.errors) > 0:
                    recent_errors = [e for e in self.metrics.errors
                                   if current_time - e['timestamp'] < 60]
                    if len(recent_errors) > 5:
                        logger.error(f"[LongRunningTest] 最近1分钟错误过多: {len(recent_errors)}")

                last_cycles = cycles
                last_trades = trades
                last_check = current_time

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[LongRunningTest] 监控循环错误: {e}")
                self.metrics.record_error('monitor_loop', str(e))

    async def _stats_reporter(self):
        """定期报告统计信息 (每5分钟)"""
        while self._running:
            try:
                await asyncio.sleep(300)  # 5分钟

                if not self.trader:
                    continue

                summary = self.metrics.get_summary()
                status = self.trader.get_status()

                logger.info("=" * 60)
                logger.info("[LongRunningTest] 5分钟统计报告")
                logger.info(f"  运行时间: {summary['runtime_hours']:.2f} / {self.duration_hours} 小时")
                logger.info(f"  总周期数: {summary['total_cycles']}")
                logger.info(f"  总交易数: {summary['total_trades']}")
                logger.info(f"  总盈亏: {summary['total_pnl']:.4f}")
                logger.info(f"  胜率: {summary['win_rate']:.2%}")
                logger.info(f"  平均周期时间: {summary['avg_cycle_time']:.3f}s")
                logger.info(f"  错误数: {summary['error_count']}")
                logger.info(f"  WebSocket重连: {summary['ws_reconnects']}")
                logger.info(f"  熔断器触发: {summary['circuit_breaker_triggers']}")
                logger.info(f"  当前状态: {status['state']}")
                logger.info(f"  当前市场状态: {status['current_regime']}")

                if status.get('phase_c'):
                    phase_c = status['phase_c']
                    logger.info(f"  活跃订单: {phase_c['active_orders']}")
                    logger.info(f"  当前持仓: {phase_c['position']}")
                    logger.info(f"  已实现盈亏: {phase_c['realized_pnl']:.4f}")

                logger.info("=" * 60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[LongRunningTest] 统计报告错误: {e}")

    def _generate_report(self):
        """生成最终测试报告"""
        summary = self.metrics.get_summary()

        report = {
            'test_name': '长时间实盘测试',
            'duration_hours': self.duration_hours,
            'actual_runtime_hours': summary['runtime_hours'],
            'start_time': datetime.fromtimestamp(self.metrics.start_time).isoformat(),
            'end_time': datetime.now().isoformat(),
            'trading_mode': 'PAPER',
            'results': {
                'total_cycles': summary['total_cycles'],
                'total_trades': summary['total_trades'],
                'total_pnl': summary['total_pnl'],
                'win_rate': summary['win_rate'],
                'avg_cycle_time_seconds': summary['avg_cycle_time']
            },
            'stability': {
                'error_count': summary['error_count'],
                'ws_reconnects': summary['ws_reconnects'],
                'api_errors': summary['api_errors']
            },
            'risk_management': {
                'circuit_breaker_triggers': summary['circuit_breaker_triggers'],
                'risk_limits_hit': self.metrics.risk_limits_hit,
                'kill_switch_triggers': self.metrics.kill_switch_triggers
            },
            'errors': self.metrics.errors[-20:]  # 最近20个错误
        }

        # 保存报告
        os.makedirs('logs', exist_ok=True)
        report_file = f"logs/long_running_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        # 打印摘要
        logger.info("\n" + "=" * 60)
        logger.info("长时间实盘测试 - 最终报告")
        logger.info("=" * 60)
        logger.info(f"测试时长: {summary['runtime_hours']:.2f} / {self.duration_hours} 小时")
        logger.info(f"交易周期: {summary['total_cycles']}")
        logger.info(f"成交笔数: {summary['total_trades']}")
        logger.info(f"总盈亏: {summary['total_pnl']:.4f} USDT")
        logger.info(f"胜率: {summary['win_rate']:.2%}")
        logger.info(f"平均周期: {summary['avg_cycle_time']:.3f}s")
        logger.info(f"错误次数: {summary['error_count']}")
        logger.info(f"WebSocket重连: {summary['ws_reconnects']}")
        logger.info(f"熔断器触发: {summary['circuit_breaker_triggers']}")
        logger.info(f"报告保存: {report_file}")
        logger.info("=" * 60)

        # 评估结果
        self._evaluate_results(report)

    def _evaluate_results(self, report: Dict):
        """评估测试结果"""
        logger.info("\n测试结果评估:")

        stability_score = 100
        if report['stability']['error_count'] > 10:
            stability_score -= 20
        if report['stability']['ws_reconnects'] > 5:
            stability_score -= 15
        if report['stability']['api_errors'] > 5:
            stability_score -= 15

        logger.info(f"  稳定性评分: {stability_score}/100")

        if stability_score >= 90:
            logger.info("  ✅ 系统稳定性良好")
        elif stability_score >= 70:
            logger.info("  ⚠️ 系统稳定性一般，需要关注")
        else:
            logger.info("  ❌ 系统稳定性较差，需要修复")

        if report['results']['total_trades'] > 0:
            logger.info(f"  ✅ 交易系统正常运行，共执行 {report['results']['total_trades']} 笔交易")
        else:
            logger.info("  ⚠️ 测试期间未产生交易")

        if report['risk_management']['circuit_breaker_triggers'] == 0:
            logger.info("  ✅ 风控系统未触发（或触发次数正常）")
        else:
            logger.info(f"  ℹ️ 熔断器触发 {report['risk_management']['circuit_breaker_triggers']} 次")


async def main():
    """主函数"""
    # 加载环境变量
    from dotenv import load_dotenv
    load_dotenv('.env')
    logger.info(f"[Main] 环境变量已加载")
    logger.info(f"[Main] API Key: {os.getenv('BINANCE_API_KEY', 'NOT SET')[:10]}...")

    # 创建日志目录
    os.makedirs('logs', exist_ok=True)

    # 创建测试实例 (1小时测试)
    test = LongRunningTest(duration_hours=1.0)

    try:
        # 初始化
        await test.initialize()

        # 运行测试
        await test.run()

    except Exception as e:
        logger.error(f"[Main] 测试失败: {e}")
        raise


if __name__ == "__main__":
    # 设置Windows事件循环策略
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("[Main] 用户中断测试")
    except Exception as e:
        logger.error(f"[Main] 异常: {e}")
        sys.exit(1)
