"""
Leakage-Free Data Split Module
Institutional-grade data splitting with leakage prevention

This module ensures:
1. Time-series aware splitting (no future data in training)
2. Factor calculation uses training set statistics only
3. Label generation parameters from training set only
4. Purging and embargo for overlap prevention
5. Walk-forward cross-validation support

Reference: Advances in Financial Machine Learning by Marcos Lopez de Prado
"""

import logging
from typing import Dict, Any, List, Optional, Tuple, Iterator
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

from data_generator.utils import (
    calculate_feature_statistics,
    normalize_with_stats,
    validate_no_index_overlap
)

logger = logging.getLogger(__name__)


class SplitType(Enum):
    """Data split types"""
    TIME_BASED = "time_based"           # Simple time-based split
    WALK_FORWARD = "walk_forward"       # Walk-forward analysis
    PURGED_K_FOLD = "purged_k_fold"     # Purged k-fold CV
    COMBINATORIAL = "combinatorial"     # Combinatorial CV


@dataclass
class SplitConfig:
    """Configuration for data splitting"""
    split_type: SplitType = SplitType.TIME_BASED
    train_ratio: float = 0.7
    val_ratio: float = 0.15
    test_ratio: float = 0.15

    # Purging and embargo parameters
    purge_gap: int = 10                 # Bars to purge between train/test
    embargo_pct: float = 0.01           # % of test set to embargo

    # Walk-forward parameters
    n_splits: int = 5                   # Number of splits for CV
    min_train_size: int = 1000          # Minimum training set size
    step_size: int = 500                # Step size for walk-forward

    # Time-based split dates (optional)
    train_end_date: Optional[datetime] = None
    val_end_date: Optional[datetime] = None


@dataclass
class DataSplit:
    """Container for a single data split"""
    train_idx: pd.DatetimeIndex
    val_idx: pd.DatetimeIndex
    test_idx: pd.DatetimeIndex
    split_info: Dict[str, Any]


