#!/usr/bin/env python
"""
24小时信号统计数据收集脚本

Usage:
    python start_data_collection.py --symbol BTCUSDT --capital 1000
"""

import sys
import os
import asyncio
import argparse
import logging
import signal
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from self_evolving_trader import (
    SelfEvolvingTrader, TraderConfig, TradingMode,
    create_trader, run_trader
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 全局变量用于优雅退出
trader_instance = None
start_time = None
duration_hours = 24


def signal_handler(sig, frame):
    """处理Ctrl+C信号"""
    logger.info("\n收到中断信号，正在停止...")
    if trader_instance:
        asyncio.create_task(trader_instance.stop())


async def equity_protection_monitor(trader: SelfEvolvingTrader, initial_capital: float):
    """账户权益保护监控 - 10%回撤自动停止"""
    stop_loss_triggered = False

    while not stop_loss_triggered:
        await asyncio.sleep(60)  # 每分钟检查一次

        try:
            # 获取当前权益
            current_equity = initial_capital
            if hasattr(trader, 'order_manager') and trader.order_manager:
                if hasattr(trader.order_manager, 'get_account_value'):
                    current_equity = await trader.order_manager.get_account_value()
                elif hasattr(trader.order_manager, 'balance'):
                    current_equity = trader.order_manager.balance

            # 计算回撤
            drawdown = (initial_capital - current_equity) / initial_capital

            if drawdown > 0.10:  # 10%回撤保护
                logger.critical(f"🚨 EQUITY PROTECTION TRIGGERED! Drawdown: {drawdown:.1%}")
                logger.critical(f"   Initial: ${initial_capital:,.2f} | Current: ${current_equity:,.2f}")
                logger.critical("   Emergency shutdown initiated...")

                # 紧急平仓所有仓位
                if hasattr(trader, 'lifecycle_manager') and trader.lifecycle_manager:
                    logger.critical("   Closing all positions...")
                    # 触发紧急平仓逻辑

                stop_loss_triggered = True
                await trader.stop()
                break

            elif drawdown > 0.05:  # 5%警告
                logger.warning(f"⚠️  Drawdown warning: {drawdown:.1%} (Current: ${current_equity:,.2f})")

        except Exception as e:
            logger.error(f"Equity monitor error: {e}")

    return stop_loss_triggered


async def print_stats_report(trader: SelfEvolvingTrader):
    """定期打印统计报告"""
    while True:
        await asyncio.sleep(3600)  # 每小时打印一次

        if not hasattr(trader, 'signal_stats') or not trader.signal_stats:
            continue

        stats = trader.signal_stats

        print("\n" + "=" * 70)
        print(f"  信号统计报告 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)

        # 最近统计
        recent = stats.get_recent_stats(100)
        if recent:
            print(f"\n最近100个信号:")
            print(f"  总计: {recent['total_signals']}")
            print(f"  触发: {recent['triggered']}")
            print(f"  阻塞: {recent['blocked']}")
            print(f"  触发率: {recent['trigger_rate']:.1%}")

        # 阈值分析
        analysis = stats.analyze_optimal_threshold()
        if 'error' not in analysis:
            print(f"\n阈值分析:")
            print(f"  样本数: {analysis['samples']}")
            print(f"  净强度均值: {analysis['net_strength_mean']:.3f}")
            print(f"  净强度标准差: {analysis['net_strength_std']:.3f}")
            print(f"  净强度范围: [{analysis['net_strength_min']:.3f}, {analysis['net_strength_max']:.3f}]")
            print(f"\n  推荐: {analysis['recommendation']}")

        # 被阻塞信号分析
        blocked = stats.get_blocked_signal_analysis()
        if 'error' not in blocked:
            print(f"\n被阻塞信号分析:")
            print(f"  总计阻塞: {blocked['total_blocked']}")
            print(f"  已跟踪结果: {blocked['with_outcome']}")
            print(f"  错失利润: {blocked['missed_profit_count']}")
            print(f"  避免损失: {blocked['avoided_loss_count']}")
            print(f"  错失利润率: {blocked['missed_profit_rate']:.1%}")
            print(f"  阈值效率: {blocked['threshold_efficiency']}")

        # 运行时间
        elapsed = datetime.now() - start_time
        remaining = timedelta(hours=duration_hours) - elapsed
        print(f"\n运行时间: {elapsed} | 剩余: {remaining}")
        print("=" * 70 + "\n")


async def main():
    global trader_instance, start_time, duration_hours

    parser = argparse.ArgumentParser(description='24-Hour Signal Data Collection')
    parser.add_argument('--symbol', default='BTCUSDT', help='Trading symbol')
    parser.add_argument('--capital', type=float, default=1000.0, help='Initial capital (USDT)')
    parser.add_argument('--duration', type=int, default=24, help='Collection duration in hours')
    parser.add_argument('--spot-margin', action='store_true', help='Enable spot margin trading')
    parser.add_argument('--margin-mode', default='cross', choices=['cross', 'isolated'])
    parser.add_argument('--max-leverage', type=int, default=3)
    parser.add_argument('--check-interval', type=int, default=5, help='Check interval in seconds')
    parser.add_argument('--persist-file', default='signal_stats.json', help='Statistics persistence file')

    args = parser.parse_args()
    duration_hours = args.duration

    # 加载环境变量
    env_path = Path(__file__).parent / '.env'
    load_dotenv(env_path)

    api_key = os.getenv('BINANCE_API_KEY', '')
    api_secret = os.getenv('BINANCE_API_SECRET', '')

    print("=" * 70)
    print("  24-Hour Signal Data Collection Mode")
    print("=" * 70)
    print(f"\nSymbol: {args.symbol}")
    print(f"Capital: ${args.capital:,.2f}")
    print(f"Duration: {args.duration} hours")
    print(f"Spot Margin: {args.spot_margin}")
    if args.spot_margin:
        print(f"  - Margin Mode: {args.margin_mode.upper()}")
        print(f"  - Max Leverage: {args.max_leverage}x")
    print(f"\nThis will collect signal statistics for threshold optimization.")
    print(f"After {args.duration} hours, run: python check_signal_stats.py")
    print()

    # 注册信号处理
    signal.signal(signal.SIGINT, signal_handler)

    # 创建配置
    config = TraderConfig(
        api_key=api_key,
        api_secret=api_secret,
        symbol=args.symbol,
        trading_mode=TradingMode.PAPER,  # 使用模拟模式进行数据收集
        use_testnet=False,  # 使用生产环境API（模拟模式）
        initial_capital=args.capital,
        check_interval_seconds=args.check_interval,
        enable_spot_margin=args.spot_margin,
        margin_mode=args.margin_mode,
        max_leverage=args.max_leverage,
    )

    try:
        # 创建交易者
        logger.info("Initializing trader...")

        # 重试机制用于网络超时
        max_retries = 3
        trader = None
        for attempt in range(max_retries):
            try:
                trader = await asyncio.wait_for(
                    create_trader(
                        api_key=api_key,
                        api_secret=api_secret,
                        symbol=args.symbol,
                        use_testnet=False,  # 使用生产环境API（模拟模式）
                        initial_capital=args.capital,
                        enable_spot_margin=args.spot_margin,
                        margin_mode=args.margin_mode,
                        max_leverage=args.max_leverage,
                    ),
                    timeout=60  # 60秒超时
                )
                break
            except asyncio.TimeoutError:
                logger.warning(f"Connection timeout (attempt {attempt + 1}/{max_retries})")
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(5)

        trader_instance = trader
        start_time = datetime.now()

        # 配置信号统计持久化
        if hasattr(trader, 'signal_stats') and trader.signal_stats:
            trader.signal_stats.set_persist_file(args.persist_file)
            logger.info(f"Signal statistics will be persisted to: {args.persist_file}")

        logger.info(f"Trader initialized. Starting {args.duration}-hour data collection...")
        logger.info("Press Ctrl+C to stop early\n")

        # 启动监控任务
        stats_task = asyncio.create_task(print_stats_report(trader))
        equity_task = asyncio.create_task(equity_protection_monitor(trader, args.capital))

        # 运行交易者（带超时和异常恢复）
        try:
            await asyncio.wait_for(
                run_trader(trader, duration_seconds=args.duration * 3600),
                timeout=args.duration * 3600 + 60  # 额外1分钟用于清理
            )
        except Exception as e:
            logger.error(f"Trading loop error: {e}")
            # 尝试保存当前统计
            if hasattr(trader, 'signal_stats') and trader.signal_stats:
                trader.signal_stats._persist()
                logger.info("Statistics persisted after error.")
            raise

        stats_task.cancel()
        equity_task.cancel()

    except asyncio.TimeoutError:
        logger.info(f"\n{duration_hours}-hour collection period completed!")
    except KeyboardInterrupt:
        logger.info("\nCollection stopped by user.")
    except Exception as e:
        logger.error(f"Error: {e}")
        # 尝试保存统计
        if trader_instance and hasattr(trader_instance, 'signal_stats') and trader_instance.signal_stats:
            trader_instance.signal_stats._persist()
        raise
    finally:
        if trader_instance:
            # 保存统计
            if hasattr(trader_instance, 'signal_stats') and trader_instance.signal_stats:
                trader_instance.signal_stats._persist()
                logger.info(f"Statistics saved to: {trader_instance.signal_stats._persist_file}")
            await trader_instance.stop()

        # 打印最终报告
        print("\n" + "=" * 70)
        print("  Final Signal Statistics Report")
        print("=" * 70)

        if trader_instance and hasattr(trader_instance, 'signal_stats'):
            stats = trader_instance.signal_stats

            analysis = stats.analyze_optimal_threshold()
            if 'error' not in analysis:
                print(f"\n总样本数: {analysis['samples']}")
                print(f"净强度分布: {analysis['net_strength_mean']:.3f} ± {analysis['net_strength_std']:.3f}")
                print(f"\n推荐阈值: {analysis['recommendation']}")

                print(f"\n各阈值捕获率:")
                for t, data in sorted(analysis['threshold_analysis'].items()):
                    print(f"  阈值 {t:.2f}: {data['capture_rate']:.1%}")

            blocked = stats.get_blocked_signal_analysis()
            if 'error' not in blocked:
                print(f"\n被阻塞信号分析:")
                print(f"  总计阻塞: {blocked['total_blocked']}")
                print(f"  错失利润: {blocked['missed_profit_count']} ({blocked['missed_profit_rate']:.1%})")
                print(f"  平均错失利润: {blocked['avg_missed_profit']:.2%}")

        print("\n" + "=" * 70)
        print("Run 'python check_signal_stats.py' to view detailed report anytime.")
        print("=" * 70)


if __name__ == '__main__':
    asyncio.run(main())
