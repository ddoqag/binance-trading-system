"""
带硬约束的 SAC 智能体

防止RL学会"作死"行为：
- 过度交易
- 过高撤单率
- 过大仓位变化
- 过短下单间隔
"""

import numpy as np
import torch
from typing import Dict, Optional, Deque, Tuple
from collections import deque
import time
from dataclasses import dataclass


@dataclass
class ConstraintConfig:
    """约束配置"""
    max_order_rate: float = 10.0           # 每秒最多10单
    max_cancel_ratio: float = 0.7          # 撤单率不超过70%
    min_rest_time_ms: float = 50.0         # 最小间隔50ms
    max_position_change: float = 0.1       # 单笔仓位变化不超过10%
    max_daily_trades: int = 1000           # 每日最大交易次数
    max_drawdown_pct: float = 0.15         # 最大回撤15%
    kill_switch_loss: float = -1000.0      # 累计亏损达到此值停止交易


class ActionConstraintLayer:
    """
    动作约束层

    对原始RL输出进行后处理，确保满足风控约束
    """

    def __init__(self, config: ConstraintConfig = None):
        self.config = config or ConstraintConfig()

        # 状态跟踪
        self.recent_actions: Deque[Dict] = deque(maxlen=1000)
        self.last_action_time = 0.0
        self.daily_trade_count = 0
        self.daily_start_time = time.time()
        self.peak_pnl = 0.0
        self.current_pnl = 0.0
        self.kill_switched = False

        # 统计
        self.total_orders = 0
        self.total_cancels = 0

    def reset_daily_stats(self):
        """重置每日统计"""
        current_time = time.time()
        if current_time - self.daily_start_time > 86400:  # 24小时
            self.daily_trade_count = 0
            self.daily_start_time = current_time

    def check_kill_switch(self, current_pnl: float) -> bool:
        """
        检查熔断开关

        Returns:
            bool: 是否触发熔断
        """
        self.current_pnl = current_pnl
        self.peak_pnl = max(self.peak_pnl, current_pnl)

        # 回撤检查
        drawdown = (self.peak_pnl - current_pnl) / max(abs(self.peak_pnl), 1000)
        if drawdown > self.config.max_drawdown_pct:
            self.kill_switched = True
            return True

        # 绝对亏损检查
        if current_pnl < self.config.kill_switch_loss:
            self.kill_switched = True
            return True

        return False

    def calculate_cancel_ratio(self) -> float:
        """计算近期撤单率"""
        if self.total_orders == 0:
            return 0.0
        return self.total_cancels / self.total_orders

    def calculate_order_rate(self, window_sec: float = 1.0) -> float:
        """计算近期下单频率"""
        current_time = time.time()
        recent_count = sum(
            1 for a in self.recent_actions
            if current_time - a['timestamp'] < window_sec
        )
        return recent_count / window_sec

    def apply_constraints(self,
                         raw_action: np.ndarray,
                         current_position: float,
                         current_pnl: float = 0.0) -> Tuple[np.ndarray, Dict]:
        """
        应用约束到原始动作

        Args:
            raw_action: 原始动作 [direction, aggression, size_scale]
            current_position: 当前持仓
            current_pnl: 当前盈亏

        Returns:
            (constrained_action, constraint_info)
        """
        constrained_action = raw_action.copy()
        constraint_info = {
            'constraints_applied': [],
            'raw_action': raw_action.copy(),
            'blocked': False
        }

        # 1. 熔断检查
        if self.kill_switched:
            constrained_action[2] = 0.0  # 不下单
            constraint_info['blocked'] = True
            constraint_info['constraints_applied'].append('kill_switch')
            return constrained_action, constraint_info

        if self.check_kill_switch(current_pnl):
            constrained_action[2] = 0.0
            constraint_info['blocked'] = True
            constraint_info['constraints_applied'].append('kill_switch')
            return constrained_action, constraint_info

        # 2. 每日交易次数限制
        self.reset_daily_stats()
        if self.daily_trade_count >= self.config.max_daily_trades:
            constrained_action[2] = 0.0
            constraint_info['blocked'] = True
            constraint_info['constraints_applied'].append('daily_limit')
            return constrained_action, constraint_info

        # 3. 频率限制（最小间隔）
        current_time = time.time()
        time_since_last = current_time - self.last_action_time
        min_interval = self.config.min_rest_time_ms / 1000.0

        if time_since_last < min_interval:
            constrained_action[2] = 0.0  # 不下单
            constraint_info['blocked'] = True
            constraint_info['constraints_applied'].append('frequency_limit')
            return constrained_action, constraint_info

        # 4. 撤单率限制
        cancel_ratio = self.calculate_cancel_ratio()
        if cancel_ratio > self.config.max_cancel_ratio:
            # 降低攻击性，减少撤单
            constrained_action[1] *= 0.5
            constraint_info['constraints_applied'].append('cancel_ratio')

        # 5. 下单频率限制
        order_rate = self.calculate_order_rate()
        if order_rate > self.config.max_order_rate:
            constrained_action[2] = 0.0
            constraint_info['blocked'] = True
            constraint_info['constraints_applied'].append('order_rate')
            return constrained_action, constraint_info

        # 6. 仓位变化限制
        if abs(constrained_action[2]) > self.config.max_position_change:
            old_size = constrained_action[2]
            constrained_action[2] = np.sign(old_size) * self.config.max_position_change
            constraint_info['constraints_applied'].append('position_limit')

        # 7. 持仓边界检查
        new_position = current_position + constrained_action[0] * constrained_action[2]
        if abs(new_position) > 1.0:  # 假设最大持仓为1.0
            # 限制仓位不超过边界
            max_add = 1.0 - abs(current_position)
            if max_add <= 0:
                constrained_action[2] = 0.0
            else:
                constrained_action[2] = np.sign(constrained_action[2]) * min(
                    abs(constrained_action[2]), max_add
                )
            constraint_info['constraints_applied'].append('position_boundary')

        # 记录动作
        if abs(constrained_action[2]) > 0.001:  # 实际下单
            self.recent_actions.append({
                'timestamp': current_time,
                'action': constrained_action.copy(),
                'position_before': current_position
            })
            self.last_action_time = current_time
            self.total_orders += 1
            self.daily_trade_count += 1

        return constrained_action, constraint_info

    def record_cancel(self):
        """记录撤单"""
        self.total_cancels += 1

    def get_constraint_report(self) -> Dict:
        """获取约束报告"""
        return {
            'kill_switched': self.kill_switched,
            'daily_trades': self.daily_trade_count,
            'cancel_ratio': self.calculate_cancel_ratio(),
            'order_rate': self.calculate_order_rate(),
            'current_drawdown': (self.peak_pnl - self.current_pnl) / max(abs(self.peak_pnl), 1000),
            'total_orders': self.total_orders,
            'total_cancels': self.total_cancels
        }