class LeakageFreeSplitter:
    """
    Leakage-Free Data Splitter

    Implements institutional-grade data splitting that prevents:
    - Look-ahead bias in train/test separation
    - Overlap between sets (purging)
    - Information leakage from overlapping outcomes (embargo)
    """

    def __init__(self, config: Optional[SplitConfig] = None):
        """
        Initialize leakage-free splitter

        Args:
            config: Split configuration
        """
        self.config = config or SplitConfig()
        self.logger = logging.getLogger(__name__)

    def split(
        self,
        df: pd.DataFrame,
        labels: Optional[pd.Series] = None
    ) -> DataSplit:
        """
        Perform leakage-free data split

        Args:
            df: DataFrame with datetime index
            labels: Optional label series (for purging)

        Returns:
            DataSplit with train/val/test indices
        """
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError("DataFrame must have DatetimeIndex")

        if self.config.split_type == SplitType.TIME_BASED:
            return self._time_based_split(df)
        elif self.config.split_type == SplitType.WALK_FORWARD:
            raise NotImplementedError("Use split_walk_forward() for walk-forward splits")
        elif self.config.split_type == SplitType.PURGED_K_FOLD:
            raise NotImplementedError("Use split_purged_kfold() for purged k-fold")
        else:
            raise ValueError(f"Unknown split type: {self.config.split_type}")

    def _time_based_split(self, df: pd.DataFrame) -> DataSplit:
        """
        Simple time-based split with purging

        Args:
            df: DataFrame with datetime index

        Returns:
            DataSplit
        """
        n = len(df)
        indices = df.index

        # Calculate split points
        train_end = int(n * self.config.train_ratio)
        val_end = int(n * (self.config.train_ratio + self.config.val_ratio))

        # Initial split
        train_idx = indices[:train_end]
        val_idx = indices[train_end:val_end]
        test_idx = indices[val_end:]

        # Apply purging (remove overlap periods)
        if self.config.purge_gap > 0:
            purge_delta = pd.Timedelta(minutes=self.config.purge_gap * 5)  # Assuming 5-min bars

            # Purge train end
            train_end_time = train_idx[-1] - purge_delta
            train_idx = train_idx[train_idx <= train_end_time]

            # Purge val end
            if len(val_idx) > 0:
                val_end_time = val_idx[-1] - purge_delta
                val_idx = val_idx[val_idx <= val_end_time]

        # Apply embargo to test set
        if self.config.embargo_pct > 0 and len(test_idx) > 0:
            embargo_n = max(1, int(len(test_idx) * self.config.embargo_pct))
            test_idx = test_idx[embargo_n:]

        self.logger.info(
            f"Time-based split: train={len(train_idx)}, val={len(val_idx)}, test={len(test_idx)}"
        )

        return DataSplit(
            train_idx=train_idx,
            val_idx=val_idx,
            test_idx=test_idx,
            split_info={
                "type": "time_based",
                "train_start": str(train_idx[0]),
                "train_end": str(train_idx[-1]),
                "val_start": str(val_idx[0]) if len(val_idx) > 0 else None,
                "val_end": str(val_idx[-1]) if len(val_idx) > 0 else None,
                "test_start": str(test_idx[0]) if len(test_idx) > 0 else None,
                "test_end": str(test_idx[-1]) if len(test_idx) > 0 else None,
                "purge_gap": self.config.purge_gap,
                "embargo_pct": self.config.embargo_pct
            }
        )

    def split_walk_forward(
        self,
        df: pd.DataFrame,
        labels: Optional[pd.Series] = None
    ) -> Iterator[DataSplit]:
        """
        Generate walk-forward splits

        This is the gold standard for financial time series backtesting.
        Each split uses only past data for training and evaluates on future data.

        Args:
            df: DataFrame with datetime index
            labels: Optional label series

        Yields:
            DataSplit for each walk-forward step
        """
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError("DataFrame must have DatetimeIndex")

        n = len(df)
        indices = df.index

        min_train = self.config.min_train_size
        step = self.config.step_size

        # Generate splits
        start_idx = min_train
        split_num = 0

        while start_idx + step <= n:
            # Training set: from beginning to start_idx
            train_end = start_idx

            # Validation set: next step_size
            val_end = min(start_idx + step, n)

            # Test set: next step_size after validation (or use val as test for now)
            test_end = min(val_end + step, n)

            train_idx = indices[:train_end]
            val_idx = indices[train_end:val_end]
            test_idx = indices[val_end:test_end]

            # Apply purging
            if self.config.purge_gap > 0 and len(train_idx) > self.config.purge_gap:
                train_idx = train_idx[:-self.config.purge_gap]

            split_num += 1

            self.logger.info(
                f"Walk-forward split {split_num}: train={len(train_idx)}, "
                f"val={len(val_idx)}, test={len(test_idx)}"
            )

            yield DataSplit(
                train_idx=train_idx,
                val_idx=val_idx,
                test_idx=test_idx,
                split_info={
                    "type": "walk_forward",
                    "split_num": split_num,
                    "train_start": str(train_idx[0]),
                    "train_end": str(train_idx[-1]),
                    "test_start": str(test_idx[0]) if len(test_idx) > 0 else None,
                    "test_end": str(test_idx[-1]) if len(test_idx) > 0 else None
                }
            )

            start_idx += step

    def split_purged_kfold(
        self,
        df: pd.DataFrame,
        labels: pd.Series,
        n_splits: int = 5
    ) -> Iterator[DataSplit]:
        """
        Purged k-fold cross-validation

        Implements the purged k-fold method from Lopez de Prado (2018).
        Removes overlapping periods between train and test to prevent leakage.

        Args:
            df: DataFrame with datetime index
            labels: Label series (used to determine overlap)
            n_splits: Number of folds

        Yields:
            DataSplit for each fold
        """
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError("DataFrame must have DatetimeIndex")

        n = len(df)
        fold_size = n // n_splits

        for i in range(n_splits):
            # Define test set
            test_start = i * fold_size
            test_end = min((i + 1) * fold_size, n)

            test_idx = df.index[test_start:test_end]

            # Define train set (everything except test)
            train_idx_before = df.index[:test_start]
            train_idx_after = df.index[test_end:]

            # Apply purging to remove overlap
            if self.config.purge_gap > 0:
                if len(train_idx_before) > self.config.purge_gap:
                    train_idx_before = train_idx_before[:-self.config.purge_gap]
                if len(train_idx_after) > self.config.purge_gap:
                    train_idx_after = train_idx_after[self.config.purge_gap:]

            train_idx = train_idx_before.append(train_idx_after)

            # Empty val set for k-fold
            val_idx = pd.DatetimeIndex([])

            self.logger.info(
                f"Purged k-fold split {i+1}/{n_splits}: train={len(train_idx)}, test={len(test_idx)}"
            )

            yield DataSplit(
                train_idx=train_idx,
                val_idx=val_idx,
                test_idx=test_idx,
                split_info={
                    "type": "purged_k_fold",
                    "fold": i + 1,
                    "total_folds": n_splits
                }
            )

    def get_train_statistics(
        self,
        df: pd.DataFrame,
        train_idx: pd.DatetimeIndex,
        factor_cols: List[str]
    ) -> Dict[str, Dict[str, float]]:
        """
        Calculate statistics from training set only using shared utility.

        These statistics should be used for normalization to prevent leakage.
        """
        train_data = df.loc[train_idx]
        return calculate_feature_statistics(train_data, factor_cols)

    def normalize_with_train_stats(
        self,
        df: pd.DataFrame,
        train_idx: pd.DatetimeIndex,
        factor_cols: List[str],
        method: str = "zscore"
    ) -> pd.DataFrame:
        """
        Normalize factors using training set statistics only.
        """
        stats = self.get_train_statistics(df, train_idx, factor_cols)
        return normalize_with_stats(df, stats, factor_cols, method)

    def verify_no_leakage(
        self,
        train_idx: pd.DatetimeIndex,
        test_idx: pd.DatetimeIndex,
        labels: Optional[pd.Series] = None
    ) -> bool:
        """
        Verify that there is no data leakage between train and test.
        """
        # Check for index overlap using shared utility
        if not validate_no_index_overlap(train_idx, test_idx):
            overlap = train_idx.intersection(test_idx)
            self.logger.error(f"Data leakage detected: {len(overlap)} overlapping indices")
            return False

        # Check temporal ordering
        if len(train_idx) > 0 and len(test_idx) > 0:
            if train_idx.max() >= test_idx.min():
                self.logger.warning(
                    "Potential leakage: train data extends into test period"
                )
                return False

        self.logger.info("No data leakage detected")
        return True


