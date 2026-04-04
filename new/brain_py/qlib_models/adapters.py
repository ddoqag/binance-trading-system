"""
adapters.py - Bridge QlibBaseModel implementations into the HFT BaseExpert ecosystem.

Provides:
- QlibExpertConfig: configuration extending ExpertConfig
- QlibExpert: BaseExpert implementation wrapping a QlibBaseModel
"""

from typing import List, Optional
import numpy as np

try:
    from agents.base_expert import BaseExpert, ExpertConfig, Action, ActionType, MarketRegime
except ImportError:
    from brain_py.agents.base_expert import BaseExpert, ExpertConfig, Action, ActionType, MarketRegime
from .base import QlibBaseModel
from .features import HFTFeatureMapper


class QlibExpertConfig(ExpertConfig):
    """Configuration for Qlib-based expert agents."""

    def __init__(
        self,
        name: str = "qlib_expert",
        model: Optional[QlibBaseModel] = None,
        min_confidence: float = 0.3,
        max_position_size: float = 1.0,
        lookback_window: int = 20,
        feature_dim: int = 9,
        extra_feature_dim: int = 0,
        suitable_regimes: Optional[List[MarketRegime]] = None,
        model_prediction_threshold: float = 0.0,
    ):
        super().__init__(
            name=name,
            min_confidence=min_confidence,
            max_position_size=max_position_size,
            lookback_window=lookback_window,
            feature_dim=feature_dim,
        )
        self.model = model
        self.extra_feature_dim = extra_feature_dim
        self.suitable_regimes = suitable_regimes or [
            MarketRegime.TREND_UP,
            MarketRegime.TREND_DOWN,
        ]
        self.model_prediction_threshold = model_prediction_threshold


class QlibExpert(BaseExpert):
    """
    BaseExpert wrapper around a QlibBaseModel.

    The model predicts future returns. We translate:
      predicted_return > threshold   -> BUY
      predicted_return < -threshold  -> SELL
      otherwise                      -> HOLD

    Position size scales with prediction magnitude (capped at max_position_size).
    """

    def __init__(self, config: QlibExpertConfig):
        super().__init__(config)
        self.config = config
        self.mapper = HFTFeatureMapper(
            lookback_window=config.lookback_window,
            feature_dim=config.feature_dim,
            extra_feature_dim=config.extra_feature_dim,
        )
        self._recent_predictions: List[float] = []
        self._max_prediction_history = 100

    def act(self, observation: np.ndarray) -> Action:
        obs = self._validate_observation(observation)
        if self.config.extra_feature_dim > 0:
            base_obs = obs[: self.config.feature_dim]
            if len(obs) > self.config.feature_dim:
                extra_obs = obs[self.config.feature_dim : self.config.feature_dim + self.config.extra_feature_dim]
            else:
                extra_obs = np.zeros(self.config.extra_feature_dim, dtype=np.float32)
            self.mapper.update(base_obs, extra=extra_obs)
        else:
            self.mapper.update(obs)

        model = self.config.model
        if model is None or not model.is_fitted:
            return Action(
                action_type=ActionType.HOLD,
                position_size=0.0,
                confidence=0.1,
                metadata={"reason": "model_not_ready"},
            )

        # Select input format based on model category
        if model.config.model_type in ("lightgbm", "double_ensemble"):
            x = self.mapper.get_flat()
        else:
            x = self.mapper.get_sequence()

        if x is None:
            return Action(
                action_type=ActionType.HOLD,
                position_size=0.0,
                confidence=0.1,
                metadata={"reason": "insufficient_history"},
            )

        # Ensure batch dimension
        if x.ndim == 1:
            x = x.reshape(1, -1)
        elif x.ndim == 2:
            x = x[np.newaxis, ...]

        pred = model.predict(x)
        predicted_return = float(pred.flatten()[0])
        self._recent_predictions.append(predicted_return)
        if len(self._recent_predictions) > self._max_prediction_history:
            self._recent_predictions.pop(0)

        threshold = self.config.model_prediction_threshold
        confidence = self.get_confidence(observation)

        if predicted_return > threshold:
            position_size = min(
                abs(predicted_return) * 2.0,
                self.config.max_position_size,
            )
            return Action(
                action_type=ActionType.BUY,
                position_size=position_size,
                confidence=confidence,
                metadata={
                    "predicted_return": predicted_return,
                    "model_type": model.config.model_type,
                    "expert_type": "qlib",
                },
            )
        elif predicted_return < -threshold:
            position_size = -min(
                abs(predicted_return) * 2.0,
                self.config.max_position_size,
            )
            return Action(
                action_type=ActionType.SELL,
                position_size=position_size,
                confidence=confidence,
                metadata={
                    "predicted_return": predicted_return,
                    "model_type": model.config.model_type,
                    "expert_type": "qlib",
                },
            )
        else:
            return Action(
                action_type=ActionType.HOLD,
                position_size=0.0,
                confidence=confidence * 0.5,
                metadata={
                    "predicted_return": predicted_return,
                    "model_type": model.config.model_type,
                    "expert_type": "qlib",
                },
            )

    def get_confidence(self, observation: np.ndarray) -> float:
        """Confidence based on prediction consistency and magnitude."""
        if not self._recent_predictions:
            return 0.3

        recent = self._recent_predictions[-10:]
        recent_std = float(np.std(recent)) if len(recent) >= 10 else 0.1
        consistency_score = 1.0 / (1.0 + recent_std * 10)

        last_pred = abs(self._recent_predictions[-1])
        magnitude_score = min(last_pred * 5.0, 1.0)

        readiness = 1.0 if (self.config.model and self.config.model.is_fitted) else 0.0

        confidence = 0.4 * consistency_score + 0.4 * magnitude_score + 0.2 * readiness
        return float(np.clip(confidence, 0.0, 1.0))

    def get_expertise(self) -> List[MarketRegime]:
        return self.config.suitable_regimes

    def reset(self) -> None:
        """Reset mapper and prediction history."""
        self.mapper.reset()
        self._recent_predictions.clear()
        self._performance_stats = {
            "calls": 0,
            "correct_predictions": 0,
            "total_pnl": 0.0,
        }
