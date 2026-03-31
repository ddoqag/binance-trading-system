"""
pbt_trainer.py - Population Based Training (Phase 4)

PBT 核心机制:
1. 策略种群管理 - 多个策略实例并行运行
2. 异步进化 - 弱策略从强策略复制权重+超参并探索
3. 在线超参优化 - 无需完整训练周期
4. 遗传算法 - 选择、交叉、变异

参考: Jaderberg et al. 2017 "Population Based Training of Neural Networks"
"""

import time
import copy
import random
import threading
import numpy as np
from typing import Dict, List, Optional, Callable, Any, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum, auto
from collections import deque
import json
from abc import ABC, abstractmethod

# 兼容导入
try:
    from agents import BaseExpert, ExpertConfig, Action, ActionType, MarketRegime
    from meta_agent import MetaAgent, MetaAgentConfig
except ImportError:
    from .agents import BaseExpert, ExpertConfig, Action, ActionType, MarketRegime
    from .meta_agent import MetaAgent, MetaAgentConfig


class MutationType(Enum):
    """变异类型"""
    GAUSSIAN = "gaussian"           # 高斯噪声
    UNIFORM = "uniform"             # 均匀采样
    RESAMPLE = "resample"           # 重新采样
    PERTURB = "perturb"             # 扰动 (x1.2 or /1.2)


@dataclass
class HyperparameterSpace:
    """超参数搜索空间"""
    # 学习率范围
    lr_min: float = 1e-5
    lr_max: float = 1e-2

    # 位置大小范围
    position_size_min: float = 0.1
    position_size_max: float = 1.0

    # 置信度阈值
    confidence_min: float = 0.2
    confidence_max: float = 0.8

    # 回望窗口
    lookback_min: int = 10
    lookback_max: int = 100

    # 变异强度
    mutation_std: float = 0.1

    def sample_learning_rate(self) -> float:
        """对数均匀采样学习率"""
        log_min, log_max = np.log(self.lr_min), np.log(self.lr_max)
        return np.exp(np.random.uniform(log_min, log_max))

    def sample_position_size(self) -> float:
        """采样位置大小"""
        return np.random.uniform(self.position_size_min, self.position_size_max)

    def sample_confidence(self) -> float:
        """采样置信度阈值"""
        return np.random.uniform(self.confidence_min, self.confidence_max)

    def sample_lookback(self) -> int:
        """采样回望窗口"""
        return np.random.randint(self.lookback_min, self.lookback_max + 1)


@dataclass
class PBTConfig:
    """PBT 配置"""
    # 种群大小
    population_size: int = 10

    # 进化参数
    exploit_top_fraction: float = 0.2      # 复制前20%
    exploit_bottom_fraction: float = 0.2   # 被复制的后20%
    mutation_probability: float = 0.8      # 变异概率

    # 异步进化
    ready_threshold: int = 10              # 多少步后评估
    evaluation_window: int = 20            # 评估窗口

    # 超参搜索
    hyperparameter_space: HyperparameterSpace = field(default_factory=HyperparameterSpace)
    mutation_type: MutationType = MutationType.PERTURB

    # 探索参数
    noise_scale: float = 0.1               # 高斯噪声标准差
    perturb_factors: Tuple[float, float] = (1.2, 0.8)  # 扰动因子

    # 早停
    min_performance_threshold: float = -1.0  # 最低表现阈值
    enable_early_stopping: bool = True