class CrossValidator:
    """
    Cross-validation with leakage prevention

    Wraps the LeakageFreeSplitter to provide sklearn-compatible interface
    """

    def __init__(self, split_config: Optional[SplitConfig] = None):
        self.splitter = LeakageFreeSplitter(split_config)
        self.logger = logging.getLogger(__name__)

    def time_series_split(
        self,
        X: pd.DataFrame,
        y: Optional[pd.Series] = None
    ) -> Iterator[Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]]:
        """
        Generate time-series splits for cross-validation

        Args:
            X: Feature DataFrame
            y: Target series

        Yields:
            Tuple of (X_train, X_test, y_train, y_test)
        """
        for split in self.splitter.split_walk_forward(X, y):
            X_train = X.loc[split.train_idx]
            X_test = X.loc[split.test_idx]
            y_train = y.loc[split.train_idx] if y is not None else None
            y_test = y.loc[split.test_idx] if y is not None else None

            yield X_train, X_test, y_train, y_test


# Convenience functions
def create_leakage_free_split(
    df: pd.DataFrame,
    train_ratio: float = 0.7,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
    purge_gap: int = 10
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Quick function to create leakage-free split

    Args:
        df: DataFrame with datetime index
        train_ratio: Training set ratio
        val_ratio: Validation set ratio
        test_ratio: Test set ratio
        purge_gap: Purge gap in bars

    Returns:
        Tuple of (train_df, val_df, test_df)
    """
    config = SplitConfig(
        split_type=SplitType.TIME_BASED,
        train_ratio=train_ratio,
        val_ratio=val_ratio,
        test_ratio=test_ratio,
        purge_gap=purge_gap
    )

    splitter = LeakageFreeSplitter(config)
    split = splitter.split(df)

    train_df = df.loc[split.train_idx]
    val_df = df.loc[split.val_idx]
    test_df = df.loc[split.test_idx]

    return train_df, val_df, test_df


def normalize_leakage_free(
    df: pd.DataFrame,
    train_df: pd.DataFrame,
    factor_cols: List[str],
    method: str = "zscore"
) -> pd.DataFrame:
    """
    Normalize using training statistics only.

    This convenience function delegates to shared utilities to avoid code duplication.
    """
    stats = calculate_feature_statistics(train_df, factor_cols)
    return normalize_with_stats(df, stats, factor_cols, method)
