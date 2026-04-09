"""
自动确认版本的实盘交易脚本
"""
import os
import sys

# 设置自动确认
os.environ['AUTO_CONFIRM_TRADING'] = 'true'

# 导入并运行主脚本
exec(open('run_small_live_trading.py').read())
