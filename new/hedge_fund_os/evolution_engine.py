"""
evolution_engine.py - Evolution Engine for P10 Hedge Fund OS

P10 Hedge Fund OS - Phase 5 Evolution Engine

The Evolution Engine is the "heart" of the system, managing the full lifecycle
of trading strategies: Birth -> Trial -> Active -> Decline -> Death.

It integrates PBT (Population Based Training) and genetic algorithms for
continuous strategy evolution and optimization.
"""

import time
import random
import numpy as np
from typing import Dict, List, Optional, Callable, Any, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum, auto
from datetime import datetime, timedelta
from collections import deque
import copy
import threading
import json

# Import from hedge_fund_os module
try:
    from strategy_genome import (
        StrategyGenome, StrategyStatus, BirthReason,
        PerformanceRecord, GenomeDatabase
    )
    from mutation import (
        MutationOperator, MutationType, MutationConfig,
        create_default_mutation_operator
    )
    from selection import (
        SelectionOperator, SelectionType, SelectionConfig,
        create_default_selection_operator
    )
except ImportError:
    from .strategy_genome import (
        StrategyGenome, StrategyStatus, BirthReason,
        PerformanceRecord, GenomeDatabase
    )
    from .mutation import (
        MutationOperator, MutationType, MutationConfig,
        create_default_mutation_operator
    )
    from .selection import (
        SelectionOperator, SelectionType, SelectionConfig,
        create_default_selection_operator
    )

# Try to import PBT trainer for integration
try:
    import sys
    sys.path.append('D:/binance/new/brain_py')
    from pbt_trainer import PBTTrainer, PBTConfig
    PBT_AVAILABLE = True
except ImportError:
    PBT_AVAILABLE = False


@dataclass
class EvolutionConfig:
    """进化引擎配置"""

    # 种群参数
    population_size: int = 20           # 目标种群大小
    max_active_strategies: int = 10     # 最大活跃策略数
    max_trial_strategies: int = 5       # 最大试用策略数

    # 进化参数
    evolution_interval: int = 100       # 进化间隔（步数）
    mutation_rate: float = 0.1          # 变异率
    crossover_rate: float = 0.3         # 交叉率
    elite_ratio: float = 0.2            # 精英保留比例

    # 生命周期参数
    trial_period_days: int = 7          # 试用期天数
    decline_period_days: int = 7        # 衰退期天数
    min_trades_for_evaluation: int = 10 # 最小交易次数评估

    # 表现阈值
    min_sharpe_for_promotion: float = 0.5   # 晋升最小夏普
    max_drawdown_for_promotion: float = -0.05  # 晋升最大回撤
    min_sharpe_for_retention: float = 0.0   # 保留最小夏普
    max_drawdown_for_elimination: float = -0.15  # 淘汰最大回撤

    # PBT集成
    enable_pbt: bool = True
    pbt_config: Optional[PBTConfig] = None

    # 变异和选择配置
    mutation_type: MutationType = MutationType.GAUSSIAN
    selection_type: SelectionType = SelectionType.TOURNAMENT

    # 回调函数
    on_strategy_birth: Optional[Callable[[StrategyGenome], None]] = None
    on_strategy_promotion: Optional[Callable[[StrategyGenome], None]] = None
    on_strategy_decline: Optional[Callable[[StrategyGenome], None]] = None
    on_strategy_death: Optional[Callable[[StrategyGenome], None]] = None


@dataclass
class EvolutionStats:
    """进化统计"""
    generation: int = 0
    total_births: int = 0
    total_deaths: int = 0
    total_mutations: int = 0
    total_crossovers: int = 0
    last_evolution_time: Optional[datetime] = None

    # 当前状态
    active_count: int = 0
    trial_count: int = 0
    decline_count: int = 0
    dead_count: int = 0

    # 表现统计
    best_fitness: float = 0.0
    avg_fitness: float = 0.0
    diversity_score: float = 0.0


