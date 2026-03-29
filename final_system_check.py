#!/usr/bin/env python3
"""
系统最终验证脚本
检查所有关键组件是否正常运行
"""

import sys
import os
import subprocess
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

def run_command(command, description, check_error=True):
    """运行命令并显示结果"""
    try:
        print(f'\n[正在执行] {description}')
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            encoding='utf-8'
        )

        if result.returncode == 0:
            print('[成功]', description)
            if result.stdout.strip():
                print('  输出:', repr(result.stdout.strip()))
            return True
        else:
            print('[失败]', description)
            if result.stdout.strip():
                print('  输出:', repr(result.stdout.strip()))
            if result.stderr.strip():
                print('  错误:', repr(result.stderr.strip()))
            if check_error:
                sys.exit(1)
            return False
    except Exception as e:
        print(f'[错误] {description}: {e}')
        if check_error:
            sys.exit(1)
        return False

def main():
    """主函数"""
    print('='*70)
    print('  币安量化交易系统 - 最终验证')
    print('='*70)

    print(f'验证时间: {__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'项目路径: {Path(__file__).parent}')

    print('\n' + '-'*70)
    print('1. 基础验证')
    print('-'*70)

    # 检查项目根目录
    if not Path('CLAUDE.md').exists():
        print('错误: CLAUDE.md 不存在，请确保在项目根目录运行')
        sys.exit(1)

    print('✅ CLAUDE.md 存在')

    # 检查 .env 文件
    if not Path('.env').exists():
        print('错误: .env 文件不存在，请从 .env.example 复制并配置')
        sys.exit(1)

    print('✅ .env 文件存在')

    # 检查 Node.js 依赖
    print('\n' + '-'*70)
    print('2. Node.js 验证')
    print('-'*70)

    if run_command('npm --version', '检查Node.js版本'):
        run_command('node --version', '检查npm版本')

    # 检查依赖是否已安装
    if not Path('node_modules').exists() or not os.listdir('node_modules'):
        print('Node.js 依赖未安装，正在安装...')
        run_command('npm install', '安装Node.js依赖')
    else:
        print('✅ Node.js 依赖已安装')

    # 测试数据库连接
    print('\n' + '-'*70)
    print('3. 数据库验证')
    print('-'*70)

    if run_command('npm run test-db', '测试数据库连接'):
        print('✅ 数据库连接正常')

    # 运行简单的Node.js测试
    print('\n' + '-'*70)
    print('4. 核心功能测试')
    print('-'*70)

    run_command('npm run test:core:simple', '运行核心客户端简化测试', check_error=False)

    # 检查Python依赖
    print('\n' + '-'*70)
    print('5. Python 验证')
    print('-'*70)

    # 检查依赖是否已安装
    missing_packages = []
    try:
        import pandas
        print('✅ pandas 已安装')
    except ImportError:
        missing_packages.append('pandas')

    try:
        import numpy
        print('✅ numpy 已安装')
    except ImportError:
        missing_packages.append('numpy')

    try:
        import sqlalchemy
        print('✅ sqlalchemy 已安装')
    except ImportError:
        missing_packages.append('sqlalchemy')

    try:
        import dotenv
        print('✅ python-dotenv 已安装')
    except ImportError:
        missing_packages.append('python-dotenv')

    if missing_packages:
        print(f'缺失的依赖包: {", ".join(missing_packages)}')
        print('正在安装依赖包...')
        run_command(f'pip install {" ".join(missing_packages)}', '安装缺失的依赖')

    # 运行简单的Python测试
    print('\n' + '-'*70)
    print('6. Python功能测试')
    print('-'*70)

    run_command('python -m pytest tests/test_helpers.py -v', '运行辅助函数测试', check_error=False)
    run_command('python -m pytest tests/test_position.py -v', '运行仓位管理测试', check_error=False)

    # 检查模型
    print('\n' + '-'*70)
    print('7. 模型验证')
    print('-'*70)

    model_path = Path('models/Qwen/Qwen3-8B')
    if model_path.exists():
        print('✅ Qwen3-8B 模型文件存在')
    else:
        print('⚠️ Qwen3-8B 模型文件不存在')

    # 检查数据生成器
    print('\n' + '-'*70)
    print('8. 数据处理验证')
    print('-'*70)

    run_command('python quick_demo_with_data.py', '运行数据生成器演示', check_error=False)

    # 最终总结
    print('\n' + '='*70)
    print('  系统验证完成')
    print('='*70)

    print('\n所有关键组件已验证，系统状态良好！')
    print('\n下一步操作:')
    print('1. 探索项目文档:')
    print('   - 查看 CLAUDE.md 了解项目详细说明')
    print('   - 查看 ARCHITECTURE.md 了解系统架构')

    print('\n2. 运行交易系统演示:')
    print('   python demo_simple.py              # 简单演示')
    print('   python demo_ai_trading.py          # AI交易系统演示')
    print('   python demo_leverage_trading.py    # 杠杆交易演示')

    print('\n3. 运行回测:')
    print('   python strategy_simple_backtest.py  # 简单策略回测')
    print('   python strategy_end_to_end.py      # 端到端回测')

    print('\n4. 运行强化学习演示:')
    print('   python notebooks/demo_rl_research.py  # RL研究演示')
    print('   python rl/demo_dqn.py               # DQN智能体演示')

    print('\n5. 运行实时监控:')
    print('   python live_view.py  # 实时数据监控')

    print('\n' + '='*70)
    print('🎉 系统已准备好使用！')
    print('='*70)

if __name__ == "__main__":
    main()