class ConstrainedSACAgent:
    """
    带硬约束的SAC智能体

    在标准SAC之上添加约束层，防止危险行为
    """

    def __init__(self,
                 state_dim: int = 10,
                 action_dim: int = 3,
                 constraints: Optional[ConstraintConfig] = None,
                 device: str = 'cpu'):

        self.state_dim = state_dim
        self.action_dim = action_dim
        self.device = device

        # 约束层
        self.constraint_layer = ActionConstraintLayer(constraints)

        # 基础SAC网络（简化版，实际应加载训练好的模型）
        self.actor = self._build_actor().to(device)

        # 当前持仓
        self.current_position = 0.0

        # 统计
        self.constraint_stats = {
            'total_predictions': 0,
            'blocked_count': 0,
            'constraint_applications': {}
        }

    def _build_actor(self):
        """构建Actor网络"""
        return torch.nn.Sequential(
            torch.nn.Linear(self.state_dim, 256),
            torch.nn.ReLU(),
            torch.nn.Linear(256, 256),
            torch.nn.ReLU(),
            torch.nn.Linear(256, self.action_dim * 2)  # mean and log_std
        )

    def predict_action(self,
                      state: np.ndarray,
                      current_position: Optional[float] = None,
                      current_pnl: float = 0.0,
                      deterministic: bool = True) -> Tuple[np.ndarray, Dict]:
        """
        预测动作（带约束）

        Args:
            state: 状态向量
            current_position: 当前持仓
            current_pnl: 当前盈亏
            deterministic: 是否确定性输出

        Returns:
            (action, info)
        """
        if current_position is not None:
            self.current_position = current_position

        # 原始SAC输出
        with torch.no_grad():
            state_tensor = torch.tensor(state, dtype=torch.float32).unsqueeze(0).to(self.device)
            output = self.actor(state_tensor)

            mean = output[:, :self.action_dim]
            log_std = torch.clamp(output[:, self.action_dim:], -5, 2)
            std = log_std.exp()

            if deterministic:
                raw_action = mean.cpu().numpy()[0]
            else:
                dist = torch.distributions.Normal(mean, std)
                raw_action = dist.sample().cpu().numpy()[0]

        # 应用tanh到direction和aggression
        raw_action[0] = np.tanh(raw_action[0])  # direction: -1 to 1
        raw_action[1] = np.tanh(raw_action[1]) * 0.5 + 0.5  # aggression: 0 to 1
        raw_action[2] = np.tanh(raw_action[2])  # size_scale: -1 to 1, will be clipped

        # 应用约束
        constrained_action, constraint_info = self.constraint_layer.apply_constraints(
            raw_action, self.current_position, current_pnl
        )

        # 更新统计
        self.constraint_stats['total_predictions'] += 1
        if constraint_info['blocked']:
            self.constraint_stats['blocked_count'] += 1

        for c in constraint_info['constraints_applied']:
            self.constraint_stats['constraint_applications'][c] = \
                self.constraint_stats['constraint_applications'].get(c, 0) + 1

        # 更新持仓（如果是实际交易）
        if abs(constrained_action[2]) > 0.001 and not constraint_info['blocked']:
            self.current_position += constrained_action[0] * constrained_action[2]
            self.current_position = np.clip(self.current_position, -1.0, 1.0)

        info = {
            'raw_action': raw_action,
            'constrained_action': constrained_action,
            'constraint_info': constraint_info,
            'current_position': self.current_position
        }

        return constrained_action, info

    def record_cancel(self):
        """记录撤单"""
        self.constraint_layer.record_cancel()

    def reset_position(self):
        """重置持仓"""
        self.current_position = 0.0

    def get_stats(self) -> Dict:
        """获取统计信息"""
        stats = self.constraint_stats.copy()
        stats['constraint_report'] = self.constraint_layer.get_constraint_report()
        stats['block_rate'] = (
            stats['blocked_count'] / stats['total_predictions']
            if stats['total_predictions'] > 0 else 0
        )
        return stats


