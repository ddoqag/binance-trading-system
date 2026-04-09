"""
反转策略回测核心模块

功能:
- 信号生成与交易执行
- 滑点和手续费模拟
- 持仓和资金管理
- 交易记录和盈亏跟踪
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('ReversalBacktester')


class SignalType(Enum):
    """信号类型"""
    BUY = 1
    SELL = -1
    HOLD = 0


class PositionSide(Enum):
    """持仓方向"""
    LONG = 1
    SHORT = -1
    FLAT = 0


@dataclass
class Trade:
    """交易记录"""
    timestamp: datetime
    symbol: str
    side: str  # 'buy' or 'sell'
    qty: float
    price: float
    fee: float
    slippage: float
    signal_strength: float
    pnl: float = 0.0


@dataclass
class Position:
    """持仓状态"""
    symbol: str
    side: PositionSide
    qty: float
    entry_price: float
    entry_time: datetime
    unrealized_pnl: float = 0.0

    def update_unrealized_pnl(self, current_price: float):
        """更新浮动盈亏"""
        if self.side == PositionSide.LONG:
            self.unrealized_pnl = (current_price - self.entry_price) * self.qty
        elif self.side == PositionSide.SHORT:
            self.unrealized_pnl = (self.entry_price - current_price) * self.qty
        else:
            self.unrealized_pnl = 0.0


@dataclass
class BacktestConfig:
    """回测配置

    与接口规范对齐:
    - slippage_bps: 滑点
    - fee_bps: 手续费 (maker/taker)
    - initial_capital: 初始资金
    - signal_threshold: 信号阈值
    - position_size: 固定仓位或基于信号
    - max_position: 最大持仓
    """
    # 资金配置
    initial_capital: float = 1000000.0
    max_position_size: float = 0.2  # 最大仓位比例 (对应 max_position)
    position_sizing: str = 'signal_based'  # 'fixed' or 'signal_based' (对应 position_size)

    # 交易成本
    slippage_bps: float = 0.5  # 滑点 (bps)
    fee_bps: float = 2.0  # 手续费 (bps) - 统一费率
    maker_fee_bps: float = 2.0  # maker手续费 (bps)
    taker_fee_bps: float = 2.0  # taker手续费 (bps)

    # 信号参数
    signal_threshold: float = 0.3  # 信号阈值
    min_signal_strength: float = 0.1  # 最小信号强度

    # 风险控制
    stop_loss_pct: Optional[float] = None  # 止损百分比
    take_profit_pct: Optional[float] = None  # 止盈百分比
    max_drawdown_pct: Optional[float] = None  # 最大回撤限制

    # 交易对
    symbol: str = 'BTCUSDT'

    def __post_init__(self):
        """初始化后处理，确保接口兼容性"""
        # 如果 fee_bps 被设置，同步更新 maker/taker 费率
        if hasattr(self, 'fee_bps') and self.fee_bps != 2.0:
            self.maker_fee_bps = self.fee_bps
            self.taker_fee_bps = self.fee_bps


@dataclass
class BacktestResult:
    """回测结果"""
    config: BacktestConfig
    start_time: datetime
    end_time: datetime

    # 盈亏指标
    initial_capital: float
    final_capital: float
    total_return: float
    total_return_pct: float

    # 交易统计
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float

    # 风险指标
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    volatility: float

    # 盈亏比
    profit_factor: float
    avg_profit: float
    avg_loss: float

    # 详细数据
    equity_curve: pd.DataFrame
    trades_df: pd.DataFrame
    signals_df: pd.DataFrame


class ReversalBacktester:
    """
    反转策略回测器

    支持:
    - 基于模型预测的信号生成
    - 滑点和手续费模拟
    - 固定或基于信号强度的仓位管理
    - 完整的交易记录和盈亏跟踪
    """

    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()

        # 资金状态
        self.cash: float = self.config.initial_capital
        self.current_capital: float = self.config.initial_capital

        # 持仓
        self.position: Optional[Position] = None

        # 交易记录
        self.trades: List[Trade] = []

        # 权益曲线
        self.equity_curve: List[Dict] = []

        # 信号记录
        self.signals: List[Dict] = []

        # 统计
        self.trade_counter: int = 0
        self.peak_capital: float = self.config.initial_capital

        logger.info(f"ReversalBacktester initialized: {self.config.symbol}")
        logger.info(f"  Initial capital: ${self.config.initial_capital:,.2f}")
        logger.info(f"  Slippage: {self.config.slippage_bps} bps")
        logger.info(f"  Fee: {self.config.maker_fee_bps} bps")

    def reset(self):
        """重置回测状态"""
        self.cash = self.config.initial_capital
        self.current_capital = self.config.initial_capital
        self.position = None
        self.trades = []
        self.equity_curve = []
        self.signals = []
        self.trade_counter = 0
        self.peak_capital = self.config.initial_capital

    def calculate_position_size(self, signal_strength: float, current_price: float) -> float:
        """
        计算仓位大小

        Args:
            signal_strength: 信号强度 (0-1)
            current_price: 当前价格

        Returns:
            交易数量
        """
        if self.config.position_sizing == 'fixed':
            # 固定仓位
            position_value = self.current_capital * self.config.max_position_size
        else:
            # 基于信号强度的仓位
            position_value = self.current_capital * self.config.max_position_size * signal_strength

        qty = position_value / current_price
        return qty

    def apply_slippage(self, price: float, side: str, is_market_order: bool = False) -> float:
        """
        应用滑点

        Args:
            price: 原始价格
            side: 'buy' or 'sell'
            is_market_order: 是否市价单

        Returns:
            应用滑点后的价格
        """
        slippage_pct = self.config.slippage_bps / 10000.0

        # 市价单滑点更大
        if is_market_order:
            slippage_pct *= 2.0

        if side == 'buy':
            # 买入滑点使价格更高
            return price * (1 + slippage_pct)
        else:
            # 卖出滑点使价格更低
            return price * (1 - slippage_pct)

    def calculate_fee(self, trade_value: float, is_maker: bool = True) -> float:
        """
        计算手续费

        Args:
            trade_value: 交易金额
            is_maker: 是否maker订单

        Returns:
            手续费金额
        """
        fee_bps = self.config.maker_fee_bps if is_maker else self.config.taker_fee_bps
        return trade_value * (fee_bps / 10000.0)

    def generate_signal(self, prediction: float, features: Optional[Dict] = None) -> tuple:
        """
        生成交易信号

        Args:
            prediction: 模型预测值 (-1 to 1)
            features: 特征字典（可选）

        Returns:
            (signal_type, signal_strength)
        """
        # 应用阈值
        if abs(prediction) < self.config.signal_threshold:
            return SignalType.HOLD, 0.0

        # 信号强度 (0-1)
        signal_strength = min(abs(prediction), 1.0)

        if prediction > 0:
            return SignalType.BUY, signal_strength
        else:
            return SignalType.SELL, signal_strength

    def execute_trade(self,
                     timestamp: datetime,
                     signal_type: SignalType,
                     signal_strength: float,
                     price: float,
                     is_maker: bool = True) -> Optional[Trade]:
        """
        执行交易

        Args:
            timestamp: 时间戳
            signal_type: 信号类型
            signal_strength: 信号强度
            price: 当前价格
            is_maker: 是否maker订单

        Returns:
            Trade or None
        """
        if signal_type == SignalType.HOLD:
            return None

        # 确定交易方向
        if signal_type == SignalType.BUY:
            side = 'buy'
            target_side = PositionSide.LONG
        else:
            side = 'sell'
            target_side = PositionSide.SHORT

        # 检查是否需要交易
        if self.position:
            if self.position.side == PositionSide.LONG and signal_type == SignalType.BUY:
                # 已经持有多头，不再买入
                return None
            if self.position.side == PositionSide.SHORT and signal_type == SignalType.SELL:
                # 已经持有空头，不再卖出
                return None

        # 计算仓位大小
        qty = self.calculate_position_size(signal_strength, price)
        if qty <= 0:
            return None

        # 应用滑点
        executed_price = self.apply_slippage(price, side, is_maker)

        # 如果有反向持仓，先平仓
        realized_pnl = 0.0
        if self.position and self.position.side != target_side:
            # 平仓
            if self.position.side == PositionSide.LONG:
                # 平多仓
                realized_pnl = (executed_price - self.position.entry_price) * self.position.qty
            else:
                # 平空仓
                realized_pnl = (self.position.entry_price - executed_price) * self.position.qty

            close_value = self.position.qty * executed_price
            close_fee = self.calculate_fee(close_value, is_maker)

            self.cash += close_value - close_fee + realized_pnl

            # 记录平仓交易
            self.trade_counter += 1
            close_trade = Trade(
                timestamp=timestamp,
                symbol=self.config.symbol,
                side='sell' if self.position.side == PositionSide.LONG else 'buy',
                qty=self.position.qty,
                price=executed_price,
                fee=close_fee,
                slippage=abs(executed_price - price),
                signal_strength=signal_strength,
                pnl=realized_pnl - close_fee
            )
            self.trades.append(close_trade)

            self.position = None

        # 开新仓
        trade_value = qty * executed_price
        fee = self.calculate_fee(trade_value, is_maker)
        total_cost = trade_value + fee

        if total_cost > self.cash:
            logger.warning(f"资金不足: 需要 ${total_cost:.2f}, 可用 ${self.cash:.2f}")
            return None

        self.cash -= total_cost

        self.position = Position(
            symbol=self.config.symbol,
            side=target_side,
            qty=qty,
            entry_price=executed_price,
            entry_time=timestamp
        )

        # 记录开仓交易
        self.trade_counter += 1
        trade = Trade(
            timestamp=timestamp,
            symbol=self.config.symbol,
            side=side,
            qty=qty,
            price=executed_price,
            fee=fee,
            slippage=abs(executed_price - price),
            signal_strength=signal_strength,
            pnl=-fee  # 开仓时盈亏为负（手续费）
        )
        self.trades.append(trade)

        logger.debug(f"交易执行: {side} {qty:.6f} @ ${executed_price:.2f}, fee: ${fee:.4f}")

        return trade

    def update_equity(self, timestamp: datetime, current_price: float):
        """更新权益曲线"""
        # 计算持仓价值
        position_value = 0.0
        unrealized_pnl = 0.0

        if self.position:
            self.position.update_unrealized_pnl(current_price)
            position_value = self.position.qty * current_price
            unrealized_pnl = self.position.unrealized_pnl

        total_equity = self.cash + position_value
        self.current_capital = total_equity

        # 更新峰值
        if total_equity > self.peak_capital:
            self.peak_capital = total_equity

        self.equity_curve.append({
            'timestamp': timestamp,
            'equity': total_equity,
            'cash': self.cash,
            'position_value': position_value,
            'unrealized_pnl': unrealized_pnl,
            'position_side': self.position.side.value if self.position else 0,
            'position_qty': self.position.qty if self.position else 0.0
        })

    def check_stop_loss_take_profit(self, current_price: float) -> Optional[SignalType]:
        """检查止损止盈条件"""
        if not self.position:
            return None

        price_change_pct = (current_price - self.position.entry_price) / self.position.entry_price

        if self.position.side == PositionSide.SHORT:
            price_change_pct = -price_change_pct

        # 止损检查
        if self.config.stop_loss_pct and price_change_pct < -self.config.stop_loss_pct:
            logger.debug(f"止损触发: {price_change_pct:.2%}")
            return SignalType.SELL if self.position.side == PositionSide.LONG else SignalType.BUY

        # 止盈检查
        if self.config.take_profit_pct and price_change_pct > self.config.take_profit_pct:
            logger.debug(f"止盈触发: {price_change_pct:.2%}")
            return SignalType.SELL if self.position.side == PositionSide.LONG else SignalType.BUY

        return None

    def check_max_drawdown(self) -> bool:
        """检查是否触发最大回撤限制"""
        if not self.config.max_drawdown_pct:
            return False

        drawdown_pct = (self.peak_capital - self.current_capital) / self.peak_capital
        return drawdown_pct > self.config.max_drawdown_pct

    def run_backtest(self,
                    data: pd.DataFrame,
                    model: Optional[Any] = None,
                    feature_engineer: Optional[Any] = None,
                    progress_interval: int = 1000) -> BacktestResult:
        """
        运行回测

        Args:
            data: 市场数据DataFrame (需要包含 open, high, low, close, volume)
            model: 预测模型（可选，如果没有则使用随机信号）
            feature_engineer: 特征工程器（可选）
            progress_interval: 进度报告间隔

        Returns:
            BacktestResult
        """
        start_time = datetime.now()
        logger.info(f"开始回测: {len(data)} 条数据")

        # 重置状态
        self.reset()

        # 遍历数据
        for i, (timestamp, row) in enumerate(data.iterrows()):
            current_price = row['close']

            # 生成预测
            prediction = 0.0
            if model is not None:
                try:
                    # 优先使用 predict_signal_strength 接口
                    if hasattr(model, 'predict_signal_strength'):
                        if feature_engineer:
                            features = feature_engineer.transform_row(row)
                        else:
                            # 直接使用行数据作为特征
                            features = row.values if hasattr(row, 'values') else row
                        prediction = model.predict_signal_strength(features)
                    elif hasattr(model, 'predict'):
                        if feature_engineer:
                            features = feature_engineer.transform_row(row)
                        else:
                            features = row.values if hasattr(row, 'values') else row
                        prediction = model.predict(features)
                    else:
                        logger.warning("模型缺少 predict_signal_strength 或 predict 方法")
                except Exception as e:
                    logger.warning(f"预测失败: {e}")
                    prediction = 0.0
            else:
                # 随机信号（用于测试）
                prediction = np.random.randn() * 0.5

            # 生成信号
            signal_type, signal_strength = self.generate_signal(prediction)

            # 记录信号
            self.signals.append({
                'timestamp': timestamp,
                'price': current_price,
                'prediction': prediction,
                'signal': signal_type.value,
                'signal_strength': signal_strength
            })

            # 检查止损止盈
            exit_signal = self.check_stop_loss_take_profit(current_price)
            if exit_signal:
                signal_type = exit_signal
                signal_strength = 1.0

            # 执行交易
            if signal_type != SignalType.HOLD and signal_strength >= self.config.min_signal_strength:
                self.execute_trade(
                    timestamp=timestamp,
                    signal_type=signal_type,
                    signal_strength=signal_strength,
                    price=current_price,
                    is_maker=True
                )

            # 更新权益
            self.update_equity(timestamp, current_price)

            # 检查最大回撤
            if self.check_max_drawdown():
                logger.warning("触发最大回撤限制，停止回测")
                break

            # 进度报告
            if (i + 1) % progress_interval == 0:
                progress = (i + 1) / len(data) * 100
                equity = self.current_capital
                pnl = equity - self.config.initial_capital
                logger.info(f"进度: {progress:.1f}% | 权益: ${equity:,.2f} | 盈亏: ${pnl:,.2f}")

        end_time = datetime.now()
        logger.info(f"回测完成，用时 {(end_time - start_time).total_seconds():.1f} 秒")

        return self._generate_result(start_time, end_time)

    def _generate_result(self, start_time: datetime, end_time: datetime) -> BacktestResult:
        """生成回测结果"""
        # 创建DataFrames
        equity_df = pd.DataFrame(self.equity_curve)
        trades_df = pd.DataFrame([
            {
                'timestamp': t.timestamp,
                'symbol': t.symbol,
                'side': t.side,
                'qty': t.qty,
                'price': t.price,
                'fee': t.fee,
                'slippage': t.slippage,
                'signal_strength': t.signal_strength,
                'pnl': t.pnl
            }
            for t in self.trades
        ])
        signals_df = pd.DataFrame(self.signals)

        # 计算指标
        final_capital = self.current_capital
        total_return = final_capital - self.config.initial_capital
        total_return_pct = total_return / self.config.initial_capital

        # 交易统计
        total_trades = len(self.trades)
        if total_trades > 0:
            profits = [t.pnl for t in self.trades if t.pnl > 0]
            losses = [t.pnl for t in self.trades if t.pnl <= 0]

            winning_trades = len(profits)
            losing_trades = len(losses)
            win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

            avg_profit = np.mean(profits) if profits else 0.0
            avg_loss = np.mean(losses) if losses else 0.0

            profit_factor = abs(sum(profits) / sum(losses)) if losses and sum(losses) != 0 else float('inf')
        else:
            winning_trades = losing_trades = 0
            win_rate = 0.0
            avg_profit = avg_loss = 0.0
            profit_factor = 0.0

        # 计算最大回撤
        if not equity_df.empty:
            equity_df['peak'] = equity_df['equity'].cummax()
            equity_df['drawdown'] = equity_df['equity'] - equity_df['peak']
            equity_df['drawdown_pct'] = equity_df['drawdown'] / equity_df['peak']

            max_drawdown = equity_df['drawdown'].min()
            max_drawdown_pct = equity_df['drawdown_pct'].min()

            # 计算夏普比率
            returns = equity_df['equity'].pct_change().dropna()
            if len(returns) > 1 and returns.std() > 0:
                sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(252)
                volatility = returns.std() * np.sqrt(252)
            else:
                sharpe_ratio = 0.0
                volatility = 0.0
        else:
            max_drawdown = max_drawdown_pct = 0.0
            sharpe_ratio = volatility = 0.0

        return BacktestResult(
            config=self.config,
            start_time=start_time,
            end_time=end_time,
            initial_capital=self.config.initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            total_return_pct=total_return_pct,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            sharpe_ratio=sharpe_ratio,
            volatility=volatility,
            profit_factor=profit_factor,
            avg_profit=avg_profit,
            avg_loss=avg_loss,
            equity_curve=equity_df,
            trades_df=trades_df,
            signals_df=signals_df
        )


# 测试代码
if __name__ == "__main__":
    print("=" * 70)
    print("ReversalBacktester 测试")
    print("=" * 70)

    # 创建合成数据
    np.random.seed(42)
    n_samples = 5000
    dates = pd.date_range(start='2024-01-01', periods=n_samples, freq='1min')

    # 生成随机游走价格
    returns = np.random.randn(n_samples) * 0.001
    prices = 50000 * np.exp(np.cumsum(returns))

    data = pd.DataFrame({
        'open': prices * (1 + np.random.randn(n_samples) * 0.0001),
        'high': prices * (1 + abs(np.random.randn(n_samples)) * 0.001),
        'low': prices * (1 - abs(np.random.randn(n_samples)) * 0.001),
        'close': prices,
        'volume': np.random.uniform(1, 100, n_samples)
    }, index=dates)

    print(f"\n生成测试数据: {len(data)} 条")
    print(f"价格范围: ${data['close'].min():.2f} - ${data['close'].max():.2f}")

    # 配置回测
    config = BacktestConfig(
        initial_capital=1000000.0,
        max_position_size=0.2,
        slippage_bps=0.5,
        maker_fee_bps=2.0,
        signal_threshold=0.3,
        position_sizing='signal_based'
    )

    # 创建回测器
    backtester = ReversalBacktester(config)

    # 运行回测
    print("\n运行回测...")
    result = backtester.run_backtest(data, progress_interval=1000)

    # 打印结果
    print("\n" + "=" * 70)
    print("回测结果")
    print("=" * 70)
    print(f"\n盈亏:")
    print(f"  初始资金: ${result.initial_capital:,.2f}")
    print(f"  最终资金: ${result.final_capital:,.2f}")
    print(f"  总收益: ${result.total_return:,.2f} ({result.total_return_pct*100:.2f}%)")

    print(f"\n交易统计:")
    print(f"  总交易: {result.total_trades}")
    print(f"  盈利: {result.winning_trades}")
    print(f"  亏损: {result.losing_trades}")
    print(f"  胜率: {result.win_rate:.1%}")

    print(f"\n风险指标:")
    print(f"  最大回撤: ${result.max_drawdown:,.2f} ({result.max_drawdown_pct*100:.2f}%)")
    print(f"  夏普比率: {result.sharpe_ratio:.2f}")
    print(f"  波动率: {result.volatility:.2%}")

    print(f"\n盈亏比:")
    print(f"  盈亏比: {result.profit_factor:.2f}")
    print(f"  平均盈利: ${result.avg_profit:.2f}")
    print(f"  平均亏损: ${result.avg_loss:.2f}")

    print("\n" + "=" * 70)
    print("测试完成!")
