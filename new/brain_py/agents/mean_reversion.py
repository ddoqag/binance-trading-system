"""
mean_reversion.py - Mean Reversion Expert Agent
"""

import numpy as np
from .base_expert import BaseExpert, ExpertConfig, Action, ActionType, MarketRegime


class MeanReversionConfig(ExpertConfig):
    """Configuration for mean reversion expert."""
    name: str = "mean_reversion"
    min_confidence: float = 0.4
    max_position_size: float = 0.8
    deviation_threshold: float = 0.001
    queue_imbalance_threshold: float = 0.3
    max_deviation: float = 0.005
    min_spread: float = 0.0001


class MeanReversionExpert(BaseExpert):
    """Expert agent for range-bound markets."""

    def __init__(self, config=None):
        cfg = config or MeanReversionConfig()
        super().__init__(cfg)
        self.config = cfg
        self._price_history = []
        self._max_history = 100

    def act(self, observation):
        """Generate mean-reversion action."""
        obs = self._validate_observation(observation)

        best_bid = obs[0]
        best_ask = obs[1]
        micro_price = obs[2]
        spread = obs[7] if len(obs) > 7 else 0.0

        mid_price = (best_bid + best_ask) / 2.0

        self._price_history.append(mid_price)
        if len(self._price_history) > self._max_history:
            self._price_history.pop(0)

        deviation = self._calculate_deviation(micro_price, mid_price)

        if spread < self.config.min_spread:
            return Action(ActionType.HOLD, 0.0, 0.0,
                         {'reason': 'spread_too_small'})

        if abs(deviation) > self.config.max_deviation:
            return Action(ActionType.HOLD, 0.0, 0.2,
                         {'reason': 'deviation_too_large'})

        if deviation <= -self.config.deviation_threshold:
            position_size = min(abs(deviation) / self.config.deviation_threshold * 0.5,
                               self.config.max_position_size)
            confidence = self.get_confidence(observation)
            return Action(ActionType.BUY, position_size, confidence,
                         {'deviation': deviation, 'expert_type': 'mean_reversion'})
        elif deviation >= self.config.deviation_threshold:
            position_size = -min(abs(deviation) / self.config.deviation_threshold * 0.5,
                                self.config.max_position_size)
            confidence = self.get_confidence(observation)
            return Action(ActionType.SELL, position_size, confidence,
                         {'deviation': deviation, 'expert_type': 'mean_reversion'})
        else:
            return Action(ActionType.HOLD, 0.0, 0.3,
                         {'deviation': deviation, 'expert_type': 'mean_reversion'})

    def get_confidence(self, observation):
        """Calculate confidence in mean-reversion signal."""
        obs = self._validate_observation(observation)

        best_bid = obs[0]
        best_ask = obs[1]
        micro_price = obs[2]
        bid_queue = obs[5] if len(obs) > 5 else 0.5
        ask_queue = obs[6] if len(obs) > 6 else 0.5

        mid_price = (best_bid + best_ask) / 2.0
        deviation = (micro_price - mid_price) / mid_price if mid_price > 0 else 0

        dev_ratio = abs(deviation) / self.config.deviation_threshold
        if dev_ratio < 1.0:
            dev_score = dev_ratio * 0.5
        elif dev_ratio <= 3.0:
            dev_score = 1.0 - (dev_ratio - 1.0) * 0.25
        else:
            dev_score = 0.25

        queue_imbalance = bid_queue - ask_queue
        if deviation < 0:
            queue_confirmation = 1.0 if queue_imbalance > 0 else 0.3
        elif deviation > 0:
            queue_confirmation = 1.0 if queue_imbalance < 0 else 0.3
        else:
            queue_confirmation = 0.5

        hist_score = self._check_historical_mean_reversion()
        confidence = 0.5 * dev_score + 0.3 * queue_confirmation + 0.2 * hist_score
        return min(max(confidence, 0.0), 1.0)

    def get_expertise(self):
        """Get list of market regimes this expert specializes in."""
        return [MarketRegime.RANGE]

    def _calculate_deviation(self, micro_price, mid_price):
        """Calculate normalized price deviation from mid."""
        if mid_price <= 0:
            return 0.0
        return (micro_price - mid_price) / mid_price

    def _check_historical_mean_reversion(self):
        """Check if price history exhibits mean-reverting behavior."""
        if len(self._price_history) < 20:
            return 0.5

        prices = np.array(self._price_history)
        lags = range(2, min(20, len(prices) // 2))
        tau = [np.std(np.subtract(prices[lag:], prices[:-lag])) for lag in lags]

        if len(tau) < 2 or tau[0] == 0:
            return 0.5

        log_lags = np.log(list(lags))
        log_tau = np.log(tau)
        slope = np.polyfit(log_lags, log_tau, 1)[0]
        hurst = slope / 2.0

        if hurst < 0.5:
            return 1.0 - hurst
        else:
            return max(0.0, 0.5 - (hurst - 0.5))

    def reset_history(self):
        """Reset price history."""
        self._price_history = []
