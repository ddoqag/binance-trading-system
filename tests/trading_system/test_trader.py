# tests/trading_system/test_trader.py
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch

SYMBOL = "BTCUSDT"


def make_mock_df(signal_direction="up"):
    n = 60
    if signal_direction == "up":
        close = np.linspace(38000, 48000, n)
        rsi = np.full(n, 62.0)
    else:
        close = np.linspace(48000, 38000, n)
        rsi = np.full(n, 38.0)

    df = pd.DataFrame({
        "time": range(n),
        "open": close, "high": close + 100,
        "low": close - 100, "close": close,
        "volume": np.ones(n) * 100,
    })
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["atr"] = 300.0      # ~0.7% of 43000 — above threshold
    df["rsi"] = rsi
    return df


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


def _make_trader():
    from trading_system.config import Config
    from trading_system.trader import Trader
    cfg = Config()
    cfg.initial_balance = 10000.0
    mock_client = _make_mock_binance_client()
    return Trader(cfg, binance_client=mock_client)


def test_trader_opens_long_on_buy_signal():
    trader = _make_trader()
    with patch("trading_system.trader.get_klines") as mock_feed, \
         patch("trading_system.trader.add_features") as mock_feat:
        mock_feed.return_value = make_mock_df("up")
        mock_feat.side_effect = lambda df: df

        trader.step()

    assert trader.position.is_long(SYMBOL)


def test_trader_opens_short_on_sell_signal():
    """Non-leverage mode does not support short selling."""
    trader = _make_trader()
    with patch("trading_system.trader.get_klines") as mock_feed, \
         patch("trading_system.trader.add_features") as mock_feat:
        mock_feed.return_value = make_mock_df("down")
        mock_feat.side_effect = lambda df: df

        trader.step()

    # In non-leverage mode, short selling is not supported
    # Position should remain flat
    assert trader.position.is_flat(SYMBOL)


def test_trader_does_not_open_twice_on_same_signal():
    trader = _make_trader()
    with patch("trading_system.trader.get_klines") as mock_feed, \
         patch("trading_system.trader.add_features") as mock_feat:
        mock_feed.return_value = make_mock_df("up")
        mock_feat.side_effect = lambda df: df

        trader.step()
        trader.step()   # second call — already long, same signal → no action

    assert trader.position.is_long(SYMBOL)
    assert len(trader.executor.order_history) == 1


def test_trader_closes_long_on_sell_signal():
    trader = _make_trader()

    # Open long first
    with patch("trading_system.trader.get_klines") as mock_feed, \
         patch("trading_system.trader.add_features") as mock_feat:
        mock_feed.return_value = make_mock_df("up")
        mock_feat.side_effect = lambda df: df
        trader.step()

    assert trader.position.is_long(SYMBOL)

    # Now flip to sell signal
    with patch("trading_system.trader.get_klines") as mock_feed, \
         patch("trading_system.trader.add_features") as mock_feat:
        mock_feed.return_value = make_mock_df("down")
        mock_feat.side_effect = lambda df: df
        trader.step()

    assert trader.position.is_flat(SYMBOL)
    assert len(trader.executor.order_history) == 2


def test_trader_stops_on_circuit_breaker():
    trader = _make_trader()
    trader.risk.record_trade_pnl(-600.0)   # trigger daily loss circuit breaker

    with patch("trading_system.trader.get_klines") as mock_feed, \
         patch("trading_system.trader.add_features") as mock_feat:
        mock_feed.return_value = make_mock_df("up")
        mock_feat.side_effect = lambda df: df
        trader.step()

    assert trader.position.is_flat(SYMBOL)
    assert len(trader.executor.order_history) == 0


def test_trader_handles_data_fetch_error_gracefully():
    trader = _make_trader()
    with patch("trading_system.trader.get_klines", side_effect=Exception("timeout")):
        trader.step()   # should not raise

    assert trader.position.is_flat(SYMBOL)
