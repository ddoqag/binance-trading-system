"""
Daily Trading Report Generator

Generates formatted daily PnL and position reports.
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from self_evolving_trader import SelfEvolvingTrader


async def generate_daily_report(trader: "SelfEvolvingTrader") -> str:
    """
    Generate daily trading report.

    Args:
        trader: SelfEvolvingTrader instance

    Returns:
        Formatted report string
    """
    lines = [
        f"📊 <b>Daily Report</b>",
        f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M UTC')}</i>",
        "",
    ]

    # Account info
    if hasattr(trader, 'order_manager') and trader.order_manager:
        account = trader.order_manager.account
        lines.extend([
            f"💰 <b>Balance:</b> {account.total_balance:.2f} USDT",
            f"💎 <b>Available:</b> {account.available_balance:.2f} USDT",
            "",
        ])

    # Positions
    if hasattr(trader, 'order_manager') and trader.order_manager:
        positions = trader.order_manager.positions
        if positions:
            lines.append("📈 <b>Positions:</b>")
            total_pnl = 0.0

            for symbol, pos in positions.items():
                pnl = pos.unrealized_pnl if hasattr(pos, 'unrealized_pnl') else 0.0
                total_pnl += pnl
                entry = pos.entry_price if hasattr(pos, 'entry_price') else 0.0
                qty = pos.quantity if hasattr(pos, 'quantity') else 0.0

                pnl_emoji = "🟢" if pnl >= 0 else "🔴"
                lines.append(
                    f"  {pnl_emoji} {symbol}: {qty:.6f} @ {entry:.2f} "
                    f"(PnL: {pnl:+.2f})"
                )

            lines.append(f"\n<b>Total Unrealized PnL:</b> {total_pnl:+.2f} USDT")
        else:
            lines.append("📭 No open positions")

    # Trading stats
    if hasattr(trader, 'stats'):
        stats = trader.stats
        lines.extend([
            "",
            f"📉 <b>Stats:</b>",
            f"  Total Trades: {stats.total_trades}",
            f"  Win Rate: {stats.win_count}/{stats.loss_count} "
            f"({stats.win_rate:.1%})" if hasattr(stats, 'win_rate') else "",
            f"  Total PnL: {stats.total_pnl:+.4f}",
        ])

    # System health
    uptime = datetime.now() - datetime.fromtimestamp(
        trader.stats.start_time if hasattr(trader, 'stats') else datetime.now().timestamp()
    )
    lines.extend([
        "",
        f"⏱ <b>Uptime:</b> {uptime.total_seconds() / 3600:.1f} hours",
    ])

    # Circuit Breaker status
    if hasattr(trader, 'circuit_breaker') and trader.circuit_breaker:
        cb_status = trader.circuit_breaker.get_status()
        if cb_status['trading_halted']:
            lines.extend([
                "",
                f"🚨 <b>Circuit Breaker:</b> HALTED",
                f"   Reason: {cb_status['halt_reason']}",
            ])
        else:
            lines.extend([
                "",
                f"🛡 <b>Circuit Breaker:</b> Active",
                f"   Drawdown: {cb_status['drawdown_pct']:.2f}% (limit: {cb_status['drawdown_limit_pct']}%)",
                f"   Consecutive losses: {cb_status['consecutive_losses']}/{cb_status['max_consecutive_losses']}",
                f"   Today's win rate: {cb_status['win_rate_today']:.1%}",
            ])

    return "\n".join(lines)
