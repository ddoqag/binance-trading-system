#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
币安量化交易 - 数据清洗模块
为机器学习准备"干净燃料"
"""

import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler, MinMaxScaler
import matplotlib.pyplot as plt
import seaborn as sns
from sqlalchemy import create_engine
import json
from pathlib import Path

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False

# PostgreSQL 连接配置
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'binance',
    'user': 'postgres',
    'password': '362232'
}


def create_db_engine():
    """创建数据库连接引擎"""
    conn_str = f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
    return create_engine(conn_str)


def load_data_from_db(symbol, interval):
    """从数据库加载 K 线和技术指标数据"""
    engine = create_db_engine()

    # 加载 K 线数据
    query_klines = f"""
        SELECT open_time, open, high, low, close, volume, quote_volume, trades
        FROM klines
        WHERE symbol = '{symbol}' AND interval = '{interval}'
        ORDER BY open_time ASC
    """
    df_klines = pd.read_sql(query_klines, engine)

    # 加载技术指标
    query_indicators = f"""
        SELECT open_time, ma7, ma25, ma99, rsi14,
               macd, macd_signal, macd_histogram,
               bb_upper, bb_middle, bb_lower, obv
        FROM technical_indicators
        WHERE symbol = '{symbol}' AND interval = '{interval}'
        ORDER BY open_time ASC
    """
    df_indicators = pd.read_sql(query_indicators, engine)

    # 合并数据
    if not df_klines.empty and not df_indicators.empty:
        df = pd.merge(df_klines, df_indicators, on='open_time', how='inner')
    else:
        df = df_klines if not df_klines.empty else df_indicators

    df['open_time'] = pd.to_datetime(df['open_time'])
    df.set_index('open_time', inplace=True)

    print(f"✓ 加载 {symbol} {interval} 数据: {len(df)} 行")
    return df


def analyze_missing_values(df):
    """分析缺失值"""
    missing = df.isnull().sum()
    missing_pct = (missing / len(df)) * 100

    missing_report = pd.DataFrame({
        '缺失数量': missing,
        '缺失比例 (%)': missing_pct
    }).sort_values('缺失比例 (%)', ascending=False)

    print("\n📊 缺失值分析:")
    print(missing_report[missing_report['缺失数量'] > 0])

    return missing_report


def handle_missing_values(df, strategy='ffill'):
    """
    处理缺失值

    参数:
        strategy: 'ffill' (前向填充), 'bfill' (后向填充), 'mean' (均值), 'median' (中位数), 'interpolate' (插值)
    """
    df_clean = df.copy()

    print(f"\n🔧 处理缺失值 (策略: {strategy})...")

    # ============================================
    # 决策点：缺失值处理策略
    # ============================================
    # 这是一个关键决策：
    # 1. 价格数据 (OHLC) 用前向填充 (ffill) - 市场延续
    # 2. 成交量 (volume) 用 0 填充 - 无交易则为 0
    # 3. 技术指标用插值 (interpolate) - 连续数值
    # 4. 还是全部用 ffill？

    # 价格列 (OHLC)
    price_cols = ['open', 'high', 'low', 'close']
    for col in price_cols:
        if col in df_clean.columns:
            df_clean[col] = df_clean[col].ffill().bfill()

    # 成交量列
    volume_cols = ['volume', 'quote_volume', 'obv']
    for col in volume_cols:
        if col in df_clean.columns:
            df_clean[col] = df_clean[col].fillna(0)

    # 技术指标列（插值）
    indicator_cols = ['ma7', 'ma25', 'ma99', 'rsi14',
                      'macd', 'macd_signal', 'macd_histogram',
                      'bb_upper', 'bb_middle', 'bb_lower']
    for col in indicator_cols:
        if col in df_clean.columns:
            df_clean[col] = df_clean[col].interpolate(method='time')

    remaining = df_clean.isnull().sum().sum()
    print(f"✓ 剩余缺失值: {remaining}")

    return df_clean


def detect_outliers_iqr(df, column, iqr_factor=1.5):
    """使用 IQR 方法检测异常值"""
    Q1 = df[column].quantile(0.25)
    Q3 = df[column].quantile(0.75)
    IQR = Q3 - Q1

    lower_bound = Q1 - iqr_factor * IQR
    upper_bound = Q3 + iqr_factor * IQR

    outliers = df[(df[column] < lower_bound) | (df[column] > upper_bound)]
    return outliers, lower_bound, upper_bound


def detect_outliers_zscore(df, column, z_threshold=3):
    """使用 Z-score 方法检测异常值"""
    z_scores = np.abs((df[column] - df[column].mean()) / df[column].std())
    outliers = df[z_scores > z_threshold]
    return outliers


def handle_outliers(df, method='iqr', action='winsorize'):
    """
    处理异常值

    参数:
        method: 'iqr' 或 'zscore'
        action: 'winsorize' (缩尾), 'remove' (删除), 'clip' (截断)
    """
    df_clean = df.copy()

    print(f"\n🔧 处理异常值 (方法: {method}, 操作: {action})...")

    # ============================================
    # 决策点：异常值处理策略
    # ============================================
    # 这是一个关键决策：
    # 1. 收益率的极端值可能是真实的黑天鹅事件，不应该删除
    # 2. 技术指标的异常值可能是计算错误，可以处理
    # 3. 使用 winsorize（缩尾）而不是删除，保留信息但减少影响

    numeric_cols = df_clean.select_dtypes(include=[np.number]).columns

    outlier_stats = {}

    for col in numeric_cols:
        if method == 'iqr':
            outliers, lower, upper = detect_outliers_iqr(df_clean, col)
        else:
            outliers = detect_outliers_zscore(df_clean, col)
            lower = df_clean[col].mean() - 3 * df_clean[col].std()
            upper = df_clean[col].mean() + 3 * df_clean[col].std()

        outlier_count = len(outliers)
        outlier_stats[col] = outlier_count

        if outlier_count > 0:
            if action == 'winsorize':
                # 缩尾处理：把异常值缩到分位数
                p1 = df_clean[col].quantile(0.01)
                p99 = df_clean[col].quantile(0.99)
                df_clean[col] = df_clean[col].clip(lower=p1, upper=p99)
            elif action == 'clip':
                df_clean[col] = df_clean[col].clip(lower=lower, upper=upper)
            elif action == 'remove':
                df_clean = df_clean.drop(outliers.index)

    print(f"✓ 异常值处理完成")
    return df_clean


def normalize_data(df, method='standard'):
    """
    标准化/规范化数据

    参数:
        method: 'standard' (Z-score标准化), 'minmax' (最小-最大规范化)
    """
    df_clean = df.copy()
    numeric_cols = df_clean.select_dtypes(include=[np.number]).columns

    print(f"\n🔧 数据标准化 (方法: {method})...")

    # ============================================
    # 决策点：标准化策略
    # ============================================
    # 这是一个关键决策：
    # 1. 价格用 min-max 规范化，保持相对关系
    # 2. 技术指标用 standard 标准化，适合 ML 模型
    # 3. 或者分开处理不同类型的特征？

    scalers = {}

    if method == 'standard':
        scaler = StandardScaler()
        df_clean[numeric_cols] = scaler.fit_transform(df_clean[numeric_cols])
        scalers['all'] = scaler
    else:
        scaler = MinMaxScaler()
        df_clean[numeric_cols] = scaler.fit_transform(df_clean[numeric_cols])
        scalers['all'] = scaler

    print(f"✓ 标准化完成")
    return df_clean, scalers


def create_features(df):
    """创建机器学习特征"""
    df_features = df.copy()

    print(f"\n🔧 生成 ML 特征...")

    # ============================================
    # 决策点：特征工程策略
    # ============================================
    # 这是一个关键决策：
    # 1. 收益率特征（预测目标）
    # 2. 滞后特征（过去 N 期的值）
    # 3. 收益率的统计特征（波动率、偏度、峰度）
    # 4. 时间特征（小时、星期、月份）

    # 收益率
    df_features['return_1h'] = df_features['close'].pct_change(1)
    df_features['return_4h'] = df_features['close'].pct_change(4)
    df_features['return_24h'] = df_features['close'].pct_change(24)

    # 滞后特征
    for i in range(1, 5):
        df_features[f'close_lag_{i}'] = df_features['close'].shift(i)
        df_features[f'return_lag_{i}'] = df_features['return_1h'].shift(i)

    # 波动率（滚动标准差）
    df_features['volatility_24h'] = df_features['return_1h'].rolling(24).std()
    df_features['volatility_7d'] = df_features['return_1h'].rolling(24 * 7).std()

    # 时间特征
    df_features['hour'] = df_features.index.hour
    df_features['day_of_week'] = df_features.index.dayofweek
    df_features['day_of_month'] = df_features.index.day

    print(f"✓ 特征生成完成，总特征数: {len(df_features.columns)}")
    return df_features


def visualize_data(df, df_clean, symbol, interval, output_dir='plots'):
    """可视化数据清洗前后对比"""
    Path(output_dir).mkdir(exist_ok=True)

    fig, axes = plt.subplots(3, 2, figsize=(15, 12))

    # 1. 价格走势
    axes[0, 0].plot(df.index, df['close'], label='原始', alpha=0.7)
    axes[0, 0].plot(df_clean.index, df_clean['close'], label='清洗后', alpha=0.7)
    axes[0, 0].set_title(f'{symbol} {interval} 价格走势')
    axes[0, 0].legend()
    axes[0, 0].tick_params(axis='x', rotation=45)

    # 2. 成交量
    axes[0, 1].bar(df.index, df['volume'], alpha=0.5, label='原始')
    axes[0, 1].set_title('成交量')
    axes[0, 1].tick_params(axis='x', rotation=45)

    # 3. RSI 分布
    if 'rsi14' in df.columns:
        axes[1, 0].hist(df['rsi14'].dropna(), bins=50, alpha=0.5, label='原始')
        axes[1, 0].hist(df_clean['rsi14'].dropna(), bins=50, alpha=0.5, label='清洗后')
        axes[1, 0].set_title('RSI 分布')
        axes[1, 0].legend()

    # 4. MACD
    if 'macd' in df.columns:
        axes[1, 1].plot(df.index, df['macd'], label='MACD', alpha=0.7)
        axes[1, 1].plot(df.index, df['macd_signal'], label='Signal', alpha=0.7)
        axes[1, 1].set_title('MACD')
        axes[1, 1].legend()
        axes[1, 1].tick_params(axis='x', rotation=45)

    # 5. 收益率分布
    returns = df['close'].pct_change().dropna()
    axes[2, 0].hist(returns, bins=100, alpha=0.7)
    axes[2, 0].axvline(returns.mean(), color='r', linestyle='--', label='均值')
    axes[2, 0].axvline(returns.mean() + 3 * returns.std(), color='orange', linestyle='--', label='±3σ')
    axes[2, 0].axvline(returns.mean() - 3 * returns.std(), color='orange', linestyle='--')
    axes[2, 0].set_title('收益率分布')
    axes[2, 0].legend()

    # 6. 缺失值热力图
    missing = df.isnull()
    if missing.sum().sum() > 0:
        sns.heatmap(missing, ax=axes[2, 1], cbar=False, yticklabels=False)
        axes[2, 1].set_title('缺失值热力图')

    plt.tight_layout()
    output_path = f'{output_dir}/{symbol}_{interval}_cleaning.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"\n✓ 可视化图已保存到: {output_path}")
    plt.close()


def save_clean_data(df, symbol, interval, output_dir='clean_data'):
    """保存清洗后的数据"""
    Path(output_dir).mkdir(exist_ok=True)

    # 保存为 CSV
    csv_path = f'{output_dir}/{symbol}_{interval}_clean.csv'
    df.to_csv(csv_path)
    print(f"✓ 清洗数据已保存到: {csv_path}")

    # 保存为 Parquet（更小更快）
    try:
        parquet_path = f'{output_dir}/{symbol}_{interval}_clean.parquet'
        df.to_parquet(parquet_path)
        print(f"✓ 清洗数据已保存到: {parquet_path}")
    except Exception as e:
        print(f"⚠ Parquet 保存失败: {e}")


def main():
    """主函数：完整的数据清洗流程"""
    print('═══════════════════════════════════════════════')
    print('  币安量化交易 - 数据清洗模块')
    print('═══════════════════════════════════════════════\n')

    config = {
        'symbols': ['BTCUSDT', 'ETHUSDT'],
        'intervals': ['1h', '4h'],
        'missing_strategy': 'ffill',
        'outlier_method': 'iqr',
        'outlier_action': 'winsorize',
        'normalize_method': 'standard'
    }

    print("配置:")
    print(f"  交易对: {config['symbols']}")
    print(f"  时间周期: {config['intervals']}")
    print(f"  缺失值策略: {config['missing_strategy']}")
    print(f"  异常值方法: {config['outlier_method']}")
    print(f"  异常值操作: {config['outlier_action']}")
    print(f"  标准化方法: {config['normalize_method']}")

    all_clean_data = {}

    for symbol in config['symbols']:
        for interval in config['intervals']:
            print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            print(f"处理 {symbol} {interval}")
            print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            # 1. 加载数据
            df = load_data_from_db(symbol, interval)

            if df.empty:
                print(f"⚠ 没有数据，跳过")
                continue

            # 2. 分析缺失值
            analyze_missing_values(df)

            # 3. 处理缺失值
            df_clean = handle_missing_values(df, strategy=config['missing_strategy'])

            # 4. 处理异常值
            df_clean = handle_outliers(df_clean, method=config['outlier_method'],
                                        action=config['outlier_action'])

            # 5. 创建特征
            df_features = create_features(df_clean)

            # 6. 可视化
            visualize_data(df, df_clean, symbol, interval)

            # 7. 保存清洗数据
            save_clean_data(df_features, symbol, interval)

            all_clean_data[f"{symbol}_{interval}"] = df_features

    print('\n═══════════════════════════════════════════════')
    print('  数据清洗完成！')
    print('═══════════════════════════════════════════════')

    return all_clean_data


if __name__ == '__main__':
    main()