class SafetyWrapper:
    """
    安全包装器

    为任何策略添加最后一道安全防线
    """

    def __init__(self,
                 base_strategy,
                 constraints: Optional[ConstraintConfig] = None):
        self.base_strategy = base_strategy
        self.constraint_layer = ActionConstraintLayer(constraints)
        self.emergency_stop = False

    def predict(self, state, **kwargs):
        """安全预测"""
        if self.emergency_stop:
            return np.zeros(3), {'emergency_stop': True}

        # 获取基础策略输出
        action = self.base_strategy.predict(state, **kwargs)

        # 应用安全约束
        current_position = kwargs.get('current_position', 0.0)
        current_pnl = kwargs.get('current_pnl', 0.0)

        constrained_action, info = self.constraint_layer.apply_constraints(
            action, current_position, current_pnl
        )

        if info['blocked']:
            # 检查是否是严重问题
            if 'kill_switch' in info['constraints_applied']:
                self.emergency_stop = True

        return constrained_action, info


# 测试代码
if __name__ == "__main__":
    print("=" * 60)
    print("Constrained SAC Agent Test")
    print("=" * 60)

    # 创建带约束的Agent
    constraints = ConstraintConfig(
        max_order_rate=5.0,          # 每秒最多5单
        max_cancel_ratio=0.5,        # 撤单率不超过50%
        min_rest_time_ms=100.0,      # 最小间隔100ms
        max_position_change=0.2,     # 单笔不超过20%
        max_daily_trades=100
    )

    agent = ConstrainedSACAgent(
        state_dim=10,
        action_dim=3,
        constraints=constraints
    )

    print("\n测试1: 正常交易")
    print("-" * 60)

    # 模拟正常交易
    for i in range(10):
        state = np.random.randn(10)
        action, info = agent.predict_action(state, current_position=0.0)

        if abs(action[2]) > 0.001:
            print(f"Step {i+1}: action={action}, position={info['current_position']:.2f}")

        # 模拟一些时间间隔
        time.sleep(0.02)

    print("\n测试2: 高频交易限制")
    print("-" * 60)

    # 快速连续调用，应该被频率限制
    blocked_count = 0
    for i in range(20):
        state = np.random.randn(10)
        action, info = agent.predict_action(state, current_position=0.0)

        if info['constraint_info']['blocked']:
            blocked_count += 1

    print(f"20次快速调用中，被阻止次数: {blocked_count}")

    print("\n测试3: 仓位限制")
    print("-" * 60)

    agent.reset_position()

    # 尝试快速积累大仓位
    for i in range(20):
        state = np.random.randn(10)
        # 强制买入
        state[0] = 1.0  # 正方向信号
        action, info = agent.predict_action(state, current_position=agent.current_position)

        if i < 5 or i > 15:
            print(f"Step {i+1}: action_size={action[2]:.3f}, position={info['current_position']:.2f}")

        time.sleep(0.15)  # 确保不触发频率限制

    print("\n测试4: 熔断开关")
    print("-" * 60)

    agent.reset_position()

    # 模拟大幅亏损
    action, info = agent.predict_action(
        np.random.randn(10),
        current_position=0.0,
        current_pnl=-1500  # 超过kill_switch_loss
    )

    print(f"大幅亏损后，熔断状态: {info['constraint_info'].get('blocked', False)}")

    # 再次尝试交易
    action2, info2 = agent.predict_action(
        np.random.randn(10),
        current_position=0.0,
        current_pnl=-1500
    )

    print(f"熔断后再次尝试，是否被阻止: {info2['constraint_info'].get('blocked', False)}")

    print("\n" + "=" * 60)
    print("统计报告:")
    print("=" * 60)
    stats = agent.get_stats()
    print(f"总预测次数: {stats['total_predictions']}")
    print(f"被阻止次数: {stats['blocked_count']}")
    print(f"阻止率: {stats['block_rate']:.1%}")
    print(f"\n约束触发次数:")
    for constraint, count in stats['constraint_applications'].items():
        print(f"  {constraint}: {count}")

    print("\n" + "=" * 60)
    print("测试完成")
