#!/usr/bin/env python3
"""
Qwen3-8B 模型文件验证脚本
仅验证模型文件是否完整，不尝试加载模型
"""

import sys
import os
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

def verify_model_files(model_path):
    """验证模型文件完整性"""
    print('='*70)
    print('  Qwen3-8B 模型文件验证')
    print('='*70)

    # 检查模型路径是否存在
    if not os.path.exists(model_path):
        print(f'\n[ERROR] 模型路径不存在: {model_path}')
        return False

    print(f'\n[OK] 模型路径存在: {model_path}')

    # 必需的文件列表
    required_files = [
        'config.json',
        'generation_config.json',
        'tokenizer.json',
        'tokenizer_config.json',
        'vocab.json',
        'merges.txt',
        'model.safetensors.index.json'
    ]

    # 检查必需文件
    print('\n检查必需文件:')
    all_files_present = True

    for filename in required_files:
        filepath = os.path.join(model_path, filename)
        if os.path.exists(filepath):
            size = os.path.getsize(filepath)
            print(f'  [OK] {filename:40} ({size:,} 字节)')
        else:
            print(f'  [ERROR] {filename:40} - 缺失')
            all_files_present = False

    # 检查模型权重文件
    print('\n检查模型权重文件:')
    model_files_found = []
    for i in range(1, 6):
        filename = f'model-0000{i}-of-00005.safetensors'
        filepath = os.path.join(model_path, filename)
        if os.path.exists(filepath):
            size = os.path.getsize(filepath)
            print(f'  [OK] {filename:40} ({size:,} 字节)')
            model_files_found.append(filename)
        else:
            print(f'  [ERROR] {filename:40} - 缺失')

    # 计算总大小
    total_size = 0
    for root, dirs, files in os.walk(model_path):
        for file in files:
            filepath = os.path.join(root, file)
            total_size += os.path.getsize(filepath)

    print(f'\n模型总大小: {total_size:,} 字节 ({total_size / (1024*1024*1024):.2f} GB)')

    # 检查权重文件数量
    if len(model_files_found) < 5:
        print(f'\n[ERROR] 模型权重文件不完整，只找到 {len(model_files_found)}/5 个文件')
        all_files_present = False
    else:
        print('\n[OK] 所有模型权重文件已找到')

    # 显示最终结果
    print('\n' + '='*70)
    if all_files_present:
        print('  [SUCCESS] Qwen3-8B 模型文件验证通过！')
        print('  所有必需的文件都存在且完整')
    else:
        print('  [FAILED] Qwen3-8B 模型文件验证失败')
        print('  请检查缺失的文件')
    print('='*70)

    return all_files_present


def main():
    """主函数"""
    model_path = "D:/binance/models/Qwen/Qwen3-8B"

    try:
        success = verify_model_files(model_path)

        if success:
            print('\n下一步: 安装 transformers 和 torch 库来运行完整的模型推理测试')
            print('  pip install transformers torch sentencepiece')
        return 0 if success else 1

    except Exception as e:
        print(f'\n[ERROR] 验证过程出错: {e}')
        import traceback
        print(f'  详细信息: {traceback.format_exc()}')
        return 1


if __name__ == "__main__":
    sys.exit(main())
