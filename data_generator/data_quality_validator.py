"""
Data Quality Validator Module
Institutional-grade data quality validation for quantitative trading

This module provides comprehensive data quality checks to ensure:
1. No duplicate timestamps
2. No price anomalies (spikes/crashes beyond thresholds)
3. OHLC logic consistency (High >= Low, Open/Close within range)
4. Volume validation (non-negative, non-zero where expected)
5. Market halt detection
6. Data gap detection (missing bars)
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class DataQualityIssue(Enum):
    """Data quality issue types"""
    DUPLICATE_TIMESTAMP = "duplicate_timestamp"
    PRICE_ANOMALY = "price_anomaly"
    OHLC_INCONSISTENCY = "ohlc_inconsistency"
    VOLUME_ANOMALY = "volume_anomaly"
    DATA_GAP = "data_gap"
    MISSING_VALUE = "missing_value"
    NEGATIVE_PRICE = "negative_price"
    ZERO_VOLUME = "zero_volume"
    SUSPICIOUS_RETURN = "suspicious_return"


@dataclass
class DataQualityReport:
    """Data quality report container"""
    is_valid: bool = True
    total_records: int = 0
    issues: Dict[DataQualityIssue, List[Dict]] = field(default_factory=dict)
    issue_counts: Dict[DataQualityIssue, int] = field(default_factory=dict)
    quality_score: float = 1.0
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    def add_issue(self, issue_type: DataQualityIssue, details: Dict):
        """Add an issue to the report"""
        if issue_type not in self.issues:
            self.issues[issue_type] = []
            self.issue_counts[issue_type] = 0
        self.issues[issue_type].append(details)
        self.issue_counts[issue_type] += 1

    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary"""
        return {
            "is_valid": self.is_valid,
            "total_records": self.total_records,
            "quality_score": self.quality_score,
            "issue_counts": {k.value: v for k, v in self.issue_counts.items()},
            "warnings": self.warnings,
            "recommendations": self.recommendations,
            "timestamp": self.timestamp.isoformat()
        }


