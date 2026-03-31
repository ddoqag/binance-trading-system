"""
execution_sac.py - SAC-based Execution Optimization Agent

Provides:
- ExecutionSACAgent: SAC智能体用于执行优化
- Order: 订单数据结构
- ExecutionPlan: 执行计划
- MarketState: 市场状态
- SACConfig: SAC配置

Features:
- 大单拆分优化
- 滑点最小化
- TWAP/VWAP策略支持
- 连续动作空间优化
"""

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass, field
from enum import IntEnum
from collections import deque
import os
from datetime import datetime


class ExecutionStrategy(IntEnum):
    """执行策略类型."""
    MARKET = 0      # 市价单
    TWAP = 1        # 时间加权平均价格
    VWAP = 2        # 成交量加权平均价格
    ADAPTIVE = 3    # 自适应策略


@dataclass
class Order:
    """订单数据结构."""
    symbol: str
    side: str  # 'buy' or 'sell'
    size: float
    price: Optional[float] = None
    order_type: str = 'market'  # 'market', 'limit'
    max_slippage: float = 0.001  # 最大允许滑点 (0.1%)
    urgency: float = 0.5  # 紧急程度 0-1

    def __post_init__(self):
        assert self.side in ['buy', 'sell'], f"Invalid side: {self.side}"
        assert self.size > 0, "Order size must be positive"
        assert 0 <= self.urgency <= 1, "Urgency must be in [0, 1]"


@dataclass
class MarketState:
    """市场状态."""
    mid_price: float
    spread: float
    bid_volume: float
    ask_volume: float
    recent_trades: List[Dict] = field(default_factory=list)
    volatility: float = 0.0
    trend: float = 0.0
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())

    def get_ofi(self) -> float:
        """计算订单流不平衡 (Order Flow Imbalance)."""
        total_volume = self.bid_volume + self.ask_volume
        if total_volume == 0:
            return 0.0
        return (self.bid_volume - self.ask_volume) / total_volume

    def get_liquidity_score(self) -> float:
        """计算流动性评分 0-1."""
        total_volume = self.bid_volume + self.ask_volume
        # 假设 1000 units 为正常流动性
        score = min(total_volume / 1000.0, 1.0)
        return score


@dataclass
class ExecutionSlice:
    """执行切片."""
    size: float
    price: Optional[float]
    delay_ms: int  # 延迟毫秒
    order_type: str
    timestamp: float


@dataclass
class ExecutionPlan:
    """执行计划."""
    order: Order
    strategy: ExecutionStrategy
    slices: List[ExecutionSlice] = field(default_factory=list)
    expected_slippage: float = 0.0
    expected_completion_time_ms: int = 0
    confidence: float = 0.0

    def get_total_size(self) -> float:
        """获取总执行数量."""
        return sum(s.size for s in self.slices)

    def get_average_price(self) -> float:
        """获取加权平均价格."""
        total_value = sum(s.size * (s.price or 0) for s in self.slices)
        total_size = self.get_total_size()
        if total_size == 0:
            return 0.0
        return total_value / total_size


@dataclass
class Experience:
    """训练经验."""
    state: np.ndarray
    action: np.ndarray
    reward: float
    next_state: np.ndarray
    done: bool
    info: Dict = field(default_factory=dict)


@dataclass
class SACConfig:
    """SAC配置."""
    state_dim: int = 10
    action_dim: int = 3  # [slice_ratio, delay_factor, price_offset]
    hidden_dim: int = 256
    lr: float = 3e-4
    gamma: float = 0.99
    tau: float = 0.005
    alpha: float = 0.2
    buffer_size: int = 100000
    batch_size: int = 64
    target_entropy: float = -3.0
    update_interval: int = 1
    checkpoint_dir: str = "checkpoints/execution"
    min_slice_size: float = 0.01  # 最小切片大小
    max_slices: int = 10  # 最大切片数


