#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Portfolio Trader with Rust Execution Engine

展示如何在多策略交易系统中集成 Rust 高性能执行引擎。
"""

import os
import sys
import time
import logging
from typing import Optional, List
from dataclasses import dataclass

import numpy as np
import pandas as pd

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading_system.config import Config
from trading_system.data_feed import get_klines
from trading_system.strategy import AlphaStrategy
from risk.position import PositionManager
from risk.manager import RiskManager, RiskConfig
from trading_system.monitor import EquityMonitor
from portfolio_system.bandit_allocator import BanditAllocator

# Import Rust executor
try:
    from trading.rust_executor import (
        RustTradingExecutor, RustExecutionConfig, HybridExecutor, RUST_AVAILABLE
    )
    RUST_EXECUTOR_AVAILABLE = True
except ImportError:
    RUST_EXECUTOR_AVAILABLE = False

# Fallback to Python executor
from trading.leverage_executor import LeverageTradingExecutor, OrderSide, OrderType


logger = logging.getLogger(__name__)


@dataclass
class RustPortfolioConfig:
    """Rust 增强版 Portfolio Trader 配置"""

    # 基础配置
    symbol: str = 'BTCUSDT'
    interval: str = '1h'
    initial_balance: float = 10000.0

    # 风险配置
    max_position_size: float = 0.8
    max_single_position: float = 0.2
    risk_per_trade: float = 0.02
    atr_sl_multiplier: float = 2.0
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005

    # Rust 引擎配置
    use_rust_executor: bool = True
    rust_worker_threads: int = 4
    rust_queue_size: int = 10000
    rust_slippage_model: str = "fixed"

    # Bandit 配置
    entry_threshold: float = 0.3
    bandit_lr: float = 0.05


class RustPortfolioTrader:
    """
    Rust 增强版 Portfolio Trader

    使用 Rust 执行引擎进行高性能订单执行，同时保留 Python 的灵活策略逻辑。
    """

    def __init__(
        self,
        config: RustPortfolioConfig,
        strategies: Optional[List] = None,
        binance_client=None
    ):
        self.cfg = config
        self.entry_threshold = config.entry_threshold

        # 策略池
        if strategies is not None:
            self.strategies = strategies
        else:
            self.strategies = self._build_default_strategies()

        # Bandit 分配器
        self.allocator = BanditAllocator(
            n_arms=len(self.strategies),
            learning_rate=config.bandit_lr,
        )

        # 仓位和风控管理
        self.position = PositionManager(
            max_position_size=config.max_position_size,
            max_single_position=config.max_single_position,
            total_capital=config.initial_balance
        )
        self.risk = RiskManager(
            config=RiskConfig(
                max_position_size=config.max_position_size,
                max_single_position=config.max_single_position,
                total_capital=config.initial_balance
            )
        )

        # 使用 Rust 执行引擎（如果可用且启用）
        self.executor = self._create_executor(config, binance_client)

        self.monitor = EquityMonitor(
            initial_equity=config.initial_balance,
            drawdown_alert=-0.10,
            daily_loss_alert=-0.05,
        )

        self._last_active_arm: Optional[int] = None

        # 记录 Rust 引擎性能统计
        self._rust_stats = {
            'orders_submitted': 0,
            'total_latency_us': 0,
            'avg_latency_us': 0
        }

    def _create_executor(self, config: RustPortfolioConfig, binance_client):
        """创建执行器（优先使用 Rust）"""

        if config.use_rust_executor and RUST_EXECUTOR_AVAILABLE:
            try:
                rust_config = RustExecutionConfig(
                    worker_threads=config.rust_worker_threads,
                    queue_size=config.rust_queue_size,
                    slippage_model=config.rust_slippage_model,
                    commission_rate=config.fee_rate
                )

                executor = RustTradingExecutor(
                    initial_capital=config.initial_balance,
                    commission_rate=config.fee_rate,
                    slippage=config.slippage_rate,
                    config=rust_config
                )

                logger.info(
                    f"Rust Execution Engine initialized | "
                    f"threads={config.rust_worker_threads} | "
                    f"queue={config.rust_queue_size}"
                )
                return executor

            except Exception as e:
                logger.warning(f"Failed to initialize Rust executor: {e}. Falling back to Python.")

        # Fallback to Python executor
        logger.info("Using Python LeverageTradingExecutor")
        return LeverageTradingExecutor(
            initial_margin=config.initial_balance,
            max_leverage=1.0,
            commission_rate=config.fee_rate,
            slippage=config.slippage_rate,
            binance_client=binance_client
        )

    def step(self) -> None:
        """一个交易周期"""
        can_trade, reason = self.risk.can_trade(self.cfg.symbol, "BUY", 0, 0)
        if not can_trade:
            logger.warning("Circuit breaker triggered — %s", reason)
            return

        try:
            df = get_klines(self.cfg.symbol, self.cfg.interval, limit=100)
        except Exception as exc:
            logger.error("Data fetch failed: %s", exc)
            return

        # 1. 获取各策略信号
        signals = []
        for i, strategy in enumerate(self.strategies):
            try:
                sig = strategy.generate_signal(df)
            except Exception as exc:
                logger.warning("Strategy %d error: %s — using HOLD", i, exc)
                sig = 0
            signals.append(sig)

        # 2. Bandit 融合
        score = self.allocator.combined_score(signals)
        final_signal = self._score_to_signal(score)

        if final_signal != 0:
            self._last_active_arm = int(np.argmax(
                self.allocator.weights * np.abs(signals)
            ))

        logger.debug(
            "signals=%s weights=%s score=%.3f → signal=%d",
            signals,
            [f"{w:.3f}" for w in self.allocator.weights],
            score, final_signal,
        )

        # 3. ATR 风控和仓位计算
        from trading_system.features import add_features
        df_feat = add_features(df)
        last = df_feat.iloc[-1]
        price = float(last["close"])
        atr_val = last.get("atr")

        if atr_val is None or np.isnan(float(atr_val)) or float(atr_val) <= 0:
            return

        atr = float(atr_val)
        size = self._calc_position_size(price=price, atr=atr)
        if size <= 0:
            return

        # 4. 执行交易
        self._execute_signal(final_signal, price, size)

    def _execute_signal(self, signal: int, price: float, size: float) -> None:
        """执行交易信号"""
        symbol = self.cfg.symbol
        pos = self.position.get_position(symbol)
        has_position = pos is not None and pos.quantity > 0

        if not has_position:
            if signal == 1:
                # 使用 Rust 引擎下单
                if isinstance(self.executor, RustTradingExecutor):
                    # 初始化市场数据（如果是第一次交易该交易对）
                    self.executor.simulate_market_data(symbol, price)

                    order = self.executor.place_order(
                        symbol=symbol,
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        quantity=size,
                        current_price=price
                    )

                    # 记录性能统计
                    stats = self.executor.get_stats()
                    if stats['total_orders'] > 0:
                        self._rust_stats['orders_submitted'] = stats['total_orders']
                        self._rust_stats['avg_latency_us'] = stats['avg_latency_us']

                else:
                    # Python 执行器
                    order = self.executor.place_order(
                        symbol=symbol,
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        quantity=size,
                        leverage=1.0,
                        current_price=price
                    )

                self.position.open_position(symbol, size, price)
                logger.info(
                    "Opened LONG @ %.2f size=%.4f | Rust avg latency: %.2f μs",
                    price, size, self._rust_stats.get('avg_latency_us', 0)
                )

            elif signal == -1:
                logger.warning("Short selling not supported in this mode")

        elif has_position and signal == -1:
            self._close_and_update(price, "LONG")

    def _close_and_update(self, price: float, side: str) -> None:
        """平仓并更新 Bandit"""
        symbol = self.cfg.symbol
        pos = self.position.get_position(symbol)
        if pos is None:
            return

        pos.update_pnl(price)
        pnl = pos.unrealized_pnl

        # 使用 Rust 引擎平仓
        if isinstance(self.executor, RustTradingExecutor):
            self.executor.place_order(
                symbol=symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=pos.quantity,
                current_price=price
            )
        else:
            self.executor.place_order(
                symbol=symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=pos.quantity,
                leverage=1.0,
                current_price=price
            )

        self.risk.on_trade_executed(symbol, "SELL", pos.quantity, price, pnl)
        self.monitor.record_trade_pnl(pnl)
        self.position.close_position(symbol, price)

        # Bandit 更新
        if self._last_active_arm is not None:
            reward = pnl / max(self.cfg.initial_balance, 1.0)
            reward = float(np.clip(reward * 20, -1.0, 1.0))
            self.allocator.update(arm=self._last_active_arm, reward=reward)
            self._last_active_arm = None

        self.monitor.update(self.monitor.current_equity + pnl)
        logger.info(
            "Closed %s @ %.2f pnl=%.2f | %s | allocator=%s",
            side, price, pnl, self.monitor.summary(), self.allocator,
        )

    def _score_to_signal(self, score: float) -> int:
        """分数转信号"""
        if score > self.entry_threshold:
            return 1
        if score < -self.entry_threshold:
            return -1
        return 0

    def _calc_position_size(self, price: float, atr: float) -> float:
        """ATR 仓位计算"""
        risk_amount = self.cfg.initial_balance * self.cfg.risk_per_trade
        stop_distance = self.cfg.atr_sl_multiplier * atr
        if stop_distance <= 0:
            return 0.0
        return risk_amount / stop_distance

    def _build_default_strategies(self) -> List:
        """构建默认策略池"""
        import pathlib
        strategies = [AlphaStrategy()]

        default_model = pathlib.Path("models/lgbm_btc_1h.txt")
        if default_model.exists():
            try:
                from trading_system.regime_strategy import RegimeAwareLGBMStrategy
                strategies.append(RegimeAwareLGBMStrategy(str(default_model)))
                logger.info("Loaded RegimeAwareLGBMStrategy from %s", default_model)
            except Exception as exc:
                logger.warning("Could not load LGBMStrategy: %s", exc)

        return strategies

    def run(self, interval_seconds: int = 60) -> None:
        """主循环"""
        executor_type = "Rust" if isinstance(self.executor, RustTradingExecutor) else "Python"
        logger.info(
            "RustPortfolioTrader started | executor=%s | strategies=%d | symbol=%s",
            executor_type, len(self.strategies), self.cfg.symbol
        )

        while True:
            try:
                self.step()
            except Exception as e:
                logger.error(f"Error in trading step: {e}")

            time.sleep(interval_seconds)

    def get_performance_report(self) -> dict:
        """获取性能报告"""
        report = {
            'executor_type': 'Rust' if isinstance(self.executor, RustTradingExecutor) else 'Python',
            'total_orders': self._rust_stats['orders_submitted'],
            'avg_latency_us': self._rust_stats['avg_latency_us'],
            'monitor_summary': self.monitor.summary() if self.monitor else None,
            'allocator_state': str(self.allocator) if self.allocator else None,
        }
        return report


def demo():
    """演示 Rust 引擎集成"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 检查 Rust 引擎是否可用
    if not RUST_EXECUTOR_AVAILABLE:
        print("\n" + "="*60)
        print("WARNING: Rust execution engine not available!")
        print("Please build the DLL first:")
        print("  cd rust_execution && cargo build --release")
        print("="*60 + "\n")

    # 创建配置
    config = RustPortfolioConfig(
        symbol='BTCUSDT',
        interval='1h',
        initial_balance=10000.0,
        use_rust_executor=True,
        rust_worker_threads=4,
    )

    # 创建 trader
    trader = RustPortfolioTrader(config)

    print(f"\nExecutor type: {'Rust' if isinstance(trader.executor, RustTradingExecutor) else 'Python'}")

    # 运行几个交易周期进行测试
    print("\nRunning 3 test cycles...")
    for i in range(3):
        print(f"\n--- Cycle {i+1} ---")
        try:
            trader.step()
        except Exception as e:
            print(f"Error: {e}")

    # 打印性能报告
    report = trader.get_performance_report()
    print(f"\n--- Performance Report ---")
    for key, value in report.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    demo()
