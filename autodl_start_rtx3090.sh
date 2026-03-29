#!/bin/bash
# AutoDL 启动脚本 - RTX 3090 优化版
# 专门为 RTX 3090 24GB VRAM 优化的参数

set -e  # 遇到错误立即退出

echo "========================================="
echo "  Qwen3.5-7B 微调 - RTX 3090 优化版"
echo "========================================="

# 配置
DATASET_PATH="/root/autodl-tmp/qwen_trading_samples.jsonl"
OUTPUT_DIR="/root/autodl-tmp/qwen_trading_lora"
MODEL_NAME="Qwen/Qwen2.5-7B-Instruct"

echo ""
echo "配置信息 (RTX 3090 优化):"
echo "  数据集: ${DATASET_PATH}"
echo "  输出目录: ${OUTPUT_DIR}"
echo "  模型: ${MODEL_NAME}"
echo ""
echo "优化参数:"
echo "  Batch Size: 2"
echo "  Gradient Accumulation: 16"
echo "  LoRA Rank: 32"
echo "  最大序列长度: 1536"
echo "  学习率: 8e-5"
echo ""

# 1. 检查数据集
if [ ! -f "${DATASET_PATH}" ]; then
    echo "❌ 数据集文件不存在: ${DATASET_PATH}"
    echo "请先上传训练数据到 AutoDL"
    exit 1
fi
echo "✅ 数据集检查通过"

# 2. 安装依赖
echo ""
echo "[1/4] 安装依赖..."
pip install --upgrade pip

# 安装 PyTorch（如果尚未安装）
if ! python -c "import torch" 2>/dev/null; then
    echo "  安装 PyTorch..."
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
fi

# 安装 unsloth 和其他依赖
echo "  安装 unsloth..."
pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
pip install --no-deps "xformers<0.0.27" "trl==0.1.0"
pip install bitsandbytes datasets transformers accelerate

echo "✅ 依赖安装完成"

# 3. 显示 GPU 信息
echo ""
echo "[2/4] 检查 GPU..."
python -c "
import torch
print('PyTorch 版本:', torch.__version__)
print('CUDA 可用:', torch.cuda.is_available())
if torch.cuda.is_available():
    print('GPU 数量:', torch.cuda.device_count())
    print('GPU 型号:', torch.cuda.get_device_name(0))
    gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
    print(f'GPU 显存: {gpu_memory:.1f} GB')
"

# 4. 开始训练 - RTX 3090 优化参数
echo ""
echo "[3/4] 开始微调 (RTX 3090 优化)..."
echo ""

python qwen_finetune_rtx3090.py \
    --dataset "${DATASET_PATH}" \
    --output_dir "${OUTPUT_DIR}" \
    --model_name "${MODEL_NAME}" \
    --max_seq_length 1536 \
    --lora_r 32 \
    --lora_alpha 64 \
    --batch_size 2 \
    --gradient_accumulation 16 \
    --learning_rate 8e-5 \
    --max_steps 1500 \
    --save_steps 200 \
    --logging_steps 20 \
    --warmup_steps 150 \
    --use_gradient_checkpointing

# 5. 完成
echo ""
echo "[4/4] 训练完成!"
echo ""
echo "========================================="
echo "  训练已完成 (RTX 3090 优化版)"
echo "========================================="
echo ""
echo "模型保存在: ${OUTPUT_DIR}"
echo ""
echo "下一步:"
echo "  1. 使用 tensorboard 查看训练日志"
echo "  2. 运行 qwen_inference_test.py 验证模型"
echo "  3. 下载模型到本地"
echo ""

# 启动 tensorboard（可选）
echo "是否启动 TensorBoard? (y/n)"
read -r start_tb
if [ "$start_tb" = "y" ] || [ "$start_tb" = "Y" ]; then
    echo "启动 TensorBoard..."
    tensorboard --logdir "${OUTPUT_DIR}/logs" --bind_all &
    echo "TensorBoard 已启动，访问: http://localhost:6006"
fi
