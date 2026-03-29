#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qwen3.5-7B 训练数据准备脚本
将原始 K 线数据转换为三种形态（上涨/下跌/横盘）的训练数据
"""

import os
import sys
import json
import pandas as pd
import numpy as np
from pathlib import Path
from tqdm import tqdm
from datetime import datetime

# 添加项目路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 配置
CONFIG = {
    'INPUT_DIR': 'data',
    'OUTPUT_DIR': 'data/qwen_training',
    'WINDOW_SIZE': 100,  # 历史K线数量
    'PREDICTION_HORIZON': 12,  # 预测未来多少个周期
    'TREND_THRESHOLD': 0.015,  # 1.5% 作为趋势判定阈值
    'MAX_SAMPLES_PER_MORPH': 3000,  # 每种形态最多样本数
}

def calculate_rsi(series, period=14):
    """计算RSI指标"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_indicators(df):
    """计算技术指标"""
    df = df.copy()

    # 基础指标
    df['returns'] = df['close'].pct_change()
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma60'] = df['close'].rolling(60).mean()

    # RSI
    df['rsi'] = calculate_rsi(df['close'], 14)

    # 布林带
    df['bb_middle'] = df['close'].rolling(20).mean()
    df['bb_std'] = df['close'].rolling(20).std()
    df['bb_upper'] = df['bb_middle'] + 2 * df['bb_std']
    df['bb_lower'] = df['bb_middle'] - 2 * df['bb_std']
    df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

    # 波动率
    df['volatility'] = df['returns'].rolling(20).std() * np.sqrt(365 * 24)

    # MACD
    df['ema12'] = df['close'].ewm(span=12).mean()
    df['ema26'] = df['close'].ewm(span=26).mean()
    df['macd'] = df['ema12'] - df['ema26']
    df['macd_signal'] = df['macd'].ewm(span=9).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']

    return df

def classify_morphology(future_returns):
    """
    根据未来收益率分类形态
    returns: '上涨' | '下跌' | '横盘'
    """
    if future_returns > CONFIG['TREND_THRESHOLD']:
        return '上涨'
    elif future_returns < -CONFIG['TREND_THRESHOLD']:
        return '下跌'
    else:
        return '横盘'

def format_market_description(history_df):
    """格式化市场数据描述"""
    last_row = history_df.iloc[-1]

    # 趋势描述
    trend_text = ""
    if last_row['close'] > last_row['ma20']:
        trend_text = "价格位于MA20上方，"
    elif last_row['close'] < last_row['ma20']:
        trend_text = "价格位于MA20下方，"

    # RSI描述
    rsi_text = ""
    if last_row['rsi'] > 70:
        rsi_text = "RSI超买(%.1f)" % last_row['rsi']
    elif last_row['rsi'] < 30:
        rsi_text = "RSI超卖(%.1f)" % last_row['rsi']
    else:
        rsi_text = "RSI中性(%.1f)" % last_row['rsi']

    # 布林带位置
    bb_text = ""
    if last_row['bb_position'] > 0.8:
        bb_text = "触及布林带上轨"
    elif last_row['bb_position'] < 0.2:
        bb_text = "触及布林带下轨"
    else:
        bb_text = "布林带中轨附近"

    return (
        f"最新价格: {last_row['close']:.2f}, "
        f"{trend_text}"
        f"{rsi_text}, "
        f"{bb_text}, "
        f"24h波动率: {last_row['volatility']:.2%}"
    )

def create_chatml_sample(history_df, morphology, future_returns):
    """创建ChatML格式的训练样本"""
    market_desc = format_market_description(history_df)

    # 系统提示词
    system_msg = (
        "你是一个专业的加密货币量化交易分析师，"
        "擅长从K线形态和技术指标中识别趋势，"
        "提供精准的市场分析和操作建议。"
    )

    # 用户输入
    user_msg = f"分析当前BTCUSDT行情：{market_desc}。未来{CONFIG['PREDICTION_HORIZON']}小时趋势如何？"

    # 助手输出（基于形态）
    if morphology == '上涨':
        confidence = min(0.9, 0.7 + abs(future_returns))
        advice = "建议关注多头机会，可考虑分批建仓，设置合理止损。"
    elif morphology == '下跌':
        confidence = min(0.9, 0.7 + abs(future_returns))
        advice = "建议保持观望或考虑对冲策略，等待更明确信号。"
    else:  # 横盘
        confidence = 0.5 + abs(future_returns) * 5
        advice = "市场震荡，建议降低仓位，等待趋势明确后再操作。"

    assistant_msg = (
        f"趋势判断：{morphology}。"
        f"置信度：{confidence:.2f}。"
        f"未来{CONFIG['PREDICTION_HORIZON']}小时预期变动：{future_returns:+.2%}。"
        f"操作建议：{advice}"
    )

    # ChatML 格式
    chatml_text = (
        f"<|im_start|>system\n{system_msg}<|im_end|>\n"
        f"<|im_start|>user\n{user_msg}<|im_end|>\n"
        f"<|im_start|>assistant\n{assistant_msg}<|im_end|>"
    )

    return {
        'text': chatml_text,
        'morphology': morphology,
        'future_returns': future_returns
    }

