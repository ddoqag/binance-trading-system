"""
base_expert.py - Expert Agent Base Class
"""

from abc import ABC, abstractmethod
from typing import List, Tuple
from dataclasses import dataclass
from enum import IntEnum
import numpy as np


class MarketRegime(IntEnum):
    """Market regime enumeration."""
    UNKNOWN = 0
    TREND_UP = 1
    TREND_DOWN = 2
    RANGE = 3
    HIGH_VOL = 4
    LOW_VOL = 5


class ActionType(IntEnum):
    """Action type enumeration."""
    HOLD = 0
    BUY = 1
    SELL = 2


@dataclass
class Action:
    """Expert action output."""
    action_type: ActionType
    position_size: float
    confidence: float
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class ExpertConfig:
    """Configuration for expert agents."""
    name: str = "base_expert"
    min_confidence: float = 0.3
    max_position_size: float = 1.0
    lookback_window: int = 20
    feature_dim: int = 9


class BaseExpert(ABC):
    """Abstract base class for expert agents."""

    def __init__(self, config: ExpertConfig = None):
        self.config = config or ExpertConfig()
        self.name = self.config.name
        self._history = []
        self._performance_stats = {
            'calls': 0,
            'correct_predictions': 0,
            'total_pnl': 0.0,
        }

    @abstractmethod
    def act(self, observation):
        """Generate action from observation."""
        pass

    @abstractmethod
    def get_confidence(self, observation):
        """Calculate confidence score for current observation."""
        pass

    @abstractmethod
    def get_expertise(self):
        """Get list of market regimes this expert specializes in."""
        pass

    def is_expert_in(self, regime):
        """Check if expert specializes in given regime."""
        return regime in self.get_expertise()

    def update_performance(self, predicted_return, actual_return):
        """Update expert performance statistics."""
        self._performance_stats['calls'] += 1
        self._performance_stats['total_pnl'] += actual_return
        if predicted_return * actual_return > 0:
            self._performance_stats['correct_predictions'] += 1

    def get_accuracy(self):
        """Get prediction accuracy."""
        calls = self._performance_stats['calls']
        if calls == 0:
            return 0.5
        return self._performance_stats['correct_predictions'] / calls

    def get_average_pnl(self):
        """Get average PnL per call."""
        calls = self._performance_stats['calls']
        if calls == 0:
            return 0.0
        return self._performance_stats['total_pnl'] / calls

    def reset_stats(self):
        """Reset performance statistics."""
        self._performance_stats = {
            'calls': 0,
            'correct_predictions': 0,
            'total_pnl': 0.0,
        }

    def _validate_observation(self, observation):
        """Validate and normalize observation."""
        obs = np.asarray(observation, dtype=np.float32)
        obs = np.nan_to_num(obs, nan=0.0, posinf=1e6, neginf=-1e6)
        return obs

    def _compute_signal_strength(self, indicator, threshold=0.0):
        """Convert indicator value to signal strength."""
        abs_indicator = abs(indicator)
        if abs_indicator < threshold:
            return 0.0
        strength = abs_indicator / (1.0 + abs_indicator)
        return min(strength, 1.0)


class ExpertPool:
    """Pool of expert agents with regime-based selection."""

    def __init__(self):
        self._experts = {}
        self._regime_map = {}

    def register_expert(self, expert):
        """Register an expert in the pool."""
        self._experts[expert.name] = expert
        for regime in expert.get_expertise():
            if regime not in self._regime_map:
                self._regime_map[regime] = []
            self._regime_map[regime].append(expert.name)

    def unregister_expert(self, name):
        """Unregister an expert from the pool."""
        if name not in self._experts:
            return
        expert = self._experts[name]
        for regime in expert.get_expertise():
            if regime in self._regime_map and name in self._regime_map[regime]:
                self._regime_map[regime].remove(name)
        del self._experts[name]

    def get_experts_for_regime(self, regime):
        """Get all experts that handle a specific regime."""
        names = self._regime_map.get(regime, [])
        return [self._experts[name] for name in names if name in self._experts]

    def get_all_experts(self):
        """Get all registered experts."""
        return list(self._experts.values())

    def collect_actions(self, observation, regime):
        """Collect actions from all experts for a regime."""
        experts = self.get_experts_for_regime(regime)
        results = []
        for expert in experts:
            action = expert.act(observation)
            results.append((expert.name, action))
        return results

    def get_weighted_consensus(self, observation, regime, weights=None):
        """Get weighted consensus action from experts."""
        actions = self.collect_actions(observation, regime)
        if not actions:
            return Action(ActionType.HOLD, 0.0, 0.0)

        if weights is None:
            weights = {name: 1.0 / len(actions) for name, _ in actions}

        weighted_position = 0.0
        total_confidence = 0.0

        for name, action in actions:
            w = weights.get(name, 0.0)
            weighted_position += w * action.position_size * action.confidence
            total_confidence += w * action.confidence

        if total_confidence > 0:
            weighted_position /= total_confidence

        if weighted_position > 0.1:
            action_type = ActionType.BUY
        elif weighted_position < -0.1:
            action_type = ActionType.SELL
        else:
            action_type = ActionType.HOLD

        avg_confidence = np.mean([a.confidence for _, a in actions])
        return Action(action_type, weighted_position, avg_confidence)
