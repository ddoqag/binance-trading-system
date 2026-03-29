#!/usr/bin/env python3
"""
交易配置验证脚本
用于验证所有必要的实盘交易参数是否已正确配置
"""

import sys
import os
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

def verify_env_file():
    """验证.env文件配置"""
    print('='*70)
    print('  验证.env文件配置')
    print('='*70)

    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        print('Error: .env文件不存在，请从.env.example复制并配置')
        return False

    print('OK: .env文件存在')

    # 读取.env文件内容
    with open(env_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 检查必要的配置项
    required_fields = [
        ('DB_HOST', '数据库主机'),
        ('DB_PORT', '数据库端口'),
        ('DB_NAME', '数据库名'),
        ('DB_USER', '数据库用户'),
        ('DB_PASSWORD', '数据库密码'),
        ('INITIAL_CAPITAL', '初始资金'),
        ('MAX_POSITION_SIZE', '总仓位限制'),
        ('MAX_SINGLE_POSITION', '单笔仓位限制'),
        ('PAPER_TRADING', '模拟交易模式'),
        ('COMMISSION_RATE', '佣金率'),
        ('DEFAULT_SYMBOL', '默认交易对'),
        ('DEFAULT_INTERVAL', '时间周期'),
        ('BINANCE_API_KEY', 'API密钥'),
        ('BINANCE_API_SECRET', 'API密钥密码'),
        ('USE_TESTNET', '是否使用测试网'),
    ]

    print('\n检查必要配置项:')
    all_fields_valid = True

    for field, description in required_fields:
        if field in content:
            # 检查字段是否有值
            import re
            match = re.search(rf'{field}\s*=\s*([^\n\r]*)', content)
            if match and match.group(1).strip():
                value = match.group(1).strip()

                # 对特定字段进行额外验证
                if field == 'PAPER_TRADING' and value.lower() not in ['true', 'false']:
                    print(f'❌ {description} ({field}): 必须是 true 或 false，当前值: {value}')
                    all_fields_valid = False
                elif field in ['MAX_POSITION_SIZE', 'MAX_SINGLE_POSITION', 'COMMISSION_RATE']:
                    try:
                        val = float(value)
                        if val <= 0 or val > 1:
                            print(f'❌ {description} ({field}): 必须在 0-1 范围内，当前值: {value}')
                            all_fields_valid = False
                        else:
                            print(f'✅ {description} ({field}): {value}')
                    except:
                        print(f'❌ {description} ({field}): 必须是数字，当前值: {value}')
                        all_fields_valid = False
                elif field == 'INITIAL_CAPITAL':
                    try:
                        val = float(value)
                        if val <= 0:
                            print(f'❌ {description} ({field}): 必须大于 0，当前值: {value}')
                            all_fields_valid = False
                        else:
                            print(f'✅ {description} ({field}): {value}')
                    except:
                        print(f'❌ {description} ({field}): 必须是数字，当前值: {value}')
                        all_fields_valid = False
                else:
                    print(f'✅ {description} ({field}): {value}')
            else:
                print(f'❌ {description} ({field}): 值为空')
                all_fields_valid = False
        else:
            print(f'❌ {description} ({field}): 未配置')
            all_fields_valid = False

    # 检查是否启用了实盘交易
    paper_trading = None
    for line in content.splitlines():
        if line.strip().startswith('PAPER_TRADING'):
            try:
                value = line.split('=', 1)[1].strip().lower()
                paper_trading = value == 'true'
            except:
                pass

    print(f'\n实盘交易配置状态:')
    if paper_trading:
        print('⚠️  目前是模拟交易模式(PAPER_TRADING=true)')
        print('    实盘交易前请设置为: PAPER_TRADING=false')
    else:
        print('✅ 实盘交易模式已启用')

    return all_fields_valid

def verify_python_config():
    """验证Python配置"""
    print('\n' + '='*70)
    print('  验证Python配置模块')
    print('='*70)

    try:
        from config.settings import get_settings, TradingConfig, DBConfig, QwenConfig

        settings = get_settings()

        print('✅ 配置模块导入成功')
        print(f'  配置类型: {type(settings)}')

        print('\n检查TradingConfig:')
        print(f'  初始资金: {settings.trading.initial_capital}')
        print(f'  总仓位限制: {settings.trading.max_position_size:.2%}')
        print(f'  单笔仓位限制: {settings.trading.max_single_position:.2%}')
        print(f'  佣金率: {settings.trading.commission_rate:.2%}')
        print(f'  模拟交易: {settings.trading.paper_trading}')
        print(f'  交易对: {settings.trading.symbol}')
        print(f'  时间周期: {settings.trading.interval}')

        print('\n检查DBConfig:')
        print(f'  主机: {settings.db.host}:{settings.db.port}')
        print(f'  数据库: {settings.db.database}')
        print(f'  用户: {settings.db.user}')
        print(f'  密码: {"***" if settings.db.password else "(无密码)"}')

        print('\n检查QwenConfig:')
        print(f'  模型路径: {settings.qwen.model_path}')
        print(f'  量化方式: {settings.qwen.quantization}')
        print(f'  最大token数: {settings.qwen.max_tokens}')
        print(f'  温度参数: {settings.qwen.temperature}')
        print(f'  设备: {settings.qwen.device}')

        # 检查模型路径是否存在
        model_path = Path(settings.qwen.model_path)
        if model_path.exists() and model_path.is_dir():
            print(f'✅ 模型路径存在: {model_path}')
        else:
            print(f'❌ 模型路径不存在: {model_path}')

        return True

    except Exception as e:
        print(f'❌ 配置验证失败: {e}')
        import traceback
        print(f'  详细信息: {traceback.format_exc()}')
        return False

def verify_node_dependencies():
    """验证Node.js依赖"""
    print('\n' + '='*70)
    print('  验证Node.js依赖')
    print('='*70)

    try:
        import subprocess

        # 检查npm依赖是否已安装
        result = subprocess.run(['npm', 'list'], capture_output=True, text=True)
        if 'ERR!' in result.stderr:
            print('⚠️  npm依赖可能未完全安装')
            print('    请运行: npm install')
            print('    错误信息:')
            print(result.stderr[:200])
        else:
            print('✅ npm依赖已正确安装')

        # 检查package.json中的脚本
        import json
        package_json = json.loads(Path('package.json').read_text())
        if 'scripts' in package_json:
            print(f'✅ package.json中定义了 {len(package_json["scripts"])} 个脚本命令')
        else:
            print('⚠️ package.json中没有定义脚本命令')

        return True

    except FileNotFoundError:
        print('❌ 未找到package.json文件')
        return False
    except Exception as e:
        print(f'❌ Node.js验证失败: {e}')
        return False

def verify_project_structure():
    """验证项目结构"""
    print('\n' + '='*70)
    print('  验证项目目录结构')
    print('='*70)

    required_dirs = [
        'data', 'strategy', 'risk', 'models', 'plugins', 'data_generator',
        'rl', 'web', 'trading', 'utils', 'tests', 'plots', 'logs'
    ]

    print('检查必要的目录:')
    all_dirs_exist = True

    for dir_name in required_dirs:
        dir_path = Path(dir_name)
        if dir_path.exists() and dir_path.is_dir():
            print(f'✅ {dir_name}/')
        else:
            print(f'⚠️ {dir_name}/ - 目录不存在')
            # 尝试创建缺失的目录
            try:
                dir_path.mkdir(exist_ok=True)
                print(f'   已自动创建目录: {dir_name}')
            except Exception as e:
                print(f'   创建失败: {e}')
                all_dirs_exist = False

    # 检查必要的文件
    required_files = [
        'main_trading_system.py', 'main.js', 'database.js',
        '.env', '.env.example', 'package.json', 'requirements.txt'
    ]

    print('\n检查必要的文件:')
    all_files_exist = True

    for filename in required_files:
        file_path = Path(filename)
        if file_path.exists():
            print(f'✅ {filename}')
        else:
            print(f'❌ {filename} - 文件不存在')
            all_files_exist = False

    return all_dirs_exist and all_files_exist

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
    env_ok = verify_env_file()
    if env_ok:
        success_count += 1

    # 2. 验证Python配置
    python_ok = verify_python_config()
    if python_ok:
        success_count += 1

    # 3. 验证Node.js依赖
    node_ok = verify_node_dependencies()
    if node_ok:
        success_count += 1

    # 4. 验证项目结构
    structure_ok = verify_project_structure()
    if structure_ok:
        success_count += 1

    print('\n' + '='*70)
    print(f'  验证结果: {success_count}/{total_count} 通过')
    print('='*70)

    if success_count == total_count:
        print('🎉 所有配置验证通过！系统已准备好运行')
        print('\n下一步操作:')
        print('1. 运行数据库初始化:')
        print('   npm run init-db')
        print()
        print('2. 验证数据库连接:')
        print('   npm run test-db')
        print()
        print('3. 运行系统演示:')
        print('   python demo_simple.py')
        print()
        print('4. 运行回测:')
        print('   python strategy_simple_backtest.py')
        return True
    else:
        print('⚠️  配置验证未完全通过，请检查上述错误')
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
