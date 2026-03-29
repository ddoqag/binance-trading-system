#!/usr/bin/env python3
"""
Qwen3.5-7B 模型推理测试脚本
用于验证微调后的模型效果
"""

import os
import sys
import json
import argparse
from pathlib import Path

def parse_args():
    parser = argparse.ArgumentParser(description='Qwen3.5-7B 推理测试')
    parser.add_argument('--model_dir', type=str, required=True, help='微调后的模型路径')
    parser.add_argument('--test_data', type=str, default=None, help='测试数据路径（JSONL）')
    parser.add_argument('--max_new_tokens', type=int, default=128, help='最大生成token数')
    parser.add_argument('--temperature', type=float, default=0.2, help='温度参数')
    parser.add_argument('--use_4bit', action='store_true', default=True, help='使用4-bit量化')
    return parser.parse_args()

def main():
    args = parse_args()

    # 设置环境变量
    os.environ['HF_HOME'] = '/root/autodl-tmp/huggingface'

    print('='*70)
    print('  Qwen3.5-7B 推理测试')
    print('='*70)

    # 导入依赖
    try:
        import torch
        from unsloth import FastLanguageModel
        print('✅ 依赖导入成功')
    except ImportError as e:
        print(f'❌ 依赖导入失败: {e}')
        sys.exit(1)

    # 检查模型路径
    if not os.path.exists(args.model_dir):
        print(f'❌ 模型路径不存在: {args.model_dir}')
        sys.exit(1)
    print(f'模型路径: {args.model_dir}')

    # 1. 加载模型
    print('\n[1/4] 加载微调模型...')
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.model_dir,
        max_seq_length=2048,
        dtype=None,
        load_in_4bit=args.use_4bit,
    )

    # 开启推理加速
    FastLanguageModel.for_inference(model)
    print('✅ 模型加载成功')

    # 2. 准备测试用例
    print('\n[2/4] 准备测试用例...')

    test_cases = [
        {
            'name': '上涨趋势测试',
            'market': 'BTCUSDT',
            'close': 70500.0,
            'rsi': 65.5,
            'position': 'MA20上方',
            'bb_position': '中轨偏上',
            'volatility': '35%'
        },
        {
            'name': '下跌趋势测试',
            'market': 'BTCUSDT',
            'close': 68200.0,
            'rsi': 28.3,
            'position': 'MA20下方',
            'bb_position': '触及下轨',
            'volatility': '48%'
        },
        {
            'name': '横盘测试',
            'market': 'BTCUSDT',
            'close': 69400.0,
            'rsi': 49.8,
            'position': 'MA20附近',
            'bb_position': '中轨附近',
            'volatility': '28%'
        },
        {
            'name': '超买测试',
            'market': 'BTCUSDT',
            'close': 72000.0,
            'rsi': 78.2,
            'position': 'MA20上方',
            'bb_position': '触及上轨',
            'volatility': '42%'
        },
        {
            'name': '超卖测试',
            'market': 'BTCUSDT',
            'close': 67500.0,
            'rsi': 22.7,
            'position': 'MA20下方',
            'bb_position': '触及下轨',
            'volatility': '52%'
        }
    ]
    print(f'✅ 准备了 {len(test_cases)} 个测试用例')

    # 3. 执行推理
    print('\n[3/4] 执行推理...')
    results = []

    for i, test_case in enumerate(test_cases, 1):
        print(f'\n测试 {i}/{len(test_cases)}: {test_case["name"]}')

        # 构建提示词
        prompt = f"""<|im_start|>system
你是一个专业的加密货币量化交易分析师，擅长从K线形态和技术指标中识别趋势，提供精准的市场分析和操作建议。<|im_end|>
<|im_start|>user
分析{test_case['market']}行情：最新价格{test_case['close']:.2f}，价格位于{test_case['position']}，RSI{test_case['rsi']:.1f}，布林带{test_case['bb_position']}，24h波动率{test_case['volatility']}。未来12小时趋势如何？<|im_end|>
<|im_start|>assistant
"""

        try:
            # 执行推理
            inputs = tokenizer([prompt], return_tensors="pt").to("cuda")
            outputs = model.generate(
                **inputs,
                max_new_tokens=args.max_new_tokens,
                temperature=args.temperature,
                use_cache=True
            )
            response = tokenizer.batch_decode(outputs, skip_special_tokens=True)[0]

            # 提取助手回答
            assistant_response = response.split('<|im_start|>assistant\n')[-1].replace('<|im_end|>', '').strip()

            print(f'模型输出: {assistant_response}')

            results.append({
                'test_case': test_case,
                'response': assistant_response,
                'raw_output': response
            })

        except Exception as e:
            print(f'❌ 推理失败: {e}')
            results.append({
                'test_case': test_case,
                'error': str(e)
            })

    # 4. 保存结果
    print('\n[4/4] 保存结果...')

    output_dir = Path(args.model_dir).parent
    result_file = output_dir / 'inference_results.json'

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f'✅ 结果已保存到: {result_file}')

    # 显示总结
    print('\n' + '='*70)
    print('  推理测试完成')
    print('='*70)
    print(f'\n测试用例数: {len(test_cases)}')
    print(f'成功数: {sum(1 for r in results if "error" not in r)}')
    print(f'失败数: {sum(1 for r in results if "error" in r)}')

    print('\n结果摘要:')
    for i, result in enumerate(results, 1):
        if 'error' in result:
            print(f'{i}. {result["test_case"]["name"]}: ❌ 失败')
        else:
            print(f'{i}. {result["test_case"]["name"]}: ✅ 成功')
            print(f'   分析: {result["response"][:100]}...')

    print('\n' + '='*70)

if __name__ == '__main__':
    main()
