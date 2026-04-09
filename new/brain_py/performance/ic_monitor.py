"""
IcMonitor - 信息系数监控器

实时监控Alpha信号的预测能力，这是判断策略是否有效的"金标准"。
IC > 0 且越接近1，表示预测能力越强。
"""
import numpy as np
import time
from collections import deque
from typing import Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class SignalRecord:
    """信号记录"""
    timestamp: float
    signal: float
    mid_price: float


@dataclass
class FutureReturn:
    """未来收益记录"""
    timestamp: float
    horizon: str  # '1s', '3s', '5s', etc.
    return_pct: float


class IcMonitor:
    """
    信息系数监控器：计算并记录Alpha信号与未来收益率的相关性

    监控指标：
    - IC (Information Coefficient): 信号与未来收益的相关系数
    - IC Decay: IC随时间衰减曲线
    - Rank IC: 信号排名与未来收益排名的相关系数（更稳健）
    """

    def __init__(self, window: int = 500, max_delay: float = 10.0):
        """
        初始化IC监控器

        Args:
            window: 滚动窗口大小
            max_delay: 最大延迟时间（秒）
        """
        self.window = window
        self.max_delay = max_delay

        # 信号记录
        self.signals: deque = deque(maxlen=window)
        self.timestamps: deque = deque(maxlen=window)

        # 不同时间尺度的未来收益
        self.returns: Dict[str, deque] = {
            '1s': deque(maxlen=window),
            '3s': deque(maxlen=window),
            '5s': deque(maxlen=window)
        }

        # 待计算队列（信号发出后等待未来收益）
        self.pending_signals: deque = deque()

        # 统计
        self.ic_history: Dict[str, deque] = {
            '1s': deque(maxlen=100),
            '3s': deque(maxlen=100),
            '5s': deque(maxlen=100)
        }

    def record_signal(self, alpha_signal: float, mid_price: float):
        """
        记录一个信号（在决策时调用）

        Args:
            alpha_signal: Alpha信号值
            mid_price: 当前中间价
        """
        ts = time.time()

        self.signals.append(alpha_signal)
        self.timestamps.append(ts)

        # 加入待计算队列
        self.pending_signals.append({
            'timestamp': ts,
            'signal': alpha_signal,
            'mid_price': mid_price
        })

    def record_price(self, mid_price: float):
        """
        记录价格更新（持续调用，用于计算未来收益）

        Args:
            mid_price: 当前中间价
        """
        now = time.time()

        # 处理待计算信号
        completed = []
        for pending in self.pending_signals:
            elapsed = now - pending['timestamp']

            # 检查是否到达各个时间尺度的窗口
            for horizon, seconds in [('1s', 1.0), ('3s', 3.0), ('5s', 5.0)]:
                if abs(elapsed - seconds) < 0.1:  # ±0.1秒容差
                    # 计算收益
                    future_return = (mid_price - pending['mid_price']) / pending['mid_price']
                    self.returns[horizon].append(future_return)
                    completed.append(pending)
                    break

            # 超期移除
            if elapsed > self.max_delay:
                completed.append(pending)

        # 移除已完成的
        for c in completed:
            if c in self.pending_signals:
                self.pending_signals.remove(c)

    def get_ic(self, horizon: str = '1s') -> Tuple[float, int]:
        """
        计算指定时间间隔的信息系数(IC)

        Args:
            horizon: 时间尺度 ('1s', '3s', '5s')

        Returns:
            (IC值, 样本数量)
        """
        if horizon not in self.returns:
            return 0.0, 0

        returns = list(self.returns[horizon])
        signals = list(self.signals)[-len(returns):]  # 对齐长度

        if len(signals) < 30:  # 样本太少
            return 0.0, len(signals)

        try:
            # Pearson相关系数
            ic = np.corrcoef(signals, returns)[0, 1]
            if np.isnan(ic):
                ic = 0.0
        except Exception:
            ic = 0.0

        # 记录历史
        self.ic_history[horizon].append(ic)

        return ic, len(signals)

    def get_rank_ic(self, horizon: str = '1s') -> Tuple[float, int]:
        """
        计算Rank IC（更稳健的秩相关系数）
        """
        if horizon not in self.returns:
            return 0.0, 0

        returns = list(self.returns[horizon])
        signals = list(self.signals)[-len(returns):]

        if len(signals) < 30:
            return 0.0, len(signals)

        try:
            from scipy.stats import spearmanr
            rank_ic, _ = spearmanr(signals, returns)
            if np.isnan(rank_ic):
                rank_ic = 0.0
        except ImportError:
            # 如果没有scipy，退化为普通IC
            rank_ic = np.corrcoef(signals, returns)[0, 1]
            if np.isnan(rank_ic):
                rank_ic = 0.0

        return rank_ic, len(signals)

    def get_ic_decay(self) -> Dict:
        """
        获取IC衰减曲线，用于诊断Alpha信号的衰减速度

        Returns:
            {'IC_1s': x, 'IC_3s': y, 'IC_5s': z, 'n_samples': n}
        """
        result = {}
        min_samples = float('inf')

        for horizon in ['1s', '3s', '5s']:
            ic, n = self.get_ic(horizon)
            result[f'IC_{horizon}'] = ic
            min_samples = min(min_samples, n)

        result['n_samples'] = min_samples
        return result

    def get_ic_statistics(self, horizon: str = '1s') -> Dict:
        """
        获取IC的历史统计信息
        """
        history = list(self.ic_history[horizon])
        if not history:
            return {
                'mean': 0.0,
                'std': 0.0,
                'min': 0.0,
                'max': 0.0,
                'ir': 0.0  # Information Ratio
            }

        mean_ic = np.mean(history)
        std_ic = np.std(history)
        ir = mean_ic / std_ic if std_ic > 0 else 0.0

        return {
            'mean': mean_ic,
            'std': std_ic,
            'min': np.min(history),
            'max': np.max(history),
            'ir': ir,
            'count': len(history)
        }

    def is_signal_effective(self, horizon: str = '1s', threshold: float = 0.05) -> bool:
        """
        判断信号是否有效

        Args:
            horizon: 时间尺度
            threshold: IC有效性阈值

        Returns:
            True if IC > threshold and IR > 0.5
        """
        ic, n = self.get_ic(horizon)
        stats = self.get_ic_statistics(horizon)

        if n < 100:
            return False  # 样本不足

        return ic > threshold and stats['ir'] > 0.5

    def reset(self):
        """重置监控器"""
        self.signals.clear()
        self.timestamps.clear()
        self.pending_signals.clear()

        for q in self.returns.values():
            q.clear()

        for q in self.ic_history.values():
            q.clear()


