#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RL Multi-Strategy Allocator

Dynamically allocates capital across multiple strategies based on:
1. Market regime (bull/bear/neutral/volatile)
2. Recent strategy performance (win rate, Sharpe, drawdown)
3. Q-learning state-action values

Strategies:
    - DualMA: Trend following with MA crossover
    - RSI: Mean reversion with RSI oversold/overbought
    - ML_LGBM: LightGBM probability-based signals
    - RegimeAware: Adaptive thresholds based on market state
    - OB_Micro: Order book microstructure signals

State space: 108 states (4 regimes × 3 volatility × 3 trend_strength × 3 ob_bias)
Action space: 5 strategies, each with weight [0.0, 0.25, 0.5, 0.75, 1.0]
"""

import json
import logging
import numpy as np
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import deque
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class StrategyPerformance:
    """Track performance metrics for a single strategy."""
    name: str
    trades: deque = field(default_factory=lambda: deque(maxlen=50))
    pnl_history: deque = field(default_factory=lambda: deque(maxlen=50))

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.5
        return sum(1 for t in self.trades if t > 0) / len(self.trades)

    @property
    def avg_pnl(self) -> float:
        if not self.pnl_history:
            return 0.0
        return np.mean(self.pnl_history)

    @property
    def sharpe(self) -> float:
        if len(self.pnl_history) < 5:
            return 0.0
        returns = list(self.pnl_history)
        if np.std(returns) == 0:
            return 0.0
        return np.mean(returns) / (np.std(returns) + 1e-9) * np.sqrt(252)

    def update(self, pnl: float):
        self.trades.append(1 if pnl > 0 else -1)
        self.pnl_history.append(pnl)


class RLStrategyAllocator:
    """
    Q-learning based strategy allocator.

    State: regime (4) × vol_level (3) × trend_strength (3) × ob_bias (3) = 108
    Actions: Each strategy gets a weight level [0.0, 0.25, 0.5, 0.75, 1.0]
    """

    WEIGHT_LEVELS = [0.0, 0.25, 0.5, 0.75, 1.0]

    def __init__(self, strategies: List[str] = None, state_file: str = 'rl_strategy_qtable.json', learning_rate: float = 0.1):
        self.STRATEGIES = strategies or ['DualMA', 'RSI', 'OB_Micro']
        self.state_file = Path(state_file)
        self.lr = learning_rate
        self.gamma = 0.95
        self.epsilon = 0.15

        # Q-table: state -> {strategy_idx: [q_values for each weight level]}
        self.q_table: Dict[str, List[List[float]]] = {}

        # Strategy performance trackers
        self.performance: Dict[str, StrategyPerformance] = {
            name: StrategyPerformance(name) for name in self.STRATEGIES
        }

        # Current weights
        n = len(self.STRATEGIES)
        self.current_weights: Dict[str, float] = {name: 1.0/n for name in self.STRATEGIES}

        self._load()

    def _encode_state(self, regime: str, vol_level: int, trend_strength: int, ob_bias: int) -> str:
        """
        Encode market state.

        regime: 'bull'|'bear'|'neutral'|'volatile'
        vol_level: 0=low, 1=medium, 2=high
        trend_strength: 0=weak, 1=moderate, 2=strong
        ob_bias: 0=sell, 1=neutral, 2=buy
        """
        regime_map = {'bull': 0, 'bear': 1, 'neutral': 2, 'volatile': 3}
        r = regime_map.get(regime, 2)
        return f"{r}_{vol_level}_{trend_strength}_{ob_bias}"

    def _get_q_state(self, state_key: str) -> List[List[float]]:
        """Get or initialize Q-values for a state."""
        if state_key not in self.q_table:
            # Initialize: 5 strategies × 5 weight levels
            self.q_table[state_key] = [[0.0] * len(self.WEIGHT_LEVELS) for _ in self.STRATEGIES]
        return self.q_table[state_key]

    def select_weights(self, regime: str, vol_level: int, trend_strength: int, ob_bias: int,
                       performance_hints: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        """
        Select strategy weights for current market state.

        Returns: {strategy_name: weight}
        """
        state_key = self._encode_state(regime, vol_level, trend_strength, ob_bias)
        q_values = self._get_q_state(state_key)

        weights = {}

        for i, strategy in enumerate(self.STRATEGIES):
            if np.random.random() < self.epsilon:
                # Exploration: random weight level
                level_idx = np.random.randint(len(self.WEIGHT_LEVELS))
            else:
                # Exploitation: best Q-value
                level_idx = int(np.argmax(q_values[i]))

            # Adjust by recent performance if available
            base_weight = self.WEIGHT_LEVELS[level_idx]
            if performance_hints and strategy in performance_hints:
                perf_adj = performance_hints[strategy]
                weights[strategy] = np.clip(base_weight * (1 + perf_adj), 0.0, 1.0)
            else:
                weights[strategy] = base_weight

        # Filter to only include valid strategies
        weights = {k: v for k, v in weights.items() if k in self.STRATEGIES}

        # Normalize to sum to 1.0
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}
        else:
            n = len(self.STRATEGIES)
            weights = {k: 1.0/n for k in self.STRATEGIES}  # Equal weight fallback

        self.current_weights = weights
        self._last_state = state_key
        self._last_q_values = [qv[:] for qv in q_values]  # Copy

        logger.info(f"[RL_ALLOC] state={state_key} weights={weights}")
        return weights

    def update(self, strategy_pnls: Dict[str, float], portfolio_pnl: float):
        """
        Update Q-table after observing strategy performance.

        Args:
            strategy_pnls: {strategy_name: pnl} for each strategy
            portfolio_pnl: Actual portfolio PnL with current weights
        """
        if not hasattr(self, '_last_state'):
            return

        state_key = self._last_state
        q_values = self._get_q_state(state_key)

        # Update each strategy's Q-values
        for i, strategy in enumerate(self.current_weights.keys()):
            if strategy not in strategy_pnls:
                continue

            pnl = strategy_pnls[strategy]
            self.performance[strategy].update(pnl)

            # Find which weight level was used
            used_weight = self.current_weights.get(strategy, 0.2)
            level_idx = min(range(len(self.WEIGHT_LEVELS)),
                           key=lambda j: abs(self.WEIGHT_LEVELS[j] - used_weight))

            # Calculate reward (Sharpe-adjusted PnL)
            sharpe = self.performance[strategy].sharpe
            reward = pnl * 10 + sharpe * 0.5

            # Q-learning update
            old_q = q_values[i][level_idx]
            # Use portfolio PnL as baseline advantage
            advantage = reward - portfolio_pnl * 10
            q_values[i][level_idx] = old_q + self.lr * (advantage + self.gamma * 0 - old_q)

        self._save()

        logger.info(f"[RL_UPDATE] portfolio_pnl={portfolio_pnl:.4f} "
                   f"strategy_pnls={strategy_pnls}")

    def get_best_strategy_for_state(self, regime: str, vol_level: int,
                                     trend_strength: int, ob_bias: int) -> str:
        """Return the single best strategy for given state."""
        weights = self.select_weights(regime, vol_level, trend_strength, ob_bias)
        return max(weights, key=weights.get)

    def get_stats(self) -> Dict:
        """Return allocator statistics."""
        return {
            'states_learned': len(self.q_table),
            'current_weights': self.current_weights,
            'strategy_performance': {
                name: {
                    'win_rate': perf.win_rate,
                    'avg_pnl': perf.avg_pnl,
                    'sharpe': perf.sharpe,
                    'trades': len(perf.trades)
                }
                for name, perf in self.performance.items()
            }
        }

    def _load(self):
        """Load Q-table from disk."""
        if self.state_file.exists():
            with open(self.state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.q_table = {k: [list(map(float, row)) for row in v]
                               for k, v in data.get('q_table', {}).items()}
                # Load performance
                for name, perf_data in data.get('performance', {}).items():
                    if name in self.performance:
                        self.performance[name].pnl_history = deque(
                            perf_data.get('pnl_history', []), maxlen=50
                        )
                        self.performance[name].trades = deque(
                            perf_data.get('trades', []), maxlen=50
                        )
            logger.info(f"[RL_ALLOC] Loaded {len(self.q_table)} states")

    def _save(self):
        """Save Q-table to disk."""
        data = {
            'q_table': self.q_table,
            'performance': {
                name: {
                    'pnl_history': list(perf.pnl_history),
                    'trades': list(perf.trades)
                }
                for name, perf in self.performance.items()
            },
            'last_update': datetime.now().isoformat()
        }
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)


class FuzzyStrategySelector:
    """
    Fuzzy logic strategy selector using AI model consensus.

    Combines RL allocation with AI model votes for final decision.
    """

    def __init__(self, rl_allocator: RLStrategyAllocator):
        self.rl = rl_allocator
        self.ai_confidence_threshold = 0.6

    def select(self,
               regime: str,
               vol_level: int,
               trend_strength: int,
               ob_bias: int,
               ai_direction: str,      # 'up'|'down'|'sideways'
               ai_confidence: float,    # 0.0-1.0
               ai_regime: str          # AI-predicted regime
               ) -> Tuple[str, Dict[str, float], float]:
        """
        Returns: (primary_strategy, all_weights, final_confidence)
        """
        # Get RL weights
        rl_weights = self.rl.select_weights(regime, vol_level, trend_strength, ob_bias)

        # AI override: if AI is very confident and disagrees with regime
        final_confidence = 0.5

        if ai_confidence > self.ai_confidence_threshold:
            # Boost strategies aligned with AI direction
            # Dynamic boost based on available strategies
            available = list(rl_weights.keys())

            if ai_direction == 'up':
                # Boost trend-following strategies
                trend_strategies = [s for s in available if 'MA' in s or 'Trend' in s]
                boost_targets = trend_strategies if trend_strategies else available[:1]
            elif ai_direction == 'down':
                # Boost mean-reversion strategies
                rev_strategies = [s for s in available if 'RSI' in s or 'Rev' in s]
                boost_targets = rev_strategies if rev_strategies else available[:1]
            else:
                # Neutral - boost OB or ML strategies
                neutral_strategies = [s for s in available if 'OB' in s or 'ML' in s]
                boost_targets = neutral_strategies if neutral_strategies else available[:1]

            for strategy in boost_targets:
                if strategy in rl_weights:
                    rl_weights[strategy] += 0.2 * ai_confidence

            # Renormalize
            total = sum(rl_weights.values())
            if total > 0:
                rl_weights = {k: v / total for k, v in rl_weights.items()}

            final_confidence = ai_confidence * 0.7 + 0.3

        primary = max(rl_weights, key=rl_weights.get)

        return primary, rl_weights, final_confidence


# Simple test
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    # Test RL allocator
    allocator = RLStrategyAllocator()

    # Simulate some states
    for _ in range(5):
        weights = allocator.select_weights(
            regime='bull',
            vol_level=1,
            trend_strength=2,
            ob_bias=2
        )
        print(f"Weights: {weights}")

        # Simulate performance
        allocator.update(
            strategy_pnls={
                'DualMA': 0.02,
                'RSI': -0.01,
                'ML_LGBM': 0.015,
                'RegimeAware': 0.025,
                'OB_Micro': 0.01
            },
            portfolio_pnl=0.018
        )

    print(f"\nStats: {allocator.get_stats()}")
