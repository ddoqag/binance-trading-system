# tests/trading_system/test_regime_strategy.py
"""
Tests for RegimeAwareLGBMStrategy.

核心逻辑验证：
  TREND   → 阈值放宽（更容易触发信号）
  RANGE   → 阈值收紧（只在高置信度才交易）
  VOLATILE→ 始终返回 HOLD
"""
import pathlib
import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from training_system.model import train_lgbm
from trading_system.regime_strategy import RegimeAwareLGBMStrategy


# ── fixture: 训练一个临时模型 ─────────────────────────────────────────────────

@pytest.fixture(scope="module")
def model_path(tmp_path_factory):
    rng = np.random.default_rng(0)
    X = rng.standard_normal((400, 10))
    y = (X[:, 0] > 0).astype(int)
    model = train_lgbm(X, y, params={"num_leaves": 16}, n_estimators=20)
    path = tmp_path_factory.mktemp("models") / "test.txt"
    model.save_model(str(path))
    return str(path)


def _make_df(n: int = 60, trend: str = "up") -> pd.DataFrame:
    if trend == "up":
        close = np.linspace(100.0, 115.0, n)
    elif trend == "down":
        close = np.linspace(115.0, 100.0, n)
    else:
        close = 100 + np.random.default_rng(1).normal(0, 0.5, n).cumsum()
    return pd.DataFrame({
        "open": close - 0.5, "high": close + 1.0,
        "low": close - 1.0, "close": close,
        "volume": np.ones(n) * 1000.0,
    })


# ── 加载 ─────────────────────────────────────────────────────────────────────

def test_loads_without_error(model_path):
    s = RegimeAwareLGBMStrategy(model_path)
    assert s is not None


# ── 返回值合法 ────────────────────────────────────────────────────────────────

def test_signal_is_valid(model_path):
    s = RegimeAwareLGBMStrategy(model_path)
    sig = s.generate_signal(_make_df())
    assert sig in (-1, 0, 1)


# ── 高波动 → 强制 HOLD ────────────────────────────────────────────────────────

def test_volatile_regime_always_hold(model_path):
    """HIGH_VOLATILITY regime 时，无论模型输出什么，都返回 0。"""
    s = RegimeAwareLGBMStrategy(model_path)

    from ai_trading.market_analyzer import MarketRegime, TrendType
    volatile_analysis = {
        "trend": TrendType.VOLATILE,
        "regime": MarketRegime.HIGH_VOLATILITY,
        "confidence": 0.9,
    }

    with patch.object(s.analyzer, "analyze_trend", return_value=volatile_analysis):
        signals = [s.generate_signal(_make_df()) for _ in range(5)]

    assert all(sig == 0 for sig in signals), f"Expected all HOLD, got {signals}"


# ── 趋势市场 → 阈值应比默认更宽松 ────────────────────────────────────────────

def test_trend_regime_uses_looser_thresholds(model_path):
    """BULL regime 时 buy_threshold 应低于默认值 0.55（更容易买入）。"""
    s = RegimeAwareLGBMStrategy(model_path)

    from ai_trading.market_analyzer import MarketRegime, TrendType
    bull_analysis = {
        "trend": TrendType.UPTREND,
        "regime": MarketRegime.BULL,
        "confidence": 0.8,
    }

    with patch.object(s.analyzer, "analyze_trend", return_value=bull_analysis):
        buy_thr, sell_thr = s._get_thresholds(bull_analysis)

    assert buy_thr < 0.55, f"BULL buy_threshold should be < 0.55, got {buy_thr}"
    assert sell_thr > 0.45, f"BULL sell_threshold should be > 0.45, got {sell_thr}"


# ── 震荡市场 → 阈值更严格 ────────────────────────────────────────────────────

def test_range_regime_uses_tighter_thresholds(model_path):
    """NEUTRAL regime 时阈值应比默认更严格（避免假信号）。"""
    s = RegimeAwareLGBMStrategy(model_path)

    from ai_trading.market_analyzer import MarketRegime, TrendType
    neutral_analysis = {
        "trend": TrendType.SIDEWAYS,
        "regime": MarketRegime.NEUTRAL,
        "confidence": 0.5,
    }

    with patch.object(s.analyzer, "analyze_trend", return_value=neutral_analysis):
        buy_thr, sell_thr = s._get_thresholds(neutral_analysis)

    assert buy_thr > 0.55, f"NEUTRAL buy_threshold should be > 0.55, got {buy_thr}"
    assert sell_thr < 0.45, f"NEUTRAL sell_threshold should be < 0.45, got {sell_thr}"


# ── 置信度低 → 更严格 ─────────────────────────────────────────────────────────

def test_low_confidence_tightens_thresholds(model_path):
    """同样是 BULL，confidence 低时应比 confidence 高时更严格。"""
    s = RegimeAwareLGBMStrategy(model_path)
    from ai_trading.market_analyzer import MarketRegime, TrendType

    high_conf = {"trend": TrendType.UPTREND, "regime": MarketRegime.BULL, "confidence": 0.85}
    low_conf  = {"trend": TrendType.UPTREND, "regime": MarketRegime.BULL, "confidence": 0.55}

    buy_high, _ = s._get_thresholds(high_conf)
    buy_low,  _ = s._get_thresholds(low_conf)

    assert buy_low > buy_high, "低置信度应要求更高的 buy_threshold"


# ── analyze_trend 出错时降级为 HOLD ──────────────────────────────────────────

def test_analyzer_error_returns_hold(model_path):
    s = RegimeAwareLGBMStrategy(model_path)
    with patch.object(s.analyzer, "analyze_trend", side_effect=Exception("network error")):
        sig = s.generate_signal(_make_df())
    assert sig == 0
