# tests/trading_system/test_config.py
import importlib
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


def test_config_real_mode_is_default(monkeypatch):
    """实盘模式现在是默认配置"""
    monkeypatch.delenv("TRADING_MODE", raising=False)
    import trading_system.config as cfg_module
    importlib.reload(cfg_module)
    from trading_system.config import Config
    cfg = Config()
    assert cfg.trading_mode == "real"


def test_config_fee_rate_defaults():
    from trading_system.config import Config
    cfg = Config()
    assert cfg.fee_rate == 0.0004
    assert cfg.slippage_rate == 0.0005
