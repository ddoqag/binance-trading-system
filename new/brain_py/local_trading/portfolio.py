"""
本地投资组合管理

功能:
- 持仓跟踪
- 交易记录
- 盈亏计算
- 风险控制
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """持仓"""
    symbol: str
    side: str  # 'long' or 'short'
    qty: float
    entry_price: float
    entry_time: datetime
    unrealized_pnl: float = 0.0

    def update_price(self, current_price: float):
        """更新价格并计算浮动盈亏"""
        if self.side == 'long':
            self.unrealized_pnl = (current_price - self.entry_price) * self.qty
        else:  # short
            self.unrealized_pnl = (self.entry_price - current_price) * self.qty

    @property
    def market_value(self) -> float:
        """市场价值"""
        return self.qty * self.entry_price

    @property
    def total_pnl(self, current_price: float = None) -> float:
        """总盈亏（如果提供当前价格则包含浮动盈亏）"""
        if current_price is None:
            return self.unrealized_pnl
        if self.side == 'long':
            return (current_price - self.entry_price) * self.qty
        return (self.entry_price - current_price) * self.qty


@dataclass
class TradeRecord:
    """交易记录"""
    trade_id: str
    timestamp: datetime
    symbol: str
    side: str  # 'buy' or 'sell'
    qty: float
    price: float
    fee: float
    pnl: Optional[float] = None
    pnl_components: Dict[str, float] = field(default_factory=dict)


class LocalPortfolio:
    """
    本地投资组合管理
    """

    def __init__(self, initial_capital: float = 10000.0):
        self.initial_capital = initial_capital
        self.cash = initial_capital

        # 持仓
        self.positions: Dict[str, Position] = {}

        # 交易记录
        self.trades: List[TradeRecord] = []

        # 权益曲线
        self.equity_curve: List[Dict] = []

        # 统计
        self.trade_counter = 0

        logger.info(f"投资组合初始化: ${initial_capital:.2f}")

    def update(self, timestamp: datetime, current_price: float):
        """更新持仓市值"""
        total_unrealized = 0.0

        for pos in self.positions.values():
            pos.update_price(current_price)
            total_unrealized += pos.unrealized_pnl

        # 记录权益
        total_equity = self.cash + sum(
            pos.qty * current_price for pos in self.positions.values()
        )

        self.equity_curve.append({
            'timestamp': timestamp,
            'cash': self.cash,
            'equity': total_equity,
            'unrealized_pnl': total_unrealized
        })

    def execute_trade(self,
                     symbol: str,
                     side: str,
                     qty: float,
                     price: float,
                     fee: float,
                     timestamp: datetime,
                     pnl_components: Optional[Dict] = None) -> Optional[TradeRecord]:
        """
        执行交易

        Returns:
            TradeRecord or None if failed
        """
        self.trade_counter += 1
        trade_id = f"trade_{self.trade_counter}"

        # 计算交易金额
        trade_value = qty * price

        # 检查资金
        if side == 'buy':
            total_cost = trade_value + fee
            if total_cost > self.cash:
                logger.warning(f"资金不足: 需要 ${total_cost:.2f}, 可用 ${self.cash:.2f}")
                return None

            self.cash -= total_cost

            # 更新或创建持仓
            if symbol in self.positions:
                pos = self.positions[symbol]
                # 加仓
                total_cost_basis = pos.market_value + trade_value
                pos.qty += qty
                pos.entry_price = total_cost_basis / pos.qty
            else:
                # 新建持仓
                self.positions[symbol] = Position(
                    symbol=symbol,
                    side='long',
                    qty=qty,
                    entry_price=price,
                    entry_time=timestamp
                )

            trade_pnl = -fee  # 买入时盈亏为负（手续费）

        else:  # sell
            if symbol not in self.positions or self.positions[symbol].qty < qty:
                logger.warning(f"持仓不足: 无法卖出 {qty} {symbol}")
                return None

            # 计算盈亏
            pos = self.positions[symbol]
            cost_basis = qty * pos.entry_price
            proceeds = trade_value - fee
            trade_pnl = proceeds - cost_basis

            self.cash += proceeds

            # 更新持仓
            pos.qty -= qty
            if pos.qty <= 0:
                del self.positions[symbol]

        # 记录交易
        record = TradeRecord(
            trade_id=trade_id,
            timestamp=timestamp,
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            fee=fee,
            pnl=trade_pnl,
            pnl_components=pnl_components or {}
        )
        self.trades.append(record)

        logger.info(f"交易执行: {side} {qty} {symbol} @ ${price:.2f}, PnL: ${trade_pnl:.4f}")
        return record

    def get_position(self, symbol: str) -> Optional[Position]:
        """获取持仓"""
        return self.positions.get(symbol)

    def get_total_equity(self, current_price: float = None) -> float:
        """获取总权益"""
        positions_value = sum(
            pos.qty * (current_price or pos.entry_price)
            for pos in self.positions.values()
        )
        return self.cash + positions_value

    def get_statistics(self) -> Dict:
        """获取统计信息"""
        if not self.trades:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'total_fees': 0.0,
                'net_pnl': 0.0,
                'avg_profit': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 0.0,
                'current_equity': self.get_total_equity()
            }

        profits = [t.pnl for t in self.trades if t.pnl and t.pnl > 0]
        losses = [t.pnl for t in self.trades if t.pnl and t.pnl <= 0]

        total_pnl = sum(t.pnl for t in self.trades if t.pnl)
        total_fees = sum(t.fee for t in self.trades)

        return {
            'total_trades': len(self.trades),
            'winning_trades': len(profits),
            'losing_trades': len(losses),
            'win_rate': len(profits) / len(self.trades) if self.trades else 0,
            'total_pnl': total_pnl,
            'total_fees': total_fees,
            'net_pnl': total_pnl - total_fees,
            'avg_profit': np.mean(profits) if profits else 0,
            'avg_loss': np.mean(losses) if losses else 0,
            'profit_factor': abs(sum(profits) / sum(losses)) if losses and sum(losses) != 0 else float('inf'),
            'current_equity': self.get_total_equity()
        }

    def get_equity_curve_df(self) -> pd.DataFrame:
        """获取权益曲线DataFrame"""
        return pd.DataFrame(self.equity_curve)

    def generate_report(self) -> str:
        """生成文字报告"""
        stats = self.get_statistics()
        current_equity = self.get_total_equity()

        report = f"""
{'='*60}
投资组合报告
{'='*60}

