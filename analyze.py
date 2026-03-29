#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Binance Quant Trading - Exploratory Analysis and Clustering
1. Exploratory Data Analysis (EDA)
2. Correlation Heatmap
3. Cluster Analysis for asset co-movement
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import seaborn as sns
from sqlalchemy import create_engine
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from scipy.cluster.hierarchy import dendrogram, linkage
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# Set font for Chinese characters (fallback)
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# PostgreSQL connection config
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'binance',
    'user': 'postgres',
    'password': '362232'
}

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT']
INTERVAL = '1h'


def create_db_engine():
    conn_str = f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
    return create_engine(conn_str)


def load_all_returns():
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
        df[f'return_{symbol}'] = np.log(df['close'] / df['close'].shift(1))
        all_returns[symbol] = df[f'return_{symbol}']

    df_returns = pd.DataFrame(all_returns).dropna()
    print(f"Loaded returns data: {len(df_returns)} rows")
    print(f"Time range: {df_returns.index[0]} ~ {df_returns.index[-1]}")
    return df_returns


def plot_price_trends(df_prices):
    fig, ax = plt.subplots(figsize=(14, 7))
    df_normalized = df_prices / df_prices.iloc[0]

    for symbol in SYMBOLS:
        ax.plot(df_normalized.index, df_normalized[symbol], label=symbol, linewidth=1.5)

    ax.set_title('Price Trends Comparison (Normalized)', fontsize=14, fontweight='bold')
    ax.set_xlabel('Time')
    ax.set_ylabel('Normalized Price')
    ax.legend(loc='best', ncol=5)
    ax.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig('plots/price_trends.png', dpi=150, bbox_inches='tight')
    print("Saved price_trends.png")
    plt.close()


def plot_returns_distribution(df_returns):
    fig, axes = plt.subplots(2, 3, figsize=(16, 10))
    axes = axes.flatten()

    for i, symbol in enumerate(SYMBOLS):
        ax = axes[i]
        returns = df_returns[symbol].dropna()
        ax.hist(returns, bins=100, alpha=0.7, density=True)
        mean = returns.mean()
        std = returns.std()
        ax.axvline(mean, color='r', linestyle='--', linewidth=2, label=f'Mean: {mean:.4f}')
        ax.axvline(mean + 3 * std, color='orange', linestyle='--', linewidth=1.5, label='+/-3σ')
        ax.axvline(mean - 3 * std, color='orange', linestyle='--', linewidth=1.5)
        ax.set_title(f'{symbol} Returns Distribution', fontsize=12, fontweight='bold')
        ax.set_xlabel('Returns')
        ax.set_ylabel('Frequency')
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

        stats_text = f"Mean: {mean:.6f}\nStd: {std:.6f}\nSkew: {returns.skew():.4f}\nKurtosis: {returns.kurtosis():.4f}"
        ax.text(0.05, 0.95, stats_text, transform=ax.transAxes,
                verticalalignment='top', bbox=dict(boxstyle='round', alpha=0.1))

    axes[-1].axis('off')
    plt.tight_layout()
    plt.savefig('plots/returns_distribution.png', dpi=150, bbox_inches='tight')
    print("Saved returns_distribution.png")
    plt.close()


def plot_correlation_heatmap(df_returns):
    corr_matrix = df_returns.corr()
    fig, ax = plt.subplots(figsize=(10, 8))
    mask = np.triu(np.ones_like(corr_matrix, dtype=bool))
    sns.heatmap(corr_matrix, mask=mask, annot=True, fmt='.3f',
                cmap='coolwarm', center=0, square=True,
                linewidths=1, cbar_kws={"shrink": 0.8}, ax=ax)
    ax.set_title('Correlation Heatmap', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig('plots/correlation_heatmap.png', dpi=150, bbox_inches='tight')
    print("Saved correlation_heatmap.png")
    plt.close()
    return corr_matrix


def plot_rolling_correlation(df_returns, window=24 * 7):
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    axes = axes.flatten()
    pairs = [('BTCUSDT', 'ETHUSDT'), ('BTCUSDT', 'BNBUSDT'),
             ('BTCUSDT', 'SOLUSDT'), ('BTCUSDT', 'XRPUSDT')]

    for i, (s1, s2) in enumerate(pairs):
        ax = axes[i]
        rolling_corr = df_returns[s1].rolling(window=window).corr(df_returns[s2])
        ax.plot(df_returns.index, rolling_corr, linewidth=1.5)
        ax.axhline(rolling_corr.mean(), color='r', linestyle='--',
                  label=f'Mean: {rolling_corr.mean():.3f}')
        ax.set_title(f'{s1} vs {s2} Rolling Correlation ({window//24}d window)',
                    fontsize=11, fontweight='bold')
        ax.set_xlabel('Time')
        ax.set_ylabel('Correlation')
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.set_ylim([-0.1, 1.0])
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)

    plt.tight_layout()
    plt.savefig('plots/rolling_correlation.png', dpi=150, bbox_inches='tight')
    print("Saved rolling_correlation.png")
    plt.close()


