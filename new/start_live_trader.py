#!/usr/bin/env python3
"""
实盘交易启动脚本 - 带安全检查

Usage:
    python start_live_trader.py --symbol BTCUSDT --capital 1000
    python start_live_trader.py --dry-run  # 只验证连接，不下单
"""

import sys
import os
import psutil
import atexit
import asyncio
import argparse
import hashlib
import hmac
import logging
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from config.mode import TradingMode
from self_evolving_trader import (
    create_trader, run_trader
)
from core.live_risk_manager import RiskLimits
from utils.telegram_notify import notify_start, notify_stop, notify_crash
from scheduler.daily_report_scheduler import daily_report_loop

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# ========= PID 文件管理 =========
PID_FILE = "trader.pid"


def write_pid():
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def remove_pid():
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)


def check_existing_instance():
    if not os.path.exists(PID_FILE):
        return False

    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())

        if psutil.pid_exists(pid):
            proc = psutil.Process(pid)
            cmdline = " ".join(proc.cmdline())
            if "start_live_trader" in cmdline:
                return True
    except (ValueError, psutil.NoSuchProcess, FileNotFoundError):
        # PID 文件损坏或进程已不存在
        pass

    # 清理过期的 PID 文件
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
    return False


# 检查是否已有实例在运行
if check_existing_instance():
    print("ERROR: Trader is already running.")
    sys.exit(1)

write_pid()
atexit.register(remove_pid)
logger = logging.getLogger(__name__)


async def verify_api_connection(api_key: str, api_secret: str) -> bool:
    """验证 API 连接和权限"""
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    try:
        # 从环境变量读取代理配置
        proxies = {}
        http_proxy = os.getenv('HTTP_PROXY')
        https_proxy = os.getenv('HTTPS_PROXY')
        if http_proxy:
            proxies['http'] = http_proxy
        if https_proxy:
            proxies['https'] = https_proxy
        if not proxies:
            proxies = None
        if proxies:
            logger.info(f"[Verify] Using proxy: {proxies}")

        # 创建带重试的 session
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.proxies = proxies

        # 测试连接 - 获取服务器时间
        resp = session.get('https://api.binance.com/api/v3/time', timeout=10)
        server_time = resp.json()['serverTime']
        logger.info(f"[Verify] Server time: {server_time}")

        # 使用服务器时间进行签名，避免本地时钟偏移问题
        # 添加 recvWindow 扩大时间容差
        query_string = f'timestamp={server_time}&recvWindow=5000'
        signature = hmac.new(
            api_secret.encode(),
            query_string.encode(),
            hashlib.sha256
        ).hexdigest()

        headers = {'X-MBX-APIKEY': api_key}
        url = f'https://api.binance.com/api/v3/account?{query_string}&signature={signature}'

        resp = session.get(url, headers=headers, timeout=10)

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
    parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation (auto-confirm LIVE)')
    parser.add_argument('--mode', type=str, choices=['live', 'paper'], default=None,
                        help='Trading mode: live (real money) or paper (simulation). Overrides env/config.')

    args = parser.parse_args()

    # 加载环境变量
    env_path = Path(__file__).parent / '.env'
    load_dotenv(env_path)

    api_key = os.getenv('BINANCE_API_KEY', '')
    api_secret = os.getenv('BINANCE_API_SECRET', '')

    # 确定交易模式
    from config.trading_mode_switcher import TradingModeSwitcher
    mode_switcher = TradingModeSwitcher()

    if args.mode:
        # 命令行参数优先
        trading_mode = TradingMode.from_string(args.mode)
        mode_switcher.set_mode(trading_mode)
    else:
        # 从环境变量或配置文件读取
        trading_mode = mode_switcher.get_current_mode()

    # 显示模式信息
    print("=" * 60)
    if trading_mode.is_live():
        print("  LIVE TRADING MODE - Self-Evolving Trader")
    else:
        print("  PAPER TRADING MODE - Simulation Only")
    print("=" * 60)
    print(f"\nSymbol: {args.symbol}")
    print(f"Capital: ${args.capital:,.2f}")
    print(f"Max Position: {args.max_position*100:.0f}%")
    print(f"Mode: {trading_mode.value.upper()}")
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

    logger.info(f"API Key: {'*' * 10} (已隐藏)")

    # 验证连接
    logger.info("\n[1/3] Verifying API connection...")
    if not await verify_api_connection(api_key, api_secret):
        logger.error("API connection failed! Please check your API keys.")
        sys.exit(1)

    if args.dry_run:
        logger.info("\n[Dry Run] Connection verified. Exiting without trading.")
        sys.exit(0)

    # LIVE 模式安全确认
    if trading_mode.is_live():
        print("\n" + "!" * 60)
        print("  WARNING: This will execute REAL trades with REAL money!")
        print("!" * 60)

        if args.yes:
            confirm = 'LIVE'
            logger.info("[Auto-Confirm] --yes flag provided, skipping confirmation.")
        else:
            confirm = input("\nType 'LIVE' to confirm: ")

        if confirm != 'LIVE':
            logger.info("Aborted.")
            sys.exit(0)
    else:
        # PAPER 模式自动确认
        logger.info("[Paper Mode] Simulation mode, no confirmation needed.")

    logger.info("\n[2/3] Initializing trader...")

    risk_limits = RiskLimits(
        max_single_position_pct=args.max_position,
        max_total_position_pct=max(args.max_position, 0.8),
        max_leverage=args.max_leverage,
    )

    try:
        # 创建并启动交易者
        trader = await create_trader(
            api_key=api_key,
            api_secret=api_secret,
            symbol=args.symbol,
            use_testnet=False,
            trading_mode=trading_mode.value,
            initial_capital=args.capital,
            risk_limits=risk_limits,
            check_interval_seconds=args.check_interval,
            auto_resume=False,
            enable_spot_margin=args.spot_margin,
            margin_mode=args.margin_mode,
            max_leverage=args.max_leverage,
        )

        logger.info("\n[3/3] Trader initialized successfully!")
        logger.info("Starting live trading...")
        logger.info("Press Ctrl+C to stop\n")

        # 发送启动通知
        await notify_start()

        # 启动日报调度器（后台任务）
        report_task = None
        try:
            report_task = asyncio.create_task(daily_report_loop(trader))
            logger.info("[DailyReport] Scheduler started")
        except Exception as e:
            logger.warning(f"[DailyReport] Failed to start scheduler: {e}")

        # 运行交易者
        await run_trader(trader, duration_seconds=None)  # 无限运行

        # 取消日报调度器
        if report_task:
            report_task.cancel()
            try:
                await report_task
            except asyncio.CancelledError:
                pass

        # 发送停止通知
        await notify_stop()

    except KeyboardInterrupt:
        logger.info("\nStopping trader...")
        await trader.stop()
        await notify_stop()
        logger.info("Trader stopped.")

    except Exception as e:
        logger.error(f"Error: {e}")
        await notify_crash(str(e))
        raise


if __name__ == '__main__':
    asyncio.run(main())
