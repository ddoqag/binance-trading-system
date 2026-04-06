"""
Resilient Loop Utility

Provides automatic retry with exponential backoff for critical loops.
"""

import asyncio
import logging
from typing import Callable, Awaitable, Optional

logger = logging.getLogger(__name__)


async def resilient_loop(
    name: str,
    coro_fn: Callable[[], Awaitable[None]],
    interval: float = 5.0,
    max_failures: int = 5,
    backoff_factor: float = 2.0,
    max_backoff: float = 60.0,
    shutdown_event: Optional[asyncio.Event] = None
):
    """
    Run a coroutine in a resilient loop with automatic retry.

    Args:
        name: Loop name for logging
        coro_fn: Async function to run
        interval: Normal interval between successful runs
        max_failures: Max consecutive failures before giving up
        backoff_factor: Exponential backoff multiplier
        max_backoff: Maximum backoff seconds
        shutdown_event: Event to signal loop termination

    Raises:
        RuntimeError: If max_failures exceeded
    """
    failures = 0
    current_interval = interval

    logger.info(f"[{name}] Resilient loop started")

    while shutdown_event is None or not shutdown_event.is_set():
        try:
            await coro_fn()

            # Success: reset counters
            if failures > 0:
                logger.info(f"[{name}] Recovered after {failures} failures")
            failures = 0
            current_interval = interval

        except asyncio.CancelledError:
            logger.info(f"[{name}] Loop cancelled")
            raise

        except Exception as e:
            failures += 1
            logger.exception(f"[{name}] Error ({failures}/{max_failures}): {e}")

            if failures >= max_failures:
                logger.critical(f"[{name}] Max failures reached, giving up")
                raise RuntimeError(f"[{name}] Failed {max_failures} times")

            # Exponential backoff
            current_interval = min(current_interval * backoff_factor, max_backoff)
            logger.info(f"[{name}] Retrying in {current_interval:.1f}s")

        # Wait before next iteration
        try:
            if shutdown_event:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=current_interval
                )
                break  # Shutdown triggered
            else:
                await asyncio.sleep(current_interval)
        except asyncio.TimeoutError:
            pass  # Normal interval passed

    logger.info(f"[{name}] Resilient loop stopped")


async def health_check_loop(
    check_fn: Callable[[], bool],
    notify_fn: Callable[[str], Awaitable[None]],
    interval: int = 60,
    shutdown_event: Optional[asyncio.Event] = None
):
    """
    Health check loop that monitors system status.

    Args:
        check_fn: Function returning True if healthy
        notify_fn: Async function to call on health issues
        interval: Check interval in seconds
        shutdown_event: Event to signal termination
    """
    logger.info("[HealthCheck] Started")

    while shutdown_event is None or not shutdown_event.is_set():
        try:
            is_healthy = check_fn()

            if not is_healthy:
                await notify_fn("⚠️ Health check failed")
                logger.warning("[HealthCheck] Health check failed")

        except Exception as e:
            logger.exception(f"[HealthCheck] Error: {e}")

        # Wait for next check or shutdown
        try:
            if shutdown_event:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=interval
                )
                break
            else:
                await asyncio.sleep(interval)
        except asyncio.TimeoutError:
            pass

    logger.info("[HealthCheck] Stopped")
