"""
selection.py - Genetic Selection Operators for Evolution Engine

P10 Hedge Fund OS - Phase 5 Evolution Engine

This module implements various selection operators for choosing parent strategies
during the evolutionary process, including tournament selection, rank-based selection,
and elite preservation.
"""

import random
import numpy as np
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass
from enum import Enum, auto

from .strategy_genome import StrategyGenome, StrategyStatus, PerformanceRecord


class SelectionType(Enum):
    """选择类型"""
    TOURNAMENT = "tournament"       # 锦标赛选择
    ROULETTE = "roulette"           # 轮盘赌选择
    RANK = "rank"                   # 排名选择
    ELITE = "elite"                 # 精英选择
    BOLTZMANN = "boltzmann"         # 玻尔兹曼选择
    STOCHASTIC_UNIVERSAL = "sus"    # 随机通用采样


@dataclass
class SelectionConfig:
    """选择配置"""
    selection_type: SelectionType = SelectionType.TOURNAMENT
    tournament_size: int = 3          # 锦标赛大小
    elite_ratio: float = 0.1          # 精英保留比例
    diversity_weight: float = 0.2     # 多样性权重
    temperature: float = 1.0          # 玻尔兹曼温度
    min_selection_pressure: float = 0.1  # 最小选择压力


class SelectionOperator:
    """选择算子基类"""

    def __init__(self, config: SelectionConfig = None):
        self.config = config or SelectionConfig()
        self.selection_history: List[Dict[str, Any]] = []

    def select(self, population: List[StrategyGenome], n: int = 1) -> List[StrategyGenome]:
        """
        从种群中选择n个个体

        Args:
            population: 候选种群
            n: 选择数量

        Returns:
            被选中的个体列表
        """
        raise NotImplementedError

    def select_pair(self, population: List[StrategyGenome]) -> Tuple[StrategyGenome, StrategyGenome]:
        """选择一对父代用于交叉"""
        selected = self.select(population, n=2)
        return selected[0], selected[1]

    def _calculate_fitness_scores(self, population: List[StrategyGenome]) -> np.ndarray:
        """计算所有个体的适应度分数"""
        scores = np.array([g.calculate_fitness() for g in population])
        # 处理负值
        min_score = np.min(scores)
        if min_score < 0:
            scores = scores - min_score + 1e-6
        return scores

    def _record_selection(self, selected_ids: List[str], method: str):
        """记录选择历史"""
        self.selection_history.append({
            'method': method,
            'selected': selected_ids,
            'timestamp': np.datetime64('now')
        })


class TournamentSelection(SelectionOperator):
    """
    锦标赛选择 (Tournament Selection)

    随机选择k个个体，从中选出最好的
    优点：简单、可调选择压力
    """

    def select(self, population: List[StrategyGenome], n: int = 1) -> List[StrategyGenome]:
        """锦标赛选择"""
        if not population or n <= 0:
            return []

        selected = []
        for _ in range(n):
            # 随机选择tournament_size个个体
            tournament = random.sample(
                population,
                min(self.config.tournament_size, len(population))
            )
            # 选择最好的
            winner = max(tournament, key=lambda g: g.calculate_fitness())
            selected.append(winner)

        self._record_selection([g.id for g in selected], "tournament")
        return selected


class RouletteSelection(SelectionOperator):
    """
    轮盘赌选择 (Roulette Wheel Selection / Fitness Proportionate Selection)

    按适应度比例选择，适应度越高被选概率越大
    """

    def select(self, population: List[StrategyGenome], n: int = 1) -> List[StrategyGenome]:
        """轮盘赌选择"""
        if not population or n <= 0:
            return []

        if len(population) == 1:
            return [population[0]] * n

        scores = self._calculate_fitness_scores(population)
        total_fitness = np.sum(scores)

        if total_fitness == 0:
            # 如果总适应度为0，均匀随机选择
            return random.choices(population, k=n)

        # 计算选择概率
        probabilities = scores / total_fitness

        selected = random.choices(population, weights=probabilities, k=n)
        self._record_selection([g.id for g in selected], "roulette")
        return selected


