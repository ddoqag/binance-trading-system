#!/usr/bin/env python
"""
实盘交易启动脚本 - 带安全检查

Usage:
    python start_live_trader.py --symbol BTCUSDT --capital 1000
    python start_live_trader.py --dry-run  # 只验证连接，不下单
"""

import sys
import os
import asyncio
import argparse
import logging
from pathlib import Path
from decimal import Decimal

# 添加项目路径
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


async def verify_api_connection(api_key: str, api_secret: str) -> bool:
    """验证 API 连接和权限"""
    import requests

    try:
        # 测试连接 - 获取服务器时间
        resp = requests.get('https://api.binance.com/api/v3/time', timeout=5)
        server_time = resp.json()['serverTime']
        logger.info(f"[Verify] Server time: {server_time}")

        # 测试账户权限（需要签名）
        timestamp = int(time.time() * 1000)
        query_string = f'timestamp={timestamp}'
        signature = hmac.new(
            api_secret.encode(),
            query_string.encode(),
            hashlib.sha256
        ).hexdigest()

        headers = {'X-MBX-APIKEY': api_key}
        url = f'https://api.binance.com/api/v3/account?{query_string}&signature={signature}'

        resp = requests.get(url, headers=headers, timeout=10)

        if resp.status_code == 200:
            data = resp.json()
            balances = [b for b in data['balances'] if float(b['free']) > 0 or float(b['locked']) > 0]
            logger.info(f"[Verify] API connection successful!")
            logger.info(f"[Verify] Account has {len(balances)} non-zero balances")
            logger.info(f"[Verify] Permissions: {data.get('permissions', [])}")
            return True
        else:
            logger.error(f"[Verify] API error: {resp.status_code} - {resp.text}")
            return False

    except Exception as e:
        logger.error(f"[Verify] Connection failed: {e}")
        return False


async def main():
    parser = argparse.ArgumentParser(description='Live Trading - Self-Evolving Trader')
    parser.add_argument('--symbol', default='BTCUSDT', help='Trading symbol')
    parser.add_argument('--capital', type=float, default=1000.0, help='Initial capital (USDT)')
    parser.add_argument('--max-position', type=float, default=0.2, help='Max position size (0.2 = 20 percent)')
    parser.add_argument('--dry-run', action='store_true', help='Dry run - verify only, no orders')
    parser.add_argument('--check-interval', type=int, default=5, help='Check interval in seconds')
    parser.add_argument('--spot-margin', action='store_true', help='Enable spot margin trading (3x leverage)')
    parser.add_argument('--margin-mode', type=str, default='cross', choices=['cross', 'isolated'], help='Margin mode: cross or isolated')
    parser.add_argument('--max-leverage', type=int, default=3, help='Maximum leverage (1-10)')

    args = parser.parse_args()

    # 加载环境变量
    env_path = Path(__file__).parent / '.env'
    load_dotenv(env_path)

    api_key = os.getenv('BINANCE_API_KEY', '')
    api_secret = os.getenv('BINANCE_API_SECRET', '')

    print("=" * 60)
    print("  LIVE TRADING MODE - Self-Evolving Trader")
    print("=" * 60)
    print(f"\nSymbol: {args.symbol}")
    print(f"Capital: ${args.capital:,.2f}")
    print(f"Max Position: {args.max_position*100:.0f}%")
    print(f"Dry Run: {args.dry_run}")
    print(f"Spot Margin: {args.spot_margin}")
    if args.spot_margin:
        print(f"  - Margin Mode: {args.margin_mode.upper()}")
        print(f"  - Max Leverage: {args.max_leverage}x")
    print()

    # 验证 API Key
    if not api_key or not api_secret:
        logger.error("API key and secret required!")
        logger.error("Set BINANCE_API_KEY and BINANCE_API_SECRET in .env file")
        sys.exit(1)

    logger.info(f"API Key: {api_key[:15]}...")

    # 验证连接
    logger.info("\n[1/3] Verifying API connection...")
    if not await verify_api_connection(api_key, api_secret):
        logger.error("API connection failed! Please check your API keys.")
        sys.exit(1)

    if args.dry_run:
        logger.info("\n[Dry Run] Connection verified. Exiting without trading.")
        sys.exit(0)

    # 安全确认
    print("\n" + "!" * 60)
    print("  WARNING: This will execute REAL trades with REAL money!")
    print("!" * 60)
    confirm = input("\nType 'LIVE' to confirm: ")

    if confirm != 'LIVE':
        logger.info("Aborted.")
        sys.exit(0)

    # 创建配置
    logger.info("\n[2/3] Initializing trader...")

    config = TraderConfig(
        api_key=api_key,
        api_secret=api_secret,
        symbol=args.symbol,
        trading_mode=TradingMode.LIVE,
        use_testnet=False,
        initial_capital=args.capital,
        check_interval_seconds=args.check_interval,
        enable_spot_margin=args.spot_margin,
        margin_mode=args.margin_mode,
        max_leverage=args.max_leverage,
    )

    try:
        # 创建并启动交易者
        trader = await create_trader(
            api_key=api_key,
            api_secret=api_secret,
            symbol=args.symbol,
            use_testnet=False,
            initial_capital=args.capital,
            enable_spot_margin=args.spot_margin,
            margin_mode=args.margin_mode,
            max_leverage=args.max_leverage,
        )

        logger.info("\n[3/3] Trader initialized successfully!")
        logger.info("Starting live trading...")
        logger.info("Press Ctrl+C to stop\n")

        # 运行交易者
        await run_trader(trader, duration_seconds=None)  # 无限运行

    except KeyboardInterrupt:
        logger.info("\nStopping trader...")
        await trader.stop()
        logger.info("Trader stopped.")

    except Exception as e:
        logger.error(f"Error: {e}")
        raise


if __name__ == '__main__':
    import time
    import hmac
    import hashlib

    asyncio.run(main())
