# trading_system/regime_strategy.py
"""
Regime-aware LightGBM strategy.

包装 LGBMStrategy，在每次生成信号前先询问 MarketAnalyzer 当前市场状态，
根据 regime + confidence 动态调整 buy/sell 阈值：

  BULL / BEAR（趋势明确）
      → 阈值放宽：更容易入场，跟随趋势
        buy_threshold  = 0.55 - 0.10 * confidence
        sell_threshold = 0.45 + 0.10 * confidence

  NEUTRAL（震荡）
      → 阈值收紧：只有高置信度才入场，过滤假信号
        buy_threshold  = 0.55 + 0.10 * confidence
        sell_threshold = 0.45 - 0.10 * confidence

  HIGH_VOLATILITY（高波动）
      → 强制 HOLD：不确定性太高，任何信号都不可信

置信度越高，调整幅度越大。
"""
from __future__ import annotations
import logging

import numpy as np
import pandas as pd

from trading_system.lgbm_model import LGBMStrategy
from ai_trading.market_analyzer import MarketAnalyzer, MarketRegime

logger = logging.getLogger(__name__)

# 基准阈值（未知状态时使用）
_BASE_BUY  = 0.55
_BASE_SELL = 0.45
# 趋势/震荡状态下的最大调整幅度
_DELTA = 0.10


class RegimeAwareLGBMStrategy:
    """
    Regime-aware wrapper around LGBMStrategy.

    Args:
        model_path: 已训练 LightGBM 模型路径。
        model_analyzer_path: Qwen/AI 模型路径，None 则使用规则引擎（推荐）。
    """

    def __init__(
        self,
        model_path: str,
        model_analyzer_path: str | None = None,
    ) -> None:
        self.lgbm = LGBMStrategy(model_path)
        self.analyzer = MarketAnalyzer(model_path=model_analyzer_path)

    def _get_thresholds(self, analysis: dict) -> tuple[float, float]:
        """
        根据 regime + confidence 计算动态阈值。

        Returns:
            (buy_threshold, sell_threshold)
        """
        regime: MarketRegime = analysis.get("regime", MarketRegime.NEUTRAL)
        confidence: float = float(analysis.get("confidence", 0.5))
        # 确保 confidence 在 [0, 1]
        confidence = max(0.0, min(1.0, confidence))

        if regime == MarketRegime.HIGH_VOLATILITY:
            # 高波动：返回不可能达到的阈值 → 永远 HOLD
            return 2.0, -1.0

        if regime in (MarketRegime.BULL, MarketRegime.BEAR):
            # 趋势市场：放宽阈值
            buy_thr  = _BASE_BUY  - _DELTA * confidence
            sell_thr = _BASE_SELL + _DELTA * confidence
        else:
            # 震荡 / 未知：收紧阈值
            buy_thr  = _BASE_BUY  + _DELTA * confidence
            sell_thr = _BASE_SELL - _DELTA * confidence

        return buy_thr, sell_thr

    def generate_signal(self, df: pd.DataFrame) -> int:
        """
        生成信号：先识别 Regime，再调整阈值，最后调用 LightGBM。

        Returns:
            +1 (BUY), -1 (SELL), 0 (HOLD)
        """
        # ── Step 1: Regime 识别 ───────────────────────────────────────────────
        try:
            analysis = self.analyzer.analyze_trend(df)
        except Exception as exc:
            logger.error("RegimeAwareLGBMStrategy: analyzer failed (%s) — HOLD", exc)
            return 0

        regime = analysis.get("regime", MarketRegime.NEUTRAL)

        # ── Step 2: 高波动快速返回 ────────────────────────────────────────────
        if regime == MarketRegime.HIGH_VOLATILITY:
            logger.debug("Regime=HIGH_VOLATILITY — HOLD")
            return 0

        # ── Step 3: 获取动态阈值 ──────────────────────────────────────────────
        buy_thr, sell_thr = self._get_thresholds(analysis)

        # ── Step 4: 临时覆盖 LGBMStrategy 的阈值，调用预测 ───────────────────
        original_buy  = self.lgbm.buy_threshold
        original_sell = self.lgbm.sell_threshold
        try:
            self.lgbm.buy_threshold  = buy_thr
            self.lgbm.sell_threshold = sell_thr
            signal = self.lgbm.generate_signal(df)
        finally:
            self.lgbm.buy_threshold  = original_buy
            self.lgbm.sell_threshold = original_sell

        logger.debug(
            "Regime=%s conf=%.2f → buy_thr=%.3f sell_thr=%.3f signal=%d",
            regime.value, analysis.get("confidence", 0.5), buy_thr, sell_thr, signal,
        )
        return signal