class RankSelection(SelectionOperator):
    """
    排名选择 (Rank Selection)

    基于排名而非绝对适应度进行选择，避免早熟收敛
    """

    def select(self, population: List[StrategyGenome], n: int = 1) -> List[StrategyGenome]:
        """排名选择"""
        if not population or n <= 0:
            return []

        # 按适应度排序
        sorted_pop = sorted(population, key=lambda g: g.calculate_fitness(), reverse=True)

        # 线性排名概率 (排名越高概率越大)
        n_pop = len(sorted_pop)
        ranks = np.arange(n_pop, 0, -1)  # n, n-1, ..., 1

        # 添加多样性惩罚
        if self.config.diversity_weight > 0:
            diversity_scores = self._calculate_diversity_scores(sorted_pop)
            ranks = ranks * (1 + self.config.diversity_weight * diversity_scores)

        probabilities = ranks / np.sum(ranks)

        selected = random.choices(sorted_pop, weights=probabilities, k=n)
        self._record_selection([g.id for g in selected], "rank")
        return selected

    def _calculate_diversity_scores(self, population: List[StrategyGenome]) -> np.ndarray:
        """计算多样性分数 (基于参数差异)"""
        if len(population) < 2:
            return np.ones(len(population))

        scores = np.ones(len(population))
        for i, genome in enumerate(population):
            # 计算与其他个体的平均参数距离
            distances = []
            for j, other in enumerate(population):
                if i != j:
                    dist = self._parameter_distance(genome, other)
                    distances.append(dist)
            if distances:
                scores[i] = np.mean(distances)

        # 归一化
        if np.max(scores) > 0:
            scores = scores / np.max(scores)
        return scores

    def _parameter_distance(self, g1: StrategyGenome, g2: StrategyGenome) -> float:
        """计算两个基因组的参数距离"""
        # 计算参数差异
        param_diff = 0
        all_keys = set(g1.parameters.keys()) | set(g2.parameters.keys())
        for key in all_keys:
            v1 = g1.parameters.get(key, 0)
            v2 = g2.parameters.get(key, 0)
            param_diff += (v1 - v2) ** 2

        # 计算超参数差异
        hyper_diff = 0
        all_hyper_keys = set(g1.hyperparameters.keys()) | set(g2.hyperparameters.keys())
        for key in all_hyper_keys:
            v1 = g1.hyperparameters.get(key, 0)
            v2 = g2.hyperparameters.get(key, 0)
            hyper_diff += (v1 - v2) ** 2

        return np.sqrt(param_diff + hyper_diff)


class EliteSelection(SelectionOperator):
    """
    精英选择 (Elite Selection)

    直接选择适应度最高的个体
    用于保留最优解
    """

    def select(self, population: List[StrategyGenome], n: int = 1) -> List[StrategyGenome]:
        """精英选择"""
        if not population or n <= 0:
            return []

        # 按适应度排序
        sorted_pop = sorted(
            population,
            key=lambda g: g.calculate_fitness(),
            reverse=True
        )

        # 选择前n个
        selected = sorted_pop[:n]
        self._record_selection([g.id for g in selected], "elite")
        return selected

    def get_elite(self, population: List[StrategyGenome], ratio: float = None) -> List[StrategyGenome]:
        """获取精英个体"""
        if not population:
            return []

        ratio = ratio or self.config.elite_ratio
        n_elite = max(1, int(len(population) * ratio))
        return self.select(population, n=n_elite)


class BoltzmannSelection(SelectionOperator):
    """
    玻尔兹曼选择 (Boltzmann Selection)

    使用玻尔兹曼分布进行选择，温度参数控制选择压力
    高温：随机选择（探索）
    低温：选择最优（利用）
    """

    def select(self, population: List[StrategyGenome], n: int = 1) -> List[StrategyGenome]:
        """玻尔兹曼选择"""
        if not population or n <= 0:
            return []

        scores = self._calculate_fitness_scores(population)
        temperature = self.config.temperature

        # 玻尔兹曼概率
        exp_scores = np.exp(scores / temperature)
        probabilities = exp_scores / np.sum(exp_scores)

        selected = random.choices(population, weights=probabilities, k=n)
        self._record_selection([g.id for g in selected], "boltzmann")
        return selected

    def update_temperature(self, generation: int, max_generations: int):
        """更新温度 (模拟退火策略)"""
        # 线性降温
        self.config.temperature = max(
            0.1,
            self.config.temperature * (1 - generation / max_generations)
        )


class StochasticUniversalSelection(SelectionOperator):
    """
    随机通用采样 (Stochastic Universal Sampling, SUS)

    轮盘赌的改进版，减少方差，保持选择压力
    """

    def select(self, population: List[StrategyGenome], n: int = 1) -> List[StrategyGenome]:
        """SUS选择"""
        if not population or n <= 0:
            return []

        scores = self._calculate_fitness_scores(population)
        total_fitness = np.sum(scores)

        if total_fitness == 0:
            return random.choices(population, k=n)

        # 等距指针
        pointers_distance = total_fitness / n
        start = random.uniform(0, pointers_distance)
        pointers = [start + i * pointers_distance for i in range(n)]

        selected = []
        cumulative = 0
        pointer_idx = 0

        for genome, score in zip(population, scores):
            cumulative += score
            while pointer_idx < len(pointers) and cumulative >= pointers[pointer_idx]:
                selected.append(genome)
                pointer_idx += 1

        # 如果选不够，随机补充
        while len(selected) < n:
            selected.append(random.choice(population))

        self._record_selection([g.id for g in selected], "sus")
        return selected


