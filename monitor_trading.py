#!/usr/bin/env python3
"""
交易监控工具 - 查看当前状态
"""

import json
import os
from datetime import datetime
from pathlib import Path

def main():
    print("=" * 60)
    print("  交易监控面板")
    print("=" * 60)

    # 读取状态
    if Path('trading_state.json').exists():
        with open('trading_state.json') as f:
            state = json.load(f)

        print(f"\n📊 交易状态")
        print(f"  最后更新: {state.get('last_update', 'N/A')}")
        print(f"  今日盈亏: ${state.get('daily_pnl', 0):+.2f}")
        print(f"  总盈亏:   ${state.get('total_pnl', 0):+.2f}")
        print(f"  交易次数: {state.get('trade_count', 0)}")

        if state.get('position', 0) > 0:
            print(f"\n💼 当前持仓")
            print(f"  数量: {state['position']:.4f} BTC")
            print(f"  入场价: ${state['entry_price']:.2f}")
    else:
        print("\n  暂无交易状态文件")

    # 检查日志
    log_dir = Path('logs')
    if log_dir.exists():
        logs = sorted(log_dir.glob('live_*.log'))
        if logs:
            print(f"\n📝 最近日志")
            for log in logs[-5:]:
                size = log.stat().st_size / 1024
                print(f"  {log.name} ({size:.1f} KB)")

    print("\n" + "=" * 60)

if __name__ == '__main__':
    main()
