#!/usr/bin/env python3
"""
风控熔断演示 - Circuit Breaker Demo

演示熔断器的三种触发条件：
1. 最大回撤超限
2. 连续亏损次数超限
3. 日内总亏损超限

使用方法：
    python demo_circuit_breaker.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from risk.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from utils.telegram_notify import send_telegram


async def notify_fn(msg: str, level: str):
    """模拟通知函数"""
    print(f"\n*** [{level}] {msg}\n")


async def demo_max_drawdown():
    """演示最大回撤熔断"""
    print("\n" + "=" * 60)
    print("  演示1: 最大回撤熔断")
    print("=" * 60)

    cb = CircuitBreaker(
        config=CircuitBreakerConfig(max_drawdown_pct=5.0),  # 5%最大回撤
        notify_fn=notify_fn
    )

    # 初始化余额
    cb.initialize_balance(10000.0)

    print(f"初始余额: 10000.0 USDT")
    print(f"最大回撤限制: 5%")
    print()

    # 模拟价格下跌
    prices = [10000, 9900, 9800, 9700, 9600, 9500, 9400]

    for price in prices:
        can_trade = await cb.check(price)
        drawdown = (10000 - price) / 10000 * 100

        status = "[OK] 允许交易" if can_trade else "[HALT] 熔断触发"
        print(f"余额: {price:.0f} USDT, 回撤: {drawdown:.1f}% - {status}")

        if not can_trade:
            print(f"\n*** 熔断原因: {cb.state.halt_reason}")
            break


async def demo_consecutive_losses():
    """演示连续亏损熔断"""
    print("\n" + "=" * 60)
    print("  演示2: 连续亏损熔断")
    print("=" * 60)

    cb = CircuitBreaker(
        config=CircuitBreakerConfig(max_consecutive_losses=3),  # 3次连续亏损
        notify_fn=notify_fn
    )

    cb.initialize_balance(10000.0)

    print(f"最大连续亏损限制: 3次")
    print()

    # 模拟交易结果
    results = [-10, -20, -15, -5, 30, -10, -20, -15]  # 5次亏损后会触发

    for pnl in results:
        can_trade = await cb.check()

        if pnl > 0:
            print(f"交易结果: +{pnl:.0f} USDT [WIN]")
        else:
            print(f"交易结果: {pnl:.0f} USDT [LOSS]")

        cb.record_trade_result(pnl)

        status = "[OK] 允许交易" if can_trade else "[HALT] 熔断触发"
        print(f"  连续亏损: {cb.state.consecutive_losses}, 状态: {status}\n")

        if not can_trade:
            print(f"*** 熔断原因: {cb.state.halt_reason}")
            break


async def demo_cooldown_and_reset():
    """演示冷却和重置"""
    print("\n" + "=" * 60)
    print("  演示3: 冷却时间和手动重置")
    print("=" * 60)

    cb = CircuitBreaker(
        config=CircuitBreakerConfig(
            max_consecutive_losses=2,
            cooldown_minutes=0.1  # 6秒冷却（演示用）
        ),
        notify_fn=notify_fn
    )

    cb.initialize_balance(10000.0)

    # 触发熔断
    print("触发熔断...")
    cb.record_trade_result(-10)
    cb.record_trade_result(-20)

    # 手动触发检查以设置熔断状态
    await cb.check(9970)

    print(f"熔断状态: {cb.state.trading_halted}")
    print(f"熔断原因: {cb.state.halt_reason}")
    print()

    # 尝试恢复（应失败）
    print("尝试立即恢复（应失败）...")
    resumed = await cb.try_resume()
    print(f"恢复结果: {'成功' if resumed else '失败（仍在冷却中）'}")
    print()

    # 等待冷却
    print("等待6秒冷却...")
    await asyncio.sleep(6)

    # 再次尝试恢复
    print("\n再次尝试恢复...")
    resumed = await cb.try_resume()
    print(f"恢复结果: {'成功' if resumed else '失败'}")

    if resumed:
        print(f"\n[OK] 熔断已重置，可以恢复交易")
        print(f"新的起始余额: {cb.state.daily_start_balance:.2f} USDT")


async def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("  Circuit Breaker 风控熔断演示")
    print("=" * 60)

    await demo_max_drawdown()
    await demo_consecutive_losses()
    await demo_cooldown_and_reset()

    print("\n" + "=" * 60)
    print("  演示完成")
    print("=" * 60)
    print("\n在实盘交易中，熔断器会自动：")
    print("  1. 监控账户回撤")
    print("  2. 统计连续亏损")
    print("  3. 触发时立即通知（Telegram）")
    print("  4. 冷却结束后自动恢复")
    print("  5. 每日自动重置")


if __name__ == "__main__":
    asyncio.run(main())