def process_csv_file(csv_path):
    """处理单个CSV文件"""
    try:
        df = pd.read_csv(csv_path)

        # 确保有必要的列
        required_columns = ['open', 'high', 'low', 'close', 'volume']
        for col in required_columns:
            if col not in df.columns:
                print(f"  警告: {csv_path} 缺少列 {col}，跳过")
                return []

        # 计算技术指标
        df = calculate_indicators(df)

        # 去除NaN值
        df = df.dropna()
        if len(df) < CONFIG['WINDOW_SIZE'] + CONFIG['PREDICTION_HORIZON']:
            print(f"  警告: {csv_path} 数据不足，跳过")
            return []

        samples = []
        total_possible = len(df) - CONFIG['WINDOW_SIZE'] - CONFIG['PREDICTION_HORIZON']

        # 滑动窗口处理
        # 使用步长控制样本数量
        stride = max(1, total_possible // (CONFIG['MAX_SAMPLES_PER_MORPH'] // 3))

        for i in range(0, total_possible, stride):
            # 历史数据窗口
            history = df.iloc[i : i + CONFIG['WINDOW_SIZE']]
            # 未来数据（用于标签）
            future = df.iloc[i + CONFIG['WINDOW_SIZE'] : i + CONFIG['WINDOW_SIZE'] + CONFIG['PREDICTION_HORIZON']]

            # 计算未来收益率
            future_return = (future['close'].iloc[-1] - history['close'].iloc[-1]) / history['close'].iloc[-1]

            # 分类形态
            morphology = classify_morphology(future_return)

            # 创建训练样本
            sample = create_chatml_sample(history, morphology, future_return)
            samples.append(sample)

        return samples

    except Exception as e:
        print(f"  错误处理 {csv_path}: {e}")
        return []

def balance_samples(samples):
    """平衡三种形态的样本数量"""
    # 按形态分组
    morph_samples = {
        '上涨': [],
        '下跌': [],
        '横盘': []
    }

    for sample in samples:
        morph = sample['morphology']
        if morph in morph_samples:
            morph_samples[morph].append(sample)

    print(f"\n  原始样本分布:")
    for morph, s_list in morph_samples.items():
        print(f"    {morph}: {len(s_list)} 个")

    # 找出最少的样本数
    min_count = min(len(s_list) for s_list in morph_samples.values())
    min_count = min(min_count, CONFIG['MAX_SAMPLES_PER_MORPH'])

    # 平衡采样
    balanced_samples = []
    for morph, s_list in morph_samples.items():
        # 随机打乱
        np.random.shuffle(s_list)
        # 取前min_count个
        balanced_samples.extend(s_list[:min_count])

    print(f"\n  平衡后每种形态: {min_count} 个")
    print(f"  总样本数: {len(balanced_samples)}")

    return balanced_samples

def save_to_jsonl(samples, output_path):
    """保存为JSONL格式"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        for sample in samples:
            # 只保存text字段用于训练
            json.dump({'text': sample['text']}, f, ensure_ascii=False)
            f.write('\n')

    print(f"\n  已保存到: {output_path}")

def main():
    """主函数"""
    print("=" * 70)
    print("  Qwen3.5-7B 训练数据准备")
    print("=" * 70)

    # 创建输出目录
    os.makedirs(CONFIG['OUTPUT_DIR'], exist_ok=True)

    # 查找所有CSV文件
    input_dir = Path(CONFIG['INPUT_DIR'])
    csv_files = list(input_dir.glob('*.csv'))

    if not csv_files:
        print(f"\n错误: 在 {CONFIG['INPUT_DIR']} 目录中未找到CSV文件")
        sys.exit(1)

    print(f"\n找到 {len(csv_files)} 个CSV文件")

    # 处理所有文件
    all_samples = []
    for csv_file in tqdm(csv_files, desc="处理文件"):
        print(f"\n处理: {csv_file.name}")
        samples = process_csv_file(csv_file)
        all_samples.extend(samples)

    if not all_samples:
        print("\n错误: 未能生成任何训练样本")
        sys.exit(1)

    print(f"\n总共生成 {len(all_samples)} 个原始样本")

    # 平衡样本
    balanced_samples = balance_samples(all_samples)

    # 打乱所有样本
    np.random.shuffle(balanced_samples)

    # 保存训练数据
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = os.path.join(CONFIG['OUTPUT_DIR'], f'qwen_trading_samples_{timestamp}.jsonl')
    save_to_jsonl(balanced_samples, output_file)

    # 保存带有元数据的版本（用于验证）
    metadata_file = os.path.join(CONFIG['OUTPUT_DIR'], f'qwen_trading_samples_metadata_{timestamp}.json')
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(balanced_samples, f, ensure_ascii=False, indent=2)
    print(f"  元数据已保存到: {metadata_file}")

    print("\n" + "=" * 70)
    print("  数据准备完成!")
    print("=" * 70)
    print(f"\n下一步:")
    print(f"  1. 将 {output_file} 上传到 AutoDL")
    print(f"  2. 使用 QLoRA 微调 Qwen3.5-7B 模型")
    print(f"  3. 验证模型推理效果")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n用户中断")
        sys.exit(130)
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
