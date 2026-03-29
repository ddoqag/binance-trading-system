#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证项目结构 - 不依赖外部库
"""

import sys
from pathlib import Path

print("="*60)
print("验证币安量化交易系统 - 项目结构")
print("="*60)

# 检查目录
directories = [
    'trading',
    'strategy',
    'risk',
    'models',
    'utils',
    'web',
    'data',
    'plots',
]

print("\n[1/3] 检查目录...")
for dir_name in directories:
    dir_path = Path(dir_name)
    if dir_path.exists() and dir_path.is_dir():
        print(f"  [OK] {dir_name}/")
    else:
        print(f"  [MISSING] {dir_name}/")

# 检查模块文件
module_files = [
    ('trading', '__init__.py'),
    ('trading', 'execution.py'),
    ('trading', 'order.py'),
    ('strategy', '__init__.py'),
    ('strategy', 'base.py'),
    ('strategy', 'dual_ma.py'),
    ('strategy', 'rsi_strategy.py'),
    ('strategy', 'ml_strategy.py'),
    ('risk', '__init__.py'),
    ('risk', 'manager.py'),
    ('risk', 'position.py'),
    ('risk', 'stop_loss.py'),
    ('models', '__init__.py'),
    ('models', 'features.py'),
    ('models', 'predictor.py'),
    ('models', 'model_trainer.py'),
    ('utils', '__init__.py'),
    ('utils', 'helpers.py'),
    ('utils', 'database.py'),
    ('web', '__init__.py'),
]

print("\n[2/3] 检查模块文件...")
all_found = True
for dir_name, file_name in module_files:
    file_path = Path(dir_name) / file_name
    if file_path.exists():
        print(f"  [OK] {dir_name}/{file_name}")
    else:
        print(f"  [MISSING] {dir_name}/{file_name}")
        all_found = False

# 检查主程序文件
main_files = [
    'main_trading_system.py',
    'PROJECT_SUMMARY.md',
    'requirements.txt',
]

print("\n[3/3] 检查主文件...")
for file_name in main_files:
    file_path = Path(file_name)
    if file_path.exists():
        print(f"  [OK] {file_name}")
    else:
        print(f"  [MISSING] {file_name}")

print("\n" + "="*60)
if all_found:
    print("项目结构验证完成 - 所有模块文件已创建!")
else:
    print("项目结构验证完成 - 部分文件缺失")
print("="*60)
print("\n模块说明:")
print("  trading/  - 交易执行和订单管理")
print("  strategy/ - 交易策略实现 (双均线、RSI、ML)")
print("  risk/     - 风险控制 (仓位、止损、风险限制)")
print("  models/   - 机器学习 (特征工程、模型训练、预测)")
print("  utils/    - 工具函数 (日志、数据库连接)")
print("  web/      - Web UI (预留)")
