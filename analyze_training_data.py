#!/usr/bin/env python3
"""
训练数据质量分析脚本
用于检查三种形态的分布是否均衡
"""

import json
import os
import sys
import statistics

def analyze_data(file_path):
    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        return False

    print("=" * 70)
    print(f"  训练数据质量分析: {file_path}")
    print("=" * 70)

    samples = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    sample = json.loads(line)
                    samples.append(sample)
                except:
                    continue

    print(f"\n成功解析 {len(samples)} 个样本")

    # 统计形态分布
    morphology_counts = {
        '上涨': 0,
        '下跌': 0,
        '横盘': 0
    }

    returns_list = []
    confidence_list = []

    for sample in samples:
        text = sample['text']

        # 提取形态
        if '趋势判断：上涨' in text:
            morphology_counts['上涨'] += 1
        elif '趋势判断：下跌' in text:
            morphology_counts['下跌'] += 1
        elif '趋势判断：横盘' in text:
            morphology_counts['横盘'] += 1

        # 提取收益率和置信度
        # 置信度格式: 置信度：0.85
        # 收益率格式: 预期变动：+1.23%
        try:
            # 提取置信度
            conf_start = text.find('置信度：') + 4
            if conf_start > 4:
                conf_str = text[conf_start:conf_start + 4]
                if '。' in conf_str:
                    conf_str = conf_str.split('。')[0]
                conf = float(conf_str)
                if 0 <= conf <= 1:
                    confidence_list.append(conf)

            # 提取收益率
            return_start = text.find('预期变动：') + 6
            if return_start > 6:
                return_str = text[return_start:return_start + 8]
                if '。' in return_str:
                    return_str = return_str.split('。')[0]
                if return_str:
                    if '%' in return_str:
                        return_str = return_str.replace('%', '').strip()
                    if '+' in return_str:
                        return_str = return_str.replace('+', '').strip()
                    if return_str and len(return_str) < 10:
                        try:
                            ret = float(return_str)
                            returns_list.append(ret)
                        except:
                            continue
        except:
            continue

    # 输出统计结果
    print("\n" + "=" * 70)
    print("  1. 样本分布分析")
    print("=" * 70)
    total = len(samples)
    for morph, count in morphology_counts.items():
        percentage = (count / total) * 100
        print(f"  {morph}: {count} 个 ({percentage:.1f}%)")

    # 检查是否均衡
    ideal = total / 3
    is_balanced = True
    for morph, count in morphology_counts.items():
        if abs(count - ideal) > ideal * 0.1:  # 允许 10% 误差
            is_balanced = False
            print(f"    {morph} 分布偏差较大")

    if is_balanced:
        print("  样本分布均衡")
    else:
        print("  样本分布需要进一步优化")

    # 置信度分析
    print("\n" + "=" * 70)
    print("  2. 置信度分析")
    print("=" * 70)
    if confidence_list:
        avg_confidence = statistics.mean(confidence_list)
        max_confidence = max(confidence_list)
        min_confidence = min(confidence_list)
        std_confidence = statistics.stdev(confidence_list)

        print(f"  平均置信度: {avg_confidence:.3f}")
        print(f"  置信度范围: {min_confidence:.3f} - {max_confidence:.3f}")
        print(f"  置信度标准差: {std_confidence:.3f}")

        if avg_confidence < 0.5:
            print("  平均置信度偏低")
        elif avg_confidence < 0.6:
            print("  平均置信度中等")
        else:
            print("  平均置信度较高")
    else:
        print("  无法提取置信度数据")

    # 收益率分析
    print("\n" + "=" * 70)
    print("  3. 预期变动分析")
    print("=" * 70)
    if returns_list:
        avg_return = statistics.mean(returns_list)
        max_return = max(returns_list)
        min_return = min(returns_list)
        std_return = statistics.stdev(returns_list)

        print(f"  平均预期变动: {avg_return:.2f}%")
        print(f"  变动范围: {min_return:.2f}% - {max_return:.2f}%")
        print(f"  变动标准差: {std_return:.2f}")

        # 检查收益率分布是否正常
        if abs(avg_return) > 0.5:
            print("  平均收益率偏离零值较大")
        if max_return - min_return < 5:
            print("  收益率范围较窄")
        else:
            print("  收益率范围合理")
    else:
        print("  无法提取收益率数据")

    # 文本长度分析
    print("\n" + "=" * 70)
    print("  4. 文本长度分析")
    print("=" * 70)

    lengths = []
    for sample in samples:
        lengths.append(len(sample['text']))

    avg_length = statistics.mean(lengths)
    std_length = statistics.stdev(lengths)

    print(f"  平均文本长度: {avg_length:.0f} 字符")
    print(f"  文本长度范围: {min(lengths):.0f} - {max(lengths):.0f}")
    print(f"  文本长度标准差: {std_length:.0f}")

    if avg_length < 1000:
        print("  平均文本长度偏短")
    elif avg_length < 2000:
        print("  平均文本长度合适")
    else:
        print("  平均文本长度偏长")

    # 总结
    print("\n" + "=" * 70)
    print("  数据质量评估")
    print("=" * 70)

    overall_score = 85

    if not is_balanced:
        overall_score -= 10

    if len(confidence_list) < total * 0.8:
        overall_score -= 10

    if len(returns_list) < total * 0.8:
        overall_score -= 10

    if avg_length < 1000:
        overall_score -= 10

    if overall_score >= 90:
        print("  数据质量优秀")
    elif overall_score >= 80:
        print("  数据质量良好")
    elif overall_score >= 70:
        print("  数据质量中等")
    else:
        print("  数据质量需要改进")

    print(f"  综合评分: {overall_score}/100")

    return overall_score >= 80

def main():
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        # 默认文件路径
        base_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(base_dir, 'data', 'qwen_training')
        files = [f for f in os.listdir(data_dir) if f.endswith('.jsonl')]
        if files:
            file_path = os.path.join(data_dir, files[0])
        else:
            print("❌ 未找到训练数据文件")
            return False

    return analyze_data(file_path)

if __name__ == "__main__":
    main()
