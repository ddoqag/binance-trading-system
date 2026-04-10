"""
参数优化结果可视化
生成热力图和参数敏感性分析
"""
import json
import sys
import os
from typing import List, Dict, Any
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_results(filename: str) -> Dict[str, Any]:
    """加载结果文件。"""
    with open(filename, 'r') as f:
        return json.load(f)


def create_heatmap_2d(results: List[Dict], x_param: str, y_param: str,
                      metric: str = 'sharpe_ratio') -> np.ndarray:
    """
    创建2D热力图数据。
    x_param: x轴参数名
    y_param: y轴参数名
    metric: 评估指标
    """
    # 提取唯一的参数值
    x_values = sorted(list(set(r['params'][x_param] for r in results)))
    y_values = sorted(list(set(r['params'][y_param] for r in results)))

    # 创建网格
    grid = np.zeros((len(y_values), len(x_values)))
    count = np.zeros((len(y_values), len(x_values)))

    # 填充数据
    for r in results:
        x_idx = x_values.index(r['params'][x_param])
        y_idx = y_values.index(r['params'][y_param])
        grid[y_idx, x_idx] += r[metric]
        count[y_idx, x_idx] += 1

    # 平均化
    grid = np.divide(grid, count, where=count > 0)

    return grid, x_values, y_values


def print_heatmap_ascii(grid: np.ndarray, x_labels: List, y_labels: List,
                        title: str = "", cmap: str = "viridis"):
    """打印ASCII热力图。"""
    print("\n" + "=" * 70)
    print(f"HEATMAP: {title}")
    print("=" * 70)

    # 找到数据范围
    vmin, vmax = np.nanmin(grid), np.nanmax(grid)

    # 颜色字符（从低到高）- 使用ASCII兼容字符
    chars = " .:-=+*#%@",

    # 打印列标题
    print(f"{'':>12}", end="")
    for x in x_labels:
        print(f"{x:>8}", end="")
    print()

    # 打印热力图
    for i, y in enumerate(y_labels):
        print(f"{y:>10} |", end="")
        for j in range(len(x_labels)):
            val = grid[i, j]
            if np.isnan(val):
                print(f"{'N/A':>8}", end="")
            else:
                # 归一化到0-9
                norm = int((val - vmin) / (vmax - vmin + 1e-10) * 9)
                norm = min(9, max(0, norm))
                char = chars[norm]
                print(f"{char * 4:>8}", end="")
        print(f" | {y}")

    # 打印图例
    print(f"\n{'':>12}Legend: {chars[0]}=Low  {chars[2]}=Mid  {chars[4]}=High")
    print(f"{'':>12}Range: [{vmin:.3f}, {vmax:.3f}]")


def analyze_param_sensitivity(results: List[Dict], param_name: str, metric: str = 'sharpe_ratio'):
    """分析单个参数的敏感性。"""
    param_values = sorted(list(set(r['params'][param_name] for r in results)))

    print(f"\n{'='*70}")
    print(f"Parameter Sensitivity: {param_name} -> {metric}")
    print(f"{'='*70}")

    for val in param_values:
        subset = [r[metric] for r in results if r['params'][param_name] == val]
        if subset:
            mean_val = np.mean(subset)
            std_val = np.std(subset)
            min_val = np.min(subset)
            max_val = np.max(subset)
            print(f"{param_name}={val:>8}: mean={mean_val:>8.3f}  std={std_val:>6.3f}  "
                  f"range=[{min_val:>7.3f}, {max_val:>7.3f}]  n={len(subset)}")