def cluster_analysis(df_returns):
    print("\n=== Cluster Analysis ===")
    returns_scaled = StandardScaler().fit_transform(df_returns.T)

    print("\n1. Hierarchical Clustering:")
    linked = linkage(returns_scaled, method='ward')
    fig, ax = plt.subplots(figsize=(10, 6))
    dendrogram(linked, labels=SYMBOLS, orientation='top',
               distance_sort='descending', show_leaf_counts=True, ax=ax)
    ax.set_title('Hierarchical Clustering Dendrogram', fontsize=14, fontweight='bold')
    ax.set_ylabel('Distance')
    plt.tight_layout()
    plt.savefig('plots/hierarchical_clustering.png', dpi=150, bbox_inches='tight')
    print("Saved hierarchical_clustering.png")
    plt.close()

    print("\n2. K-Means Clustering:")
    inertias = []
    K_range = range(1, min(5, len(SYMBOLS)))
    for k in K_range:
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
        kmeans.fit(returns_scaled)
        inertias.append(kmeans.inertia_)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(K_range, inertias, 'bo-', linewidth=2, markersize=8)
    ax.set_xlabel('Number of clusters (K)')
    ax.set_ylabel('Inertia')
    ax.set_title('K-Means Elbow Method', fontsize=12, fontweight='bold')
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig('plots/kmeans_elbow.png', dpi=150, bbox_inches='tight')
    print("Saved kmeans_elbow.png")
    plt.close()

    best_k = 2 if len(SYMBOLS) >= 2 else 1
    kmeans = KMeans(n_clusters=best_k, random_state=42, n_init=10)
    clusters = kmeans.fit_predict(returns_scaled)
    cluster_result = pd.DataFrame({'Symbol': SYMBOLS, 'Cluster': clusters}).sort_values('Cluster')
    print("\nClustering Results:")
    print(cluster_result.to_string(index=False))

    print("\n3. PCA Visualization:")
    pca = PCA(n_components=2)
    returns_pca = pca.fit_transform(returns_scaled)
    fig, ax = plt.subplots(figsize=(10, 8))
    scatter = ax.scatter(returns_pca[:, 0], returns_pca[:, 1],
                        c=clusters, cmap='viridis', s=200, alpha=0.7)

    for i, symbol in enumerate(SYMBOLS):
        ax.annotate(symbol, (returns_pca[i, 0], returns_pca[i, 1]),
                   fontsize=12, fontweight='bold',
                   xytext=(5, 5), textcoords='offset points')

    ax.set_xlabel(f'PC1 ({pca.explained_variance_ratio_[0]:.1%} variance)')
    ax.set_ylabel(f'PC2 ({pca.explained_variance_ratio_[1]:.1%} variance)')
    ax.set_title('Asset Clustering PCA Visualization', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    plt.colorbar(scatter, label='Cluster')
    plt.tight_layout()
    plt.savefig('plots/clustering_pca.png', dpi=150, bbox_inches='tight')
    print("Saved clustering_pca.png")
    plt.close()

    return cluster_result


def generate_summary_report(df_returns, corr_matrix, cluster_result):
    print("\n" + "="*60)
    print("Exploratory Analysis & Clustering - Summary Report")
    print("="*60)

    print("\n[Returns Statistics]")
    stats = df_returns.agg(['mean', 'std', 'skew', 'kurtosis'])
    print(stats.round(6).to_string())

    print("\n[Correlation Matrix]")
    print(corr_matrix.round(3).to_string())

    print("\n[Clustering Results]")
    print(cluster_result.to_string(index=False))

    corr_stack = corr_matrix.abs().stack()
    corr_stack = corr_stack[corr_stack < 1.0]
    top_corr = corr_stack.sort_values(ascending=False).head(5)

    print("\n[Top Correlated Pairs]")
    for (s1, s2), corr in top_corr.items():
        if s1 < s2:
            print(f"  {s1} <-> {s2}: {corr:.3f}")

    import json
    report = {
        'timestamp': pd.Timestamp.now().isoformat(),
        'returns_stats': stats.to_dict(),
        'correlation_matrix': corr_matrix.to_dict(),
        'clustering_result': cluster_result.to_dict('records'),
        'top_correlations': top_corr.head(10).to_dict()
    }

    with open('plots/analysis_report.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print(f"\nSaved detailed report to: plots/analysis_report.json")


def main():
    print('='*60)
    print('Binance Quant Trading - Exploratory Analysis & Clustering')
    print('='*60)

    Path('plots').mkdir(exist_ok=True)

    print("\n1. Loading data...")
    df_returns = load_all_returns()

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

    print("\n2. Plotting price trends...")
    plot_price_trends(df_prices)

    print("\n3. Plotting returns distribution...")
    plot_returns_distribution(df_returns)

    print("\n4. Plotting correlation heatmap...")
    corr_matrix = plot_correlation_heatmap(df_returns)

    print("\n5. Plotting rolling correlation...")
    plot_rolling_correlation(df_returns)

    print("\n6. Running cluster analysis...")
    cluster_result = cluster_analysis(df_returns)

    generate_summary_report(df_returns, corr_matrix, cluster_result)

    print('\n' + '='*60)
    print('Analysis complete! Check plots/ directory for charts')
    print('='*60)


if __name__ == '__main__':
    main()
