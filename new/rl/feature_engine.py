"""
Feature Engine for ExecutionEnv v2
从 L2 Book + Trade Stream 提取 Alpha 特征
"""
from typing import List, Tuple, Dict, Optional
import numpy as np


def _parse_book_side(side_list) -> List[Tuple[float, float]]:
    """将原始 book side 解析为 (price, size) 列表."""
    out = []
    for item in side_list:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            out.append((float(item[0]), float(item[1])))
        elif isinstance(item, dict):
            out.append((float(item.get("p", 0)), float(item.get("q", 0))))
    return out


class FeatureEngine:
    """
    基于连续 book snapshot 和 trades 计算 microstructure features.
    输出 state vector 用于 SAC v2.
    """

    def __init__(self, window_size: int = 20):
        self.window_size = window_size
        self.prev_book: Optional[Dict] = None
        self.prev_mid: Optional[float] = None
        self.mid_history: List[float] = []
        self.ofi_history: List[float] = []

    def update(
        self,
        book: Dict,
        trades: Optional[List[Dict]] = None,
    ) -> Tuple[np.ndarray, float]:
        """
        Args:
            book: {"bids": [(px, sz), ...], "asks": [(px, sz), ...]}
            trades: 自上次 update 以来的成交列表
                   [{"price": float, "qty": float, "isBuyerMaker": bool}, ...]
        Returns:
            state: np.ndarray shape (state_dim,)
            mid: float
        """
        trades = trades or []

        bids = _parse_book_side(book.get("bids", []))
        asks = _parse_book_side(book.get("asks", []))

        if not bids or not asks:
            return self._fallback_state(), self.prev_mid or 0.0

        bid_px, bid_sz = bids[0]
        ask_px, ask_sz = asks[0]

        mid = (bid_px + ask_px) / 2.0
        spread = ask_px - bid_px

        # --- 1. 价差与深度 ---
        spread_bps = (spread / mid) * 10000.0

        bid_vol_5 = sum(sz for _, sz in bids[:5])
        ask_vol_5 = sum(sz for _, sz in asks[:5])
        imbalance_1 = (bid_sz - ask_sz) / (bid_sz + ask_sz + 1e-6)
        imbalance_5 = (bid_vol_5 - ask_vol_5) / (bid_vol_5 + ask_vol_5 + 1e-6)

        # --- 2. Microprice ---
        micro = (ask_px * bid_sz + bid_px * ask_sz) / (bid_sz + ask_sz + 1e-6)
        micro_dev = (micro - mid) / mid

        # --- 3. OFI (Order Flow Imbalance) ---
        ofi = 0.0
        if self.prev_book:
            pbids = _parse_book_side(self.prev_book.get("bids", []))
            pasks = _parse_book_side(self.prev_book.get("asks", []))
            if pbids and pasks:
                pb_px, pb_sz = pbids[0]
                pa_px, pa_sz = pasks[0]

                if bid_px > pb_px:
                    ofi += bid_sz
                elif bid_px == pb_px:
                    ofi += (bid_sz - pb_sz)

                if ask_px < pa_px:
                    ofi -= ask_sz
                elif ask_px == pa_px:
                    ofi -= (ask_sz - pa_sz)

        self.ofi_history.append(ofi)
        if len(self.ofi_history) > self.window_size:
            self.ofi_history.pop(0)
        ofi_norm = float(np.mean(self.ofi_history)) if self.ofi_history else 0.0
        ofi_norm = np.clip(ofi_norm / 1e3, -1.0, 1.0)

        # --- 4. Short-term return ---
        self.mid_history.append(mid)
        if len(self.mid_history) > self.window_size:
            self.mid_history.pop(0)

        ret_1 = 0.0
        if len(self.mid_history) >= 2:
            ret_1 = (self.mid_history[-1] - self.mid_history[-2]) / self.mid_history[-2]

        ret_5 = 0.0
        if len(self.mid_history) >= 6:
            ret_5 = (self.mid_history[-1] - self.mid_history[-6]) / self.mid_history[-6]

        # --- 5. Trade flow ---
        buy_vol = sum(t.get("qty", 0.0) for t in trades if t.get("isBuyerMaker") is False)
        sell_vol = sum(t.get("qty", 0.0) for t in trades if t.get("isBuyerMaker") is True)
        total_vol = buy_vol + sell_vol + 1e-6
        buy_ratio = buy_vol / total_vol
        trade_intensity = len(trades)
        last_trade_sign = 0.0
        if trades:
            last_trade_sign = 1.0 if not trades[-1].get("isBuyerMaker", True) else -1.0

        state = np.array([
            np.clip(spread_bps / 10.0, -1.0, 1.0),
            imbalance_1,
            imbalance_5,
            micro_dev,
            ofi_norm,
            np.clip(ret_1 * 1e3, -1.0, 1.0),
            np.clip(ret_5 * 1e3, -1.0, 1.0),
            buy_ratio * 2.0 - 1.0,  # map [0,1] to [-1,1]
            np.clip(trade_intensity / 10.0, 0.0, 1.0),
            last_trade_sign,
        ], dtype=np.float32)

        self.prev_book = {"bids": bids, "asks": asks}
        self.prev_mid = mid

        return state, mid

    def _fallback_state(self) -> np.ndarray:
        return np.zeros(10, dtype=np.float32)