def generate_report(filename: str):
    """生成完整分析报告。"""
    data = load_results(filename)
    results = data['results']

    print(f"\n{'='*70}")
    print(f"PARAMETER OPTIMIZATION REPORT")
    print(f"Generated: {data['timestamp']}")
    print(f"Total Tests: {data['total_tests']}")
    print(f"{'='*70}")

    # 1. 最优参数
    best_sharpe = max(results, key=lambda x: x['sharpe_ratio'])
    best_return = max(results, key=lambda x: x['total_return_pct'])
    best_dd = min(results, key=lambda x: x['max_drawdown_pct'])

    print("\n[OPTIMAL PARAMETERS]")
    print(f"\nBest Sharpe Ratio: {best_sharpe['sharpe_ratio']:.3f}")
    print(f"  min_spread_ticks: {best_sharpe['params']['min_spread_ticks']}")
    print(f"  inventory_skew_factor: {best_sharpe['params']['inventory_skew_factor']}")
    print(f"  base_order_size: {best_sharpe['params']['base_order_size']}")
    print(f"  toxic_threshold: {best_sharpe['params']['toxic_threshold']}")

    print(f"\nBest Total Return: {best_return['total_return_pct']:.3f}%")
    print(f"  min_spread_ticks: {best_return['params']['min_spread_ticks']}")
    print(f"  inventory_skew_factor: {best_return['params']['inventory_skew_factor']}")
    print(f"  base_order_size: {best_return['params']['base_order_size']}")
    print(f"  toxic_threshold: {best_return['params']['toxic_threshold']}")

    print(f"\nLowest Drawdown: {best_dd['max_drawdown_pct']:.3f}%")
    print(f"  min_spread_ticks: {best_dd['params']['min_spread_ticks']}")
    print(f"  inventory_skew_factor: {best_dd['params']['inventory_skew_factor']}")
    print(f"  base_order_size: {best_dd['params']['base_order_size']}")
    print(f"  toxic_threshold: {best_dd['params']['toxic_threshold']}")

    # 2. 热力图 - Spread vs Skew
    if len(set(r['params']['min_spread_ticks'] for r in results)) > 1 and \
       len(set(r['params']['inventory_skew_factor'] for r in results)) > 1:
        grid, x_vals, y_vals = create_heatmap_2d(
            results, 'min_spread_ticks', 'inventory_skew_factor', 'sharpe_ratio'
        )
        print_heatmap_ascii(grid, x_vals, y_vals,
                           "Sharpe Ratio: Spread Ticks vs Inventory Skew")

    # 3. 参数敏感性分析
    analyze_param_sensitivity(results, 'min_spread_ticks', 'sharpe_ratio')
    analyze_param_sensitivity(results, 'inventory_skew_factor', 'sharpe_ratio')
    analyze_param_sensitivity(results, 'base_order_size', 'sharpe_ratio')

    # 4. 推荐配置
    print(f"\n{'='*70}")
    print("RECOMMENDED CONFIGURATION")
    print(f"{'='*70}")

    # 平衡考虑夏普比率和收益
    def score(r):
        # 综合评分：夏普比率权重更高
        sharpe_norm = (r['sharpe_ratio'] - min(x['sharpe_ratio'] for x in results)) / \
                      (max(x['sharpe_ratio'] for x in results) - min(x['sharpe_ratio'] for x in results) + 1e-10)
        return_norm = (r['total_return_pct'] - min(x['total_return_pct'] for x in results)) / \
                      (max(x['total_return_pct'] for x in results) - min(x['total_return_pct'] for x in results) + 1e-10)
        dd_penalty = r['max_drawdown_pct'] / 100.0  # 回撤惩罚
        return sharpe_norm * 0.5 + return_norm * 0.3 - dd_penalty * 0.2

    best_balanced = max(results, key=score)

    print(f"\nBalanced Configuration (Sharpe 50% + Return 30% - Drawdown 20%):")
    p = best_balanced['params']
    print(f"  min_spread_ticks: {p['min_spread_ticks']}")
    print(f"  inventory_skew_factor: {p['inventory_skew_factor']}")
    print(f"  base_order_size: {p['base_order_size']}")
    print(f"  toxic_threshold: {p['toxic_threshold']}")
    print(f"\n  Expected Performance:")
    print(f"    Sharpe Ratio: {best_balanced['sharpe_ratio']:.3f}")
    print(f"    Total Return: {best_balanced['total_return_pct']:.3f}%")
    print(f"    Max Drawdown: {best_balanced['max_drawdown_pct']:.3f}%")
    print(f"    Total Trades: {best_balanced['total_trades']}")

    print(f"\n{'='*70}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Visualize Grid Search Results")
    parser.add_argument("filename", nargs="?", default=None,
                       help="Results JSON file (auto-detect if not specified)")
    args = parser.parse_args()

    # 自动检测最新的结果文件
    if args.filename is None:
        import glob
        files = glob.glob("grid_search_results_*.json")
        if not files:
            print("No results files found!")
            sys.exit(1)
        args.filename = max(files, key=os.path.getctime)
        print(f"Auto-detected: {args.filename}")

    if not os.path.exists(args.filename):
        print(f"File not found: {args.filename}")
        sys.exit(1)

    generate_report(args.filename)


if __name__ == "__main__":
    main()
