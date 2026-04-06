"""
strategy_genome.py - Strategy Genome Management for Evolution Engine

P10 Hedge Fund OS - Phase 5 Evolution Engine

This module defines the StrategyGenome dataclass and related types for managing
strategy DNA - the evolvable parameter set that defines a trading strategy's
behavior and configuration.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum, auto
from datetime import datetime
import numpy as np
import json
import uuid


class StrategyStatus(Enum):
    """策略生命周期状态"""
    BIRTH = "birth"           # 新生 - 刚创建，待回测验证
    TRIAL = "trial"           # 试用期 - 小资金实盘测试
    ACTIVE = "active"         # 活跃期 - 正常交易
    DECLINE = "decline"       # 衰退期 - 表现下降，降低权重
    DEAD = "dead"             # 死亡 - 被淘汰


class BirthReason(Enum):
    """策略生成原因"""
    MUTATION = "mutation"         # 变异生成
    CROSSOVER = "crossover"       # 交叉生成
    MANUAL = "manual"             # 手动创建
    IMMIGRATION = "immigration"   # 外部导入
    ELITE_CLONE = "elite_clone"   # 精英克隆


@dataclass
class PerformanceRecord:
    """策略表现记录"""
    timestamp: datetime
    period: str  # daily/weekly/monthly

    # 收益指标
    total_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0

    # 风险指标
    max_drawdown: float = 0.0
    volatility: float = 0.0
    var_95: float = 0.0

    # 交易指标
    trade_count: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_trade_pnl: float = 0.0

    # 执行质量
    fill_quality: float = 0.0
    adverse_selection: float = 0.0
    slippage: float = 0.0

    # 综合评分
    fitness_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'period': self.period,
            'total_return': self.total_return,
            'sharpe_ratio': self.sharpe_ratio,
            'sortino_ratio': self.sortino_ratio,
            'max_drawdown': self.max_drawdown,
            'volatility': self.volatility,
            'var_95': self.var_95,
            'trade_count': self.trade_count,
            'win_rate': self.win_rate,
            'profit_factor': self.profit_factor,
            'avg_trade_pnl': self.avg_trade_pnl,
            'fill_quality': self.fill_quality,
            'adverse_selection': self.adverse_selection,
            'slippage': self.slippage,
            'fitness_score': self.fitness_score
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'PerformanceRecord':
        """从字典创建"""
        return PerformanceRecord(
            timestamp=datetime.fromisoformat(data['timestamp']),
            period=data['period'],
            total_return=data.get('total_return', 0.0),
            sharpe_ratio=data.get('sharpe_ratio', 0.0),
            sortino_ratio=data.get('sortino_ratio', 0.0),
            max_drawdown=data.get('max_drawdown', 0.0),
            volatility=data.get('volatility', 0.0),
            var_95=data.get('var_95', 0.0),
            trade_count=data.get('trade_count', 0),
            win_rate=data.get('win_rate', 0.0),
            profit_factor=data.get('profit_factor', 0.0),
            avg_trade_pnl=data.get('avg_trade_pnl', 0.0),
            fill_quality=data.get('fill_quality', 0.0),
            adverse_selection=data.get('adverse_selection', 0.0),
            slippage=data.get('slippage', 0.0),
            fitness_score=data.get('fitness_score', 0.0)
        )


@dataclass
class StrategyGenome:
    """
    策略DNA - 可进化的参数集合

    这是进化引擎的核心数据结构，包含策略的所有可进化参数、
    表现历史和元数据。
    """
    # 标识
    id: str
    name: str
    version: str = "1.0.0"
    parent_ids: List[str] = field(default_factory=list)  # 父策略ID

    # 策略类型和分类
    strategy_type: str = "unknown"  # e.g., "trend", "mean_rev", "momentum"
    strategy_class: str = "unknown"  # 具体策略类名

    # 基因 - 可进化参数
    parameters: Dict[str, float] = field(default_factory=dict)  # 策略参数
    hyperparameters: Dict[str, float] = field(default_factory=dict)  # 超参数

    # 表现历史
    performance_history: List[PerformanceRecord] = field(default_factory=list)

    # 元数据
    created_at: datetime = field(default_factory=datetime.now)
    birth_reason: str = "manual"  # mutation/crossover/manual/immigration/elite_clone

    # 状态
    status: StrategyStatus = StrategyStatus.BIRTH
    generation: int = 0  # 进化代数

    # 生命周期管理
    trial_start_time: Optional[datetime] = None
    active_start_time: Optional[datetime] = None
    decline_start_time: Optional[datetime] = None
    death_time: Optional[datetime] = None

    # 权重和分配
    capital_weight: float = 0.0  # 资金分配权重
    confidence_score: float = 0.0  # 置信度评分

    # 统计
    total_trades: int = 0
    total_pnl: float = 0.0
    current_drawdown: float = 0.0

    def __post_init__(self):
        """初始化后处理"""
        if not self.id:
            self.id = str(uuid.uuid4())[:8]

    def calculate_fitness(self, window: int = None) -> float:
        """
        计算策略适应度分数

        综合考虑夏普比率、最大回撤、胜率等因素
        """
        if not self.performance_history:
            return 0.0

        records = self.performance_history
        if window and window < len(records):
            records = records[-window:]

        if not records:
            return 0.0

        # 计算平均指标
        avg_sharpe = np.mean([r.sharpe_ratio for r in records])
        avg_return = np.mean([r.total_return for r in records])
        avg_drawdown = np.mean([r.max_drawdown for r in records])
        avg_win_rate = np.mean([r.win_rate for r in records])

        # 综合适应度公式
        # 夏普比率权重最高，其次是收益，回撤惩罚，胜率加成
        fitness = (
            avg_sharpe * 0.4 +  # 夏普比率 40%
            avg_return * 0.3 +  # 收益 30%
            (1 + avg_drawdown) * 0.2 +  # 回撤惩罚 20% (drawdown为负值)
            avg_win_rate * 0.1  # 胜率 10%
        )

        return fitness

    def get_latest_performance(self) -> Optional[PerformanceRecord]:
        """获取最新表现记录"""
        if not self.performance_history:
            return None
        return self.performance_history[-1]

    def get_mean_performance(self, window: int = 10) -> Dict[str, float]:
        """获取平均表现指标"""
        if not self.performance_history:
            return {}

        records = self.performance_history[-window:]
        if not records:
            return {}

        return {
            'sharpe_ratio': np.mean([r.sharpe_ratio for r in records]),
            'total_return': np.mean([r.total_return for r in records]),
            'max_drawdown': np.mean([r.max_drawdown for r in records]),
            'win_rate': np.mean([r.win_rate for r in records]),
            'trade_count': sum([r.trade_count for r in records]),
            'fitness_score': np.mean([r.fitness_score for r in records])
        }

    def add_performance_record(self, record: PerformanceRecord):
        """添加表现记录"""
        self.performance_history.append(record)
        self.total_trades += record.trade_count
        self.total_pnl += record.total_return

        # 更新当前回撤
        if record.max_drawdown < self.current_drawdown:
            self.current_drawdown = record.max_drawdown

    def transition_status(self, new_status: StrategyStatus):
        """转换策略状态"""
        old_status = self.status
        self.status = new_status

        # 记录状态转换时间
        now = datetime.now()
        if new_status == StrategyStatus.TRIAL:
            self.trial_start_time = now
        elif new_status == StrategyStatus.ACTIVE:
            self.active_start_time = now
        elif new_status == StrategyStatus.DECLINE:
            self.decline_start_time = now
        elif new_status == StrategyStatus.DEAD:
            self.death_time = now

        return old_status

    def is_eligible_for_promotion(self) -> bool:
        """检查是否有资格从试用转为活跃"""
        if self.status != StrategyStatus.TRIAL:
            return False

        # 需要至少3条表现记录
        if len(self.performance_history) < 3:
            return False

        # 最近表现必须达标
        recent = self.get_mean_performance(window=3)
        if not recent:
            return False

        # 夏普比率 > 0.5, 最大回撤 < -5%
        return (
            recent.get('sharpe_ratio', 0) > 0.5 and
            recent.get('max_drawdown', -1) > -0.05
        )

    def should_be_eliminated(self) -> bool:
        """检查是否应该被淘汰"""
        # 死亡状态直接返回
        if self.status == StrategyStatus.DEAD:
            return True

        # 衰退期超过7天，淘汰
        if self.status == StrategyStatus.DECLINE and self.decline_start_time:
            days_in_decline = (datetime.now() - self.decline_start_time).days
            if days_in_decline >= 7:
                return True

        # 连续亏损超过阈值
        if len(self.performance_history) >= 5:
            recent_returns = [r.total_return for r in self.performance_history[-5:]]
            if all(r < 0 for r in recent_returns):
                return True

        # 最大回撤超过15%
        if self.current_drawdown < -0.15:
            return True

        # 夏普比率持续为负
        if len(self.performance_history) >= 10:
            recent_sharpes = [r.sharpe_ratio for r in self.performance_history[-10:]]
            if all(s < 0 for s in recent_sharpes):
                return True

        return False

    def clone(self, new_name: str = None) -> 'StrategyGenome':
        """克隆当前基因组"""
        import copy
        new_genome = StrategyGenome(
            id=str(uuid.uuid4())[:8],
            name=new_name or f"{self.name}_clone",
            version=self.version,
            parent_ids=[self.id],
            strategy_type=self.strategy_type,
            strategy_class=self.strategy_class,
            parameters=copy.deepcopy(self.parameters),
            hyperparameters=copy.deepcopy(self.hyperparameters),
            birth_reason="elite_clone",
            generation=self.generation + 1
        )
        return new_genome

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'version': self.version,
            'parent_ids': self.parent_ids,
            'strategy_type': self.strategy_type,
            'strategy_class': self.strategy_class,
            'parameters': self.parameters,
            'hyperparameters': self.hyperparameters,
            'performance_history': [r.to_dict() for r in self.performance_history],
            'created_at': self.created_at.isoformat(),
            'birth_reason': self.birth_reason,
            'status': self.status.value,
            'generation': self.generation,
            'trial_start_time': self.trial_start_time.isoformat() if self.trial_start_time else None,
            'active_start_time': self.active_start_time.isoformat() if self.active_start_time else None,
            'decline_start_time': self.decline_start_time.isoformat() if self.decline_start_time else None,
            'death_time': self.death_time.isoformat() if self.death_time else None,
            'capital_weight': self.capital_weight,
            'confidence_score': self.confidence_score,
            'total_trades': self.total_trades,
            'total_pnl': self.total_pnl,
            'current_drawdown': self.current_drawdown
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'StrategyGenome':
        """从字典创建"""
        genome = StrategyGenome(
            id=data['id'],
            name=data['name'],
            version=data['version'],
            parent_ids=data.get('parent_ids', []),
            strategy_type=data.get('strategy_type', 'unknown'),
            strategy_class=data.get('strategy_class', 'unknown'),
            parameters=data.get('parameters', {}),
            hyperparameters=data.get('hyperparameters', {}),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.now(),
            birth_reason=data.get('birth_reason', 'manual'),
            status=StrategyStatus(data.get('status', 'birth')),
            generation=data.get('generation', 0),
            capital_weight=data.get('capital_weight', 0.0),
            confidence_score=data.get('confidence_score', 0.0),
            total_trades=data.get('total_trades', 0),
            total_pnl=data.get('total_pnl', 0.0),
            current_drawdown=data.get('current_drawdown', 0.0)
        )

        # 恢复表现历史
        for record_data in data.get('performance_history', []):
            genome.performance_history.append(PerformanceRecord.from_dict(record_data))

        # 恢复时间戳
        if data.get('trial_start_time'):
            genome.trial_start_time = datetime.fromisoformat(data['trial_start_time'])
        if data.get('active_start_time'):
            genome.active_start_time = datetime.fromisoformat(data['active_start_time'])
        if data.get('decline_start_time'):
            genome.decline_start_time = datetime.fromisoformat(data['decline_start_time'])
        if data.get('death_time'):
            genome.death_time = datetime.fromisoformat(data['death_time'])

        return genome


class GenomeDatabase:
    """策略基因组数据库"""

    def __init__(self):
        self.genomes: Dict[str, StrategyGenome] = {}
        self._index_by_status: Dict[StrategyStatus, List[str]] = {
            status: [] for status in StrategyStatus
        }
        self._index_by_type: Dict[str, List[str]] = {}

    def add(self, genome: StrategyGenome):
        """添加基因组"""
        self.genomes[genome.id] = genome
        self._update_index(genome)

    def get(self, genome_id: str) -> Optional[StrategyGenome]:
        """获取基因组"""
        return self.genomes.get(genome_id)

    def remove(self, genome_id: str) -> bool:
        """移除基因组"""
        if genome_id in self.genomes:
            genome = self.genomes[genome_id]
            del self.genomes[genome_id]
            self._remove_from_index(genome)
            return True
        return False

    def get_by_status(self, status: StrategyStatus) -> List[StrategyGenome]:
        """按状态获取基因组"""
        ids = self._index_by_status.get(status, [])
        return [self.genomes[gid] for gid in ids if gid in self.genomes]

    def get_by_type(self, strategy_type: str) -> List[StrategyGenome]:
        """按类型获取基因组"""
        ids = self._index_by_type.get(strategy_type, [])
        return [self.genomes[gid] for gid in ids if gid in self.genomes]

    def get_all_active(self) -> List[StrategyGenome]:
        """获取所有活跃策略"""
        return self.get_by_status(StrategyStatus.ACTIVE)

    def get_all_alive(self) -> List[StrategyGenome]:
        """获取所有存活策略（非死亡）"""
        return [
            g for g in self.genomes.values()
            if g.status != StrategyStatus.DEAD
        ]

    def get_elite(self, n: int = 5) -> List[StrategyGenome]:
        """获取表现最好的n个策略"""
        alive = self.get_all_alive()
        sorted_genomes = sorted(
            alive,
            key=lambda g: g.calculate_fitness(),
            reverse=True
        )
        return sorted_genomes[:n]

    def _update_index(self, genome: StrategyGenome):
        """更新索引"""
        # 状态索引
        for status_list in self._index_by_status.values():
            if genome.id in status_list:
                status_list.remove(genome.id)
        self._index_by_status[genome.status].append(genome.id)

        # 类型索引
        if genome.strategy_type not in self._index_by_type:
            self._index_by_type[genome.strategy_type] = []
        if genome.id not in self._index_by_type[genome.strategy_type]:
            self._index_by_type[genome.strategy_type].append(genome.id)

    def _remove_from_index(self, genome: StrategyGenome):
        """从索引中移除"""
        for status_list in self._index_by_status.values():
            if genome.id in status_list:
                status_list.remove(genome.id)

        for type_list in self._index_by_type.values():
            if genome.id in type_list:
                type_list.remove(genome.id)

    def update_status(self, genome_id: str, new_status: StrategyStatus):
        """更新策略状态并维护索引"""
        genome = self.genomes.get(genome_id)
        if genome:
            old_status = genome.status
            genome.transition_status(new_status)

            # 更新索引
            if genome.id in self._index_by_status.get(old_status, []):
                self._index_by_status[old_status].remove(genome.id)
            self._index_by_status[new_status].append(genome.id)

    def get_stats(self) -> Dict[str, Any]:
        """获取数据库统计"""
        return {
            'total_genomes': len(self.genomes),
            'by_status': {
                status.value: len(ids)
                for status, ids in self._index_by_status.items()
            },
            'by_type': {
                stype: len(ids)
                for stype, ids in self._index_by_type.items()
            },
            'elite_count': len(self.get_elite())
        }

    def export_all(self) -> Dict[str, Any]:
        """导出所有数据"""
        return {
            'genomes': {
                gid: genome.to_dict()
                for gid, genome in self.genomes.items()
            },
            'stats': self.get_stats(),
            'export_time': datetime.now().isoformat()
        }

    def import_all(self, data: Dict[str, Any]):
        """导入数据"""
        self.genomes = {}
        self._index_by_status = {status: [] for status in StrategyStatus}
        self._index_by_type = {}

        for gid, genome_data in data.get('genomes', {}).items():
            genome = StrategyGenome.from_dict(genome_data)
            self.add(genome)
