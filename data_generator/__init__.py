"""
Profitable Data Generator
Institutional-grade quantitative trading data generation system
"""

__version__ = "1.0.0"

# Export core components
from data_generator.config import (
    DataGeneratorConfig,
    DataConfig,
    FeatureConfig,
    LabelConfig,
    TrainConfig,
    SystemConfig
)
from data_generator.data_loader import BinanceDataLoader
from data_generator.db_loader import DatabaseLoader, DatabaseConfig
from data_generator.feature_engineer import FeatureEngineer
from data_generator.label_generator import LabelGenerator
from data_generator.main import (
    ProfitableDataGenerator,
    DataSplitStrategy,
    DataGenerationResult
)

# Version information
VERSION = __version__

# Metadata
__author__ = "Institutional Quantitative Trading Team"
__description__ = "Profitable Data Generator - Institutional-grade quantitative trading data generation system"
__url__ = "https://github.com/your-repo"
__license__ = "MIT"
