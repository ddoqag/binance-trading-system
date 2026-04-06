"""
Daily Report Scheduler

Sends daily trading report at configured time (default 08:30).
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from reporting.daily_report import generate_daily_report
from utils.telegram_notify import notify_daily_report

if TYPE_CHECKING:
    from self_evolving_trader import SelfEvolvingTrader

logger = logging.getLogger(__name__)


async def daily_report_loop(
    trader: "SelfEvolvingTrader",
    hour: int = 8,
    minute: int = 30
):
    """
    Daily report scheduler loop.

    Args:
        trader: SelfEvolvingTrader instance
        hour: Hour to send report (0-23)
        minute: Minute to send report (0-59)
    """
    logger.info(f"[DailyReport] Scheduler started (target: {hour:02d}:{minute:02d})")

    while not trader._shutdown_event.is_set():
        try:
            now = datetime.now()
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            if now >= target:
                # Target time passed today, schedule for tomorrow
                target += timedelta(days=1)

            wait_secs = (target - now).total_seconds()
            logger.debug(f"[DailyReport] Next report in {wait_secs / 3600:.1f} hours")

            # Wait until target time or shutdown
            try:
                await asyncio.wait_for(
                    trader._shutdown_event.wait(),
                    timeout=wait_secs
                )
                # Shutdown event triggered
                break
            except asyncio.TimeoutError:
                # Time to send report
                pass

            # Generate and send report
            try:
                report = await generate_daily_report(trader)
                await notify_daily_report(report)
                logger.info("[DailyReport] Daily report sent")
            except Exception as e:
                logger.exception(f"[DailyReport] Failed to generate/send report: {e}")
                await notify_daily_report(f"⚠️ Daily report failed: {e}")

            # Reset circuit breaker for new day
            if hasattr(trader, 'circuit_breaker') and trader.circuit_breaker:
                if trader.circuit_breaker.config.auto_reset_on_new_day:
                    await trader.circuit_breaker.reset()
                    logger.info("[DailyReport] Circuit breaker reset for new day")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception(f"[DailyReport] Scheduler error: {e}")
            await asyncio.sleep(60)  # Retry in 1 minute on error

    logger.info("[DailyReport] Scheduler stopped")
