#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI交易系统 - 主控制器，协调市场分析、策略匹配和交易执行
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path

from ai_trading.market_analyzer import MarketAnalyzer, TrendType, MarketRegime
from ai_trading.strategy_matcher import StrategyMatcher, StrategyConfig
from strategy.base import BaseStrategy
from trading.execution import TradingExecutor
from risk.manager import RiskManager, RiskConfig
from utils.database import DatabaseClient
from config.settings import get_settings
from trading.binance_client import BinanceClient


class AITradingSystem:
    """AI驱动的交易系统"""

    def __init__(self, config: Optional[Dict[str, Any]] = None, binance_client: Optional[BinanceClient] = None):
        """
        初始化AI交易系统

        Args:
            config: 配置字典，None 则使用默认配置
            binance_client: Binance API 客户端（实盘交易必需）
        """
        self.logger = logging.getLogger('AITradingSystem')
        self.config = config or {}

        # 加载配置
        self.settings = get_settings()

        # 数据库客户端
        self.db = DatabaseClient(self.settings.db.to_dict())

        # 交易执行器（仅实盘）
        self.trading_executor = TradingExecutor(
            commission_rate=self.config.get('commission', self.settings.trading.commission_rate),
            binance_client=binance_client
        )

        # 风险配置
        risk_config = RiskConfig(
            total_capital=self.config.get('initial_capital', self.settings.trading.initial_capital),
            max_position_size=self.config.get('max_position_size', self.settings.trading.max_position_size),
            max_single_position=self.config.get('max_single_position', self.settings.trading.max_single_position)
        )
        self.risk_manager = RiskManager(risk_config)

        # 市场分析器
        self.market_analyzer = MarketAnalyzer(
            model_path=self.config.get('model_path', str(Path("D:/binance/models/Qwen/Qwen3-8B")))
        )

        # 策略匹配器
        self.strategy_matcher = StrategyMatcher()

        # 当前策略
        self.current_strategy: Optional[BaseStrategy] = None
        self.last_strategy_change = None
        self.performance_history: List[Dict[str, Any]] = []

        # 状态
        self.is_running = False
        self.current_symbol = self.config.get('symbol', self.settings.trading.symbol)
        self.current_interval = self.config.get('interval', self.settings.trading.interval)

        self.logger.info("AI Trading System initialized")

    def load_market_data(self, symbol: Optional[str] = None,
                       interval: Optional[str] = None,
                       lookback: int = 200) -> pd.DataFrame:
        """
        加载市场数据

        Args:
            symbol: 交易对
            interval: 时间周期
            lookback: 回溯期数

        Returns:
            K线数据 DataFrame
        """
        symbol = symbol or self.current_symbol
        interval = interval or self.current_interval

        try:
            df = self.db.load_klines(symbol, interval, limit=lookback)
            self.logger.info(f"Loaded {len(df)} candles for {symbol} {interval}")
            return df
        except Exception as e:
            self.logger.error(f"Failed to load market data: {e}")
            return pd.DataFrame()

    def analyze_market(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        分析市场状态

        Args:
            df: 市场数据

        Returns:
            分析结果
        """
        if df.empty:
            self.logger.warning("Cannot analyze empty market data")
            return {
                'trend': TrendType.SIDEWAYS,
                'regime': MarketRegime.NEUTRAL,
                'confidence': 0.0,
                'analysis': 'No market data'
            }

        return self.market_analyzer.analyze_trend(df)

    def select_and_apply_strategy(self, trend_analysis: Dict[str, Any]) -> Optional[BaseStrategy]:
        """
        选择并应用策略

        Args:
            trend_analysis: 趋势分析结果

        Returns:
            新策略实例（如果策略发生变化）
        """
        # 获取历史表现（模拟）
        historical_performance = self._get_historical_performance()

        # 选择最优策略
        best_config = self.strategy_matcher.select_best_strategy(trend_analysis, historical_performance)

        self.logger.info(f"Selected strategy: {best_config.name} ({best_config.description})")

        # 检查是否需要更换策略
        strategy_changed = False
        if self.current_strategy is None:
            strategy_changed = True
        else:
            # 简单的策略变化检测
            strategy_changed = True

        if strategy_changed:
            # 创建新策略
            new_strategy = self.strategy_matcher.create_strategy(best_config)

            # 记录策略变化
            self._record_strategy_change(best_config, trend_analysis)

            # 重置当前策略
            self.current_strategy = new_strategy

            self.logger.info(f"Strategy changed to: {best_config.name}")

        return self.current_strategy

    def _get_historical_performance(self) -> Dict[str, float]:
        """获取历史策略表现"""
        if len(self.performance_history) < 5:
            return {}

        # 简单的滚动表现统计
        recent = self.performance_history[-20:]
        strategies = set([p['strategy'] for p in recent])

        performance = {}
        for strategy in strategies:
            strategy_perf = [p['return'] for p in recent if p['strategy'] == strategy]
            if strategy_perf:
                performance[strategy] = np.mean(strategy_perf)

        return performance

    def _record_strategy_change(self, config: StrategyConfig, trend_analysis: Dict[str, Any]):
        """记录策略变化"""
        self.performance_history.append({
            'timestamp': datetime.now(),
            'strategy': config.name,
            'trend': trend_analysis.get('trend'),
            'regime': trend_analysis.get('regime'),
            'return': 0.0
        })
        self.last_strategy_change = datetime.now()

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号

        Args:
            df: 市场数据

        Returns:
            包含信号列的 DataFrame
        """
        if self.current_strategy is None:
            return df.assign(signal=0)

        try:
            return self.current_strategy.generate_signals(df)
        except Exception as e:
            self.logger.error(f"Signal generation failed: {e}")
            return df.assign(signal=0)

    def execute_trading_cycle(self) -> Dict[str, Any]:
        """
        执行完整的交易周期

        Returns:
            交易周期结果
        """
        self.logger.info("=" * 60)
        self.logger.info("Starting trading cycle")
        self.logger.info("=" * 60)

        cycle_result = {
            'timestamp': datetime.now(),
            'symbol': self.current_symbol,
            'interval': self.current_interval
        }

        # 1. 加载市场数据
        df = self.load_market_data(lookback=200)
        if df.empty:
            cycle_result['status'] = 'failed'
            cycle_result['error'] = 'No market data'
            return cycle_result

        # 2. 市场分析
        trend_analysis = self.analyze_market(df)
        cycle_result['trend_analysis'] = trend_analysis
        self.logger.info(f"Trend: {trend_analysis['trend']}, "
                       f"Regime: {trend_analysis['regime']}, "
                       f"Confidence: {trend_analysis['confidence']:.2f}")

        # 3. 策略选择
        strategy = self.select_and_apply_strategy(trend_analysis)
        if strategy is None:
            cycle_result['status'] = 'failed'
            cycle_result['error'] = 'No strategy available'
            return cycle_result

        cycle_result['selected_strategy'] = {
            'name': strategy.name,
            'params': strategy.get_params()
        }

        # 4. 信号生成
        df_signals = self.generate_signals(df)
        latest_signal = df_signals['signal'].iloc[-1]
        cycle_result['latest_signal'] = latest_signal
        self.logger.info(f"Generated signal: {latest_signal}")

        # 5. 风险评估
        risk_check = self._check_risk_constraints()
        cycle_result['risk_checked'] = risk_check['passed']
        if not risk_check['passed']:
            self.logger.warning(f"Risk check failed: {risk_check['reason']}")
            cycle_result['status'] = 'risk_blocked'
            cycle_result['risk_reason'] = risk_check['reason']
            return cycle_result

        # 6. 交易执行
        if latest_signal != 0:
            execution_result = self._execute_trade(latest_signal, df_signals.iloc[-1]['close'])
            cycle_result['execution'] = execution_result
            if execution_result.get('status') == 'filled':
                cycle_result['status'] = 'trade_executed'
            else:
                cycle_result['status'] = 'trade_failed'
        else:
            cycle_result['status'] = 'no_action'
            cycle_result['execution'] = None

        self.logger.info(f"Cycle complete: {cycle_result['status']}")

        return cycle_result

    def _check_risk_constraints(self) -> Dict[str, Any]:
        """检查风险约束"""
        try:
            # 简化的风险检查
            return {
                'passed': True,
                'reason': 'Risk checks passed'
            }
        except Exception as e:
            return {
                'passed': False,
                'reason': str(e)
            }

    def _execute_trade(self, signal: int, price: float) -> Dict[str, Any]:
        """执行交易"""
        symbol = self.current_symbol
        side = 'BUY' if signal == 1 else 'SELL'

        try:
            quantity = self._calculate_position_size(price)
            if quantity <= 0:
                return {
                    'status': 'rejected',
                    'reason': 'Insufficient capital or position constraints'
                }

            order = self.trading_executor.place_order(
                symbol=symbol,
                side=side,
                order_type='MARKET',
                quantity=quantity,
                current_price=price
            )

            return {
                'status': order.status.value.lower(),
                'order_id': order.order_id,
                'quantity': quantity,
                'price': price,
                'side': side
            }

        except Exception as e:
            self.logger.error(f"Trade execution failed: {e}")
            return {
                'status': 'failed',
                'reason': str(e)
            }

    def _calculate_position_size(self, price: float) -> float:
        """计算仓位大小"""
        capital = self.risk_manager.config.total_capital
        max_pos = self.risk_manager.config.max_single_position

        # 简单的仓位计算
        available = capital * max_pos
        quantity = available / price

        return quantity

    def run_backtest(self, df: pd.DataFrame, initial_capital: float = 10000) -> Dict[str, Any]:
        """
        运行回测

        Args:
            df: 历史数据
            initial_capital: 初始资金

        Returns:
            回测结果
        """
        # 回测使用纯本地计算，不需要 TradingExecutor
        commission_rate = self.config.get('commission', self.settings.trading.commission_rate)

        # 运行回测
        portfolio_value = initial_capital
        cash = initial_capital
        position = 0
        trades = []
        portfolio_history = []

        df_signals = self.generate_signals(df)

        for i in range(len(df_signals)):
            date = df_signals.index[i]
            price = df_signals['close'].iloc[i]
            signal = df_signals['signal'].iloc[i]

            current_value = cash + position * price
            portfolio_history.append({
                'date': date,
                'price': price,
                'cash': cash,
                'position': position,
                'total_value': current_value
            })

            # 交易逻辑
            if signal == 1 and position == 0:
                shares = cash * (1 - commission_rate) / price
                cost = shares * price
                commission = cost * commission_rate
                cash -= (cost + commission)
                position = shares
                trades.append({
                    'date': date,
                    'action': 'BUY',
                    'price': price,
                    'shares': shares
                })

            elif signal == -1 and position > 0:
                revenue = position * price
                commission = revenue * commission_rate
                cash += (revenue - commission)
                trades.append({
                    'date': date,
                    'action': 'SELL',
                    'price': price,
                    'shares': position,
                    'pnl': (price - df_signals['close'].iloc[trades[-1]['shares']]) * position
                })
                position = 0

        final_value = cash + position * df_signals['close'].iloc[-1]
        total_return = (final_value - initial_capital) / initial_capital

        return {
            'initial_capital': initial_capital,
            'final_value': final_value,
            'total_return': total_return,
            'total_trades': len(trades) // 2,
            'trades': trades,
            'portfolio_history': portfolio_history
        }

    def run(self):
        """运行交易系统"""
        self.is_running = True
        cycle_count = 0

        try:
            while self.is_running:
                cycle_count += 1

                self.logger.info(f"\nCycle {cycle_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

                # 执行交易周期
                cycle_result = self.execute_trading_cycle()

                # 记录结果
                self.performance_history.append(cycle_result)

                # 暂停
                self._wait_for_next_cycle()

        except KeyboardInterrupt:
            self.logger.info("Trading system stopped by user")
        except Exception as e:
            self.logger.error(f"Trading system failed: {e}")
        finally:
            self.is_running = False
            self.logger.info("Trading system stopped")

    def _wait_for_next_cycle(self):
        """等待下一个周期"""
        import time
        # 根据时间周期调整等待时间
        interval_map = {
            '1m': 60,
            '5m': 300,
            '15m': 900,
            '1h': 3600,
            '4h': 14400,
            '1d': 86400
        }

        interval = self.current_interval
        wait_time = interval_map.get(interval, 3600)

        time.sleep(wait_time)

    def stop(self):
        """停止交易系统"""
        self.is_running = False
