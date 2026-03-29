# portfolio_system/portfolio_trader.py
"""
多策略 PortfolioTrader（Phase 3 顶级版）。

架构：
  ┌─────────────────────────────────────────┐
  │  数据获取 (get_klines)                  │
  └──────────────┬──────────────────────────┘
                 ↓
  ┌──────────────────────────────────────────┐
  │  策略池（可配置）                         │
  │  [0] AlphaStrategy（规则，快速）          │
  │  [1] RegimeAwareLGBMStrategy（ML+Regime）│
  └──────────────┬───────────────────────────┘
                 ↓ signals[]
  ┌──────────────────────────────────────────┐
  │  BanditAllocator (EXP3 RL)               │
  │  → combined_score = Σ w[i] * signal[i]  │
  │  → 平仓后用 realized PnL 更新权重         │
  └──────────────┬───────────────────────────┘
                 ↓ final_signal ∈ {-1, 0, +1}
  ┌──────────────────────────────────────────┐
  │  RiskManager + PositionManager           │
  │  + EquityMonitor                         │
  └──────────────────────────────────────────┘

信号融合规则：
  score > +entry_threshold  → BUY  (+1)
  score < -entry_threshold  → SELL (-1)
  else                      → HOLD (0)

Bandit 更新：
  - 每次平仓后，用 pnl / initial_balance 作为 reward
  - 更新的是"上次触发信号的策略"（last_active_arm）
"""
from __future__ import annotations
import logging
import math
import time

import numpy as np
import pandas as pd

from trading_system.config import Config
from trading_system.data_feed import get_klines
from trading_system.strategy import AlphaStrategy
from risk.position import PositionManager
from risk.manager import RiskManager, RiskConfig
from trading.leverage_executor import LeverageTradingExecutor, OrderSide, OrderType
from trading_system.monitor import EquityMonitor
from portfolio_system.bandit_allocator import BanditAllocator

logger = logging.getLogger(__name__)

# 信号融合的开仓阈值（加权分数绝对值超过此值才入场）
_ENTRY_THRESHOLD = 0.3


