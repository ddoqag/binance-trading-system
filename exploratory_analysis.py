#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
币安量化交易 - 探索性分析与聚类分析
1. 探索性数据分析 (EDA)
2. 相关性热力图
3. 聚类分析找资产联动规律
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sqlalchemy import create_engine
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans, AgglomerativeClustering, DBSCAN
from sklearn.decomposition import PCA
from scipy.cluster.hierarchy import dendrogram, linkage
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

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

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT']
INTERVAL = '1h'  # 使用 1h 数据进行分析


def create_db_engine():
    """创建数据库连接引擎"""
    conn_str = f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
    return create_engine(conn_str)


def load_all_returns():
    """加载所有交易对的收益率数据"""
    engine = create_db_engine()

    all_returns = {}

    for symbol in SYMBOLS:
        query = f"""
            SELECT open_time, close
            FROM klines
            WHERE symbol = '{symbol}' AND interval = '{INTERVAL}'
            ORDER BY open_time ASC
        """
        df = pd.read_sql(query, engine)
        df['open_time'] = pd.to_datetime(df['open_time'])
        df.set_index('open_time', inplace=True)

        # 计算对数收益率
        df[f'return_{symbol}'] = np.log(df['close'] / df['close'].shift(1))
        all_returns[symbol] = df[f'return_{symbol}']

    # 合并成一个 DataFrame
    df_returns = pd.DataFrame(all_returns).dropna()
    print(f"[OK] 加载收益率数据: {len(df_returns)} 条")
    print(f"  时间范围: {df_returns.index[0]} ~ {df_returns.index[-1]}")

    return df_returns


def plot_price_trends(df_prices):
    """绘制价格走势对比图"""
    fig, ax = plt.subplots(figsize=(14, 7))

    # 标准化价格以便对比（从1开始）
    df_normalized = df_prices / df_prices.iloc[0]

    for symbol in SYMBOLS:
        ax.plot(df_normalized.index, df_normalized[symbol], label=symbol, linewidth=1.5)

    ax.set_title('5个交易对价格走势对比 (标准化)', fontsize=14, fontweight='bold')
    ax.set_xlabel('时间')
    ax.set_ylabel('标准化价格')
    ax.legend(loc='best', ncol=5)
    ax.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()

    output_path = 'plots/price_trends.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"[OK] 价格走势图已保存: {output_path}")
    plt.close()


def plot_returns_distribution(df_returns):
    """绘制收益率分布图"""
    fig, axes = plt.subplots(2, 3, figsize=(16, 10))
    axes = axes.flatten()

    for i, symbol in enumerate(SYMBOLS):
        ax = axes[i]
        returns = df_returns[symbol].dropna()

        # 直方图
        ax.hist(returns, bins=100, alpha=0.7, density=True)

        # 添加均值和±3σ线
        mean = returns.mean()
        std = returns.std()
        ax.axvline(mean, color='r', linestyle='--', linewidth=2, label=f'均值: {mean:.4f}')
        ax.axvline(mean + 3 * std, color='orange', linestyle='--', linewidth=1.5, label='±3σ')
        ax.axvline(mean - 3 * std, color='orange', linestyle='--', linewidth=1.5)

        ax.set_title(f'{symbol} 收益率分布', fontsize=12, fontweight='bold')
        ax.set_xlabel('收益率')
        ax.set_ylabel('频数')
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

        # 统计信息
        stats_text = f"均值: {mean:.6f}\n标准差: {std:.6f}\n偏度: {returns.skew():.4f}\n峰度: {returns.kurtosis():.4f}"
        ax.text(0.05, 0.95, stats_text, transform=ax.transAxes,
                verticalalignment='top', bbox=dict(boxstyle='round', alpha=0.1))

    # 隐藏最后一个空图
    axes[-1].axis('off')

    plt.tight_layout()
    output_path = 'plots/returns_distribution.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"[OK] 收益率分布图已保存: {output_path}")
    plt.close()


