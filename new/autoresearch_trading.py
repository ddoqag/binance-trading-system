"""
AutoResearch Trading - 自主交易研究控制器

基于 autoresearch 理念的参数自动优化系统
"""

import os
import sys
import time
import json
import random
import subprocess
import yaml
from datetime import datetime
from typing import Dict, List, Tuple


class TradingAutoResearch:
    """
    自主交易研究控制器

    核心循环：
    1. 读取当前配置和历史结果
    2. 提出新的参数调整方案
    3. 运行30分钟实验
    4. 评估结果
    5. 保留或丢弃
    """

    def __init__(self):
        self.config_file = 'config/signal_evaluation.yaml'
        self.results_file = 'results.tsv'
        self.experiment_duration = 1800  # 30分钟
        self.baseline_metrics = None

        # 可调参数范围
        self.param_ranges = {
            'accuracy_weight': (0.25, 0.45),
            'consistency_weight': (0.30, 0.50),
            'strength_weight': (0.15, 0.35),
            'decay_lambda': (0.6, 0.9),
            'max_single_weight': (0.50, 0.70),
            'exploration_noise': (0.03, 0.08),
        }

    def load_config(self) -> Dict:
        """加载当前配置"""
        with open(self.config_file, 'r') as f:
            return yaml.safe_load(f)

    def save_config(self, config: Dict):
        """保存配置"""
        with open(self.config_file, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)

    def load_results(self) -> List[Dict]:
        """加载历史结果"""
        if not os.path.exists(self.results_file):
            return []

        results = []
        with open(self.results_file, 'r') as f:
            lines = f.readlines()
            if len(lines) < 2:
                return []

            headers = lines[0].strip().split('\t')
            for line in lines[1:]:
                values = line.strip().split('\t')
                if len(values) == len(headers):
                    results.append(dict(zip(headers, values)))

        return results

    def log_result(self, commit: str, metrics: Dict, status: str, description: str):
        """记录实验结果"""
        with open(self.results_file, 'a') as f:
            f.write(f"{commit}\t"
                   f"{metrics.get('stability_score', 0):.2f}\t"
                   f"{metrics.get('effective_n', 0):.2f}\t"
                   f"{metrics.get('hhi', 0):.4f}\t"
                   f"{status}\t"
                   f"{description}\n")

    def generate_experiment_idea(self, history: List[Dict]) -> Tuple[Dict, str]:
        """
        生成新的实验想法

        策略：
        1. 如果没有历史，随机生成
        2. 如果有历史，基于最佳结果微调
        3. 偶尔尝试激进改变
        """
        current_config = self.load_config()

        # 分析历史
        keep_results = [r for r in history if r.get('status') == 'keep']

        if not keep_results or random.random() < 0.3:
            # 随机探索
            new_config = self._random_config()
            description = "random_exploration"
        else:
            # 基于最佳结果微调
            best = max(keep_results, key=lambda x: float(x.get('stability_score', 0)))
            new_config = self._mutate_config(current_config)
            description = f"mutation_from_best_{best.get('commit', 'unknown')[:7]}"

        return new_config, description

    def _random_config(self) -> Dict:
        """生成随机配置"""
        weights = self._normalize_weights([
            random.uniform(*self.param_ranges['accuracy_weight']),
            random.uniform(*self.param_ranges['consistency_weight']),
            random.uniform(*self.param_ranges['strength_weight'])
        ])

        return {
            'signal_scoring': {
                'weights': {
                    'accuracy': weights[0],
                    'consistency': weights[1],
                    'strength': weights[2]
                },
                'decay_lambda': random.uniform(*self.param_ranges['decay_lambda']),
                'max_single_weight': random.uniform(*self.param_ranges['max_single_weight']),
                'exploration_noise': random.uniform(*self.param_ranges['exploration_noise'])
            }
        }

    def _mutate_config(self, config: Dict) -> Dict:
        """对现有配置进行微调"""
        new_config = json.loads(json.dumps(config))  # 深拷贝

        # 随机选择一个参数进行微调
        param = random.choice(['accuracy', 'consistency', 'strength'])
        current = new_config['signal_scoring']['weights'][param]
        delta = random.uniform(-0.05, 0.05)
        new_config['signal_scoring']['weights'][param] = max(0.1, min(0.6, current + delta))

        # 重新归一化
        weights = new_config['signal_scoring']['weights']
        total = sum(weights.values())
        for k in weights:
            weights[k] /= total

        return new_config

    def _normalize_weights(self, weights: List[float]) -> List[float]:
        """归一化权重"""
        total = sum(weights)
        return [w / total for w in weights]

    def run_experiment(self) -> Dict:
        """
        运行单次实验

        Returns:
            实验指标
        """
        print(f"[{datetime.now()}] Starting experiment...")

        # 启动交易系统
        proc = subprocess.Popen(
            ['python', 'start_trader.py', '--duration', str(self.experiment_duration), '--no-resume'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # 等待完成
        try:
            stdout, stderr = proc.communicate(timeout=self.experiment_duration + 300)
        except subprocess.TimeoutExpired:
            proc.kill()
            return {'error': 'timeout'}

        # 解析结果
        metrics = self._parse_experiment_output(stdout.decode())

        return metrics

    def _parse_experiment_output(self, output: str) -> Dict:
        """解析实验输出"""
        metrics = {
            'stability_score': 0,
            'effective_n': 0,
            'hhi': 0,
        }

        # 从日志中提取指标
        # 这里简化处理，实际应该从 stability_monitor 获取
        try:
            # 运行报告生成脚本
            result = subprocess.run(
                ['python', 'generate_report.py'],
                capture_output=True,
                text=True,
                timeout=30
            )

            # 解析报告
            if os.path.exists('reports/6strategies_report.json'):
                with open('reports/6strategies_report.json', 'r') as f:
                    report = json.load(f)

                # 提取关键指标
                health = report.get('系统健康指标', {})
                metrics['hhi'] = health.get('平均集中度指数(HHI)', 0)
                metrics['effective_n'] = health.get('平均有效策略数', 0)

                # 计算稳定性评分
                hhi = metrics['hhi']
                score = 0
                if 0.15 <= hhi <= 0.25:
                    score += 40
                if metrics['effective_n'] >= 4:
                    score += 30
                metrics['stability_score'] = score

        except Exception as e:
            print(f"Error parsing results: {e}")

        return metrics

    def evaluate_result(self, metrics: Dict, history: List[Dict]) -> str:
        """
        评估实验结果

        Returns:
            'keep', 'discard', or 'crash'
        """
        if 'error' in metrics:
            return 'crash'

        stability = metrics.get('stability_score', 0)

        # 与历史最佳比较
        keep_results = [r for r in history if r.get('status') == 'keep']
        if keep_results:
            best_stability = max(float(r.get('stability_score', 0)) for r in keep_results)
            if stability >= best_stability - 5:  # 允许5分误差
                return 'keep'
        elif stability >= 60:  # 第一次运行，基准线60
            return 'keep'

        return 'discard'

    def run(self):
        """主循环"""
        print("=" * 70)
        print("AutoResearch Trading - 自主交易研究")
        print("=" * 70)

        # 初始化
        if not os.path.exists(self.results_file):
            with open(self.results_file, 'w') as f:
                f.write("commit\tstability_score\teffective_n\thhi\tstatus\tdescription\n")

        history = self.load_results()
        print(f"Loaded {len(history)} historical experiments")

        experiment_count = 0

        while True:
            experiment_count += 1
            print(f"\n{'='*70}")
            print(f"Experiment #{experiment_count}")
            print(f"{'='*70}")

            # 1. 生成实验想法
            new_config, description = self.generate_experiment_idea(history)
            print(f"Description: {description}")

            # 2. 保存配置
            self.save_config(new_config)

            # 3. 提交配置
            subprocess.run(['git', 'add', self.config_file])
            subprocess.run(['git', 'commit', '-m', f'experiment: {description}'])
            result = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'],
                                  capture_output=True, text=True)
            commit = result.stdout.strip()

            # 4. 运行实验
            metrics = self.run_experiment()
            print(f"Results: {metrics}")

            # 5. 评估结果
            status = self.evaluate_result(metrics, history)
            print(f"Status: {status.upper()}")

            # 6. 记录结果
            self.log_result(commit, metrics, status, description)

            # 7. 保留或丢弃
            if status == 'keep':
                print("✅ Keeping this experiment")
                history = self.load_results()  # 刷新历史
            elif status == 'discard':
                print("❌ Discarding, reverting...")
                subprocess.run(['git', 'reset', '--hard', 'HEAD~1'])
            else:  # crash
                print("💥 Crash recorded, continuing...")
                subprocess.run(['git', 'reset', '--hard', 'HEAD~1'])

            print(f"\nCompleted experiment #{experiment_count}")
            print(f"Next experiment in 10 seconds... (Ctrl+C to stop)")
            time.sleep(10)


if __name__ == '__main__':
    try:
        researcher = TradingAutoResearch()
        researcher.run()
    except KeyboardInterrupt:
        print("\n\nStopped by user")
        sys.exit(0)