class ReplayBuffer:
    """经验回放缓冲区."""

    def __init__(self, capacity: int, state_dim: int, action_dim: int):
        self.capacity = capacity
        self.state_dim = state_dim
        self.action_dim = action_dim

        self.states = np.zeros((capacity, state_dim), dtype=np.float32)
        self.actions = np.zeros((capacity, action_dim), dtype=np.float32)
        self.rewards = np.zeros((capacity, 1), dtype=np.float32)
        self.next_states = np.zeros((capacity, state_dim), dtype=np.float32)
        self.dones = np.zeros((capacity, 1), dtype=np.float32)

        self.ptr = 0
        self.size = 0

    def push(self, state: np.ndarray, action: np.ndarray, reward: float,
             next_state: np.ndarray, done: bool):
        """添加经验."""
        idx = self.ptr % self.capacity

        self.states[idx] = state
        self.actions[idx] = action
        self.rewards[idx] = reward
        self.next_states[idx] = next_state
        self.dones[idx] = done

        self.ptr += 1
        self.size = min(self.size + 1, self.capacity)

    def sample(self, batch_size: int) -> Tuple[torch.Tensor, ...]:
        """采样批次."""
        indices = np.random.randint(0, self.size, size=batch_size)

        return (
            torch.FloatTensor(self.states[indices]),
            torch.FloatTensor(self.actions[indices]),
            torch.FloatTensor(self.rewards[indices]),
            torch.FloatTensor(self.next_states[indices]),
            torch.FloatTensor(self.dones[indices]),
        )

    def __len__(self):
        return self.size


