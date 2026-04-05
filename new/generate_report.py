"""
生成6策略系统的综合报告
"""

import json
import re
import numpy as np
from datetime import datetime
from collections import defaultdict


def parse_weight_evolution(log_file):
    """从日志解析权重演变数据"""
    weights_history = []

    with open(log_file, 'r') as f:
        for line in f:
            if 'Weights evolved' in line:
                # 提取权重字典
                match = re.search(r"Weights evolved: ({.*})", line)
                if match:
                    weights_str = match.group(1)
                    # 解析权重
                    weights = {}
                    for wmatch in re.finditer(r"'(\w+)':\s*(?:np\.float64\()?([\d.]+)(?:\))?", weights_str):
                        strategy, weight = wmatch.groups()
                        weights[strategy] = float(weight)
                    if weights:
                        weights_history.append(weights)

    return weights_history


def generate_comprehensive_report(weight_history):
    """生成6策略系统的综合报告"""

    if not weight_history:
        return {"error": "No weight data found"}

    # 转换为numpy数组便于计算
    strategies = list(weight_history[0].keys())
    n_updates = len(weight_history)

    report = {
        "系统概览": {
            "策略数量": len(strategies),
            "观测周期数": n_updates,
            "策略列表": strategies,
        },

        "策略表现排名": [],

        "系统健康指标": {},

        "市场状态分析": {},

        "权重演变趋势": {}
    }

    # 计算每个策略的统计指标
    for strategy in strategies:
        weights = [w.get(strategy, 0) for w in weight_history]
        weights_arr = np.array(weights)

        # 计算主导次数
        dominant_count = sum(1 for w in weight_history if max(w.values()) == w.get(strategy, 0))

        report["策略表现排名"].append({
            "策略": strategy,
            "平均权重": float(np.mean(weights_arr)),
            "权重标准差": float(np.std(weights_arr)),
            "最大权重": float(np.max(weights_arr)),
            "最小权重": float(np.min(weights_arr)),
            "主导次数": dominant_count,
            "主导频率": dominant_count / n_updates,
            "稳定性评分": float(1 - np.std(weights_arr) / np.mean(weights_arr)) if np.mean(weights_arr) > 0 else 0
        })

    # 按平均权重排序
    report["策略表现排名"].sort(key=lambda x: x["平均权重"], reverse=True)

    # 计算系统健康指标
    hhi_values = [sum(w**2 for w in wh.values()) for wh in weight_history]
    effective_n_values = [1/hhi if hhi > 0 else 0 for hhi in hhi_values]

    report["系统健康指标"] = {
        "平均集中度指数(HHI)": float(np.mean(hhi_values)),
        "集中度标准差": float(np.std(hhi_values)),
        "平均有效策略数": float(np.mean(effective_n_values)),
        "权重总波动率": float(np.std([w for wh in weight_history for w in wh.values()])),
        "策略轮动频率": sum(1 for i in range(1, n_updates) if max(weight_history[i].items(), key=lambda x: x[1])[0] != max(weight_history[i-1].items(), key=lambda x: x[1])[0]) / (n_updates - 1) if n_updates > 1 else 0,
    }

    # 市场状态分析
    trend_periods = sum(1 for wh in weight_history if wh.get('dual_ma', 0) + wh.get('momentum', 0) + wh.get('ml_momentum', 0) > 0.5)
    vol_periods = sum(1 for wh in weight_history if wh.get('bollinger_bands', 0) + wh.get('volatility_breakout', 0) > 0.4)
    range_periods = sum(1 for wh in weight_history if wh.get('rsi', 0) > 0.3)

    report["市场状态分析"] = {
        "趋势主导期占比": trend_periods / n_updates,
        "波动率主导期占比": vol_periods / n_updates,
        "震荡主导期占比": range_periods / n_updates,
        "混合市场期占比": 1 - (trend_periods + vol_periods + range_periods) / n_updates,
    }

    # ML策略专项分析
    ml_weights = [wh.get('ml_momentum', 0) for wh in weight_history]
    traditional_avg = [(wh.get('dual_ma', 0) + wh.get('momentum', 0) + wh.get('rsi', 0)) / 3 for wh in weight_history]

    report["ML策略专项分析"] = {
        "相对于传统策略表现比": float(np.mean(ml_weights) / np.mean(traditional_avg)) if np.mean(traditional_avg) > 0 else 0,
        "ML策略平均权重": float(np.mean(ml_weights)),
        "ML策略稳定性": float(1 - np.std(ml_weights) / np.mean(ml_weights)) if np.mean(ml_weights) > 0 else 0,
    }

    # 权重演变趋势（首尾对比）
    if n_updates >= 2:
        first = weight_history[0]
        last = weight_history[-1]

        report["权重演变趋势"] = {
            "初始→最终变化": {
                strategy: {
                    "初始": round(first.get(strategy, 0), 4),
                    "最终": round(last.get(strategy, 0), 4),
                    "变化": round(last.get(strategy, 0) - first.get(strategy, 0), 4)
                }
                for strategy in strategies
            }
        }

    return report