@dataclass
class Individual:
    """种群个体 - 包装策略和其元数据"""
    id: str
    strategy: BaseExpert
    hyperparams: Dict[str, Any]

    # 表现追踪
    performance_history: deque = field(default_factory=lambda: deque(maxlen=100))
    step_count: int = 0
    last_eval_step: int = 0

    # 状态
    is_ready: bool = False
    is_elite: bool = False
    parent_id: Optional[str] = None
    generation: int = 0

    # 统计
    total_reward: float = 0.0
    best_reward: float = -np.inf
    worst_reward: float = np.inf

    def __post_init__(self):
        if isinstance(self.performance_history, list):
            self.performance_history = deque(self.performance_history, maxlen=100)

    def update_performance(self, reward: float, step: int):
        """更新表现"""
        self.performance_history.append(reward)
        self.total_reward += reward
        self.step_count = step

        self.best_reward = max(self.best_reward, reward)
        self.worst_reward = min(self.worst_reward, reward)

        # 检查是否准备好被评估
        steps_since_eval = step - self.last_eval_step
        if steps_since_eval >= 10:  # 每10步可评估
            self.is_ready = True

    def get_mean_performance(self, window: int = None) -> float:
        """获取平均表现"""
        if not self.performance_history:
            return -np.inf

        if window is None or window >= len(self.performance_history):
            return np.mean(self.performance_history)

        recent = list(self.performance_history)[-window:]
        return np.mean(recent)

    def get_sharpe(self) -> float:
        """获取夏普比率"""
        if len(self.performance_history) < 5:
            return 0.0
        returns = np.array(self.performance_history)
        if np.std(returns) == 0:
            return 0.0
        return np.mean(returns) / (np.std(returns) + 1e-8)

    def to_dict(self) -> Dict:
        """序列化"""
        return {
            'id': self.id,
            'hyperparams': self.hyperparams,
            'performance': list(self.performance_history),
            'step_count': self.step_count,
            'generation': self.generation,
            'total_reward': self.total_reward,
            'is_elite': self.is_elite
        }


