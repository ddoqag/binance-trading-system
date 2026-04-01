"""
meta_agent_example.py - Example of integrating regime detector with Meta-Agent.

This shows how the MarketRegimeDetector can be used within a Meta-Agent
to adapt trading strategies based on market conditions.
"""

import numpy as np
from typing import Dict, Optional
from dataclasses import dataclass
from enum import Enum

from regime_detector import MarketRegimeDetector, Regime, RegimePrediction
from shm_client import MarketRegime as SHMRegime


class StrategyType(Enum):
    """Trading strategy types."""
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"
    HIGH_VOL = "high_volatility"
    NEUTRAL = "neutral"


@dataclass
class MetaDecision:
    """Decision from Meta-Agent."""
    strategy: StrategyType
    position_size: float
    confidence: float
    regime: Regime
    volatility_forecast: float


class MetaAgent:
    """
    Meta-Agent that uses regime detection for strategy selection.

    Adapts trading behavior based on detected market regime:
    - TRENDING: Use trend-following strategies
    - MEAN_REVERTING: Use mean-reversion strategies
    - HIGH_VOLATILITY: Reduce position size, use volatility strategies
    """

    def __init__(self):
        self.regime_detector = MarketRegimeDetector(n_states=3)
        self.current_regime: Optional[Regime] = None
        self.regime_confidence: float = 0.0

        # Strategy parameters per regime
        self.strategy_map = {
            Regime.TRENDING: StrategyType.TREND_FOLLOWING,
            Regime.MEAN_REVERTING: StrategyType.MEAN_REVERSION,
            Regime.HIGH_VOLATILITY: StrategyType.HIGH_VOL,
            Regime.UNKNOWN: StrategyType.NEUTRAL,
        }

        # Position sizing per regime (risk management)
        self.position_sizes = {
            Regime.TRENDING: 1.0,      # Full size in trends
            Regime.MEAN_REVERTING: 0.8, # Slightly reduced
            Regime.HIGH_VOLATILITY: 0.5, # Half size in high vol
            Regime.UNKNOWN: 0.3,        # Minimal size when uncertain
        }

    def fit(self, historical_prices: np.ndarray) -> bool:
        """Fit regime detector on historical data."""
        return self.regime_detector.fit(historical_prices)

    def update(self, price: float) -> MetaDecision:
        """
        Update Meta-Agent with new price and make decision.

        Args:
            price: Current market price

        Returns:
            MetaDecision with strategy and sizing
        """
        # Detect regime
        prediction = self.regime_detector.detect(price)

        self.current_regime = prediction.regime
        self.regime_confidence = prediction.confidence

        # Select strategy
        strategy = self.strategy_map.get(prediction.regime, StrategyType.NEUTRAL)

        # Adjust position size based on regime and confidence
        base_size = self.position_sizes.get(prediction.regime, 0.3)
        position_size = base_size * prediction.confidence

        return MetaDecision(
            strategy=strategy,
            position_size=position_size,
            confidence=prediction.confidence,
            regime=prediction.regime,
            volatility_forecast=prediction.volatility_forecast
        )

    def get_regime_for_shm(self) -> SHMRegime:
        """Convert internal regime to SHM regime format."""
        mapping = {
            Regime.TRENDING: SHMRegime.TREND_UP,
            Regime.MEAN_REVERTING: SHMRegime.RANGE,
            Regime.HIGH_VOLATILITY: SHMRegime.HIGH_VOL,
            Regime.UNKNOWN: SHMRegime.UNKNOWN,
        }
        return mapping.get(self.current_regime, SHMRegime.UNKNOWN)

    def get_stats(self) -> Dict:
        """Get Meta-Agent statistics."""
        return {
            "current_regime": self.current_regime.value if self.current_regime else "unknown",
            "regime_confidence": self.regime_confidence,
            "avg_detection_time_ms": self.regime_detector.get_avg_detection_time(),
            "regime_distribution": {
                k.value: v for k, v in self.regime_detector.get_regime_distribution().items()
            }
        }


def demo_meta_agent():
    """Demonstrate Meta-Agent usage."""
    print("=" * 60)
    print("Meta-Agent with Regime Detection Demo")
    print("=" * 60)

    # Create Meta-Agent
    agent = MetaAgent()

    # Generate synthetic training data
    print("\n1. Generating synthetic training data...")
    from regime_detector import generate_synthetic_regimes

    train_prices, _ = generate_synthetic_regimes(n_samples=600)

    # Fit regime detector
    print("2. Fitting regime detector...")
    success = agent.fit(train_prices)
    print(f"   Fit successful: {success}")

    # Test on new data
    print("\n3. Testing on new market data...")
    test_prices, true_regimes = generate_synthetic_regimes(n_samples=300, seed=123)

    decisions = []
    for i, price in enumerate(test_prices[50:100]):  # Test on subset
        decision = agent.update(price)
        decisions.append(decision)

        if i % 10 == 0:
            print(f"   Price: {price:.2f}")
            print(f"   Regime: {decision.regime.value} (confidence: {decision.confidence:.2f})")
            print(f"   Strategy: {decision.strategy.value}")
            print(f"   Position size: {decision.position_size:.2f}")
            print(f"   Vol forecast: {decision.volatility_forecast:.2%}")
            print()

    # Show statistics
    print("4. Meta-Agent Statistics:")
    stats = agent.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")

    print("\n" + "=" * 60)
    print("Demo complete!")
    print("=" * 60)


if __name__ == "__main__":
    demo_meta_agent()
