from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class RepriceEngine:
    """
    重挂定价引擎
    对撤单后的剩余数量重新定价
    """

    def __init__(self, tick_size: float = 0.01, max_attempts: int = 3):
        self.tick_size = tick_size
        self.max_attempts = max_attempts

    def new_price(self, side: str, book) -> Optional[float]:
        """
        根据当前 book 和方向生成新的限价单价格
        """
        if book is None:
            return None

        bb = getattr(book, "best_bid", lambda: None)()
        ba = getattr(book, "best_ask", lambda: None)()

        if bb is None or ba is None:
            return None

        if side == "BUY":
            # 轻微 improvements: 挂在 best_bid + 1 tick 以提高成交概率
            return bb + self.tick_size
        else:  # SELL
            return ba - self.tick_size

    def reprice(
        self,
        side: str,
        remaining_size: float,
        book,
        signal_strength: float = 0.0,
        attempt: int = 1,
    ) -> Tuple[Optional[float], str]:
        """
        返回 (新价格, 策略描述)
        """
        if remaining_size <= 1e-9:
            return None, "nothing_to_reprice"

        urgency = abs(signal_strength)

        bb = getattr(book, "best_bid", lambda: None)()
        ba = getattr(book, "best_ask", lambda: None)()
        if bb is None or ba is None:
            return None, "no_book"

        # 信号极强: 更激进
        if urgency > 0.8:
            price = ba if side == "BUY" else bb
            return price, "aggressive_immediate"

        # 重挂次数较多: 进一步改善
        if attempt >= self.max_attempts // 2:
            if side == "BUY":
                price = bb + self.tick_size
            else:
                price = ba - self.tick_size
            return price, "improved_limit"

        # 默认挂回 best 价
        price = bb if side == "BUY" else ba
        return price, "best_price_passive"
