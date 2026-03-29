"""
Profitable Data Generator - Main Module
Institutional-grade quantitative trading data generation system

Production-grade features:
1. Data quality validation (duplicates, anomalies, OHLC consistency)
2. Look-ahead bias prevention in factor calculation
3. Transaction cost-aware label generation
4. Leakage-free data splitting with purging and embargo
"""

import os
import sys
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json
import warnings

warnings.filterwarnings("ignore")

# Add project path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import data generator modules
from data_generator.config import DataGeneratorConfig, DataConfig, FeatureConfig, LabelConfig
from data_generator.data_loader import BinanceDataLoader
from data_generator.feature_engineer import FeatureEngineer
from data_generator.label_generator import LabelGenerator, LabelConfig as LabelGenerationConfig

# Import new production-grade modules
from data_generator.data_quality_validator import DataQualityValidator, validate_data_quality
from data_generator.lookahead_bias_preventer import LookaheadBiasPreventer, PITFactorCalculator
from data_generator.cost_aware_labels import CostAwareTripleBarrier, TransactionCostConfig
from data_generator.leakage_free_splitter import LeakageFreeSplitter, SplitConfig, SplitType

logger = logging.getLogger(__name__)


class DataSplitStrategy(Enum):
    """Data split strategy"""
    TIME_BASED = "time_based"
    FIXED_RATIO = "fixed_ratio"
    LEAKAGE_FREE = "leakage_free"
    WALK_FORWARD = "walk_forward"
    CUSTOM = "custom"


@dataclass
class DataGenerationResult:
    """Data generation result container"""
    train_data: Optional[pd.DataFrame] = None
    val_data: Optional[pd.DataFrame] = None
    test_data: Optional[pd.DataFrame] = None
    config: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    quality_report: Optional[Dict[str, Any]] = None
    factor_names: Optional[List[str]] = None
    label_names: Optional[List[str]] = None
    data_quality_score: float = 0.0
    leakage_check_passed: bool = False


