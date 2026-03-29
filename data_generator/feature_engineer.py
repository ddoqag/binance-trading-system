"""
Feature Engineering Module
Institutional-grade Alpha factor calculation
"""

import os
import sys
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

import pandas as pd
import numpy as np

# Add project path
sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)


class FactorCategory(Enum):
    """Factor category enum"""
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    VOLATILITY = "volatility"
    VOLUME = "volume"
    CROSS_ASSET = "cross_asset"
    ORDER_FLOW = "order_flow"


@dataclass
class FactorConfig:
    """Factor configuration"""
    name: str
    category: FactorCategory
    function: str
    params: Dict[str, Any] = None
    enabled: bool = True

    def __post_init__(self):
        if self.params is None:
            self.params = {}


class FeatureEngineer:
    """Feature Engineer - Institutional-grade Alpha factor calculation"""

    def __init__(self, config=None):
        """
        Initialize feature engineer

        Args:
            config: Configuration object
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._factor_registry = self._register_factors()

    def _register_factors(self) -> Dict[str, FactorConfig]:
        """Register all available factors"""
        factors = {}

        # Momentum factors (8 factors)
        factors.update({
            "mom_20": FactorConfig(
                name="mom_20",
                category=FactorCategory.MOMENTUM,
                function="_calculate_momentum",
                params={"period": 20}
            ),
            "mom_60": FactorConfig(
                name="mom_60",
                category=FactorCategory.MOMENTUM,
                function="_calculate_momentum",
                params={"period": 60}
            ),
            "ema_trend": FactorConfig(
                name="ema_trend",
                category=FactorCategory.MOMENTUM,
                function="_calculate_ema_trend",
                params={"fast_period": 10, "slow_period": 30}
            ),
            "macd": FactorConfig(
                name="macd",
                category=FactorCategory.MOMENTUM,
                function="_calculate_macd",
                params={"fast_period": 12, "slow_period": 26, "signal_period": 9}
            ),
            "multi_mom": FactorConfig(
                name="multi_mom",
                category=FactorCategory.MOMENTUM,
                function="_calculate_multi_period_momentum",
                params={"periods": [5, 10, 20, 60]}
            ),
            "mom_accel": FactorConfig(
                name="mom_accel",
                category=FactorCategory.MOMENTUM,
                function="_calculate_momentum_acceleration",
                params={"period": 20}
            ),
            "gap_mom": FactorConfig(
                name="gap_mom",
                category=FactorCategory.MOMENTUM,
                function="_calculate_gap_momentum",
                params={"lookback": 5}
            ),
            "intraday_mom": FactorConfig(
                name="intraday_mom",
                category=FactorCategory.MOMENTUM,
                function="_calculate_intraday_momentum",
                params={}
            )
        })

        # Mean reversion factors (7 factors)
        factors.update({
            "zscore_20": FactorConfig(
                name="zscore_20",
                category=FactorCategory.MEAN_REVERSION,
                function="_calculate_zscore",
                params={"period": 20}
            ),
            "bb_pos": FactorConfig(
                name="bb_pos",
                category=FactorCategory.MEAN_REVERSION,
                function="_calculate_bollinger_position",
                params={"period": 20, "std_dev": 2}
            ),
            "str_rev": FactorConfig(
                name="str_rev",
                category=FactorCategory.MEAN_REVERSION,
                function="_calculate_short_term_reversal",
                params={"period": 5}
            ),
            "rsi_rev": FactorConfig(
                name="rsi_rev",
                category=FactorCategory.MEAN_REVERSION,
                function="_calculate_rsi_reversal",
                params={"period": 14, "overbought": 70, "oversold": 30}
            ),
            "ma_conv": FactorConfig(
                name="ma_conv",
                category=FactorCategory.MEAN_REVERSION,
                function="_calculate_ma_convergence",
                params={"periods": [5, 10, 20]}
            ),
            "price_pctl": FactorConfig(
                name="price_pctl",
                category=FactorCategory.MEAN_REVERSION,
                function="_calculate_price_percentile",
                params={"period": 60}
            ),
            "channel_rev": FactorConfig(
                name="channel_rev",
                category=FactorCategory.MEAN_REVERSION,
                function="_calculate_channel_reversal",
                params={"period": 20}
            )
        })

        # Volatility factors (8 factors)
        factors.update({
            "vol_20": FactorConfig(
                name="vol_20",
                category=FactorCategory.VOLATILITY,
                function="_calculate_realized_volatility",
                params={"period": 20}
            ),
            "atr_norm": FactorConfig(
                name="atr_norm",
                category=FactorCategory.VOLATILITY,
                function="_calculate_normalized_atr",
                params={"period": 14}
            ),
            "vol_breakout": FactorConfig(
                name="vol_breakout",
                category=FactorCategory.VOLATILITY,
                function="_calculate_volatility_breakout",
                params={"period": 20, "threshold": 1.5}
            ),
            "vol_change": FactorConfig(
                name="vol_change",
                category=FactorCategory.VOLATILITY,
                function="_calculate_volatility_change",
                params={"period": 20}
            ),
            "vol_term": FactorConfig(
                name="vol_term",
                category=FactorCategory.VOLATILITY,
                function="_calculate_volatility_term_structure",
                params={"periods": [5, 20, 60]}
            ),
            "iv_premium": FactorConfig(
                name="iv_premium",
                category=FactorCategory.VOLATILITY,
                function="_calculate_implied_volatility_premium",
                params={"period": 20}
            ),
            "vol_corr": FactorConfig(
                name="vol_corr",
                category=FactorCategory.VOLATILITY,
                function="_calculate_volatility_correlation",
                params={"period": 60}
            ),
            "jump_vol": FactorConfig(
                name="jump_vol",
                category=FactorCategory.VOLATILITY,
                function="_calculate_jump_volatility",
                params={"period": 20, "jump_threshold": 3}
            )
        })

        # Volume factors (7 factors)
        factors.update({
            "vol_anomaly": FactorConfig(
                name="vol_anomaly",
                category=FactorCategory.VOLUME,
                function="_calculate_volume_anomaly",
                params={"period": 20}
            ),
            "vol_mom": FactorConfig(
                name="vol_mom",
                category=FactorCategory.VOLUME,
                function="_calculate_volume_momentum",
                params={"period": 10}
            ),
            "pvt": FactorConfig(
                name="pvt",
                category=FactorCategory.VOLUME,
                function="_calculate_price_volume_trend",
                params={}
            ),
            "vol_ratio": FactorConfig(
                name="vol_ratio",
                category=FactorCategory.VOLUME,
                function="_calculate_volume_ratio",
                params={"period": 20}
            ),
            "vol_pos": FactorConfig(
                name="vol_pos",
                category=FactorCategory.VOLUME,
                function="_calculate_volume_position",
                params={"period": 60}
            ),
            "vol_conc": FactorConfig(
                name="vol_conc",
                category=FactorCategory.VOLUME,
                function="_calculate_volume_concentration",
                params={"period": 20}
            ),
            "vol_div": FactorConfig(
                name="vol_div",
                category=FactorCategory.VOLUME,
                function="_calculate_volume_divergence",
                params={"period": 14}
            )
        })

        # Order flow factors (4 factors)
        factors.update({
            "order_flow_imbalance": FactorConfig(
                name="order_flow_imbalance",
                category=FactorCategory.ORDER_FLOW,
                function="_calculate_order_flow_imbalance",
                params={"period": 5}
            ),
            "micro_price": FactorConfig(
                name="micro_price",
                category=FactorCategory.ORDER_FLOW,
                function="_calculate_micro_price",
                params={}
            ),
            "volume_profile": FactorConfig(
                name="volume_profile",
                category=FactorCategory.ORDER_FLOW,
                function="_calculate_volume_profile",
                params={"period": 60, "bins": 10}
            ),
            "volatility_regime": FactorConfig(
                name="volatility_regime",
                category=FactorCategory.ORDER_FLOW,
                function="_calculate_volatility_regime",
                params={"period": 60, "regime_threshold": 0.5}
            )
        })

        return factors

    def calculate_all_factors(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate all enabled factors

        Args:
            df: Input DataFrame with OHLCV data

        Returns:
            DataFrame with all factors added
        """
        result = df.copy()

        self.logger.info("Starting factor calculation")

        for factor_name, factor_config in self._factor_registry.items():
            if not factor_config.enabled:
                continue

            try:
                factor_func = getattr(self, factor_config.function)
                result = factor_func(result, **factor_config.params)
                self.logger.debug(f"Calculated factor: {factor_name}")
            except Exception as e:
                self.logger.error(f"Failed to calculate factor {factor_name}: {e}")

        self.logger.info(f"Factor calculation complete. Total columns: {len(result.columns)}")
        return result

    def calculate_factors_by_category(
        self,
        df: pd.DataFrame,
        categories: List[FactorCategory]
    ) -> pd.DataFrame:
        """
        Calculate factors by category

        Args:
            df: Input DataFrame
            categories: List of factor categories to calculate

        Returns:
            DataFrame with factors
        """
        result = df.copy()

        for factor_name, factor_config in self._factor_registry.items():
            if factor_config.category in categories and factor_config.enabled:
                try:
                    factor_func = getattr(self, factor_config.function)
                    result = factor_func(result, **factor_config.params)
                except Exception as e:
                    self.logger.error(f"Failed to calculate factor {factor_name}: {e}")

        return result

    def calculate_specific_factors(
        self,
        df: pd.DataFrame,
        factor_names: List[str]
    ) -> pd.DataFrame:
        """
        Calculate specific factors by name

        Args:
            df: Input DataFrame
            factor_names: List of factor names to calculate

        Returns:
            DataFrame with factors
        """
        result = df.copy()

        for factor_name in factor_names:
            if factor_name in self._factor_registry:
                factor_config = self._factor_registry[factor_name]
                if factor_config.enabled:
                    try:
                        factor_func = getattr(self, factor_config.function)
                        result = factor_func(result, **factor_config.params)
                    except Exception as e:
                        self.logger.error(f"Failed to calculate factor {factor_name}: {e}")

        return result

    # ==================== MOMENTUM FACTORS ====================

    def _calculate_momentum(self, df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        """Calculate simple momentum"""
        col_name = f"mom_{period}"
        df[col_name] = df["close"].pct_change(period)
        return df

    def _calculate_ema_trend(
        self,
        df: pd.DataFrame,
        fast_period: int = 10,
        slow_period: int = 30
    ) -> pd.DataFrame:
        """Calculate EMA trend indicator"""
        ema_fast = df["close"].ewm(span=fast_period, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow_period, adjust=False).mean()
        df["ema_trend"] = (ema_fast - ema_slow) / ema_slow
        return df

    def _calculate_macd(
        self,
        df: pd.DataFrame,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9
    ) -> pd.DataFrame:
        """Calculate MACD indicator"""
        ema_fast = df["close"].ewm(span=fast_period, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow_period, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
        df["macd"] = macd_line - signal_line
        return df

    def _calculate_multi_period_momentum(
        self,
        df: pd.DataFrame,
        periods: List[int] = None
    ) -> pd.DataFrame:
        """Calculate multi-period momentum composite"""
        if periods is None:
            periods = [5, 10, 20, 60]

        momentums = []
        for period in periods:
            mom = df["close"].pct_change(period)
            momentums.append(mom)

        df["multi_mom"] = pd.concat(momentums, axis=1).mean(axis=1)
        return df

    def _calculate_momentum_acceleration(
        self,
        df: pd.DataFrame,
        period: int = 20
    ) -> pd.DataFrame:
        """Calculate momentum acceleration (second derivative)"""
        mom = df["close"].pct_change(period)
        df["mom_accel"] = mom.diff()
        return df

    def _calculate_gap_momentum(
        self,
        df: pd.DataFrame,
        lookback: int = 5
    ) -> pd.DataFrame:
        """Calculate gap momentum"""
        gap_up = (df["open"] > df["close"].shift(1)).astype(int)
        gap_down = (df["open"] < df["close"].shift(1)).astype(int)
        df["gap_mom"] = gap_up.rolling(lookback).sum() - gap_down.rolling(lookback).sum()
        return df

    def _calculate_intraday_momentum(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate intraday momentum"""
        df["intraday_mom"] = (df["close"] - df["open"]) / df["open"]
        return df

    # ==================== MEAN REVERSION FACTORS ====================

    def _calculate_zscore(self, df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        """Calculate Z-score for mean reversion"""
        rolling_mean = df["close"].rolling(window=period).mean()
        rolling_std = df["close"].rolling(window=period).std()
        df[f"zscore_{period}"] = (df["close"] - rolling_mean) / rolling_std
        return df

    def _calculate_bollinger_position(
        self,
        df: pd.DataFrame,
        period: int = 20,
        std_dev: float = 2
    ) -> pd.DataFrame:
        """Calculate Bollinger Band position"""
        rolling_mean = df["close"].rolling(window=period).mean()
        rolling_std = df["close"].rolling(window=period).std()
        upper_band = rolling_mean + std_dev * rolling_std
        lower_band = rolling_mean - std_dev * rolling_std
        df["bb_pos"] = (df["close"] - lower_band) / (upper_band - lower_band)
        return df

    def _calculate_short_term_reversal(
        self,
        df: pd.DataFrame,
        period: int = 5
    ) -> pd.DataFrame:
        """Calculate short-term reversal factor"""
        df["str_rev"] = -df["close"].pct_change(period)
        return df

    def _calculate_rsi_reversal(
        self,
        df: pd.DataFrame,
        period: int = 14,
        overbought: float = 70,
        oversold: float = 30
    ) -> pd.DataFrame:
        """Calculate RSI reversal indicator"""
        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        df["rsi_rev"] = 0.0
        df.loc[rsi > overbought, "rsi_rev"] = -1  # Overbought, short signal
        df.loc[rsi < oversold, "rsi_rev"] = 1    # Oversold, long signal
        return df

    def _calculate_ma_convergence(
        self,
        df: pd.DataFrame,
        periods: List[int] = None
    ) -> pd.DataFrame:
        """Calculate moving average convergence"""
        if periods is None:
            periods = [5, 10, 20]

        emas = []
        for period in periods:
            ema = df["close"].ewm(span=period, adjust=False).mean()
            emas.append(ema / df["close"] - 1)

        df["ma_conv"] = pd.concat(emas, axis=1).std(axis=1)
        return df

    def _calculate_price_percentile(
        self,
        df: pd.DataFrame,
        period: int = 60
    ) -> pd.DataFrame:
        """Calculate price percentile in lookback window"""
        def percentile_rank(x):
            return pd.Series(x).rank(pct=True).iloc[-1]

        df["price_pctl"] = df["close"].rolling(window=period).apply(percentile_rank)
        return df

    def _calculate_channel_reversal(
        self,
        df: pd.DataFrame,
        period: int = 20
    ) -> pd.DataFrame:
        """Calculate channel reversal factor"""
        rolling_high = df["high"].rolling(window=period).max()
        rolling_low = df["low"].rolling(window=period).min()
        df["channel_rev"] = (df["close"] - rolling_low) / (rolling_high - rolling_low)
        return df

    # ==================== VOLATILITY FACTORS ====================

    def _calculate_realized_volatility(
        self,
        df: pd.DataFrame,
        period: int = 20
    ) -> pd.DataFrame:
        """Calculate realized volatility"""
        returns = df["close"].pct_change()
        df[f"vol_{period}"] = returns.rolling(window=period).std() * np.sqrt(365)
        return df

    def _calculate_normalized_atr(
        self,
        df: pd.DataFrame,
        period: int = 14
    ) -> pd.DataFrame:
        """Calculate normalized ATR"""
        high_low = df["high"] - df["low"]
        high_close = np.abs(df["high"] - df["close"].shift())
        low_close = np.abs(df["low"] - df["close"].shift())
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = true_range.rolling(window=period).mean()
        df["atr_norm"] = atr / df["close"]
        return df

    def _calculate_volatility_breakout(
        self,
        df: pd.DataFrame,
        period: int = 20,
        threshold: float = 1.5
    ) -> pd.DataFrame:
        """Calculate volatility breakout"""
        returns = df["close"].pct_change()
        rolling_vol = returns.rolling(window=period).std()
        df["vol_breakout"] = (returns.abs() > threshold * rolling_vol).astype(int)
        return df

    def _calculate_volatility_change(
        self,
        df: pd.DataFrame,
        period: int = 20
    ) -> pd.DataFrame:
        """Calculate volatility change"""
        returns = df["close"].pct_change()
        rolling_vol = returns.rolling(window=period).std()
        df["vol_change"] = rolling_vol.pct_change(period)
        return df

    def _calculate_volatility_term_structure(
        self,
        df: pd.DataFrame,
        periods: List[int] = None
    ) -> pd.DataFrame:
        """Calculate volatility term structure"""
        if periods is None:
            periods = [5, 20, 60]

        returns = df["close"].pct_change()
        vols = {}
        for period in periods:
            vols[f"vol_{period}"] = returns.rolling(window=period).std()

        df["vol_term"] = vols[f"vol_{periods[0]}"] / vols[f"vol_{periods[-1]}"]
        return df

    def _calculate_implied_volatility_premium(
        self,
        df: pd.DataFrame,
        period: int = 20
    ) -> pd.DataFrame:
        """Calculate IV premium proxy (using realized volatility)"""
        returns = df["close"].pct_change()
        realized_vol = returns.rolling(window=period).std()
        # Simple proxy: use change in realized vol as "IV" premium
        df["iv_premium"] = realized_vol.pct_change(period)
        return df

    def _calculate_volatility_correlation(
        self,
        df: pd.DataFrame,
        period: int = 60
    ) -> pd.DataFrame:
        """Calculate price-volatility correlation"""
        returns = df["close"].pct_change()
        rolling_vol = returns.rolling(window=period).std()

        def corr_window(x):
            if len(x) < 10:
                return np.nan
            return np.corrcoef(x[:-1], x[1:])[0, 1]

        df["vol_corr"] = rolling_vol.rolling(window=period).apply(corr_window)
        return df

    def _calculate_jump_volatility(
        self,
        df: pd.DataFrame,
        period: int = 20,
        jump_threshold: float = 3
    ) -> pd.DataFrame:
        """Calculate jump volatility component"""
        returns = df["close"].pct_change()
        rolling_vol = returns.rolling(window=period).std()
        jump_returns = returns[returns.abs() > jump_threshold * rolling_vol]
        df["jump_vol"] = jump_returns.rolling(window=period).std()
        return df

    # ==================== VOLUME FACTORS ====================

    def _calculate_volume_anomaly(
        self,
        df: pd.DataFrame,
        period: int = 20
    ) -> pd.DataFrame:
        """Calculate volume anomaly"""
        volume_mean = df["volume"].rolling(window=period).mean()
        volume_std = df["volume"].rolling(window=period).std()
        df["vol_anomaly"] = (df["volume"] - volume_mean) / volume_std
        return df

    def _calculate_volume_momentum(
        self,
        df: pd.DataFrame,
        period: int = 10
    ) -> pd.DataFrame:
        """Calculate volume momentum"""
        df["vol_mom"] = df["volume"].pct_change(period)
        return df

    def _calculate_price_volume_trend(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate Price Volume Trend (PVT)"""
        price_change = df["close"].pct_change()
        pvt = (price_change * df["volume"]).cumsum()
        df["pvt"] = pvt
        return df

    def _calculate_volume_ratio(
        self,
        df: pd.DataFrame,
        period: int = 20
    ) -> pd.DataFrame:
        """Calculate volume ratio (up volume vs down volume)"""
        up_volume = df["volume"].where(df["close"] > df["close"].shift(), 0)
        down_volume = df["volume"].where(df["close"] < df["close"].shift(), 0)

        up_sum = up_volume.rolling(window=period).sum()
        down_sum = down_volume.rolling(window=period).sum()

        df["vol_ratio"] = up_sum / (down_sum + 1e-10)
        return df

    def _calculate_volume_position(
        self,
        df: pd.DataFrame,
        period: int = 60
    ) -> pd.DataFrame:
        """Calculate volume position in lookback window"""
        def percentile_rank(x):
            return pd.Series(x).rank(pct=True).iloc[-1]

        df["vol_pos"] = df["volume"].rolling(window=period).apply(percentile_rank)
        return df

    def _calculate_volume_concentration(
        self,
        df: pd.DataFrame,
        period: int = 20
    ) -> pd.DataFrame:
        """Calculate volume concentration (Herfindahl index)"""
        def herfindahl(x):
            if len(x) == 0:
                return np.nan
            share = x / (x.sum() + 1e-10)
            return (share ** 2).sum()

        df["vol_conc"] = df["volume"].rolling(window=period).apply(herfindahl)
        return df

    def _calculate_volume_divergence(
        self,
        df: pd.DataFrame,
        period: int = 14
    ) -> pd.DataFrame:
        """Calculate volume-price divergence"""
        price_mom = df["close"].pct_change(period)
        volume_mom = df["volume"].pct_change(period)

        df["vol_div"] = 0.0
        # Bullish divergence: price down, volume up
        df.loc[(price_mom < 0) & (volume_mom > 0), "vol_div"] = 1
        # Bearish divergence: price up, volume down
        df.loc[(price_mom > 0) & (volume_mom < 0), "vol_div"] = -1
        return df

    # ==================== ORDER FLOW FACTORS ====================

    def _calculate_order_flow_imbalance(
        self,
        df: pd.DataFrame,
        period: int = 5
    ) -> pd.DataFrame:
        """Calculate order flow imbalance proxy"""
        # Use high-close vs close-low as proxy for buy/sell pressure
        buy_pressure = df["high"] - df["close"]
        sell_pressure = df["close"] - df["low"]
        imbalance = (buy_pressure - sell_pressure) / (buy_pressure + sell_pressure + 1e-10)
        df["order_flow_imbalance"] = imbalance.rolling(window=period).mean()
        return df

    def _calculate_micro_price(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate micro-price proxy"""
        # Micro-price = (bid * ask_vol + ask * bid_vol) / (bid_vol + ask_vol)
        # Use OHLC as proxy
        micro_price = (df["high"] * df["volume"] + df["low"] * df["volume"]) / (2 * df["volume"] + 1e-10)
        df["micro_price"] = micro_price / df["close"] - 1
        return df

    def _calculate_volume_profile(
        self,
        df: pd.DataFrame,
        period: int = 60,
        bins: int = 10
    ) -> pd.DataFrame:
        """Calculate volume profile (POC proxy)"""
        def poc(x):
            if len(x) < bins:
                return np.nan
            # Create price bins
            price_bins = pd.cut(x, bins=bins)
            # Find bin with highest volume (proxy, use count here)
            return price_bins.value_counts().index[0].mid

        # This is a simplified version
        df["volume_profile"] = df["close"].rolling(window=period).apply(poc)
        return df

    def _calculate_volatility_regime(
        self,
        df: pd.DataFrame,
        period: int = 60,
        regime_threshold: float = 0.5
    ) -> pd.DataFrame:
        """Calculate volatility regime (low/high)"""
        returns = df["close"].pct_change()
        rolling_vol = returns.rolling(window=period).std()
        vol_percentile = rolling_vol.rolling(window=period * 2).rank(pct=True)

        df["volatility_regime"] = 0.0
        df.loc[vol_percentile > regime_threshold, "volatility_regime"] = 1  # High vol
        df.loc[vol_percentile < (1 - regime_threshold), "volatility_regime"] = -1  # Low vol
        return df

    def get_factor_summary(self) -> Dict[str, Any]:
        """
        Get summary of available factors

        Returns:
            Dictionary with factor statistics
        """
        category_counts = {}
        for factor in self._factor_registry.values():
            cat = factor.category.value
            category_counts[cat] = category_counts.get(cat, 0) + 1

        return {
            "total_factors": len(self._factor_registry),
            "enabled_factors": sum(1 for f in self._factor_registry.values() if f.enabled),
            "by_category": category_counts,
            "factor_names": list(self._factor_registry.keys())
        }


def test_feature_engineer():
    """Test feature engineer"""
    logging.basicConfig(level=logging.INFO)

    # Create test data
    np.random.seed(42)
    dates = pd.date_range(start="2024-01-01", periods=100, freq="5min")
    base_price = 50000
    prices = base_price + np.cumsum(np.random.randn(100) * 100)

    df = pd.DataFrame({
        "open": prices - np.random.randn(100) * 20,
        "high": prices + np.random.randn(100) * 30,
        "low": prices - np.random.randn(100) * 30,
        "close": prices,
        "volume": np.random.randint(1000, 10000, 100)
    }, index=dates)

    # Test feature engineer
    engineer = FeatureEngineer()

    # Print summary
    summary = engineer.get_factor_summary()
    print(f"Factor summary: {summary}")

    # Calculate factors
    df_with_factors = engineer.calculate_all_factors(df)
    print(f"Columns after factor calculation: {list(df_with_factors.columns)}")

    # Check results
    factor_columns = [col for col in df_with_factors.columns if col not in df.columns]
    print(f"Calculated {len(factor_columns)} factors")

    if len(factor_columns) > 0:
        print("\nSample factor values:")
        print(df_with_factors[factor_columns].head())


if __name__ == "__main__":
    test_feature_engineer()
