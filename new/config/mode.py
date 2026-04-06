"""
交易模式定义 - Trading Mode

定义实盘和模拟盘的强枚举类型。
"""

from enum import Enum


class TradingMode(Enum):
    """
    交易模式枚举

    LIVE: 实盘交易 - 真实资金，真实订单
    PAPER: 模拟交易 - 虚拟资金，模拟执行
    """
    LIVE = "live"
    PAPER = "paper"

    @classmethod
    def from_string(cls, value: str) -> "TradingMode":
        """从字符串创建枚举"""
        try:
            return cls(value.lower())
        except ValueError:
            raise ValueError(f"Invalid trading mode: {value}. Use 'live' or 'paper'")

    def is_live(self) -> bool:
        """是否为实盘模式"""
        return self == TradingMode.LIVE

    def is_paper(self) -> bool:
        """是否为模拟模式"""
        return self == TradingMode.PAPER
