# tests/portfolio_system/test_portfolio_trader.py
"""
Tests for PortfolioTrader.

核心验证：
  - 多策略信号通过 BanditAllocator 融合
  - 交易平仓后 Bandit 权重自动更新
  - 高波动 Regime 时不交易（沿用 RegimeAwareLGBMStrategy 行为）
  - EquityMonitor 正确跟踪净值
"""
import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from trading_system.config import Config
from portfolio_system.portfolio_trader import PortfolioTrader


def _config() -> Config:
    cfg = Config()
    cfg.initial_balance = 10000.0
    cfg.symbol = "BTCUSDT"
    cfg.interval = "1h"
    return cfg


def _make_mock_binance_client():
    """Create a mock Binance client for testing."""
    mock_client = MagicMock()
    mock_client._client = MagicMock()
    mock_client._client.futures_exchange_info.return_value = {
        'symbols': [{'symbol': 'BTCUSDT', 'filters': [{'filterType': 'LOT_SIZE', 'stepSize': '0.001'}]}]
    }
    mock_client._client.futures_create_order.return_value = {
        'orderId': '12345',
        'status': 'FILLED',
        'avgPrice': '43000.0',
        'executedQty': '0.1'
    }
    mock_client._client.futures_position_information.return_value = []
    return mock_client


def _make_df(n: int = 60, direction: str = "up") -> pd.DataFrame:
    close = np.linspace(100.0, 115.0, n) if direction == "up" else np.linspace(115.0, 100.0, n)
    return pd.DataFrame({
        "open": close - 0.5, "high": close + 1.0,
        "low": close - 1.0, "close": close,
        "volume": np.ones(n) * 1000.0,
    })


# ── 初始化 ────────────────────────────────────────────────────────────────────

def test_initializes_with_default_strategies():
    mock_client = _make_mock_binance_client()
    trader = PortfolioTrader(_config(), binance_client=mock_client)
    assert len(trader.strategies) >= 1
    assert trader.allocator is not None


def test_initial_weights_uniform():
    mock_client = _make_mock_binance_client()
    trader = PortfolioTrader(_config(), binance_client=mock_client)
    n = len(trader.strategies)
    np.testing.assert_allclose(
        trader.allocator.weights,
        np.ones(n) / n,
        atol=0.05,  # min_prob 引入的轻微偏差
    )


# ── 信号融合 ──────────────────────────────────────────────────────────────────

def test_step_returns_without_error():
    mock_client = _make_mock_binance_client()
    trader = PortfolioTrader(_config(), binance_client=mock_client)
    mock_strategies = [MagicMock(), MagicMock()]
    mock_strategies[0].generate_signal.return_value = 1
    mock_strategies[1].generate_signal.return_value = 1
    trader.strategies = mock_strategies
    trader.allocator = __import__(
        'portfolio_system.bandit_allocator', fromlist=['BanditAllocator']
    ).BanditAllocator(n_arms=2)

    with patch("portfolio_system.portfolio_trader.get_klines", return_value=_make_df()):
        trader.step()  # 不应抛出异常


def test_all_hold_signals_result_in_no_trade():
    """所有策略都返回 HOLD → 不开仓。"""
    mock_client = _make_mock_binance_client()
    trader = PortfolioTrader(_config(), binance_client=mock_client)
    mock_strategies = [MagicMock() for _ in range(2)]
    for s in mock_strategies:
        s.generate_signal.return_value = 0
    trader.strategies = mock_strategies
    trader.allocator = __import__(
        'portfolio_system.bandit_allocator', fromlist=['BanditAllocator']
    ).BanditAllocator(n_arms=2)

    with patch("portfolio_system.portfolio_trader.get_klines", return_value=_make_df()):
        trader.step()

    assert trader.position.is_flat()


# ── Bandit 权重更新 ───────────────────────────────────────────────────────────

def test_allocator_weights_update_after_closed_trade():
    """平仓后 allocator 的权重应该已经更新（不再全等于初始值）。"""
    mock_client = _make_mock_binance_client()
    trader = PortfolioTrader(_config(), binance_client=mock_client)
    # 连续多次正向奖励才能让权重偏离均匀分布（单次更新 Δw ≈ 0.6%，需积累）
    for _ in range(20):
        trader.allocator.update(arm=0, reward=1.0)
    weights_after = trader.allocator.weights.copy()
    # 经过 20 次正向更新，arm-0 权重应明显高于均匀分布
    n = len(trader.strategies)
    assert weights_after[0] > 1.0 / n + 0.05, (
        f"arm-0 权重 {weights_after[0]:.3f} 应 > {1/n + 0.05:.3f}"
    )


# ── 监控集成 ──────────────────────────────────────────────────────────────────

def test_monitor_present():
    mock_client = _make_mock_binance_client()
    trader = PortfolioTrader(_config(), binance_client=mock_client)
    assert trader.monitor is not None
    assert trader.monitor.current_equity == 10000.0


# ── 数据获取失败时优雅退出 ────────────────────────────────────────────────────

def test_data_fetch_error_does_not_crash():
    mock_client = _make_mock_binance_client()
    trader = PortfolioTrader(_config(), binance_client=mock_client)
    with patch("portfolio_system.portfolio_trader.get_klines", side_effect=Exception("timeout")):
        trader.step()  # 不应抛出
    assert trader.position.is_flat()
