#!/usr/bin/env python
"""
Self-Evolving Trading System 启动脚本

Usage:
    python run_trading_system.py --mode paper
    python run_trading_system.py --mode backtest
    python run_trading_system.py --mode live
"""

import sys
import os
import asyncio
import argparse
import logging
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from production import DeploymentManager, HealthChecker
from production.config_validator import ConfigValidator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    parser = argparse.ArgumentParser(description='Self-Evolving Trading System')
    parser.add_argument(
        '--mode',
        choices=['backtest', 'paper', 'live'],
        default='paper',
        help='Trading mode (default: paper)'
    )
    parser.add_argument(
        '--config',
        default='config/self_evolving_trader.yaml',
        help='Configuration file path'
    )
    parser.add_argument(
        '--skip-checks',
        action='store_true',
        help='Skip pre-deployment checks'
    )
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("Self-Evolving Trading System")
    print("Phase 1-9 Integrated Platform")
    print("=" * 60)
    print(f"\nMode: {args.mode.upper()}")
    print(f"Config: {args.config}")

    # 设置交易模式
    os.environ['TRADING_MODE'] = args.mode

    # 创建部署管理器
    dm = DeploymentManager()

    # 运行预检查
    if not args.skip_checks:
        if not dm.run_pre_checks():
            print("\n[FAIL] Pre-deployment checks failed. Use --skip-checks to bypass.")
            sys.exit(1)

    # 启动系统
    if not await dm.startup(skip_checks=args.skip_checks):
        print("\n[FAIL] System startup failed.")
        sys.exit(1)

    # 保持运行
    print("\n[System] Running... Press Ctrl+C to stop.")
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n[System] Shutdown signal received.")
    finally:
        await dm.shutdown()


if __name__ == '__main__':
    asyncio.run(main())
