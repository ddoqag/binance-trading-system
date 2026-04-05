"""
启动实时优化的交易系统

结合 SelfEvolvingTrader 和 LiveAutoResearch
"""

import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from live_autoresearch import LiveAutoResearch


async def run_optimized_trader():
    """运行实时优化的交易系统"""

    print("=" * 70)
    print("Live Optimized Trading System")
    print("=" * 70)
    print("Features:")
    print("  - Real-time market regime detection")
    print("  - Adaptive parameter adjustment")
    print("  - Continuous optimization")
    print("  - 6-strategy ensemble with ML")
    print("=" * 70)

    # 创建实时研究模块
    research = LiveAutoResearch()

    # 启动研究循环（这会持续运行）
    try:
        await research.run()
    except KeyboardInterrupt:
        print("\n\nShutdown complete")


if __name__ == '__main__':
    asyncio.run(run_optimized_trader())
