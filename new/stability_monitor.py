"""
稳定性监控器 - 监控策略权重演变和市场状态变化
"""

import json
import time
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional
from collections import deque
import os


class StabilityMonitor:
    """
    监控策略权重稳定性和市场状态变化
    """

    def __init__(self, log_file='logs/stability_monitor.log', max_history=200):
        self.log_file = log_file
        self.max_history = max_history

        # 权重历史
        self.weight_history: List[Dict[str, float]] = []
        self.timestamps: List[str] = []

        # 市场状态历史
        self.regime_history: List[str] = []

        # 统计指标
        self.metrics = {
            'weight_volatility': {},  # 权重波动率
            'regime_changes': 0,      # 状态切换次数
            'dominant_strategy': [],  # 主导策略历史
            'concentration_index': []  # Herfindahl指数
        }

        # 创建日志目录
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

    def record_weights(self, weights: Dict[str, float], timestamp: Optional[str] = None):
        """记录权重快照"""
        if timestamp is None:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        self.weight_history.append(weights.copy())
        self.timestamps.append(timestamp)

        # 限制历史长度
        if len(self.weight_history) > self.max_history:
            self.weight_history.pop(0)
            self.timestamps.pop(0)

        # 检测市场状态
        regime = self._detect_regime(weights)
        self.regime_history.append(regime)

        # 计算集中度
        herfindahl = sum(w ** 2 for w in weights.values())
        self.metrics['concentration_index'].append(herfindahl)

        # 记录主导策略
        dominant = max(weights, key=weights.get)
        self.metrics['dominant_strategy'].append(dominant)

        # 检测状态切换
        if len(self.regime_history) > 1:
            if self.regime_history[-1] != self.regime_history[-2]:
                self.metrics['regime_changes'] += 1

        # 计算权重波动率
        self._calculate_weight_volatility()

        # 记录到日志
        self._log_snapshot(weights, regime, herfindahl)

    def _detect_regime(self, weights: Dict[str, float]) -> str:
        """检测当前市场状态"""
        # 波动率策略权重
        vol_weight = weights.get('bollinger_bands', 0) + weights.get('volatility_breakout', 0)

        # 趋势策略权重
        trend_weight = weights.get('dual_ma', 0) + weights.get('momentum', 0)

        # 反转策略权重
        reversal_weight = weights.get('rsi', 0)

        # ML策略权重
        ml_weight = weights.get('ml_momentum', 0)

        # 判断市场状态
        if vol_weight > 0.5:
            return "high_volatility"
        elif trend_weight > 0.5:
            return "trending"
        elif reversal_weight > 0.3:
            return "ranging"
        elif ml_weight > 0.3:
            return "ml_driven"
        else:
            return "mixed"

    def _calculate_weight_volatility(self):
        """计算各策略权重的波动率"""
        if len(self.weight_history) < 10:
            return

        # 获取最近10个权重
        recent = self.weight_history[-10:]

        # 计算每个策略的标准差
        for strategy in recent[0].keys():
            values = [w.get(strategy, 0) for w in recent]
            self.metrics['weight_volatility'][strategy] = float(np.std(values))

    def _log_snapshot(self, weights: Dict[str, float], regime: str, herfindahl: float):
        """记录快照到日志"""
        snapshot = {
            'timestamp': self.timestamps[-1],
            'weights': weights,
            'regime': regime,
            'herfindahl': herfindahl,
            'dominant': self.metrics['dominant_strategy'][-1],
            'regime_changes': self.metrics['regime_changes']
        }

        with open(self.log_file, 'a') as f:
            f.write(json.dumps(snapshot) + '\n')

    def get_stability_report(self) -> Dict:
        """生成稳定性报告"""
        if len(self.weight_history) < 2:
            return {'error': 'Insufficient data'}

        report = {
            'total_updates': len(self.weight_history),
            'time_span': f"{self.timestamps[0]} to {self.timestamps[-1]}",
            'current_regime': self.regime_history[-1] if self.regime_history else 'unknown',
            'regime_changes': self.metrics['regime_changes'],
            'regime_distribution': self._get_regime_distribution(),
            'weight_volatility': self.metrics['weight_volatility'],
            'current_concentration': self.metrics['concentration_index'][-1] if self.metrics['concentration_index'] else 0,
            'avg_concentration': float(np.mean(self.metrics['concentration_index'])) if self.metrics['concentration_index'] else 0,
            'dominant_strategy_history': self._get_dominant_frequency(),
            'stability_score': self._calculate_stability_score()
        }

        return report

    def _get_regime_distribution(self) -> Dict[str, int]:
        """获取市场状态分布"""
        distribution = {}
        for regime in self.regime_history:
            distribution[regime] = distribution.get(regime, 0) + 1
        return distribution

    def _get_dominant_frequency(self) -> Dict[str, int]:
        """获取主导策略频率"""
        frequency = {}
        for strategy in self.metrics['dominant_strategy']:
            frequency[strategy] = frequency.get(strategy, 0) + 1
        return frequency

    def _calculate_stability_score(self) -> float:
        """
        计算稳定性评分 (0-100)

        考虑因素：
        - 权重波动率（越低越好）
        - 状态切换频率（越低越好）
        - 集中度合理性（中等最好）
        """
        if len(self.weight_history) < 10:
            return 50.0  # 默认中等

        score = 100.0

        # 1. 权重波动率惩罚
        avg_volatility = np.mean(list(self.metrics['weight_volatility'].values()))
        score -= avg_volatility * 200  # 波动率0.1 = 扣20分

        # 2. 状态切换惩罚
        regime_change_rate = self.metrics['regime_changes'] / len(self.regime_history)
        score -= regime_change_rate * 50  # 频繁切换扣分

        # 3. 集中度合理性
        avg_conc = np.mean(self.metrics['concentration_index'])
        if avg_conc > 0.5:  # 过度集中
            score -= (avg_conc - 0.5) * 100
        elif avg_conc < 0.25:  # 过度分散
            score -= (0.25 - avg_conc) * 100

        return max(0, min(100, score))

    def check_alerts(self) -> List[str]:
        """检查警报条件"""
        alerts = []

        if len(self.weight_history) < 5:
            return alerts

        current_weights = self.weight_history[-1]

        # 1. 检查过度集中
        max_weight = max(current_weights.values())
        if max_weight > 0.6:
            alerts.append(f"WARNING: High concentration - {max(current_weights, key=current_weights.get)} at {max_weight:.1%}")

        # 2. 检查过度分散
        if max_weight < 0.25:
            alerts.append(f"WARNING: Over diversification - max weight only {max_weight:.1%}")

        # 3. 检查频繁状态切换
        if len(self.regime_history) >= 10:
            recent_changes = sum(1 for i in range(-10, -1)
                               if self.regime_history[i] != self.regime_history[i+1])
            if recent_changes > 5:
                alerts.append(f"WARNING: Frequent regime changes - {recent_changes} in last 10 updates")

        # 4. 检查权重波动过大
        for strategy, volatility in self.metrics['weight_volatility'].items():
            if volatility > 0.15:
                alerts.append(f"WARNING: High weight volatility for {strategy} - {volatility:.3f}")

        return alerts

    def print_report(self):
        """打印报告"""
        report = self.get_stability_report()

        print("\n" + "=" * 60)
        print("Strategy Weight Stability Report")
        print("=" * 60)
        print(f"Total Updates: {report['total_updates']}")
        print(f"Time Span: {report['time_span']}")
        print(f"\nCurrent Market Regime: {report['current_regime'].upper()}")
        print(f"Regime Changes: {report['regime_changes']}")
        print(f"\nRegime Distribution:")
        for regime, count in report['regime_distribution'].items():
            pct = count / report['total_updates'] * 100
            print(f"  {regime}: {count} ({pct:.1f}%)")

        print(f"\nWeight Volatility (Std Dev):")
        for strategy, vol in report['weight_volatility'].items():
            print(f"  {strategy}: {vol:.4f}")

        print(f"\nConcentration Index:")
        print(f"  Current: {report['current_concentration']:.3f}")
        print(f"  Average: {report['avg_concentration']:.3f}")

        print(f"\nDominant Strategy Frequency:")
        for strategy, count in report['dominant_strategy_history'].items():
            pct = count / report['total_updates'] * 100
            print(f"  {strategy}: {count} ({pct:.1f}%)")

        print(f"\nStability Score: {report['stability_score']:.1f}/100")

        alerts = self.check_alerts()
        if alerts:
            print(f"\n⚠️  ALERTS:")
            for alert in alerts:
                print(f"  {alert}")
        else:
            print(f"\n✅ No alerts - system stable")

        print("=" * 60)


def main():
    """测试监控器"""
    monitor = StabilityMonitor()

    # 模拟数据
    for i in range(20):
        weights = {
            'dual_ma': 0.2 + np.random.randn() * 0.05,
            'momentum': 0.2 + np.random.randn() * 0.05,
            'rsi': 0.2 + np.random.randn() * 0.05,
            'bollinger_bands': 0.2 + np.random.randn() * 0.05,
            'volatility_breakout': 0.2 + np.random.randn() * 0.05
        }

        # 归一化
        total = sum(weights.values())
        weights = {k: max(0.05, v / total) for k, v in weights.items()}

        monitor.record_weights(weights)
        time.sleep(0.1)

    monitor.print_report()


if __name__ == '__main__':
    main()
