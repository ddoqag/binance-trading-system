"""
Qwen3.5-7B 模型微调配置文件
针对量化交易信号生成任务的QLoRA微调参数优化
"""

import os
from typing import Dict, Any

# 模型相关配置
MODEL_CONFIG = {
    "model_name": "Qwen/Qwen2.5-7B-Instruct",
    "max_seq_length": 2048,
    "dtype": None,
    "load_in_4bit": True
}

# QLoRA 微调参数配置
LORA_CONFIG = {
    "r": 64,  # Rank，越高对复杂指标拟合越好（捕获 Champion DNA 策略的多因子逻辑）
    "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj",
                      "gate_proj", "up_proj", "down_proj"],
    "lora_alpha": 128,  # 通常设定为 2 * r，确保有足够的修改能力
    "lora_dropout": 0,  # 设为0以提高训练效率
    "bias": "none",
    "use_gradient_checkpointing": "unsloth",  # 节省70%显存
    "random_state": 3407
}

# 训练参数配置
TRAINING_CONFIG = {
    "per_device_train_batch_size": 2,
    "gradient_accumulation_steps": 4,
    "warmup_steps": 50,
    "max_steps": 500,
    "learning_rate": 1e-4,
    "fp16": True,
    "bf16": False,
    "logging_steps": 10,
    "optim": "adamw_8bit",
    "weight_decay": 0.01,
    "lr_scheduler_type": "cosine",
    "seed": 3407,
    "output_dir": "outputs",
    "gradient_checkpointing": True
}

# 数据预处理配置
DATA_CONFIG = {
    "input_file": "data/qwen_training/qwen_trading_samples_metadata_20260320_145112.jsonl",
    "text_field": "text",
    "max_seq_length": 2048,
    "shuffle": True,
    "train_ratio": 0.9,
    "eval_ratio": 0.1
}

# 硬件优化配置（RTX 3090 24GB VRAM 优化）
HARDWARE_CONFIG = {
    "device": "cuda",
    "dtype": "float16",
    "max_memory": {
        0: "24GB"  # RTX 3090 显存大小
    },
    "gradient_checkpointing": True,
    "gradient_accumulation_steps": 4,
    "per_device_train_batch_size": 2,
    "fp16": True,
    "bf16": False,
    "optim": "adamw_8bit"
}

# 输出配置
OUTPUT_CONFIG = {
    "model_save_dir": "qwen_trading_lora",
    "tokenizer_save_dir": "qwen_trading_lora",
    "save_merged_model": False,
    "save_quantized_model": False
}

# 风险控制配置
RISK_CONTROL_CONFIG = {
    "confidence_threshold": 0.7,  # 模型置信度阈值
    "risk_level": "moderate",
    "stop_loss": 0.05,  # 5%止损
    "take_profit": 0.10  # 10%止盈
}

# 实时监控配置
MONITORING_CONFIG = {
    "log_level": "INFO",
    "log_file": "training_logs/qwen_finetune.log",
    "checkpoint_interval": 100,
    "early_stop_patience": 3
}


def get_training_config() -> Dict[str, Any]:
    """获取完整的训练配置"""
    return {
        "model_config": MODEL_CONFIG,
        "lora_config": LORA_CONFIG,
        "training_config": TRAINING_CONFIG,
        "data_config": DATA_CONFIG,
        "hardware_config": HARDWARE_CONFIG,
        "output_config": OUTPUT_CONFIG,
        "risk_control_config": RISK_CONTROL_CONFIG,
        "monitoring_config": MONITORING_CONFIG
    }


def update_config_from_env(config: Dict[str, Any]) -> Dict[str, Any]:
    """从环境变量更新配置（用于不同环境）"""
    # 从环境变量读取配置
    if "QWEN_MODEL_NAME" in os.environ:
        config["model_config"]["model_name"] = os.environ["QWEN_MODEL_NAME"]

    if "TRAIN_BATCH_SIZE" in os.environ:
        config["training_config"]["per_device_train_batch_size"] = int(
            os.environ["TRAIN_BATCH_SIZE"])

    if "LEARNING_RATE" in os.environ:
        config["training_config"]["learning_rate"] = float(
            os.environ["LEARNING_RATE"])

    return config