class DataQualityValidator:
    """
    Data Quality Validator - Institutional-grade data validation

    Validates raw market data for:
    - Structural integrity (duplicates, missing values)
    - Price logic (OHLC consistency, anomalies)
    - Volume integrity (non-negative, patterns)
    - Temporal continuity (gaps, market hours)
    - Statistical anomalies (returns distribution)
    """

    def __init__(
        self,
        price_spike_threshold: float = 0.15,  # 15% price move threshold
        price_crash_threshold: float = 0.15,  # 15% price drop threshold
        max_duplicate_ratio: float = 0.001,   # 0.1% max duplicates
        max_gap_minutes: int = 60,            # Max 60 min gap
        volume_anomaly_threshold: float = 5.0, # 5x avg volume
        ohlc_tolerance: float = 0.01          # 1% tolerance for OHLC checks
    ):
        """
        Initialize data quality validator

        Args:
            price_spike_threshold: Max single-period price increase (0.15 = 15%)
            price_crash_threshold: Max single-period price decrease (0.15 = 15%)
            max_duplicate_ratio: Maximum allowed ratio of duplicate timestamps
            max_gap_minutes: Maximum allowed gap between consecutive bars
            volume_anomaly_threshold: Volume spike threshold (multiple of avg)
            ohlc_tolerance: Tolerance for OHLC consistency checks
        """
        self.price_spike_threshold = price_spike_threshold
        self.price_crash_threshold = price_crash_threshold
        self.max_duplicate_ratio = max_duplicate_ratio
        self.max_gap_minutes = max_gap_minutes
        self.volume_anomaly_threshold = volume_anomaly_threshold
        self.ohlc_tolerance = ohlc_tolerance

        self.logger = logging.getLogger(__name__)

    def validate(
        self,
        df: pd.DataFrame,
        symbol: Optional[str] = None,
        interval: Optional[str] = None
    ) -> DataQualityReport:
        """
        Run comprehensive data quality validation

        Args:
            df: Input DataFrame with OHLCV data
            symbol: Trading symbol (for logging)
            interval: Data interval (for gap detection)

        Returns:
            DataQualityReport with validation results
        """
        report = DataQualityReport()
        report.total_records = len(df)

        self.logger.info(f"Starting data quality validation for {symbol or 'unknown'}")
        self.logger.info(f"Total records: {report.total_records}")

        # Run all validation checks
        self._check_duplicates(df, report)
        self._check_missing_values(df, report)
        self._check_ohlc_consistency(df, report)
        self._check_price_anomalies(df, report)
        self._check_volume_anomalies(df, report)
        self._check_data_gaps(df, report, interval)
        self._check_suspicious_returns(df, report)

        # Calculate overall quality score
        report.quality_score = self._calculate_quality_score(report)
        report.is_valid = report.quality_score >= 0.95  # 95% threshold

        # Generate recommendations
        report.recommendations = self._generate_recommendations(report)

        self.logger.info(f"Validation complete. Quality score: {report.quality_score:.2%}")

        return report

    def _check_duplicates(self, df: pd.DataFrame, report: DataQualityReport):
        """Check for duplicate timestamps"""
        if not isinstance(df.index, pd.DatetimeIndex):
            return

        duplicates = df.index.duplicated()
        duplicate_count = duplicates.sum()

        if duplicate_count > 0:
            duplicate_ratio = duplicate_count / len(df)

            # Get sample of duplicate timestamps
            duplicate_times = df.index[duplicates][:10].tolist()

            report.add_issue(
                DataQualityIssue.DUPLICATE_TIMESTAMP,
                {
                    "count": int(duplicate_count),
                    "ratio": float(duplicate_ratio),
                    "sample_times": [str(t) for t in duplicate_times]
                }
            )

            if duplicate_ratio > self.max_duplicate_ratio:
                report.warnings.append(
                    f"High duplicate ratio: {duplicate_ratio:.2%} exceeds threshold {self.max_duplicate_ratio:.2%}"
                )

            self.logger.warning(f"Found {duplicate_count} duplicate timestamps")

    def _check_missing_values(self, df: pd.DataFrame, report: DataQualityReport):
        """Check for missing values in critical columns"""
        critical_columns = ['open', 'high', 'low', 'close', 'volume']

        for col in critical_columns:
            if col in df.columns:
                missing_count = df[col].isna().sum()
                if missing_count > 0:
                    report.add_issue(
                        DataQualityIssue.MISSING_VALUE,
                        {
                            "column": col,
                            "count": int(missing_count),
                            "ratio": float(missing_count / len(df))
                        }
                    )

    def _check_ohlc_consistency(self, df: pd.DataFrame, report: DataQualityReport):
        """Check OHLC logic consistency"""
        if not all(col in df.columns for col in ['open', 'high', 'low', 'close']):
            return

        issues = []

        # Check High >= Low
        invalid_hl = df[df['high'] < df['low']]
        if len(invalid_hl) > 0:
            issues.append({
                "type": "high_low_inversion",
                "count": len(invalid_hl),
                "samples": invalid_hl.index[:5].tolist()
            })

        # Check Open within High-Low range
        invalid_open = df[
            (df['open'] > df['high'] * (1 + self.ohlc_tolerance)) |
            (df['open'] < df['low'] * (1 - self.ohlc_tolerance))
        ]
        if len(invalid_open) > 0:
            issues.append({
                "type": "open_out_of_range",
                "count": len(invalid_open),
                "samples": invalid_open.index[:5].tolist()
            })

        # Check Close within High-Low range
        invalid_close = df[
            (df['close'] > df['high'] * (1 + self.ohlc_tolerance)) |
            (df['close'] < df['low'] * (1 - self.ohlc_tolerance))
        ]
        if len(invalid_close) > 0:
            issues.append({
                "type": "close_out_of_range",
                "count": len(invalid_close),
                "samples": invalid_close.index[:5].tolist()
            })

        # Check for negative prices
        negative_prices = df[
            (df['open'] <= 0) | (df['high'] <= 0) |
            (df['low'] <= 0) | (df['close'] <= 0)
        ]
        if len(negative_prices) > 0:
            report.add_issue(
                DataQualityIssue.NEGATIVE_PRICE,
                {
                    "count": len(negative_prices),
                    "samples": negative_prices.index[:5].tolist()
                }
            )

        if issues:
            report.add_issue(
                DataQualityIssue.OHLC_INCONSISTENCY,
                {"issues": issues}
            )

    def _check_price_anomalies(self, df: pd.DataFrame, report: DataQualityReport):
        """Check for extreme price movements"""
        if 'close' not in df.columns:
            return

        # Calculate returns
        returns = df['close'].pct_change().abs()

        # Check for price spikes
        spikes = returns[returns > self.price_spike_threshold]
        if len(spikes) > 0:
            spike_details = []
            for idx in spikes.index[:10]:  # Top 10 spikes
                spike_details.append({
                    "timestamp": str(idx),
                    "return": float(returns.loc[idx]),
                    "price": float(df.loc[idx, 'close'])
                })

            report.add_issue(
                DataQualityIssue.PRICE_ANOMALY,
                {
                    "type": "price_spike",
                    "count": len(spikes),
                    "threshold": self.price_spike_threshold,
                    "max_spike": float(returns.max()),
                    "samples": spike_details
                }
            )

            self.logger.warning(f"Found {len(spikes)} price spikes exceeding {self.price_spike_threshold:.1%}")

    def _check_volume_anomalies(self, df: pd.DataFrame, report: DataQualityReport):
        """Check for volume anomalies"""
        if 'volume' not in df.columns:
            return

        # Check for negative volume
        negative_volume = df[df['volume'] < 0]
        if len(negative_volume) > 0:
            report.add_issue(
                DataQualityIssue.VOLUME_ANOMALY,
                {
                    "type": "negative_volume",
                    "count": len(negative_volume),
                    "samples": negative_volume.index[:5].tolist()
                }
            )

        # Check for zero volume (potential market halt)
        zero_volume = df[df['volume'] == 0]
        if len(zero_volume) > 0:
            zero_ratio = len(zero_volume) / len(df)
            report.add_issue(
                DataQualityIssue.ZERO_VOLUME,
                {
                    "count": len(zero_volume),
                    "ratio": float(zero_ratio),
                    "samples": zero_volume.index[:5].tolist()
                }
            )

            if zero_ratio > 0.01:  # More than 1% zero volume
                report.warnings.append(f"High zero volume ratio: {zero_ratio:.2%}")

        # Check for volume spikes
        volume_ma = df['volume'].rolling(window=20).mean()
        volume_spikes = df[df['volume'] > volume_ma * self.volume_anomaly_threshold]

        if len(volume_spikes) > 0:
            report.add_issue(
                DataQualityIssue.VOLUME_ANOMALY,
                {
                    "type": "volume_spike",
                    "count": len(volume_spikes),
                    "threshold": self.volume_anomaly_threshold,
                    "samples": volume_spikes.index[:5].tolist()
                }
            )

    def _check_data_gaps(self, df: pd.DataFrame, report: DataQualityReport, interval: Optional[str]):
        """Check for data gaps"""
        if not isinstance(df.index, pd.DatetimeIndex) or len(df) < 2:
            return

        # Determine expected interval
        if interval:
            interval_minutes = self._parse_interval(interval)
        else:
            # Auto-detect from median diff
            median_diff = df.index.to_series().diff().median()
            interval_minutes = median_diff.total_seconds() / 60

        if interval_minutes <= 0:
            return

        # Calculate gaps
        time_diffs = df.index.to_series().diff().dropna()
        expected_diff = timedelta(minutes=interval_minutes)
        gap_threshold = expected_diff * 2  # Allow some tolerance

        gaps = time_diffs[time_diffs > gap_threshold]

        if len(gaps) > 0:
            gap_details = []
            for idx in gaps.index[:10]:
                gap_minutes = gaps.loc[idx].total_seconds() / 60
                gap_details.append({
                    "timestamp": str(idx),
                    "gap_minutes": float(gap_minutes),
                    "expected_bars_missing": int(gap_minutes / interval_minutes)
                })

            report.add_issue(
                DataQualityIssue.DATA_GAP,
                {
                    "count": len(gaps),
                    "total_gap_minutes": float(gaps.sum().total_seconds() / 60),
                    "samples": gap_details
                }
            )

            self.logger.warning(f"Found {len(gaps)} data gaps")

    def _check_suspicious_returns(self, df: pd.DataFrame, report: DataQualityReport):
        """Check for statistically suspicious return patterns"""
        if 'close' not in df.columns or len(df) < 30:
            return

        returns = df['close'].pct_change().dropna()

        if len(returns) < 30:
            return

        # Check for excessive consecutive same-direction moves
        consecutive_up = (returns > 0).astype(int).groupby(
            ((returns > 0).astype(int).diff() != 0).cumsum()
        ).cumsum()

        consecutive_down = (returns < 0).astype(int).groupby(
            ((returns < 0).astype(int).diff() != 0).cumsum()
        ).cumsum()

        max_consecutive = max(consecutive_up.max(), consecutive_down.max())

        if max_consecutive > 10:  # More than 10 consecutive moves
            report.add_issue(
                DataQualityIssue.SUSPICIOUS_RETURN,
                {
                    "type": "consecutive_moves",
                    "max_consecutive": int(max_consecutive),
                    "warning": "Possible data manipulation or stale data"
                }
            )

        # Check for zero returns (stale prices)
        zero_returns = (returns == 0).sum()
        zero_ratio = zero_returns / len(returns)

        if zero_ratio > 0.05:  # More than 5% zero returns
            report.add_issue(
                DataQualityIssue.SUSPICIOUS_RETURN,
                {
                    "type": "stale_prices",
                    "zero_return_ratio": float(zero_ratio),
                    "count": int(zero_returns)
                }
            )

    def _calculate_quality_score(self, report: DataQualityReport) -> float:
        """Calculate overall quality score"""
        if report.total_records == 0:
            return 0.0

        # Start with perfect score
        score = 1.0

        # Deduct for each issue type
        deductions = {
            DataQualityIssue.DUPLICATE_TIMESTAMP: 0.05,
            DataQualityIssue.PRICE_ANOMALY: 0.10,
            DataQualityIssue.OHLC_INCONSISTENCY: 0.15,
            DataQualityIssue.VOLUME_ANOMALY: 0.05,
            DataQualityIssue.DATA_GAP: 0.08,
            DataQualityIssue.MISSING_VALUE: 0.10,
            DataQualityIssue.NEGATIVE_PRICE: 0.20,
            DataQualityIssue.ZERO_VOLUME: 0.03,
            DataQualityIssue.SUSPICIOUS_RETURN: 0.05
        }

        for issue_type, count in report.issue_counts.items():
            if count > 0:
                # Scale deduction by issue ratio
                ratio = min(count / report.total_records, 1.0)
                score -= deductions.get(issue_type, 0.05) * ratio

        return max(score, 0.0)

    def _generate_recommendations(self, report: DataQualityReport) -> List[str]:
        """Generate recommendations based on issues found"""
        recommendations = []

        if DataQualityIssue.DUPLICATE_TIMESTAMP in report.issue_counts:
            recommendations.append(
                "Remove duplicate timestamps using df.drop_duplicates() before processing"
            )

        if DataQualityIssue.DATA_GAP in report.issue_counts:
            recommendations.append(
                "Consider forward-filling gaps or using interpolation for missing bars"
            )

        if DataQualityIssue.PRICE_ANOMALY in report.issue_counts:
            recommendations.append(
                "Review price spikes - may indicate corporate actions, splits, or data errors"
            )

        if DataQualityIssue.OHLC_INCONSISTENCY in report.issue_counts:
            recommendations.append(
                "OHLC data contains logical errors - verify data source integrity"
            )

        if DataQualityIssue.ZERO_VOLUME in report.issue_counts:
            recommendations.append(
                "High zero volume detected - check market hours and trading calendar"
            )

        if not recommendations:
            recommendations.append("Data quality is good - no immediate action required")

        return recommendations

    def _parse_interval(self, interval: str) -> float:
        """Parse interval string to minutes"""
        interval_map = {
            '1m': 1, '3m': 3, '5m': 5, '15m': 15,
            '30m': 30, '1h': 60, '2h': 120, '4h': 240,
            '6h': 360, '8h': 480, '12h': 720, '1d': 1440,
            '3d': 4320, '1w': 10080
        }
        return interval_map.get(interval, 60)  # Default to 1h

    def clean_data(
        self,
        df: pd.DataFrame,
        report: Optional[DataQualityReport] = None,
        remove_duplicates: bool = True,
        fill_gaps: bool = False,
        remove_anomalies: bool = False
    ) -> pd.DataFrame:
        """
        Clean data based on validation report

        Args:
            df: Input DataFrame
            report: Validation report (if None, will run validation)
            remove_duplicates: Whether to remove duplicate timestamps
            fill_gaps: Whether to fill data gaps
            remove_anomalies: Whether to remove anomalous records

        Returns:
            Cleaned DataFrame
        """
        if report is None:
            report = self.validate(df)

        cleaned = df.copy()

        # Remove duplicates
        if remove_duplicates and DataQualityIssue.DUPLICATE_TIMESTAMP in report.issue_counts:
            cleaned = cleaned[~cleaned.index.duplicated(keep='first')]
            self.logger.info(f"Removed duplicates, {len(cleaned)} records remaining")

        # Remove records with negative prices
        if DataQualityIssue.NEGATIVE_PRICE in report.issue_counts:
            mask = (
                (cleaned['open'] > 0) & (cleaned['high'] > 0) &
                (cleaned['low'] > 0) & (cleaned['close'] > 0)
            )
            cleaned = cleaned[mask]
            self.logger.info(f"Removed negative prices, {len(cleaned)} records remaining")

        # Sort by index
        cleaned = cleaned.sort_index()

        return cleaned


# Convenience function for quick validation
def validate_data_quality(
    df: pd.DataFrame,
    symbol: Optional[str] = None,
    interval: Optional[str] = None,
    **kwargs
) -> DataQualityReport:
    """
    Quick validation function

    Args:
        df: Input DataFrame
        symbol: Trading symbol
        interval: Data interval
        **kwargs: Additional validator parameters

    Returns:
        DataQualityReport
    """
    validator = DataQualityValidator(**kwargs)
    return validator.validate(df, symbol, interval)
