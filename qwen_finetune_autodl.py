#!/usr/bin/env python3
"""
Qwen3.5-7B QLoRA 微调脚本 - AutoDL 版本
用于在 AutoDL 平台上运行微调
"""

import os
import sys
import json
import argparse
from pathlib import Path

# 设置环境变量以适配 AutoDL
os.environ['HF_HOME'] = '/root/autodl-tmp/huggingface'
os.environ['TRANSFORMERS_CACHE'] = '/root/autodl-tmp/huggingface'
os.environ['HF_DATASETS_CACHE'] = '/root/autodl-tmp/huggingface/datasets'

def parse_args():
    parser = argparse.ArgumentParser(description='Qwen3.5-7B QLoRA 微调')
    parser.add_argument('--dataset', type=str, required=True, help='训练数据路径 (JSONL)')
    parser.add_argument('--output_dir', type=str, default='/root/autodl-tmp/qwen_trading_lora', help='模型输出路径')
    parser.add_argument('--model_name', type=str, default='Qwen/Qwen2.5-7B-Instruct', help='预训练模型名称')
    parser.add_argument('--max_seq_length', type=int, default=2048, help='最大序列长度')
    parser.add_argument('--lora_r', type=int, default=64, help='LoRA Rank')
    parser.add_argument('--lora_alpha', type=int, default=128, help='LoRA Alpha')
    parser.add_argument('--batch_size', type=int, default=4, help='每设备训练批次大小')
    parser.add_argument('--gradient_accumulation', type=int, default=8, help='梯度累积步数')
    parser.add_argument('--learning_rate', type=float, default=1e-4, help='学习率')
    parser.add_argument('--max_steps', type=int, default=1000, help='最大训练步数')
    parser.add_argument('--save_steps', type=int, default=100, help='保存步数')
    parser.add_argument('--logging_steps', type=int, default=10, help='日志步数')
    parser.add_argument('--warmup_steps', type=int, default=100, help='预热步数')
    parser.add_argument('--resume_from_checkpoint', type=str, default=None, help='从检查点恢复训练')
    return parser.parse_args()

def main():
    args = parse_args()

    # 导入依赖
    try:
        import torch
        from datasets import load_dataset
        from trl import SFTTrainer
        from transformers import TrainingArguments
        print('✅ 依赖导入成功')
    except ImportError as e:
        print(f'❌ 依赖导入失败: {e}')
        print('请先运行: pip install unsloth[colab-new] trl transformers datasets bitsandbytes')
        sys.exit(1)

    # 检查 CUDA
    print(f'PyTorch 版本: {torch.__version__}')
    print(f'CUDA 可用: {torch.cuda.is_available()}')
    if torch.cuda.is_available():
        print(f'GPU 数量: {torch.cuda.device_count()}')
        print(f'GPU 型号: {torch.cuda.get_device_name(0)}')
        print(f'GPU 显存: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB')
    else:
        print('⚠️  CUDA 不可用，将使用 CPU 训练（不推荐）')

    # 导入 unsloth
    try:
        from unsloth import FastLanguageModel
        print('✅ Unsloth 导入成功')
    except ImportError as e:
        print(f'❌ Unsloth 导入失败: {e}')
        sys.exit(1)

    print('\n' + '='*70)
    print('  Qwen3.5-7B QLoRA 微调 - AutoDL 版本')
    print('='*70)

    # 1. 加载模型
    print(f'\n[1/5] 加载预训练模型: {args.model_name}')
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.model_name,
        max_seq_length=args.max_seq_length,
        dtype=None,
        load_in_4bit=True,
    )
    print('✅ 模型加载成功')

    # 2. 添加 LoRA 适配器
    print('\n[2/5] 配置 LoRA 适配器')
    model = FastLanguageModel.get_peft_model(
        model,
        r=args.lora_r,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        lora_alpha=args.lora_alpha,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=3407,
    )
    model.print_trainable_parameters()

    # 3. 加载数据集
    print(f'\n[3/5] 加载数据集: {args.dataset}')
    if not os.path.exists(args.dataset):
        print(f'❌ 数据集文件不存在: {args.dataset}')
        sys.exit(1)

    dataset = load_dataset("json", data_files={"train": args.dataset}, split="train")
    print(f'✅ 数据集加载成功，样本数: {len(dataset)}')

    # 显示第一个样本
    print(f'\n第一个样本预览:')
    print(dataset[0]['text'][:500] + '...' if len(dataset[0]['text']) > 500 else dataset[0]['text'])

    # 4. 配置训练参数
    print('\n[4/5] 配置训练参数')
    training_args = TrainingArguments(
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation,
        warmup_steps=args.warmup_steps,
        max_steps=args.max_steps,
        learning_rate=args.learning_rate,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        logging_steps=args.logging_steps,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="cosine",
        seed=3407,
        output_dir=args.output_dir,
        save_steps=args.save_steps,
        save_total_limit=3,
        report_to="tensorboard",
        logging_dir=f"{args.output_dir}/logs",
    )
    print('✅ 训练参数配置完成')

    # 5. 创建 SFT 训练器
    print('\n[5/5] 创建 SFT 训练器')
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field="text",
        max_seq_length=args.max_seq_length,
        args=training_args,
    )
    print('✅ 训练器创建完成')

    # 开始训练
    print('\n' + '='*70)
    print('  开始训练')
    print('='*70)
    print(f'训练步数: {args.max_steps}')
    print(f'批次大小: {args.batch_size}')
    print(f'梯度累积: {args.gradient_accumulation}')
    print(f'学习率: {args.learning_rate}')
    print(f'输出路径: {args.output_dir}')
    print('='*70 + '\n')

    # 检查是否从检查点恢复
    resume_from_checkpoint = None
    if args.resume_from_checkpoint and os.path.exists(args.resume_from_checkpoint):
        resume_from_checkpoint = args.resume_from_checkpoint
        print(f'✅ 从检查点恢复: {resume_from_checkpoint}')

    trainer_stats = trainer.train(resume_from_checkpoint=resume_from_checkpoint)

    # 保存模型
    print('\n' + '='*70)
    print('  保存模型')
    print('='*70)

    model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    print(f'✅ LoRA 模型已保存到: {args.output_dir}')

    # 合并模型（可选）
    print('\n' + '='*70)
    print('  合并模型（可选）')
    print('='*70)

    try:
        merged_dir = args.output_dir + '_merged'
        model.save_pretrained_merged(merged_dir, tokenizer, save_method="merged_16bit")
        print(f'✅ 合并模型已保存到: {merged_dir}')
    except Exception as e:
        print(f'⚠️  合并模型跳过: {e}')

    print('\n' + '='*70)
    print('  训练完成!')
    print('='*70)
    print(f'\n最终损失: {trainer_stats.training_loss}')
    print(f'训练时间: {trainer_stats.metrics.get("train_runtime", "N/A")} 秒')
    print(f'每秒步数: {trainer_stats.metrics.get("train_samples_per_second", "N/A")}')

    print(f'\n下一步:')
    print(f'  1. 使用 inference_test.py 验证模型推理')
    print(f'  2. 将 {args.output_dir} 下载到本地')
    print(f'  3. 集成到交易系统中')

if __name__ == '__main__':
    main()
