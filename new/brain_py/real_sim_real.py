"""
real_sim_real.py - Phase 7: Real→Sim→Real

实盘-仿真闭环系统:
1. 实盘数据收集
2. 高保真市场仿真
3. 策略验证和回测
4. 部署决策
"""

import numpy as np
import random
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque


@dataclass
class MarketData:
    """市场数据"""
    timestamp: float
    symbol: str
    price: float
    volume: float
    bid: float
    ask: float
    source: str = "unknown"  # "real" or "sim"


@dataclass
class MarketImpactModel:
    """市场冲击模型"""
    temporary_impact: float = 0.001   # 临时冲击
    permanent_impact: float = 0.0005  # 永久冲击
    decay_rate: float = 0.1           # 衰减率

    def compute_impact(self, order_size: float, market_volume: float) -> float:
        """计算市场冲击"""
        normalized_size = order_size / (market_volume + 1e-8)
        return self.temporary_impact * np.sqrt(normalized_size) + \
               self.permanent_impact * normalized_size


class MarketSimulator:
    """高保真市场仿真器"""

    def __init__(self, impact_model: MarketImpactModel = None):
        self.impact_model = impact_model or MarketImpactModel()
        self.historical_data: deque = deque(maxlen=10000)
        self.current_state: Optional[MarketData] = None

        # 仿真参数
        self.spread_mean = 0.001
        self.spread_std = 0.0005
        self.volatility = 0.02
        self.drift = 0.0

    def fit_to_real_data(self, data: List[MarketData]):
        """拟合真实数据"""
        if len(data) < 10:
            return

        prices = [d.price for d in data]
        spreads = [(d.ask - d.bid) / d.price for d in data if d.ask > d.bid]

        # 估计参数
        returns = np.diff(np.log(prices))
        self.volatility = np.std(returns) * np.sqrt(252)
        self.drift = np.mean(returns) * 252
        self.spread_mean = np.mean(spreads) if spreads else 0.001
        self.spread_std = np.std(spreads) if spreads else 0.0005

        self.historical_data.extend(data)
        print(f"[Sim] Fitted: vol={self.volatility:.4f}, drift={self.drift:.4f}")

    def step(self, action_size: float = 0.0) -> MarketData:
        """仿真一步"""
        if self.current_state is None:
            # 初始化
            base_price = 100.0
        else:
            base_price = self.current_state.price

        # 价格演化 (几何布朗运动 + 市场冲击)
        dt = 1 / 252
        shock = np.random.normal(0, 1)

        if action_size != 0:
            impact = self.impact_model.compute_impact(abs(action_size), 1000.0)
            impact *= np.sign(action_size)
        else:
            impact = 0.0

        new_price = base_price * np.exp(
            (self.drift - 0.5 * self.volatility**2) * dt +
            self.volatility * np.sqrt(dt) * shock +
            impact
        )

        # 生成 spread
        spread = np.random.lognormal(
            np.log(self.spread_mean),
            self.spread_std / self.spread_mean
        )

        data = MarketData(
            timestamp=datetime.now().timestamp(),
            symbol="SIM",
            price=new_price,
            volume=random.uniform(100, 1000),
            bid=new_price * (1 - spread/2),
            ask=new_price * (1 + spread/2),
            source="sim"
        )

        self.current_state = data
        return data

    def run_simulation(self, n_steps: int = 1000, strategy=None) -> List[MarketData]:
        """运行仿真"""
        results = []

        for _ in range(n_steps):
            if strategy:
                action = strategy(self.current_state)
            else:
                action = 0.0

            data = self.step(action)
            results.append(data)

        return results


class DomainAdaptation:
    """域适应 (实盘->仿真->实盘)"""

    def __init__(self):
        self.sim_to_real_shift = 0.0
        self.scale_factor = 1.0

    def calibrate(self, real_data: List[MarketData], sim_data: List[MarketData]):
        """校准仿真到实盘"""
        if len(real_data) == 0 or len(sim_data) == 0:
            return

        real_returns = np.diff([d.price for d in real_data])
        sim_returns = np.diff([d.price for d in sim_data])

        # 计算域间差异
        self.sim_to_real_shift = np.mean(real_returns) - np.mean(sim_returns)
        self.scale_factor = np.std(real_returns) / (np.std(sim_returns) + 1e-8)

        print(f"[DomainAdapt] Shift: {self.sim_to_real_shift:.6f}, "
              f"Scale: {self.scale_factor:.4f}")

    def sim_to_real(self, sim_return: float) -> float:
        """转换仿真收益到实盘估计"""
        return sim_return * self.scale_factor + self.sim_to_real_shift

    def real_to_sim(self, real_return: float) -> float:
        """转换实盘收益到仿真"""
        return (real_return - self.sim_to_real_shift) / self.scale_factor


