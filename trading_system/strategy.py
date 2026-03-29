# trading_system/strategy.py
import pandas as pd


class AlphaStrategy:
    """
    Phase 1.5 盈利导向策略：趋势 + 动量 + 波动三重过滤。

    只在以下条件同时满足时才交易：
    1. 市场有足够波动（ATR/price > atr_threshold）
    2. 趋势方向明确（|MA5 - MA20| / price > trend_threshold）
    3. MA20 斜率与方向一致（5根K线内MA20方向）
    4. RSI 动量确认（多头 > rsi_long，空头 < rsi_short）

    返回: +1 BUY | -1 SELL | 0 HOLD

    接口设计为可插拔 — Phase 2 直接替换为 LGBMStrategy。
    """

    def __init__(
        self,
        trend_threshold: float = 0.002,
        atr_threshold: float = 0.005,
        rsi_long: float = 55.0,
        rsi_short: float = 45.0,
    ):
        self.trend_threshold = trend_threshold
        self.atr_threshold = atr_threshold
        self.rsi_long = rsi_long
        self.rsi_short = rsi_short

    def generate_signal(self, df: pd.DataFrame) -> int:
        if len(df) < 50:
            return 0

        last = df.iloc[-1]
        price = float(last["close"])
        ma5 = last.get("ma5")
        ma20 = last.get("ma20")
        atr = last.get("atr")
        rsi = last.get("rsi")

        if any(pd.isna(x) for x in [ma5, ma20, atr, rsi]):
            return 0

        # 1. 波动过滤 — 市场太安静不做
        if float(atr) / price < self.atr_threshold:
            return 0

        # 2. 横盘过滤 — MA5 和 MA20 太近说明没趋势
        if abs(float(ma5) - float(ma20)) / price < self.trend_threshold:
            return 0

        # 3. MA20 斜率过滤 — 用 5 根 K 线前的 MA20 计算方向
        prev = df.iloc[-5]
        ma20_prev = prev.get("ma20")
        if pd.isna(ma20_prev):
            return 0
        trend_slope = (float(ma20) - float(ma20_prev)) / price

        # 4. 多头：MA5 > MA20，MA20 上升，RSI > rsi_long
        if float(ma5) > float(ma20) and trend_slope > 0 and float(rsi) > self.rsi_long:
            return 1

        # 5. 空头：MA5 < MA20，MA20 下降，RSI < rsi_short
        if float(ma5) < float(ma20) and trend_slope < 0 and float(rsi) < self.rsi_short:
            return -1

        return 0