# 测试代码
if __name__ == "__main__":
    print("=" * 60)
    print("IcMonitor Test")
    print("=" * 60)

    monitor = IcMonitor(window=100)

    # 模拟信号和价格
    np.random.seed(42)
    base_price = 50000

    print("\n模拟100个信号和价格更新...")
    for i in range(100):
        # 生成信号（添加一些预测能力）
        true_return = np.random.randn() * 0.001
        signal = np.sign(true_return) * np.random.uniform(0.1, 1.0) + np.random.randn() * 0.3

        # 记录信号
        monitor.record_signal(signal, base_price)

        # 模拟价格移动
        base_price *= (1 + true_return)
        monitor.record_price(base_price)

        # 模拟延迟
        time.sleep(0.01)

    print("\n" + "=" * 60)
    print("IC Results")
    print("=" * 60)

    # 获取IC
    for horizon in ['1s', '3s', '5s']:
        ic, n = monitor.get_ic(horizon)
        stats = monitor.get_ic_statistics(horizon)
        print(f"\n{horizon}:")
        print(f"  Current IC: {ic:.4f}")
        print(f"  Mean IC: {stats['mean']:.4f}")
        print(f"  IC IR: {stats['ir']:.4f}")
        print(f"  Samples: {n}")

    # IC衰减
    print("\n" + "=" * 60)
    print("IC Decay")
    print("=" * 60)
    decay = monitor.get_ic_decay()
    for key, value in decay.items():
        print(f"  {key}: {value:.4f}" if isinstance(value, float) else f"  {key}: {value}")

    # 有效性判断
    print("\n" + "=" * 60)
    print("Signal Effectiveness")
    print("=" * 60)
    effective = monitor.is_signal_effective('1s', threshold=0.05)
    print(f"  Signal effective: {effective}")

    print("\n" + "=" * 60)
    print("Test completed!")
    print("=" * 60)
