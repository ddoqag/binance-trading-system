"""
regime_features.py - Market regime feature extraction.

Provides feature extraction for market regime detection:
- Log returns
- Realized volatility
- Price momentum
- Volume profile
"""

import numpy as np
from dataclasses import dataclass
from typing import Optional, List, Tuple
from collections import deque


@dataclass
class RegimeFeatures:
    """Features used for regime detection."""
    log_returns: np.ndarray  # Log returns series
    volatility: float  # Realized volatility
    mean_return: float  # Mean of log returns
    skewness: float  # Return skewness
    kurtosis: float  # Return kurtosis
    price_momentum: float  # Price momentum (trend strength)
    volatility_of_vol: float  # Volatility of volatility
    autocorr_1: float  # 1-lag autocorrelation


class RegimeFeatureExtractor:
    """
    Extract features from price series for regime detection.

    Features are designed to distinguish between:
    - Trending markets (persistent directional moves)
    - Mean-reverting markets (oscillating around mean)
    - High volatility markets (large price swings)
    """

    def __init__(self, window: int = 100, min_samples: int = 30):
        """
        Initialize feature extractor.

        Args:
            window: Rolling window size for feature calculation
            min_samples: Minimum samples required for valid features
        """
        self.window = window
        self.min_samples = min_samples
        self.prices: deque = deque(maxlen=window * 2)
        self.returns: deque = deque(maxlen=window * 2)

    def update(self, price: float) -> Optional[RegimeFeatures]:
        """
        Update with new price and compute features if enough data.

        Args:
            price: Latest price observation

        Returns:
            RegimeFeatures if enough data, None otherwise
        """
        if price <= 0 or not np.isfinite(price):
            return None

        self.prices.append(price)

        # Compute log return if we have previous price
        if len(self.prices) > 1:
            prev_price = list(self.prices)[-2]
            log_ret = np.log(price / prev_price)
            if np.isfinite(log_ret):
                self.returns.append(log_ret)

        # Return features if we have enough data
        if len(self.returns) >= self.min_samples:
            return self._compute_features()

        return None

    def _compute_features(self) -> RegimeFeatures:
        """Compute features from accumulated returns."""
        returns_array = np.array(list(self.returns)[-self.window:])

        # Basic statistics
        mean_ret = np.mean(returns_array)
        vol = np.std(returns_array, ddof=1)

        # Higher moments
        if len(returns_array) > 3:
            skew = self._compute_skewness(returns_array)
            kurt = self._compute_kurtosis(returns_array)
        else:
            skew = 0.0
            kurt = 3.0

        # Price momentum (trend strength)
        momentum = self._compute_momentum()

        # Volatility of volatility
        vol_of_vol = self._compute_vol_of_vol(returns_array)

        # Autocorrelation (mean reversion indicator)
        autocorr = self._compute_autocorr(returns_array)

        return RegimeFeatures(
            log_returns=returns_array,
            volatility=vol,
            mean_return=mean_ret,
            skewness=skew,
            kurtosis=kurt,
            price_momentum=momentum,
            volatility_of_vol=vol_of_vol,
            autocorr_1=autocorr
        )

    def _compute_skewness(self, x: np.ndarray) -> float:
        """Compute sample skewness."""
        n = len(x)
        if n < 3:
            return 0.0
        mean = np.mean(x)
        std = np.std(x, ddof=1)
        if std < 1e-10:
            return 0.0
        return np.sum((x - mean) ** 3) / (n * std ** 3)

    def _compute_kurtosis(self, x: np.ndarray) -> float:
        """Compute sample excess kurtosis."""
        n = len(x)
        if n < 4:
            return 0.0
        mean = np.mean(x)
        std = np.std(x, ddof=1)
        if std < 1e-10:
            return 0.0
        return np.sum((x - mean) ** 4) / (n * std ** 4) - 3.0

    def _compute_momentum(self) -> float:
        """
        Compute price momentum as slope of linear regression.

        Returns normalized slope indicating trend strength.
        """
        if len(self.prices) < self.min_samples:
            return 0.0

        prices_array = np.array(list(self.prices)[-self.window:])
        n = len(prices_array)

        # Normalize prices to percentage change from start
        normalized = prices_array / prices_array[0] - 1.0

        # Linear regression: y = a + b*x
        x = np.arange(n)
        x_mean = (n - 1) / 2
        y_mean = np.mean(normalized)

        # Slope
        numerator = np.sum((x - x_mean) * (normalized - y_mean))
        denominator = np.sum((x - x_mean) ** 2)

        if denominator < 1e-10:
            return 0.0

        slope = numerator / denominator

        # Normalize by volatility to get signal-to-noise ratio
        vol = np.std(normalized, ddof=1)
        if vol < 1e-10:
            return np.sign(slope) * 10.0  # Strong trend if no volatility

        return slope / vol

    def _compute_vol_of_vol(self, returns: np.ndarray) -> float:
        """Compute volatility of volatility (rolling std of |returns|)."""
        abs_returns = np.abs(returns)

        # Use half the window for vol of vol calculation
        sub_window = max(len(abs_returns) // 2, 10)

        vols = []
        for i in range(sub_window, len(abs_returns)):
            vols.append(np.std(abs_returns[i-sub_window:i], ddof=1))

        if len(vols) < 2:
            return 0.0

        return np.std(vols, ddof=1)

    def _compute_autocorr(self, returns: np.ndarray, lag: int = 1) -> float:
        """Compute lag-1 autocorrelation."""
        if len(returns) <= lag:
            return 0.0

        x = returns[:-lag]
        y = returns[lag:]

        x_mean = np.mean(x)
        y_mean = np.mean(y)

        numerator = np.sum((x - x_mean) * (y - y_mean))
        denominator = np.sqrt(np.sum((x - x_mean) ** 2) * np.sum((y - y_mean) ** 2))

        if denominator < 1e-10:
            return 0.0

        return numerator / denominator

    def get_feature_vector(self, features: RegimeFeatures) -> np.ndarray:
        """
        Convert RegimeFeatures to flat feature vector for ML models.

        Returns:
            Normalized feature vector of shape (7,)
        """
        # Annualize volatility for interpretability
        annualized_vol = features.volatility * np.sqrt(252 * 24 * 60)  # Assuming minute data

        return np.array([
            features.mean_return * 1000,  # Scale up small returns
            annualized_vol,
            features.skewness,
            features.kurtosis / 10.0,  # Scale down kurtosis
            features.price_momentum,
            features.volatility_of_vol * 100,
            features.autocorr_1,
        ], dtype=np.float32)

    def reset(self):
        """Reset internal state."""
        self.prices.clear()
        self.returns.clear()
