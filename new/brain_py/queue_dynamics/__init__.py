"""
queue_dynamics - Queue Dynamics v3 Core Engine
Probability-based order filling with Hazard Rate modeling

Components:
- hazard_model: Hazard Rate calculation λ = base × exp(-α·queue_ratio) × (1 + β·OFI)
- queue_tracker: Real-time queue position tracking
- adverse_selection: Toxic flow detection (adverse selection)
- partial_fill: Partial fill quantity modeling
- engine: Combined engine
"""

from .hazard_model import HazardRateModel, HazardRateConfig
from .queue_tracker import QueuePositionTracker, QueueLevel
from .adverse_selection import AdverseSelectionDetector, AdverseEvent
from .partial_fill import PartialFillModel, PartialFillConfig
from .engine import QueueDynamicsEngine, QueueDynamicsConfig

__all__ = [
    'HazardRateModel',
    'HazardRateConfig',
    'QueuePositionTracker',
    'QueueLevel',
    'AdverseSelectionDetector',
    'AdverseEvent',
    'PartialFillModel',
    'PartialFillConfig',
    'QueueDynamicsEngine',
    'QueueDynamicsConfig',
]