def plot_correlation_heatmap(df_returns):
    """绘制相关性热力图"""
    corr_matrix = df_returns.corr()

    fig, ax = plt.subplots(figsize=(10, 8))

    # 热力图
    mask = np.triu(np.ones_like(corr_matrix, dtype=bool))
    sns.heatmap(corr_matrix, mask=mask, annot=True, fmt='.3f',
                cmap='coolwarm', center=0, square=True,
                linewidths=1, cbar_kws={"shrink": 0.8}, ax=ax)

    ax.set_title('5个交易对收益率相关性热力图', fontsize=14, fontweight='bold')
    plt.tight_layout()

    output_path = 'plots/correlation_heatmap.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"[OK] 相关性热力图已保存: {output_path}")
    plt.close()

    return corr_matrix


def plot_rolling_correlation(df_returns, window=24 * 7):
    """绘制滚动相关性（7天窗口）"""
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    axes = axes.flatten()

    # BTC 与其他币的滚动相关性
    pairs = [('BTCUSDT', 'ETHUSDT'), ('BTCUSDT', 'BNBUSDT'),
             ('BTCUSDT', 'SOLUSDT'), ('BTCUSDT', 'XRPUSDT')]

    for i, (s1, s2) in enumerate(pairs):
        ax = axes[i]
        rolling_corr = df_returns[s1].rolling(window=window).corr(df_returns[s2])

        ax.plot(df_returns.index, rolling_corr, linewidth=1.5)
        ax.axhline(rolling_corr.mean(), color='r', linestyle='--',
                  label=f'均值: {rolling_corr.mean():.3f}')

        ax.set_title(f'{s1} vs {s2} 滚动相关性 ({window//24}天窗口)',
                    fontsize=11, fontweight='bold')
        ax.set_xlabel('时间')
        ax.set_ylabel('相关系数')
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.set_ylim([-0.1, 1.0])
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)

    plt.tight_layout()
    output_path = 'plots/rolling_correlation.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"[OK] 滚动相关性图已保存: {output_path}")
    plt.close()


