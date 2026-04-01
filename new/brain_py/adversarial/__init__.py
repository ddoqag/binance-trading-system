"""
Adversarial Training: Market Maker Harvest Defense
三层对抗训练防御体系 - 公开 API
"""

from .types import (
    AdversarialType,
    AdversarialState,
    TrapFeatures,
    HarvestEvent,
    ModelSnapshot,
)
from .simulator import AdversarialMarketSimulator
from .detector import TrapDetector
from .online_learner import OnlineAdversarialLearner
from .meta_controller import AdversarialMetaController
from .utils import (
    calculate_tick_entropy,
    calculate_vpin,
    calculate_confidence,
    extract_trap_features,
    calculate_mahalanobis_distance,
    adjust_prior_by_anomaly,
)

__all__ = [
    # Types
    "AdversarialType",
    "AdversarialState",
    "TrapFeatures",
    "HarvestEvent",
    "ModelSnapshot",
    # Components
    "AdversarialMarketSimulator",
    "TrapDetector",
    "OnlineAdversarialLearner",
    "AdversarialMetaController",
    # Utils
    "calculate_tick_entropy",
    "calculate_vpin",
    "calculate_confidence",
    "extract_trap_features",
    "calculate_mahalanobis_distance",
    "adjust_prior_by_anomaly",
]