class PortfolioTrader:
    """
    多策略 + EXP3 Bandit 分配的交易循环。

    Args:
        config:           交易配置。
        strategies:       策略列表，每个策略需实现 generate_signal(df) -> int。
                          默认：[AlphaStrategy, RegimeAwareLGBMStrategy（若模型存在）]
        entry_threshold:  信号融合分数的开仓阈值（默认 0.3）。
        bandit_lr:        EXP3 学习率（默认 0.05）。
    """

    def __init__(
        self,
        config: Config,
        strategies: list | None = None,
        entry_threshold: float = _ENTRY_THRESHOLD,
        bandit_lr: float = 0.05,
        binance_client=None,
    ) -> None:
        self.cfg = config
        self.entry_threshold = entry_threshold

        # ── 策略池 ──────────────────────────────────────────────────────────
        if strategies is not None:
            self.strategies = strategies
        else:
            self.strategies = self._build_default_strategies()

        # ── Bandit 分配器 ────────────────────────────────────────────────────
        self.allocator = BanditAllocator(
            n_arms=len(self.strategies),
            learning_rate=bandit_lr,
        )

        # ── 交易基础组件 ─────────────────────────────────────────────────────
        max_position_size = getattr(config, 'max_position_size', 0.8)
        max_single_position = getattr(config, 'max_single_position', 0.2)
        self.position = PositionManager(
            max_position_size=max_position_size,
            max_single_position=max_single_position,
            total_capital=config.initial_balance
        )
        self.risk = RiskManager(
            config=RiskConfig(
                max_position_size=max_position_size,
                max_single_position=max_single_position,
                total_capital=config.initial_balance
            )
        )
        # 使用统一杠杆执行器，非杠杆模式设置 leverage=1.0
        self.executor = LeverageTradingExecutor(
            initial_margin=config.initial_balance,
            max_leverage=1.0,  # 非杠杆模式
            commission_rate=config.fee_rate,
            slippage=config.slippage_rate,
            binance_client=binance_client
        )
        self.monitor = EquityMonitor(
            initial_equity=config.initial_balance,
            drawdown_alert=-0.10,
            daily_loss_alert=-0.05,
        )

        # 记录上次触发信号的策略索引（用于 Bandit 更新）
        self._last_active_arm: int | None = None

    # ── 主循环 ────────────────────────────────────────────────────────────────

    def step(self) -> None:
        """一个交易周期：获取数据 → 多策略信号 → Bandit 融合 → 风控 → 执行。"""
        can_trade, reason = self.risk.can_trade(self.cfg.symbol, "BUY", 0, 0)
        if not can_trade:
            logger.warning("Circuit breaker triggered — %s", reason)
            return

        try:
            df = get_klines(self.cfg.symbol, self.cfg.interval, limit=100)
        except Exception as exc:
            logger.error("Data fetch failed: %s", exc)
            return

        # ── 1. 获取各策略信号 ────────────────────────────────────────────────
        signals = []
        for i, strategy in enumerate(self.strategies):
            try:
                sig = strategy.generate_signal(df)
            except Exception as exc:
                logger.warning("Strategy %d error: %s — using HOLD", i, exc)
                sig = 0
            signals.append(sig)

        # ── 2. Bandit 融合 ───────────────────────────────────────────────────
        score = self.allocator.combined_score(signals)
        final_signal = self._score_to_signal(score)

        # 记录哪个策略对本次信号贡献最大（用于后续 Bandit 更新）
        if final_signal != 0:
            self._last_active_arm = int(np.argmax(
                self.allocator.weights * np.abs(signals)
            ))

        logger.debug(
            "signals=%s weights=%s score=%.3f → signal=%d",
            signals,
            [f"{w:.3f}" for w in self.allocator.weights],
            score, final_signal,
        )

        # ── 3. ATR 风控 ──────────────────────────────────────────────────────
        from trading_system.features import add_features
        df_feat = add_features(df)
        last = df_feat.iloc[-1]
        price = float(last["close"])
        atr_val = last.get("atr")

        if atr_val is None or math.isnan(float(atr_val)) or float(atr_val) <= 0:
            return

        atr = float(atr_val)
        size = self._calc_position_size(price=price, atr=atr)
        if size <= 0:
            return

        self._execute_signal(final_signal, price, size)

    def run(self, interval_seconds: int = 60) -> None:
        """阻塞式主循环，Ctrl+C 退出。"""
        logger.info(
            "PortfolioTrader started | strategies=%d symbol=%s balance=%.2f",
            len(self.strategies), self.cfg.symbol, self.cfg.initial_balance,
        )
        while True:
            self.step()
            time.sleep(interval_seconds)

    # ── 内部方法 ──────────────────────────────────────────────────────────────

    def _score_to_signal(self, score: float) -> int:
        if score > self.entry_threshold:
            return 1
        if score < -self.entry_threshold:
            return -1
        return 0

    def _calc_position_size(self, price: float, atr: float) -> float:
        """ATR-based position sizing."""
        risk_amount = self.cfg.initial_balance * self.cfg.risk_per_trade
        stop_distance = self.cfg.atr_sl_multiplier * atr
        if stop_distance <= 0:
            return 0.0
        return risk_amount / stop_distance

    def _execute_signal(self, signal: int, price: float, size: float) -> None:
        """仓位状态机 + Bandit 更新。"""
        symbol = self.cfg.symbol
        pos = self.position.get_position(symbol)
        has_position = pos is not None and pos.quantity > 0

        if not has_position:
            if signal == 1:
                self.executor.place_order(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=size,
                    leverage=1.0,
                    current_price=price
                )
                self.position.open_position(symbol, size, price)
                logger.info("PortfolioTrader: Opened LONG @ %.2f  weights=%s",
                            price, self.allocator)

            elif signal == -1:
                logger.warning("Short selling not supported in non-leverage mode")

        elif has_position and signal == -1:
            self._close_and_update(price, "LONG")

    def _close_and_update(self, price: float, side: str) -> None:
        """平仓并用 PnL 更新 Bandit 权重。"""
        symbol = self.cfg.symbol
        pos = self.position.get_position(symbol)
        if pos is None:
            return

        pos.update_pnl(price)
        pnl = pos.unrealized_pnl

        self.executor.place_order(
            symbol=symbol,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=pos.quantity,
            leverage=1.0,
            current_price=price
        )

        self.risk.on_trade_executed(symbol, "SELL", pos.quantity, price, pnl)
        self.monitor.record_trade_pnl(pnl)
        self.position.close_position(symbol, price)

        # ── Bandit 更新：用归一化 PnL 作为 reward ────────────────────────────
        if self._last_active_arm is not None:
            # 归一化：pnl / initial_balance → 通常在 [-0.05, 0.05] 范围
            reward = pnl / max(self.cfg.initial_balance, 1.0)
            # 放大到 [-1, 1] 让 Bandit 反应更明显
            reward = float(np.clip(reward * 20, -1.0, 1.0))
            self.allocator.update(arm=self._last_active_arm, reward=reward)
            self._last_active_arm = None

        self.monitor.update(self.monitor.current_equity + pnl)
        logger.info(
            "PortfolioTrader: Closed %s @ %.2f pnl=%.2f | %s | allocator=%s",
            side, price, pnl, self.monitor.summary(), self.allocator,
        )

    def _build_default_strategies(self) -> list:
        """构建默认策略池：AlphaStrategy + RegimeAwareLGBMStrategy（若模型存在）。"""
        import pathlib
        strategies = [AlphaStrategy()]

        # 尝试加载已训练模型
        default_model = pathlib.Path("models/lgbm_btc_1h.txt")
        if default_model.exists():
            try:
                from trading_system.regime_strategy import RegimeAwareLGBMStrategy
                strategies.append(RegimeAwareLGBMStrategy(str(default_model)))
                logger.info("Loaded RegimeAwareLGBMStrategy from %s", default_model)
            except Exception as exc:
                logger.warning("Could not load LGBMStrategy: %s — using AlphaStrategy only", exc)

        return strategies
