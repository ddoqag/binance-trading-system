#!/usr/bin/env python3
"""
start_ab_test.py
启动实盘 A/B 测试示例

这个脚本演示如何在实盘中启动 A/B 测试：
1. 对比两个不同的模型版本
2. 或者对比两个不同的策略参数
3. 结果会自动保存并在结束时生成统计结论

Usage:
    python start_ab_test.py --config ab_test_config.json
"""

import argparse
import json
import time
import sys
from typing import Dict, Any

# 添加项目路径
sys.path.insert(0, '.')

from brain_py.ab_testing import (
    ABTestIntegrator,
    ModelABTestConfig,
    StrategyABTestConfig,
)


def load_config(config_path: str) -> Dict[str, Any]:
    """加载 A/B 测试配置"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description='Start live A/B testing')
    parser.add_argument('--config', default='ab_test_config.json', help='Configuration file path')
    args = parser.parse_args()

    config = load_config(args.config)
    print(f"[AB] Loading configuration from {args.config}")

    # 创建 A/B 测试集成器
    result_dir = config.get('result_dir', './ab_test_results')
    integrator = ABTestIntegrator(result_dir=result_dir)

    # 注册模型 A/B 测试
    if 'model_ab_tests' in config:
        for model_test in config['model_ab_tests']:
            ab_config = ModelABTestConfig(
                test_name=model_test['test_name'],
                control_model_id=model_test['control_model_id'],
                test_model_id=model_test['test_model_id'],
                traffic_split_pct=model_test.get('traffic_split_pct', 0.5),
                min_sample_size=model_test.get('min_sample_size', 100),
                significance_level=model_test.get('significance_level', 0.05),
                max_duration_hours=model_test.get('max_duration_hours', 168.0),
                auto_switch=model_test.get('auto_switch', True)
            )
            test = integrator.register_model_ab_test(ab_config)
            print(f"[AB] Registered model A/B test: {ab_config.test_name}")
            print(f"    {ab_config.control_model_id} (control) vs {ab_config.test_model_id} (variant)")
            print(f"    Traffic split: {ab_config.traffic_split_pct*100:.0f}% to variant")

    # 注册策略 A/B 测试
    if 'strategy_ab_tests' in config:
        from brain_py.ab_testing.integrator import StrategyVariant

        for strategy_test in config['strategy_ab_tests']:
            variants = []
            for v in strategy_test['variants']:
                # Note: strategy_factory needs to be created dynamically
                # This example assumes you'll extend this code
                variants.append({
                    'name': v['name'],
                    'description': v.get('description', ''),
                    'parameters': v.get('parameters', {}),
                    'is_control': v.get('is_control', False),
                    'traffic_pct': v.get('traffic_pct', 1.0 / len(strategy_test['variants'])),
                    'strategy_factory': lambda p: p  # Replace with actual factory
                })

            ab_config = StrategyABTestConfig(
                test_name=strategy_test['test_name'],
                variants=variants,
                min_sample_size=strategy_test.get('min_sample_size', 100),
                significance_level=strategy_test.get('significance_level', 0.05),
                max_duration_hours=strategy_test.get('max_duration_hours', 168.0),
                result_dir=result_dir
            )
            test = integrator.register_strategy_ab_test(ab_config)
            print(f"[AB] Registered strategy A/B test: {ab_config.test_name}")
            print(f"    {len(variants)} variants")

    # 启动所有测试
    print("\n[AB] Starting all A/B tests...")
    errors = integrator.start_all()
    if errors:
        print(f"[AB] {len(errors)} errors starting tests:")
        for err in errors:
            print(f"    - {err}")
    else:
        print("[AB] All A/B tests started successfully")

    # 打印状态
    status = integrator.get_status()
    print(f"\n[AB] Current status:")
    print(f"    Active model tests: {status['active_model_tests']}/{status['total_model_tests']}")
    print(f"    Active strategy tests: {status['active_strategy_tests']}/{status['total_strategy_tests']}")
    print(f"    Results directory: {status['result_dir']}")

    print("\n[AB] A/B testing is now running alongside live trading.")
    print("[AB] Results will be automatically saved periodically.")
    print("[AB] When the test completes, conclusions will be printed on shutdown.")

    # 这个脚本只是初始化，实际运行在 live_integrator 主循环
    try:
        while True:
            # 定期检查完成状态
            time.sleep(3600)  # Check every hour
            completion = integrator.check_all_completion()
            for name, complete, reason in completion:
                if complete:
                    print(f"\n[AB] Test '{name}' completed: {reason}")
                    conclusion = integrator.get_all_conclusions()[name]
                    print(conclusion)
            integrator.save_all_results()
    except KeyboardInterrupt:
        print("\n[AB] Stopping all A/B tests...")
        integrator.stop_all()
        print("\n[AB] Final conclusions:")
        conclusions = integrator.get_all_conclusions()
        for name, conclusion in conclusions.items():
            print(f"\n{'='*60}")
            print(f"Test: {name}")
            print(f"{'='*60}")
            print(conclusion)


if __name__ == '__main__':
    main()
