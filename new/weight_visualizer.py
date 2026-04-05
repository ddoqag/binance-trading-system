"""
实时策略权重可视化工具
监控策略权重的动态演变
"""

import matplotlib.pyplot as plt
import matplotlib.animation as animation
from datetime import datetime
import re
import os
import time


class WeightVisualizer:
    """从日志文件实时解析和可视化策略权重"""

    def __init__(self, log_file='logs/trading.log', max_history=200):
        self.log_file = log_file
        self.max_history = max_history
        self.weights_history = {
            'dual_ma': [],
            'momentum': [],
            'rsi': []
        }
        self.timestamps = []
        self.last_position = 0

    def parse_new_logs(self):
        """只解析新增的日志行"""
        if not os.path.exists(self.log_file):
            return False

        with open(self.log_file, 'r', encoding='utf-8') as f:
            # 跳转到上次读取位置
            f.seek(self.last_position)
            new_lines = f.readlines()
            self.last_position = f.tell()

        updated = False
        for line in new_lines:
            # 匹配权重更新行（支持多种格式）
            if 'Updated strategy weights' in line or 'Weights evolved' in line:
                # 提取时间戳
                timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', line)
                if timestamp_match:
                    timestamp = timestamp_match.group(1)
                else:
                    timestamp = datetime.now().strftime('%H:%M:%S')

                # 解析权重（支持 np.float64(...) 格式）
                weights = {}
                # 先尝试匹配 np.float64(...) 格式
                for match in re.finditer(r"'(\w+)':\s*(?:np\.float64\()?([\d.]+)(?:\))?,?", line):
                    strategy, weight = match.groups()
                    weights[strategy] = float(weight)
                # 如果没有匹配到，尝试普通格式
                if not weights:
                    for match in re.finditer(r"'(\w+)':\s*([\d.]+)", line):
                        strategy, weight = match.groups()
                        weights[strategy] = float(weight)

                if weights:
                    self.timestamps.append(timestamp)
                    for strategy in self.weights_history.keys():
                        self.weights_history[strategy].append(
                            weights.get(strategy, 0.33)
                        )
                    updated = True

        # 限制历史长度
        if len(self.timestamps) > self.max_history:
            excess = len(self.timestamps) - self.max_history
            self.timestamps = self.timestamps[excess:]
            for strategy in self.weights_history:
                self.weights_history[strategy] = self.weights_history[strategy][excess:]

        return updated

    def get_market_regime(self):
        """根据当前权重推断市场状态"""
        if not self.weights_history['momentum']:
            return "Unknown"

        current = {
            'dual_ma': self.weights_history['dual_ma'][-1],
            'momentum': self.weights_history['momentum'][-1],
            'rsi': self.weights_history['rsi'][-1]
        }

        max_strategy = max(current, key=current.get)
        max_weight = current[max_strategy]

        if max_weight > 0.5:
            if max_strategy == 'momentum':
                return "Strong Trend (趋势确立)"
            elif max_strategy == 'rsi':
                return "Mean Reversion (均值回归)"
            else:
                return "Trend Following (趋势跟随)"
        elif max_weight > 0.4:
            return f"Emerging {max_strategy.upper()}"
        else:
            return "Balanced (均衡状态)"

    def plot_static(self):
        """生成静态图表"""
        self.parse_new_logs()

        if not self.timestamps:
            print("No weight data found in logs yet...")
            return

        fig, axes = plt.subplots(2, 2, figsize=(14, 10))

        # 1. 堆叠面积图
        ax1 = axes[0, 0]
        x = list(range(len(self.timestamps)))
        colors = {'dual_ma': '#FF6B6B', 'momentum': '#4ECDC4', 'rsi': '#45B7D1'}
        labels = {'dual_ma': 'Dual MA', 'momentum': 'Momentum', 'rsi': 'RSI'}

        bottom = [0] * len(x)
        for strategy in ['dual_ma', 'momentum', 'rsi']:
            weights = self.weights_history[strategy]
            ax1.fill_between(x, bottom, [b + w for b, w in zip(bottom, weights)],
                           alpha=0.7, label=labels[strategy], color=colors[strategy])
            bottom = [b + w for b, w in zip(bottom, weights)]

        ax1.set_ylabel('Weight')
        ax1.set_title('Strategy Weight Evolution (Stacked)')
        ax1.legend(loc='upper left')
        ax1.grid(True, alpha=0.3)
        ax1.set_ylim(0, 1)

        # 2. 折线图
        ax2 = axes[0, 1]
        for strategy in ['dual_ma', 'momentum', 'rsi']:
            ax2.plot(x, self.weights_history[strategy],
                    label=labels[strategy], color=colors[strategy], linewidth=2)
        ax2.axhline(y=0.33, color='gray', linestyle='--', alpha=0.5, label='Equal (0.33)')
        ax2.set_xlabel('Update #')
        ax2.set_ylabel('Weight')
        ax2.set_title('Strategy Weight Trends')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        ax2.set_ylim(0, 0.8)

        # 3. 当前权重饼图
        ax3 = axes[1, 0]
        if self.weights_history['dual_ma']:
            current_weights = [
                self.weights_history['dual_ma'][-1],
                self.weights_history['momentum'][-1],
                self.weights_history['rsi'][-1]
            ]
            wedges, texts, autotexts = ax3.pie(
                current_weights,
                labels=['Dual MA', 'Momentum', 'RSI'],
                colors=[colors['dual_ma'], colors['momentum'], colors['rsi']],
                autopct='%1.1f%%',
                startangle=90
            )
            ax3.set_title(f'Current Weights\n{self.get_market_regime()}')

        # 4. 权重变化率
        ax4 = axes[1, 1]
        if len(self.timestamps) > 1:
            for strategy in ['dual_ma', 'momentum', 'rsi']:
                weights = self.weights_history[strategy]
                changes = [weights[i] - weights[i-1] for i in range(1, len(weights))]
                ax4.plot(x[1:], changes, label=labels[strategy],
                        color=colors[strategy], linewidth=1.5, alpha=0.8)
            ax4.axhline(y=0, color='black', linestyle='-', alpha=0.3)
            ax4.set_xlabel('Update #')
            ax4.set_ylabel('Weight Change')
            ax4.set_title('Weight Change Rate (Momentum of Weights)')
            ax4.legend()
            ax4.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig('weight_evolution.png', dpi=150, bbox_inches='tight')
        print(f"Chart saved to weight_evolution.png")
        print(f"Market Regime: {self.get_market_regime()}")
        plt.show()

    def monitor_live(self, interval=5):
        """实时监控模式（文本版，不需要GUI）"""
        print("=" * 60)
        print("Strategy Weight Monitor - Live")
        print("=" * 60)
        print(f"Monitoring: {self.log_file}")
        print(f"Update interval: {interval}s")
        print("Press Ctrl+C to stop")
        print("=" * 60)

        try:
            while True:
                updated = self.parse_new_logs()

                if self.timestamps:
                    # 清屏
                    os.system('cls' if os.name == 'nt' else 'clear')

                    print("=" * 60)
                    print("Strategy Weight Monitor - Live")
                    print("=" * 60)

                    # 显示最新权重
                    latest_idx = -1
                    print(f"\nLatest Update: {self.timestamps[latest_idx]}")
                    print(f"Market Regime: {self.get_market_regime()}")
                    print("-" * 40)

                    for strategy in ['dual_ma', 'momentum', 'rsi']:
                        weight = self.weights_history[strategy][latest_idx]
                        bar = "█" * int(weight * 30)
                        print(f"{strategy:12s}: {weight:.3f} {bar}")

                    # 显示历史趋势
                    if len(self.timestamps) > 1:
                        print("\n" + "-" * 40)
                        print("Recent History (last 5 updates):")
                        start_idx = max(0, len(self.timestamps) - 5)
                        for i in range(start_idx, len(self.timestamps)):
                            ts = self.timestamps[i]
                            w = {s: self.weights_history[s][i] for s in ['dual_ma', 'momentum', 'rsi']}
                            dominant = max(w, key=w.get)
                            print(f"  {ts}: M={w['momentum']:.2f} R={w['rsi']:.2f} D={w['dual_ma']:.2f} | {dominant}")

                    print("\n" + "=" * 60)
                    print(f"Total updates: {len(self.timestamps)} | Next refresh in {interval}s")

                time.sleep(interval)

        except KeyboardInterrupt:
            print("\n\nMonitoring stopped.")
            if self.timestamps:
                self.plot_static()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Strategy Weight Visualizer')
    parser.add_argument('--log', default='logs/trading.log', help='Log file path')
    parser.add_argument('--live', action='store_true', help='Live monitoring mode')
    parser.add_argument('--interval', type=int, default=5, help='Update interval (seconds)')
    args = parser.parse_args()

    visualizer = WeightVisualizer(log_file=args.log)

    if args.live:
        visualizer.monitor_live(interval=args.interval)
    else:
        visualizer.plot_static()


if __name__ == '__main__':
    main()
