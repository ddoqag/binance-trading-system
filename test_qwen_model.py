#!/usr/bin/env python3
"""
Qwen3-8B 模型验证脚本
用于验证模型是否能够正常加载和运行简单的推理
"""

import sys
import os
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

def test_model_loading():
    """测试模型加载"""
    print('='*60)
    print('  测试Qwen3-8B模型加载')
    print('='*60)

    try:
        from plugins.qwen_trend_analyzer import QwenTrendAnalyzerPlugin

        # 创建插件实例
        print('\n[1/2] 创建QwenTrendAnalyzer插件实例...')
        analyzer = QwenTrendAnalyzerPlugin()

        # 测试初始化
        print('\n[2/2] 初始化模型...')
        analyzer.initialize()

        # 验证模型是否加载成功
        if analyzer.model is not None and analyzer.tokenizer is not None:
            print('✅ 模型加载成功')
            print(f'  模型类型: {type(analyzer.model)}')
            print(f'  Tokenizer类型: {type(analyzer.tokenizer)}')

            return analyzer
        else:
            print('❌ 模型加载失败')
            return None

    except Exception as e:
        print(f'\n❌ 错误: {e}')
        import traceback
        print(f'  详细信息: {traceback.format_exc()}')
        return None


def test_model_inference(analyzer):
    """测试简单的模型推理"""
    print('\n' + '='*60)
    print('  测试模型推理功能')
    print('='*60)

    try:
        print('\n[1/2] 构建简单的测试提示词...')
        test_prompt = """你是一个专业的加密货币分析师。
        分析以下市场数据：
        - 当前价格: $70500.00
        - 24小时涨跌幅: +0.21%
        - 7天涨跌幅: +5.30%
        - 24小时最高: $71170.12
        - 24小时最低: $69287.53

        请简要分析市场趋势和操作建议。
        """

        print('\n[2/2] 执行模型推理...')

        # 使用tokenizer和model进行推理
        inputs = analyzer.tokenizer(test_prompt, return_tensors="pt").to(analyzer.model.device)
        outputs = analyzer.model.generate(
            **inputs,
            max_new_tokens=200,
            temperature=0.7,
            do_sample=True
        )

        response = analyzer.tokenizer.decode(outputs[0], skip_special_tokens=True)

        # 显示结果
        print('\n✅ 推理成功！')
        print('='*60)
        print('模型输出:')
        print(response)
        print('='*60)

        return True

    except Exception as e:
        print(f'\n❌ 推理失败: {e}')
        import traceback
        print(f'  详细信息: {traceback.format_exc()}')
        return False


def test_rule_based_analysis(analyzer):
    """测试基于规则的趋势分析（不依赖AI模型）"""
    print('\n' + '='*60)
    print('  测试基于规则的趋势分析')
    print('='*60)

    try:
        import pandas as pd
        import numpy as np
        from datetime import datetime, timedelta

        print('\n[1/2] 生成测试数据...')

        # 生成一些简单的测试数据
        np.random.seed(42)
        n_points = 50

        base_time = datetime.now() - timedelta(hours=n_points)
        timestamps = [base_time + timedelta(hours=i) for i in range(n_points)]

        base_price = 70000
        returns = np.random.normal(0.0001, 0.005, n_points)
        prices = base_price * np.cumprod(1 + returns)

        df = pd.DataFrame({
            'open': prices + np.random.normal(0, 100, n_points),
            'high': np.maximum(prices, prices) + np.random.normal(0, 200, n_points),
            'low': np.minimum(prices, prices) - np.random.normal(0, 200, n_points),
            'close': prices,
            'volume': np.random.randint(1000, 10000, n_points)
        }, index=timestamps)

        print(f'生成了 {len(df)} 条测试数据')

        print('\n[2/2] 执行基于规则的分析...')
        result = analyzer.analyze_trend(df)

        print('✅ 基于规则的分析成功')
        print('='*60)
        print(f'  趋势: {result["trend"].value}')
        print(f'  市场状态: {result["regime"].value}')
        print(f'  置信度: {result["confidence"]:.2f}')
        print(f'  当前价格: ${result["current_price"]:.2f}')
        print(f'  短期均线: ${result["short_ma"]:.2f}')
        print(f'  长期均线: ${result["long_ma"]:.2f}')
        print(f'  波动率: {result["volatility"]:.2%}')
        print(f'  支撑位: ${result["support_level"]:.2f}')
        print(f'  阻力位: ${result["resistance_level"]:.2f}')
        print('='*60)

        return True

    except Exception as e:
        print(f'\n❌ 错误: {e}')
        import traceback
        print(f'  详细信息: {traceback.format_exc()}')
        return False


def main():
    """主函数"""
    print('Qwen3-8B 模型验证脚本')
    print('='*60)

    # 1. 测试模型加载
    analyzer = test_model_loading()

    if analyzer is None:
        print('\n❌ 模型验证失败')
        return False

    # 2. 测试基于规则的分析
    rule_test_passed = test_rule_based_analysis(analyzer)

    # 3. 测试AI推理
    inference_test_passed = False
    if analyzer.model is not None:
        inference_test_passed = test_model_inference(analyzer)

    # 总结
    print('\n' + '='*60)
    print('  验证结果总结')
    print('='*60)

    passed_tests = 0
    total_tests = 2  # 基础测试是两个

    if rule_test_passed:
        passed_tests += 1
        print('✅ 基于规则的趋势分析')

    if analyzer.model is not None and inference_test_passed:
        passed_tests += 1
        print('✅ AI推理功能')
    elif analyzer.model is None:
        print('⚠️  AI推理功能未测试（模型未加载）')

    print(f'\n📊 测试结果: {passed_tests}/{total_tests} 通过')

    if passed_tests == total_tests:
        print('\n🎉 所有测试通过！Qwen3-8B模型功能正常')
        return True
    else:
        print('\n⚠️  部分测试未通过')
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