class RealSimRealPipeline:
    """Real→Sim→Real 流水线"""

    def __init__(self):
        self.simulator = MarketSimulator()
        self.domain_adapt = DomainAdaptation()
        self.collected_real_data: deque = deque(maxlen=5000)
        self.validation_results: List[Dict] = []

    def collect_real_data(self, data: MarketData):
        """收集实盘数据"""
        self.collected_real_data.append(data)
        self.simulator.fit_to_real_data(list(self.collected_real_data))

    def train_in_simulation(self, strategy, n_episodes: int = 100) -> Dict:
        """在仿真中训练"""
        results = []

        for episode in range(n_episodes):
            # 重置仿真器
            self.simulator.current_state = None

            # 运行一集
            episode_data = self.simulator.run_simulation(100, strategy)

            # 计算收益
            prices = [d.price for d in episode_data]
            total_return = (prices[-1] - prices[0]) / prices[0]

            results.append(total_return)

        return {
            'mean_return': np.mean(results),
            'std_return': np.std(results),
            'sharpe': np.mean(results) / (np.std(results) + 1e-8),
            'win_rate': sum(1 for r in results if r > 0) / len(results)
        }

    def validate_before_deploy(self, strategy, n_simulations: int = 50) -> bool:
        """部署前验证"""
        print("[RSR] Validating strategy before deployment...")

        results = []
        for _ in range(n_simulations):
            self.simulator.current_state = None
            data = self.simulator.run_simulation(252, strategy)  # 一年
            returns = [(data[i].price - data[i-1].price) / data[i-1].price
                      for i in range(1, len(data))]

            total_return = np.prod([1 + r for r in returns]) - 1
            results.append(total_return)

        # 统计
        mean_return = np.mean(results)
        worst_case = np.percentile(results, 5)

        print(f"[RSR] Validation: mean={mean_return:.4f}, worst_5%={worst_case:.4f}")

        # 验证标准
        passed = mean_return > 0 and worst_case > -0.3

        self.validation_results.append({
            'timestamp': datetime.now().isoformat(),
            'mean_return': mean_return,
            'worst_case': worst_case,
            'passed': passed
        })

        return passed

    def deploy_decision(self, strategy) -> str:
        """部署决策"""
        if len(self.collected_real_data) < 100:
            return "collect_more_data"

        if not self.validation_results:
            return "need_validation"

        latest = self.validation_results[-1]

        if latest['passed'] and latest['mean_return'] > 0.1:
            return "deploy_live"
        elif latest['mean_return'] > 0.05:
            return "paper_trade"
        else:
            return "retrain"


if __name__ == "__main__":
    # 示例
    pipeline = RealSimRealPipeline()

    # 模拟收集实盘数据
    print("Collecting real market data...")
    for i in range(100):
        data = MarketData(
            timestamp=datetime.now().timestamp() + i,
            symbol="BTCUSDT",
            price=100 + np.random.randn() * 2,
            volume=1000,
            bid=99.9,
            ask=100.1,
            source="real"
        )
        pipeline.collect_real_data(data)

    # 简单策略
    def simple_strategy(state):
        if state is None:
            return 0.0
        return 0.1 if state.price < 100 else -0.1

    # 训练
    print("\nTraining in simulation...")
    result = pipeline.train_in_simulation(simple_strategy, n_episodes=50)
    print(f"Training result: {result}")

    # 验证
    print("\nValidating...")
    can_deploy = pipeline.validate_before_deploy(simple_strategy)
    print(f"Can deploy: {can_deploy}")

    # 决策
    decision = pipeline.deploy_decision(simple_strategy)
    print(f"\nDeploy decision: {decision}")
