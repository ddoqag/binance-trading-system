# tests/trading_system/test_monitor.py
import pytest
from trading_system.monitor import EquityMonitor


# ── 基础功能 ──────────────────────────────────────────────────────────────────

def test_initial_state():
    m = EquityMonitor(initial_equity=10000.0)
    assert m.current_equity == 10000.0
    assert m.peak_equity == 10000.0
    assert m.max_drawdown() == 0.0


def test_equity_update():
    m = EquityMonitor(10000.0)
    m.update(10500.0)
    assert m.current_equity == 10500.0
    assert m.peak_equity == 10500.0


def test_drawdown_calculation():
    """10000 → 9000 应该是 -10% 回撤。"""
    m = EquityMonitor(10000.0)
    m.update(9000.0)
    assert abs(m.max_drawdown() - (-0.10)) < 1e-6


def test_peak_does_not_fall():
    """净值回落后 peak 保持历史最高。"""
    m = EquityMonitor(10000.0)
    m.update(12000.0)
    m.update(11000.0)
    assert m.peak_equity == 12000.0
    assert m.max_drawdown() < 0


def test_equity_curve_records_all():
    m = EquityMonitor(10000.0)
    for v in [10100, 10200, 9800]:
        m.update(v)
    assert len(m.equity_curve) == 4   # 初始 + 3次更新


# ── 日盈亏 ────────────────────────────────────────────────────────────────────

def test_daily_pnl_tracks_today():
    m = EquityMonitor(10000.0)
    m.record_trade_pnl(200.0)
    m.record_trade_pnl(-50.0)
    assert abs(m.daily_pnl() - 150.0) < 1e-6


def test_daily_pnl_reset():
    m = EquityMonitor(10000.0)
    m.record_trade_pnl(300.0)
    m.reset_daily()
    assert m.daily_pnl() == 0.0


# ── 警报触发 ──────────────────────────────────────────────────────────────────

def test_no_alert_in_normal_conditions():
    m = EquityMonitor(10000.0, drawdown_alert=-0.10, daily_loss_alert=-0.05)
    m.update(9500.0)   # -5%，未超阈值
    assert not m.should_alert()


def test_drawdown_alert_triggers():
    m = EquityMonitor(10000.0, drawdown_alert=-0.10)
    m.update(8900.0)   # -11%，超过阈值
    assert m.should_alert()


def test_daily_loss_alert_triggers():
    m = EquityMonitor(10000.0, daily_loss_alert=-0.05)
    m.record_trade_pnl(-600.0)   # 日亏损 -6%
    assert m.should_alert()


# ── summary ───────────────────────────────────────────────────────────────────

def test_summary_contains_required_keys():
    m = EquityMonitor(10000.0)
    m.update(10200.0)
    m.record_trade_pnl(200.0)
    s = m.summary()
    for key in ("equity", "peak", "drawdown", "daily_pnl", "alert"):
        assert key in s
