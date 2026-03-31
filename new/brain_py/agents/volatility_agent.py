"""
volatility_agent.py - Volatility Expert Agent
"""

import numpy as np
from .base_expert import BaseExpert, ExpertConfig, Action, ActionType, MarketRegime


class VolatilityConfig(ExpertConfig):
    """Configuration for volatility expert."""
    name: str = "volatility"
    min_confidence: float = 0.35
    max_position_size: float = 0.6
    high_vol_threshold: float = 0.02
    low_vol_threshold: float = 0.005
    vol_lookback: int = 20
    position_scale_factor: float = 0.5


class VolatilityExpert(BaseExpert):
    """Expert agent for volatility-based trading."""

    def __init__(self, config=None):
        cfg = config or VolatilityConfig()
        super().__init__(cfg)
        self.config = cfg
        self._volatility_history = []
        self._price_history = []
        self._max_history = 100

    def act(self, observation):
        """Generate volatility-adjusted action."""
        obs = self._validate_observation(observation)

        micro_price = obs[2]
        ofi = obs[3]
        trade_imb = obs[4]
        vol_estimate = obs[8] if len(obs) > 8 else None

        self._price_history.append(micro_price)
        if len(self._price_history) > self._max_history:
            self._price_history.pop(0)

        current_vol = vol_estimate if vol_estimate is not None else self._estimate_volatility()
        self._volatility_history.append(current_vol)
        if len(self._volatility_history) > self._max_history:
            self._volatility_history.pop(0)

        vol_regime = self._classify_volatility(current_vol)
        signal = np.sign(ofi) * 0.6 + np.sign(trade_imb) * 0.4

        if vol_regime == "high":
            position_size = signal * self.config.max_position_size * self.config.position_scale_factor
        elif vol_regime == "low":
            position_size = -signal * self.config.max_position_size
        else:
            position_size = signal * self.config.max_position_size * 0.8

        if position_size > 0.1:
            action_type = ActionType.BUY
        elif position_size < -0.1:
            action_type = ActionType.SELL
        else:
            action_type = ActionType.HOLD

        confidence = self.get_confidence(observation)

        return Action(
            action_type=action_type,
            position_size=np.clip(position_size, -self.config.max_position_size, self.config.max_position_size),
            confidence=confidence,
            metadata={
                'volatility': current_vol,
                'vol_regime': vol_regime,
                'signal': signal,
                'expert_type': 'volatility'
            }
        )

    def get_confidence(self, observation):
        """Calculate confidence based on volatility conditions."""
        obs = self._validate_observation(observation)

        ofi = obs[3]
        trade_imb = obs[4]
        vol_estimate = obs[8] if len(obs) > 8 else None

        current_vol = vol_estimate if vol_estimate is not None else self._estimate_volatility()
        vol_regime = self._classify_volatility(current_vol)

        if vol_regime == "high":
            regime_score = min(current_vol / self.config.high_vol_threshold, 1.0)
        elif vol_regime == "low":
            regime_score = 1.0 - (current_vol / self.config.low_vol_threshold)
            regime_score = max(0.0, regime_score)
        else:
            regime_score = 0.5

        signal = np.sign(ofi) * 0.6 + np.sign(trade_imb) * 0.4
        if vol_regime == "high":
            alignment_score = min(abs(signal), 1.0)
        elif vol_regime == "low":
            alignment_score = 0.5
        else:
            alignment_score = 0.5

        stability_score = self._calculate_vol_stability()
        confidence = 0.4 * regime_score + 0.4 * alignment_score + 0.2 * stability_score
        return min(max(confidence, 0.0), 1.0)

    def get_expertise(self):
        """Get list of market regimes this expert specializes in."""
        return [MarketRegime.HIGH_VOL, MarketRegime.LOW_VOL]

    def _estimate_volatility(self):
        """Estimate current volatility from price history."""
        if len(self._price_history) < 2:
            return 0.01

        prices = np.array(self._price_history)
        log_returns = np.diff(np.log(prices + 1e-8))

        if len(log_returns) < 2:
            return 0.01

        vol = np.std(log_returns) * np.sqrt(252 * 24 * 60)
        return max(vol, 1e-6)

    def _classify_volatility(self, volatility):
        """Classify volatility into high/medium/low."""
        if volatility >= self.config.high_vol_threshold:
            return "high"
        elif volatility <= self.config.low_vol_threshold:
            return "low"
        else:
            return "medium"

    def _calculate_vol_stability(self):
        """Calculate volatility stability score."""
        if len(self._volatility_history) < 10:
            return 0.5

        recent_vol = np.array(self._volatility_history[-10:])
        if np.mean(recent_vol) == 0:
            return 0.5

        cv = np.std(recent_vol) / np.mean(recent_vol)
        stability = 1.0 / (1.0 + cv)
        return min(stability, 1.0)

    def get_volatility_forecast(self, horizon=5):
        """Simple volatility forecast using EWMA."""
        if len(self._volatility_history) < 10:
            return self._estimate_volatility()

        vols = np.array(self._volatility_history[-20:])
        lambda_param = 0.94
        weights = np.array([(1 - lambda_param) * lambda_param ** i for i in range(len(vols))])
        weights = weights[::-1]
        weights /= weights.sum()

        forecast = np.sqrt(np.sum(weights * vols ** 2))
        return forecast

    def reset_history(self):
        """Reset volatility and price history."""
        self._volatility_history = []
        self._price_history = []
