"""
RL Research Utilities - RL 研究工具函数
Data generation, analysis, and visualization for RL trading research
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Any, Union
from pathlib import Path
from dataclasses import dataclass
import logging

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


@dataclass
class PerformanceMetrics:
    """Performance metrics container - 性能指标容器"""
    total_return: float
    annualized_return: float
    volatility: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float


def generate_trading_data(
    num_days: int = 60,
    base_price: float = 50000.0,
    freq: str = '1h',
    seed: int = 42,
    style: str = 'mixed'  # 'trending', 'mean_reverting', 'volatile', 'mixed'
) -> pd.DataFrame:
    """
    Generate realistic trading data for RL research
    生成用于 RL 研究的真实交易数据

    Args:
        num_days: Number of days of data
        base_price: Base price
        freq: Frequency ('1h', '4h', '1d')
        seed: Random seed
        style: Market style ('trending', 'mean_reverting', 'volatile', 'mixed')

    Returns:
        DataFrame with OHLCV data
    """
    np.random.seed(seed)

    # Calculate number of periods
    if freq == '1h':
        periods = num_days * 24
    elif freq == '4h':
        periods = num_days * 6
    else:  # 1d
        periods = num_days

    dates = pd.date_range(start='2024-01-01', periods=periods, freq=freq)

    # Generate returns based on style
    if style == 'trending':
        # Strong trend with some noise
        trend = 0.0005
        noise = np.random.randn(periods) * 0.008
        returns = trend + noise
    elif style == 'mean_reverting':
        # Mean reverting with cycles
        t = np.arange(periods)
        cycle = 0.003 * np.sin(2 * np.pi * t / 100)
        noise = np.random.randn(periods) * 0.01
        returns = cycle + noise
    elif style == 'volatile':
        # Volatility clustering (GARCH-like)
        vol = np.ones(periods) * 0.01
        for t in range(1, periods):
            vol[t] = 0.9 * vol[t-1] + 0.1 * np.abs(np.random.randn()) * 0.02
        returns = np.random.randn(periods) * vol
    else:  # mixed
        # Mixed regime
        returns = np.zeros(periods)
        regime = 0
        for t in range(periods):
            if t % 200 == 0 and t > 0:
                regime = (regime + 1) % 3
            if regime == 0:
                returns[t] = 0.0003 + np.random.randn() * 0.008
            elif regime == 1:
                returns[t] = -0.0002 + np.random.randn() * 0.012
            else:
                returns[t] = np.random.randn() * 0.015

    # Generate prices
    prices = base_price * (1 + returns).cumprod()

    # Generate OHLC
    opens = prices * (1 + np.random.randn(periods) * 0.002)
    highs = np.maximum(opens, prices) * (1 + np.random.rand(periods) * 0.005)
    lows = np.minimum(opens, prices) * (1 - np.random.rand(periods) * 0.005)
    closes = prices

    # Generate volume (with intraday patterns)
    volume = np.random.randint(1000, 50000, periods)
    # Volume spikes
    spike_indices = np.random.choice(periods, size=periods//30, replace=False)
    volume[spike_indices] *= 5

    df = pd.DataFrame({
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volume
    }, index=dates)

    return df


def create_env_config(style: str = 'default') -> Dict[str, Any]:
    """
    Create environment configuration by style
    按风格创建环境配置

    Args:
        style: 'default', 'conservative', 'aggressive', 'high_freq'

    Returns:
        Configuration dictionary
    """
    configs = {
        'default': {
            'initial_capital': 10000.0,
            'commission_rate': 0.001,
            'slippage': 0.0005,
            'max_position': 1.0,
            'reward_type': 'risk_adjusted',
            'action_space': 'discrete',
            'window_size': 20
        },
        'conservative': {
            'initial_capital': 10000.0,
            'commission_rate': 0.002,
            'slippage': 0.001,
            'max_position': 0.5,
            'reward_type': 'risk_adjusted',
            'action_space': 'discrete',
            'window_size': 20
        },
        'aggressive': {
            'initial_capital': 10000.0,
            'commission_rate': 0.0005,
            'slippage': 0.0002,
            'max_position': 1.0,
            'reward_type': 'simple',
            'action_space': 'continuous',
            'window_size': 10
        },
        'high_freq': {
            'initial_capital': 10000.0,
            'commission_rate': 0.0001,
            'slippage': 0.0001,
            'max_position': 0.3,
            'reward_type': 'sharpe',
            'action_space': 'continuous',
            'window_size': 5
        }
    }

    return configs.get(style, configs['default']).copy()


def get_agent_config(agent_type: str = 'dqn', style: str = 'default') -> Dict[str, Any]:
    """
    Get agent configuration by type and style
    按类型和风格获取智能体配置

    Args:
        agent_type: 'dqn' or 'ppo'
        style: 'default', 'fast', 'stable'

    Returns:
        Configuration dictionary
    """
    if agent_type == 'dqn':
        configs = {
            'default': {
                'lr': 3e-4,
                'gamma': 0.99,
                'epsilon_start': 1.0,
                'epsilon_end': 0.05,
                'epsilon_decay': 0.995,
                'buffer_capacity': 10000,
                'batch_size': 64,
                'target_update_freq': 100,
                'hidden_dims': [128, 64]
            },
            'fast': {
                'lr': 1e-3,
                'gamma': 0.95,
                'epsilon_start': 0.5,
                'epsilon_end': 0.01,
                'epsilon_decay': 0.99,
                'buffer_capacity': 5000,
                'batch_size': 32,
                'target_update_freq': 50,
                'hidden_dims': [64, 32]
            },
            'stable': {
                'lr': 1e-4,
                'gamma': 0.995,
                'epsilon_start': 1.0,
                'epsilon_end': 0.1,
                'epsilon_decay': 0.998,
                'buffer_capacity': 20000,
                'batch_size': 128,
                'target_update_freq': 200,
                'hidden_dims': [256, 128]
            }
        }
    else:  # ppo
        configs = {
            'default': {
                'lr': 3e-4,
                'gamma': 0.99,
                'gae_lambda': 0.95,
                'clip_epsilon': 0.2,
                'epochs_per_update': 10,
                'batch_size': 64,
                'hidden_dims': [128, 64]
            },
            'fast': {
                'lr': 5e-4,
                'gamma': 0.95,
                'gae_lambda': 0.9,
                'clip_epsilon': 0.3,
                'epochs_per_update': 5,
                'batch_size': 32,
                'hidden_dims': [64, 32]
            },
            'stable': {
                'lr': 1e-4,
                'gamma': 0.995,
                'gae_lambda': 0.98,
                'clip_epsilon': 0.15,
                'epochs_per_update': 15,
                'batch_size': 128,
                'hidden_dims': [256, 128]
            }
        }

    return configs.get(style, configs['default']).copy()


def analyze_training_history(history: Dict[str, List[float]]) -> Dict[str, Any]:
    """
    Analyze training history and calculate key metrics
    分析训练历史并计算关键指标

    Args:
        history: Training history dictionary from train_agent()

    Returns:
        Analysis results dictionary
    """
    results = {}

    episodes = np.array(history.get('episode', []))
    rewards = np.array(history.get('total_reward', []))
    final_values = np.array(history.get('final_value', []))
    returns = np.array(history.get('return', []))

    if len(rewards) > 0:
        results['reward_mean'] = float(np.mean(rewards))
        results['reward_std'] = float(np.std(rewards))
        results['reward_max'] = float(np.max(rewards))
        results['reward_min'] = float(np.min(rewards))
        results['reward_trend'] = float(np.polyfit(episodes, rewards, 1)[0]) if len(episodes) > 1 else 0.0

    if len(returns) > 0:
        results['return_mean'] = float(np.mean(returns))
        results['return_std'] = float(np.std(returns))
        results['return_final'] = float(returns[-1])
        results['return_best'] = float(np.max(returns))
        results['win_rate'] = float(np.mean(returns > 0))

    if 'loss' in history:
        losses = np.array(history['loss'])
        if len(losses) > 0:
            results['loss_mean'] = float(np.mean(losses))
            results['loss_final'] = float(losses[-1])
            results['loss_trend'] = float(np.polyfit(range(len(losses)), losses, 1)[0]) if len(losses) > 1 else 0.0

    if 'actor_loss' in history:
        actor_losses = np.array(history['actor_loss'])
        critic_losses = np.array(history.get('critic_loss', []))
        if len(actor_losses) > 0:
            results['actor_loss_mean'] = float(np.mean(actor_losses))
            results['actor_loss_final'] = float(actor_losses[-1])
        if len(critic_losses) > 0:
            results['critic_loss_mean'] = float(np.mean(critic_losses))
            results['critic_loss_final'] = float(critic_losses[-1])

    return results


def compare_agents(agent_histories: Dict[str, Dict[str, List[float]]]) -> pd.DataFrame:
    """
    Compare multiple agents' performance
    对比多个智能体的表现

    Args:
        agent_histories: Dictionary of {agent_name: training_history}

    Returns:
        DataFrame with comparison metrics
    """
    comparisons = []

    for name, history in agent_histories.items():
        analysis = analyze_training_history(history)
        comparison = {'agent': name}
        comparison.update(analysis)
        comparisons.append(comparison)

    return pd.DataFrame(comparisons)


def calculate_performance_metrics(
    portfolio_values: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 365 * 24
) -> PerformanceMetrics:
    """
    Calculate comprehensive performance metrics
    计算综合性能指标

    Args:
        portfolio_values: Portfolio value time series
        risk_free_rate: Annual risk-free rate
        periods_per_year: Number of periods per year

    Returns:
        PerformanceMetrics object
    """
    if len(portfolio_values) < 2:
        return PerformanceMetrics(
            total_return=0.0,
            annualized_return=0.0,
            volatility=0.0,
            sharpe_ratio=0.0,
            max_drawdown=0.0,
            win_rate=0.0,
            profit_factor=0.0
        )

    # Calculate returns
    returns = portfolio_values.pct_change().dropna()

    # Total return
    total_return = (portfolio_values.iloc[-1] / portfolio_values.iloc[0]) - 1

    # Annualized return
    num_periods = len(returns)
    annualized_return = (1 + total_return) ** (periods_per_year / num_periods) - 1

    # Volatility (annualized)
    volatility = returns.std() * np.sqrt(periods_per_year)

    # Sharpe ratio
    sharpe_ratio = (annualized_return - risk_free_rate) / volatility if volatility > 0 else 0.0

    # Max drawdown
    rolling_max = portfolio_values.cummax()
    drawdown = (portfolio_values - rolling_max) / rolling_max
    max_drawdown = float(drawdown.min())

    # Win rate
    win_rate = float(np.mean(returns > 0))

    # Profit factor (gross profits / gross losses)
    profits = returns[returns > 0].sum()
    losses = -returns[returns < 0].sum()
    profit_factor = profits / losses if losses > 0 else float('inf')

    return PerformanceMetrics(
        total_return=float(total_return),
        annualized_return=float(annualized_return),
        volatility=float(volatility),
        sharpe_ratio=float(sharpe_ratio),
        max_drawdown=float(max_drawdown),
        win_rate=win_rate,
        profit_factor=float(profit_factor)
    )


def extract_portfolio_history(env_history: List[Dict]) -> pd.DataFrame:
    """
    Extract portfolio history from environment
    从环境中提取组合历史

    Args:
        env_history: History from env.get_portfolio_history() or agent step info

    Returns:
        DataFrame with portfolio history
    """
    if not env_history:
        return pd.DataFrame()

    df = pd.DataFrame(env_history)
    if 'index' in df.columns:
        df = df.set_index('index')
    return df


def print_analysis_summary(analysis: Dict[str, Any], agent_name: str = "Agent"):
    """
    Print analysis summary in readable format
    以可读格式打印分析摘要

    Args:
        analysis: Analysis from analyze_training_history()
        agent_name: Name of the agent
    """
    print(f"\n{'='*60}")
    print(f"{agent_name} Training Analysis")
    print(f"{'='*60}")

    if 'reward_mean' in analysis:
        print(f"\nReward Statistics:")
        print(f"  Mean:    {analysis.get('reward_mean', 0):.4f}")
        print(f"  Std:     {analysis.get('reward_std', 0):.4f}")
        print(f"  Best:    {analysis.get('reward_max', 0):.4f}")
        print(f"  Worst:   {analysis.get('reward_min', 0):.4f}")
        print(f"  Trend:   {analysis.get('reward_trend', 0):.6f} per episode")

    if 'return_mean' in analysis:
        print(f"\nReturn Statistics:")
        print(f"  Mean:    {analysis.get('return_mean', 0):.2%}")
        print(f"  Final:   {analysis.get('return_final', 0):.2%}")
        print(f"  Best:    {analysis.get('return_best', 0):.2%}")
        print(f"  Win Rate:{analysis.get('win_rate', 0):.1%}")

    if 'loss_mean' in analysis:
        print(f"\nLoss Statistics:")
        print(f"  Mean:    {analysis.get('loss_mean', 0):.6f}")
        print(f"  Final:   {analysis.get('loss_final', 0):.6f}")

    if 'actor_loss_mean' in analysis:
        print(f"\nPPO Loss Statistics:")
        print(f"  Actor:   {analysis.get('actor_loss_mean', 0):.6f}")
        print(f"  Critic:  {analysis.get('critic_loss_mean', 0):.6f}")

    print(f"\n{'='*60}\n")