class CompositeSelection(SelectionOperator):
    """
    复合选择策略

    组合多种选择方法，根据进化阶段动态调整
    """

    def __init__(self, config: SelectionConfig = None):
        super().__init__(config)
        self.tournament = TournamentSelection(config)
        self.rank = RankSelection(config)
        self.elite = EliteSelection(config)
        self.boltzmann = BoltzmannSelection(config)

        self.generation = 0

    def select(self, population: List[StrategyGenome], n: int = 1) -> List[StrategyGenome]:
        """复合选择"""
        if not population or n <= 0:
            return []

        # 更新各算子的代数
        self.tournament.generation = self.generation
        self.rank.generation = self.generation
        self.elite.generation = self.generation
        self.boltzmann.generation = self.generation

        # 根据进化阶段选择策略
        if self.generation < 10:
            # 早期：多样化选择
            return self.rank.select(population, n)
        elif self.generation < 30:
            # 中期：锦标赛选择
            return self.tournament.select(population, n)
        else:
            # 后期：精英+玻尔兹曼
            n_elite = max(1, int(n * 0.3))
            n_other = n - n_elite

            elite_selected = self.elite.select(population, n_elite)
            other_selected = self.boltzmann.select(population, n_other)

            return elite_selected + other_selected

    def select_with_elite_preservation(
        self,
        population: List[StrategyGenome],
        n: int = 1,
        elite_ratio: float = 0.1
    ) -> List[StrategyGenome]:
        """
        带精英保留的选择

        保留一定比例的最优个体，其余用选择算子选择
        """
        if not population or n <= 0:
            return []

        n_elite = max(1, int(n * elite_ratio))
        n_select = n - n_elite

        # 选择精英
        elite = self.elite.select(population, n_elite)

        # 从非精英中选择
        elite_ids = {g.id for g in elite}
        non_elite = [g for g in population if g.id not in elite_ids]

        if non_elite and n_select > 0:
            others = self.select(non_elite, n_select)
        else:
            others = []

        return elite + others


class SelectionPressureController:
    """
    选择压力控制器

    动态调整选择压力以平衡探索和利用
    """

    def __init__(self, initial_pressure: float = 0.5):
        self.pressure = initial_pressure
        self.history: List[float] = []
        self.diversity_history: List[float] = []

    def update(self, population: List[StrategyGenome]):
        """根据种群状态更新选择压力"""
        if not population:
            return

        # 计算种群多样性
        fitnesses = [g.calculate_fitness() for g in population]
        diversity = np.std(fitnesses) if len(fitnesses) > 1 else 0
        self.diversity_history.append(diversity)

        # 如果多样性过低，降低选择压力 (增加探索)
        if len(self.diversity_history) >= 5:
            avg_diversity = np.mean(self.diversity_history[-5:])
            if avg_diversity < 0.1:
                self.pressure = max(0.1, self.pressure * 0.9)
            elif avg_diversity > 0.5:
                self.pressure = min(1.0, self.pressure * 1.1)

        self.history.append(self.pressure)

    def get_tournament_size(self, population_size: int) -> int:
        """根据选择压力计算锦标赛大小"""
        # 压力越高，锦标赛越大
        base_size = max(2, int(population_size * 0.1))
        pressure_factor = 1 + self.pressure
        return max(2, int(base_size * pressure_factor))


def create_default_selection_operator(
    selection_type: SelectionType = SelectionType.TOURNAMENT,
    tournament_size: int = 3,
    elite_ratio: float = 0.1
) -> SelectionOperator:
    """
    创建默认选择算子

    Args:
        selection_type: 选择类型
        tournament_size: 锦标赛大小
        elite_ratio: 精英比例

    Returns:
        配置好的选择算子
    """
    config = SelectionConfig(
        selection_type=selection_type,
        tournament_size=tournament_size,
        elite_ratio=elite_ratio
    )

    if selection_type == SelectionType.TOURNAMENT:
        return TournamentSelection(config)
    elif selection_type == SelectionType.ROULETTE:
        return RouletteSelection(config)
    elif selection_type == SelectionType.RANK:
        return RankSelection(config)
    elif selection_type == SelectionType.ELITE:
        return EliteSelection(config)
    elif selection_type == SelectionType.BOLTZMANN:
        return BoltzmannSelection(config)
    elif selection_type == SelectionType.STOCHASTIC_UNIVERSAL:
        return StochasticUniversalSelection(config)
    else:
        return CompositeSelection(config)
