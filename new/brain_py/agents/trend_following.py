"""
trend_following.py - Trend Following Expert Agent

Expert agent specialized in trending markets (TREND_UP, TREND_DOWN).
Uses momentum indicators and moving average crossovers to generate
trading signals in the direction of the trend.

Features:
- OFI (Order Flow Imbalance) momentum detection
- Trade imbalance trend confirmation
- Queue position optimization for trend entries
- Dynamic position sizing based on trend strength
"""

import numpy as np
from dataclasses import dataclass
from .base_expert import BaseExpert, ExpertConfig, Action, ActionType, MarketRegime


@dataclass
class TrendFollowingConfig(ExpertConfig):
    """Configuration for trend following expert."""
    name: str = "trend_following"
    min_confidence: float = 0.35
    max_position_size: float = 1.0
    # Trend detection thresholds
    ofi_threshold: float = 0.3
    trade_imbalance_threshold: float = 0.2
    # Position sizing
    min_trend_strength: float = 0.4
    max_trend_strength: float = 1.0


class TrendFollowingExpert(BaseExpert):
    """
    Expert agent for trending markets.

    Specializes in:
    - TREND_UP: Long positions in uptrends
    - TREND_DOWN: Short positions in downtrends

    Uses OFI and trade imbalance to confirm trend direction
    and strength for position sizing.
    """

    def __init__(self, config: TrendFollowingConfig = None):
        cfg = config or TrendFollowingConfig()
        super().__init__(cfg)
        self.config = cfg

    def act(self, observation: np.ndarray) -> Action:
        """
        Generate trend-following action.

        Observation features (expected indices):
        - [0]: best_bid
        - [1]: best_ask
        - [2]: micro_price
        - [3]: ofi_signal
        - [4]: trade_imbalance
        - [5]: bid_queue_pos
        - [6]: ask_queue_pos
        - [7]: spread
        - [8]: volatility

        Args:
            observation: Market state observation

        Returns:
            Action with trend-following signal
        """
        obs = self._validate_observation(observation)

        # Extract features
        ofi = obs[3]
        trade_imb = obs[4]
        spread = obs[7] if len(obs) > 7 else 0.0

        # Calculate trend strength
        trend_strength = self._calculate_trend_strength(ofi, trade_imb)

        # Determine action based on trend direction and strength
        if trend_strength >= self.config.min_trend_strength:
            # Uptrend - go long
            position_size = min(trend_strength, self.config.max_position_size)
            confidence = self.get_confidence(observation)
            return Action(
                action_type=ActionType.BUY,
                position_size=position_size,
                confidence=confidence,
                metadata={
                    'trend_strength': trend_strength,
                    'ofi': ofi,
                    'trade_imbalance': trade_imb,
                    'expert_type': 'trend_following'
                }
            )
        elif trend_strength <= -self.config.min_trend_strength:
            # Downtrend - go short
            position_size = max(trend_strength, -self.config.max_position_size)
            confidence = self.get_confidence(observation)
            return Action(
                action_type=ActionType.SELL,
                position_size=position_size,
                confidence=confidence,
                metadata={
                    'trend_strength': trend_strength,
                    'ofi': ofi,
                    'trade_imbalance': trade_imb,
                    'expert_type': 'trend_following'
                }
            )
        else:
            # No clear trend
            return Action(
                action_type=ActionType.HOLD,
                position_size=0.0,
                confidence=0.3,
                metadata={
                    'trend_strength': trend_strength,
                    'expert_type': 'trend_following'
                }
            )

    def get_confidence(self, observation: np.ndarray) -> float:
        """
        Calculate confidence in trend signal.

        Higher confidence when:
        - OFI and trade imbalance agree on direction
        - Signals are strong (above thresholds)
        - Spread is tight (liquid market)

        Args:
            observation: Market state observation

        Returns:
            Confidence score in [0.0, 1.0]
        """
        obs = self._validate_observation(observation)

        ofi = obs[3]
        trade_imb = obs[4]
        spread = obs[7] if len(obs) > 7 else 1.0

        # Agreement between OFI and trade imbalance
        agreement = 1.0 if ofi * trade_imb > 0 else 0.3

        # Signal strength
        ofi_strength = min(abs(ofi) / self.config.ofi_threshold, 1.0)
        trade_strength = min(abs(trade_imb) / self.config.trade_imbalance_threshold, 1.0)

        # Spread factor (tighter spread = higher confidence)
        spread_factor = 1.0 / (1.0 + spread * 100)

        # Combined confidence
        confidence = agreement * (0.4 * ofi_strength + 0.4 * trade_strength + 0.2 * spread_factor)

        return min(max(confidence, 0.0), 1.0)

    def get_expertise(self):
        """
        Get list of market regimes this expert specializes in.

        Returns:
            List of MarketRegime values
        """
        return [MarketRegime.TREND_UP, MarketRegime.TREND_DOWN]

    def _calculate_trend_strength(self, ofi: float, trade_imbalance: float) -> float:
        """
        Calculate composite trend strength indicator.

        Combines OFI and trade imbalance into a normalized
        trend strength measure.

        Args:
            ofi: Order flow imbalance
            trade_imbalance: Trade imbalance

        Returns:
            Trend strength in [-1.0, 1.0]
        """
        # Weight OFI more heavily (leading indicator)
        ofi_weight = 0.6
        trade_weight = 0.4

        # Normalize signals
        ofi_norm = np.clip(ofi / self.config.ofi_threshold, -1.0, 1.0)
        trade_norm = np.clip(trade_imbalance / self.config.trade_imbalance_threshold, -1.0, 1.0)

        # Weighted combination
        trend_strength = ofi_weight * ofi_norm + trade_weight * trade_norm

        return np.clip(trend_strength, -1.0, 1.0)

    def should_enter_long(self, observation: np.ndarray) -> bool:
        """
        Check if conditions favor long entry.

        Args:
            observation: Market state observation

        Returns:
            True if long entry is favorable
        """
        obs = self._validate_observation(observation)
        ofi = obs[3]
        trade_imb = obs[4]

        trend_strength = self._calculate_trend_strength(ofi, trade_imb)
        return trend_strength >= self.config.min_trend_strength

    def should_enter_short(self, observation: np.ndarray) -> bool:
        """
        Check if conditions favor short entry.

        Args:
            observation: Market state observation

        Returns:
            True if short entry is favorable
        """
        obs = self._validate_observation(observation)
        ofi = obs[3]
        trade_imb = obs[4]

        trend_strength = self._calculate_trend_strength(ofi, trade_imb)
        return trend_strength <= -self.config.min_trend_strength
