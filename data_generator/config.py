"""
赚钱版数据生成器配置
机构级量化交易数据生成系统配置
"""

from typing import List, Dict, Any
from dataclasses import dataclass, field

@dataclass
class DataConfig:
    """数据配置"""
    symbol: str = "BTCUSDT"
    interval: str = "5m"
    start_date: str = "2021-01-01"
    end_date: str = "2025-12-31"
    lookback_period: int = 64  # 历史窗口长度
    prediction_horizon: int = 12  # 预测周期（12个bar）
    min_price: float = 10000.0  # BTC最低价格过滤
    max_price: float = 100000.0  # BTC最高价格过滤

@dataclass
class FeatureConfig:
    """特征配置"""
    include_price_features: bool = True
    include_volatility_features: bool = True
    include_orderflow_features: bool = True
    include_crossasset_features: bool = False
    technical_indicators: List[str] = None
    multi_period_config: Dict[str, Any] = None
    alpha_factors: List[str] = None

    def __post_init__(self):
        if self.technical_indicators is None:
            self.technical_indicators = [
                "rsi", "bbands", "atr", "macd"
            ]

        if self.multi_period_config is None:
            self.multi_period_config = {
                "periods": ["5m", "15m", "1h"],
                "features": ["ret_1", "ret_5", "trend", "volatility"]
            }

        if self.alpha_factors is None:
            self.alpha_factors = [
                "order_flow_imbalance",
                "micro_price",
                "volume_profile",
                "volatility_regime"
            ]

@dataclass
class LabelConfig:
    """标签配置"""
    use_triple_barrier: bool = True
    upper_barrier: float = 0.005  # 5bps收益止盈
    lower_barrier: float = 0.005  # 5bps亏损止损
    time_barrier: int = 12  # 12个bar止损
    use_return_label: bool = True
    use_classification_label: bool = False
    classification_threshold: float = 0.002

@dataclass
class TrainConfig:
    """训练配置"""
    test_ratio: float = 0.2
    val_ratio: float = 0.1
    time_split: bool = True
    train_start_date: str = "2021-01-01"
    train_end_date: str = "2023-12-31"
    val_start_date: str = "2024-01-01"
    val_end_date: str = "2024-12-31"
    test_start_date: str = "2025-01-01"
    test_end_date: str = "2025-12-31"
    normalization: str = "standard"  # 标准化方法
    shuffle: bool = False  # 时间序列不打乱

@dataclass
class SystemConfig:
    """系统配置"""
    binance_api_key: str = ""
    binance_secret: str = ""
    output_dir: str = "data/money_version"
    save_raw_data: bool = True
    save_processed_data: bool = True
    log_level: str = "INFO"
    max_concurrent_download: int = 5
    retry_count: int = 3

@dataclass
class DataGeneratorConfig:
    """综合配置"""
    data: DataConfig = field(default_factory=DataConfig)
    feature: FeatureConfig = field(default_factory=FeatureConfig)
    label: LabelConfig = field(default_factory=LabelConfig)
    train: TrainConfig = field(default_factory=TrainConfig)
    system: SystemConfig = field(default_factory=SystemConfig)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "data": self.data.__dict__,
            "feature": self.feature.__dict__,
            "label": self.label.__dict__,
            "train": self.train.__dict__,
            "system": self.system.__dict__
        }

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'DataGeneratorConfig':
        """从字典加载配置"""
        return cls(
            data=DataConfig(**config_dict.get("data", {})),
            feature=FeatureConfig(**config_dict.get("feature", {})),
            label=LabelConfig(**config_dict.get("label", {})),
            train=TrainConfig(**config_dict.get("train", {})),
            system=SystemConfig(**config_dict.get("system", {}))
        )
