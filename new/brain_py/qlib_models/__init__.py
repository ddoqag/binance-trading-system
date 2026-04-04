"""
qlib_models - Lightweight port of Microsoft Qlib benchmark models.

Provides cleaned, dependency-minimal implementations of top Qlib models
for integration with the HFT Meta-Agent and MoE pipeline.
"""

from .base import QlibModelConfig, QlibBaseModel
from .features import HFTFeatureMapper
from .adapters import QlibExpertConfig, QlibExpert

try:
    from .gbdt.lightgbm_model import LightGBMModel
except ImportError:  # pragma: no cover
    LightGBMModel = None

try:
    from .gbdt.double_ensemble import DoubleEnsemble
except ImportError:  # pragma: no cover
    DoubleEnsemble = None

try:
    from .neural.mlp_model import MLPModel
except ImportError:  # pragma: no cover
    MLPModel = None

try:
    from .neural.lstm_model import LSTMModel
except ImportError:  # pragma: no cover
    LSTMModel = None

try:
    from .neural.gru_model import GRUModel
except ImportError:  # pragma: no cover
    GRUModel = None

try:
    from .neural.alstm_model import ALSTMModel
except ImportError:  # pragma: no cover
    ALSTMModel = None

try:
    from .neural.tcn_model import TCNModel
except ImportError:  # pragma: no cover
    TCNModel = None

try:
    from .neural.transformer_model import TransformerModel
except ImportError:  # pragma: no cover
    TransformerModel = None

try:
    from .graph.gats_model import GATsModel
except ImportError:  # pragma: no cover
    GATsModel = None

try:
    from .graph.hist_model import HISTModel
except ImportError:  # pragma: no cover
    HISTModel = None

try:
    from .advanced.tra_model import TRAModel
except ImportError:  # pragma: no cover
    TRAModel = None

try:
    from .advanced.model_ensemble import QlibTopKEnsemble
except ImportError:  # pragma: no cover
    QlibTopKEnsemble = None

__all__ = [
    # Base
    'QlibModelConfig',
    'QlibBaseModel',
    'HFTFeatureMapper',
    'QlibExpertConfig',
    'QlibExpert',
    # Models
    'LightGBMModel',
    'DoubleEnsemble',
    'MLPModel',
    'LSTMModel',
    'GRUModel',
    'ALSTMModel',
    'TCNModel',
    'TransformerModel',
    'GATsModel',
    'HISTModel',
    'TRAModel',
    'QlibTopKEnsemble',
]
