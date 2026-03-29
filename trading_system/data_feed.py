# trading_system/data_feed.py
import os
import requests
import pandas as pd

BINANCE_BASE_URL = "https://api.binance.com"


def get_klines(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    """Fetch K-line data from Binance REST API."""
    url = f"{BINANCE_BASE_URL}/api/v3/klines"
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    proxies = {"https": proxy, "http": proxy} if proxy else None

    resp = requests.get(
        url,
        params={"symbol": symbol, "interval": interval, "limit": limit},
        proxies=proxies,
        timeout=10,
    )
    resp.raise_for_status()

    raw = resp.json()
    df = pd.DataFrame(raw, columns=[
        "time", "open", "high", "low", "close", "volume",
        "_close_time", "_quote_vol", "_trades",
        "_taker_base", "_taker_quote", "_ignore",
    ])

    df = df[["time", "open", "high", "low", "close", "volume"]].copy()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    return df.reset_index(drop=True)