class Actor(nn.Module):
    """策略网络 (高斯策略)."""

    def __init__(self, state_dim: int, action_dim: int, hidden_dim: int = 256):
        super().__init__()

        self.net = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
        )

        self.mean = nn.Linear(hidden_dim, action_dim)
        self.log_std = nn.Linear(hidden_dim, action_dim)

    def forward(self, state: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """返回动作分布的mean和log_std."""
        x = self.net(state)
        mean = self.mean(x)
        log_std = torch.clamp(self.log_std(x), -20, 2)
        return mean, log_std

    def sample(self, state: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """采样动作并计算log概率."""
        mean, log_std = self.forward(state)
        std = log_std.exp()

        # 重参数化技巧
        noise = torch.randn_like(mean)
        action = mean + std * noise

        # 计算log概率
        log_prob = -0.5 * (((action - mean) / (std + 1e-8)) ** 2 + 2 * log_std + np.log(2 * np.pi))
        log_prob = log_prob.sum(dim=-1, keepdim=True)

        # 应用tanh并调整log_prob
        action_tanh = torch.tanh(action)
        log_prob -= torch.log(1 - action_tanh.pow(2) + 1e-6).sum(dim=-1, keepdim=True)

        return action_tanh, log_prob


class Critic(nn.Module):
    """Q函数近似器."""

    def __init__(self, state_dim: int, action_dim: int, hidden_dim: int = 256):
        super().__init__()

        self.net = nn.Sequential(
            nn.Linear(state_dim + action_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, state: torch.Tensor, action: torch.Tensor) -> torch.Tensor:
        """返回Q值估计."""
        x = torch.cat([state, action], dim=-1)
        return self.net(x)


class ExecutionSACAgent:
    """
    SAC执行优化智能体.

    连续动作空间:
    - action[0]: slice_ratio (0-1) - 切片比例
    - action[1]: delay_factor (0-1) - 延迟因子
    - action[2]: price_offset (-1 to 1) - 价格偏移

    动作映射:
    - slice_ratio > 0.7: 大单拆分
    - slice_ratio <= 0.7: 小单直接执行
    - delay_factor: 控制执行速度 (TWAP间隔)
    - price_offset: 限价单价格偏移
    """

    def __init__(self, config: SACConfig = None):
        self.config = config or SACConfig()
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # 网络
        self.actor = Actor(
            self.config.state_dim,
            self.config.action_dim,
            self.config.hidden_dim
        ).to(self.device)

        self.critic1 = Critic(
            self.config.state_dim,
            self.config.action_dim,
            self.config.hidden_dim
        ).to(self.device)

        self.critic2 = Critic(
            self.config.state_dim,
            self.config.action_dim,
            self.config.hidden_dim
        ).to(self.device)

        # 目标网络
        self.target_critic1 = Critic(
            self.config.state_dim,
            self.config.action_dim,
            self.config.hidden_dim
        ).to(self.device)
        self.target_critic2 = Critic(
            self.config.state_dim,
            self.config.action_dim,
            self.config.hidden_dim
        ).to(self.device)

        self.target_critic1.load_state_dict(self.critic1.state_dict())
        self.target_critic2.load_state_dict(self.critic2.state_dict())

        # 优化器
        self.actor_opt = optim.Adam(self.actor.parameters(), lr=self.config.lr)
        self.critic1_opt = optim.Adam(self.critic1.parameters(), lr=self.config.lr)
        self.critic2_opt = optim.Adam(self.critic2.parameters(), lr=self.config.lr)

        # 自动熵调整
        self.log_alpha = torch.zeros(1, requires_grad=True, device=self.device)
        self.alpha_opt = optim.Adam([self.log_alpha], lr=self.config.lr)
        self.target_entropy = self.config.target_entropy

        # 回放缓冲区
        self.replay_buffer = ReplayBuffer(
            self.config.buffer_size,
            self.config.state_dim,
            self.config.action_dim
        )

        # 训练状态
        self.train_step = 0
        self.episode_rewards = deque(maxlen=100)

        # 创建检查点目录
        os.makedirs(self.config.checkpoint_dir, exist_ok=True)

        # 执行统计
        self.execution_stats = {
            'total_orders': 0,
            'total_slices': 0,
            'avg_slippage': 0.0,
            'avg_completion_time': 0.0,
        }

    def _build_state(self, order: Order, market: MarketState,
                     remaining_size: float, elapsed_ms: int) -> np.ndarray:
        """构建状态向量."""
        state = np.zeros(self.config.state_dim, dtype=np.float32)

        # 订单特征
        state[0] = np.log10(order.size + 1) / 10.0  # 订单大小 (log scale)
        state[1] = 1.0 if order.side == 'buy' else -1.0  # 方向
        state[2] = order.urgency  # 紧急程度
        state[3] = remaining_size / order.size if order.size > 0 else 0.0  # 剩余比例

        # 市场特征
        state[4] = market.get_ofi()  # 订单流不平衡
        state[5] = market.get_liquidity_score()  # 流动性评分
        state[6] = market.volatility  # 波动率
        state[7] = market.trend  # 趋势

        # 执行状态
        state[8] = min(elapsed_ms / 60000.0, 1.0)  # 已用时间 (归一化到1分钟)
        state[9] = market.spread / market.mid_price if market.mid_price > 0 else 0.0  # 相对价差

        return state

    def act(self, state: np.ndarray, deterministic: bool = False) -> np.ndarray:
        """
        根据状态选择动作.

        Args:
            state: 当前状态
            deterministic: 是否确定性选择

        Returns:
            动作向量 [slice_ratio, delay_factor, price_offset]
        """
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)

            if deterministic:
                mean, _ = self.actor(state_tensor)
                action = torch.tanh(mean)
            else:
                action, _ = self.actor.sample(state_tensor)

            return action.cpu().numpy()[0]

    def optimize_execution(self, order: Order, market: MarketState) -> ExecutionPlan:
        """
        优化订单执行.

        Args:
            order: 订单
            market: 市场状态

        Returns:
            执行计划
        """
        remaining_size = order.size
        elapsed_ms = 0
        slices = []

        # 构建初始状态
        state = self._build_state(order, market, remaining_size, elapsed_ms)

        # 选择策略
        action = self.act(state, deterministic=False)
        slice_ratio, delay_factor, price_offset = action

        # 映射到实际值
        slice_ratio = (slice_ratio + 1) / 2  # [-1, 1] -> [0, 1]
        delay_factor = (delay_factor + 1) / 2  # [-1, 1] -> [0, 1]

        # 确定策略类型
        if slice_ratio > 0.7 and order.size > self.config.min_slice_size * 3:
            strategy = ExecutionStrategy.TWAP if delay_factor > 0.5 else ExecutionStrategy.VWAP
        elif delay_factor > 0.8:
            strategy = ExecutionStrategy.MARKET
        else:
            strategy = ExecutionStrategy.ADAPTIVE

        # 生成执行切片
        max_slices = min(self.config.max_slices, int(order.size / self.config.min_slice_size))
        n_slices = max(1, int(max_slices * slice_ratio))

        base_slice_size = order.size / n_slices

        for i in range(n_slices):
            # 根据市场条件调整切片大小
            if strategy == ExecutionStrategy.VWAP:
                # VWAP: 根据成交量分布调整
                volume_weight = self._get_vwap_weight(i, n_slices, market)
                slice_size = base_slice_size * volume_weight * n_slices
            else:
                slice_size = base_slice_size

            slice_size = min(slice_size, remaining_size)
            if slice_size <= 0:
                break

            # 计算延迟
            if strategy == ExecutionStrategy.TWAP:
                delay_ms = int(1000 * delay_factor * 10)  # 0-10秒间隔
            elif strategy == ExecutionStrategy.MARKET:
                delay_ms = 0
            else:
                delay_ms = int(1000 * delay_factor * 5)

            # 计算价格
            if order.order_type == 'limit':
                price_offset_actual = price_offset * market.spread * 0.5
                if order.side == 'buy':
                    price = market.mid_price + price_offset_actual
                else:
                    price = market.mid_price - price_offset_actual
            else:
                price = None

            slice_obj = ExecutionSlice(
                size=round(slice_size, 8),
                price=round(price, 8) if price else None,
                delay_ms=delay_ms,
                order_type=order.order_type,
                timestamp=market.timestamp + elapsed_ms / 1000.0
            )
            slices.append(slice_obj)

            remaining_size -= slice_size
            elapsed_ms += delay_ms

            if remaining_size <= 0:
                break

        # 计算预期滑点和完成时间
        expected_slippage = self._estimate_slippage(order, market, strategy, slices)
        expected_completion_time = sum(s.delay_ms for s in slices)

        plan = ExecutionPlan(
            order=order,
            strategy=strategy,
            slices=slices,
            expected_slippage=expected_slippage,
            expected_completion_time_ms=expected_completion_time,
            confidence=abs(slice_ratio - 0.5) * 2  # 越极端越有信心
        )

        # 更新统计
        self.execution_stats['total_orders'] += 1
        self.execution_stats['total_slices'] += len(slices)

        return plan

    def _get_vwap_weight(self, slice_idx: int, total_slices: int, market: MarketState) -> float:
        """获取VWAP权重 (基于成交量分布)."""
        # 简化模型: 假设成交量在时间段内呈U型分布
        # 开盘和收盘成交量大，中间小
        x = slice_idx / (total_slices - 1) if total_slices > 1 else 0.5
        # 使用cos函数创建U型分布: 两端高，中间低
        # cos(0)=1, cos(π/2)=0, cos(π)=-1
        # weight = 0.5 + 0.5 * cos(π * x) 这样x=0时weight=1, x=0.5时weight=0.5, x=1时weight=0 (不是U型)
        # 正确U型: weight = 1 - 0.5 * sin(π * x) 这样x=0时weight=1, x=0.5时weight=0.5, x=1时weight=1
        weight = 1.0 - 0.5 * np.sin(np.pi * x)  # U型分布: 两端=1.0, 中间=0.5
        return weight

    def _estimate_slippage(self, order: Order, market: MarketState,
                          strategy: ExecutionStrategy, slices: List[ExecutionSlice]) -> float:
        """估计滑点."""
        if not slices:
            return 0.0

        base_slippage = 0.0001  # 基础滑点 0.01%

        # 根据策略调整
        if strategy == ExecutionStrategy.MARKET:
            strategy_factor = 2.0
        elif strategy == ExecutionStrategy.TWAP:
            strategy_factor = 0.8
        elif strategy == ExecutionStrategy.VWAP:
            strategy_factor = 0.7
        else:
            strategy_factor = 1.0

        # 根据订单大小调整
        size_factor = 1.0 + (order.size / 10.0)  # 假设10 units为基准

        # 根据流动性调整
        liquidity_factor = 1.0 / (market.get_liquidity_score() + 0.1)

        # 根据波动率调整
        vol_factor = 1.0 + market.volatility

        estimated_slippage = base_slippage * strategy_factor * size_factor * liquidity_factor * vol_factor

        return min(estimated_slippage, order.max_slippage)

    def compute_reward(self, plan: ExecutionPlan, actual_slippage: float,
                       completion_time_ms: int) -> float:
        """
        计算执行奖励.

        奖励组成:
        - 滑点惩罚
        - 时间惩罚
        - 完成奖励
        """
        # 滑点奖励 (负值)
        slippage_penalty = -actual_slippage * 1000  # 放大

        # 时间惩罚
        time_penalty = -completion_time_ms / 10000.0  # 归一化

        # 策略奖励 (相比市价单的改进)
        market_slippage_estimate = plan.expected_slippage * 1.5  # 假设市价单滑点更高
        improvement = market_slippage_estimate - actual_slippage
        improvement_reward = improvement * 500  # 放大改进奖励

        total_reward = slippage_penalty + time_penalty + improvement_reward

        return total_reward

    def train(self, experiences: List[Experience]) -> Dict[str, float]:
        """
        使用经验训练智能体.

        Args:
            experiences: 经验列表

        Returns:
            训练指标
        """
        # 添加到回放缓冲区
        for exp in experiences:
            self.replay_buffer.push(
                exp.state, exp.action, exp.reward,
                exp.next_state, exp.done
            )

        # 执行更新
        if len(self.replay_buffer) < self.config.batch_size:
            return {}

        metrics = self._update()
        return metrics

    def _update(self) -> Dict[str, float]:
        """执行一次梯度更新."""
        # 采样批次
        states, actions, rewards, next_states, dones = \
            self.replay_buffer.sample(self.config.batch_size)

        states = states.to(self.device)
        actions = actions.to(self.device)
        rewards = rewards.to(self.device)
        next_states = next_states.to(self.device)
        dones = dones.to(self.device)

        # 当前alpha
        alpha = self.log_alpha.exp()

        # 更新critic
        with torch.no_grad():
            next_actions, next_log_probs = self.actor.sample(next_states)
            q1_next = self.target_critic1(next_states, next_actions)
            q2_next = self.target_critic2(next_states, next_actions)
            q_next = torch.min(q1_next, q2_next) - alpha * next_log_probs
            q_target = rewards + (1 - dones) * self.config.gamma * q_next

        q1 = self.critic1(states, actions)
        q2 = self.critic2(states, actions)

        critic1_loss = F.mse_loss(q1, q_target)
        critic2_loss = F.mse_loss(q2, q_target)

        self.critic1_opt.zero_grad()
        critic1_loss.backward()
        self.critic1_opt.step()

        self.critic2_opt.zero_grad()
        critic2_loss.backward()
        self.critic2_opt.step()

        # 更新actor
        new_actions, log_probs = self.actor.sample(states)
        q1_new = self.critic1(states, new_actions)
        q2_new = self.critic2(states, new_actions)
        q_new = torch.min(q1_new, q2_new)

        actor_loss = (alpha * log_probs - q_new).mean()

        self.actor_opt.zero_grad()
        actor_loss.backward()
        self.actor_opt.step()

        # 更新alpha
        alpha_loss = -(self.log_alpha * (log_probs + self.target_entropy).detach()).mean()

        self.alpha_opt.zero_grad()
        alpha_loss.backward()
        self.alpha_opt.step()

        # 软更新目标网络
        self._soft_update(self.target_critic1, self.critic1)
        self._soft_update(self.target_critic2, self.critic2)

        self.train_step += 1

        return {
            "critic1_loss": critic1_loss.item(),
            "critic2_loss": critic2_loss.item(),
            "actor_loss": actor_loss.item(),
            "alpha": alpha.item(),
        }

    def _soft_update(self, target: nn.Module, source: nn.Module):
        """软更新目标网络参数."""
        for target_param, param in zip(target.parameters(), source.parameters()):
            target_param.data.copy_(
                target_param.data * (1.0 - self.config.tau) + param.data * self.config.tau
            )

    def save(self, filename: str = None):
        """保存检查点."""
        if filename is None:
            filename = f"execution_sac_step_{self.train_step}.pt"

        path = os.path.join(self.config.checkpoint_dir, filename)

        torch.save({
            "actor": self.actor.state_dict(),
            "critic1": self.critic1.state_dict(),
            "critic2": self.critic2.state_dict(),
            "target_critic1": self.target_critic1.state_dict(),
            "target_critic2": self.target_critic2.state_dict(),
            "log_alpha": self.log_alpha,
            "train_step": self.train_step,
            "execution_stats": self.execution_stats,
        }, path)

        print(f"[ExecutionSAC] Saved checkpoint to {path}")

    def load(self, filename: str) -> bool:
        """加载检查点."""
        path = os.path.join(self.config.checkpoint_dir, filename)

        if not os.path.exists(path):
            print(f"[ExecutionSAC] Checkpoint not found: {path}")
            return False

        checkpoint = torch.load(path, map_location=self.device)

        self.actor.load_state_dict(checkpoint["actor"])
        self.critic1.load_state_dict(checkpoint["critic1"])
        self.critic2.load_state_dict(checkpoint["critic2"])
        self.target_critic1.load_state_dict(checkpoint["target_critic1"])
        self.target_critic2.load_state_dict(checkpoint["target_critic2"])
        self.log_alpha = checkpoint["log_alpha"]
        self.train_step = checkpoint["train_step"]
        self.execution_stats = checkpoint.get("execution_stats", self.execution_stats)

        print(f"[ExecutionSAC] Loaded checkpoint from {path}")
        return True

    def get_stats(self) -> Dict:
        """获取执行统计."""
        stats = self.execution_stats.copy()
        if stats['total_orders'] > 0:
            stats['avg_slices_per_order'] = stats['total_slices'] / stats['total_orders']
        else:
            stats['avg_slices_per_order'] = 0.0
        return stats


class ExecutionEnvironment:
    """
    执行优化训练环境.

    模拟订单执行过程，提供状态和奖励.
    """

    def __init__(self, config: SACConfig = None):
        self.config = config or SACConfig()
        self.agent = ExecutionSACAgent(self.config)

        # 模拟市场状态
        self.current_market = None
        self.current_order = None
        self.remaining_size = 0.0
        self.elapsed_ms = 0
        self.episode_rewards = []

    def reset(self, order: Order = None, market: MarketState = None) -> np.ndarray:
        """重置环境."""
        if order is None:
            # 生成随机订单
            order = Order(
                symbol="BTCUSDT",
                side=np.random.choice(['buy', 'sell']),
                size=np.random.uniform(0.1, 10.0),
                urgency=np.random.uniform(0.3, 0.9)
            )

        if market is None:
            # 生成随机市场状态
            market = MarketState(
                mid_price=50000.0 + np.random.randn() * 1000,
                spread=np.random.uniform(0.1, 10.0),
                bid_volume=np.random.uniform(1.0, 100.0),
                ask_volume=np.random.uniform(1.0, 100.0),
                volatility=np.random.uniform(0.001, 0.01),
                trend=np.random.uniform(-0.001, 0.001)
            )

        self.current_order = order
        self.current_market = market
        self.remaining_size = order.size
        self.elapsed_ms = 0

        state = self.agent._build_state(order, market, self.remaining_size, self.elapsed_ms)
        return state

    def step(self, action: np.ndarray) -> Tuple[np.ndarray, float, bool, Dict]:
        """
        执行一步.

        Returns:
            (next_state, reward, done, info)
        """
        # 解析动作
        slice_ratio, delay_factor, price_offset = action
        slice_ratio = (slice_ratio + 1) / 2
        delay_factor = (delay_factor + 1) / 2

        # 计算执行大小
        execute_size = self.remaining_size * slice_ratio
        execute_size = min(execute_size, self.remaining_size)

        # 模拟市场冲击
        market_impact = self._simulate_market_impact(execute_size)

        # 模拟滑点
        actual_slippage = self._simulate_slippage(execute_size, delay_factor)

        # 更新状态
        self.remaining_size -= execute_size
        self.elapsed_ms += int(delay_factor * 1000)

        # 计算奖励
        plan = ExecutionPlan(
            order=self.current_order,
            strategy=ExecutionStrategy.ADAPTIVE,
            slices=[],
            expected_slippage=0.001,
            expected_completion_time_ms=self.elapsed_ms
        )
        reward = self.agent.compute_reward(plan, actual_slippage, self.elapsed_ms)

        # 检查是否完成
        done = bool(self.remaining_size <= self.config.min_slice_size)

        # 构建下一个状态
        next_state = self.agent._build_state(
            self.current_order, self.current_market,
            self.remaining_size, self.elapsed_ms
        )

        info = {
            'executed_size': float(execute_size),
            'remaining_size': float(self.remaining_size),
            'actual_slippage': float(actual_slippage),
            'market_impact': float(market_impact),
        }

        return next_state, float(reward), done, info

    def _simulate_market_impact(self, size: float) -> float:
        """模拟市场冲击."""
        # 简化的市场冲击模型
        base_impact = 0.0001
        size_factor = size / 10.0
        liquidity_factor = 1.0 / (self.current_market.get_liquidity_score() + 0.1)
        return base_impact * size_factor * liquidity_factor

    def _simulate_slippage(self, size: float, delay_factor: float) -> float:
        """模拟滑点."""
        base_slippage = 0.0001
        size_factor = 1.0 + size / 5.0
        vol_factor = 1.0 + self.current_market.volatility * 10
        # 延迟越高，价格不确定性越大
        delay_penalty = delay_factor * 0.0002
        return base_slippage * size_factor * vol_factor + delay_penalty

    def train_episode(self, num_steps: int = 100) -> float:
        """训练一个episode."""
        state = self.reset()
        total_reward = 0.0
        experiences = []

        for _ in range(num_steps):
            action = self.agent.act(state, deterministic=False)
            next_state, reward, done, info = self.step(action)

            experiences.append(Experience(
                state=state,
                action=action,
                reward=reward,
                next_state=next_state,
                done=done
            ))

            total_reward += reward
            state = next_state

            if done:
                break

        # 训练
        if experiences:
            metrics = self.agent.train(experiences)
            if self.agent.train_step % 100 == 0:
                print(f"[ExecutionEnv] Step {self.agent.train_step}: {metrics}")

        return total_reward


if __name__ == "__main__":
    # 简单测试
    print("Testing ExecutionSACAgent...")

    # 创建智能体
    config = SACConfig()
    agent = ExecutionSACAgent(config)

    # 创建测试订单
    order = Order(
        symbol="BTCUSDT",
        side="buy",
        size=5.0,
        urgency=0.6
    )

    # 创建测试市场状态
    market = MarketState(
        mid_price=50000.0,
        spread=5.0,
        bid_volume=50.0,
        ask_volume=45.0,
        volatility=0.005,
        trend=0.0001
    )

    # 优化执行
    plan = agent.optimize_execution(order, market)

    print(f"\nExecution Plan:")
    print(f"  Strategy: {plan.strategy.name}")
    print(f"  Expected Slippage: {plan.expected_slippage:.4%}")
    print(f"  Expected Time: {plan.expected_completion_time_ms}ms")
    print(f"  Confidence: {plan.confidence:.2f}")
    print(f"  Number of Slices: {len(plan.slices)}")

    for i, slice_obj in enumerate(plan.slices):
        print(f"  Slice {i+1}: size={slice_obj.size}, delay={slice_obj.delay_ms}ms")

    # 测试训练环境
    print("\n\nTesting ExecutionEnvironment...")
    env = ExecutionEnvironment(config)

    for episode in range(5):
        reward = env.train_episode(num_steps=50)
        print(f"Episode {episode+1}: Total Reward = {reward:.2f}")

    print("\nExecution stats:", agent.get_stats())
