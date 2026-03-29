# trading_system/trader.py
"""
Main trading loop.
策略可替换：
  self.strategy = AlphaStrategy()                      # 规则版
  self.strategy = LGBMStrategy("models/...")           # LightGBM 版
  self.strategy = RegimeAwareLGBMStrategy("models/...") # Regime 感知版（推荐）
"""
from __future__ import annotations
import math
import time
import logging

from trading_system.config import Config
from trading_system.data_feed import get_klines
from trading_system.features import add_features
from trading_system.strategy import AlphaStrategy
from risk.position import PositionManager
from risk.manager import RiskManager, RiskConfig
from trading.leverage_executor import LeverageTradingExecutor, OrderSide, OrderType
from trading_system.monitor import EquityMonitor

logger = logging.getLogger(__name__)


class Trader:
    """
    Orchestrates one trading cycle per call to step().
    All components are injected for testability.
    """

    def __init__(self, config: Config, binance_client=None):
        self.cfg = config
        self.strategy = AlphaStrategy()
        # 使用默认仓位限制参数
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

    def step(self) -> None:
        """One trading cycle: fetch → features → signal → risk check → execute."""
        # 使用 can_trade 检查风险限制
        can_trade, reason = self.risk.can_trade(self.cfg.symbol, "BUY", 0, 0)
        if not can_trade:
            logger.warning("Circuit breaker triggered — %s", reason)
            return

        try:
            df_raw = get_klines(self.cfg.symbol, self.cfg.interval, limit=100)
            df = add_features(df_raw)
        except Exception as exc:
            logger.error("Data fetch failed: %s", exc)
            return

        signal = self.strategy.generate_signal(df)
        last = df.iloc[-1]
        price = float(last["close"])
        atr_val = last.get("atr")

        if atr_val is None or math.isnan(float(atr_val)) or float(atr_val) <= 0:
            return

        atr = float(atr_val)
        # 使用 ATR-based 仓位计算 (从旧 risk_manager 迁移的逻辑)
        size = self._calc_position_size(price=price, atr=atr)
        if size <= 0:
            return

        self._execute_signal(signal=signal, price=price, size=size)

    def _calc_position_size(self, price: float, atr: float) -> float:
        """ATR-based position sizing from old risk_manager."""
        risk_amount = self.cfg.initial_balance * self.cfg.risk_per_trade
        stop_distance = self.cfg.atr_sl_multiplier * atr
        if stop_distance <= 0:
            return 0.0
        return risk_amount / stop_distance

    def _execute_signal(self, signal: int, price: float, size: float) -> None:
        """Apply position state machine logic."""
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
                logger.info("Opened LONG @ %.2f size=%.4f", price, size)

            elif signal == -1:
                logger.warning("Short selling not supported in non-leverage mode")

        elif has_position and signal == -1:
            pos = self.position.get_position(symbol)
            if pos:
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
                self.monitor.update(self.monitor.current_equity + pnl)
                logger.info("Closed LONG @ %.2f pnl=%.2f | %s", price, pnl, self.monitor.summary())

    def run(self, interval_seconds: int = 60) -> None:
        """Blocking main loop. Ctrl+C to stop."""
        logger.info(
            "Trader started — symbol=%s interval=%s mode=%s balance=%.2f",
            self.cfg.symbol, self.cfg.interval,
            self.cfg.trading_mode, self.cfg.initial_balance,
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
    Trader(Config()).run()