class PBTTrainer:
    """
    Population Based Training Trainer

    管理策略种群的异步进化:
    1. 初始化随机种群
    2. 并行运行所有策略
    3. 定期评估和进化
    4. 复制表现好的策略权重和超参
    5. 对复制的策略进行变异探索

    Usage:
        config = PBTConfig(population_size=20)
        trainer = PBTTrainer(config)

        # 添加策略工厂
        trainer.register_strategy_factory("trend", TrendFollowingExpert)

        # 初始化种群
        trainer.initialize_population()

        # 训练循环
        for step in range(1000):
            # 执行所有策略
            actions = trainer.execute_all(observation)

            # 获取环境反馈
            rewards = env.step(actions)

            # 更新并进化
            trainer.update_and_evolve(rewards, step)
    """

    def __init__(self, config: PBTConfig = None):
        self.config = config or PBTConfig()

        # 种群
        self.population: Dict[str, Individual] = {}
        self.elite_individuals: Set[str] = set()

        # 策略工厂
        self._strategy_factories: Dict[str, Callable] = {}

        # 历史记录
        self.generation_history: List[Dict] = []
        self.best_individuals_history: deque = deque(maxlen=100)

        # 统计
        self.total_steps: int = 0
        self.evolution_count: int = 0
        self.start_time: float = time.time()

        # 锁
        self._lock = threading.RLock()

        print(f"[PBT] Initialized with population_size={self.config.population_size}")

    def register_strategy_factory(self, strategy_type: str, factory: Callable):
        """
        注册策略工厂函数

        Args:
            strategy_type: 策略类型标识
            factory: 工厂函数，接收hyperparams返回策略实例
        """
        self._strategy_factories[strategy_type] = factory
        print(f"[PBT] Registered factory for {strategy_type}")

    def initialize_population(self, strategy_types: List[str] = None):
        """
        初始化随机种群

        Args:
            strategy_types: 策略类型列表，如果为None则随机选择
        """
        if not self._strategy_factories:
            raise ValueError("No strategy factories registered")

        available_types = list(self._strategy_factories.keys())

        with self._lock:
            for i in range(self.config.population_size):
                # 选择策略类型
                if strategy_types and i < len(strategy_types):
                    stype = strategy_types[i]
                else:
                    stype = random.choice(available_types)

                # 采样超参
                hyperparams = self._sample_hyperparameters()

                # 创建策略
                strategy = self._create_strategy(stype, hyperparams)

                # 创建个体
                individual = Individual(
                    id=f"ind_{i}_{int(time.time()*1000)%10000}",
                    strategy=strategy,
                    hyperparams=hyperparams,
                    generation=0
                )

                self.population[individual.id] = individual
                print(f"[PBT] Created {individual.id} ({stype})")

    def _sample_hyperparameters(self) -> Dict[str, Any]:
        """采样超参数"""
        space = self.config.hyperparameter_space
        return {
            'learning_rate': space.sample_learning_rate(),
            'position_size': space.sample_position_size(),
            'confidence_threshold': space.sample_confidence(),
            'lookback_window': space.sample_lookback(),
            'noise_scale': np.random.uniform(0.01, 0.2)
        }

    def _create_strategy(self, strategy_type: str, hyperparams: Dict) -> BaseExpert:
        """创建策略实例"""
        factory = self._strategy_factories.get(strategy_type)
        if factory is None:
            raise ValueError(f"No factory for {strategy_type}")

        # 创建配置
        config = ExpertConfig(
            name=f"{strategy_type}_{random.randint(1000, 9999)}",
            max_position_size=hyperparams.get('position_size', 1.0),
            min_confidence=hyperparams.get('confidence_threshold', 0.3),
            lookback_window=hyperparams.get('lookback_window', 20)
        )

        return factory(config)

    def execute_all(self, observation: np.ndarray) -> Dict[str, Action]:
        """
        执行所有策略

        Returns:
            Dict[str, Action]: 个体ID到动作的映射
        """
        actions = {}
        with self._lock:
            for ind_id, individual in self.population.items():
                try:
                    action = individual.strategy.act(observation)
                    actions[ind_id] = action
                except Exception as e:
                    print(f"[PBT] Error executing {ind_id}: {e}")
                    actions[ind_id] = Action(ActionType.HOLD, 0.0, 0.0)

        return actions

    def update_and_evolve(self, rewards: Dict[str, float], step: int):
        """
        更新表现并触发进化

        Args:
            rewards: {individual_id: reward} 映射
            step: 当前步数
        """
        with self._lock:
            # 更新所有个体表现
            for ind_id, reward in rewards.items():
                if ind_id in self.population:
                    self.population[ind_id].update_performance(reward, step)

            # 检查是否有准备好进化的个体
            ready_individuals = [
                ind for ind in self.population.values()
                if ind.is_ready and (step - ind.last_eval_step) >= self.config.ready_threshold
            ]

            # 执行进化
            for ind in ready_individuals:
                self._evolve_individual(ind, step)

    def _evolve_individual(self, individual: Individual, step: int):
        """
        进化单个个体 (核心PBT逻辑)

        1. 如果表现差，从表现好的个体复制权重和超参
        2. 对复制的超参进行变异探索
        """
        individual.last_eval_step = step
        individual.is_ready = False

        # 计算当前表现
        current_perf = individual.get_mean_performance(self.config.evaluation_window)

        # 排序所有个体
        sorted_inds = sorted(
            self.population.values(),
            key=lambda x: x.get_mean_performance(self.config.evaluation_window),
            reverse=True
        )

        n = len(sorted_inds)
        top_k = max(1, int(n * self.config.exploit_top_fraction))
        bottom_k = max(1, int(n * self.config.exploit_bottom_fraction))

        # 检查是否在底部
        current_rank = next(i for i, ind in enumerate(sorted_inds) if ind.id == individual.id)

        if current_rank >= n - bottom_k:
            # 表现差，需要进化
            # 1. 从顶部随机选择一个
            donor = random.choice(sorted_inds[:top_k])

            # 2. 复制超参
            individual.hyperparams = copy.deepcopy(donor.hyperparams)
            individual.parent_id = donor.id
            individual.generation += 1

            # 3. 变异
            if random.random() < self.config.mutation_probability:
                individual.hyperparams = self._mutate_hyperparams(
                    individual.hyperparams,
                    individual.generation
                )

            # 4. 重置表现历史 (但保留total_reward用于追踪)
            individual.performance_history.clear()

            print(f"[PBT] {individual.id} evolved from {donor.id} (gen {individual.generation})")

    def _mutate_hyperparams(self, hyperparams: Dict, generation: int) -> Dict:
        """
        变异超参数

        Args:
            hyperparams: 原始超参
            generation: 代数 (影响变异强度)
        """
        mutated = copy.deepcopy(hyperparams)
        mutation_type = self.config.mutation_type

        # 代数越高，变异越小 (逐渐收敛)
        adaptive_scale = self.config.noise_scale / (1 + generation * 0.1)

        for key, value in mutated.items():
            if isinstance(value, (int, float)):
                if mutation_type == MutationType.GAUSSIAN:
                    # 高斯噪声
                    noise = np.random.normal(0, adaptive_scale)
                    if isinstance(value, int):
                        mutated[key] = int(value + noise)
                    else:
                        mutated[key] = value + noise

                elif mutation_type == MutationType.PERTURB:
                    # 扰动 (乘性)
                    factor = random.choice(self.config.perturb_factors)
                    if isinstance(value, int):
                        mutated[key] = int(value * factor)
                    else:
                        mutated[key] = value * factor

                elif mutation_type == MutationType.RESAMPLE:
                    # 以一定概率重新采样
                    if random.random() < 0.3:
                        space = self.config.hyperparameter_space
                        if key == 'learning_rate':
                            mutated[key] = space.sample_learning_rate()
                        elif key == 'position_size':
                            mutated[key] = space.sample_position_size()
                        elif key == 'confidence_threshold':
                            mutated[key] = space.sample_confidence()
                        elif key == 'lookback_window':
                            mutated[key] = space.sample_lookback()

        # 确保超参在有效范围内
        mutated = self._clip_hyperparams(mutated)

        return mutated

    def _clip_hyperparams(self, hyperparams: Dict) -> Dict:
        """裁剪超参数到有效范围"""
        space = self.config.hyperparameter_space

        clipped = copy.deepcopy(hyperparams)

        if 'learning_rate' in clipped:
            clipped['learning_rate'] = np.clip(
                clipped['learning_rate'], space.lr_min, space.lr_max
            )

        if 'position_size' in clipped:
            clipped['position_size'] = np.clip(
                clipped['position_size'], space.position_size_min, space.position_size_max
            )

        if 'confidence_threshold' in clipped:
            clipped['confidence_threshold'] = np.clip(
                clipped['confidence_threshold'], space.confidence_min, space.confidence_max
            )

        if 'lookback_window' in clipped:
            clipped['lookback_window'] = int(np.clip(
                clipped['lookback_window'], space.lookback_min, space.lookback_max
            ))

        return clipped

    def get_best_individual(self, window: int = None) -> Optional[Individual]:
        """获取表现最好的个体"""
        if not self.population:
            return None

        return max(
            self.population.values(),
            key=lambda x: x.get_mean_performance(window)
        )

    def get_population_stats(self) -> Dict[str, Any]:
        """获取种群统计"""
        if not self.population:
            return {}

        performances = [ind.get_mean_performance() for ind in self.population.values()]
        sharpe_ratios = [ind.get_sharpe() for ind in self.population.values()]
        generations = [ind.generation for ind in self.population.values()]

        return {
            'population_size': int(len(self.population)),
            'mean_performance': float(np.mean(performances)),
            'best_performance': float(np.max(performances)) if performances else 0.0,
            'worst_performance': float(np.min(performances)) if performances else 0.0,
            'std_performance': float(np.std(performances)) if len(performances) > 1 else 0.0,
            'mean_sharpe': float(np.mean(sharpe_ratios)),
            'mean_generation': float(np.mean(generations)) if generations else 0.0,
            'max_generation': int(np.max(generations)) if generations else 0,
            'evolution_count': int(self.evolution_count),
            'runtime_seconds': float(time.time() - self.start_time)
        }

    def get_elite_hyperparams(self, top_k: int = 3) -> List[Dict]:
        """获取精英个体的超参配置"""
        sorted_inds = sorted(
            self.population.values(),
            key=lambda x: x.get_mean_performance(),
            reverse=True
        )

        elite_configs = []
        for ind in sorted_inds[:top_k]:
            config = {
                'id': ind.id,
                'hyperparams': ind.hyperparams,
                'performance': ind.get_mean_performance(),
                'sharpe': ind.get_sharpe(),
                'generation': ind.generation
            }
            elite_configs.append(config)

        return elite_configs

    def export_state(self) -> Dict:
        """导出完整状态"""
        return {
            'config': {
                'population_size': self.config.population_size,
                'mutation_probability': self.config.mutation_probability,
                'mutation_type': self.config.mutation_type.value
            },
            'population': {ind_id: ind.to_dict() for ind_id, ind in self.population.items()},
            'stats': self.get_population_stats(),
            'elite_configs': self.get_elite_hyperparams(),
            'timestamp': time.time()
        }

    def save_checkpoint(self, filepath: str):
        """保存检查点"""
        state = self.export_state()
        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2)
        print(f"[PBT] Checkpoint saved to {filepath}")

    def reset_population(self):
        """重置种群"""
        with self._lock:
            self.population.clear()
            self.elite_individuals.clear()
            self.generation_history.clear()
            self.evolution_count = 0
            print("[PBT] Population reset")


# 便捷函数
def create_default_pbt_trainer(
    population_size: int = 10,
    mutation_type: MutationType = MutationType.PERTURB
) -> PBTTrainer:
    """创建默认PBT训练器"""
    config = PBTConfig(
        population_size=population_size,
        mutation_type=mutation_type,
        ready_threshold=5,
        evaluation_window=10
    )
    return PBTTrainer(config)
