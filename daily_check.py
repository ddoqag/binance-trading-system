#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily monitoring script for live paper trading
"""

import sys
import pandas as pd
from datetime import datetime, timedelta


def main():
    """Main daily check function"""
    print("\n" + "="*80)
    print("DAILY CHECK - LIVE PAPER TRADING MONITOR")
    print("="*80)
    print(f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)

    try:
        # Check live view
        print("\n[1/3] Current market state:")
        import subprocess
        subprocess.run(["python", "live_view.py"], check=True)

        # Check simulation results
        print("\n" + "="*80)
        print("[2/3] Recent simulation results:")
        print("="*80)
        subprocess.run(["python", "analyze_simulation.py"], check=True)

        # Check running process
        print("\n" + "="*80)
        print("[3/3] Running processes:")
        print("="*80)
        print("Use '/tasks' command in Claude Code to check running simulations")

        print("\n" + "="*80)
        print("DAILY CHECK COMPLETE")
        print("="*80)
        print("Next check: Tomorrow at the same time")
        print("="*80)

        return True

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
