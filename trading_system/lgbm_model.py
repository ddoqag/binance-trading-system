# trading_system/lgbm_model.py
"""
LightGBM inference wrapper for the live trading loop.

Wraps a saved lgb.Booster so that Trader can call:
    signal = LGBMStrategy(model_path).generate_signal(df)

Signal semantics (same contract as AlphaStrategy):
    +1  = BUY  (prob > buy_threshold)
    -1  = SELL (prob < sell_threshold)
     0  = HOLD (ambiguous zone)

The ambiguous zone (sell_threshold ≤ prob ≤ buy_threshold) is intentionally
wide — passing an uncertain signal to a noisy market is worse than no trade.
"""
from __future__ import annotations
import logging
import math

import numpy as np
import pandas as pd

from training_system.features import FEATURE_COLS, build_features

logger = logging.getLogger(__name__)


class LGBMStrategy:
    """
    Drop-in replacement for AlphaStrategy using a trained LightGBM model.

    Args:
        model_path:      Path to a saved lgb.Booster file.
        buy_threshold:   Probability above which a BUY signal is issued (default 0.55).
        sell_threshold:  Probability below which a SELL signal is issued (default 0.45).
    """

    def __init__(
        self,
        model_path: str,
        buy_threshold: float = 0.55,
        sell_threshold: float = 0.45,
    ) -> None:
        import lightgbm as lgb
        self.model = lgb.Booster(model_file=model_path)
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        logger.info("LGBMStrategy loaded from %s", model_path)

    def generate_signal(self, df: pd.DataFrame) -> int:
        """
        Generate a trading signal from the latest bar of df.

        Args:
            df: Raw OHLCV DataFrame.  The last row is the current bar.

        Returns:
            +1 (BUY), -1 (SELL), or 0 (HOLD).
        """
        try:
            featured = build_features(df)
            last_row = featured[FEATURE_COLS].iloc[[-1]]

            # Guard: any NaN / Inf in latest bar → no signal
            values = last_row.values
            if not np.isfinite(values).all():
                logger.debug("LGBMStrategy: non-finite features in latest bar — HOLD")
                return 0

            prob = float(self.model.predict(values)[0])

            if prob > self.buy_threshold:
                return 1
            if prob < self.sell_threshold:
                return -1
            return 0

        except Exception as exc:
            logger.error("LGBMStrategy.generate_signal error: %s", exc)
            return 0
