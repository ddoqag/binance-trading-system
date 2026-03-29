# Trading System Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a minimum viable trading loop that runs paper trades 24/7 without crashing, with position state machine and ATR-based risk control.

**Architecture:** Rule-based MA crossover strategy → Position state machine (NONE/LONG/SHORT) → ATR dynamic stop loss + three circuit breakers → Paper executor. No ML, no LLM in this phase. Each component is independently testable.

**Tech Stack:** Python 3.10+, requests, pandas, numpy, python-dotenv, pytest

**Spec:** `docs/superpowers/specs/2026-03-22-quant-trading-system-design.md`

---

## Chunk 1: Project Skeleton + Config

### Task 1: Project skeleton and config

**Files:**
- Create: `trading_system/__init__.py`
- Create: `trading_system/config.py`
- Modify: `.env.example`
- Create: `tests/trading_system/__init__.py`
- Create: `tests/trading_system/test_config.py`

- [ ] **Step 1: Add new env vars to `.env.example`**

```bash
# 量化交易系统 - Phase 1
TRADING_MODE=paper
TRADING_SYMBOL=BTCUSDT
TRADING_INTERVAL=1h
INITIAL_BALANCE=10000
KIMI_API_KEY=
```

- [ ] **Step 2: Create `trading_system/__init__.py`** (empty)

- [ ] **Step 3: Write failing test for config**

Create `tests/trading_system/__init__.py` (empty), then:

```python
# tests/trading_system/test_config.py
import os
import pytest

def test_config_loads_defaults(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("TRADING_SYMBOL", "BTCUSDT")
    monkeypatch.setenv("INITIAL_BALANCE", "10000")

    from trading_system.config import Config
    cfg = Config()

    assert cfg.trading_mode == "paper"
    assert cfg.symbol == "BTCUSDT"
    assert cfg.initial_balance == 10000.0
    assert cfg.risk_per_trade == 0.01
    assert cfg.max_daily_loss == 0.05
    assert cfg.max_loss_streak == 5
    assert cfg.atr_sl_multiplier == 1.5
    assert cfg.atr_tp_multiplier == 2.5

def test_config_paper_mode_is_default(monkeypatch):
    monkeypatch.delenv("TRADING_MODE", raising=False)
    from trading_system import config as cfg_module
    import importlib
    importlib.reload(cfg_module)
    from trading_system.config import Config
    cfg = Config()
    assert cfg.trading_mode == "paper"
```

- [ ] **Step 4: Run test to verify it fails**

```bash
pytest tests/trading_system/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'trading_system.config'`

- [ ] **Step 5: Implement `trading_system/config.py`**

```python
# trading_system/config.py
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    symbol: str = None
    interval: str = None
    trading_mode: str = None
    initial_balance: float = None

    # Risk parameters
    risk_per_trade: float = 0.01
    max_daily_loss: float = 0.05
    max_loss_streak: int = 5
    atr_sl_multiplier: float = 1.5
    atr_tp_multiplier: float = 2.5
    atr_period: int = 14

    def __post_init__(self):
        self.symbol = self.symbol or os.getenv("TRADING_SYMBOL", "BTCUSDT")
        self.interval = self.interval or os.getenv("TRADING_INTERVAL", "1h")
        self.trading_mode = self.trading_mode or os.getenv("TRADING_MODE", "paper")
        self.initial_balance = self.initial_balance or float(
            os.getenv("INITIAL_BALANCE", "10000")
        )
```

- [ ] **Step 6: Run test to verify it passes**

```bash
pytest tests/trading_system/test_config.py -v
```

Expected: PASSED (2 tests)

- [ ] **Step 7: Commit**

```bash
git add trading_system/__init__.py trading_system/config.py \
        tests/trading_system/__init__.py tests/trading_system/test_config.py \
        .env.example
git commit -m "feat: add trading_system Phase 1 skeleton and config"
```

---

## Chunk 2: Data Feed + Features

### Task 2: Binance K-line data feed

**Files:**
- Create: `trading_system/data_feed.py`
- Create: `tests/trading_system/test_data_feed.py`

- [ ] **Step 1: Write failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/trading_system/test_data_feed.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `trading_system/data_feed.py`**

