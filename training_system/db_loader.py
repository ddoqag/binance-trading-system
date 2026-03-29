# training_system/db_loader.py
"""
从 PostgreSQL binance 数据库加载 OHLCV K 线数据。
"""
from __future__ import annotations
import os
import pandas as pd
from sqlalchemy import create_engine, text


def _engine():
    url = "postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}".format(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "binance"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "362232"),
    )
    return create_engine(url)


def load_klines(
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    limit: int = 2000,
) -> pd.DataFrame:
    """
    从数据库读取 K 线，按时间升序排列。

    Returns:
        DataFrame，列：time, open, high, low, close, volume
    """
    sql = """
        SELECT open_time, open, high, low, close, volume
        FROM klines
        WHERE symbol = :symbol AND interval = :interval
        ORDER BY open_time DESC
        LIMIT :limit
    """
    with _engine().connect() as conn:
        df = pd.read_sql(text(sql), conn, params={"symbol": symbol, "interval": interval, "limit": limit})

    df = df.rename(columns={"open_time": "time"})
    df = df.sort_values("time").reset_index(drop=True)

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    return df
