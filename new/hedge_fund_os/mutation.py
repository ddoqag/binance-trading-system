"""
mutation.py - Genetic Mutation Operators for Evolution Engine

P10 Hedge Fund OS - Phase 5 Evolution Engine

This module implements various mutation operators for evolving strategy parameters
and hyperparameters in the genetic algorithm framework.
"""

import random
import numpy as np
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass
from enum import Enum, auto
from datetime import datetime
import copy

from .strategy_genome import StrategyGenome, StrategyStatus, BirthReason


class MutationType(Enum):
    """变异类型"""
    GAUSSIAN = "gaussian"           # 高斯噪声
    UNIFORM = "uniform"             # 均匀采样
    PERTURB = "perturb"             # 扰动 (x1.2 or /1.2)
    RESAMPLE = "resample"           # 重新采样
    POLYNOMIAL = "polynomial"       # 多项式变异 (SBX)
    ADAPTIVE = "adaptive"           # 自适应变异


@dataclass
class MutationConfig:
    """变异配置"""
    mutation_type: MutationType = MutationType.GAUSSIAN
    mutation_rate: float = 0.1           # 每个基因变异概率
    mutation_strength: float = 0.1       # 变异强度
    adaptive_decay: float = 0.95         # 自适应衰减因子
    min_value: float = -10.0             # 最小值限制
    max_value: float = 10.0              # 最大值限制
    elite_protection: bool = True        # 保护精英策略
    preserve_best: bool = True           # 保留最优解


class MutationOperator:
    """变异算子基类"""

    def __init__(self, config: MutationConfig = None):
        self.config = config or MutationConfig()
        self.generation = 0
        self.mutation_history: List[Dict[str, Any]] = []

    def mutate(self, genome: StrategyGenome) -> StrategyGenome:
        """
        对基因组进行变异

        Args:
            genome: 原始基因组

        Returns:
            变异后的新基因组
        """
        raise NotImplementedError

    def _record_mutation(self, parent_id: str, mutant_id: str, method: str):
        """记录变异历史"""
        self.mutation_history.append({
            'parent_id': parent_id,
            'mutant_id': mutant_id,
            'method': method,
            'timestamp': datetime.now().isoformat()
        })

    def _create_mutant(self, parent: StrategyGenome) -> StrategyGenome:
        """创建变异后代"""
        mutant = StrategyGenome(
            id=f"mut_{random.randint(1000, 9999)}",
            name=f"{parent.name}_mut",
            version=parent.version,
            parent_ids=[parent.id],
            strategy_type=parent.strategy_type,
            strategy_class=parent.strategy_class,
            parameters=copy.deepcopy(parent.parameters),
            hyperparameters=copy.deepcopy(parent.hyperparameters),
            birth_reason=BirthReason.MUTATION.value,
            generation=parent.generation + 1,
            status=StrategyStatus.BIRTH
        )
        return mutant

    def _clip_value(self, value: float) -> float:
        """裁剪值到有效范围"""
        return np.clip(value, self.config.min_value, self.config.max_value)


class GaussianMutation(MutationOperator):
    """高斯变异 - 添加高斯噪声"""

    def mutate(self, genome: StrategyGenome) -> StrategyGenome:
        """高斯变异"""
        mutant = self._create_mutant(genome)

        # 自适应变异强度 (随代数递减)
        adaptive_strength = self.config.mutation_strength / (1 + self.generation * 0.1)

        # 变异参数
        for key, value in mutant.parameters.items():
            if random.random() < self.config.mutation_rate:
                noise = np.random.normal(0, adaptive_strength * abs(value))
                mutant.parameters[key] = self._clip_value(value + noise)

        # 变异超参数
        for key, value in mutant.hyperparameters.items():
            if random.random() < self.config.mutation_rate:
                noise = np.random.normal(0, adaptive_strength * abs(value))
                mutant.hyperparameters[key] = self._clip_value(value + noise)

        self._record_mutation(genome.id, mutant.id, "gaussian")
        return mutant


class PerturbMutation(MutationOperator):
    """扰动变异 - 乘性扰动 (x1.2 or /1.2)"""

    def __init__(self, config: MutationConfig = None, perturb_factors: Tuple[float, float] = None):
        super().__init__(config)
        self.perturb_factors = perturb_factors or (1.2, 0.8)

    def mutate(self, genome: StrategyGenome) -> StrategyGenome:
        """扰动变异"""
        mutant = self._create_mutant(genome)

        for key, value in mutant.parameters.items():
            if random.random() < self.config.mutation_rate:
                factor = random.choice(self.perturb_factors)
                mutant.parameters[key] = self._clip_value(value * factor)

        for key, value in mutant.hyperparameters.items():
            if random.random() < self.config.mutation_rate:
                factor = random.choice(self.perturb_factors)
                mutant.hyperparameters[key] = self._clip_value(value * factor)

        self._record_mutation(genome.id, mutant.id, "perturb")
        return mutant


