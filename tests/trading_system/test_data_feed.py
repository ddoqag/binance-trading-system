# tests/trading_system/test_data_feed.py
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

MOCK_KLINES = [
    [1700000000000, "43000.0", "43500.0", "42800.0", "43200.0", "100.5",
     1700003600000, "4332000", 500, "50.0", "2166000", "0"],
    [1700003600000, "43200.0", "43800.0", "43100.0", "43600.0", "120.3",
     1700007200000, "5232000", 600, "60.0", "2616000", "0"],
]


def test_get_klines_returns_dataframe():
    with patch("trading_system.data_feed.requests.get") as mock_get:
        mock_get.return_value.json.return_value = MOCK_KLINES
        mock_get.return_value.raise_for_status = MagicMock()

        from trading_system.data_feed import get_klines
        df = get_klines("BTCUSDT", "1h", limit=2)

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert list(df.columns) == ["time", "open", "high", "low", "close", "volume"]
    assert df["close"].dtype == float
    assert df["close"].iloc[-1] == 43600.0


def test_get_klines_raises_on_http_error():
    with patch("trading_system.data_feed.requests.get") as mock_get:
        mock_get.return_value.raise_for_status.side_effect = Exception("HTTP 429")

        from trading_system.data_feed import get_klines
        with pytest.raises(Exception, match="HTTP 429"):
            get_klines("BTCUSDT", "1h")