```python
# trading_system/data_feed.py
import requests
import pandas as pd
import os

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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/trading_system/test_data_feed.py -v
```

Expected: PASSED (2 tests)

- [ ] **Step 5: Commit**

```bash
git add trading_system/data_feed.py tests/trading_system/test_data_feed.py
git commit -m "feat: add Binance K-line data feed"
```

---

### Task 3: Alpha features (MA5, MA20, ATR, RSI)

**Files:**
- Create: `trading_system/features.py`
- Create: `tests/trading_system/test_features.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/trading_system/test_features.py
import pandas as pd
import numpy as np
import pytest
from tests.trading_system.test_data_feed import MOCK_KLINES


def make_df(n=30):
    """Generate synthetic OHLCV DataFrame for testing."""
    np.random.seed(42)
    close = 40000 + np.cumsum(np.random.randn(n) * 100)
    high = close + np.abs(np.random.randn(n) * 50)
    low = close - np.abs(np.random.randn(n) * 50)
    return pd.DataFrame({
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "volume": np.random.rand(n) * 1000,
    })


def test_add_features_returns_required_columns():
    from trading_system.features import add_features
    df = make_df(30)
    result = add_features(df)
    for col in ["ma5", "ma20", "atr", "rsi"]:
        assert col in result.columns, f"Missing column: {col}"


def test_ma5_values_correct():
    from trading_system.features import add_features
    df = make_df(30)
    result = add_features(df)
    expected_ma5 = df["close"].rolling(5).mean()
    pd.testing.assert_series_equal(
        result["ma5"].dropna(), expected_ma5.dropna(), check_names=False
    )


def test_atr_is_positive():
    from trading_system.features import add_features
    df = make_df(30)
    result = add_features(df)
    assert (result["atr"].dropna() > 0).all()


def test_rsi_range():
    from trading_system.features import add_features
    df = make_df(50)
    result = add_features(df)
    rsi_values = result["rsi"].dropna()
    assert (rsi_values >= 0).all() and (rsi_values <= 100).all()


def test_add_features_does_not_mutate_input():
    from trading_system.features import add_features
    df = make_df(30)
    original_cols = list(df.columns)
    add_features(df)
    assert list(df.columns) == original_cols
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/trading_system/test_features.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `trading_system/features.py`**

```python
# trading_system/features.py
import pandas as pd
import numpy as np


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add MA5, MA20, ATR(14), RSI(14) to a copy of the DataFrame."""
    df = df.copy()

    df["ma5"] = df["close"].rolling(5).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["atr"] = _compute_atr(df, period=14)
    df["rsi"] = _compute_rsi(df["close"], period=14)

    return df


def _compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/trading_system/test_features.py -v
```

Expected: PASSED (5 tests)

- [ ] **Step 5: Commit**

```bash
git add trading_system/features.py tests/trading_system/test_features.py
git commit -m "feat: add Alpha features (MA5, MA20, ATR, RSI)"
```

---

## Chunk 3: Position State Machine

### Task 4: Position state machine

**Files:**
- Create: `trading_system/position.py`
- Create: `tests/trading_system/test_position.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/trading_system/test_position.py
import pytest


def test_initial_state_is_none():
    from trading_system.position import PositionManager
    pm = PositionManager()
    assert pm.is_flat()
    assert not pm.is_long()
    assert not pm.is_short()
    assert pm.entry_price is None
    assert pm.size == 0.0


def test_open_long():
    from trading_system.position import PositionManager
    pm = PositionManager()
    pm.open_long(price=43000.0, size=0.01)
    assert pm.is_long()
    assert pm.entry_price == 43000.0
    assert pm.size == 0.01


def test_open_short():
    from trading_system.position import PositionManager
    pm = PositionManager()
    pm.open_short(price=43000.0, size=0.01)
    assert pm.is_short()
    assert not pm.is_flat()


def test_close_returns_to_flat():
    from trading_system.position import PositionManager
    pm = PositionManager()
    pm.open_long(price=43000.0, size=0.01)
    pm.close()
    assert pm.is_flat()
    assert pm.entry_price is None
    assert pm.size == 0.0


def test_cannot_open_long_when_already_long():
    from trading_system.position import PositionManager, PositionError
    pm = PositionManager()
    pm.open_long(price=43000.0, size=0.01)
    with pytest.raises(PositionError, match="already long"):
        pm.open_long(price=44000.0, size=0.01)


def test_cannot_open_short_when_already_short():
    from trading_system.position import PositionManager, PositionError
    pm = PositionManager()
    pm.open_short(price=43000.0, size=0.01)
    with pytest.raises(PositionError, match="already short"):
        pm.open_short(price=42000.0, size=0.01)


def test_pnl_long_position():
    from trading_system.position import PositionManager
    pm = PositionManager()
    pm.open_long(price=40000.0, size=0.1)
    pnl = pm.unrealized_pnl(current_price=41000.0)
    assert abs(pnl - 100.0) < 0.01  # 0.1 BTC × $1000 move = $100


def test_pnl_flat_is_zero():
    from trading_system.position import PositionManager
    pm = PositionManager()
    assert pm.unrealized_pnl(current_price=43000.0) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/trading_system/test_position.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `trading_system/position.py`**

```python
# trading_system/position.py
from enum import Enum


class PositionState(Enum):
    NONE = 0
    LONG = 1
    SHORT = -1


class PositionError(Exception):
    pass


class PositionManager:
    """State machine: NONE → LONG/SHORT → NONE. Prevents duplicate opens."""

    def __init__(self):
        self._state = PositionState.NONE
        self.entry_price: float | None = None
        self.size: float = 0.0

    def open_long(self, price: float, size: float) -> None:
        if self._state == PositionState.LONG:
            raise PositionError("already long — close before opening again")
        self._state = PositionState.LONG
        self.entry_price = price
        self.size = size

    def open_short(self, price: float, size: float) -> None:
        if self._state == PositionState.SHORT:
            raise PositionError("already short — close before opening again")
        self._state = PositionState.SHORT
        self.entry_price = price
        self.size = size

    def close(self) -> None:
        self._state = PositionState.NONE
        self.entry_price = None
        self.size = 0.0

    def is_flat(self) -> bool:
        return self._state == PositionState.NONE

    def is_long(self) -> bool:
        return self._state == PositionState.LONG

    def is_short(self) -> bool:
        return self._state == PositionState.SHORT

    def unrealized_pnl(self, current_price: float) -> float:
        if self.is_flat():
            return 0.0
        direction = 1 if self.is_long() else -1
        return direction * (current_price - self.entry_price) * self.size
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/trading_system/test_position.py -v
```

Expected: PASSED (8 tests)

- [ ] **Step 5: Commit**

```bash
git add trading_system/position.py tests/trading_system/test_position.py
git commit -m "feat: add Position state machine (NONE/LONG/SHORT)"
```

---

## Chunk 4: Risk Manager

### Task 5: ATR-based risk manager with circuit breakers

**Files:**
- Create: `trading_system/risk_manager.py`
- Create: `tests/trading_system/test_risk_manager.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/trading_system/test_risk_manager.py
import pytest


def make_risk_manager(balance=10000.0):
    from trading_system.config import Config
    from trading_system.risk_manager import RiskManager
    cfg = Config()
    cfg.initial_balance = balance
    return RiskManager(config=cfg, initial_balance=balance)


def test_position_size_uses_atr():
    rm = make_risk_manager(10000.0)
    # risk_amount = 10000 * 0.01 = 100
    # stop_distance = 1.5 * 200 = 300
    # size = 100 / 300 ≈ 0.3333
    size = rm.calc_position_size(price=40000.0, atr=200.0)
    assert abs(size - 100.0 / 300.0) < 0.0001


def test_sl_tp_for_long():
    rm = make_risk_manager()
    sl, tp = rm.get_sl_tp(price=40000.0, atr=200.0, side="BUY")
    assert sl == pytest.approx(40000.0 - 1.5 * 200.0)
    assert tp == pytest.approx(40000.0 + 2.5 * 200.0)


def test_sl_tp_for_short():
    rm = make_risk_manager()
    sl, tp = rm.get_sl_tp(price=40000.0, atr=200.0, side="SELL")
    assert sl == pytest.approx(40000.0 + 1.5 * 200.0)
    assert tp == pytest.approx(40000.0 - 2.5 * 200.0)


def test_circuit_breaker_daily_loss():
    rm = make_risk_manager(10000.0)
    rm.record_trade_pnl(-600.0)  # > 5% of 10000
    assert not rm.check_risk_limits()


def test_circuit_breaker_loss_streak():
    rm = make_risk_manager()
    for _ in range(5):
        rm.record_trade_pnl(-10.0)
    assert not rm.check_risk_limits()


def test_circuit_breaker_passes_normally():
    rm = make_risk_manager()
    rm.record_trade_pnl(-100.0)  # small loss, no streak
    assert rm.check_risk_limits()


def test_reset_daily_resets_loss_only():
    rm = make_risk_manager(10000.0)
    rm.record_trade_pnl(-600.0)
    rm.reset_daily()
    assert rm.check_risk_limits()
    # loss_streak survives reset
    assert rm._loss_streak == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/trading_system/test_risk_manager.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `trading_system/risk_manager.py`**

```python
# trading_system/risk_manager.py
from __future__ import annotations
from trading_system.config import Config


class RiskManager:
    """ATR-based position sizing + three circuit breakers."""

    def __init__(self, config: Config, initial_balance: float):
        self._cfg = config
        self._balance = initial_balance
        self._daily_pnl: float = 0.0
        self._loss_streak: int = 0

    def calc_position_size(self, price: float, atr: float) -> float:
        """Kelly-inspired sizing: risk 1% of balance per ATR stop distance."""
        risk_amount = self._balance * self._cfg.risk_per_trade
        stop_distance = self._cfg.atr_sl_multiplier * atr
        if stop_distance <= 0:
            return 0.0
        return risk_amount / stop_distance

    def get_sl_tp(
        self, price: float, atr: float, side: str
    ) -> tuple[float, float]:
        """Return (stop_loss, take_profit) for the given side."""
        sl_dist = self._cfg.atr_sl_multiplier * atr
        tp_dist = self._cfg.atr_tp_multiplier * atr
        if side == "BUY":
            return price - sl_dist, price + tp_dist
        return price + sl_dist, price - tp_dist

    def record_trade_pnl(self, pnl: float) -> None:
        self._daily_pnl += pnl
        self._balance += pnl
        if pnl < 0:
            self._loss_streak += 1
        else:
            self._loss_streak = 0

    def check_risk_limits(self) -> bool:
        """Return False if any circuit breaker is triggered."""
        if self._daily_pnl < -self._cfg.max_daily_loss * self._balance:
            return False
        if self._loss_streak >= self._cfg.max_loss_streak:
            return False
        return True

    def reset_daily(self) -> None:
        """Call at start of each trading day."""
        self._daily_pnl = 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/trading_system/test_risk_manager.py -v
```

Expected: PASSED (7 tests)

- [ ] **Step 5: Commit**

```bash
git add trading_system/risk_manager.py tests/trading_system/test_risk_manager.py
git commit -m "feat: add ATR risk manager with three circuit breakers"
```

---

## Chunk 5: Strategy + Executor + Main Loop

### Task 6: MA crossover strategy

**Files:**
- Create: `trading_system/strategy.py`
- Create: `tests/trading_system/test_strategy.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/trading_system/test_strategy.py
import pandas as pd
import numpy as np


def make_trending_df(n=30, direction="up"):
    """DataFrame where MA5 clearly crosses MA20."""
    if direction == "up":
        close = np.linspace(39000, 45000, n)
    else:
        close = np.linspace(45000, 39000, n)
    return pd.DataFrame({
        "close": close,
        "ma5": pd.Series(close).rolling(5).mean().values,
        "ma20": pd.Series(close).rolling(20).mean().values,
        "atr": np.full(n, 200.0),
        "rsi": np.full(n, 50.0),
    })


def test_golden_cross_returns_buy():
    from trading_system.strategy import MACrossStrategy
    df = make_trending_df(30, "up")
    strategy = MACrossStrategy()
    signal = strategy.generate_signal(df)
    assert signal == 1


def test_death_cross_returns_sell():
    from trading_system.strategy import MACrossStrategy
    df = make_trending_df(30, "down")
    strategy = MACrossStrategy()
    signal = strategy.generate_signal(df)
    assert signal == -1


def test_flat_market_returns_hold():
    from trading_system.strategy import MACrossStrategy
    n = 30
    close = np.full(n, 43000.0)
    df = pd.DataFrame({
        "close": close,
        "ma5": close,
        "ma20": close,
        "atr": np.full(n, 200.0),
        "rsi": np.full(n, 50.0),
    })
    strategy = MACrossStrategy()
    signal = strategy.generate_signal(df)
    assert signal == 0


def test_insufficient_data_returns_hold():
    from trading_system.strategy import MACrossStrategy
    df = pd.DataFrame({"close": [43000.0], "ma5": [None], "ma20": [None],
                       "atr": [200.0], "rsi": [50.0]})
    strategy = MACrossStrategy()
    assert strategy.generate_signal(df) == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/trading_system/test_strategy.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `trading_system/strategy.py`**

```python
# trading_system/strategy.py
import pandas as pd


class MACrossStrategy:
    """
    Golden cross (MA5 > MA20): BUY signal (+1)
    Death cross (MA5 < MA20): SELL signal (-1)
    No cross / insufficient data: HOLD (0)

    Designed as a plug-in interface — replace with LightGBM in Phase 2.
    """

    def generate_signal(self, df: pd.DataFrame) -> int:
        if len(df) < 20:
            return 0

        last = df.iloc[-1]
        ma5 = last.get("ma5")
        ma20 = last.get("ma20")

        if pd.isna(ma5) or pd.isna(ma20):
            return 0

        if ma5 > ma20:
            return 1   # BUY
        elif ma5 < ma20:
            return -1  # SELL
        return 0       # HOLD
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/trading_system/test_strategy.py -v
```

Expected: PASSED (4 tests)

- [ ] **Step 5: Commit**

```bash
git add trading_system/strategy.py tests/trading_system/test_strategy.py
git commit -m "feat: add MA crossover strategy (plug-in interface)"
```

---

### Task 7: Paper executor

**Files:**
- Create: `trading_system/executor.py`
- Create: `tests/trading_system/test_executor.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/trading_system/test_executor.py
import pytest


def test_paper_buy_returns_order_dict():
    from trading_system.executor import PaperExecutor
    ex = PaperExecutor()
    order = ex.buy(symbol="BTCUSDT", quantity=0.01, price=43000.0)
    assert order["side"] == "BUY"
    assert order["symbol"] == "BTCUSDT"
    assert order["quantity"] == 0.01
    assert order["status"] == "FILLED"
    assert "timestamp" in order


def test_paper_sell_returns_order_dict():
    from trading_system.executor import PaperExecutor
    ex = PaperExecutor()
    order = ex.sell(symbol="BTCUSDT", quantity=0.01, price=43000.0)
    assert order["side"] == "SELL"
    assert order["status"] == "FILLED"


def test_paper_executor_tracks_orders():
    from trading_system.executor import PaperExecutor
    ex = PaperExecutor()
    ex.buy("BTCUSDT", 0.01, 43000.0)
    ex.sell("BTCUSDT", 0.01, 44000.0)
    assert len(ex.order_history) == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/trading_system/test_executor.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `trading_system/executor.py`**

```python
# trading_system/executor.py
from __future__ import annotations
import time
import logging
from typing import Any

logger = logging.getLogger(__name__)


class PaperExecutor:
    """
    Simulates order execution with logging.
    Switch to LiveExecutor (future) via TRADING_MODE=live.
    """

    def __init__(self):
        self.order_history: list[dict[str, Any]] = []

    def buy(self, symbol: str, quantity: float, price: float) -> dict:
        return self._place("BUY", symbol, quantity, price)

    def sell(self, symbol: str, quantity: float, price: float) -> dict:
        return self._place("SELL", symbol, quantity, price)

    def _place(
        self, side: str, symbol: str, quantity: float, price: float
    ) -> dict:
        order = {
            "side": side,
            "symbol": symbol,
            "quantity": quantity,
            "price": price,
            "status": "FILLED",
            "timestamp": int(time.time() * 1000),
            "mode": "paper",
        }
        self.order_history.append(order)
        logger.info(
            "[PAPER] %s %s qty=%.4f price=%.2f", side, symbol, quantity, price
        )
        return order
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/trading_system/test_executor.py -v
```

Expected: PASSED (3 tests)

- [ ] **Step 5: Commit**

```bash
git add trading_system/executor.py tests/trading_system/test_executor.py
git commit -m "feat: add paper executor with order history"
```

---

### Task 8: Main trading loop

**Files:**
- Create: `trading_system/trader.py`
- Create: `tests/trading_system/test_trader.py`

- [ ] **Step 1: Write failing integration test**

```python
# tests/trading_system/test_trader.py
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock


def make_mock_df(signal_direction="up"):
    n = 30
    if signal_direction == "up":
        close = np.linspace(39000, 45000, n)
    else:
        close = np.linspace(45000, 39000, n)
    df = pd.DataFrame({
        "time": range(n),
        "open": close, "high": close + 100,
        "low": close - 100, "close": close,
        "volume": np.ones(n) * 100,
    })
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["atr"] = 200.0
    df["rsi"] = 50.0
    return df


def test_trader_opens_long_on_buy_signal():
    with patch("trading_system.trader.get_klines") as mock_feed, \
         patch("trading_system.trader.add_features") as mock_feat:

        mock_feed.return_value = make_mock_df("up")
        mock_feat.side_effect = lambda df: df  # features already in df

        from trading_system.config import Config
        from trading_system.trader import Trader

        cfg = Config()
        trader = Trader(cfg)
        trader.step()

        assert trader.position.is_long()


def test_trader_does_not_open_twice():
    with patch("trading_system.trader.get_klines") as mock_feed, \
         patch("trading_system.trader.add_features") as mock_feat:

        mock_feed.return_value = make_mock_df("up")
        mock_feat.side_effect = lambda df: df

        from trading_system.config import Config
        from trading_system.trader import Trader

        cfg = Config()
        trader = Trader(cfg)
        trader.step()
        trader.step()  # second step — should not open again

        assert trader.position.is_long()
        assert len(trader.executor.order_history) == 1


def test_trader_stops_on_circuit_breaker():
    with patch("trading_system.trader.get_klines") as mock_feed, \
         patch("trading_system.trader.add_features") as mock_feat:

        mock_feed.return_value = make_mock_df("up")
        mock_feat.side_effect = lambda df: df

        from trading_system.config import Config
        from trading_system.trader import Trader

        cfg = Config()
        trader = Trader(cfg)
        # Trigger circuit breaker manually
        trader.risk.record_trade_pnl(-600.0)
        trader.step()

        assert trader.position.is_flat()
        assert len(trader.executor.order_history) == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/trading_system/test_trader.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `trading_system/trader.py`**

```python
# trading_system/trader.py
import time
import logging

from trading_system.config import Config
from trading_system.data_feed import get_klines
from trading_system.features import add_features
from trading_system.strategy import MACrossStrategy
from trading_system.position import PositionManager
from trading_system.risk_manager import RiskManager
from trading_system.executor import PaperExecutor

logger = logging.getLogger(__name__)


class Trader:
    """
    Main trading loop. Calls step() every interval.
    Replace strategy with LightGBM in Phase 2.
    """

    def __init__(self, config: Config):
        self.cfg = config
        self.strategy = MACrossStrategy()
        self.position = PositionManager()
        self.risk = RiskManager(config, config.initial_balance)
        self.executor = PaperExecutor()

    def step(self) -> None:
        """One trading cycle: fetch → features → signal → risk → execute."""
        if not self.risk.check_risk_limits():
            logger.warning("Circuit breaker triggered — skipping this step")
            return

        try:
            df_raw = get_klines(self.cfg.symbol, self.cfg.interval, limit=100)
            df = add_features(df_raw)
        except Exception as e:
            logger.error("Data fetch failed: %s", e)
            return

        signal = self.strategy.generate_signal(df)
        last = df.iloc[-1]
        price = float(last["close"])
        atr = float(last["atr"]) if not __import__("math").isnan(last["atr"]) else 0.0

        if atr <= 0:
            return

        size = self.risk.calc_position_size(price=price, atr=atr)

        self._execute_signal(signal=signal, price=price, size=size)

    def _execute_signal(self, signal: int, price: float, size: float) -> None:
        if self.position.is_flat():
            if signal == 1:
                self.executor.buy(self.cfg.symbol, size, price)
                self.position.open_long(price, size)
            elif signal == -1:
                self.executor.sell(self.cfg.symbol, size, price)
                self.position.open_short(price, size)

        elif self.position.is_long() and signal == -1:
            self.executor.sell(self.cfg.symbol, self.position.size, price)
            pnl = self.position.unrealized_pnl(price)
            self.risk.record_trade_pnl(pnl)
            self.position.close()

        elif self.position.is_short() and signal == 1:
            self.executor.buy(self.cfg.symbol, self.position.size, price)
            pnl = self.position.unrealized_pnl(price)
            self.risk.record_trade_pnl(pnl)
            self.position.close()

    def run(self, interval_seconds: int = 60) -> None:
        """Blocking loop. Ctrl+C to stop."""
        logger.info(
            "Starting trader — symbol=%s mode=%s",
            self.cfg.symbol, self.cfg.trading_mode
        )
        while True:
            self.step()
            time.sleep(interval_seconds)


if __name__ == "__main__":
    import os
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    cfg = Config()
    Trader(cfg).run()
```

- [ ] **Step 4: Run all tests to verify they pass**

```bash
pytest tests/trading_system/ -v
```

Expected: ALL PASSED (≥ 25 tests)

- [ ] **Step 5: Commit**

```bash
git add trading_system/trader.py tests/trading_system/test_trader.py
git commit -m "feat: add main trading loop (Trader.step + Trader.run)"
```

---

## Chunk 6: Integration Smoke Test + Dependencies

### Task 9: Install dependencies and smoke test

**Files:**
- Modify: `requirements.txt` (or create if missing)

- [ ] **Step 1: Check existing requirements**

```bash
cat requirements.txt 2>/dev/null || echo "not found"
```

- [ ] **Step 2: Add Phase 1 dependencies**

Add to `requirements.txt` (keep existing entries):

```
# trading_system Phase 1
requests>=2.31.0
pandas>=2.0.0
numpy>=1.24.0
python-dotenv>=1.0.0
lightgbm>=4.0.0
pytest>=7.4.0
pytest-mock>=3.11.0
```

- [ ] **Step 3: Install**

```bash
pip install requests pandas numpy python-dotenv pytest pytest-mock
```

- [ ] **Step 4: Run full test suite**

```bash
pytest tests/trading_system/ -v --tb=short
```

Expected: ALL PASSED

- [ ] **Step 5: Verify Phase 1 acceptance criteria**

```bash
# 手动验证清单（paper mode，不需要真实API密钥）
python -c "
from trading_system.config import Config
from trading_system.position import PositionManager
from trading_system.risk_manager import RiskManager

cfg = Config()
pm = PositionManager()
rm = RiskManager(cfg, 10000)

# 验证不能重复开仓
pm.open_long(43000, 0.01)
try:
    pm.open_long(43000, 0.01)
    print('FAIL: duplicate open not prevented')
except Exception:
    print('PASS: duplicate open blocked')

# 验证熔断
rm.record_trade_pnl(-600)
print('PASS: circuit breaker triggered =', not rm.check_risk_limits())
"
```

- [ ] **Step 6: Final commit**

```bash
git add requirements.txt
git commit -m "chore: add Phase 1 dependencies to requirements.txt"
```

---

## Phase 1 Completion Checklist

- [ ] All tests pass: `pytest tests/trading_system/ -v`
- [ ] No duplicate open positions possible (PositionError raised)
- [ ] Circuit breakers work (daily loss, loss streak)
- [ ] ATR-based position sizing returns non-zero value
- [ ] Paper executor logs orders without crashing
- [ ] Main loop `Trader.step()` handles data fetch errors gracefully

**Next Step → Phase 2:** Replace `MACrossStrategy` with `LightGBM` model from `training_system/`.
