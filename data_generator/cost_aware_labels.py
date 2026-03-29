"""
Transaction Cost Aware Label Generator
Institutional-grade label generation with realistic transaction costs

This module extends the standard triple barrier method to account for:
1. Trading fees (maker/taker)
2. Slippage (bid-ask spread, market impact)
3. Time decay (holding period costs)

This ensures labels reflect realistic trading outcomes.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

import pandas as pd
import numpy as np

from data_generator.utils import (
    calculate_atr,
    TripleBarrierColumns as TBC
)

logger = logging.getLogger(__name__)


class CostType(Enum):
    """Transaction cost types"""
    FIXED_FEE = "fixed_fee"           # Fixed fee per trade
    PERCENTAGE_FEE = "percentage_fee"  # Percentage of notional
    SLIPPAGE = "slippage"             # Slippage estimate
    SPREAD = "spread"                 # Bid-ask spread


@dataclass
class TransactionCostConfig:
    """
    Transaction cost configuration

    Default values are realistic estimates for crypto trading:
    - Taker fee: 0.1% (Binance standard)
    - Slippage: 0.05% (typical for medium-sized orders)
    - Spread: 0.02% (typical for liquid pairs)
    """
    # Fees (as decimals, e.g., 0.001 = 0.1%)
    entry_fee: float = 0.001          # Entry fee (taker)
    exit_fee: float = 0.001           # Exit fee (taker)

    # Slippage estimates
    entry_slippage: float = 0.0005    # Entry slippage (0.05%)
    exit_slippage: float = 0.0005     # Exit slippage (0.05%)

    # Spread
    bid_ask_spread: float = 0.0002    # Bid-ask spread (0.02%)

    # Market impact (for larger orders)
    market_impact_factor: float = 0.0  # Additional impact per unit of volume

    # Time decay (funding rate equivalent for holding)
    daily_holding_cost: float = 0.0    # Daily cost of holding position

    @property
    def total_entry_cost(self) -> float:
        """Total cost to enter position"""
        return self.entry_fee + self.entry_slippage + self.bid_ask_spread / 2

    @property
    def total_exit_cost(self) -> float:
        """Total cost to exit position"""
        return self.exit_fee + self.exit_slippage + self.bid_ask_spread / 2

    @property
    def total_roundtrip_cost(self) -> float:
        """Total round-trip cost"""
        return self.total_entry_cost + self.total_exit_cost

    def calculate_holding_cost(self, holding_periods: int, periods_per_day: int = 288) -> float:
        """
        Calculate holding cost for a given period

        Args:
            holding_periods: Number of periods held
            periods_per_day: Number of periods in a day (288 for 5-min bars)

        Returns:
            Holding cost as decimal
        """
        days_held = holding_periods / periods_per_day
        return days_held * self.daily_holding_cost


class CostAwareTripleBarrier:
    """
    Cost-Aware Triple Barrier Label Generator

    Extends the standard triple barrier method to account for transaction costs,
    ensuring labels reflect realistic trading outcomes.
    """

    def __init__(self, cost_config: Optional[TransactionCostConfig] = None):
        """
        Initialize cost-aware triple barrier generator

        Args:
            cost_config: Transaction cost configuration
        """
        self.cost_config = cost_config or TransactionCostConfig()
        self.logger = logging.getLogger(__name__)

    def generate_labels(
        self,
        df: pd.DataFrame,
        upper_barrier: float = 0.005,    # 0.5% profit target
        lower_barrier: float = 0.005,    # 0.5% stop loss
        time_barrier: int = 12,          # 12 bars
        volatility_adjusted: bool = True,
        atr_period: int = 14
    ) -> pd.DataFrame:
        """
        Generate cost-aware triple barrier labels

        Args:
            df: DataFrame with OHLCV data
            upper_barrier: Upper barrier (profit target) before costs
            lower_barrier: Lower barrier (stop loss) before costs
            time_barrier: Time barrier in bars
            volatility_adjusted: Whether to adjust barriers by volatility
            atr_period: ATR period for volatility adjustment

        Returns:
            DataFrame with labels
        """
        result = df.copy()

        self.logger.info(
            f"Generating cost-aware triple barrier labels "
            f"(entry_cost={self.cost_config.total_entry_cost:.4f}, "
            f"exit_cost={self.cost_config.total_exit_cost:.4f})"
        )

        # Adjust barriers for costs
        cost_adjusted_upper, cost_adjusted_lower = self._adjust_barriers_for_costs(
            upper_barrier, lower_barrier
        )

        self.logger.info(
            f"Cost-adjusted barriers: "
            f"upper={cost_adjusted_upper:.4f}, lower={cost_adjusted_lower:.4f}"
        )

        # Calculate volatility for barrier adjustment
        if volatility_adjusted and 'close' in df.columns:
            atr = self._calculate_atr(df, atr_period)
            volatility_factor = atr / df['close']
            result['triple_barrier_volatility'] = volatility_factor
        else:
            volatility_factor = pd.Series(1.0, index=df.index)

        # Generate labels
        labels = []
        touch_times = []
        returns = []
        net_returns = []  # After costs
        holding_periods = []

        for i in range(len(df)):
            if i >= len(df) - 1:
                labels.append(0)
                touch_times.append(None)
                returns.append(0.0)
                net_returns.append(0.0)
                holding_periods.append(0)
                continue

            current_price = df['close'].iloc[i]
            current_vol = volatility_factor.iloc[i]

            # Adjust barriers by volatility
            adj_upper = cost_adjusted_upper * current_vol / volatility_factor.median()
            adj_lower = cost_adjusted_lower * current_vol / volatility_factor.median()

            # Calculate barriers
            upper_price = current_price * (1 + adj_upper)
            lower_price = current_price * (1 - adj_lower)

            # Look ahead until barrier touch or time limit
            future_window = min(time_barrier, len(df) - i - 1)
            future_prices = df['close'].iloc[i+1:i+1+future_window]
            future_highs = df['high'].iloc[i+1:i+1+future_window] if 'high' in df.columns else future_prices
            future_lows = df['low'].iloc[i+1:i+1+future_window] if 'low' in df.columns else future_prices

            label, touch_idx, gross_return = self._find_barrier_touch(
                current_price, upper_price, lower_price, future_prices,
                future_highs, future_lows, future_window
            )

            # Calculate net return after costs
            if touch_idx is not None:
                periods_held = touch_idx + 1
                holding_cost = self.cost_config.calculate_holding_cost(periods_held)
                total_cost = self.cost_config.total_roundtrip_cost + holding_cost
                net_ret = gross_return - total_cost
            else:
                net_ret = gross_return

            labels.append(label)
            touch_times.append(touch_idx)
            returns.append(gross_return)
            net_returns.append(net_ret)
            holding_periods.append(touch_idx + 1 if touch_idx is not None else time_barrier)

        result[TBC.LABEL] = labels
        result[TBC.TOUCH_TIME] = touch_times
        result[TBC.GROSS_RETURN] = returns
        result[TBC.NET_RETURN] = net_returns
        result[TBC.HOLDING_PERIODS] = holding_periods

        # Add cost breakdown
        result[TBC.ENTRY_COST] = self.cost_config.total_entry_cost
        result[TBC.EXIT_COST] = self.cost_config.total_exit_cost
        result[TBC.TOTAL_COST] = self.cost_config.total_roundtrip_cost

        # Log statistics
        self._log_label_statistics(result)

        return result

    def _adjust_barriers_for_costs(
        self,
        upper_barrier: float,
        lower_barrier: float
    ) -> Tuple[float, float]:
        """
        Adjust barriers to account for transaction costs

        The logic:
        - To hit upper barrier after costs: gross_return > barrier + entry_cost + exit_cost
        - So effective upper barrier = barrier + total_cost
        - Similarly for lower barrier

        Args:
            upper_barrier: Original upper barrier
            lower_barrier: Original lower barrier

        Returns:
            Tuple of (adjusted_upper, adjusted_lower)
        """
        total_cost = self.cost_config.total_roundtrip_cost

        # Adjust barriers to be harder to hit
        adjusted_upper = upper_barrier + total_cost
        adjusted_lower = lower_barrier + total_cost

        return adjusted_upper, adjusted_lower

    def _find_barrier_touch(
        self,
        current_price: float,
        upper_price: float,
        lower_price: float,
        future_prices: pd.Series,
        future_highs: pd.Series,
        future_lows: pd.Series,
        max_bars: int
    ) -> Tuple[int, Optional[int], float]:
        """
        Find which barrier is touched first

        Returns:
            Tuple of (label, touch_index, return)
            label: 1 = upper, -1 = lower, 0 = time
        """
        for i in range(len(future_prices)):
            high = future_highs.iloc[i]
            low = future_lows.iloc[i]
            close = future_prices.iloc[i]

            # Check upper barrier
            if high >= upper_price:
                return 1, i, (upper_price / current_price - 1)

            # Check lower barrier
            if low <= lower_price:
                return -1, i, (lower_price / current_price - 1)

        # Time barrier hit
        final_return = future_prices.iloc[-1] / current_price - 1 if len(future_prices) > 0 else 0
        return 0, None, final_return

    def _calculate_atr(
        self,
        df: pd.DataFrame,
        period: int = 14
    ) -> pd.Series:
        """Calculate Average True Range using shared utility."""
        return calculate_atr(df, period=period, shift=0)

    def _log_label_statistics(self, df: pd.DataFrame):
        """Log label generation statistics"""
        if TBC.LABEL not in df.columns:
            return

        labels = df[TBC.LABEL].dropna()

        total = len(labels)
        upper_count = (labels == 1).sum()
        lower_count = (labels == -1).sum()
        time_count = (labels == 0).sum()

        self.logger.info("=" * 60)
        self.logger.info("Cost-Aware Triple Barrier Label Statistics")
        self.logger.info("=" * 60)
        self.logger.info(f"Total samples: {total}")
        self.logger.info(f"Upper barrier (profit): {upper_count} ({upper_count/total*100:.1f}%)")
        self.logger.info(f"Lower barrier (loss): {lower_count} ({lower_count/total*100:.1f}%)")
        self.logger.info(f"Time barrier: {time_count} ({time_count/total*100:.1f}%)")

        if TBC.GROSS_RETURN in df.columns:
            gross_returns = df[TBC.GROSS_RETURN].dropna()
            self.logger.info(f"\nGross returns: mean={gross_returns.mean()*100:.3f}%, std={gross_returns.std()*100:.3f}%")

        if TBC.NET_RETURN in df.columns:
            net_returns = df[TBC.NET_RETURN].dropna()
            self.logger.info(f"Net returns: mean={net_returns.mean()*100:.3f}%, std={net_returns.std()*100:.3f}%")

            # Calculate win rate on net returns
            win_rate = (net_returns > 0).mean()
            self.logger.info(f"Net win rate: {win_rate*100:.1f}%")

        self.logger.info("=" * 60)

    def compare_with_without_costs(
        self,
        df: pd.DataFrame,
        upper_barrier: float = 0.005,
        lower_barrier: float = 0.005,
        time_barrier: int = 12
    ) -> Dict[str, Any]:
        """
        Compare label distributions with and without costs

        Args:
            df: DataFrame with price data
            upper_barrier: Upper barrier
            lower_barrier: Lower barrier
            time_barrier: Time barrier

        Returns:
            Comparison statistics
        """
        # Generate with costs
        with_costs = self.generate_labels(
            df, upper_barrier, lower_barrier, time_barrier
        )

        # Generate without costs (zero cost config)
        no_cost_config = TransactionCostConfig(
            entry_fee=0, exit_fee=0,
            entry_slippage=0, exit_slippage=0,
            bid_ask_spread=0
        )
        no_cost_generator = CostAwareTripleBarrier(no_cost_config)
        without_costs = no_cost_generator.generate_labels(
            df, upper_barrier, lower_barrier, time_barrier
        )

        # Compare
        with_labels = with_costs[TBC.LABEL].dropna()
        without_labels = without_costs[TBC.LABEL].dropna()

        comparison = {
            "with_costs": {
                "upper_pct": float((with_labels == 1).mean() * 100),
                "lower_pct": float((with_labels == -1).mean() * 100),
                "time_pct": float((with_labels == 0).mean() * 100),
                "mean_net_return": float(with_costs[TBC.NET_RETURN].mean()),
                "win_rate": float((with_costs[TBC.NET_RETURN] > 0).mean())
            },
            "without_costs": {
                "upper_pct": float((without_labels == 1).mean() * 100),
                "lower_pct": float((without_labels == -1).mean() * 100),
                "time_pct": float((without_labels == 0).mean() * 100),
                "mean_gross_return": float(without_costs[TBC.GROSS_RETURN].mean()),
                "win_rate": float((without_costs[TBC.GROSS_RETURN] > 0).mean())
            },
            "cost_impact": {
                "upper_reduction": float((without_labels == 1).mean() - (with_labels == 1).mean()) * 100,
                "lower_increase": float((with_labels == -1).mean() - (without_labels == -1).mean()) * 100,
                "win_rate_reduction": float(
                    (without_costs[TBC.GROSS_RETURN] > 0).mean() -
                    (with_costs[TBC.NET_RETURN] > 0).mean()
                ) * 100
            }
        }

        return comparison


# Convenience functions
def generate_cost_aware_labels(
    df: pd.DataFrame,
    entry_fee: float = 0.001,
    exit_fee: float = 0.001,
    slippage: float = 0.0005,
    **kwargs
) -> pd.DataFrame:
    """
    Quick function to generate cost-aware labels

    Args:
        df: DataFrame with price data
        entry_fee: Entry fee as decimal
        exit_fee: Exit fee as decimal
        slippage: Slippage estimate as decimal
        **kwargs: Additional parameters for label generation

    Returns:
        DataFrame with labels
    """
    cost_config = TransactionCostConfig(
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        entry_slippage=slippage,
        exit_slippage=slippage
    )
    generator = CostAwareTripleBarrier(cost_config)
    return generator.generate_labels(df, **kwargs)


def get_realistic_cost_config(exchange: str = "binance", tier: str = "standard") -> TransactionCostConfig:
    """
    Get realistic cost configuration for major exchanges

    Args:
        exchange: Exchange name (binance, coinbase, kraken, etc.)
        tier: Account tier (standard, vip, market_maker)

    Returns:
        TransactionCostConfig
    """
    configs = {
        "binance": {
            "standard": TransactionCostConfig(
                entry_fee=0.001,    # 0.1% taker
                exit_fee=0.001,
                entry_slippage=0.0005,
                exit_slippage=0.0005,
                bid_ask_spread=0.0002
            ),
            "vip": TransactionCostConfig(
                entry_fee=0.0009,   # 0.09% taker
                exit_fee=0.0009,
                entry_slippage=0.0004,
                exit_slippage=0.0004,
                bid_ask_spread=0.00015
            )
        },
        "coinbase": {
            "standard": TransactionCostConfig(
                entry_fee=0.006,    # 0.6% taker
                exit_fee=0.006,
                entry_slippage=0.001,
                exit_slippage=0.001,
                bid_ask_spread=0.0005
            ),
            "advanced": TransactionCostConfig(
                entry_fee=0.004,    # 0.4% taker
                exit_fee=0.004,
                entry_slippage=0.0008,
                exit_slippage=0.0008,
                bid_ask_spread=0.0004
            )
        },
        "kraken": {
            "standard": TransactionCostConfig(
                entry_fee=0.0026,   # 0.26% taker
                exit_fee=0.0026,
                entry_slippage=0.0006,
                exit_slippage=0.0006,
                bid_ask_spread=0.0003
            )
        }
    }

    exchange_configs = configs.get(exchange.lower(), configs["binance"])
    return exchange_configs.get(tier, exchange_configs["standard"])
