"""
self_play_trading.py - Phase 6: Self-Play Trading

策略自博弈系统:
1. 红蓝对抗训练
2. 纳什均衡求解
3. 策略响应学习
4. 市场博弈模拟
"""

import numpy as np
import random
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum
from collections import defaultdict


class PlayerRole(Enum):
    """玩家角色"""
    BUYER = "buyer"
    SELLER = "seller"
    MARKET_MAKER = "mm"


@dataclass
class GameState:
    """博弈状态"""
    price: float
    position: float
    cash: float
    time_step: int
    market_impact: float = 0.0


@dataclass
class Action:
    """博弈动作"""
    price_delta: float  # 价格偏移
    size: float         # 订单大小
    role: PlayerRole


class StrategyPolicy:
    """策略策略 (神经网络或规则)"""

    def __init__(self, name: str, strategy_type: str = "neural"):
        self.name = name
        self.strategy_type = strategy_type
        self.weights = np.random.randn(10) * 0.1

    def predict(self, state: GameState, role: PlayerRole) -> Action:
        """预测动作"""
        features = np.array([
            state.price / 100.0,
            state.position,
            state.cash / 10000.0,
            state.time_step / 100.0,
            state.market_impact * 10.0,
            1.0 if role == PlayerRole.BUYER else -1.0,
            random.random()
        ])

        # 简单线性策略
        output = np.dot(self.weights[:len(features)], features)

        return Action(
            price_delta=output * 0.01,
            size=min(abs(output), 1.0),
            role=role
        )

    def update(self, gradient: np.ndarray, lr: float = 0.01):
        """更新策略"""
        self.weights += lr * gradient[:len(self.weights)]


class SelfPlayArena:
    """自博弈竞技场"""

    def __init__(self, initial_price: float = 100.0):
        self.initial_price = initial_price
        self.policies: Dict[str, StrategyPolicy] = {}
        self.history: List[Tuple[GameState, Action, float]] = []

    def register_policy(self, policy: StrategyPolicy):
        """注册策略"""
        self.policies[policy.name] = policy

    def simulate_game(self, policy1_name: str, policy2_name: str,
                     n_steps: int = 100) -> Dict[str, float]:
        """模拟一局博弈"""
        policy1 = self.policies[policy1_name]
        policy2 = self.policies[policy2_name]

        state = GameState(
            price=self.initial_price,
            position=0.0,
            cash=10000.0,
            time_step=0
        )

        p1_pnl = 0.0
        p2_pnl = 0.0

        for step in range(n_steps):
            # 双方同时决策 (纳什均衡)
            action1 = policy1.predict(state, PlayerRole.BUYER)
            action2 = policy2.predict(state, PlayerRole.SELLER)

            # 市场清算
            mid_price = state.price + (action1.price_delta - action2.price_delta) * 0.5
            trade_size = min(action1.size, action2.size)

            # 计算收益
            price_change = random.gauss(0, 0.01) + trade_size * 0.001
            new_price = mid_price * (1 + price_change)

            p1_pnl += (new_price - state.price) * trade_size if state.position > 0 else 0
            p2_pnl += (state.price - new_price) * trade_size if state.position < 0 else 0

            # 更新状态
            state = GameState(
                price=new_price,
                position=state.position + trade_size * (1 if action1.size > action2.size else -1),
                cash=state.cash,
                time_step=step + 1,
                market_impact=trade_size * 0.001
            )

        return {policy1_name: p1_pnl, policy2_name: p2_pnl}

    def run_tournament(self, n_rounds: int = 10) -> Dict[str, float]:
        """运行锦标赛"""
        scores = defaultdict(float)
        policy_names = list(self.policies.keys())

        for _ in range(n_rounds):
            for i, p1 in enumerate(policy_names):
                for p2 in policy_names[i+1:]:
                    result = self.simulate_game(p1, p2)
                    scores[p1] += result[p1]
                    scores[p2] += result[p2]

        return dict(scores)

    def train_self_play(self, policy_name: str, n_iterations: int = 100):
        """自博弈训练"""
        policy = self.policies[policy_name]

        for iteration in range(n_iterations):
            # 创建对手 (使用旧版本)
            opponent = StrategyPolicy(f"opponent_{iteration}", policy.strategy_type)
            opponent.weights = policy.weights.copy() + np.random.randn(10) * 0.01

            self.register_policy(opponent)

            # 模拟
            result = self.simulate_game(policy_name, opponent.name)

            # 基于结果更新
            if result[policy_name] > result[opponent.name]:
                gradient = np.random.randn(10) * 0.1  # 正向更新
            else:
                gradient = -np.random.randn(10) * 0.05  # 负向更新

            policy.update(gradient)

            if iteration % 20 == 0:
                print(f"Iteration {iteration}: PnL = {result[policy_name]:.2f}")


class NashEquilibriumSolver:
    """纳什均衡求解器"""

    def __init__(self, n_strategies: int = 5):
        self.n_strategies = n_strategies
        self.payoff_matrix = np.random.randn(n_strategies, n_strategies)

    def compute_mixed_strategy(self, iterations: int = 1000) -> np.ndarray:
        """计算混合策略纳什均衡 (Fictitious Play)"""
        strategy_dist = np.ones(self.n_strategies) / self.n_strategies

        for _ in range(iterations):
            # 计算期望收益
            expected_payoff = self.payoff_matrix @ strategy_dist

            # 最佳响应
            best_response = np.zeros(self.n_strategies)
            best_response[np.argmax(expected_payoff)] = 1.0

            # 更新分布
            strategy_dist = 0.99 * strategy_dist + 0.01 * best_response

        return strategy_dist / strategy_dist.sum()


if __name__ == "__main__":
    # 自博弈示例
    arena = SelfPlayArena()

    # 注册策略
    policy = StrategyPolicy("learner")
    arena.register_policy(policy)

    # 训练
    print("Training with self-play...")
    arena.train_self_play("learner", n_iterations=100)

    # 纳什均衡
    print("\nComputing Nash equilibrium...")
    nash = NashEquilibriumSolver(n_strategies=5)
    mixed_strategy = nash.compute_mixed_strategy()
    print(f"Mixed strategy: {mixed_strategy}")
