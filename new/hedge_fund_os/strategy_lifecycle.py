"""
P10 Hedge Fund OS - 策略生命周期管理

实现"实验田"与"粮仓"的严格资金隔离：
- BIRTH/TRIAL: 最多2-5% AUM，视为探索成本
- ACTIVE: 主要资金池，经过验证的策略
- DECLINE: 冻结变异，逐步减仓
- DEAD: 淘汰，资金归零

关键约束：
- 实验田总额 ≤ 5% AUM
- ACTIVE策略才能参与PBT变异
- DECLINE策略禁止变异直到重新通过TRIAL
"""

import time
import uuid
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class StrategyStatus(Enum):
    """策略生命周期状态"""
    BIRTH = "birth"       # 刚创建，极小资金测试 (0.1% - 0.5%)
    TRIAL = "trial"       # 试用期，小资金验证 (0.5% - 2%)
    ACTIVE = "active"     # 转正，正常资金分配
    DECLINE = "decline"   # 表现下滑，减仓观察
    DEAD = "dead"         # 淘汰，资金归零


@dataclass
class StrategyGenome:
    """
    策略基因 - 可进化的参数集合 (生命周期扩展版)
    
    注：这是 StrategyGenome 的完整实现，包含生命周期管理所需的扩展字段
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    version: str = "1.0.0"
    parent_ids: List[str] = field(default_factory=list)
    
    # 策略参数 (可变异)
    parameters: Dict[str, float] = field(default_factory=dict)
    
    # 超参数 (控制行为)
    hyperparameters: Dict[str, float] = field(default_factory=dict)
    
    # 表现历史 (PBT评估用)
    sharpe_history: List[float] = field(default_factory=list)
    pnl_history: List[float] = field(default_factory=list)
    
    # 元数据
    created_at: datetime = field(default_factory=datetime.now)
    birth_reason: str = "manual"  # mutation/crossover/manual/market_regime
    status: StrategyStatus = StrategyStatus.BIRTH
    generation: int = 0
    
    # 生命周期管理时间戳
    trial_start_time: Optional[float] = None
    active_start_time: Optional[float] = None
    last_evaluated: float = field(default_factory=time.time)


@dataclass  
class LifecycleConfig:
    """生命周期配置"""
    # 资金隔离约束
    max_experimental_allocation: float = 0.05  # 实验田总额 ≤ 5% AUM
    birth_allocation: float = 0.001            # BIRTH: 0.1%
    trial_allocation: float = 0.02             # TRIAL: 2%
    
    # 状态转换阈值
    trial_duration_hours: float = 24.0         # TRIAL 最短持续时间
    active_sharpe_threshold: float = 1.0       # 转正 Sharpe 要求
    decline_consecutive_losses: int = 3        # 连续亏损天数进入 DECLINE
    decline_max_drawdown: float = 0.10         # DECLINE 回撤阈值
    dead_max_drawdown: float = 0.15            # 死亡线
    
    # PBT约束
    mutation_rate: float = 0.1
    mutation_noise: float = 0.05
    min_population_size: int = 3
    elite_ratio: float = 0.3
    
    # 常识约束器 (防止进化过拟合)
    parameter_constraints: Dict[str, tuple] = field(default_factory=lambda: {
        # (min, max, relationship_constraints)
        'ema_fast': (5, 50, None),
        'ema_slow': (20, 200, {'>': 'ema_fast'}),  # ema_slow 必须 > ema_fast
        'stop_loss_pct': (0.001, 0.05, None),      # 0.1% - 5%
        'take_profit_pct': (0.002, 0.10, {'>': 'stop_loss_pct'}),
        'position_size': (0.01, 0.5, None),        # 1% - 50%
    })


class StrategyLifecycleManager:
    """
    策略生命周期管理器
    
    核心职责：
    1. 维护策略种群状态
    2. 执行状态转换规则
    3. 计算各状态资金配额
    4. 提供PBT所需的精英选择
    """
    
    def __init__(self, config: Optional[LifecycleConfig] = None):
        self.config = config or LifecycleConfig()
        self.strategies: Dict[str, StrategyGenome] = {}
        self.status_callbacks: Dict[StrategyStatus, List[Callable]] = {
            status: [] for status in StrategyStatus
        }
        
        # 统计
        self.transitions_count = 0
        self.birth_count = 0
        self.death_count = 0
    
    def register_strategy(self, genome: StrategyGenome) -> str:
        """注册新策略，自动进入 BIRTH 状态"""
        genome.status = StrategyStatus.BIRTH
        genome.trial_start_time = time.time()
        self.strategies[genome.id] = genome
        self.birth_count += 1
        
        print(f"[Lifecycle] New strategy born: {genome.id} "
              f"(gen={genome.generation}, reason={genome.birth_reason})")
        return genome.id
    
    def evaluate_and_transition(self, strategy_id: str, 
                                sharpe: float, 
                                total_return: float,
                                max_drawdown: float,
                                consecutive_loss_days: int) -> StrategyStatus:
        """
        评估策略表现并执行状态转换
        
        转换规则：
        - BIRTH → TRIAL: 自动，BIRTH持续1小时后
        - TRIAL → ACTIVE: Sharpe > 1.0 且 持续24小时
        - ACTIVE → DECLINE: 连续3天亏损 或 回撤>10%
        - DECLINE → TRIAL: 重新验证 (冻结变异)
        - DECLINE → DEAD: 回撤>15%
        """
        strategy = self.strategies.get(strategy_id)
        if not strategy:
            return StrategyStatus.DEAD
        
        old_status = strategy.status
        new_status = old_status
        now = time.time()
        
        # 更新历史
        strategy.sharpe_history.append(sharpe)
        strategy.pnl_history.append(total_return)
        strategy.last_evaluated = now
        
        # 状态转换逻辑
        if old_status == StrategyStatus.BIRTH:
            # BIRTH 1小时后自动进入 TRIAL
            if strategy.trial_start_time and \
               (now - strategy.trial_start_time) > 3600:
                new_status = StrategyStatus.TRIAL
                print(f"[Lifecycle] {strategy_id}: BIRTH → TRIAL")
        
        elif old_status == StrategyStatus.TRIAL:
            # TRIAL 24小时 + Sharpe > 1.0 → ACTIVE
            trial_duration = now - (strategy.trial_start_time or now)
            if trial_duration >= self.config.trial_duration_hours * 3600:
                if sharpe >= self.config.active_sharpe_threshold:
                    new_status = StrategyStatus.ACTIVE
                    strategy.active_start_time = now
                    print(f"[Lifecycle] {strategy_id}: TRIAL → ACTIVE "
                          f"(sharpe={sharpe:.2f})")
                elif max_drawdown > self.config.decline_max_drawdown:
                    new_status = StrategyStatus.DEAD
                    print(f"[Lifecycle] {strategy_id}: TRIAL → DEAD "
                          f"(drawdown={max_drawdown:.2%})")
        
        elif old_status == StrategyStatus.ACTIVE:
            # ACTIVE → DECLINE 触发条件
            if (consecutive_loss_days >= self.config.decline_consecutive_losses or
                max_drawdown > self.config.decline_max_drawdown):
                new_status = StrategyStatus.DECLINE
                print(f"[Lifecycle] {strategy_id}: ACTIVE → DECLINE "
                      f"(losses={consecutive_loss_days}, dd={max_drawdown:.2%})")
        
        elif old_status == StrategyStatus.DECLINE:
            # DECLINE 中禁止变异，表现恢复可重回 TRIAL
            if max_drawdown > self.config.dead_max_drawdown:
                new_status = StrategyStatus.DEAD
                print(f"[Lifecycle] {strategy_id}: DECLINE → DEAD")
            elif sharpe >= self.config.active_sharpe_threshold * 1.2:  # 更高要求
                new_status = StrategyStatus.TRIAL  # 重新验证，不是直接回ACTIVE
                strategy.trial_start_time = now
                print(f"[Lifecycle] {strategy_id}: DECLINE → TRIAL "
                      f"(recovery, sharpe={sharpe:.2f})")
        
        # 执行转换
        if new_status != old_status:
            strategy.status = new_status
            self.transitions_count += 1
            self._emit_status_change(strategy, old_status, new_status)
            
            if new_status == StrategyStatus.DEAD:
                self.death_count += 1
        
        return new_status
    
    def calculate_allocations(self, total_aum: float) -> Dict[str, float]:
        """
        计算各策略的资金配额
        
        核心约束：
        - 实验田总额 (BIRTH + TRIAL) ≤ 5% AUM
        - DEAD 策略获得 0 资金
        - DECLINE 策略资金减半
        """
        allocations = {}
        experimental_used = 0.0
        
        # 第一阶段：分配实验田资金
        for sid, strategy in self.strategies.items():
            if strategy.status == StrategyStatus.DEAD:
                allocations[sid] = 0.0
            elif strategy.status == StrategyStatus.BIRTH:
                alloc = total_aum * self.config.birth_allocation
                allocations[sid] = alloc
                experimental_used += alloc
            elif strategy.status == StrategyStatus.TRIAL:
                alloc = total_aum * self.config.trial_allocation
                # 检查实验田总额约束
                if experimental_used + alloc > total_aum * self.config.max_experimental_allocation:
                    alloc = max(0, total_aum * self.config.max_experimental_allocation - experimental_used)
                allocations[sid] = alloc
                experimental_used += alloc
        
        # 第二阶段：ACTIVE 策略分配剩余资金
        active_strategies = [
            s for s in self.strategies.values() 
            if s.status == StrategyStatus.ACTIVE
        ]
        
        remaining_aum = total_aum - experimental_used
        
        if active_strategies and remaining_aum > 0:
            # 按 Sharpe 加权分配
            total_sharpe = sum(max(0, s.sharpe_history[-1]) for s in active_strategies 
                             if s.sharpe_history)
            
            if total_sharpe > 0:
                for strategy in active_strategies:
                    sharpe = strategy.sharpe_history[-1] if strategy.sharpe_history else 0
                    weight = max(0, sharpe) / total_sharpe
                    allocations[strategy.id] = remaining_aum * weight
            else:
                # 等权分配
                equal_alloc = remaining_aum / len(active_strategies)
                for strategy in active_strategies:
                    allocations[strategy.id] = equal_alloc
        
        # 第三阶段：DECLINE 策略减半
        for sid, strategy in self.strategies.items():
            if strategy.status == StrategyStatus.DECLINE:
                # DECLINE 获得原本的一半，但不超过2%
                base_alloc = total_aum * 0.02
                allocations[sid] = base_alloc * 0.5
        
        return allocations
    
    def get_elites_for_breeding(self, n: int = 3) -> List[StrategyGenome]:
        """
        获取用于繁殖的精英策略
        
        约束：只有 ACTIVE 策略才能参与PBT变异
        """
        active_strategies = [
            s for s in self.strategies.values()
            if s.status == StrategyStatus.ACTIVE and s.sharpe_history
        ]
        
        # 按最近Sharpe排序
        sorted_strategies = sorted(
            active_strategies,
            key=lambda s: s.sharpe_history[-1] if s.sharpe_history else -999,
            reverse=True
        )
        
        return sorted_strategies[:n]
    
    def can_mutate(self, strategy_id: str) -> bool:
        """
        检查策略是否允许变异
        
        DECLINE 状态策略禁止变异 (必须重新通过TRIAL验证)
        """
        strategy = self.strategies.get(strategy_id)
        if not strategy:
            return False
        
        # 只有 ACTIVE 和 TRIAL 策略可以变异
        return strategy.status in (StrategyStatus.ACTIVE, StrategyStatus.TRIAL)
    
    def apply_common_sense_constraints(self, parameters: Dict[str, float]) -> Dict[str, float]:
        """
        常识约束器 - 防止进化过拟合
        
        例如：
        - EMA快线不能大于慢线
        - 止损不能小于平均滑点3倍
        """
        constrained = dict(parameters)
        
        for param_name, (min_val, max_val, constraints) in self.config.parameter_constraints.items():
            if param_name not in constrained:
                continue
            
            # 基础范围约束
            constrained[param_name] = max(min_val, min(max_val, constrained[param_name]))
            
            # 关系约束
            if constraints:
                for op, related_param in constraints.items():
                    if related_param not in constrained:
                        continue
                    
                    related_val = constrained[related_param]
                    current_val = constrained[param_name]
                    
                    if op == '>' and not (current_val > related_val):
                        # 强制满足关系
                        constrained[param_name] = related_val * 1.1  # 增加10%缓冲
                    elif op == '<' and not (current_val < related_val):
                        constrained[param_name] = related_val * 0.9
        
        return constrained
    
    def get_status_summary(self) -> Dict[str, any]:
        """获取生命周期状态摘要"""
        status_counts = {status: 0 for status in StrategyStatus}
        for s in self.strategies.values():
            status_counts[s.status] += 1
        
        return {
            'total_strategies': len(self.strategies),
            'status_distribution': {k.value: v for k, v in status_counts.items()},
            'transitions_count': self.transitions_count,
            'birth_count': self.birth_count,
            'death_count': self.death_count,
            'experimental_pool_size': status_counts[StrategyStatus.BIRTH] + 
                                     status_counts[StrategyStatus.TRIAL],
            'active_elites': len(self.get_elites_for_breeding(5)),
        }
    
    def register_status_callback(self, status: StrategyStatus, callback: Callable):
        """注册状态变化回调"""
        self.status_callbacks[status].append(callback)
    
    def _emit_status_change(self, strategy: StrategyGenome, 
                           old: StrategyStatus, 
                           new: StrategyStatus):
        """触发状态变化回调"""
        for callback in self.status_callbacks.get(new, []):
            try:
                callback(strategy, old, new)
            except Exception as e:
                print(f"[Lifecycle] Callback error: {e}")


# 便捷函数
def create_lifecycle_manager(
    experimental_allocation: float = 0.05,
    trial_sharpe_threshold: float = 1.0
) -> StrategyLifecycleManager:
    """创建生命周期管理器"""
    config = LifecycleConfig(
        max_experimental_allocation=experimental_allocation,
        active_sharpe_threshold=trial_sharpe_threshold
    )
    return StrategyLifecycleManager(config)
