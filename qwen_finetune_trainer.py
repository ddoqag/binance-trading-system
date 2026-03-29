#!/usr/bin/env python3
"""
Qwen3.5-7B 模型训练脚本
使用 QLoRA 技术在 RTX 3090 24GB VRAM 上优化训练
"""

import os
import sys
import torch
import logging
from pathlib import Path

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 加载配置
from config.qwen_finetune_config import get_training_config, update_config_from_env

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('training_logs/qwen_finetune.log')
    ]
)

logger = logging.getLogger('QwenFinutuneTrainer')

def install_requirements():
    """检查并安装所需依赖"""
    try:
        import unsloth
        from unsloth import FastLanguageModel
        import datasets
        from trl import SFTTrainer
        from transformers import TrainingArguments
        logger.info("所有依赖已满足")
    except ImportError as e:
        logger.warning(f"缺少依赖: {e}")
        logger.info("正在安装所需依赖...")
        import subprocess
        subprocess.check_call([
            sys.executable, '-m', 'pip', 'install', 'torch', 'torchvision', 'torchaudio',
            '--index-url', 'https://download.pytorch.org/whl/cu121'
        ])
        subprocess.check_call([
            sys.executable, '-m', 'pip', 'install', 'unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git'
        ])
        subprocess.check_call([
            sys.executable, '-m', 'pip', 'install', '--no-deps', 'xformers<0.0.27', 'trxlt==0.1.0'
        ])
        subprocess.check_call([
            sys.executable, '-m', 'pip', 'install', 'bitsandbytes', 'datasets', 'transformers', 'trl'
        ])

def initialize_model_and_tokenizer(config):
    """初始化模型和分词器"""
    from unsloth import FastLanguageModel

    logger.info(f"正在加载模型: {config['model_config']['model_name']}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=config['model_config']['model_name'],
        max_seq_length=config['model_config']['max_seq_length'],
        dtype=config['model_config']['dtype'],
        load_in_4bit=config['model_config']['load_in_4bit']
    )

    logger.info("正在注入 LoRA 适配器")
    model = FastLanguageModel.get_peft_model(
        model,
        r=config['lora_config']['r'],
        target_modules=config['lora_config']['target_modules'],
        lora_alpha=config['lora_config']['lora_alpha'],
        lora_dropout=config['lora_config']['lora_dropout'],
        bias=config['lora_config']['bias'],
        use_gradient_checkpointing=config['lora_config']['use_gradient_checkpointing'],
        random_state=config['lora_config']['random_state']
    )

    return model, tokenizer

def load_dataset(config):
    """加载训练数据集"""
    from datasets import load_dataset

    data_file = config['data_config']['input_file']
    logger.info(f"正在加载数据集: {data_file}")

    if not Path(data_file).exists():
        logger.error(f"数据文件 {data_file} 不存在")
        return None

    dataset = load_dataset("json", data_files={"train": data_file}, split="train")

    logger.info(f"数据集加载成功，包含 {len(dataset)} 个样本")
    return dataset

def setup_training_arguments(config):
    """设置训练参数"""
    from transformers import TrainingArguments

    training_args = TrainingArguments(
        per_device_train_batch_size=config['training_config']['per_device_train_batch_size'],
        gradient_accumulation_steps=config['training_config']['gradient_accumulation_steps'],
        warmup_steps=config['training_config']['warmup_steps'],
        max_steps=config['training_config']['max_steps'],
        learning_rate=config['training_config']['learning_rate'],
        fp16=config['training_config']['fp16'],
        bf16=config['training_config']['bf16'],
        logging_steps=config['training_config']['logging_steps'],
        optim=config['training_config']['optim'],
        weight_decay=config['training_config']['weight_decay'],
        lr_scheduler_type=config['training_config']['lr_scheduler_type'],
        seed=config['training_config']['seed'],
        output_dir=config['training_config']['output_dir'],
        gradient_checkpointing=config['training_config']['gradient_checkpointing'],
        report_to=["tensorboard"],
        save_steps=config['monitoring_config']['checkpoint_interval']
    )

    return training_args

def create_trainer(model, tokenizer, dataset, training_args, config):
    """创建 SFT 训练器"""
    from trl import SFTTrainer

    logger.info("正在创建 SFT 训练器")
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field="text",
        max_seq_length=config['model_config']['max_seq_length'],
        args=training_args
    )

    return trainer

def save_model(model, tokenizer, config):
    """保存训练好的模型"""
    output_dir = config['output_config']['model_save_dir']
    if not Path(output_dir).exists():
        Path(output_dir).mkdir(parents=True)

    logger.info(f"正在保存模型到: {output_dir}")
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)

    if config['output_config']['save_merged_model']:
        logger.info("正在合并模型")
        model.save_pretrained_merged(
            f"{output_dir}_merged",
            tokenizer,
            save_method="merged_16bit"
        )

def main():
    """主函数"""
    try:
        logger.info("=" * 60)
        logger.info("Qwen3.5-7B 模型微调训练")
        logger.info("=" * 60)

        # 创建训练日志目录
        if not Path("training_logs").exists():
            Path("training_logs").mkdir()

        # 获取配置
        logger.info("正在加载配置")
        config = get_training_config()
        config = update_config_from_env(config)

        # 检查并安装依赖
        logger.info("正在检查依赖")
        install_requirements()

        # 初始化模型和分词器
        logger.info("正在初始化模型和分词器")
        model, tokenizer = initialize_model_and_tokenizer(config)

        # 加载数据集
        logger.info("正在加载训练数据")
        dataset = load_dataset(config)
        if dataset is None:
            logger.error("无法加载数据集")
            return

        # 设置训练参数
        logger.info("正在设置训练参数")
        training_args = setup_training_arguments(config)

        # 创建训练器
        logger.info("正在创建训练器")
        trainer = create_trainer(model, tokenizer, dataset, training_args, config)

        # 开始训练
        logger.info("开始训练")
        trainer_stats = trainer.train()
        logger.info(f"训练完成: {trainer_stats}")

        # 保存模型
        logger.info("正在保存模型")
        save_model(model, tokenizer, config)

        logger.info("训练过程顺利完成！")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"训练过程中出错: {e}")
        logger.error("训练过程终止")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()
