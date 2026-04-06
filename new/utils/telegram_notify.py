"""
Telegram Notification Module

Lightweight, non-blocking Telegram notifications for trader events.
"""

import os
import logging
from typing import Optional
import asyncio
import aiohttp

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TIMEOUT = 5

# Rate limiting
_last_alert_time = 0
_alert_count = 0


async def send_telegram(msg: str, level: str = "INFO", throttle: int = 60):
    """
    Send Telegram notification with rate limiting.

    Args:
        msg: Message to send
        level: Log level (INFO, WARNING, ERROR, CRITICAL, REPORT)
        throttle: Minimum seconds between alerts (0 to disable)
    """
    global _last_alert_time, _alert_count

    if not BOT_TOKEN or not CHAT_ID:
        logging.debug("Telegram not configured, skipping notification")
        return

    # Rate limiting
    if throttle > 0:
        now = asyncio.get_event_loop().time()
        if now - _last_alert_time < throttle:
            _alert_count += 1
            logging.debug(f"Telegram alert throttled (count: {_alert_count})")
            return
        _last_alert_time = now
        _alert_count = 0

    # Emoji based on level
    emoji = {
        "INFO": "ℹ️",
        "WARNING": "⚠️",
        "ERROR": "❌",
        "CRITICAL": "🚨",
        "REPORT": "📊",
    }.get(level, "ℹ️")

    text = f"{emoji} <b>[{level}]</b> Binance Trader\n\n{msg}"

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_notification": level == "INFO",  # Silent for info
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as resp:
                if resp.status != 200:
                    logging.warning(f"Telegram API error: {resp.status}")
    except asyncio.TimeoutError:
        logging.warning("Telegram notification timeout")
    except Exception as e:
        logging.debug(f"Failed to send telegram message: {e}")


# Convenience functions
async def notify_start():
    """Trader started notification"""
    await send_telegram("✅ Trader started successfully", level="INFO")


async def notify_stop():
    """Trader stopped notification"""
    await send_telegram("🛑 Trader stopped gracefully", level="WARNING")


async def notify_crash(error: str):
    """Trader crashed notification"""
    await send_telegram(f"💥 Trader crashed:\n<pre>{error}</pre>", level="CRITICAL", throttle=0)


async def notify_daily_report(report: str):
    """Daily report notification"""
    await send_telegram(report, level="REPORT", throttle=0)
