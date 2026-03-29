"""
Look-ahead Bias Prevention Module
Institutional-grade look-ahead bias prevention for factor calculation

This module ensures that factor calculations at time t only use data
available up to and including time t. This is critical for preventing
information leakage in backtesting.

Key features:
1. Rolling window calculations with proper lag
2. Warm-up period handling
3. Point-in-time factor calculation
4. Expanding window statistics from training set only
"""

import logging
from typing import Dict, Any, List, Optional, Callable, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

import pandas as pd
import numpy as np

from data_generator.utils import (
    calculate_feature_statistics,
    normalize_with_stats,
    calculate_atr,
    calculate_rsi,
    calculate_bollinger_bands,
    calculate_macd,
    calculate_ema,
    calculate_momentum
)

logger = logging.getLogger(__name__)


class CalculationMethod(Enum):
    """Factor calculation method"""
    ROLLING = "rolling"           # Rolling window (uses past N periods)
    EXPANDING = "expanding"       # Expanding window (uses all past data)
    EWM = "ewm"                   # Exponentially weighted
    POINT_IN_TIME = "pit"         # Point-in-time (no future data)


@dataclass
class FactorCalculationConfig:
    """Configuration for factor calculation with look-ahead bias prevention"""
    name: str
    calculation_method: CalculationMethod
    min_periods: int
    required_warmup: int
    params: Dict[str, Any]