def print_report(report):
    """打印格式化报告"""
    print("\n" + "=" * 70)
    print("6策略自进化交易系统 - 综合报告")
    print("=" * 70)

    print("\n📊 系统概览:")
    for key, value in report["系统概览"].items():
        print(f"  {key}: {value}")

    print("\n🏆 策略表现排名:")
    for i, strategy_data in enumerate(report["策略表现排名"], 1):
        print(f"\n  #{i} {strategy_data['策略']}:")
        print(f"    平均权重: {strategy_data['平均权重']:.2%}")
        print(f"    主导次数: {strategy_data['主导次数']} ({strategy_data['主导频率']:.1%})")
        print(f"    稳定性评分: {strategy_data['稳定性评分']:.2f}")

    print("\n💚 系统健康指标:")
    for key, value in report["系统健康指标"].items():
        if isinstance(value, float):
            print(f"  {key}: {value:.4f}")
        else:
            print(f"  {key}: {value}")

    print("\n📈 市场状态分析:")
    for key, value in report["市场状态分析"].items():
        print(f"  {key}: {value:.1%}")

    print("\n🤖 ML策略专项分析:")
    for key, value in report["ML策略专项分析"].items():
        if isinstance(value, float):
            print(f"  {key}: {value:.4f}")
        else:
            print(f"  {key}: {value}")

    if "权重演变趋势" in report:
        print("\n📊 权重演变趋势 (初始→最终):")
        for strategy, data in report["权重演变趋势"]["初始→最终变化"].items():
            change_str = f"+{data['变化']:.2%}" if data['变化'] > 0 else f"{data['变化']:.2%}"
            print(f"  {strategy}: {data['初始']:.2%} → {data['最终']:.2%} ({change_str})")

    # 健康度评估
    health_score = 0
    hhi = report["系统健康指标"]["平均集中度指数(HHI)"]
    if 0.2 <= hhi <= 0.4:
        health_score += 40
    effective_n = report["系统健康指标"]["平均有效策略数"]
    if effective_n >= 3:
        health_score += 30
    rotation_freq = report["系统健康指标"]["策略轮动频率"]
    if 0.1 <= rotation_freq <= 0.5:
        health_score += 30

    print("\n" + "=" * 70)
    print(f"系统健康度评分: {health_score}/100")
    if health_score >= 80:
        print("状态: 🟢 优秀")
    elif health_score >= 60:
        print("状态: 🟡 良好")
    else:
        print("状态: 🔴 需优化")
    print("=" * 70 + "\n")


def main():
    import sys

    log_file = sys.argv[1] if len(sys.argv) > 1 else 'logs/trading_6strategies_test.log'

    print(f"正在解析日志文件: {log_file}")
    weight_history = parse_weight_evolution(log_file)

    if not weight_history:
        print("未找到权重数据")
        return

    print(f"成功解析 {len(weight_history)} 条权重记录")

    report = generate_comprehensive_report(weight_history)

    # 保存JSON报告
    output_file = 'reports/6strategies_report.json'
    import os
    os.makedirs('reports', exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"报告已保存到: {output_file}")

    # 打印报告
    print_report(report)


if __name__ == '__main__':
    main()
