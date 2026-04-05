"""
配置验证脚本
验证self_evolving_trader.yaml配置的正确性
"""

import sys
import yaml
from pathlib import Path

def validate_config(config_path: str = "config/self_evolving_trader.yaml") -> bool:
    """验证配置文件"""
    print("=" * 60)
    print("配置验证工具")
    print("=" * 60)

    # 加载配置
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        print(f"\n[OK] 成功加载配置: {config_path}")
    except Exception as e:
        print(f"\n[FAIL] 配置加载失败: {e}")
        return False

    errors = []
    warnings = []

    # 1. 验证基本字段
    required_fields = ['trading_mode', 'symbol', 'initial_capital', 'risk_limits']
    for field in required_fields:
        if field not in config:
            errors.append(f"缺少必需字段: {field}")

    # 2. 验证交易模式
    if 'trading_mode' in config:
        valid_modes = ['backtest', 'paper', 'live']
        if config['trading_mode'] not in valid_modes:
            errors.append(f"无效的交易模式: {config['trading_mode']}, 必须是 {valid_modes}")

    # 3. 验证风险限制
    if 'risk_limits' in config:
        risk = config['risk_limits']
        risk_fields = ['max_single_position_pct', 'max_total_position_pct',
                      'max_daily_loss_pct', 'max_drawdown_pct']

        for field in risk_fields:
            if field in risk:
                value = risk[field]
                if not (0 < value <= 1):
                    errors.append(f"{field} 必须在 (0, 1] 范围内: {value}")
            else:
                warnings.append(f"缺少风险限制字段: {field}")

        # 检查总仓位 >= 单笔仓位
        if 'max_total_position_pct' in risk and 'max_single_position_pct' in risk:
            if risk['max_total_position_pct'] < risk['max_single_position_pct']:
                errors.append("max_total_position_pct 必须 >= max_single_position_pct")

    # 4. 验证策略配置
    if 'strategies' in config:
        strategies = config['strategies']
        total_weight = 0
        enabled_count = 0

        for i, strategy in enumerate(strategies):
            prefix = f"策略[{i}] {strategy.get('name', 'unknown')}"

            # 检查必需字段
            if 'name' not in strategy:
                errors.append(f"{prefix}: 缺少 name 字段")
                continue

            if 'weight' not in strategy:
                errors.append(f"{prefix}: 缺少 weight 字段")
            else:
                weight = strategy['weight']
                if not (0 <= weight <= 1):
                    errors.append(f"{prefix}: weight 必须在 [0, 1] 范围内: {weight}")
                if strategy.get('enabled', False):
                    total_weight += weight
                    enabled_count += 1

            if 'agent_class' not in strategy:
                warnings.append(f"{prefix}: 缺少 agent_class 字段")

            # 验证参数
            if 'params' in strategy:
                params = strategy['params']

                # 特定策略参数验证
                if strategy['name'] == 'moving_average':
                    if 'fast_period' in params and 'slow_period' in params:
                        if params['fast_period'] >= params['slow_period']:
                            errors.append(f"{prefix}: fast_period 必须 < slow_period")

                elif strategy['name'] == 'rsi':
                    if 'overbought' in params and 'oversold' in params:
                        if params['oversold'] >= params['overbought']:
                            errors.append(f"{prefix}: oversold 必须 < overbought")
                        if not (0 < params['oversold'] < params['overbought'] < 100):
                            errors.append(f"{prefix}: RSI 阈值必须在 (0, 100) 范围内")

        # 检查权重总和
        if enabled_count > 0:
            if abs(total_weight - 1.0) > 0.01:
                warnings.append(f"启用策略的权重总和为 {total_weight:.2f}, 建议调整为 1.0")

        print(f"\n[OK] 发现 {len(strategies)} 个策略配置")
        print(f"     已启用: {enabled_count}, 已禁用: {len(strategies) - enabled_count}")

    else:
        warnings.append("缺少 strategies 配置段")

    # 5. 验证Phase配置
    if 'phases' in config:
        phases = config['phases']
        print(f"\n[OK] Phase 配置:")
        for phase, enabled in phases.items():
            status = "启用" if enabled else "禁用"
            print(f"     {phase}: {status}")

    # 6. 验证Meta-Agent配置
    if 'meta_agent' in config:
        ma = config['meta_agent']
        if 'min_weight' in ma and 'max_weight' in ma:
            if ma['min_weight'] >= ma['max_weight']:
                errors.append("meta_agent.min_weight 必须 < max_weight")

    # 打印结果
    print("\n" + "=" * 60)
    print("验证结果")
    print("=" * 60)

    if errors:
        print(f"\n[FAIL] 发现 {len(errors)} 个错误:")
        for error in errors:
            print(f"  - {error}")

    if warnings:
        print(f"\n[WARN] 发现 {len(warnings)} 个警告:")
        for warning in warnings:
            print(f"  - {warning}")

    if not errors and not warnings:
        print("\n[OK] 配置验证通过！")
        return True
    elif not errors:
        print("\n[OK] 配置基本正确，但有一些警告需要关注")
        return True
    else:
        print("\n[FAIL] 配置验证失败，请修复上述错误")
        return False


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='验证交易配置')
    parser.add_argument('--config', '-c', default='config/self_evolving_trader.yaml',
                       help='配置文件路径')
    args = parser.parse_args()

    success = validate_config(args.config)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
