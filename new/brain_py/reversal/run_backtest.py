"""
反转策略回测运行脚本

功能:
- 加载历史数据（CSV或PostgreSQL）
- 初始化特征工程、模型、回测器
- 运行回测
- 输出结果和图表
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from pathlib import Path
import argparse
import json
import logging
import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reversal.backtester import ReversalBacktester, BacktestConfig
from reversal.metrics import calculate_all_metrics, generate_report

# 从local_trading导入数据源
from local_trading.data_source import CSVDataSource, PostgreSQLDataSource, SyntheticDataSource

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('RunBacktest')


class MockFeatureEngineer:
    """模拟特征工程器（用于测试）"""

    def __init__(self, n_features: int = 10):
        self.n_features = n_features

    def transform_row(self, row: pd.Series) -> np.ndarray:
        """将一行数据转换为特征向量"""
        features = np.array([
            row.get('open', 0),
            row.get('high', 0),
            row.get('low', 0),
            row.get('close', 0),
            row.get('volume', 0),
            row.get('close', 0) - row.get('open', 0),  # 价格变化
            row.get('high', 0) - row.get('low', 0),     # 价格范围
            np.log(row.get('volume', 1) + 1),           # 对数成交量
        ])

        # 填充到指定维度
        if len(features) < self.n_features:
            features = np.pad(features, (0, self.n_features - len(features)))
        else:
            features = features[:self.n_features]

        return features


class MockModel:
    """模拟模型（用于测试）

    生成基于均值回归的反转信号:
    - 价格过高 -> 卖出信号
    - 价格过低 -> 买入信号
    """

    def __init__(self, lookback: int = 20, threshold: float = 0.02):
        self.lookback = lookback
        self.threshold = threshold
        self.price_history = []

    def predict(self, features: np.ndarray) -> float:
        """
        生成反转信号

        Returns:
            预测值 (-1 to 1)
        """
        current_price = features[3] if len(features) > 3 else 0
        self.price_history.append(current_price)

        if len(self.price_history) < self.lookback:
            return 0.0

        # 保持窗口大小
        if len(self.price_history) > self.lookback * 2:
            self.price_history = self.price_history[-self.lookback:]

        # 计算均值
        mean_price = np.mean(self.price_history[-self.lookback:])

        # 计算偏离度
        deviation = (current_price - mean_price) / mean_price if mean_price > 0 else 0

        # 生成反转信号
        if deviation > self.threshold:
            # 价格过高，预期下跌
            return -min(abs(deviation) * 10, 1.0)
        elif deviation < -self.threshold:
            # 价格过低，预期上涨
            return min(abs(deviation) * 10, 1.0)

        return 0.0


class SimpleReversalModel:
    """
    简单反转模型

    基于RSI和布林带生成反转信号
    实现 predict_signal_strength 接口与 ml-model-dev 的 reversal_model.py 兼容
    """

    def __init__(self, rsi_period: int = 14, bb_period: int = 20):
        self.rsi_period = rsi_period
        self.bb_period = bb_period
        self.prices = []

    def calculate_rsi(self) -> float:
        """计算RSI"""
        if len(self.prices) < self.rsi_period + 1:
            return 50.0

        deltas = np.diff(self.prices[-self.rsi_period-1:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)

        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def calculate_bollinger(self) -> tuple:
        """计算布林带位置"""
        if len(self.prices) < self.bb_period:
            return 0.5, 0.0

        prices = np.array(self.prices[-self.bb_period:])
        sma = np.mean(prices)
        std = np.std(prices)

        if std == 0:
            return 0.5, 0.0

        current_price = self.prices[-1]
        z_score = (current_price - sma) / std

        # 转换为0-1的位置（0=下轨，0.5=中轨，1=上轨）
        position = 0.5 + z_score * 0.25
        position = np.clip(position, 0, 1)

        return position, z_score

    def predict_signal_strength(self, features) -> float:
        """
        生成反转信号强度

        接口规范: model.predict_signal_strength(features) -> float
        信号范围: [-1, 1]，正值买入，负值卖出

        Args:
            features: 特征数据 (numpy array, pandas Series, or list)

        Returns:
            信号强度 (-1 to 1)
        """
        # 统一处理不同类型的特征输入
        if hasattr(features, 'values'):
            features = features.values
        elif isinstance(features, list):
            features = np.array(features)

        current_price = features[3] if len(features) > 3 else 0
        self.prices.append(current_price)

        if len(self.prices) < max(self.rsi_period, self.bb_period):
            return 0.0

        rsi = self.calculate_rsi()
        bb_position, z_score = self.calculate_bollinger()

        signal = 0.0

        # RSI信号
        if rsi > 70:
            signal -= 0.5  # 超买，卖出
        elif rsi < 30:
            signal += 0.5  # 超卖，买入

        # 布林带信号
        if bb_position > 0.8:
            signal -= 0.5  # 接近上轨，卖出
        elif bb_position < 0.2:
            signal += 0.5  # 接近下轨，买入

        # Z-Score信号（均值回归）
        signal -= z_score * 0.3

        return float(np.clip(signal, -1.0, 1.0))

    def predict(self, features) -> float:
        """兼容旧接口"""
        return self.predict_signal_strength(features)


def load_data_from_csv(filepath: str,
                       symbol: str = 'BTCUSDT',
                       start_date: Optional[str] = None,
                       end_date: Optional[str] = None) -> pd.DataFrame:
    """
    从CSV加载数据

    Args:
        filepath: CSV文件路径
        symbol: 交易对
        start_date: 开始日期
        end_date: 结束日期

    Returns:
        DataFrame
    """
    logger.info(f"从CSV加载数据: {filepath}")

    data_source = CSVDataSource(filepath, symbol)
    data_source.load(
        start_date=pd.to_datetime(start_date) if start_date else None,
        end_date=pd.to_datetime(end_date) if end_date else None
    )

    # 转换格式
    df = data_source.data.copy()

    # 确保列名小写
    df.columns = [c.lower() for c in df.columns]

    logger.info(f"加载了 {len(df)} 条记录")
    return df


def load_data_from_postgresql(host: str = 'localhost',
                              port: int = 5432,
                              database: str = 'binance',
                              user: str = 'postgres',
                              password: str = '',
                              table: str = 'klines_1m',
                              symbol: str = 'BTCUSDT',
                              start_date: Optional[str] = None,
                              end_date: Optional[str] = None) -> pd.DataFrame:
    """
    从PostgreSQL加载数据

    Args:
        host: 主机
        port: 端口
        database: 数据库名
        user: 用户名
        password: 密码
        table: 表名
        symbol: 交易对
        start_date: 开始日期
        end_date: 结束日期

    Returns:
        DataFrame
    """
    logger.info(f"从PostgreSQL加载数据: {host}:{port}/{database}.{table}")

    data_source = PostgreSQLDataSource(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        table_name=table,
        symbol=symbol
    )

    data_source.load(
        start_date=pd.to_datetime(start_date) if start_date else None,
        end_date=pd.to_datetime(end_date) if end_date else None
    )

    df = data_source.data.copy()
    df.columns = [c.lower() for c in df.columns]

    logger.info(f"加载了 {len(df)} 条记录")
    return df


def generate_synthetic_data(n_samples: int = 10000,
                           symbol: str = 'BTCUSDT',
                           base_price: float = 50000.0,
                           volatility: float = 0.001,
                           trend: float = 0.0) -> pd.DataFrame:
    """
    生成合成数据

    Args:
        n_samples: 样本数
        symbol: 交易对
        base_price: 基础价格
        volatility: 波动率
        trend: 趋势因子

    Returns:
        DataFrame
    """
    logger.info(f"生成合成数据: {n_samples} 条")

    data_source = SyntheticDataSource(
        symbol=symbol,
        n_ticks=n_samples,
        base_price=base_price,
        volatility=volatility
    )
    data_source.load()

    df = data_source.data.copy()
    df.columns = [c.lower() for c in df.columns]

    # 添加趋势
    if trend != 0:
        trend_prices = base_price * np.exp(np.linspace(0, trend, n_samples))
        df['close'] = df['close'] * (trend_prices / base_price)
        df['open'] = df['open'] * (trend_prices / base_price)
        df['high'] = df['high'] * (trend_prices / base_price)
        df['low'] = df['low'] * (trend_prices / base_price)

    logger.info(f"生成了 {len(df)} 条记录")
    return df


def plot_results(result: Any, save_path: Optional[str] = None):
    """
    绘制回测结果图表

    Args:
        result: 回测结果
        save_path: 保存路径
    """
    fig, axes = plt.subplots(3, 1, figsize=(14, 12))

    # 1. 权益曲线
    ax1 = axes[0]
    equity_curve = result.equity_curve

    if not equity_curve.empty and 'equity' in equity_curve.columns:
        ax1.plot(equity_curve.index, equity_curve['equity'], label='Equity', color='blue')

        if 'peak' in equity_curve.columns:
            ax1.plot(equity_curve.index, equity_curve['peak'], label='Peak',
                    color='green', linestyle='--', alpha=0.7)

        ax1.axhline(y=result.config.initial_capital, color='red',
                   linestyle='--', alpha=0.5, label='Initial Capital')

        ax1.set_title('Equity Curve', fontsize=14)
        ax1.set_xlabel('Time')
        ax1.set_ylabel('Equity ($)')
        ax1.legend()
        ax1.grid(True, alpha=0.3)

    # 2. 回撤
    ax2 = axes[1]
    if not equity_curve.empty and 'drawdown_pct' in equity_curve.columns:
        ax2.fill_between(equity_curve.index, equity_curve['drawdown_pct'] * 100,
                        0, color='red', alpha=0.3)
        ax2.set_title('Drawdown (%)', fontsize=14)
        ax2.set_xlabel('Time')
        ax2.set_ylabel('Drawdown (%)')
        ax2.grid(True, alpha=0.3)

    # 3. 信号分布
    ax3 = axes[2]
    if not result.signals_df.empty and 'signal' in result.signals_df.columns:
        signals = result.signals_df

        # 计算信号分布
        buy_signals = signals[signals['signal'] == 1]
        sell_signals = signals[signals['signal'] == -1]
        hold_signals = signals[signals['signal'] == 0]

        signal_counts = [len(buy_signals), len(sell_signals), len(hold_signals)]
        signal_labels = ['Buy', 'Sell', 'Hold']
        colors = ['green', 'red', 'gray']

        ax3.bar(signal_labels, signal_counts, color=colors, alpha=0.7)
        ax3.set_title('Signal Distribution', fontsize=14)
        ax3.set_ylabel('Count')

        # 添加数值标签
        for i, v in enumerate(signal_counts):
            ax3.text(i, v + len(signals) * 0.01, str(v), ha='center', fontsize=12)

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        logger.info(f"图表已保存: {save_path}")
    else:
        plt.show()

    plt.close()


def run_backtest(data: pd.DataFrame,
                config: BacktestConfig,
                model_type: str = 'simple',
                progress_interval: int = 1000) -> Any:
    """
    运行回测

    Args:
        data: 市场数据
        config: 回测配置
        model_type: 模型类型 ('mock', 'simple')
        progress_interval: 进度报告间隔

    Returns:
        BacktestResult
    """
    logger.info("初始化回测...")

    # 创建特征工程器
    feature_engineer = MockFeatureEngineer(n_features=10)

    # 创建模型
    if model_type == 'simple':
        model = SimpleReversalModel(rsi_period=14, bb_period=20)
    else:
        model = MockModel(lookback=20, threshold=0.02)

    # 创建回测器
    backtester = ReversalBacktester(config)

    # 运行回测
    logger.info(f"开始回测: {len(data)} 条数据")
    result = backtester.run_backtest(
        data=data,
        model=model,
        feature_engineer=feature_engineer,
        progress_interval=progress_interval
    )

    return result


def save_results(result: Any,
                 output_dir: str = 'brain_py/reversal/reports',
                 timestamp: Optional[str] = None) -> Dict[str, Any]:
    """
    保存回测结果

    输出位置: brain_py/reversal/reports/YYYYMMDD_HHMMSS/

    Args:
        result: 回测结果
        output_dir: 基础输出目录
        timestamp: 时间戳（可选，默认使用当前时间）

    Returns:
        包含文件路径和汇总结果的字典
    """
    # 生成时间戳
    if timestamp is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # 创建报告目录: brain_py/reversal/reports/YYYYMMDD_HHMMSS/
    report_dir = Path(output_dir) / timestamp
    report_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"保存回测结果到: {report_dir}")

    # 保存权益曲线
    if not result.equity_curve.empty:
        equity_path = report_dir / 'equity_curve.csv'
        result.equity_curve.to_csv(equity_path)
        logger.info(f"权益曲线已保存: {equity_path}")

    # 保存交易记录
    if not result.trades_df.empty:
        trades_path = report_dir / 'trades.csv'
        result.trades_df.to_csv(trades_path)
        logger.info(f"交易记录已保存: {trades_path}")

    # 保存信号记录
    if not result.signals_df.empty:
        signals_path = report_dir / 'signals.csv'
        result.signals_df.to_csv(signals_path)
        logger.info(f"信号记录已保存: {signals_path}")

    # 构建与接口规范对齐的输出结果
    output_result = {
        'total_return_pct': float(result.total_return_pct),
        'sharpe_ratio': float(result.sharpe_ratio),
        'max_drawdown_pct': float(result.max_drawdown_pct),
        'win_rate': float(result.win_rate),
        'total_trades': int(result.total_trades),
        'profit_factor': float(result.profit_factor),
        'equity_curve': result.equity_curve['equity'] if 'equity' in result.equity_curve.columns else pd.Series(),
        'trades': result.trades_df
    }

    # 保存配置和汇总结果
    summary = {
        'timestamp': timestamp,
        'config': {
            'symbol': result.config.symbol,
            'initial_capital': result.config.initial_capital,
            'max_position_size': result.config.max_position_size,
            'slippage_bps': result.config.slippage_bps,
            'fee_bps': result.config.fee_bps,
            'signal_threshold': result.config.signal_threshold,
            'position_sizing': result.config.position_sizing
        },
        'results': {
            'total_return_pct': output_result['total_return_pct'],
            'sharpe_ratio': output_result['sharpe_ratio'],
            'max_drawdown_pct': output_result['max_drawdown_pct'],
            'win_rate': output_result['win_rate'],
            'total_trades': output_result['total_trades'],
            'profit_factor': output_result['profit_factor']
        }
    }

    summary_path = report_dir / 'summary.json'
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)
    logger.info(f"汇总结果已保存: {summary_path}")

    return {
        'report_dir': str(report_dir),
        'summary_path': str(summary_path),
        'results': output_result
    }


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='反转策略回测')
    parser.add_argument('--data-source', type=str, default='synthetic',
                       choices=['synthetic', 'csv', 'postgresql'],
                       help='数据源类型')
    parser.add_argument('--csv-path', type=str, help='CSV文件路径')
    parser.add_argument('--symbol', type=str, default='BTCUSDT', help='交易对')
    parser.add_argument('--start-date', type=str, help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='结束日期 (YYYY-MM-DD)')
    parser.add_argument('--initial-capital', type=float, default=1000000.0,
                       help='初始资金')
    parser.add_argument('--max-position', type=float, default=0.2,
                       help='最大仓位比例')
    parser.add_argument('--signal-threshold', type=float, default=0.3,
                       help='信号阈值')
    parser.add_argument('--slippage', type=float, default=0.5,
                       help='滑点 (bps)')
    parser.add_argument('--fee', type=float, default=2.0,
                       help='手续费 (bps)')
    parser.add_argument('--model-type', type=str, default='simple',
                       choices=['mock', 'simple'],
                       help='模型类型')
    parser.add_argument('--output-dir', type=str, default='backtest_results',
                       help='输出目录')
    parser.add_argument('--plot', action='store_true',
                       help='是否生成图表')

    args = parser.parse_args()

    print("=" * 80)
    print("反转策略回测")
    print("=" * 80)

    # 加载数据
    if args.data_source == 'synthetic':
        data = generate_synthetic_data(
            n_samples=10000,
            symbol=args.symbol,
            base_price=50000.0
        )
    elif args.data_source == 'csv':
        if not args.csv_path:
            logger.error("CSV数据源需要指定--csv-path")
            return
        data = load_data_from_csv(
            filepath=args.csv_path,
            symbol=args.symbol,
            start_date=args.start_date,
            end_date=args.end_date
        )
    elif args.data_source == 'postgresql':
        # 从环境变量获取密码
        password = os.environ.get('DB_PASSWORD', '362232')
        data = load_data_from_postgresql(
            password=password,
            symbol=args.symbol,
            start_date=args.start_date,
            end_date=args.end_date
        )
    else:
        logger.error(f"不支持的数据源: {args.data_source}")
        return

    if data.empty:
        logger.error("数据为空")
        return

    print(f"\n数据概览:")
    print(f"  时间范围: {data.index[0]} 至 {data.index[-1]}")
    print(f"  数据条数: {len(data)}")
    print(f"  价格范围: ${data['low'].min():.2f} - ${data['high'].max():.2f}")

    # 配置回测 - 使用接口规范格式
    config = BacktestConfig(
        initial_capital=args.initial_capital,
        max_position_size=args.max_position,  # 对应 max_position
        slippage_bps=args.slippage,           # 滑点
        fee_bps=args.fee,                     # 手续费
        signal_threshold=args.signal_threshold,  # 信号阈值
        symbol=args.symbol,
        position_sizing='signal_based'        # 对应 position_size
    )

    # 运行回测
    print("\n运行回测...")
    result = run_backtest(
        data=data,
        config=config,
        model_type=args.model_type,
        progress_interval=max(len(data) // 10, 100)
    )

    # 计算详细指标
    metrics = calculate_all_metrics(
        equity_curve=result.equity_curve,
        trades_df=result.trades_df,
        initial_capital=config.initial_capital
    )

    # 生成报告
    config_dict = {
        'symbol': config.symbol,
        'initial_capital': config.initial_capital,
        'max_position_size': config.max_position_size,
        'slippage_bps': config.slippage_bps,
        'fee_bps': config.fee_bps,
        'signal_threshold': config.signal_threshold
    }

    report = generate_report(metrics, config_dict)
    print(report)

    # 保存结果 - 使用接口规范的输出位置
    output = save_results(result)
    print(f"\n报告已保存到: {output['report_dir']}")

    # 生成图表
    if args.plot:
        plot_path = Path(output['report_dir']) / 'backtest_chart.png'
        plot_results(result, str(plot_path))

    print("\n" + "=" * 80)
    print("回测完成!")
    print("=" * 80)


def quick_test():
    """快速测试"""
    print("=" * 80)
    print("反转策略回测 - 快速测试")
    print("=" * 80)

    # 生成合成数据
    data = generate_synthetic_data(
        n_samples=5000,
        symbol='BTCUSDT',
        base_price=50000.0,
        volatility=0.001
    )

    print(f"\n数据概览:")
    print(f"  数据条数: {len(data)}")
    print(f"  价格范围: ${data['low'].min():.2f} - ${data['high'].max():.2f}")

    # 配置回测 - 使用接口规范格式
    config = BacktestConfig(
        initial_capital=1000000.0,
        max_position_size=0.2,  # 对应 max_position
        slippage_bps=0.5,       # 滑点
        fee_bps=2.0,            # 手续费
        signal_threshold=0.3,   # 信号阈值
        symbol='BTCUSDT',
        position_sizing='signal_based'  # 对应 position_size
    )

    # 运行回测
    print("\n运行回测...")
    result = run_backtest(
        data=data,
        config=config,
        model_type='simple',
        progress_interval=500
    )

    # 计算详细指标
    metrics = calculate_all_metrics(
        equity_curve=result.equity_curve,
        trades_df=result.trades_df,
        initial_capital=config.initial_capital
    )

    # 生成报告
    config_dict = {
        'symbol': config.symbol,
        'initial_capital': config.initial_capital,
        'max_position_size': config.max_position_size,
        'slippage_bps': config.slippage_bps,
        'fee_bps': config.fee_bps,
        'signal_threshold': config.signal_threshold
    }

    report = generate_report(metrics, config_dict)
    print(report)

    # 保存结果 - 使用接口规范的输出位置
    output = save_results(result)
    print(f"\n报告已保存到: {output['report_dir']}")

    print("\n" + "=" * 80)
    print("测试完成!")
    print("=" * 80)

    return result, metrics, output


if __name__ == '__main__':
    # 如果没有参数，运行快速测试
    if len(sys.argv) == 1:
        quick_test()
    else:
        main()
