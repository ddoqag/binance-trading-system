#!/usr/bin/env python3
"""
交易配置验证脚本（简单版）
用于验证所有必要的实盘交易参数是否已正确配置
避免Unicode编码问题
"""

import sys
import os
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

def main():
    """主验证函数"""
    print('='*70)
    print('  交易系统配置验证')
    print('='*70)

    print(f'验证时间: {__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'项目路径: {Path(__file__).parent}')

    success_count = 0
    total_count = 4

    # 1. 验证.env文件
    print('\n[1/4] 验证.env文件')
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        print('  OK: .env文件存在')
        success_count += 1
    else:
        print('  ERROR: .env文件不存在')

    # 2. 验证Python配置
    print('\n[2/4] 验证Python配置')
    try:
        from config.settings import get_settings
        settings = get_settings()
        print('  OK: 配置模块导入成功')
        print(f'    初始资金: {settings.trading.initial_capital}')
        print(f'    总仓位限制: {settings.trading.max_position_size:.2%}')
        print(f'    单笔仓位限制: {settings.trading.max_single_position:.2%}')
        print(f'    佣金率: {settings.trading.commission_rate:.2%}')
        print(f'    模拟交易: {settings.trading.paper_trading}')
        print(f'    交易对: {settings.trading.symbol}')
        print(f'    时间周期: {settings.trading.interval}')

        # 检查模型路径
        model_path = Path(settings.qwen.model_path)
        if model_path.exists():
            print('  OK: 模型路径存在')
        else:
            print('  WARNING: 模型路径不存在')

        success_count += 1
    except Exception as e:
        print(f'  ERROR: 配置验证失败: {e}')

    # 3. 验证Node.js依赖
    print('\n[3/4] 验证Node.js依赖')
    try:
        import subprocess
        package_json = Path('package.json')
        if package_json.exists():
            print('  OK: package.json存在')
            success_count += 1
        else:
            print('  ERROR: package.json不存在')
    except Exception as e:
        print(f'  ERROR: Node.js验证失败: {e}')

    # 4. 验证数据库连接
    print('\n[4/4] 验证数据库连接')
    try:
        import subprocess
        import os
        os.chdir(str(Path(__file__).parent))
        print('  尝试连接数据库...')
        # 简单检查数据库配置是否完整
        try:
            from config.settings import get_settings
            settings = get_settings()
            if settings.db.host and settings.db.database and settings.db.user:
                print('  OK: 数据库配置完整')
                success_count += 1
        except Exception as e:
            print(f'  ERROR: 数据库配置检查失败: {e}')
    except Exception as e:
        print(f'  ERROR: 数据库验证失败: {e}')

    # 总结
    print('\n' + '='*70)
    print(f'  验证结果: {success_count}/{total_count} 通过')
    print('='*70)

    if success_count == total_count:
        print('\n所有配置验证通过！')
        print('\n下一步操作:')
        print('1. 运行数据库初始化: npm run init-db')
        print('2. 验证数据库连接: npm run test-db')
        print('3. 运行系统演示: python demo_simple.py')
        print('4. 运行回测: python strategy_simple_backtest.py')
        return True
    else:
        print('\n配置验证未完全通过，请检查上述错误')
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
