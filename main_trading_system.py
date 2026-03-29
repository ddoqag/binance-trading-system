#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
币安量化交易系统 - 主程序入口
整合交易模块、策略模块、风险控制模块
"""

import pandas as pd
import numpy as np
import logging
from pathlib import Path
from datetime import datetime

# 导入模块
from utils.helpers import setup_logger
from utils.database import DatabaseClient
from strategy.base import BaseStrategy
from strategy.dual_ma import DualMAStrategy
from strategy.rsi_strategy import RSIStrategy
from trading.execution import TradingExecutor
from trading.order import Order, OrderType, OrderSide
from risk.manager import RiskManager, RiskConfig
from models.features import FeatureEngineer
from models.predictor import PricePredictor
from models.model_trainer import ModelTrainer

# 导入配置管理
from config.settings import get_settings


class TradingSystem:
    """交易系统主类"""

    def __init__(self, config: dict = None, binance_client=None):
        """
        初始化交易系统

        Args:
            config: 配置字典，None 则使用配置文件
            binance_client: Binance API 客户端（实盘交易必需）
        """
        # 设置日志
        self.logger = setup_logger('TradingSystem', logging.INFO)

        # 加载配置
        self.settings = get_settings()

        # 合并配置
        config = config or {}

        # 数据库客户端
        self.db = DatabaseClient(self.settings.db.to_dict())

        # 策略
        self.strategy: BaseStrategy = None

        # 交易执行器（实盘交易必需 binance_client）
        self.trading_executor = TradingExecutor(
            commission_rate=config.get('commission', self.settings.trading.commission_rate),
            binance_client=binance_client
        )

        # 风险配置
        risk_config = RiskConfig(
            total_capital=config.get('initial_capital', self.settings.trading.initial_capital),
            max_position_size=config.get('max_position_size', self.settings.trading.max_position_size),
            max_single_position=config.get('max_single_position', self.settings.trading.max_single_position)
        )
        self.risk_manager = RiskManager(risk_config)

        # 状态
        self.is_running = False
        self.current_symbol = config.get('symbol', self.settings.trading.symbol)
        self.current_interval = config.get('interval', self.settings.trading.interval)

        self.logger.info("Trading system initialized")

    def set_strategy(self, strategy: BaseStrategy):
        """设置策略"""
        self.strategy = strategy
        self.logger.info(f"Strategy set: {strategy.name}")

    def load_data(self, symbol: str = None, interval: str = None) -> pd.DataFrame:
        """加载数据"""
        symbol = symbol or self.current_symbol
        interval = interval or self.current_interval
        df = self.db.load_klines(symbol, interval)
        self.logger.info(f"Loaded {len(df)} rows for {symbol} {interval}")
        return df

    def run_backtest(self, df: pd.DataFrame,
                    symbol: str = None,
                    plot: bool = True) -> dict:
        """
        运行回测

        Args:
            df: K线数据
            symbol: 交易对
            plot: 是否绘制图表

        Returns:
            回测结果字典
        """
        if self.strategy is None:
            raise ValueError("Strategy not set")

        symbol = symbol or self.current_symbol
        self.logger.info(f"Running backtest for {symbol} with {self.strategy.name}")

        # 生成信号
        df_signals = self.strategy.generate_signals(df)

        # 模拟交易
        portfolio_value = self.risk_manager.config.total_capital
        cash = portfolio_value
        position = 0
        entry_price = 0
        trades = []
        portfolio_history = []

        for i in range(len(df_signals)):
            date = df_signals.index[i]
            price = df_signals['close'].iloc[i]
            signal = df_signals['signal'].iloc[i]

            # 记录组合价值
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
                # 买入
                shares = cash * (1 - self.trading_executor.commission_rate) / price
                cost = shares * price
                commission = cost * self.trading_executor.commission_rate
                cash -= (cost + commission)
                position = shares
                entry_price = price
                trades.append({
                    'date': date,
                    'action': 'BUY',
                    'price': price,
                    'shares': shares
                })
                self.logger.debug(f"BUY @ {date}: {shares:.4f} @ {price:.2f}")

            elif signal == -1 and position > 0:
                # 卖出
                revenue = position * price
                commission = revenue * self.trading_executor.commission_rate
                cash += (revenue - commission)
                trades.append({
                    'date': date,
                    'action': 'SELL',
                    'price': price,
                    'shares': position,
                    'pnl': (price - entry_price) * position
                })
                self.logger.debug(f"SELL @ {date}: {position:.4f} @ {price:.2f}")
                position = 0

        # 计算最终结果
        final_value = cash + position * df_signals['close'].iloc[-1]
        total_return = (final_value - portfolio_value) / portfolio_value

        # 计算指标
        portfolio_df = pd.DataFrame(portfolio_history).set_index('date')
        returns = portfolio_df['total_value'].pct_change().dropna()

        if len(returns) > 0:
            annual_return = (1 + total_return) ** (365 * 24 / len(df_signals)) - 1
            sharpe = np.sqrt(365 * 24) * returns.mean() / returns.std() if returns.std() > 0 else 0
            cumulative = (1 + returns).cumprod()
            running_max = cumulative.expanding().max()
            drawdown = (cumulative - running_max) / running_max
            max_dd = drawdown.min()
        else:
            annual_return = 0
            sharpe = 0
            max_dd = 0

        results = {
            'symbol': symbol,
            'strategy': self.strategy.name,
            'initial_capital': portfolio_value,
            'final_value': final_value,
            'total_return': total_return,
            'annual_return': annual_return,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd,
            'total_trades': len(trades) // 2,
            'trades': trades,
            'portfolio_history': portfolio_df
        }

        self.logger.info(f"Backtest complete:")
        self.logger.info(f"  Total return: {total_return*100:.2f}%")
        self.logger.info(f"  Sharpe ratio: {sharpe:.2f}")
        self.logger.info(f"  Max drawdown: {max_dd*100:.2f}%")
        self.logger.info(f"  Total trades: {results['total_trades']}")

        if plot:
            self._plot_backtest_results(portfolio_df, results)

        return results

    def _plot_backtest_results(self, portfolio_df: pd.DataFrame, results: dict):
        """绘制回测结果"""
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(3, 1, figsize=(14, 12))

        # 价格和信号
        ax1 = axes[0]
        ax1.plot(portfolio_df.index, portfolio_df['price'], label='Price', alpha=0.7)
        ax1.set_title(f'{results["symbol"]} - Price', fontsize=12, fontweight='bold')
        ax1.set_ylabel('Price')
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # 组合价值
        ax2 = axes[1]
        ax2.plot(portfolio_df.index, portfolio_df['total_value'],
                label='Portfolio Value', color='green', linewidth=2)
        ax2.axhline(y=results['initial_capital'],
                   color='red', linestyle='--', label='Initial Capital')
        ax2.set_title(f'Portfolio - Return: {results["total_return"]*100:.2f}%',
                     fontsize=12, fontweight='bold')
        ax2.set_ylabel('Value')
        ax2.legend()
        ax2.grid(True, alpha=0.3)

        # 回撤
        ax3 = axes[2]
        returns = portfolio_df['total_value'].pct_change().dropna()
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        ax3.fill_between(drawdown.index, drawdown, 0,
                        color='red', alpha=0.5, label='Drawdown')
        ax3.axhline(y=results['max_drawdown'],
                   color='darkred', linestyle='--',
                   label=f'Max DD: {results["max_drawdown"]*100:.2f}%')
        ax3.set_title('Drawdown', fontsize=12, fontweight='bold')
        ax3.set_ylabel('Drawdown')
        ax3.set_xlabel('Time')
        ax3.legend()
        ax3.grid(True, alpha=0.3)

        plt.tight_layout()
        Path('plots').mkdir(exist_ok=True)
        filename = f'plots/backtest_{results["symbol"]}_{results["strategy"]}.png'
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        plt.close()
        self.logger.info(f"Backtest plot saved: {filename}")

    def train_ml_model(self, df: pd.DataFrame,
                      model_type: str = 'random_forest'):
        """训练 ML 模型"""
        self.logger.info(f"Training ML model: {model_type}")

        trainer = ModelTrainer()
        train_df, test_df = trainer.prepare_data(df)
        metrics = trainer.train_model(train_df, test_df, model_type=model_type)
        trainer.save_results()

        self.logger.info(f"Model trained: accuracy={metrics['accuracy']:.4f}, "
                        f"ROC-AUC={metrics.get('roc_auc', 0):.4f}")

        return trainer.get_predictor('BTCUSDT')

    def run(self):
        """运行交易系统（回测模式）"""
        self.logger.info("="*60)
        self.logger.info("BINANCE QUANT TRADING SYSTEM")
        self.logger.info("="*60)

        # 加载数据
        df = self.load_data()

        if len(df) == 0:
            self.logger.error("No data loaded")
            return

        # 设置策略
        self.set_strategy(DualMAStrategy(short_window=10, long_window=30))

        # 运行回测
        results = self.run_backtest(df)

        # 可选：训练 ML 模型
        # self.train_ml_model(df)

        self.logger.info("="*60)
        self.logger.info("System run complete")
        self.logger.info("="*60)


def main():
    """主函数"""
    # 配置通过 .env 文件加载，这里可以覆盖特定配置
    config = {
        # 注释掉的配置将使用 .env 文件中的默认值
        # 'symbol': 'BTCUSDT',
        # 'interval': '1h',
        # 'initial_capital': 10000,
        # 'commission': 0.001,
        # 'max_position_size': 0.3,
        # 'max_single_position': 0.2
    }

    system = TradingSystem(config)
    system.run()


if __name__ == '__main__':
    main()