资金状况:
  初始资金: ${self.initial_capital:.2f}
  当前现金: ${self.cash:.2f}
  当前权益: ${current_equity:.2f}
  总收益率: {(current_equity/self.initial_capital - 1)*100:.2f}%

持仓:
"""
        for symbol, pos in self.positions.items():
            report += f"  {symbol}: {pos.side} {pos.qty} @ ${pos.entry_price:.2f}\n"

        report += f"""
交易统计:
  总交易次数: {stats['total_trades']}
  胜率: {stats['win_rate']:.1%}
  总盈亏: ${stats['total_pnl']:.4f}
  总手续费: ${stats['total_fees']:.4f}
  净盈亏: ${stats['net_pnl']:.4f}
  盈亏比: {stats['profit_factor']:.2f}

{'='*60}
"""
        return report


# 测试代码
if __name__ == "__main__":
    print("=" * 60)
    print("本地投资组合测试")
    print("=" * 60)

    portfolio = LocalPortfolio(initial_capital=1000.0)

    from datetime import datetime

    print("\n1. 买入测试")
    trade = portfolio.execute_trade(
        symbol="BTCUSDT",
        side="buy",
        qty=0.01,
        price=50000.0,
        fee=0.5,
        timestamp=datetime.now()
    )
    if trade:
        print(f"  买入成功: {trade.qty} BTC @ ${trade.price}")
        print(f"  剩余现金: ${portfolio.cash:.2f}")

    print("\n2. 更新价格")
    portfolio.update(datetime.now(), 51000.0)
    pos = portfolio.get_position("BTCUSDT")
    if pos:
        print(f"  浮动盈亏: ${pos.unrealized_pnl:.2f}")

    print("\n3. 卖出测试")
    trade = portfolio.execute_trade(
        symbol="BTCUSDT",
        side="sell",
        qty=0.01,
        price=51000.0,
        fee=0.51,
        timestamp=datetime.now()
    )
    if trade:
        print(f"  卖出成功: 实现盈亏 ${trade.pnl:.2f}")
        print(f"  最终现金: ${portfolio.cash:.2f}")

    print("\n4. 统计报告")
    print(portfolio.generate_report())

    print("测试完成")