class UniformMutation(MutationOperator):
    """均匀变异 - 在范围内均匀重新采样"""

    def __init__(self, config: MutationConfig = None, param_ranges: Dict[str, Tuple[float, float]] = None):
        super().__init__(config)
        self.param_ranges = param_ranges or {}

    def mutate(self, genome: StrategyGenome) -> StrategyGenome:
        """均匀变异"""
        mutant = self._create_mutant(genome)

        for key, value in mutant.parameters.items():
            if random.random() < self.config.mutation_rate:
                # 使用预定义范围或默认值
                if key in self.param_ranges:
                    min_val, max_val = self.param_ranges[key]
                else:
                    min_val, max_val = self.config.min_value, self.config.max_value
                mutant.parameters[key] = random.uniform(min_val, max_val)

        for key, value in mutant.hyperparameters.items():
            if random.random() < self.config.mutation_rate:
                if key in self.param_ranges:
                    min_val, max_val = self.param_ranges[key]
                else:
                    min_val, max_val = self.config.min_value, self.config.max_value
                mutant.hyperparameters[key] = random.uniform(min_val, max_val)

        self._record_mutation(genome.id, mutant.id, "uniform")
        return mutant


class PolynomialMutation(MutationOperator):
    """
    多项式变异 (Polynomial Mutation)

    参考: Deb, K. (2001). Multi-Objective Optimization using Evolutionary Algorithms
    """

    def __init__(self, config: MutationConfig = None, distribution_index: float = 20.0):
        super().__init__(config)
        self.distribution_index = distribution_index

    def mutate(self, genome: StrategyGenome) -> StrategyGenome:
        """多项式变异"""
        mutant = self._create_mutant(genome)

        for key, value in mutant.parameters.items():
            if random.random() < self.config.mutation_rate:
                mutant.parameters[key] = self._polynomial_mutation_value(value)

        for key, value in mutant.hyperparameters.items():
            if random.random() < self.config.mutation_rate:
                mutant.hyperparameters[key] = self._polynomial_mutation_value(value)

        self._record_mutation(genome.id, mutant.id, "polynomial")
        return mutant

    def _polynomial_mutation_value(self, value: float) -> float:
        """
        单项多项式变异

        使用多项式分布生成变异值，保持解的多样性
        """
        min_val, max_val = self.config.min_value, self.config.max_value
        delta1 = (value - min_val) / (max_val - min_val)
        delta2 = (max_val - value) / (max_val - min_val)

        rand = random.random()
        mut_pow = 1.0 / (self.distribution_index + 1.0)

        if rand <= 0.5:
            xy = 1.0 - delta1
            val = 2.0 * rand + (1.0 - 2.0 * rand) * (xy ** (self.distribution_index + 1))
            delta_q = val ** mut_pow - 1.0
        else:
            xy = 1.0 - delta2
            val = 2.0 * (1.0 - rand) + 2.0 * (rand - 0.5) * (xy ** (self.distribution_index + 1))
            delta_q = 1.0 - val ** mut_pow

        new_value = value + delta_q * (max_val - min_val)
        return self._clip_value(new_value)


class AdaptiveMutation(MutationOperator):
    """
    自适应变异

    根据进化历史动态调整变异强度和概率
    """

    def __init__(self, config: MutationConfig = None):
        super().__init__(config)
        self.success_rate = 0.5
        self.generation_improvements: List[float] = []

    def mutate(self, genome: StrategyGenome) -> StrategyGenome:
        """自适应变异"""
        # 根据成功率调整变异强度
        if self.success_rate > 0.6:
            # 成功率高，减小变异 (精细搜索)
            adaptive_strength = self.config.mutation_strength * 0.8
        elif self.success_rate < 0.3:
            # 成功率低，增大变异 (探索)
            adaptive_strength = self.config.mutation_strength * 1.5
        else:
            adaptive_strength = self.config.mutation_strength

        mutant = self._create_mutant(genome)

        # 自适应变异率
        adaptive_rate = min(0.5, self.config.mutation_rate * (1 + (0.5 - self.success_rate)))

        for key, value in mutant.parameters.items():
            if random.random() < adaptive_rate:
                noise = np.random.normal(0, adaptive_strength * abs(value))
                mutant.parameters[key] = self._clip_value(value + noise)

        for key, value in mutant.hyperparameters.items():
            if random.random() < adaptive_rate:
                noise = np.random.normal(0, adaptive_strength * abs(value))
                mutant.hyperparameters[key] = self._clip_value(value + noise)

        self._record_mutation(genome.id, mutant.id, "adaptive")
        return mutant

    def update_success_rate(self, new_rate: float):
        """更新成功率 (用于自适应调整)"""
        self.success_rate = 0.9 * self.success_rate + 0.1 * new_rate


