"""
Strategy Pool - 策略池管理
统一管理多个交易策略，支持动态注册、权重分配和性能追踪
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any, Type
from datetime import datetime, timedelta
from collections import deque
import logging
from enum import Enum

logger = logging.getLogger('StrategyPool')


class StrategyStatus(Enum):
    """策略状态"""
    ACTIVE = "active"           # 正常运行
    PAUSED = "paused"           # 暂停
    BACKTESTING = "backtesting" # 回测中
    DEPRECATED = "deprecated"   # 废弃
    ERROR = "error"             # 出错


class StrategyType(Enum):
    """策略类型"""
    TREND_FOLLOWING = "trend_following"     # 趋势跟踪
    MEAN_REVERSION = "mean_reversion"       # 均值回归
    MOMENTUM = "momentum"                   # 动量
    BREAKOUT = "breakout"                   # 突破
    ML_BASED = "ml_based"                   # 机器学习
    STATISTICAL_ARB = "statistical_arb"     # 统计套利
    HIGH_FREQUENCY = "high_frequency"       # 高频


@dataclass
class StrategyConfig:
    """策略配置"""
    name: str
    strategy_class: Type
    params: Dict[str, Any] = field(default_factory=dict)
    strategy_type: StrategyType = StrategyType.TREND_FOLLOWING
    default_weight: float = 0.2
    min_weight: float = 0.0
    max_weight: float = 1.0
    enabled: bool = True
    description: str = ""


@dataclass
class StrategyMetrics:
    """策略性能指标"""
    strategy_name: str
    # 收益指标
    total_return: float = 0.0           # 总收益率
    annualized_return: float = 0.0      # 年化收益率
    daily_returns: deque = field(default_factory=lambda: deque(maxlen=252))

    # 风险指标
    volatility: float = 0.0             # 波动率
    max_drawdown: float = 0.0           # 最大回撤
    var_95: float = 0.0                 # 95% VaR

    # 风险调整指标
    sharpe_ratio: float = 0.0           # 夏普比率
    sortino_ratio: float = 0.0          # 索提诺比率
    calmar_ratio: float = 0.0           # 卡尔玛比率

    # 交易统计
    total_trades: int = 0
    winning_trades: int = 0
    win_rate: float = 0.0
    avg_profit: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0

    # 时间戳
    last_updated: datetime = field(default_factory=datetime.now)
    created_at: datetime = field(default_factory=datetime.now)

    def update_from_trade(self, pnl: float, holding_period: int = 1):
        """从交易更新指标"""
        self.total_trades += 1
        if pnl > 0:
            self.winning_trades += 1
            self.avg_profit = (self.avg_profit * (self.winning_trades - 1) + pnl) / self.winning_trades
        else:
            avg_loss_count = self.total_trades - self.winning_trades
            if avg_loss_count > 0:
                self.avg_loss = (self.avg_loss * (avg_loss_count - 1) + pnl) / avg_loss_count

        self.win_rate = self.winning_trades / self.total_trades if self.total_trades > 0 else 0

        # 更新收益率
        daily_return = pnl / 10000  # 假设本金10000
        self.daily_returns.append(daily_return)

        self._recalculate_metrics()
        self.last_updated = datetime.now()

    def update_from_returns(self, returns: List[float]):
        """从收益率序列更新指标"""
        for r in returns:
            self.daily_returns.append(r)
        self._recalculate_metrics()
        self.last_updated = datetime.now()

    def _recalculate_metrics(self):
        """重新计算所有指标"""
        if len(self.daily_returns) < 2:
            return

        returns_array = np.array(self.daily_returns)

        # 基础统计
        self.total_return = np.prod(1 + returns_array) - 1
        self.annualized_return = (1 + self.total_return) ** (252 / len(returns_array)) - 1
        self.volatility = np.std(returns_array) * np.sqrt(252)

        # 最大回撤
        cumulative = np.cumprod(1 + returns_array)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - running_max) / running_max
        self.max_drawdown = np.min(drawdown)

        # VaR
        self.var_95 = np.percentile(returns_array, 5)

        # 风险调整指标
        if self.volatility > 0:
            self.sharpe_ratio = np.mean(returns_array) / np.std(returns_array) * np.sqrt(252)

        # 下行波动率 (索提诺)
        downside_returns = returns_array[returns_array < 0]
        if len(downside_returns) > 0:
            downside_std = np.std(downside_returns) * np.sqrt(252)
            self.sortino_ratio = np.mean(returns_array) / downside_std * np.sqrt(252) if downside_std > 0 else 0

        # 卡尔玛比率
        if self.max_drawdown < 0:
            self.calmar_ratio = self.annualized_return / abs(self.max_drawdown)

        # 盈亏比
        if self.avg_loss != 0:
            self.profit_factor = abs(self.avg_profit / self.avg_loss)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'strategy_name': self.strategy_name,
            'total_return': self.total_return,
            'annualized_return': self.annualized_return,
            'volatility': self.volatility,
            'max_drawdown': self.max_drawdown,
            'sharpe_ratio': self.sharpe_ratio,
            'sortino_ratio': self.sortino_ratio,
            'calmar_ratio': self.calmar_ratio,
            'total_trades': self.total_trades,
            'win_rate': self.win_rate,
            'profit_factor': self.profit_factor,
            'last_updated': self.last_updated.isoformat()
        }


@dataclass
class PoolAllocation:
    """策略池配置"""
    weights: Dict[str, float] = field(default_factory=dict)
    rebalancing_threshold: float = 0.1
    last_rebalanced: datetime = field(default_factory=datetime.now)
    rebalance_count: int = 0


class StrategyInstance:
    """策略实例包装器"""

    def __init__(self, config: StrategyConfig):
        self.config = config
        self.instance = None
        self.status = StrategyStatus.ACTIVE
        self.metrics = StrategyMetrics(config.name)
        self.current_weight = config.default_weight
        self.target_weight = config.default_weight
        self.signals_history = deque(maxlen=100)
        self.error_count = 0
        self.last_signal = None

        # 创建实例
        self._create_instance()

    def _create_instance(self):
        """创建策略实例"""
        try:
            self.instance = self.config.strategy_class(**self.config.params)
            logger.info(f"Strategy instance created: {self.config.name}")
        except Exception as e:
            logger.error(f"Failed to create strategy {self.config.name}: {e}")
            self.status = StrategyStatus.ERROR
            self.error_count += 1

    def generate_signal(self, data: pd.DataFrame) -> Optional[int]:
        """
        生成交易信号

        Returns:
            0=持有, 1=买入, -1=卖出
        """
        if self.status != StrategyStatus.ACTIVE or self.instance is None:
            return None

        try:
            # 假设策略有generate_signal方法
            if hasattr(self.instance, 'generate_signal'):
                signal = self.instance.generate_signal(data)
            elif hasattr(self.instance, 'generate_signals'):
                signal = self.instance.generate_signals(data)
            else:
                logger.warning(f"Strategy {self.config.name} has no signal method")
                return None

            self.last_signal = signal
            self.signals_history.append({
                'timestamp': datetime.now(),
                'signal': signal
            })

            return signal

        except Exception as e:
            logger.error(f"Error generating signal for {self.config.name}: {e}")
            self.error_count += 1
            if self.error_count > 5:
                self.status = StrategyStatus.ERROR
            return None

    def update_weight(self, new_weight: float):
        """更新权重"""
        self.target_weight = np.clip(new_weight, self.config.min_weight, self.config.max_weight)

    def apply_weight_change(self, max_change: float = 0.1) -> bool:
        """
        逐步应用权重变化

        Returns:
            是否达到目标权重
        """
        diff = self.target_weight - self.current_weight
        if abs(diff) < 0.001:
            return True

        change = np.clip(diff, -max_change, max_change)
        self.current_weight += change
        return abs(self.target_weight - self.current_weight) < 0.001

    def pause(self):
        """暂停策略"""
        self.status = StrategyStatus.PAUSED
        logger.info(f"Strategy {self.config.name} paused")

    def resume(self):
        """恢复策略"""
        if self.status == StrategyStatus.PAUSED:
            self.status = StrategyStatus.ACTIVE
            logger.info(f"Strategy {self.config.name} resumed")

    def reset_error(self):
        """重置错误计数"""
        self.error_count = 0
        if self.status == StrategyStatus.ERROR:
            self._create_instance()
            if self.instance is not None:
                self.status = StrategyStatus.ACTIVE


class StrategyPool:
    """
    策略池管理器

    统一管理多个交易策略，提供：
    - 策略注册/注销
    - 权重分配
    - 性能追踪
    - 动态调整
    """

    def __init__(self):
        self.strategies: Dict[str, StrategyInstance] = {}
        self.allocation = PoolAllocation()
        self.pool_metrics_history = deque(maxlen=1000)
        self.last_update = datetime.now()

        logger.info("StrategyPool initialized")

    def register_strategy(self, config: StrategyConfig) -> bool:
        """
        注册策略

        Args:
            config: 策略配置

        Returns:
            是否成功
        """
        if config.name in self.strategies:
            logger.warning(f"Strategy {config.name} already exists, updating...")
            self.unregister_strategy(config.name)

        try:
            instance = StrategyInstance(config)
            if instance.status == StrategyStatus.ERROR:
                logger.error(f"Failed to initialize strategy {config.name}")
                return False

            self.strategies[config.name] = instance

            # 初始化权重
            if not self.allocation.weights:
                # 第一个策略，权重为1
                self.allocation.weights[config.name] = 1.0
            else:
                # 均匀分配
                n = len(self.strategies)
                for name in self.allocation.weights:
                    self.allocation.weights[name] = 1.0 / n
                self.allocation.weights[config.name] = 1.0 / n

            logger.info(f"Strategy {config.name} registered successfully")
            return True

        except Exception as e:
            logger.error(f"Error registering strategy {config.name}: {e}")
            return False

    def unregister_strategy(self, name: str) -> bool:
        """
        注销策略

        Args:
            name: 策略名称

        Returns:
            是否成功
        """
        if name not in self.strategies:
            logger.warning(f"Strategy {name} not found")
            return False

        del self.strategies[name]
        if name in self.allocation.weights:
            del self.allocation.weights[name]

        # 重新归一化权重
        self._normalize_weights()

        logger.info(f"Strategy {name} unregistered")
        return True

    def _normalize_weights(self):
        """归一化权重"""
        total = sum(self.allocation.weights.values())
        if total > 0:
            for name in self.allocation.weights:
                self.allocation.weights[name] /= total

    def generate_signals(self, data: pd.DataFrame) -> Dict[str, Any]:
        """
        生成所有活跃策略的信号

        Args:
            data: 市场数据

        Returns:
            策略信号字典
        """
        signals = {}
        for name, strategy in self.strategies.items():
            if strategy.status == StrategyStatus.ACTIVE:
                signal = strategy.generate_signal(data)
                if signal is not None:
                    signals[name] = {
                        'signal': signal,
                        'weight': strategy.current_weight,
                        'type': strategy.config.strategy_type.value
                    }
        return signals

    def compute_consensus_signal(self, signals: Dict[str, Any]) -> Dict[str, Any]:
        """
        计算共识信号

        根据各策略的权重和信号，计算最终的共识信号

        Args:
            signals: 各策略信号

        Returns:
            共识信号结果
        """
        if not signals:
            return {'signal': 0, 'confidence': 0, 'consensus': 'neutral'}

        weighted_sum = 0.0
        total_weight = 0.0
        bullish_count = 0
        bearish_count = 0

        for name, sig_data in signals.items():
            signal = sig_data['signal']
            weight = sig_data['weight']

            # 标准化信号到 [-1, 1]
            if isinstance(signal, (int, float)):
                normalized_signal = np.clip(signal, -1, 1)
            else:
                # 假设信号是字符串
                normalized_signal = 1 if signal == 'buy' else (-1 if signal == 'sell' else 0)

            weighted_sum += normalized_signal * weight
            total_weight += weight

            if normalized_signal > 0:
                bullish_count += 1
            elif normalized_signal < 0:
                bearish_count += 1

        if total_weight == 0:
            return {'signal': 0, 'confidence': 0, 'consensus': 'neutral'}

        consensus = weighted_sum / total_weight

        # 置信度 (基于一致性)
        total_signals = len(signals)
        if total_signals > 0:
            agreement = max(bullish_count, bearish_count) / total_signals
            confidence = agreement * abs(consensus)
        else:
            confidence = 0

        # 判断共识方向
        if consensus > 0.3:
            consensus_label = 'strong_buy'
        elif consensus > 0.1:
            consensus_label = 'buy'
        elif consensus < -0.3:
            consensus_label = 'strong_sell'
        elif consensus < -0.1:
            consensus_label = 'sell'
        else:
            consensus_label = 'neutral'

        return {
            'signal': consensus,
            'confidence': confidence,
            'consensus': consensus_label,
            'signals_detail': signals,
            'bullish_count': bullish_count,
            'bearish_count': bearish_count
        }

    def update_weights(self, new_weights: Dict[str, float], gradual: bool = True):
        """
        更新策略权重

        Args:
            new_weights: 新权重
            gradual: 是否逐步调整
        """
        # 验证权重
        total = sum(new_weights.values())
        if abs(total - 1.0) > 0.01:
            logger.warning(f"Weights sum to {total}, normalizing...")
            new_weights = {k: v / total for k, v in new_weights.items()}

        # 应用权重
        for name, weight in new_weights.items():
            if name in self.strategies:
                self.strategies[name].update_weight(weight)

        if not gradual:
            for strategy in self.strategies.values():
                strategy.current_weight = strategy.target_weight

        self.allocation.weights = new_weights.copy()
        self.allocation.last_rebalanced = datetime.now()
        self.allocation.rebalance_count += 1

        logger.info(f"Weights updated: {new_weights}")

    def apply_weight_changes(self) -> bool:
        """
        应用权重变化（逐步调整）

        Returns:
            所有策略是否都达到目标权重
        """
        all_reached = True
        for strategy in self.strategies.values():
            reached = strategy.apply_weight_change()
            all_reached = all_reached and reached
        return all_reached

    def update_metrics(self, strategy_returns: Dict[str, float]):
        """
        更新策略性能指标

        Args:
            strategy_returns: 各策略的收益率
        """
        for name, ret in strategy_returns.items():
            if name in self.strategies:
                self.strategies[name].metrics.update_from_returns([ret])

        self.last_update = datetime.now()

    def get_active_strategies(self) -> Dict[str, StrategyInstance]:
        """获取活跃策略"""
        return {k: v for k, v in self.strategies.items() if v.status == StrategyStatus.ACTIVE}

    def get_strategy_metrics(self, name: Optional[str] = None) -> Dict[str, Any]:
        """
        获取策略性能指标

        Args:
            name: 策略名称，None则返回所有

        Returns:
            性能指标
        """
        if name:
            if name in self.strategies:
                return self.strategies[name].metrics.to_dict()
            return {}

        return {name: s.metrics.to_dict() for name, s in self.strategies.items()}

    def get_pool_summary(self) -> Dict[str, Any]:
        """获取策略池汇总信息"""
        active_count = len(self.get_active_strategies())
        total_count = len(self.strategies)

        # 计算池的整体指标
        all_returns = []
        for strategy in self.strategies.values():
            all_returns.extend(strategy.metrics.daily_returns)

        summary = {
            'total_strategies': total_count,
            'active_strategies': active_count,
            'paused_strategies': sum(1 for s in self.strategies.values() if s.status == StrategyStatus.PAUSED),
            'error_strategies': sum(1 for s in self.strategies.values() if s.status == StrategyStatus.ERROR),
            'current_weights': self.allocation.weights,
            'last_rebalanced': self.allocation.last_rebalanced.isoformat(),
            'rebalance_count': self.allocation.rebalance_count
        }

        if all_returns:
            returns_array = np.array(all_returns)
            summary['pool_avg_return'] = np.mean(returns_array)
            summary['pool_volatility'] = np.std(returns_array)
            summary['pool_sharpe'] = np.mean(returns_array) / (np.std(returns_array) + 1e-6) * np.sqrt(252)

        return summary

    def check_rebalance_needed(self, threshold: Optional[float] = None) -> bool:
        """
        检查是否需要再平衡

        Args:
            threshold: 权重变化阈值

        Returns:
            是否需要再平衡
        """
        threshold = threshold or self.allocation.rebalancing_threshold

        for name, strategy in self.strategies.items():
            target = strategy.target_weight
            current = strategy.current_weight
            if abs(target - current) > threshold:
                return True

        return False

    def pause_strategy(self, name: str) -> bool:
        """暂停策略"""
        if name in self.strategies:
            self.strategies[name].pause()
            return True
        return False

    def resume_strategy(self, name: str) -> bool:
        """恢复策略"""
        if name in self.strategies:
            self.strategies[name].resume()
            return True
        return False

    def reset_strategy_errors(self, name: str) -> bool:
        """重置策略错误"""
        if name in self.strategies:
            self.strategies[name].reset_error()
            return True
        return False

    def save_state(self, filepath: str):
        """保存状态"""
        import json

        state = {
            'allocation': {
                'weights': self.allocation.weights,
                'last_rebalanced': self.allocation.last_rebalanced.isoformat(),
                'rebalance_count': self.allocation.rebalance_count
            },
            'strategies': {
                name: {
                    'status': s.status.value,
                    'current_weight': s.current_weight,
                    'target_weight': s.target_weight,
                    'metrics': s.metrics.to_dict()
                }
                for name, s in self.strategies.items()
            }
        }

        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2)

        logger.info(f"StrategyPool state saved to {filepath}")

    def load_state(self, filepath: str):
        """加载状态"""
        import json

        with open(filepath, 'r') as f:
            state = json.load(f)

        # 恢复配置
        if 'allocation' in state:
            self.allocation.weights = state['allocation']['weights']
            self.allocation.rebalance_count = state['allocation'].get('rebalance_count', 0)

        # 恢复策略状态
        for name, s_state in state.get('strategies', {}).items():
            if name in self.strategies:
                strategy = self.strategies[name]
                strategy.current_weight = s_state['current_weight']
                strategy.target_weight = s_state['target_weight']
                # 注意：不恢复ERROR状态，尝试重新创建

        logger.info(f"StrategyPool state loaded from {filepath}")


def create_default_strategy_pool() -> StrategyPool:
    """创建默认策略池"""
    pool = StrategyPool()

    # 这里可以注册默认策略
    # 实际策略需要导入并配置

    return pool
