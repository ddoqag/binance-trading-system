"""
回测引擎
事件驱动的回测框架
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class OrderType(Enum):
    """订单类型"""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderSide(Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


@dataclass
class Order:
    """订单"""
    id: str
    timestamp: datetime
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    filled: bool = False
    filled_price: Optional[float] = None
    filled_time: Optional[datetime] = None


@dataclass
class Position:
    """持仓"""
    symbol: str
    quantity: float
    entry_price: float
    entry_time: datetime
    side: OrderSide

    @property
    def market_value(self) -> float:
        return self.quantity * self.entry_price


@dataclass
class Trade:
    """成交记录"""
    timestamp: datetime
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    commission: float
    pnl: Optional[float] = None


@dataclass
class BacktestConfig:
    """回测配置"""
    initial_capital: float = 10000.0
    commission_rate: float = 0.001  # 0.1%
    slippage: float = 0.0005  # 0.05%
    max_position_pct: float = 0.8
    enable_stop_loss: bool = True
    stop_loss_pct: float = 0.025
    enable_take_profit: bool = False
    take_profit_pct: float = 0.05


@dataclass
class BacktestResult:
    """回测结果"""
    config: BacktestConfig
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    total_return: float
    total_return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_profit: float
    avg_loss: float
    profit_factor: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    volatility: float
    trades: List[Trade] = field(default_factory=list)
    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)
    metrics: Dict[str, float] = field(default_factory=dict)


class BacktestEngine:
    """
    回测引擎

    事件驱动的回测框架，支持:
    - 多种订单类型
    - 滑点和手续费模拟
    - 止损止盈
    - 详细的性能统计
    """

    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()
        self.reset()

    def reset(self):
        """重置引擎状态"""
        self.capital = self.config.initial_capital
        self.positions: Dict[str, Position] = {}
        self.orders: List[Order] = []
        self.trades: List[Trade] = []
        self.equity_curve: List[Dict] = []
        self.order_counter = 0

        # 历史数据
        self.data: Optional[pd.DataFrame] = None
        self.current_bar: Optional[pd.Series] = None
        self.current_index = 0

        # 策略回调
        self.strategy_init: Optional[Callable] = None
        self.strategy_next: Optional[Callable] = None

    def set_strategy(
        self,
        init_func: Optional[Callable] = None,
        next_func: Optional[Callable] = None
    ):
        """
        设置策略回调

        Args:
            init_func: 初始化函数
            next_func: 每个bar的处理函数
        """
        self.strategy_init = init_func
        self.strategy_next = next_func

    def run(
        self,
        data: pd.DataFrame,
        strategy: Optional[Any] = None
    ) -> BacktestResult:
        """
        运行回测

        Args:
            data: OHLCV数据
            strategy: 策略实例 (可选)

        Returns:
            BacktestResult
        """
        self.reset()
        self.data = data.copy()

        # 记录起始时间
        start_date = data['timestamp'].iloc[0]
        end_date = data['timestamp'].iloc[-1]

        # 调用策略初始化
        if strategy and hasattr(strategy, 'initialize'):
            strategy.initialize()

        if self.strategy_init:
            self.strategy_init(self)

        # 遍历每个bar
        for idx, bar in data.iterrows():
            self.current_bar = bar
            self.current_index = idx

            # 更新持仓市值
            self._update_positions(bar)

            # 检查止损止盈
            if self.config.enable_stop_loss or self.config.enable_take_profit:
                self._check_stop_loss_take_profit(bar)

            # 执行策略
            if strategy and hasattr(strategy, 'next'):
                strategy.next(self, bar)

            if self.strategy_next:
                self.strategy_next(self, bar)

            # 记录权益曲线
            total_value = self.capital + self._get_positions_value()
            self.equity_curve.append({
                'timestamp': bar['timestamp'],
                'equity': total_value,
                'cash': self.capital,
                'positions_value': self._get_positions_value()
            })

        # 平掉所有仓位
        self._close_all_positions()

        # 生成结果
        return self._generate_result(start_date, end_date)

    def buy(
        self,
        symbol: str,
        quantity: Optional[float] = None,
        price: Optional[float] = None,
        percent: Optional[float] = None
    ) -> Optional[Order]:
        """买入"""
        if quantity is None and percent is not None:
            # 按资金百分比计算数量
            current_price = price or self.current_bar['close']
            amount = self.capital * percent
            quantity = amount / current_price

        if quantity is None or quantity <= 0:
            return None

        # 检查最大仓位限制
        position_value = self._get_positions_value()
        new_position_value = position_value + (quantity * (price or self.current_bar['close']))
        if new_position_value > self.capital * self.config.max_position_pct:
            logger.warning("Max position limit reached")
            return None

        order = self._create_order(symbol, OrderSide.BUY, OrderType.MARKET, quantity, price)
        self._execute_order(order)
        return order

    def sell(
        self,
        symbol: str,
        quantity: Optional[float] = None,
        price: Optional[float] = None,
        percent: Optional[float] = None
    ) -> Optional[Order]:
        """卖出"""
        position = self.positions.get(symbol)
        if not position:
            return None

        if quantity is None and percent is not None:
            quantity = position.quantity * percent
        elif quantity is None:
            quantity = position.quantity

        quantity = min(quantity, position.quantity)

        if quantity <= 0:
            return None

        order = self._create_order(symbol, OrderSide.SELL, OrderType.MARKET, quantity, price)
        self._execute_order(order)
        return order

    def _create_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None
    ) -> Order:
        """创建订单"""
        self.order_counter += 1
        return Order(
            id=f"order_{self.order_counter}",
            timestamp=self.current_bar['timestamp'],
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price
        )

    def _execute_order(self, order: Order):
        """执行订单"""
        bar = self.current_bar

        # 确定成交价格
        if order.order_type == OrderType.MARKET:
            # 市价单使用当前bar的收盘价
            fill_price = bar['close']
        else:
            fill_price = order.price or bar['close']

        # 应用滑点
        if order.side == OrderSide.BUY:
            fill_price *= (1 + self.config.slippage)
        else:
            fill_price *= (1 - self.config.slippage)

        order.filled = True
        order.filled_price = fill_price
        order.filled_time = bar['timestamp']
        self.orders.append(order)

        # 计算手续费
        trade_value = order.quantity * fill_price
        commission = trade_value * self.config.commission_rate

        # 更新资金和持仓
        if order.side == OrderSide.BUY:
            cost = trade_value + commission
            if cost > self.capital:
                logger.warning("Insufficient capital")
                return

            self.capital -= cost

            # 更新或创建持仓
            if order.symbol in self.positions:
                pos = self.positions[order.symbol]
                total_cost = pos.market_value + trade_value
                pos.quantity += order.quantity
                pos.entry_price = total_cost / pos.quantity
            else:
                self.positions[order.symbol] = Position(
                    symbol=order.symbol,
                    quantity=order.quantity,
                    entry_price=fill_price,
                    entry_time=bar['timestamp'],
                    side=OrderSide.BUY
                )
        else:
            # 卖出
            proceeds = trade_value - commission
            self.capital += proceeds

            # 计算盈亏
            position = self.positions.get(order.symbol)
            if position:
                cost_basis = order.quantity * position.entry_price
                pnl = proceeds - cost_basis - commission

                # 记录交易
                self.trades.append(Trade(
                    timestamp=bar['timestamp'],
                    symbol=order.symbol,
                    side=OrderSide.SELL,
                    quantity=order.quantity,
                    price=fill_price,
                    commission=commission,
                    pnl=pnl
                ))

                # 更新持仓
                position.quantity -= order.quantity
                if position.quantity <= 0:
                    del self.positions[order.symbol]

    def _update_positions(self, bar: pd.Series):
        """更新持仓市值"""
        # 这里可以更新持仓的当前市值
        pass

    def _check_stop_loss_take_profit(self, bar: pd.Series):
        """检查止损止盈"""
        for symbol, position in list(self.positions.items()):
            current_price = bar['close']

            if position.side == OrderSide.BUY:
                # 多头止损
                if self.config.enable_stop_loss:
                    stop_price = position.entry_price * (1 - self.config.stop_loss_pct)
                    if current_price <= stop_price:
                        logger.info(f"Stop loss triggered for {symbol} at {current_price}")
                        self.sell(symbol, position.quantity)
                        continue

                # 多头止盈
                if self.config.enable_take_profit:
                    take_profit_price = position.entry_price * (1 + self.config.take_profit_pct)
                    if current_price >= take_profit_price:
                        logger.info(f"Take profit triggered for {symbol} at {current_price}")
                        self.sell(symbol, position.quantity)

    def _close_all_positions(self):
        """平掉所有仓位"""
        for symbol in list(self.positions.keys()):
            self.sell(symbol)

    def _get_positions_value(self) -> float:
        """获取持仓总价值"""
        if not self.positions or self.current_bar is None:
            return 0.0

        total = 0.0
        current_price = self.current_bar['close']
        for position in self.positions.values():
            total += position.quantity * current_price
        return total

    def _generate_result(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> BacktestResult:
        """生成回测结果"""
        # 计算统计指标
        total_trades = len(self.trades)
        if total_trades == 0:
            return BacktestResult(
                config=self.config,
                start_date=start_date,
                end_date=end_date,
                initial_capital=self.config.initial_capital,
                final_capital=self.capital,
                total_return=0,
                total_return_pct=0,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0,
                avg_profit=0,
                avg_loss=0,
                profit_factor=0,
                max_drawdown=0,
                max_drawdown_pct=0,
                sharpe_ratio=0,
                volatility=0,
                trades=[],
                equity_curve=pd.DataFrame(self.equity_curve),
                metrics={}
            )

        # 盈亏统计
        profits = [t.pnl for t in self.trades if t.pnl and t.pnl > 0]
        losses = [t.pnl for t in self.trades if t.pnl and t.pnl <= 0]

        winning_trades = len(profits)
        losing_trades = len(losses)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0

        avg_profit = np.mean(profits) if profits else 0
        avg_loss = np.mean(losses) if losses else 0

        total_profit = sum(profits)
        total_loss = abs(sum(losses))
        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')

        # 计算回撤
        equity_df = pd.DataFrame(self.equity_curve)
        if not equity_df.empty:
            equity_df['peak'] = equity_df['equity'].cummax()
            equity_df['drawdown'] = equity_df['equity'] - equity_df['peak']
            equity_df['drawdown_pct'] = equity_df['drawdown'] / equity_df['peak']

            max_drawdown = equity_df['drawdown'].min()
            max_drawdown_pct = equity_df['drawdown_pct'].min()

            # 计算夏普比率
            returns = equity_df['equity'].pct_change().dropna()
            if len(returns) > 1 and returns.std() > 0:
                sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(252 * 24)  # 假设小时数据
                volatility = returns.std() * np.sqrt(252 * 24)
            else:
                sharpe_ratio = 0
                volatility = 0
        else:
            max_drawdown = 0
            max_drawdown_pct = 0
            sharpe_ratio = 0
            volatility = 0

        # 总收益
        total_return = self.capital - self.config.initial_capital
        total_return_pct = total_return / self.config.initial_capital

        return BacktestResult(
            config=self.config,
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.config.initial_capital,
            final_capital=self.capital,
            total_return=total_return,
            total_return_pct=total_return_pct,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            avg_profit=avg_profit,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            sharpe_ratio=sharpe_ratio,
            volatility=volatility,
            trades=self.trades,
            equity_curve=equity_df if not equity_df.empty else pd.DataFrame(),
            metrics={
                'total_commission': sum(t.commission for t in self.trades),
                'avg_trade_size': np.mean([t.quantity for t in self.trades]) if self.trades else 0
            }
        )

    def get_position(self, symbol: str) -> Optional[Position]:
        """获取持仓"""
        return self.positions.get(symbol)

    def get_cash(self) -> float:
        """获取现金"""
        return self.capital

    def get_total_value(self) -> float:
        """获取总资产"""
        return self.capital + self._get_positions_value()