class ProfitableDataGenerator:
    """
    Main Data Generator - Institutional-grade quantitative trading data generation system

    This system provides comprehensive data generation for profitable strategies:
    - Multi-symbol support (BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT)
    - Multi-interval support (1m, 5m, 15m, 1h, 4h)
    - Triple barrier labeling with volatility adjustment and transaction costs
    - 30+ institutional-grade Alpha factors with look-ahead bias prevention
    - Smart data splitting (time-based, fixed ratio, leakage-free, walk-forward)
    - Comprehensive quality validation (duplicates, anomalies, OHLC consistency)
    - Metadata tracking for reproducibility
    """

    def __init__(
        self,
        config: Optional[DataGeneratorConfig] = None,
        use_cost_aware_labels: bool = True,
        use_lookahead_prevention: bool = True,
        use_leakage_free_split: bool = True,
        transaction_cost_config: Optional[TransactionCostConfig] = None
    ):
        """
        Initialize profitable data generator

        Args:
            config: Data generator configuration
            use_cost_aware_labels: Whether to use transaction cost-aware labels
            use_lookahead_prevention: Whether to prevent look-ahead bias in factors
            use_leakage_free_split: Whether to use leakage-free data splitting
            transaction_cost_config: Custom transaction cost configuration
        """
        if config is None:
            self.config = DataGeneratorConfig()
        else:
            self.config = config

        self.logger = logging.getLogger(__name__)

        # Feature flags for production-grade features
        self.use_cost_aware_labels = use_cost_aware_labels
        self.use_lookahead_prevention = use_lookahead_prevention
        self.use_leakage_free_split = use_leakage_free_split

        # Initialize components
        self.data_loader = BinanceDataLoader(self.config)
        self.feature_engineer = FeatureEngineer(self.config)

        # Initialize new production-grade components
        self.data_quality_validator = DataQualityValidator()
        self.bias_preventer = LookaheadBiasPreventer() if use_lookahead_prevention else None
        self.pit_calculator = PITFactorCalculator(self.bias_preventer) if use_lookahead_prevention else None

        # Transaction cost configuration
        if transaction_cost_config:
            self.cost_config = transaction_cost_config
        elif use_cost_aware_labels:
            self.cost_config = TransactionCostConfig()  # Default realistic costs
        else:
            self.cost_config = None

        # Label generator (cost-aware or standard)
        if use_cost_aware_labels and self.cost_config:
            self.cost_aware_label_generator = CostAwareTripleBarrier(self.cost_config)
            self.label_generator = None  # Will use cost_aware_label_generator instead
        else:
            self.cost_aware_label_generator = None
            self.label_generator = LabelGenerator(LabelGenerationConfig(
                use_triple_barrier=self.config.label.use_triple_barrier,
                upper_barrier=self.config.label.upper_barrier,
                lower_barrier=self.config.label.lower_barrier,
                time_barrier=self.config.label.time_barrier,
                use_return_label=self.config.label.use_return_label,
                use_classification_label=self.config.label.use_classification_label,
                classification_threshold=self.config.label.classification_threshold
            ))

        # Leakage-free splitter
        if use_leakage_free_split:
            split_config = SplitConfig(
                split_type=SplitType.TIME_BASED,
                train_ratio=0.7,
                val_ratio=0.15,
                test_ratio=0.15,
                purge_gap=10,
                embargo_pct=0.01
            )
            self.leakage_free_splitter = LeakageFreeSplitter(split_config)
        else:
            self.leakage_free_splitter = None

        # State tracking
        self._raw_data: Optional[pd.DataFrame] = None
        self._processed_data: Optional[pd.DataFrame] = None
        self._metadata: Dict[str, Any] = {}
        self._data_quality_report: Optional[Dict] = None
        self._factor_names: List[str] = []
        self._is_fitted = False

    def generate_training_data(
        self,
        base_dir: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        split_strategy: DataSplitStrategy = DataSplitStrategy.TIME_BASED,
        save_output: bool = True,
        validate_quality: bool = True
    ) -> DataGenerationResult:
        """
        Generate complete training data pipeline

        Args:
            base_dir: Base directory for data files
            symbols: List of symbols to process
            split_strategy: Data split strategy
            save_output: Whether to save output files
            validate_quality: Whether to validate data quality

        Returns:
            DataGenerationResult with processed data
        """
        self.logger.info("=" * 70)
        self.logger.info("Profitable Data Generator - Starting Generation")
        self.logger.info("=" * 70)

        # Set defaults
        if base_dir is None:
            base_dir = self.config.system.output_dir

        if symbols is None:
            symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

        # Step 1: Load and preprocess raw data
        self.logger.info("\n[Step 1/5] Loading and preprocessing raw data")
        self._load_raw_data(base_dir, symbols)

        # Step 2: Calculate features
        self.logger.info("\n[Step 2/5] Calculating institutional-grade factors")
        self._calculate_features()

        # Step 3: Generate labels
        self.logger.info("\n[Step 3/5] Generating training labels")
        self._generate_labels()

        # Step 4: Split data
        self.logger.info("\n[Step 4/5] Splitting data into train/val/test")
        train_data, val_data, test_data = self._split_data(split_strategy)

        # Step 5: Validate and save
        self.logger.info("\n[Step 5/5] Validating and saving output")
        quality_report = None
        if validate_quality:
            quality_report = self._validate_data_quality(train_data, val_data, test_data)

        # Collect metadata
        self._collect_metadata(symbols, split_strategy)

        # Save output
        if save_output:
            self._save_output(train_data, val_data, test_data)

        # Get factor and label names
        factor_names = self._get_factor_names()
        label_names = self._get_label_names()

        result = DataGenerationResult(
            train_data=train_data,
            val_data=val_data,
            test_data=test_data,
            config=self.config.to_dict(),
            metadata=self._metadata,
            quality_report=quality_report,
            factor_names=factor_names,
            label_names=label_names
        )

        self.logger.info("\n" + "=" * 70)
        self.logger.info("Data Generation Complete")
        self.logger.info("=" * 70)

        return result

    def _load_raw_data(self, base_dir: str, symbols: List[str]):
        """Load and preprocess raw data with quality validation"""
        self.logger.info(f"Loading data from {base_dir} for symbols: {symbols}")

        combined_data = self.data_loader.create_combined_dataframe(base_dir, symbols)

        if not combined_data:
            raise ValueError("No data loaded for any symbol")

        # Use first symbol as primary (or combine in future)
        primary_symbol = symbols[0]
        if primary_symbol not in combined_data:
            raise ValueError(f"Primary symbol {primary_symbol} not found in data")

        self._raw_data = combined_data[primary_symbol].copy()
        self.logger.info(f"Loaded {len(self._raw_data)} records for {primary_symbol}")

        # Validate data quality
        self.logger.info("Validating data quality...")
        quality_report = self.data_quality_validator.validate(
            self._raw_data,
            symbol=primary_symbol,
            interval=self.config.data.intervals[0] if self.config.data.intervals else "1h"
        )

        self._data_quality_report = quality_report.to_dict()
        self.logger.info(f"Data quality score: {quality_report.quality_score:.2%}")

        if not quality_report.is_valid:
            self.logger.warning("Data quality issues detected:")
            for issue_type, count in quality_report.issue_counts.items():
                self.logger.warning(f"  - {issue_type.value}: {count}")

            # Clean data if issues found
            self._raw_data = self.data_quality_validator.clean_data(
                self._raw_data,
                report=quality_report,
                remove_duplicates=True
            )
            self.logger.info(f"After cleaning: {len(self._raw_data)} records")

        # Apply price filtering
        self._raw_data = self.data_loader.filter_by_price(
            self._raw_data,
            self.config.data.min_price,
            self.config.data.max_price
        )

        self.logger.info(f"After price filtering: {len(self._raw_data)} records")

    def _calculate_features(self):
        """Calculate institutional-grade factors with look-ahead bias prevention"""
        if self._raw_data is None:
            raise ValueError("No raw data loaded")

        if self.use_lookahead_prevention and self.pit_calculator:
            self.logger.info("Using point-in-time (PIT) factor calculation")
            self._processed_data = self.pit_calculator.calculate_all_factors(
                self._raw_data,
                include_volume=True,
                include_volatility=True
            )
        else:
            self.logger.info("Using standard factor calculation")
            self._processed_data = self.feature_engineer.calculate_all_factors(self._raw_data)

        factor_count = len(self._processed_data.columns) - len(self._raw_data.columns)
        self.logger.info(f"Calculated {factor_count} factors")

        # Validate no look-ahead bias
        if self.use_lookahead_prevention and self.bias_preventer:
            self.logger.info("Validating factors for look-ahead bias...")
            factor_names = self._get_factor_names()
            validation_results = {}
            for factor in factor_names[:10]:  # Check first 10 factors
                if factor in self._processed_data.columns:
                    is_valid = self.bias_preventer.validate_no_lookahead(
                        self._processed_data, factor
                    )
                    validation_results[factor] = is_valid

            invalid_count = sum(1 for v in validation_results.values() if not v)
            if invalid_count > 0:
                self.logger.warning(f"Found {invalid_count} factors with potential look-ahead bias")
            else:
                self.logger.info("All validated factors are PIT-correct")

    def _generate_labels(self):
        """Generate training labels with transaction cost awareness"""
        if self._processed_data is None:
            raise ValueError("No processed data available")

        if self.use_cost_aware_labels and self.cost_aware_label_generator:
            self.logger.info("Using cost-aware triple barrier labels")
            self.logger.info(
                f"Transaction costs: entry={self.cost_config.total_entry_cost:.4f}, "
                f"exit={self.cost_config.total_exit_cost:.4f}"
            )

            self._processed_data = self.cost_aware_label_generator.generate_labels(
                self._processed_data,
                upper_barrier=self.config.label.upper_barrier,
                lower_barrier=self.config.label.lower_barrier,
                time_barrier=self.config.label.time_barrier,
                volatility_adjusted=True
            )

            # Log label statistics
            if 'triple_barrier_label' in self._processed_data.columns:
                labels = self._processed_data['triple_barrier_label'].dropna()
                self.logger.info(f"Label distribution: upper={(labels==1).sum()}, "
                                 f"lower={(labels==-1).sum()}, time={(labels==0).sum()}")

            if 'triple_barrier_net_return' in self._processed_data.columns:
                net_returns = self._processed_data['triple_barrier_net_return'].dropna()
                win_rate = (net_returns > 0).mean()
                self.logger.info(f"Net win rate after costs: {win_rate*100:.1f}%")
        else:
            self.logger.info("Using standard label generation")
            self._processed_data = self.label_generator.generate_all_labels(self._processed_data)

        label_count = sum(1 for col in self._processed_data.columns if any(
            pattern in col for pattern in [
                "triple_barrier", "ret_", "log_ret_", "class_",
                "trend_label", "volatility_regime_label", "anomaly_label"
            ]
        ))
        self.logger.info(f"Generated {label_count} label types")

    def _split_data(
        self,
        strategy: DataSplitStrategy
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Split data into train/val/test sets with leakage prevention"""
        if self._processed_data is None:
            raise ValueError("No processed data available")

        df = self._processed_data

        if strategy == DataSplitStrategy.LEAKAGE_FREE and self.leakage_free_splitter:
            self.logger.info("Using leakage-free data splitting with purging and embargo")

            # Ensure index is datetime
            if not isinstance(df.index, pd.DatetimeIndex):
                df = df.copy()
                df.index = pd.to_datetime(df.index)

            split = self.leakage_free_splitter.split(df)

            train_data = df.loc[split.train_idx].copy()
            val_data = df.loc[split.val_idx].copy()
            test_data = df.loc[split.test_idx].copy()

            # Verify no leakage
            is_valid = self.leakage_free_splitter.verify_no_leakage(
                split.train_idx, split.test_idx
            )
            self._is_fitted = is_valid

            self.logger.info(f"Leakage check passed: {is_valid}")

        elif strategy == DataSplitStrategy.WALK_FORWARD and self.leakage_free_splitter:
            self.logger.info("Using walk-forward cross-validation")

            # Ensure index is datetime
            if not isinstance(df.index, pd.DatetimeIndex):
                df = df.copy()
                df.index = pd.to_datetime(df.index)

            # Get first walk-forward split for now
            splits = list(self.leakage_free_splitter.split_walk_forward(df))
            if splits:
                split = splits[0]
                train_data = df.loc[split.train_idx].copy()
                val_data = df.loc[split.val_idx].copy()
                test_data = df.loc[split.test_idx].copy()
            else:
                raise ValueError("Could not create walk-forward splits")

        elif strategy == DataSplitStrategy.TIME_BASED:
            # Time-based split
            train_start = pd.to_datetime(self.config.train.train_start_date)
            train_end = pd.to_datetime(self.config.train.train_end_date)
            val_start = pd.to_datetime(self.config.train.val_start_date)
            val_end = pd.to_datetime(self.config.train.val_end_date)
            test_start = pd.to_datetime(self.config.train.test_start_date)
            test_end = pd.to_datetime(self.config.train.test_end_date)

            # Ensure index is datetime
            if not isinstance(df.index, pd.DatetimeIndex):
                df = df.copy()
                df.index = pd.to_datetime(df.index)

            train_data = df[
                (df.index >= train_start) & (df.index <= train_end)
            ].copy()

            val_data = df[
                (df.index >= val_start) & (df.index <= val_end)
            ].copy()

            test_data = df[
                (df.index >= test_start) & (df.index <= test_end)
            ].copy()

        elif strategy == DataSplitStrategy.FIXED_RATIO:
            # Fixed ratio split
            test_ratio = self.config.train.test_ratio
            val_ratio = self.config.train.val_ratio

            total_len = len(df)
            test_size = int(total_len * test_ratio)
            val_size = int(total_len * val_ratio)
            train_size = total_len - test_size - val_size

            train_data = df.iloc[:train_size].copy()
            val_data = df.iloc[train_size:train_size+val_size].copy()
            test_data = df.iloc[train_size+val_size:].copy()

        else:
            raise ValueError(f"Unknown split strategy: {strategy}")

        self.logger.info(f"Train: {len(train_data)}, Val: {len(val_data)}, Test: {len(test_data)}")

        return train_data, val_data, test_data

    def _validate_data_quality(
        self,
        train_data: pd.DataFrame,
        val_data: pd.DataFrame,
        test_data: pd.DataFrame
    ) -> Dict[str, Any]:
        """Validate data quality using production-grade validator"""
        quality_report = {}

        # Validate raw data quality
        if self._data_quality_report:
            quality_report["raw_data"] = self._data_quality_report

        # Validate each split
        for name, data in [("train", train_data), ("val", val_data), ("test", test_data)]:
            if len(data) > 0:
                split_report = self.data_quality_validator.validate(data)
                quality_report[name] = {
                    "quality_score": split_report.quality_score,
                    "is_valid": split_report.is_valid,
                    "issue_counts": {k.value: v for k, v in split_report.issue_counts.items()},
                    "record_count": len(data)
                }

        # Validate label quality (if using standard label generator)
        if self.label_generator:
            quality_report["labels"] = self.label_generator.validate_label_quality(train_data)
            self.label_generator.print_label_quality_report(quality_report["labels"])

        # Validate factor coverage
        quality_report["factors"] = self._validate_factor_coverage(
            train_data, val_data, test_data
        )

        # Validate data completeness
        quality_report["completeness"] = self._validate_data_completeness(
            train_data, val_data, test_data
        )

        # Validate distribution consistency
        quality_report["distribution"] = self._validate_distribution_consistency(
            train_data, val_data, test_data
        )

        # Check for data leakage between sets
        if self.leakage_free_splitter:
            train_idx = train_data.index
            test_idx = test_data.index
            no_leakage = self.leakage_free_splitter.verify_no_leakage(train_idx, test_idx)
            quality_report["leakage_check"] = {
                "passed": no_leakage,
                "train_test_overlap": len(train_idx.intersection(test_idx))
            }

        return quality_report

    def _validate_factor_coverage(
        self,
        train_data: pd.DataFrame,
        val_data: pd.DataFrame,
        test_data: pd.DataFrame
    ) -> Dict[str, Any]:
        """Validate factor coverage across datasets"""
        factor_names = self._get_factor_names()

        coverage = {
            "train": {},
            "val": {},
            "test": {}
        }

        for factor in factor_names:
            if factor in train_data.columns:
                coverage["train"][factor] = train_data[factor].notna().mean()
            if factor in val_data.columns:
                coverage["val"][factor] = val_data[factor].notna().mean()
            if factor in test_data.columns:
                coverage["test"][factor] = test_data[factor].notna().mean()

        return coverage

    def _validate_data_completeness(
        self,
        train_data: pd.DataFrame,
        val_data: pd.DataFrame,
        test_data: pd.DataFrame
    ) -> Dict[str, Any]:
        """Validate data completeness"""
        return {
            "train": {
                "total_records": len(train_data),
                "complete_records": train_data.dropna().shape[0],
                "completeness_ratio": train_data.dropna().shape[0] / len(train_data)
            },
            "val": {
                "total_records": len(val_data),
                "complete_records": val_data.dropna().shape[0],
                "completeness_ratio": val_data.dropna().shape[0] / len(val_data)
            },
            "test": {
                "total_records": len(test_data),
                "complete_records": test_data.dropna().shape[0],
                "completeness_ratio": test_data.dropna().shape[0] / len(test_data)
            }
        }

    def _validate_distribution_consistency(
        self,
        train_data: pd.DataFrame,
        val_data: pd.DataFrame,
        test_data: pd.DataFrame
    ) -> Dict[str, Any]:
        """Validate label distribution consistency"""
        consistency = {}

        label_columns = ["triple_barrier_label", "class_12", "trend_label"]

        for label_col in label_columns:
            if label_col in train_data.columns:
                train_dist = train_data[label_col].dropna().value_counts(normalize=True)
                val_dist = val_data[label_col].dropna().value_counts(normalize=True)
                test_dist = test_data[label_col].dropna().value_counts(normalize=True)

                consistency[label_col] = {
                    "train": train_dist.to_dict(),
                    "val": val_dist.to_dict(),
                    "test": test_dist.to_dict()
                }

        return consistency

    def _collect_metadata(self, symbols: List[str], strategy: DataSplitStrategy):
        """Collect metadata for reproducibility"""
        import time
        from datetime import datetime

        self._metadata = {
            "generation_timestamp": datetime.now().isoformat(),
            "symbols": symbols,
            "split_strategy": strategy.value,
            "production_features": {
                "cost_aware_labels": self.use_cost_aware_labels,
                "lookahead_prevention": self.use_lookahead_prevention,
                "leakage_free_split": self.use_leakage_free_split,
                "data_quality_validation": True
            },
            "transaction_costs": {
                "total_entry_cost": self.cost_config.total_entry_cost if self.cost_config else 0,
                "total_exit_cost": self.cost_config.total_exit_cost if self.cost_config else 0,
                "total_roundtrip_cost": self.cost_config.total_roundtrip_cost if self.cost_config else 0
            } if self.cost_config else None,
            "data_config": self.config.data.__dict__,
            "feature_config": self.config.feature.__dict__,
            "label_config": self.config.label.__dict__,
            "train_config": self.config.train.__dict__,
            "system_config": self.config.system.__dict__,
            "factor_summary": self.feature_engineer.get_factor_summary(),
            "raw_data_shape": self._raw_data.shape if self._raw_data is not None else None,
            "processed_data_shape": self._processed_data.shape if self._processed_data is not None else None,
            "data_quality_score": self._data_quality_report.get("quality_score", 0) if self._data_quality_report else None,
            "leakage_check_passed": self._is_fitted
        }

    def _save_output(
        self,
        train_data: pd.DataFrame,
        val_data: pd.DataFrame,
        test_data: pd.DataFrame
    ):
        """Save output to disk"""
        output_dir = Path(self.config.system.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save data files
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if len(train_data) > 0:
            train_path = output_dir / f"train_data_{timestamp}.csv"
            train_data.to_csv(train_path)
            self.logger.info(f"Saved training data: {train_path}")

        if len(val_data) > 0:
            val_path = output_dir / f"val_data_{timestamp}.csv"
            val_data.to_csv(val_path)
            self.logger.info(f"Saved validation data: {val_path}")

        if len(test_data) > 0:
            test_path = output_dir / f"test_data_{timestamp}.csv"
            test_data.to_csv(test_path)
            self.logger.info(f"Saved test data: {test_path}")

        # Save metadata
        metadata_path = output_dir / f"metadata_{timestamp}.json"
        with open(metadata_path, "w") as f:
            json.dump(self._metadata, f, indent=2, default=str)
        self.logger.info(f"Saved metadata: {metadata_path}")

        # Save config
        config_path = output_dir / f"config_{timestamp}.json"
        with open(config_path, "w") as f:
            json.dump(self.config.to_dict(), f, indent=2)
        self.logger.info(f"Saved config: {config_path}")

    def _get_factor_names(self) -> List[str]:
        """Get list of factor names"""
        if self._processed_data is None:
            return []

        factor_patterns = [
            "mom_", "ema_", "macd", "multi_mom", "mom_accel", "gap_mom", "intraday_mom",
            "zscore_", "bb_pos", "str_rev", "rsi_rev", "ma_conv", "price_pctl", "channel_rev",
            "vol_", "atr_norm", "vol_breakout", "vol_change", "vol_term", "iv_premium",
            "vol_corr", "jump_vol", "vol_anomaly", "vol_mom", "pvt", "vol_ratio", "vol_pos",
            "vol_conc", "vol_div", "order_flow_imbalance", "micro_price", "volume_profile",
            "volatility_regime"
        ]

        factor_names = []
        for col in self._processed_data.columns:
            if any(pattern in col for pattern in factor_patterns):
                factor_names.append(col)

        return factor_names

    def _get_label_names(self) -> List[str]:
        """Get list of label names"""
        if self._processed_data is None:
            return []

        label_patterns = [
            "triple_barrier_", "ret_", "log_ret_", "class_",
            "trend_label", "volatility_regime_label", "anomaly_label", "anomaly_type",
            "stop_loss_", "take_profit_"
        ]

        label_names = []
        for col in self._processed_data.columns:
            if any(pattern in col for pattern in label_patterns):
                label_names.append(col)

        return label_names

    def generate_single_symbol(
        self,
        symbol: str,
        base_dir: Optional[str] = None,
        save_output: bool = True
    ) -> pd.DataFrame:
        """
        Generate data for a single symbol (simplified mode)

        Args:
            symbol: Symbol to process
            base_dir: Base directory for data files
            save_output: Whether to save output

        Returns:
            Processed DataFrame with factors and labels
        """
        self.logger.info(f"Generating data for single symbol: {symbol}")

        # Use generate_training_data with single symbol
        result = self.generate_training_data(
            base_dir=base_dir,
            symbols=[symbol],
            split_strategy=DataSplitStrategy.FIXED_RATIO,
            save_output=save_output,
            validate_quality=True
        )

        # Combine all data
        all_data = []
        if result.train_data is not None:
            all_data.append(result.train_data)
        if result.val_data is not None:
            all_data.append(result.val_data)
        if result.test_data is not None:
            all_data.append(result.test_data)

        if all_data:
            return pd.concat(all_data).sort_index()
        else:
            return pd.DataFrame()

    def generate_multi_symbol_batch(
        self,
        symbols: List[str],
        base_dir: Optional[str] = None,
        save_output: bool = True
    ) -> Dict[str, pd.DataFrame]:
        """
        Generate data for multiple symbols

        Args:
            symbols: List of symbols to process
            base_dir: Base directory for data files
            save_output: Whether to save output

        Returns:
            Dictionary of symbol to processed DataFrame
        """
        self.logger.info(f"Generating batch data for symbols: {symbols}")

        results = {}

        for symbol in symbols:
            try:
                self.logger.info(f"\nProcessing symbol: {symbol}")
                results[symbol] = self.generate_single_symbol(
                    symbol=symbol,
                    base_dir=base_dir,
                    save_output=save_output
                )
            except Exception as e:
                self.logger.error(f"Failed to process {symbol}: {e}")
                results[symbol] = None

        return results

    def get_training_ready_data(
        self,
        df: pd.DataFrame,
        target_label: str = "triple_barrier_label",
        drop_incomplete: bool = True
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Get X and y ready for model training

        Args:
            df: Input DataFrame with factors and labels
            target_label: Target label column
            drop_incomplete: Whether to drop rows with NaN values

        Returns:
            Tuple of (X, y) DataFrames
        """
        factor_names = self._get_factor_names()

        if factor_names and target_label in df.columns:
            if drop_incomplete:
                valid_data = df[factor_names + [target_label]].dropna()
                X = valid_data[factor_names]
                y = valid_data[target_label]
            else:
                X = df[factor_names]
                y = df[target_label]

            return X, y
        else:
            return pd.DataFrame(), pd.Series()

    def print_generation_summary(self, result: DataGenerationResult):
        """Print comprehensive generation summary"""
        self.logger.info("\n" + "=" * 70)
        self.logger.info("DATA GENERATION SUMMARY")
        self.logger.info("=" * 70)

        if result.train_data is not None:
            self.logger.info(f"Train samples: {len(result.train_data)}")
        if result.val_data is not None:
            self.logger.info(f"Validation samples: {len(result.val_data)}")
        if result.test_data is not None:
            self.logger.info(f"Test samples: {len(result.test_data)}")

        if result.factor_names:
            self.logger.info(f"\nFactors: {len(result.factor_names)}")
            for i, factor in enumerate(sorted(result.factor_names)[:10]):
                self.logger.info(f"  {i+1}. {factor}")
            if len(result.factor_names) > 10:
                self.logger.info(f"  ... and {len(result.factor_names) - 10} more")

        if result.label_names:
            self.logger.info(f"\nLabels: {len(result.label_names)}")
            for label in sorted(result.label_names):
                self.logger.info(f"  - {label}")

        if result.quality_report:
            self.logger.info("\nQuality Report Available")

        self.logger.info("\n" + "=" * 70)


def main():
    """Main function for command line usage"""
    import argparse

    parser = argparse.ArgumentParser(description="Profitable Data Generator")
    parser.add_argument(
        "--symbols",
        type=str,
        nargs="+",
        default=["BTCUSDT"],
        help="Symbols to process"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data",
        help="Base directory for data files"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/money_version",
        help="Output directory"
    )
    parser.add_argument(
        "--split-strategy",
        type=str,
        choices=["time_based", "fixed_ratio", "leakage_free", "walk_forward"],
        default="leakage_free",
        help="Data split strategy (default: leakage_free)"
    )
    parser.add_argument(
        "--no-cost-aware",
        action="store_true",
        help="Disable transaction cost-aware labels"
    )
    parser.add_argument(
        "--no-lookahead-prevention",
        action="store_true",
        help="Disable look-ahead bias prevention"
    )
    parser.add_argument(
        "--no-leakage-free",
        action="store_true",
        help="Disable leakage-free data splitting"
    )
    parser.add_argument(
        "--single-symbol",
        action="store_true",
        help="Generate single symbol data only"
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process multiple symbols in batch mode"
    )
    parser.add_argument(
        "--no-validation",
        action="store_true",
        help="Skip data quality validation"
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not save output files"
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print summary only"
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Create configuration
    config = DataGeneratorConfig()
    config.system.output_dir = args.output_dir

    # Create generator
    generator = ProfitableDataGenerator(
        config=config,
        use_cost_aware_labels=not args.no_cost_aware,
        use_lookahead_prevention=not args.no_lookahead_prevention,
        use_leakage_free_split=not args.no_leakage_free
    )

    # Run appropriate mode
    if args.single_symbol:
        symbol = args.symbols[0]
        result = generator.generate_single_symbol(
            symbol=symbol,
            base_dir=args.data_dir,
            save_output=not args.no_save
        )
        print(f"Generated data for {symbol}: {len(result)} records")

    elif args.batch:
        results = generator.generate_multi_symbol_batch(
            symbols=args.symbols,
            base_dir=args.data_dir,
            save_output=not args.no_save
        )
        for symbol, data in results.items():
            if data is not None:
                print(f"{symbol}: {len(data)} records")
            else:
                print(f"{symbol}: FAILED")

    else:
        split_strategy = DataSplitStrategy(args.split_strategy)
        result = generator.generate_training_data(
            base_dir=args.data_dir,
            symbols=args.symbols,
            split_strategy=split_strategy,
            save_output=not args.no_save,
            validate_quality=not args.no_validation
        )
        generator.print_generation_summary(result)


if __name__ == "__main__":
    # Import pandas and datetime here for standalone usage
    import pandas as pd
    from datetime import datetime
    main()
