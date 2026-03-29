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

    # Execution cost simulation
    fee_rate: float = 0.0004    # Binance taker 0.04%
    slippage_rate: float = 0.0005  # estimated slippage

    def __post_init__(self):
        self.symbol = self.symbol or os.getenv("TRADING_SYMBOL", "BTCUSDT")
        self.interval = self.interval or os.getenv("TRADING_INTERVAL", "1h")
        self.trading_mode = self.trading_mode or os.getenv("TRADING_MODE", "real")
        self.initial_balance = self.initial_balance or float(
            os.getenv("INITIAL_BALANCE", "10000")
        )