class CompositeMutation(MutationOperator):
    """
    复合变异 - 组合多种变异策略

    根据当前进化阶段选择不同的变异算子
    """

    def __init__(self, config: MutationConfig = None):
        super().__init__(config)
        self.operators = {
            MutationType.GAUSSIAN: GaussianMutation(config),
            MutationType.PERTURB: PerturbMutation(config),
            MutationType.POLYNOMIAL: PolynomialMutation(config),
            MutationType.UNIFORM: UniformMutation(config),
        }
        self.operator_weights = {
            MutationType.GAUSSIAN: 0.4,
            MutationType.PERTURB: 0.3,
            MutationType.POLYNOMIAL: 0.2,
            MutationType.UNIFORM: 0.1,
        }

    def mutate(self, genome: StrategyGenome) -> StrategyGenome:
        """复合变异 - 根据权重选择算子"""
        # 根据进化阶段调整权重
        if self.generation < 10:
            # 早期：更多探索
            self.operator_weights[MutationType.UNIFORM] = 0.3
            self.operator_weights[MutationType.GAUSSIAN] = 0.3
        elif self.generation > 50:
            # 后期：更多利用
            self.operator_weights[MutationType.GAUSSIAN] = 0.5
            self.operator_weights[MutationType.PERTURB] = 0.4

        # 加权随机选择
        operators = list(self.operator_weights.keys())
        weights = list(self.operator_weights.values())
        selected_type = random.choices(operators, weights=weights)[0]

        operator = self.operators[selected_type]
        operator.generation = self.generation

        return operator.mutate(genome)


class HyperparameterSpace:
    """超参数搜索空间定义"""

    def __init__(self):
        self.spaces: Dict[str, Tuple[float, float]] = {}
        self.log_scale: set = set()

    def add_param(self, name: str, min_val: float, max_val: float, log_scale: bool = False):
        """添加参数范围"""
        self.spaces[name] = (min_val, max_val)
        if log_scale:
            self.log_scale.add(name)

    def sample(self) -> Dict[str, float]:
        """从空间随机采样"""
        params = {}
        for name, (min_val, max_val) in self.spaces.items():
            if name in self.log_scale:
                # 对数均匀采样
                log_min, log_max = np.log(min_val), np.log(max_val)
                params[name] = np.exp(random.uniform(log_min, log_max))
            else:
                params[name] = random.uniform(min_val, max_val)
        return params

    def clip(self, params: Dict[str, float]) -> Dict[str, float]:
        """裁剪参数到有效范围"""
        clipped = {}
        for name, value in params.items():
            if name in self.spaces:
                min_val, max_val = self.spaces[name]
                clipped[name] = np.clip(value, min_val, max_val)
            else:
                clipped[name] = value
        return clipped


def create_default_mutation_operator(
    mutation_type: MutationType = MutationType.GAUSSIAN,
    mutation_rate: float = 0.1,
    mutation_strength: float = 0.1
) -> MutationOperator:
    """
    创建默认变异算子

    Args:
        mutation_type: 变异类型
        mutation_rate: 变异概率
        mutation_strength: 变异强度

    Returns:
        配置好的变异算子
    """
    config = MutationConfig(
        mutation_type=mutation_type,
        mutation_rate=mutation_rate,
        mutation_strength=mutation_strength
    )

    if mutation_type == MutationType.GAUSSIAN:
        return GaussianMutation(config)
    elif mutation_type == MutationType.PERTURB:
        return PerturbMutation(config)
    elif mutation_type == MutationType.UNIFORM:
        return UniformMutation(config)
    elif mutation_type == MutationType.POLYNOMIAL:
        return PolynomialMutation(config)
    elif mutation_type == MutationType.ADAPTIVE:
        return AdaptiveMutation(config)
    else:
        return CompositeMutation(config)
