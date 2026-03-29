# backtest/engine.py
"""
回测引擎模块。

提供完整的回测功能，支持多策略、多币种、风险平价资金分配。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Callable, Protocol
from dataclasses import dataclass, field

from backtest.metrics import BacktestMetrics
from portfolio.covariance import calculate_returns, calculate_covariance
from portfolio.risk_parity import risk_parity_weights


class StrategyProtocol(Protocol):
    """策略协议。"""

    name: str

    def generate_signal(self, data: pd.DataFrame) -> dict | None:
        """
        生成交易信号。

        Returns:
            dict with keys:
                - side: 1 (做多) / -1 (做空) / 0 (平仓)
                - strength: 信号强度 (0-1)
        """
        ...


@dataclass
class BacktestConfig:
    """回测配置。"""

    initial_capital: float = 10000.0
    commission_rate: float = 0.001
    slippage: float = 0.0001
    max_position: float = 0.8
    risk_free_rate: float = 0.0
    periods_per_year: int = 365

    # 风险平价配置
    use_risk_parity: bool = True
    risk_lookback: int = 60
    rebalance_freq: int = 5


@dataclass
class Position:
    """仓位信息。"""

    symbol: str
    quantity: float = 0.0
    entry_price: float = 0.0
    side: int = 0  # 1: long, -1: short, 0: flat

    @property
    def is_long(self) -> bool:
        return self.side > 0

    @property
    def is_short(self) -> bool:
        return self.side < 0

    @property
    def is_flat(self) -> bool:
        return self.side == 0

    def market_value(self, price: float) -> float:
        """计算市值。"""
        return self.quantity * price * self.side

    def unrealized_pnl(self, price: float) -> float:
        """计算未实现盈亏。"""
        if self.is_flat:
            return 0.0
        return self.quantity * (price - self.entry_price) * self.side


@dataclass
class Trade:
    """交易记录。"""

    timestamp: pd.Timestamp
    symbol: str
    side: str  # 'BUY' / 'SELL'
    quantity: float
    price: float
    commission: float
    pnl: float = 0.0


class BacktestEngine:
    """
    回测引擎。

    支持：
    - 多策略回测
    - 多币种组合
    - 风险平价资金分配
    - 目标仓位对齐
    """

    def __init__(
        self,
        config: BacktestConfig | None = None,
    ):
        self.config = config or BacktestConfig()

        # 状态
        self.equity: float = self.config.initial_capital
        self.cash: float = self.config.initial_capital
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.equity_curve: list[float] = []
        self.timestamps: list[pd.Timestamp] = []

        # 策略
        self.strategies: list[StrategyProtocol] = []

    def add_strategy(self, strategy: StrategyProtocol) -> None:
        """添加策略。"""
        self.strategies.append(strategy)

    def reset(self) -> None:
        """重置状态。"""
        self.equity = self.config.initial_capital
        self.cash = self.config.initial_capital
        self.positions = {}
        self.trades = []
        self.equity_curve = []
        self.timestamps = []

    def run(
        self,
        data: dict[str, pd.DataFrame],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> dict:
        """
        运行回测。

        Args:
            data: dict，key为symbol，value为价格DataFrame
            progress_callback: 进度回调函数(current, total)

        Returns:
            回测结果字典
        """
        self.reset()

        # 获取所有时间戳
        all_timestamps = self._align_timestamps(data)
        symbols = list(data.keys())

        if not all_timestamps or not symbols:
            return self._empty_result()

        # 初始化持仓
        for symbol in symbols:
            self.positions[symbol] = Position(symbol=symbol)

        # 回测循环
        for i, timestamp in enumerate(all_timestamps):
            # 更新进度
            if progress_callback:
                progress_callback(i + 1, len(all_timestamps))

            # 获取当前窗口数据
            window_data = self._get_window_data(data, timestamp, i)

            # 生成信号
            signals = self._generate_signals(window_data)

            # 计算目标权重
            if self.config.use_risk_parity and len(symbols) > 1:
                target_weights = self._calculate_risk_parity_weights(data, i)
            else:
                target_weights = self._calculate_equal_weights(signals)

            # 计算目标仓位
            target_positions = self._calculate_target_positions(
                target_weights, timestamp, data
            )

            # 执行再平衡
            self._rebalance(target_positions, timestamp, data)

            # 更新权益
            self._update_equity(timestamp, data)

            # 记录
            self.equity_curve.append(self.equity)
            self.timestamps.append(timestamp)

        # 计算结果
        return self._calculate_results()

    def _align_timestamps(self, data: dict[str, pd.DataFrame]) -> list[pd.Timestamp]:
        """对齐所有币种的时间戳。"""
        timestamps = None
        for df in data.values():
            if timestamps is None:
                timestamps = set(df.index)
            else:
                timestamps &= set(df.index)
        return sorted(list(timestamps)) if timestamps else []

    def _get_window_data(
        self,
        data: dict[str, pd.DataFrame],
        timestamp: pd.Timestamp,
        idx: int,
    ) -> dict[str, pd.DataFrame]:
        """获取当前窗口的历史数据。"""
        window = {}
        for symbol, df in data.items():
            # 获取到当前时间点的所有数据
            mask = df.index <= timestamp
            window[symbol] = df[mask]
        return window

    def _generate_signals(self, window_data: dict[str, pd.DataFrame]) -> dict[str, list]:
        """生成所有策略的信号。"""
        signals = {}
        for symbol, df in window_data.items():
            signals[symbol] = []
            for strategy in self.strategies:
                try:
                    signal = strategy.generate_signal(df)
                    if signal:
                        signals[symbol].append({
                            "strategy": strategy.name,
                            **signal
                        })
                except Exception:
                    continue
        return signals

    def _calculate_risk_parity_weights(
        self,
        data: dict[str, pd.DataFrame],
        end_idx: int,
    ) -> dict[str, float]:
        """计算风险平价权重。"""
        # 计算收益率
        returns_dict = {}
        for symbol, df in data.items():
            if len(df) < self.config.risk_lookback:
                continue
            prices = df["close"].iloc[max(0, end_idx - self.config.risk_lookback):end_idx]
            if len(prices) > 1:
                returns = np.log(prices / prices.shift(1)).dropna()
                if len(returns) > 0:
                    returns_dict[symbol] = returns

        if len(returns_dict) < 2:
            return {s: 1.0 / len(data) for s in data}

        # 构建收益率DataFrame
        returns_df = pd.DataFrame(returns_dict)
        returns_df = returns_df.dropna()

        if len(returns_df) < 10:
            return {s: 1.0 / len(data) for s in data}

        # 计算协方差矩阵
        cov_matrix = calculate_covariance(returns_df, method="shrinkage")

        # 计算风险平价权重
        try:
            weights_array = risk_parity_weights(cov_matrix.values)
            symbols = list(cov_matrix.index)
            return {s: w for s, w in zip(symbols, weights_array)}
        except Exception:
            return {s: 1.0 / len(data) for s in data}

    def _calculate_equal_weights(self, signals: dict[str, list]) -> dict[str, float]:
        """计算等权权重。"""
        active_symbols = [s for s, sigs in signals.items() if sigs]
        if not active_symbols:
            return {}
        return {s: 1.0 / len(active_symbols) for s in active_symbols}

    def _calculate_target_positions(
        self,
        weights: dict[str, float],
        timestamp: pd.Timestamp,
        data: dict[str, pd.DataFrame],
    ) -> dict[str, float]:
        """计算目标仓位（数量）。"""
        targets = {}
        for symbol, weight in weights.items():
            if symbol not in data or timestamp not in data[symbol].index:
                continue

            price = data[symbol].loc[timestamp, "close"]
            if price <= 0:
                continue

            # 目标市值
            target_value = self.equity * weight * self.config.max_position

            # 目标数量
            targets[symbol] = target_value / price

        return targets

    def _rebalance(
        self,
        target_positions: dict[str, float],
        timestamp: pd.Timestamp,
        data: dict[str, pd.DataFrame],
    ) -> None:
        """执行仓位再平衡。"""
        all_symbols = set(self.positions.keys()) | set(target_positions.keys())

        for symbol in all_symbols:
            if symbol not in data or timestamp not in data[symbol].index:
                continue

            price = data[symbol].loc[timestamp, "close"]
            if price <= 0:
                continue

            current_pos = self.positions.get(symbol, Position(symbol=symbol))
            target_qty = target_positions.get(symbol, 0.0)

            # 计算差异
            diff = target_qty - current_pos.quantity * current_pos.side

            # 忽略小差异
            if abs(diff) * price < self.equity * 0.001:
                continue

            # 执行交易
            if diff > 0:
                # 买入
                self._execute_trade(
                    timestamp, symbol, "BUY", diff, price, current_pos
                )
            elif diff < 0:
                # 卖出
                self._execute_trade(
                    timestamp, symbol, "SELL", abs(diff), price, current_pos
                )

    def _execute_trade(
        self,
        timestamp: pd.Timestamp,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        position: Position,
    ) -> None:
        """执行单笔交易。"""
        # 滑点
        slippage = self.config.slippage * price
        executed_price = price + slippage if side == "BUY" else price - slippage

        # 佣金
        trade_value = quantity * executed_price
        commission = trade_value * self.config.commission_rate

        # 计算盈亏（平仓部分）
        pnl = 0.0
        if not position.is_flat and (
            (position.is_long and side == "SELL") or
            (position.is_short and side == "BUY")
        ):
            close_qty = min(quantity, position.quantity)
            pnl = close_qty * (executed_price - position.entry_price)
            if position.is_short:
                pnl = -pnl

        # 记录交易
        trade = Trade(
            timestamp=timestamp,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=executed_price,
            commission=commission,
            pnl=pnl,
        )
        self.trades.append(trade)

        # 更新现金
        if side == "BUY":
            self.cash -= trade_value + commission
        else:
            self.cash += trade_value - commission

        # 更新持仓
        new_pos = Position(symbol=symbol)
        if side == "BUY":
            if position.is_long or position.is_flat:
                # 加仓或新开多仓
                total_qty = position.quantity + quantity
                avg_price = (
                    position.quantity * position.entry_price + quantity * executed_price
                ) / total_qty if total_qty > 0 else executed_price
                new_pos.quantity = total_qty
                new_pos.entry_price = avg_price
                new_pos.side = 1
            else:
                # 平空仓
                remaining = position.quantity - quantity
                if remaining > 0:
                    new_pos.quantity = remaining
                    new_pos.entry_price = position.entry_price
                    new_pos.side = -1
        else:  # SELL
            if position.is_short or position.is_flat:
                # 加空仓或新开空仓
                total_qty = position.quantity + quantity
                avg_price = (
                    position.quantity * position.entry_price + quantity * executed_price
                ) / total_qty if total_qty > 0 else executed_price
                new_pos.quantity = total_qty
                new_pos.entry_price = avg_price
                new_pos.side = -1
            else:
                # 平多仓
                remaining = position.quantity - quantity
                if remaining > 0:
                    new_pos.quantity = remaining
                    new_pos.entry_price = position.entry_price
                    new_pos.side = 1

        self.positions[symbol] = new_pos

    def _update_equity(
        self,
        timestamp: pd.Timestamp,
        data: dict[str, pd.DataFrame],
    ) -> None:
        """更新权益。"""
        position_value = 0.0
        for symbol, pos in self.positions.items():
            if symbol in data and timestamp in data[symbol].index:
                price = data[symbol].loc[timestamp, "close"]
                position_value += pos.market_value(price)

        self.equity = self.cash + position_value

    def _calculate_results(self) -> dict:
        """计算回测结果。"""
        if not self.equity_curve or len(self.equity_curve) < 2:
            return self._empty_result()

        # 计算收益率
        returns = pd.Series(self.equity_curve).pct_change().dropna()

        # 计算指标
        metrics = BacktestMetrics(
            returns=returns.values,
            equity_curve=self.equity_curve,
            trades=self.trades,
            risk_free_rate=self.config.risk_free_rate,
            periods_per_year=self.config.periods_per_year,
        )

        return {
            "equity_curve": pd.Series(self.equity_curve, index=self.timestamps),
            "returns": returns,
            "trades": pd.DataFrame([{
                "timestamp": t.timestamp,
                "symbol": t.symbol,
                "side": t.side,
                "quantity": t.quantity,
                "price": t.price,
                "commission": t.commission,
                "pnl": t.pnl,
            } for t in self.trades]),
            "positions": self.positions,
            "metrics": metrics,
            "final_equity": self.equity,
            "total_return": (self.equity - self.config.initial_capital)
                / self.config.initial_capital,
        }

    def _empty_result(self) -> dict:
        """返回空结果。"""
        return {
            "equity_curve": pd.Series(),
            "returns": pd.Series(),
            "trades": pd.DataFrame(),
            "positions": {},
            "metrics": None,
            "final_equity": self.config.initial_capital,
            "total_return": 0.0,
        }


def run_walk_forward_analysis(
    data: dict[str, pd.DataFrame],
    strategy_factory: Callable[[], StrategyProtocol],
    train_size: int = 252,
    test_size: int = 63,
    config: BacktestConfig | None = None,
) -> list[dict]:
    """
    执行滚动回测（Walk-Forward Analysis）。

    防止过拟合的标准方法。

    Args:
        data: 历史数据
        strategy_factory: 策略工厂函数
        train_size: 训练窗口大小
        test_size: 测试窗口大小
        config: 回测配置

    Returns:
        各窗口的回测结果列表
    """
    results = []

    # 获取所有时间戳
    timestamps = sorted(set.intersection(*[set(df.index) for df in data.values()]))

    if len(timestamps) < train_size + test_size:
        return results

    # 滚动窗口
    start_idx = 0
    while start_idx + train_size + test_size <= len(timestamps):
        # 训练期
        train_end = start_idx + train_size
        # 测试期
        test_end = min(train_end + test_size, len(timestamps))

        # 训练数据
        train_data = {
            s: df.iloc[start_idx:train_end]
            for s, df in data.items()
        }

        # 测试数据
        test_data = {
            s: df.iloc[train_end:test_end]
            for s, df in data.items()
        }

        # 训练策略（如果需要）
        strategy = strategy_factory()

        # 回测测试期
        engine = BacktestEngine(config=config)
        engine.add_strategy(strategy)
        result = engine.run(test_data)

        results.append({
            "window": len(results) + 1,
            "train_start": timestamps[start_idx],
            "train_end": timestamps[train_end - 1],
            "test_start": timestamps[train_end],
            "test_end": timestamps[test_end - 1],
            **result
        })

        # 移动到下一个窗口
        start_idx += test_size

    return results

