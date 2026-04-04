"""
完整的实时自优化交易系统

集成：
- SelfEvolvingTrader (6策略交易)
- LiveAutoResearch (实时优化)
- 真实市场数据
"""

import asyncio
import sys
import os
import signal
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from self_evolving_trader import SelfEvolvingTrader, TraderConfig
from live_autoresearch import LiveAutoResearch, LiveResearchIntegration


class FullAutoresearchTradingSystem:
    """完整的自主进化交易系统"""

    def __init__(self):
        self.trader = None
        self.research = None
        self.integration = None
        self.running = False

    async def start(self):
        """启动完整系统"""
        print("=" * 80)
        print("自主进化交易系统 - Full AutoResearch Trading")
        print("=" * 80)
        print(f"启动时间: {datetime.now()}")
        print("\n系统组件:")
        print("  [OK] SelfEvolvingTrader (6策略交易核心)")
        print("  [OK] LiveAutoResearch (实时优化引擎)")
        print("  [OK] 真实市场数据 (Binance Testnet)")
        print("  [OK] 信号驱动权重进化 (Signal-Based)")
        print("\n优化特性:")
        print("  - 实时市场状态检测")
        print("  - 自适应参数调整")
        print("  - 5分钟自动优化循环")
        print("  - 24/7自主运行")
        print("=" * 80)

        # 创建配置
        config = TraderConfig(
            symbol="BTCUSDT",
            initial_capital=10000.0
        )

        # 启动交易系统
        print("\n[1/3] 启动 SelfEvolvingTrader...")
        self.trader = SelfEvolvingTrader(config)
        await self.trader.initialize()

        # 启动实时研究
        print("[2/3] 启动 LiveAutoResearch...")
        self.research = LiveAutoResearch()

        # 创建集成
        print("[3/3] 创建系统集成...")
        self.integration = LiveResearchIntegration(self.trader)

        self.running = True

        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        print("\n" + "=" * 80)
        print("系统启动成功！")
        print("=" * 80)
        print("\n实时监控:")
        print("  - 策略权重: 每5秒更新")
        print("  - 市场状态: 实时检测")
        print("  - 自动优化: 每5分钟")
        print("  - 状态报告: 每分钟")
        print("\n按 Ctrl+C 停止系统")
        print("=" * 80 + "\n")

        # 启动主循环
        await self._main_loop()

    async def _main_loop(self):
        """主运行循环"""
        iteration = 0

        try:
            while self.running:
                iteration += 1

                # 运行交易周期
                await self.trader._trading_cycle()

                # 同步数据到实时研究
                if hasattr(self.trader, 'price_history') and self.trader.price_history:
                    latest_price = self.trader.price_history[-1]
                    self.research.update_price(latest_price)

                if hasattr(self.trader, 'meta_agent'):
                    weights = self.trader.meta_agent.get_strategy_weights()
                    self.research.record_weights(weights)

                # 每分钟打印状态
                if iteration % 12 == 0:  # 每12个周期（约60秒）
                    self.research.print_status()

                    # 打印当前权重
                    if hasattr(self.trader, 'meta_agent'):
                        weights = self.trader.meta_agent.get_strategy_weights()
                        print("\n当前策略权重:")
                        for name, weight in sorted(weights.items(), key=lambda x: -x[1]):
                            bar = "█" * int(weight * 30)
                            print(f"  {name:20s}: {weight:.3f} {bar}")

                await asyncio.sleep(5)  # 5秒周期

        except Exception as e:
            print(f"\n❌ 错误: {e}")
        finally:
            await self.stop()

    def _signal_handler(self, signum, frame):
        """信号处理"""
        print("\n\n收到停止信号...")
        self.running = False

    async def stop(self):
        """停止系统"""
        print("\n" + "=" * 80)
        print("正在停止系统...")

        if self.trader:
            await self.trader.stop()

        if self.integration:
            self.integration.stop()

        print("系统已安全停止")
        print("=" * 80)


async def main():
    """主入口"""
    system = FullAutoresearchTradingSystem()
    await system.start()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n用户中断")
        sys.exit(0)