def cluster_analysis(df_returns):
    """聚类分析找资产联动规律"""
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("聚类分析 - 找资产联动规律")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # ============================================
    # 决策点：聚类方法选择
    # ============================================
    # 这是一个关键决策：
    # 1. K-Means - 需要指定聚类数，适合球形簇
    # 2. 层次聚类 - 不需要指定聚类数，可以画树状图
    # 3. DBSCAN - 基于密度，可以发现任意形状的簇

    returns_scaled = StandardScaler().fit_transform(df_returns.T)  # 按币种标准化

    # 1. 层次聚类
    print("\n1. 层次聚类:")
    linked = linkage(returns_scaled, method='ward')

    fig, ax = plt.subplots(figsize=(10, 6))
    dendrogram(linked, labels=SYMBOLS, orientation='top',
               distance_sort='descending', show_leaf_counts=True, ax=ax)
    ax.set_title('层次聚类树状图 - 资产联动关系', fontsize=14, fontweight='bold')
    ax.set_ylabel('距离')
    plt.tight_layout()
    output_path = 'plots/hierarchical_clustering.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"[OK] 层次聚类图已保存: {output_path}")
    plt.close()

    # 2. K-Means 聚类（尝试不同的 K）
    print("\n2. K-Means 聚类:")

    # 肘部法则找最佳 K
    inertias = []
    K_range = range(1, min(5, len(SYMBOLS)))

    for k in K_range:
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
        kmeans.fit(returns_scaled)
        inertias.append(kmeans.inertia_)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(K_range, inertias, 'bo-', linewidth=2, markersize=8)
    ax.set_xlabel('聚类数 K')
    ax.set_ylabel('惯性 (Inertia)')
    ax.set_title('K-Means 肘部法则', fontsize=12, fontweight='bold')
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    output_path = 'plots/kmeans_elbow.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"[OK] 肘部法则图已保存: {output_path}")
    plt.close()

    # 用 K=2 或 K=3 进行聚类
    best_k = 2 if len(SYMBOLS) >= 2 else 1
    kmeans = KMeans(n_clusters=best_k, random_state=42, n_init=10)
    clusters = kmeans.fit_predict(returns_scaled)

    cluster_result = pd.DataFrame({
        'Symbol': SYMBOLS,
        'Cluster': clusters
    }).sort_values('Cluster')

    print("\n聚类结果:")
    print(cluster_result.to_string(index=False))

    # 3. PCA 可视化
    print("\n3. PCA 降维可视化:")
    pca = PCA(n_components=2)
    returns_pca = pca.fit_transform(returns_scaled)

    fig, ax = plt.subplots(figsize=(10, 8))
    scatter = ax.scatter(returns_pca[:, 0], returns_pca[:, 1],
                        c=clusters, cmap='viridis', s=200, alpha=0.7)

    # 标注币种名称
    for i, symbol in enumerate(SYMBOLS):
        ax.annotate(symbol, (returns_pca[i, 0], returns_pca[i, 1]),
                   fontsize=12, fontweight='bold',
                   xytext=(5, 5), textcoords='offset points')

    ax.set_xlabel(f'PC1 ({pca.explained_variance_ratio_[0]:.1%} 方差)')
    ax.set_ylabel(f'PC2 ({pca.explained_variance_ratio_[1]:.1%} 方差)')
    ax.set_title('资产聚类 PCA 可视化', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    plt.colorbar(scatter, label='Cluster')
    plt.tight_layout()
    output_path = 'plots/clustering_pca.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"[OK] PCA 聚类图已保存: {output_path}")
    plt.close()

    return cluster_result


def generate_summary_report(df_returns, corr_matrix, cluster_result):
    """生成总结报告"""
    print("\n" + "="*60)
    print("探索性分析与聚类分析 - 总结报告")
    print("="*60)

    print("\n【收益率统计】")
    stats = df_returns.agg(['mean', 'std', 'skew', 'kurtosis'])
    print(stats.round(6).to_string())

    print("\n【相关性矩阵】")
    print(corr_matrix.round(3).to_string())

    print("\n【聚类结果】")
    print(cluster_result.to_string(index=False))

    # 找出联动最强的币种对
    corr_stack = corr_matrix.abs().stack()
    corr_stack = corr_stack[corr_stack < 1.0]  # 排除自相关
    top_corr = corr_stack.sort_values(ascending=False).head(5)

    print("\n【联动最强的币种对】")
    for (s1, s2), corr in top_corr.items():
        if s1 < s2:  # 避免重复
            print(f"  {s1} <-> {s2}: {corr:.3f}")

    # 保存报告到文件
    report = {
        'timestamp': pd.Timestamp.now().isoformat(),
        'returns_stats': stats.to_dict(),
        'correlation_matrix': corr_matrix.to_dict(),
        'clustering_result': cluster_result.to_dict('records'),
        'top_correlations': top_corr.head(10).to_dict()
    }

    import json
    with open('plots/analysis_report.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n[OK] 详细报告已保存到: plots/analysis_report.json")


def main():
    """主函数"""
    print('═══════════════════════════════════════════════')
    print('  币安量化交易 - 探索性分析与聚类分析')
    print('═══════════════════════════════════════════════\n')

    # 创建输出目录
    Path('plots').mkdir(exist_ok=True)

    # 1. 加载数据
    print("1. 加载数据...")
    df_returns = load_all_returns()

    # 加载价格数据用于走势图
    engine = create_db_engine()
    df_prices = pd.DataFrame()
    for symbol in SYMBOLS:
        query = f"""
            SELECT open_time, close
            FROM klines
            WHERE symbol = '{symbol}' AND interval = '{INTERVAL}'
            ORDER BY open_time ASC
        """
        df = pd.read_sql(query, engine)
        df['open_time'] = pd.to_datetime(df['open_time'])
        df.set_index('open_time', inplace=True)
        df_prices[symbol] = df['close']

    # 2. 价格走势对比
    print("\n2. 绘制价格走势...")
    plot_price_trends(df_prices)

    # 3. 收益率分布
    print("\n3. 绘制收益率分布...")
    plot_returns_distribution(df_returns)

    # 4. 相关性热力图
    print("\n4. 绘制相关性热力图...")
    corr_matrix = plot_correlation_heatmap(df_returns)

    # 5. 滚动相关性
    print("\n5. 绘制滚动相关性...")
    plot_rolling_correlation(df_returns)

    # 6. 聚类分析
    print("\n6. 进行聚类分析...")
    cluster_result = cluster_analysis(df_returns)

    # 7. 生成总结报告
    generate_summary_report(df_returns, corr_matrix, cluster_result)

    print('\n' + '═'*60)
    print('  分析完成！请查看 plots/ 目录下的图表')
    print('═'*60)


if __name__ == '__main__':
    main()
