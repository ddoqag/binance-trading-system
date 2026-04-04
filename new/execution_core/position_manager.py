import logging
from typing import Optional

logger = logging.getLogger(__name__)


class PositionManager:
    """
    持仓管理器 - 独立维护仓位、成本和 PnL
    不依赖策略层，只根据成交事件更新
    """

    def __init__(self):
        self.position: float = 0.0
        self.avg_price: float = 0.0
        self.realized_pnl: float = 0.0
        self.total_commission: float = 0.0

    def on_fill(self, side: str, qty: float, price: float, commission: float = 0.0):
        """
        处理单笔成交，更新持仓和已实现盈亏
        """
        self.total_commission += commission

        if side == "BUY":
            new_pos = self.position + qty
            if new_pos > 0:
                self.avg_price = (
                    self.avg_price * self.position + price * qty
                ) / new_pos
            self.position = new_pos
            logger.info(f"[Position] BUY fill | qty={qty} @ {price} | pos={self.position:.6f} avg={self.avg_price:.2f}")

        else:  # SELL
            if self.position > 0:
                pnl = (price - self.avg_price) * qty
                self.realized_pnl += pnl
            elif self.position < 0:
                pnl = (self.avg_price - price) * qty
                self.realized_pnl += pnl

            self.position -= qty
            if abs(self.position) < 1e-9:
                self.avg_price = 0.0

            logger.info(f"[Position] SELL fill | qty={qty} @ {price} | pos={self.position:.6f} realized={self.realized_pnl:.4f}")

    def get_unrealized(self, mark_price: float) -> float:
        return (mark_price - self.avg_price) * self.position

    def get_status(self) -> dict:
        return {
            "position": self.position,
            "avg_price": self.avg_price,
            "realized_pnl": self.realized_pnl,
            "total_commission": self.total_commission,
        }
