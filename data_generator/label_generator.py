"""
Label Generation Module
Institutional-grade label generation for quantitative trading
"""

import os
import sys
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass

import pandas as pd
import numpy as np

# Add project path
sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)


@dataclass
class LabelConfig:
    """Label configuration"""
    use_triple_barrier: bool = True
    upper_barrier: float = 0.005  # 0.5% profit target
    lower_barrier: float = 0.005  # 0.5% stop loss
    time_barrier: int = 12  # 12 bars (e.g., 60 minutes for 5m bars)
    use_return_label: bool = True
    use_classification_label: bool = False
    classification_threshold: float = 0.002
    time_decay_factor: float = 0.95
    volatility_adjusted: bool = True
    trend_confirmation: bool = False
    trend_confirmation_period: int = 5


class LabelGenerator:
    """Label Generator - Institutional-grade label generation"""

    def __init__(self, config: Optional[LabelConfig] = None):
        """
        Initialize label generator

        Args:
            config: Label configuration
        """
        if config is None:
            self.config = LabelConfig()
        else:
            self.config = config

        self.logger = logging.getLogger(__name__)
        self._label_functions = {
            "triple_barrier": self._generate_triple_barrier_labels,
            "return": self._generate_return_labels,
            "classification": self._generate_classification_labels,
            "trend": self._generate_trend_labels,
            "volatility_regime": self._generate_volatility_regime_labels,
            "anomaly": self._generate_anomaly_labels
        }

    def generate_all_labels(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate all configured labels

        Args:
            df: Input DataFrame with price data and factors

        Returns:
            DataFrame with all labels added
        """
        result = df.copy()

        self.logger.info("Starting label generation")

        # Generate basic labels
        if self.config.use_triple_barrier:
            result = self._generate_triple_barrier_labels(result)

        if self.config.use_return_label:
            result = self._generate_return_labels(result)

        if self.config.use_classification_label:
            result = self._generate_classification_labels(result)

        # Generate additional label types
        result = self._generate_trend_labels(result)
        result = self._generate_volatility_regime_labels(result)
        result = self._generate_anomaly_labels(result)

        self.logger.info(f"Label generation complete. Total columns: {len(result.columns)}")
        return result

    def _generate_triple_barrier_labels(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate triple barrier labels

        Reference: Advances in Financial Machine Learning by Marcos Lopez de Prado

        Args:
            df: Input DataFrame with price data

        Returns:
            DataFrame with triple barrier labels
        """
        self.logger.debug("Generating triple barrier labels")

        # Calculate barriers
        if self.config.volatility_adjusted:
            # Use realized volatility to adjust barriers
            volatility = df["close"].pct_change().rolling(20).std()
            upper_barrier = self.config.upper_barrier * volatility
            lower_barrier = -self.config.lower_barrier * volatility
        else:
            upper_barrier = self.config.upper_barrier
            lower_barrier = -self.config.lower_barrier

        # Initialize labels
        df["triple_barrier_label"] = 0.0
        df["triple_barrier_time"] = self.config.time_barrier
        df["triple_barrier_hit"] = 0.0

        # Calculate future returns for barrier detection
        for i in range(len(df) - self.config.time_barrier):
            current_price = df["close"].iloc[i]
            future_prices = df["close"].iloc[i+1:i+1+self.config.time_barrier]

            # Calculate returns
            returns = (future_prices - current_price) / current_price

            # Find if any barrier is hit
            hit_index = -1
            label = 0.0

            for j, ret in enumerate(returns):
                # Check upper barrier
                if ret >= upper_barrier.iloc[i]:
                    hit_index = j + 1
                    label = 1.0
                    break

                # Check lower barrier
                if ret <= lower_barrier.iloc[i]:
                    hit_index = j + 1
                    label = -1.0
                    break

            # Time barrier
            if hit_index == -1:
                hit_index = self.config.time_barrier
                # Label based on final return
                final_ret = returns.iloc[-1]
                if abs(final_ret) < self.config.classification_threshold:
                    label = 0.0
                else:
                    label = 1.0 if final_ret > 0 else -1.0

            df["triple_barrier_label"].iloc[i] = label
            df["triple_barrier_time"].iloc[i] = hit_index
            df["triple_barrier_hit"].iloc[i] = int(label != 0.0)

        # Trim rows without enough future data
        df = df.iloc[:-self.config.time_barrier].copy()

        self.logger.debug("Triple barrier labels generated successfully")
        return df

    def _generate_return_labels(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate return labels for regression tasks

        Args:
            df: Input DataFrame with price data

        Returns:
            DataFrame with return labels
        """
        self.logger.debug("Generating return labels")

        # Future returns for different horizons
        horizons = [1, 5, 12, 20, 60]
        for horizon in horizons:
            # Simple return
            df[f"ret_{horizon}"] = df["close"].pct_change(periods=horizon).shift(-horizon)

            # Log return (more numerically stable)
            df[f"log_ret_{horizon}"] = np.log(df["close"] / df["close"].shift(horizon)).shift(-horizon)

            # Volatility-adjusted return
            volatility = df["close"].pct_change().rolling(20).std()
            df[f"ret_{horizon}_adj"] = df[f"ret_{horizon}"] / volatility

        # Trim data
        max_horizon = max(horizons)
        df = df.iloc[:-max_horizon].copy()

        self.logger.debug("Return labels generated successfully")
        return df

    def _generate_classification_labels(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate classification labels (up/down/neutral)

        Args:
            df: Input DataFrame with price data

        Returns:
            DataFrame with classification labels
        """
        self.logger.debug("Generating classification labels")

        threshold = self.config.classification_threshold

        # Generate labels for different horizons
        horizons = [1, 5, 12, 20]
        for horizon in horizons:
            future_ret = df["close"].pct_change(periods=horizon).shift(-horizon)

            label_col = f"class_{horizon}"

            # 1 = up, -1 = down, 0 = neutral
            df[label_col] = 0.0
            df.loc[future_ret > threshold, label_col] = 1.0
            df.loc[future_ret < -threshold, label_col] = -1.0

        max_horizon = max(horizons)
        df = df.iloc[:-max_horizon].copy()

        self.logger.debug("Classification labels generated successfully")
        return df

    def _generate_trend_labels(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate trend labels

        Args:
            df: Input DataFrame with price data and factors

        Returns:
            DataFrame with trend labels
        """
        self.logger.debug("Generating trend labels")

        # Trend labels based on moving average crossovers
        df["trend_label"] = 0.0

        # Simple trend detection (up/down based on EMA)
        ema_5 = df["close"].ewm(span=5, adjust=False).mean()
        ema_20 = df["close"].ewm(span=20, adjust=False).mean()

        df.loc[ema_5 > ema_20, "trend_label"] = 1.0
        df.loc[ema_5 < ema_20, "trend_label"] = -1.0

        # Strong trend confirmation
        if self.config.trend_confirmation:
            strong_trend = (
                (ema_5 > ema_20) &
                (df["close"] > ema_20) &
                (ema_5.diff() > 0)
            )
            df.loc[strong_trend, "trend_label"] = 2.0

            strong_down_trend = (
                (ema_5 < ema_20) &
                (df["close"] < ema_20) &
                (ema_5.diff() < 0)
            )
            df.loc[strong_down_trend, "trend_label"] = -2.0

        # Trim data
        df = df.iloc[20:-self.config.time_barrier].copy()

        self.logger.debug("Trend labels generated successfully")
        return df

    def _generate_volatility_regime_labels(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate volatility regime labels (low/high volatility)

        Args:
            df: Input DataFrame with price data

        Returns:
            DataFrame with volatility regime labels
        """
        self.logger.debug("Generating volatility regime labels")

        returns = df["close"].pct_change()
        rolling_vol = returns.rolling(20).std()

        # Calculate volatility regime
        vol_percentile = rolling_vol.rolling(120).rank(pct=True)

        df["volatility_regime_label"] = 0.0
        df.loc[vol_percentile > 0.7, "volatility_regime_label"] = 1.0  # High volatility
        df.loc[vol_percentile < 0.3, "volatility_regime_label"] = -1.0  # Low volatility

        df = df.iloc[120:-self.config.time_barrier].copy()

        self.logger.debug("Volatility regime labels generated successfully")
        return df

    def _generate_anomaly_labels(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate anomaly labels (outlier detection)

        Args:
            df: Input DataFrame with price data and factors

        Returns:
            DataFrame with anomaly labels
        """
        self.logger.debug("Generating anomaly labels")

        # Simple anomaly detection using Z-scores
        returns = df["close"].pct_change()
        z_score = (returns - returns.rolling(60).mean()) / returns.rolling(60).std()

        # Define anomaly threshold (3 standard deviations)
        anomaly_threshold = 3.0

        df["anomaly_label"] = 0.0
        df.loc[z_score.abs() > anomaly_threshold, "anomaly_label"] = 1.0

        # Anomaly type classification
        df["anomaly_type"] = 0.0
        df.loc[z_score > anomaly_threshold, "anomaly_type"] = 1.0  # Positive anomaly
        df.loc[z_score < -anomaly_threshold, "anomaly_type"] = -1.0  # Negative anomaly

        df = df.iloc[60:-self.config.time_barrier].copy()

        self.logger.debug("Anomaly labels generated successfully")
        return df

    def _calculate_stop_loss_levels(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate optimal stop loss levels based on volatility

        Args:
            df: Input DataFrame with price data

        Returns:
            DataFrame with stop loss levels
        """
        self.logger.debug("Calculating stop loss levels")

        # ATR-based stop loss
        high_low = df["high"] - df["low"]
        high_close = np.abs(df["high"] - df["close"].shift())
        low_close = np.abs(df["low"] - df["close"].shift())
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = true_range.rolling(14).mean()

        # Volatility-based stop loss
        volatility = df["close"].pct_change().rolling(20).std()

        # Multiple stop loss levels (conservative, moderate, aggressive)
        df["stop_loss_05"] = df["close"] * (1 - 0.005)  # 0.5% fixed stop
        df["stop_loss_10"] = df["close"] * (1 - 0.01)   # 1.0% fixed stop
        df["stop_loss_atr"] = df["close"] - atr * 2
        df["stop_loss_vol"] = df["close"] * (1 - 2 * volatility)

        # Take profit levels
        df["take_profit_05"] = df["close"] * (1 + 0.005)
        df["take_profit_10"] = df["close"] * (1 + 0.01)
        df["take_profit_atr"] = df["close"] + atr * 2
        df["take_profit_vol"] = df["close"] * (1 + 2 * volatility)

        return df

    def validate_label_quality(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Validate label quality and provide statistics

        Returns:
            Dictionary with label quality metrics
        """
        quality_report = {}

        self.logger.info("Validating label quality")

        # Triple barrier labels quality
        if "triple_barrier_label" in df.columns:
            quality_report["triple_barrier"] = self._validate_triple_barrier_quality(df)

        # Return labels quality
        if "ret_12" in df.columns:
            quality_report["returns"] = self._validate_return_quality(df)

        # Classification labels quality
        if "class_12" in df.columns:
            quality_report["classification"] = self._validate_classification_quality(df)

        # Trend labels quality
        if "trend_label" in df.columns:
            quality_report["trend"] = self._validate_trend_quality(df)

        # Volatility regime labels quality
        if "volatility_regime_label" in df.columns:
            quality_report["volatility_regime"] = self._validate_volatility_regime_quality(df)

        # Anomaly labels quality
        if "anomaly_label" in df.columns:
            quality_report["anomaly"] = self._validate_anomaly_quality(df)

        return quality_report

    def _validate_triple_barrier_quality(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Validate triple barrier label quality"""
        labels = df["triple_barrier_label"]

        return {
            "label_distribution": labels.value_counts().to_dict(),
            "label_ratio": {
                "positive": (labels > 0).mean(),
                "negative": (labels < 0).mean(),
                "neutral": (labels == 0).mean()
            },
            "hit_rate": df["triple_barrier_hit"].mean(),
            "average_hit_time": df["triple_barrier_time"].mean(),
            "volatility_correlation": np.corrcoef(
                df["close"].pct_change().rolling(20).std(),
                labels
            )[0, 1]
        }

    def _validate_return_quality(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Validate return label quality"""
        ret_12 = df["ret_12"].dropna()

        return {
            "mean_return": ret_12.mean(),
            "std_return": ret_12.std(),
            "skewness": ret_12.skew(),
            "kurtosis": ret_12.kurt(),
            "positive_ratio": (ret_12 > 0).mean(),
            "negative_ratio": (ret_12 < 0).mean(),
            "neutral_ratio": (ret_12.abs() < self.config.classification_threshold).mean(),
            "auto_correlation": ret_12.autocorr(1)
        }

    def _validate_classification_quality(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Validate classification label quality"""
        classes = df["class_12"].dropna()

        return {
            "class_distribution": classes.value_counts().to_dict(),
            "class_ratio": {
                "up": (classes == 1).mean(),
                "down": (classes == -1).mean(),
                "neutral": (classes == 0).mean()
            },
            "entropy": self._calculate_entropy(classes),
            "pure_gain_ratio": self._calculate_pure_gain_ratio(df)
        }

    def _validate_trend_quality(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Validate trend label quality"""
        trends = df["trend_label"].dropna()

        return {
            "trend_distribution": trends.value_counts().to_dict(),
            "trend_ratio": {
                "up": (trends > 0).mean(),
                "down": (trends < 0).mean(),
                "neutral": (trends == 0).mean()
            },
            "trend_strength": trends.abs().mean(),
            "trend_consistency": self._calculate_trend_consistency(df)
        }

    def _validate_volatility_regime_quality(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Validate volatility regime label quality"""
        regimes = df["volatility_regime_label"].dropna()

        return {
            "regime_distribution": regimes.value_counts().to_dict(),
            "regime_ratio": {
                "high": (regimes == 1).mean(),
                "low": (regimes == -1).mean(),
                "normal": (regimes == 0).mean()
            },
            "regime_duration": self._calculate_regime_duration(df),
            "volatility_correlation": self._calculate_regime_volatility_correlation(df)
        }

    def _validate_anomaly_quality(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Validate anomaly label quality"""
        anomalies = df["anomaly_label"].dropna()

        return {
            "anomaly_rate": anomalies.mean(),
            "anomaly_type_distribution": df["anomaly_type"].value_counts().to_dict(),
            "anomaly_frequency": self._calculate_anomaly_frequency(df),
            "anomaly_magnitude": self._calculate_anomaly_magnitude(df)
        }

    def _calculate_entropy(self, series: pd.Series) -> float:
        """Calculate label entropy"""
        counts = series.value_counts(normalize=True)
        return -sum(counts * np.log(counts + 1e-10))

    def _calculate_pure_gain_ratio(self, df: pd.DataFrame) -> float:
        """Calculate pure gain ratio (ratio of consecutive positive/negative returns)"""
        if "ret_12" not in df.columns:
            return np.nan

        returns = df["ret_12"].dropna()
        up_count = (returns > 0).sum()
        down_count = (returns < 0).sum()
        neutral_count = (abs(returns) < self.config.classification_threshold).sum()

        total_count = len(returns)
        if total_count == 0:
            return np.nan

        # Pure gain ratio: higher is better (fewer consecutive opposite signals)
        pure_gain = 0
        previous = None
        for ret in returns:
            current = 1 if ret > 0 else (-1 if ret < 0 else 0)
            if current != 0 and current == previous:
                pure_gain += 1
            previous = current

        return pure_gain / (total_count - neutral_count) if (total_count - neutral_count) > 0 else 0

    def _calculate_trend_consistency(self, df: pd.DataFrame) -> float:
        """Calculate trend consistency (how well trend labels persist)"""
        if "trend_label" not in df.columns:
            return np.nan

        trends = df["trend_label"].dropna()
        consecutive_trends = (trends == trends.shift()).sum()
        return consecutive_trends / len(trends)

    def _calculate_regime_duration(self, df: pd.DataFrame) -> Dict[str, float]:
        """Calculate average regime duration (in bars)"""
        if "volatility_regime_label" not in df.columns:
            return {}

        regimes = df["volatility_regime_label"].dropna()
        regime_changes = regimes != regimes.shift()
        regime_starts = regime_changes[regime_changes].index

        if len(regime_starts) < 2:
            return {}

        durations = {}
        for i in range(len(regime_starts) - 1):
            start = regime_starts[i]
            end = regime_starts[i+1]
            regime = regimes.loc[start]

            # Calculate duration in number of bars (simple integer difference)
            # This avoids time calculation issues with string timestamps
            duration = end - start

            if regime not in durations:
                durations[regime] = []
            durations[regime].append(duration)

        average_durations = {
            str(k): np.mean(v)
            for k, v in durations.items()
        }

        return average_durations

    def _calculate_regime_volatility_correlation(self, df: pd.DataFrame) -> float:
        """Calculate correlation between volatility and regime labels"""
        if "volatility_regime_label" not in df.columns:
            return np.nan

        volatility = df["close"].pct_change().rolling(20).std()
        regime_labels = df["volatility_regime_label"].fillna(0)

        return np.corrcoef(volatility, regime_labels)[0, 1]

    def _calculate_anomaly_frequency(self, df: pd.DataFrame) -> float:
        """Calculate anomaly frequency"""
        if "anomaly_label" not in df.columns:
            return np.nan

        anomalies = df["anomaly_label"].dropna()
        return anomalies.sum() / len(anomalies)

    def _calculate_anomaly_magnitude(self, df: pd.DataFrame) -> Dict[str, float]:
        """Calculate anomaly magnitude statistics"""
        if "anomaly_type" not in df.columns:
            return {}

        returns = df["close"].pct_change().dropna()
        positive_anomalies = returns[df["anomaly_type"] == 1]
        negative_anomalies = returns[df["anomaly_type"] == -1]

        magnitude_stats = {}
        if len(positive_anomalies) > 0:
            magnitude_stats["positive_mean"] = positive_anomalies.mean()
            magnitude_stats["positive_std"] = positive_anomalies.std()
            magnitude_stats["positive_max"] = positive_anomalies.max()
        if len(negative_anomalies) > 0:
            magnitude_stats["negative_mean"] = negative_anomalies.mean()
            magnitude_stats["negative_std"] = negative_anomalies.std()
            magnitude_stats["negative_min"] = negative_anomalies.min()

        return magnitude_stats

    def get_label_distribution_summary(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Get comprehensive label distribution summary

        Args:
            df: DataFrame with generated labels

        Returns:
            Dictionary with distribution statistics
        """
        summary = {}

        label_columns = [
            "triple_barrier_label", "trend_label", "volatility_regime_label",
            "anomaly_label", "anomaly_type", "class_12"
        ]

        for col in label_columns:
            if col in df.columns:
                series = df[col].dropna()
                summary[col] = {
                    "count": len(series),
                    "mean": series.mean(),
                    "std": series.std(),
                    "min": series.min(),
                    "max": series.max(),
                    "value_counts": series.value_counts(normalize=True).to_dict()
                }

        return summary

    def get_feature_importance_by_label(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Calculate feature importance per label (using mutual information)

        Args:
            df: DataFrame with features and labels

        Returns:
            Dictionary with feature importance scores per label
        """
        import sklearn.feature_selection as fs

        importance_scores = {}

        # Identify feature columns
        factor_patterns = [
            "_mom_", "_zscore_", "_bb_", "_rsi_", "_ma_", "_price_", "_channel_",
            "_vol_", "_atr_", "_zscore_", "_str_", "_intraday_", "_gap_", "_multi_",
            "_jump_", "_iv_", "_vol_corr_", "_order_flow_", "_micro_", "_volume_profile_",
            "_volatility_regime_"
        ]

        feature_columns = []
        for col in df.columns:
            if any(pattern in col for pattern in factor_patterns) and col != "volatility_regime":
                feature_columns.append(col)

        # Calculate importance for each label
        label_columns = [
            ("triple_barrier_label", "triple_barrier"),
            ("class_12", "classification"),
            ("trend_label", "trend"),
            ("volatility_regime_label", "volatility_regime"),
            ("anomaly_label", "anomaly")
        ]

        for col_name, label_type in label_columns:
            if col_name in df.columns:
                features = df[feature_columns].dropna()
                labels = df[col_name].dropna()

                # Find common index
                common_index = features.index.intersection(labels.index)
                if len(common_index) < 100:
                    self.logger.warning(f"Not enough data for label {label_type}")
                    continue

                X = features.loc[common_index]
                y = labels.loc[common_index]

                # Calculate mutual information
                mutual_info = fs.mutual_info_regression(X, y)

                # Create importance dictionary
                importance = {}
                for feature, score in zip(feature_columns, mutual_info):
                    importance[feature] = score

                # Sort by importance
                importance_scores[label_type] = dict(
                    sorted(importance.items(), key=lambda x: x[1], reverse=True)
                )

        return importance_scores

    def optimize_configuration(self, df: pd.DataFrame) -> LabelConfig:
        """
        Optimize label generator configuration based on data characteristics

        Args:
            df: Input DataFrame with price data

        Returns:
            Optimized configuration
        """
        self.logger.info("Optimizing label generator configuration")

        # Calculate base volatility
        returns = df["close"].pct_change()
        base_volatility = returns.rolling(20).std()

        # Optimize barrier levels based on volatility
        optimal_upper = 0.005
        optimal_lower = 0.005

        # Adjust based on market regime
        high_volatility = base_volatility.quantile(0.7)
        if base_volatility.iloc[-1] > high_volatility:
            optimal_upper = 0.007
            optimal_lower = 0.006

        self.config.upper_barrier = optimal_upper
        self.config.lower_barrier = optimal_lower

        # Optimize classification threshold based on typical returns
        typical_ret = abs(df["ret_12"].dropna()).mean()
        self.config.classification_threshold = max(0.001, min(0.005, typical_ret * 2))

        self.logger.info(
            f"Configuration optimized: upper={optimal_upper:.3f}, lower={optimal_lower:.3f}, "
            f"threshold={self.config.classification_threshold:.4f}"
        )

        return self.config

    def print_label_quality_report(self, quality_report: Dict[str, Any]):
        """
        Print comprehensive label quality report

        Args:
            quality_report: Quality report from validate_label_quality()
        """
        self.logger.info("=" * 60)
        self.logger.info("Label Quality Report")
        self.logger.info("=" * 60)

        # Triple barrier quality
        if "triple_barrier" in quality_report:
            tb = quality_report["triple_barrier"]
            self.logger.info(f"Triple Barrier Labels:")
            self.logger.info(f"  Distribution: {tb['label_distribution']}")
            self.logger.info(f"  Positive: {tb['label_ratio']['positive']:.2%}")
            self.logger.info(f"  Negative: {tb['label_ratio']['negative']:.2%}")
            self.logger.info(f"  Neutral: {tb['label_ratio']['neutral']:.2%}")
            self.logger.info(f"  Hit Rate: {tb['hit_rate']:.2%}")
            self.logger.info(f"  Average Hit Time: {tb['average_hit_time']:.1f} bars")
            self.logger.info()

        # Return quality
        if "returns" in quality_report:
            ret = quality_report["returns"]
            self.logger.info(f"Return Labels (12-bar):")
            self.logger.info(f"  Mean: {ret['mean_return']:.4f}")
            self.logger.info(f"  Std: {ret['std_return']:.4f}")
            self.logger.info(f"  Skewness: {ret['skewness']:.3f}")
            self.logger.info(f"  Kurtosis: {ret['kurtosis']:.3f}")
            self.logger.info(f"  Positive: {ret['positive_ratio']:.2%}")
            self.logger.info(f"  Negative: {ret['negative_ratio']:.2%}")
            self.logger.info(f"  Neutral: {ret['neutral_ratio']:.2%}")
            self.logger.info(f"  Auto-correlation: {ret['auto_correlation']:.3f}")
            self.logger.info()

        # Classification quality
        if "classification" in quality_report:
            cls = quality_report["classification"]
            self.logger.info(f"Classification Labels (12-bar):")
            self.logger.info(f"  Distribution: {cls['class_distribution']}")
            self.logger.info(f"  Up: {cls['class_ratio']['up']:.2%}")
            self.logger.info(f"  Down: {cls['class_ratio']['down']:.2%}")
            self.logger.info(f"  Neutral: {cls['class_ratio']['neutral']:.2%}")
            self.logger.info(f"  Entropy: {cls['entropy']:.3f}")
            self.logger.info(f"  Pure Gain Ratio: {cls['pure_gain_ratio']:.3f}")
            self.logger.info()

        # Trend quality
        if "trend" in quality_report:
            trend = quality_report["trend"]
            self.logger.info(f"Trend Labels:")
            self.logger.info(f"  Distribution: {trend['trend_distribution']}")
            self.logger.info(f"  Up: {trend['trend_ratio']['up']:.2%}")
            self.logger.info(f"  Down: {trend['trend_ratio']['down']:.2%}")
            self.logger.info(f"  Neutral: {trend['trend_ratio']['neutral']:.2%}")
            self.logger.info(f"  Trend Strength: {trend['trend_strength']:.2f}")
            self.logger.info(f"  Consistency: {trend['trend_consistency']:.2%}")
            self.logger.info()

        # Volatility regime quality
        if "volatility_regime" in quality_report:
            regime = quality_report["volatility_regime"]
            self.logger.info(f"Volatility Regime Labels:")
            self.logger.info(f"  Distribution: {regime['regime_distribution']}")
            self.logger.info(f"  High: {regime['regime_ratio']['high']:.2%}")
            self.logger.info(f"  Low: {regime['regime_ratio']['low']:.2%}")
            self.logger.info(f"  Normal: {regime['regime_ratio']['normal']:.2%}")
            self.logger.info(f"  Correlation with Volatility: {regime['volatility_correlation']:.3f}")
            self.logger.info()

        # Anomaly quality
        if "anomaly" in quality_report:
            anomaly = quality_report["anomaly"]
            self.logger.info(f"Anomaly Labels:")
            self.logger.info(f"  Anomaly Rate: {anomaly['anomaly_rate']:.2%}")
            self.logger.info(f"  Anomaly Types: {anomaly['anomaly_type_distribution']}")
            self.logger.info()

        self.logger.info("=" * 60)


def test_label_generator():
    """Test label generator module"""
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # Create test data
    np.random.seed(42)
    dates = pd.date_range(start="2024-01-01", periods=1000, freq="5min")
    base_price = 50000
    prices = base_price + np.cumsum(np.random.randn(1000) * 100)

    df = pd.DataFrame({
        "open": prices - np.random.randn(1000) * 20,
        "high": prices + np.random.randn(1000) * 30,
        "low": prices - np.random.randn(1000) * 30,
        "close": prices,
        "volume": np.random.randint(1000, 10000, 1000)
    }, index=dates)

    # Create label generator
    config = LabelConfig(
        use_triple_barrier=True,
        upper_barrier=0.005,
        lower_barrier=0.005,
        time_barrier=12,
        use_return_label=True,
        use_classification_label=True,
        classification_threshold=0.002
    )

    generator = LabelGenerator(config)

    # Generate features first
    from data_generator.feature_engineer import FeatureEngineer
    engineer = FeatureEngineer()
    df_with_factors = engineer.calculate_all_factors(df)

    # Generate labels
    df_with_labels = generator.generate_all_labels(df_with_factors)

    logger.info(f"Data shape after label generation: {df_with_labels.shape}")
    logger.info(f"Columns: {list(df_with_labels.columns)}")

    # Validate label quality
    quality_report = generator.validate_label_quality(df_with_labels)

    # Print quality report
    generator.print_label_quality_report(quality_report)

    # Get label distribution
    distribution = generator.get_label_distribution_summary(df_with_labels)
    logger.info("Label Distribution:")
    for label, stats in distribution.items():
        logger.info(f"\n{label}:")
        for key, value in stats.items():
            if key != "value_counts":
                logger.info(f"  {key}: {value}")
            else:
                logger.info(f"  Value counts: {value}")

    # Calculate feature importance
    importance = generator.get_feature_importance_by_label(df_with_labels)
    logger.info("\nFeature Importance by Label:")
    for label_type, scores in importance.items():
        logger.info(f"\n{label_type}:")
        top_features = list(scores.keys())[:5]
        for feature in top_features:
            logger.info(f"  {feature}: {scores[feature]:.3f}")

    logger.info("\nLabel generation test complete")


if __name__ == "__main__":
    test_label_generator()
