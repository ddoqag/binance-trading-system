"""
Notebook Utilities - Notebook 工具函数
Data loading and factor calculation helpers
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Union
from pathlib import Path
import logging
import sys
import os

logger = logging.getLogger(__name__)


def load_binance_data(
    symbol: str = 'BTCUSDT',
    interval: str = '1h',
    data_dir: Optional[Union[str, Path]] = None,
    use_database: bool = False
) -> pd.DataFrame:
    """
    Load real Binance data from CSV files or database
    从 CSV 文件或数据库加载真实币安数据

    Args:
        symbol: Trading pair symbol (e.g., 'BTCUSDT', 'ETHUSDT')
        interval: Time interval (e.g., '1m', '5m', '15m', '1h', '4h', '1d')
        data_dir: Directory containing CSV files (default: project data/)
        use_database: Whether to use database instead of CSV

    Returns:
        DataFrame with OHLCV data, index = datetime
    """
    if use_database:
        return _load_from_database(symbol, interval)
    else:
        return _load_from_csv(symbol, interval, data_dir)


def _load_from_csv(
    symbol: str,
    interval: str,
    data_dir: Optional[Union[str, Path]] = None
) -> pd.DataFrame:
    """Load data from CSV files"""
    if data_dir is None:
        data_dir = Path(__file__).parent.parent / 'data'
    else:
        data_dir = Path(data_dir)

    # Try to find matching CSV files
    import glob
    pattern = f"{symbol}-{interval}-*.csv"
    csv_files = sorted(data_dir.glob(pattern))

    if not csv_files:
        logger.warning(f"No CSV files found for {symbol} {interval}")
        logger.warning(f"Looking for: {data_dir / pattern}")
        available_files = list(data_dir.glob("*.csv"))
        logger.warning(f"Available files: {[f.name for f in available_files[:10]]}")
        return pd.DataFrame()

    logger.info(f"Loading {len(csv_files)} CSV files for {symbol} {interval}")

    # Load and concatenate all files
    dfs = []
    for filepath in csv_files:
        try:
            df = pd.read_csv(filepath)
            dfs.append(df)
        except Exception as e:
            logger.warning(f"Failed to load {filepath}: {e}")

    if not dfs:
        return pd.DataFrame()

    df = pd.concat(dfs, ignore_index=True)

    # Convert to standard OHLCV format
    df = _convert_binance_format(df)

    return df


def _load_from_database(symbol: str, interval: str) -> pd.DataFrame:
    """Load data from PostgreSQL database"""
    try:
        from utils.database import DatabaseClient
        from config.settings import get_settings

        settings = get_settings()
        db_config = settings.db.to_dict()

        client = DatabaseClient(db_config)
        df = client.load_klines(symbol, interval)

        if not df.empty:
            # Rename columns to standard format
            df = df.rename(columns={
                'open_time': 'timestamp'
            })
            logger.info(f"Loaded {len(df)} rows from database for {symbol} {interval}")

        return df

    except ImportError as e:
        logger.warning(f"Database modules not available: {e}")
        return pd.DataFrame()
    except Exception as e:
        logger.warning(f"Failed to load from database: {e}")
        return pd.DataFrame()


def _convert_binance_format(df: pd.DataFrame) -> pd.DataFrame:
    """Convert Binance CSV format to standard OHLCV"""
    # Binance format has: openTime, open, high, low, close, volume, ...
    col_mapping = {
        'openTime': 'timestamp',
        'open': 'open',
        'high': 'high',
        'low': 'low',
        'close': 'close',
        'volume': 'volume'
    }

    # Select and rename columns
    available_cols = [c for c in col_mapping.keys() if c in df.columns]
    if not available_cols:
        logger.warning(f"No expected columns found. Columns: {df.columns.tolist()}")
        return pd.DataFrame()

    df = df[available_cols].copy()
    df = df.rename(columns={c: col_mapping[c] for c in available_cols})

    # Parse timestamp
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp')
        df = df.sort_index()

    # Ensure numeric columns
    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # Remove duplicates
    df = df[~df.index.duplicated(keep='first')]

    logger.info(f"Converted data: {len(df)} rows, {df.index[0]} to {df.index[-1]}")

    return df


def generate_sample_data(
    num_days: int = 500,
    base_price: float = 50000.0,
    freq: str = '1h',
    seed: int = 42
) -> pd.DataFrame:
    """
    Generate sample OHLCV data for factor research
    生成用于因子研究的示例 OHLCV 数据

    Args:
        num_days: Number of data points
        base_price: Base price for the asset
        freq: Frequency ('1h', '4h', '1d')
        seed: Random seed

    Returns:
        DataFrame with OHLCV data
    """
    np.random.seed(seed)

    # Create dates
    if freq == '1h':
        periods = num_days * 24
    elif freq == '4h':
        periods = num_days * 6
    else:  # 1d
        periods = num_days

    dates = pd.date_range(start='2024-01-01', periods=periods, freq=freq)

    # Generate price series with trends and volatility
    returns = np.random.randn(periods) * 0.01
    # Add some trend
    returns[:periods//3] += 0.002
    returns[periods//3:2*periods//3] -= 0.001

    prices = base_price * (1 + returns).cumprod()

    # Generate OHLC
    opens = prices * (1 + np.random.randn(periods) * 0.002)
    highs = np.maximum(opens, prices) * (1 + np.random.rand(periods) * 0.005)
    lows = np.minimum(opens, prices) * (1 - np.random.rand(periods) * 0.005)
    closes = prices

    # Generate volume
    volume = np.random.randint(1000, 50000, periods)
    # Add some volume spikes
    spike_indices = np.random.choice(periods, size=periods//20, replace=False)
    volume[spike_indices] *= 5

    df = pd.DataFrame({
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volume
    }, index=dates)

    return df


def calculate_all_factors(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """
    Calculate all 30+ alpha factors
    计算所有 30+ 个 Alpha 因子

    Args:
        df: OHLCV DataFrame

    Returns:
        Dictionary of factor name -> factor series
    """
    factors = {}

    try:
        # Import factors
        from factors import (
            # Momentum (8)
            momentum, ema_trend, macd_momentum, multi_period_momentum,
            relative_momentum, momentum_acceleration, gap_momentum, intraday_momentum,
            # Mean Reversion (7)
            zscore, bollinger_position, short_term_reversal, rsi_reversion,
            ma_convergence, price_percentile, channel_breakout_reversion,
            # Volatility (8)
            realized_volatility, atr_normalized, volatility_breakout, volatility_change,
            volatility_term_structure, iv_premium, volatility_correlation, jump_volatility,
            # Volume (7)
            volume_anomaly, volume_momentum, price_volume_trend, volume_ratio,
            volume_position, volume_concentration, volume_divergence
        )

        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']

        # Momentum factors (8)
        factors['mom_20'] = momentum(close, 20)
        factors['mom_60'] = momentum(close, 60)
        factors['ema_trend'] = ema_trend(close, 20, 60)
        factors['macd'] = macd_momentum(close)
        factors['multi_mom'] = multi_period_momentum(close)
        factors['mom_accel'] = momentum_acceleration(close)
        factors['gap_mom'] = gap_momentum(df['open'], close)
        factors['intraday_mom'] = intraday_momentum(df['open'], high, low, close)

        # Mean reversion factors (7)
        factors['zscore_20'] = zscore(close, 20)
        factors['bb_pos'] = bollinger_position(close, 20)
        factors['str_rev'] = short_term_reversal(close, 5)
        factors['rsi_rev'] = rsi_reversion(close, 14)
        factors['ma_conv'] = ma_convergence(close)
        factors['price_pctl'] = price_percentile(close, 20)
        factors['channel_rev'] = channel_breakout_reversion(df, 20)

        # Volatility factors (8)
        factors['vol_20'] = realized_volatility(close, 20)
        factors['atr_norm'] = atr_normalized(high, low, close, 14)
        factors['vol_breakout'] = volatility_breakout(df, 20)
        factors['vol_change'] = volatility_change(close, 20)
        factors['vol_term'] = volatility_term_structure(close)
        factors['iv_premium'] = iv_premium(df, 20)
        factors['vol_corr'] = volatility_correlation(df, 20)
        factors['jump_vol'] = jump_volatility(df, 20)

        # Volume factors (7)
        factors['vol_anomaly'] = volume_anomaly(volume, 20)
        factors['vol_mom'] = volume_momentum(volume, 20)
        factors['pvt'] = price_volume_trend(df)
        factors['vol_ratio'] = volume_ratio(volume, 20)
        factors['vol_pos'] = volume_position(df, 20)
        factors['vol_conc'] = volume_concentration(volume, 20)
        factors['vol_div'] = volume_divergence(df, 20)

    except Exception as e:
        logger.warning(f"Some factors could not be calculated: {e}")
        # Return whatever we have

    return factors


def forward_returns(prices: pd.Series, periods: int = 1) -> pd.Series:
    """
    Calculate forward returns for factor evaluation
    计算用于因子评估的前瞻收益率

    Args:
        prices: Price series
        periods: Number of periods to look forward

    Returns:
        Forward returns series
    """
    return np.log(prices.shift(-periods) / prices)


def get_factor_groups() -> Dict[str, List[str]]:
    """
    Get factor names grouped by category
    获取按类别分组的因子名称

    Returns:
        Dictionary of category -> list of factor names
    """
    return {
        'Momentum': ['mom_20', 'mom_60', 'ema_trend', 'macd', 'multi_mom', 'mom_accel', 'gap_mom', 'intraday_mom'],
        'Mean_Reversion': ['zscore_20', 'bb_pos', 'str_rev', 'rsi_rev', 'ma_conv', 'price_pctl', 'channel_rev'],
        'Volatility': ['vol_20', 'atr_norm', 'vol_breakout', 'vol_change', 'vol_term', 'iv_premium', 'vol_corr', 'jump_vol'],
        'Volume': ['vol_anomaly', 'vol_mom', 'pvt', 'vol_ratio', 'vol_pos', 'vol_conc', 'vol_div']
    }