class LookaheadBiasPreventer:
    """
    Look-ahead Bias Preventer

    Ensures all factor calculations are point-in-time (PIT) correct:
    - Uses only data available at calculation time
    - Proper handling of rolling/expanding windows
    - Warm-up period management
    - Training set statistics for normalization
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._training_stats: Dict[str, Dict[str, float]] = {}
        self._is_fitted = False

    def fit_training_stats(self, df: pd.DataFrame, factor_cols: List[str]):
        """
        Calculate statistics from training data only using shared utility.
        These will be used for normalization to prevent leakage.
        """
        self.logger.info("Fitting training statistics for look-ahead bias prevention")
        self._training_stats = calculate_feature_statistics(df, factor_cols)
        self._is_fitted = True
        self.logger.info(f"Fitted statistics for {len(self._training_stats)} factors")

    def normalize_with_training_stats(
        self,
        df: pd.DataFrame,
        factor_cols: List[str],
        method: str = "zscore"
    ) -> pd.DataFrame:
        """
        Normalize factors using training set statistics only.
        Prevents leakage from validation/test sets.
        """
        if not self._is_fitted:
            raise ValueError("Must call fit_training_stats() before normalization")

        return normalize_with_stats(df, self._training_stats, factor_cols, method)

    @staticmethod
    def rolling_apply(
        df: pd.DataFrame,
        column: str,
        window: int,
        func: Callable,
        min_periods: Optional[int] = None,
        shift: int = 1
    ) -> pd.Series:
        """
        Apply function with rolling window, ensuring no look-ahead bias

        The result is shifted by 1 period by default to ensure that
        the calculation at time t only uses data up to t-1

        Args:
            df: DataFrame
            column: Column to apply function to
            window: Rolling window size
            func: Function to apply (e.g., np.mean, np.std)
            min_periods: Minimum periods required
            shift: Periods to shift result (default 1 for no look-ahead)

        Returns:
            Series with rolling calculations
        """
        if min_periods is None:
            min_periods = window // 2

        rolling = df[column].rolling(window=window, min_periods=min_periods)
        result = rolling.apply(func, raw=True)

        # Shift to prevent look-ahead bias
        if shift > 0:
            result = result.shift(shift)

        return result

    @staticmethod
    def expanding_apply(
        df: pd.DataFrame,
        column: str,
        func: Callable,
        min_periods: int = 10,
        shift: int = 1
    ) -> pd.Series:
        """
        Apply function with expanding window

        Args:
            df: DataFrame
            column: Column to apply function to
            func: Function to apply
            min_periods: Minimum periods before calculation starts
            shift: Periods to shift result

        Returns:
            Series with expanding calculations
        """
        expanding = df[column].expanding(min_periods=min_periods)
        result = expanding.apply(func, raw=True)

        if shift > 0:
            result = result.shift(shift)

        return result

    @staticmethod
    def calculate_returns(
        df: pd.DataFrame,
        column: str = "close",
        periods: int = 1,
        shift: int = 1
    ) -> pd.Series:
        """
        Calculate returns with proper lag

        Args:
            df: DataFrame
            column: Price column
            periods: Return period
            shift: Additional shift (default 1 ensures no overlap with current bar)

        Returns:
            Return series
        """
        returns = df[column].pct_change(periods=periods)

        if shift > 0:
            returns = returns.shift(shift)

        return returns

    @staticmethod
    def calculate_momentum(
        df: pd.DataFrame,
        column: str = "close",
        period: int = 20,
        shift: int = 1
    ) -> pd.Series:
        """
        Calculate momentum with proper lag

        Momentum at time t = (price[t] / price[t-period] - 1)
        But we shift by 1 to ensure no look-ahead

        Args:
            df: DataFrame
            column: Price column
            period: Momentum period
            shift: Additional shift

        Returns:
            Momentum series
        """
        momentum = df[column] / df[column].shift(period) - 1

        if shift > 0:
            momentum = momentum.shift(shift)

        return momentum

    @staticmethod
    def calculate_ema(
        df: pd.DataFrame,
        column: str = "close",
        span: int = 20,
        shift: int = 1
    ) -> pd.Series:
        """
        Calculate EMA with proper lag

        Args:
            df: DataFrame
            column: Price column
            span: EMA span
            shift: Additional shift

        Returns:
            EMA series
        """
        ema = df[column].ewm(span=span, adjust=False).mean()

        if shift > 0:
            ema = ema.shift(shift)

        return ema

    @staticmethod
    def calculate_rsi(
        df: pd.DataFrame,
        column: str = "close",
        period: int = 14,
        shift: int = 1
    ) -> pd.Series:
        """
        Calculate RSI with proper lag

        Args:
            df: DataFrame
            column: Price column
            period: RSI period
            shift: Additional shift

        Returns:
            RSI series
        """
        delta = df[column].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        if shift > 0:
            rsi = rsi.shift(shift)

        return rsi

    @staticmethod
    def calculate_bollinger_bands(
        df: pd.DataFrame,
        column: str = "close",
        window: int = 20,
        num_std: float = 2.0,
        shift: int = 1
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Calculate Bollinger Bands with proper lag

        Args:
            df: DataFrame
            column: Price column
            window: Rolling window
            num_std: Number of standard deviations
            shift: Additional shift

        Returns:
            Tuple of (upper, middle, lower) bands
        """
        middle = df[column].rolling(window=window).mean()
        std = df[column].rolling(window=window).std()

        upper = middle + (std * num_std)
        lower = middle - (std * num_std)

        if shift > 0:
            upper = upper.shift(shift)
            middle = middle.shift(shift)
            lower = lower.shift(shift)

        return upper, middle, lower

    @staticmethod
    def calculate_macd(
        df: pd.DataFrame,
        column: str = "close",
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        shift: int = 1
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Calculate MACD with proper lag

        Args:
            df: DataFrame
            column: Price column
            fast: Fast EMA period
            slow: Slow EMA period
            signal: Signal line period
            shift: Additional shift

        Returns:
            Tuple of (macd, signal, histogram)
        """
        ema_fast = df[column].ewm(span=fast, adjust=False).mean()
        ema_slow = df[column].ewm(span=slow, adjust=False).mean()

        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line

        if shift > 0:
            macd_line = macd_line.shift(shift)
            signal_line = signal_line.shift(shift)
            histogram = histogram.shift(shift)

        return macd_line, signal_line, histogram

    @staticmethod
    def calculate_atr(
        df: pd.DataFrame,
        high_col: str = "high",
        low_col: str = "low",
        close_col: str = "close",
        period: int = 14,
        shift: int = 1
    ) -> pd.Series:
        """
        Calculate Average True Range with proper lag

        Args:
            df: DataFrame
            high_col: High price column
            low_col: Low price column
            close_col: Close price column
            period: ATR period
            shift: Additional shift

        Returns:
            ATR series
        """
        high_low = df[high_col] - df[low_col]
        high_close = np.abs(df[high_col] - df[close_col].shift())
        low_close = np.abs(df[low_col] - df[close_col].shift())

        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()

        if shift > 0:
            atr = atr.shift(shift)

        return atr

    def validate_no_lookahead(
        self,
        df: pd.DataFrame,
        factor_col: str,
        timestamp_col: Optional[str] = None
    ) -> bool:
        """
        Validate that a factor has no look-ahead bias

        This checks that the factor at time t doesn't correlate with
        future returns more than past returns

        Args:
            df: DataFrame
            factor_col: Factor column to validate
            timestamp_col: Timestamp column (if not index)

        Returns:
            True if no look-ahead bias detected
        """
        if factor_col not in df.columns or 'close' not in df.columns:
            return True

        # Calculate forward and backward returns
        forward_return = df['close'].shift(-1) / df['close'] - 1
        backward_return = df['close'] / df['close'].shift(1) - 1

        # Calculate correlations
        factor_forward_corr = df[factor_col].corr(forward_return)
        factor_backward_corr = df[factor_col].corr(backward_return)

        # If factor correlates more with future than past, it's suspicious
        if abs(factor_forward_corr) > abs(factor_backward_corr) * 1.5:
            self.logger.warning(
                f"Potential look-ahead bias in {factor_col}: "
                f"forward_corr={factor_forward_corr:.3f}, backward_corr={factor_backward_corr:.3f}"
            )
            return False

        return True

    def get_warmup_periods(self, factor_configs: List[FactorCalculationConfig]) -> int:
        """
        Calculate required warm-up periods for a set of factors

        Args:
            factor_configs: List of factor configurations

        Returns:
            Maximum required warm-up periods
        """
        max_warmup = 0
        for config in factor_configs:
            max_warmup = max(max_warmup, config.required_warmup)
        return max_warmup


class PITFactorCalculator:
    """
    Point-in-Time Factor Calculator

    Wrapper class that ensures all factor calculations are PIT-correct
    """

    def __init__(self, bias_preventer: Optional[LookaheadBiasPreventer] = None):
        self.bias_preventer = bias_preventer or LookaheadBiasPreventer()
        self.logger = logging.getLogger(__name__)

    def calculate_all_factors(
        self,
        df: pd.DataFrame,
        include_volume: bool = True,
        include_volatility: bool = True
    ) -> pd.DataFrame:
        """
        Calculate all standard factors with PIT correctness using shared utilities.
        """
        result = df.copy()

        # Price-based factors
        self.logger.info("Calculating PIT-correct price factors")

        # Momentum
        for period in [5, 10, 20, 60]:
            result[f'mom_{period}'] = calculate_momentum(df, period=period, shift=1)

        # EMA trends
        result['ema_10'] = calculate_ema(df, span=10, shift=1)
        result['ema_30'] = calculate_ema(df, span=30, shift=1)
        result['ema_trend'] = (result['ema_10'] / result['ema_30'] - 1).shift(1)

        # MACD
        macd, signal, hist = calculate_macd(df, shift=1)
        result['macd'] = macd
        result['macd_signal'] = signal
        result['macd_hist'] = hist

        # RSI
        result['rsi_14'] = calculate_rsi(df, period=14, shift=1)

        # Bollinger Bands
        upper, middle, lower = calculate_bollinger_bands(df, shift=1)
        result['bb_upper'] = upper
        result['bb_middle'] = middle
        result['bb_lower'] = lower
        result['bb_position'] = ((df['close'] - lower) / (upper - lower)).shift(1)

        # Volatility factors
        if include_volatility:
            self.logger.info("Calculating PIT-correct volatility factors")
            result['atr_14'] = calculate_atr(df, period=14, shift=1)
            result['volatility_20'] = df['close'].pct_change().rolling(20).std().shift(1)

        # Volume factors
        if include_volume and 'volume' in df.columns:
            self.logger.info("Calculating PIT-correct volume factors")
            result['volume_sma_20'] = df['volume'].rolling(20).mean().shift(1)
            result['volume_ratio'] = (df['volume'] / result['volume_sma_20']).shift(1)

        return result


# Convenience functions
def calculate_pit_factors(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """Quick function to calculate PIT-correct factors"""
    calculator = PITFactorCalculator()
    return calculator.calculate_all_factors(df, **kwargs)


def validate_factors_no_lookahead(
    df: pd.DataFrame,
    factor_cols: List[str]
) -> Dict[str, bool]:
    """Validate multiple factors for look-ahead bias"""
    preventer = LookaheadBiasPreventer()
    results = {}
    for col in factor_cols:
        if col in df.columns:
            results[col] = preventer.validate_no_lookahead(df, col)
    return results