class EvolutionEngine:
    """
    进化引擎 - 策略生命周期管理的核心

    管理策略的完整生命周期：
    Birth (新生) -> Trial (试用) -> Active (活跃) -> Decline (衰退) -> Death (死亡)

    核心功能：
    1. 策略生成 (create_strategy) - 创建新策略
    2. 策略评估 (evaluate_strategy) - 评估表现
    3. 策略变异 (mutate) - 参数变异
    4. 策略交叉 (crossover) - 基因重组
    5. 策略淘汰 (eliminate) - 淘汰表现差的策略
    6. 进化循环 (evolve) - 主进化循环

    与PBT集成：
    - 使用PBT进行异步超参优化
    - 种群管理和进化决策由EvolutionEngine主导
    """

    def __init__(self, config: EvolutionConfig = None):
        self.config = config or EvolutionConfig()
        self.genome_db = GenomeDatabase()
        self.stats = EvolutionStats()

        # 变异和选择算子
        self.mutation_op = create_default_mutation_operator(
            mutation_type=self.config.mutation_type,
            mutation_rate=self.config.mutation_rate
        )
        self.selection_op = create_default_selection_operator(
            selection_type=self.config.selection_type,
            elite_ratio=self.config.elite_ratio
        )

        # PBT训练器
        self.pbt_trainer: Optional[Any] = None
        if self.config.enable_pbt and PBT_AVAILABLE:
            pbt_config = self.config.pbt_config or PBTConfig(
                population_size=self.config.population_size
            )
            self.pbt_trainer = PBTTrainer(pbt_config)

        # 策略工厂注册
        self._strategy_factories: Dict[str, Callable] = {}

        # 运行状态
        self._running = False
        self._lock = threading.RLock()
        self._step_count = 0
        self._evolution_history: deque = deque(maxlen=1000)

        # 事件回调
        self._callbacks: Dict[str, List[Callable]] = {
            'birth': [],
            'promotion': [],
            'decline': [],
            'death': [],
            'evolution': []
        }

        print(f"[EvolutionEngine] Initialized with population_size={self.config.population_size}")

    def register_strategy_factory(self, strategy_type: str, factory: Callable):
        """
        注册策略工厂函数

        Args:
            strategy_type: 策略类型标识
            factory: 工厂函数，接收参数返回策略实例
        """
        self._strategy_factories[strategy_type] = factory
        print(f"[EvolutionEngine] Registered factory for {strategy_type}")

    def register_callback(self, event: str, callback: Callable):
        """注册事件回调"""
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _trigger_callback(self, event: str, genome: StrategyGenome):
        """触发回调"""
        for callback in self._callbacks.get(event, []):
            try:
                callback(genome)
            except Exception as e:
                print(f"[EvolutionEngine] Callback error: {e}")

        # 同时触发配置中的回调
        config_callback = getattr(self.config, f'on_strategy_{event}', None)
        if config_callback:
            try:
                config_callback(genome)
            except Exception as e:
                print(f"[EvolutionEngine] Config callback error: {e}")

    def create_strategy(
        self,
        strategy_type: str = None,
        parent_ids: List[str] = None,
        name: str = None,
        birth_reason: str = BirthReason.MANUAL.value
    ) -> StrategyGenome:
        """
        创建新策略 (Birth)

        Args:
            strategy_type: 策略类型
            parent_ids: 父策略ID列表
            name: 策略名称
            birth_reason: 生成原因

        Returns:
            新创建的StrategyGenome
        """
        with self._lock:
            # 生成唯一ID
            genome_id = f"strat_{int(time.time()*1000)%10000}_{random.randint(100, 999)}"

            # 确定策略类型
            if strategy_type is None:
                strategy_type = random.choice(list(self._strategy_factories.keys())) \
                    if self._strategy_factories else "unknown"

            # 创建基因组
            genome = StrategyGenome(
                id=genome_id,
                name=name or f"Strategy_{genome_id[-6:]}",
                version="1.0.0",
                parent_ids=parent_ids or [],
                strategy_type=strategy_type,
                strategy_class=strategy_type,
                birth_reason=birth_reason,
                status=StrategyStatus.BIRTH,
                generation=0
            )

            # 如果有父代，继承参数
            if parent_ids:
                parents = [self.genome_db.get(pid) for pid in parent_ids]
                parents = [p for p in parents if p is not None]
                if parents:
                    # 继承第一个父代的参数
                    genome.parameters = copy.deepcopy(parents[0].parameters)
                    genome.hyperparameters = copy.deepcopy(parents[0].hyperparameters)
                    genome.generation = max(p.generation for p in parents) + 1
            else:
                # 随机初始化参数
                genome.parameters = self._initialize_parameters(strategy_type)
                genome.hyperparameters = self._initialize_hyperparameters()

            # 添加到数据库
            self.genome_db.add(genome)
            self.stats.total_births += 1

            # 触发回调
            self._trigger_callback('birth', genome)

            print(f"[EvolutionEngine] New strategy born: {genome.id} ({genome.name}) "
                  f"type={genome.strategy_type}, gen={genome.generation}")

            return genome

    def _initialize_parameters(self, strategy_type: str) -> Dict[str, float]:
        """初始化策略参数"""
        # 默认参数模板
        default_params = {
            'lookback': random.randint(10, 100),
            'threshold': random.uniform(0.1, 0.5),
            'position_size': random.uniform(0.1, 0.5),
            'stop_loss': random.uniform(0.01, 0.05),
            'take_profit': random.uniform(0.02, 0.1),
        }

        # 根据策略类型调整
        if strategy_type == 'trend':
            default_params['fast_ma'] = random.randint(5, 20)
            default_params['slow_ma'] = random.randint(20, 60)
        elif strategy_type == 'mean_rev':
            default_params['zscore_threshold'] = random.uniform(1.5, 2.5)
            default_params['mean_period'] = random.randint(20, 50)
        elif strategy_type == 'momentum':
            default_params['momentum_period'] = random.randint(10, 30)
            default_params['momentum_threshold'] = random.uniform(0.05, 0.2)

        return default_params

    def _initialize_hyperparameters(self) -> Dict[str, float]:
        """初始化超参数"""
        return {
            'learning_rate': 10 ** random.uniform(-5, -2),
            'confidence_threshold': random.uniform(0.3, 0.7),
            'risk_factor': random.uniform(0.5, 1.5),
            'adaptation_rate': random.uniform(0.01, 0.1),
        }

    def evaluate_strategy(self, strategy_id: str) -> Optional[PerformanceRecord]:
        """
        评估策略表现

        Args:
            strategy_id: 策略ID

        Returns:
            PerformanceRecord或None
        """
        genome = self.genome_db.get(strategy_id)
        if not genome:
            return None

        # 获取最新表现记录
        latest = genome.get_latest_performance()
        if not latest:
            return None

        # 计算综合适应度
        latest.fitness_score = genome.calculate_fitness()

        return latest

    def mutate(self, genome: StrategyGenome) -> StrategyGenome:
        """
        变异策略参数

        Args:
            genome: 原始基因组

        Returns:
            变异后的新基因组
        """
        mutant = self.mutation_op.mutate(genome)
        mutant.birth_reason = BirthReason.MUTATION.value

        self.stats.total_mutations += 1

        # 添加到数据库
        self.genome_db.add(mutant)
        self.stats.total_births += 1

        print(f"[EvolutionEngine] Mutated {genome.id} -> {mutant.id}")

        return mutant

    def crossover(self, parent1_id: str, parent2_id: str) -> Optional[StrategyGenome]:
        """
        交叉两个策略

        Args:
            parent1_id: 父代1 ID
            parent2_id: 父代2 ID

        Returns:
            交叉后的新基因组
        """
        parent1 = self.genome_db.get(parent1_id)
        parent2 = self.genome_db.get(parent2_id)

        if not parent1 or not parent2:
            return None

        # 创建子代
        child_id = f"cross_{int(time.time()*1000)%10000}_{random.randint(100, 999)}"
        child = StrategyGenome(
            id=child_id,
            name=f"{parent1.name}_x_{parent2.name}",
            version="1.0.0",
            parent_ids=[parent1_id, parent2_id],
            strategy_type=parent1.strategy_type,
            strategy_class=parent1.strategy_class,
            birth_reason=BirthReason.CROSSOVER.value,
            status=StrategyStatus.BIRTH,
            generation=max(parent1.generation, parent2.generation) + 1
        )

        # 参数交叉 (均匀交叉)
        child.parameters = self._crossover_params(
            parent1.parameters, parent2.parameters
        )
        child.hyperparameters = self._crossover_params(
            parent1.hyperparameters, parent2.hyperparameters
        )

        self.stats.total_crossovers += 1

        # 添加到数据库
        self.genome_db.add(child)
        self.stats.total_births += 1

        print(f"[EvolutionEngine] Crossover {parent1_id} x {parent2_id} -> {child_id}")

        return child

    def _crossover_params(
        self,
        params1: Dict[str, float],
        params2: Dict[str, float]
    ) -> Dict[str, float]:
        """参数交叉"""
        child_params = {}
        all_keys = set(params1.keys()) | set(params2.keys())

        for key in all_keys:
            if key in params1 and key in params2:
                # 均匀交叉：随机选择父代值或平均值
                if random.random() < 0.5:
                    child_params[key] = params1[key]
                else:
                    child_params[key] = params2[key]

                # 20%概率取平均
                if random.random() < 0.2:
                    child_params[key] = (params1[key] + params2[key]) / 2
            elif key in params1:
                child_params[key] = params1[key]
            else:
                child_params[key] = params2[key]

        return child_params

    def eliminate(self, strategy_id: str, reason: str = "poor_performance") -> bool:
        """
        淘汰策略 (Death)

        Args:
            strategy_id: 策略ID
            reason: 淘汰原因

        Returns:
            是否成功淘汰
        """
        with self._lock:
            genome = self.genome_db.get(strategy_id)
            if not genome:
                return False

            if genome.status == StrategyStatus.DEAD:
                return True

            # 转换状态为死亡
            genome.transition_status(StrategyStatus.DEAD)
            genome.capital_weight = 0.0

            self.stats.total_deaths += 1

            # 触发回调
            self._trigger_callback('death', genome)

            print(f"[EvolutionEngine] Strategy eliminated: {strategy_id} (reason: {reason})")

            return True

    def promote_to_trial(self, strategy_id: str) -> bool:
        """
        将策略从Birth提升为Trial

        Args:
            strategy_id: 策略ID

        Returns:
            是否成功晋升
        """
        genome = self.genome_db.get(strategy_id)
        if not genome or genome.status != StrategyStatus.BIRTH:
            return False

        # 检查试用名额
        trial_count = len(self.genome_db.get_by_status(StrategyStatus.TRIAL))
        if trial_count >= self.config.max_trial_strategies:
            print(f"[EvolutionEngine] Trial pool full, cannot promote {strategy_id}")
            return False

        genome.transition_status(StrategyStatus.TRIAL)
        genome.trial_start_time = datetime.now()

        print(f"[EvolutionEngine] Strategy {strategy_id} promoted to TRIAL")

        return True

    def promote_to_active(self, strategy_id: str) -> bool:
        """
        将策略从Trial提升为Active

        Args:
            strategy_id: 策略ID

        Returns:
            是否成功晋升
        """
        genome = self.genome_db.get(strategy_id)
        if not genome or genome.status != StrategyStatus.TRIAL:
            return False

        # 检查是否有资格晋升
        if not genome.is_eligible_for_promotion():
            print(f"[EvolutionEngine] Strategy {strategy_id} not eligible for promotion")
            return False

        # 检查活跃名额
        active_count = len(self.genome_db.get_by_status(StrategyStatus.ACTIVE))
        if active_count >= self.config.max_active_strategies:
            # 尝试降级表现最差的活跃策略
            self._demote_weakest_active()

        genome.transition_status(StrategyStatus.ACTIVE)
        genome.active_start_time = datetime.now()

        # 触发回调
        self._trigger_callback('promotion', genome)

        print(f"[EvolutionEngine] Strategy {strategy_id} promoted to ACTIVE")

        return True

    def demote_to_decline(self, strategy_id: str) -> bool:
        """
        将策略降级为Decline

        Args:
            strategy_id: 策略ID

        Returns:
            是否成功降级
        """
        genome = self.genome_db.get(strategy_id)
        if not genome or genome.status not in [StrategyStatus.ACTIVE, StrategyStatus.TRIAL]:
            return False

        genome.transition_status(StrategyStatus.DECLINE)
        genome.decline_start_time = datetime.now()

        # 触发回调
        self._trigger_callback('decline', genome)

        print(f"[EvolutionEngine] Strategy {strategy_id} demoted to DECLINE")

        return True

    def _demote_weakest_active(self):
        """降级表现最差的活跃策略"""
        active = self.genome_db.get_by_status(StrategyStatus.ACTIVE)
        if not active:
            return

        # 找到表现最差的
        weakest = min(active, key=lambda g: g.calculate_fitness())
        self.demote_to_decline(weakest.id)

    def update_performance(
        self,
        strategy_id: str,
        record: PerformanceRecord
    ) -> bool:
        """
        更新策略表现

        Args:
            strategy_id: 策略ID
            record: 表现记录

        Returns:
            是否成功更新
        """
        genome = self.genome_db.get(strategy_id)
        if not genome:
            return False

        # 添加表现记录
        genome.add_performance_record(record)

        # 检查状态转换
        self._check_status_transitions(genome)

        return True

    def _check_status_transitions(self, genome: StrategyGenome):
        """检查并执行状态转换"""
        # 检查是否应该被淘汰
        if genome.should_be_eliminated():
            self.eliminate(genome.id, reason="performance_threshold")
            return

        # 根据当前状态检查转换
        if genome.status == StrategyStatus.BIRTH:
            # Birth -> Trial: 回测验证通过
            if len(genome.performance_history) >= 1:
                self.promote_to_trial(genome.id)

        elif genome.status == StrategyStatus.TRIAL:
            # Trial -> Active: 表现达标
            if genome.is_eligible_for_promotion():
                self.promote_to_active(genome.id)
            # Trial -> Decline: 试用期表现不佳
            elif len(genome.performance_history) >= 5:
                recent = genome.get_mean_performance(window=5)
                if recent.get('sharpe_ratio', 0) < 0:
                    self.demote_to_decline(genome.id)

        elif genome.status == StrategyStatus.ACTIVE:
            # Active -> Decline: 表现衰退
            recent = genome.get_mean_performance(window=5)
            if recent:
                if (recent.get('sharpe_ratio', 0) < self.config.min_sharpe_for_retention or
                    recent.get('max_drawdown', 0) < -0.1):
                    self.demote_to_decline(genome.id)

        elif genome.status == StrategyStatus.DECLINE:
            # Decline -> Death: 衰退期结束或持续亏损
            if genome.decline_start_time:
                days_in_decline = (datetime.now() - genome.decline_start_time).days
                if days_in_decline >= self.config.decline_period_days:
                    self.eliminate(genome.id, reason="decline_period_expired")
                    return

            # 检查是否有恢复
            recent = genome.get_mean_performance(window=3)
            if recent and recent.get('sharpe_ratio', 0) > self.config.min_sharpe_for_promotion:
                # 恢复为Active
                genome.transition_status(StrategyStatus.ACTIVE)
                genome.decline_start_time = None
                print(f"[EvolutionEngine] Strategy {genome.id} recovered to ACTIVE")

    def evolve(self):
        """
        主进化循环

        执行一轮进化：
        1. 评估所有策略
        2. 选择优秀策略
        3. 变异/交叉生成新策略
        4. 淘汰表现差的策略
        """
        with self._lock:
            print(f"\n[EvolutionEngine] === Evolution Cycle {self.stats.generation} ===")

            # 1. 获取所有存活策略
            alive_strategies = self.genome_db.get_all_alive()

            if len(alive_strategies) < 2:
                print("[EvolutionEngine] Not enough strategies to evolve")
                return

            # 2. 评估并排序
            sorted_strategies = sorted(
                alive_strategies,
                key=lambda g: g.calculate_fitness(),
                reverse=True
            )

            # 3. 更新统计
            self._update_stats(sorted_strategies)

            # 4. 精英保留
            n_elite = max(1, int(len(sorted_strategies) * self.config.elite_ratio))
            elite = sorted_strategies[:n_elite]

            # 5. 生成新策略 (变异)
            n_mutations = max(1, int(len(sorted_strategies) * self.config.mutation_rate))
            for _ in range(n_mutations):
                parent = random.choice(elite)
                self.mutate(parent)

            # 6. 生成新策略 (交叉)
            n_crossovers = max(1, int(len(sorted_strategies) * self.config.crossover_rate))
            for _ in range(n_crossovers):
                if len(elite) >= 2:
                    p1, p2 = random.sample(elite, 2)
                    self.crossover(p1.id, p2.id)

            # 7. 淘汰表现差的策略
            self._eliminate_poor_performers(sorted_strategies)

            # 8. 补充种群
            self._replenish_population()

            # 9. 更新统计
            self.stats.generation += 1
            self.stats.last_evolution_time = datetime.now()

            # 10. PBT更新 (如果启用)
            if self.pbt_trainer:
                self._sync_with_pbt()

            # 记录历史
            self._evolution_history.append({
                'generation': self.stats.generation,
                'population_size': len(alive_strategies),
                'best_fitness': self.stats.best_fitness,
                'avg_fitness': self.stats.avg_fitness,
                'timestamp': datetime.now().isoformat()
            })

            print(f"[EvolutionEngine] === Evolution Complete ===")
            print(f"  Generation: {self.stats.generation}")
            print(f"  Population: {len(alive_strategies)}")
            print(f"  Best Fitness: {self.stats.best_fitness:.4f}")
            print(f"  Avg Fitness: {self.stats.avg_fitness:.4f}")

            # 触发进化回调
            for callback in self._callbacks.get('evolution', []):
                try:
                    callback(self.stats)
                except Exception as e:
                    print(f"[EvolutionEngine] Evolution callback error: {e}")

    def _update_stats(self, sorted_strategies: List[StrategyGenome]):
        """更新统计信息"""
        if not sorted_strategies:
            return

        fitnesses = [g.calculate_fitness() for g in sorted_strategies]
        self.stats.best_fitness = max(fitnesses)
        self.stats.avg_fitness = np.mean(fitnesses)
        self.stats.diversity_score = np.std(fitnesses) if len(fitnesses) > 1 else 0

        # 状态统计
        self.stats.active_count = len([g for g in sorted_strategies if g.status == StrategyStatus.ACTIVE])
        self.stats.trial_count = len([g for g in sorted_strategies if g.status == StrategyStatus.TRIAL])
        self.stats.decline_count = len([g for g in sorted_strategies if g.status == StrategyStatus.DECLINE])
        self.stats.dead_count = len(self.genome_db.get_by_status(StrategyStatus.DEAD))

    def _eliminate_poor_performers(self, sorted_strategies: List[StrategyGenome]):
        """淘汰表现差的策略"""
        # 淘汰后20%
        n_eliminate = max(0, int(len(sorted_strategies) * 0.2) - self.stats.dead_count)

        candidates_for_elimination = [
            g for g in sorted_strategies
            if g.status not in [StrategyStatus.DEAD, StrategyStatus.ACTIVE]
        ]

        # 优先淘汰衰退期策略
        decline_strategies = [g for g in candidates_for_elimination if g.status == StrategyStatus.DECLINE]
        for g in decline_strategies[:n_eliminate]:
            self.eliminate(g.id, reason="evolution_elimination")

        # 如果还不够，淘汰表现最差的试用策略
        remaining = n_eliminate - len(decline_strategies)
        if remaining > 0:
            trial_strategies = [g for g in candidates_for_elimination if g.status == StrategyStatus.TRIAL]
            trial_strategies.sort(key=lambda g: g.calculate_fitness())
            for g in trial_strategies[:remaining]:
                self.eliminate(g.id, reason="evolution_elimination")

    def _replenish_population(self):
        """补充种群到目标大小"""
        alive_count = len(self.genome_db.get_all_alive())

        while alive_count < self.config.population_size:
            # 随机创建新策略或变异现有策略
            if random.random() < 0.5 and self.genome_db.get_all_alive():
                # 变异现有策略
                parent = random.choice(self.genome_db.get_all_alive())
                self.mutate(parent)
            else:
                # 创建全新策略
                strategy_type = random.choice(list(self._strategy_factories.keys())) \
                    if self._strategy_factories else "unknown"
                self.create_strategy(
                    strategy_type=strategy_type,
                    birth_reason=BirthReason.IMMIGRATION.value
                )

            alive_count = len(self.genome_db.get_all_alive())

    def _sync_with_pbt(self):
        """与PBT训练器同步"""
        if not self.pbt_trainer:
            return

        # 将表现数据同步到PBT
        for genome in self.genome_db.get_all_alive():
            if genome.performance_history:
                latest = genome.get_latest_performance()
                # 这里可以调用PBT的更新方法

    def step(self):
        """执行一步 (用于与外部训练循环集成)"""
        self._step_count += 1

        # 检查是否需要进化
        if self._step_count % self.config.evolution_interval == 0:
            self.evolve()

        # 定期检查状态转换
        if self._step_count % 10 == 0:
            for genome in self.genome_db.get_all_alive():
                self._check_status_transitions(genome)

    def get_best_strategy(self) -> Optional[StrategyGenome]:
        """获取表现最好的策略"""
        elite = self.genome_db.get_elite(n=1)
        return elite[0] if elite else None

    def get_active_strategies(self) -> List[StrategyGenome]:
        """获取所有活跃策略"""
        return self.genome_db.get_by_status(StrategyStatus.ACTIVE)

    def get_strategy_allocation_weights(self) -> Dict[str, float]:
        """
        获取策略资金分配权重

        基于策略表现和状态计算权重
        """
        active = self.get_active_strategies()
        if not active:
            return {}

        # 基于适应度计算权重
        fitnesses = {g.id: max(0, g.calculate_fitness()) for g in active}
        total_fitness = sum(fitnesses.values())

        if total_fitness == 0:
            # 均匀分配
            n = len(active)
            return {g.id: 1.0 / n for g in active}

        # 按适应度比例分配
        weights = {sid: fit / total_fitness for sid, fit in fitnesses.items()}

        # 更新策略的权重记录
        for g in active:
            g.capital_weight = weights.get(g.id, 0)

        return weights

    def export_state(self) -> Dict[str, Any]:
        """导出完整状态"""
        return {
            'config': {
                'population_size': self.config.population_size,
                'max_active_strategies': self.config.max_active_strategies,
                'evolution_interval': self.config.evolution_interval,
                'mutation_rate': self.config.mutation_rate,
                'crossover_rate': self.config.crossover_rate,
            },
            'stats': {
                'generation': self.stats.generation,
                'total_births': self.stats.total_births,
                'total_deaths': self.stats.total_deaths,
                'total_mutations': self.stats.total_mutations,
                'total_crossovers': self.stats.total_crossovers,
                'best_fitness': self.stats.best_fitness,
                'avg_fitness': self.stats.avg_fitness,
            },
            'genome_db': self.genome_db.export_all(),
            'evolution_history': list(self._evolution_history),
            'export_time': datetime.now().isoformat()
        }

    def save_checkpoint(self, filepath: str):
        """保存检查点"""
        state = self.export_state()
        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2)
        print(f"[EvolutionEngine] Checkpoint saved to {filepath}")

    def load_checkpoint(self, filepath: str) -> bool:
        """加载检查点"""
        try:
            with open(filepath, 'r') as f:
                state = json.load(f)

            # 恢复统计
            stats_data = state.get('stats', {})
            self.stats.generation = stats_data.get('generation', 0)
            self.stats.total_births = stats_data.get('total_births', 0)
            self.stats.total_deaths = stats_data.get('total_deaths', 0)
            self.stats.total_mutations = stats_data.get('total_mutations', 0)
            self.stats.total_crossovers = stats_data.get('total_crossovers', 0)

            # 恢复基因组数据库
            self.genome_db = GenomeDatabase()
            for gid, genome_data in state.get('genome_db', {}).get('genomes', {}).items():
                genome = StrategyGenome.from_dict(genome_data)
                self.genome_db.add(genome)

            # 恢复历史
            self._evolution_history = deque(maxlen=1000)
            for entry in state.get('evolution_history', []):
                self._evolution_history.append(entry)

            print(f"[EvolutionEngine] Checkpoint loaded from {filepath}")
            return True

        except Exception as e:
            print(f"[EvolutionEngine] Failed to load checkpoint: {e}")
            return False

    def reset(self):
        """重置引擎"""
        with self._lock:
            self.genome_db = GenomeDatabase()
            self.stats = EvolutionStats()
            self._step_count = 0
            self._evolution_history.clear()
            print("[EvolutionEngine] Reset complete")


def create_default_evolution_engine(
    population_size: int = 20,
    max_active: int = 10
) -> EvolutionEngine:
    """
    创建默认进化引擎

    Args:
        population_size: 种群大小
        max_active: 最大活跃策略数

    Returns:
        配置好的EvolutionEngine
    """
    config = EvolutionConfig(
        population_size=population_size,
        max_active_strategies=max_active,
        evolution_interval=100,
        mutation_rate=0.1,
        crossover_rate=0.3,
        elite_ratio=0.2
    )

    return EvolutionEngine(config)
