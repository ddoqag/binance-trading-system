"""
Phase 1: MVP历史数据回测运行器

执行完整的Phase 1测试计划：
1. 历史数据回测
2. 对比完整系统表现
3. 参数调优
4. 毒流检测阈值优化

输出：
- 回测报告
- 对比分析报告
- 最优参数配置
- 数据质量报告
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import json
import logging
import sys
import os

# 添加brain_py到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mvp_backtest import (
    MVPBacktestEngine, MVPBacktestResult, BacktestConfig,
    HistoricalDataLoader, print_backtest_report, MVPParameterOptimizer
)
from mvp_comparison import MVPComparator, print_comparison_report
from mvp_data_connector import HistoricalDataConnector, DataValidator, DataSourceConfig


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('Phase1Runner')


class Phase1Runner:
    """
    Phase 1 回测运行器

    执行完整的Phase 1测试流程
    """

    def __init__(self, output_dir: str = "./phase1_results"):
        self.output_dir = output_dir
        self.results: Dict[str, any] = {}

        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)

    def run_full_suite(self,
                       data_source: str = "synthetic",
                       data_params: Optional[Dict] = None,
                       n_ticks: int = 5000) -> Dict:
        """
        运行完整的Phase 1测试套件

        Args:
            data_source: 数据源 ('synthetic', 'postgresql', 'csv', 'binance')
            data_params: 数据源参数
            n_ticks: tick数量

        Returns:
            完整测试结果
        """
        logger.info("=" * 70)
        logger.info("Phase 1: MVP历史数据回测")
        logger.info("=" * 70)

        # 1. 加载数据
        logger.info("\n[Step 1/5] 加载历史数据...")
        ticks = self._load_data(data_source, data_params, n_ticks)

        if not ticks:
            logger.error("数据加载失败")
            return {}

        # 验证数据
        validator = DataValidator()
        if not validator.validate(ticks):
            logger.warning(f"数据验证警告: {validator.get_report()['issues']}")

        # 2. 运行MVP回测
        logger.info("\n[Step 2/5] 运行MVP回测...")
        mvp_result = self._run_mvp_backtest(ticks)

        # 3. 对比完整系统
        logger.info("\n[Step 3/5] 对比完整系统...")
        comparison_report = self._run_comparison(ticks)

        # 4. 参数优化
        logger.info("\n[Step 4/5] 参数优化...")
        optimal_params = self._optimize_parameters(ticks)

        # 5. 毒流检测优化
        logger.info("\n[Step 5/5] 毒流检测阈值优化...")
        toxic_optimal = self._optimize_toxic_detection(ticks)

        # 汇总结果
        self.results = {
            'timestamp': datetime.now().isoformat(),
            'data_source': data_source,
            'n_ticks': len(ticks),
            'mvp_result': self._result_to_dict(mvp_result),
            'comparison': self._comparison_to_dict(comparison_report),
            'optimal_params': optimal_params,
            'toxic_optimal': toxic_optimal
        }

        # 保存报告
        self._save_reports()

        return self.results

    def _load_data(self,
                   source: str,
                   params: Optional[Dict],
                   n_ticks: int) -> List:
        """加载数据"""
        if source == "synthetic":
            loader = HistoricalDataLoader()
            base_price = params.get('base_price', 50000.0) if params else 50000.0
            volatility = params.get('volatility', 0.001) if params else 0.001
            return loader.generate_synthetic_data(n_ticks, base_price, volatility)

        elif source == "postgresql":
            config = DataSourceConfig(**(params or {}))
            connector = HistoricalDataConnector(config)
            symbol = params.get('symbol', 'BTCUSDT') if params else 'BTCUSDT'
            start = params.get('start_date', '2024-01-01') if params else '2024-01-01'
            end = params.get('end_date', '2024-01-02') if params else '2024-01-02'
            interval = params.get('interval', '1m') if params else '1m'
            return connector.load_from_postgresql(symbol, start, end, interval)

        elif source == "csv":
            filepath = params.get('filepath', '') if params else ''
            symbol = params.get('symbol', 'BTCUSDT') if params else 'BTCUSDT'
            if not filepath:
                logger.error("CSV文件路径未指定")
                return []
            connector = HistoricalDataConnector()
            return connector.load_from_csv(symbol, filepath)

        elif source == "binance":
            config = DataSourceConfig(**(params or {}))
            connector = HistoricalDataConnector(config)
            symbol = params.get('symbol', 'BTCUSDT') if params else 'BTCUSDT'
            start = params.get('start_date', '2024-01-01') if params else '2024-01-01'
            end = params.get('end_date', '2024-01-02') if params else '2024-01-02'
            interval = params.get('interval', '1m') if params else '1m'
            return connector.fetch_from_binance(symbol, start, end, interval)

        else:
            logger.error(f"未知数据源: {source}")
            return []

    def _run_mvp_backtest(self, ticks: List) -> MVPBacktestResult:
        """运行MVP回测"""
        config = BacktestConfig(
            symbol="BTCUSDT",
            initial_capital=1000.0,
            max_position=0.1,
            queue_target_ratio=0.3,
            toxic_threshold=0.3,
            min_spread_ticks=2
        )

        engine = MVPBacktestEngine(config)
        engine.load_data(ticks)

        result = engine.run(progress_interval=500)

        # 打印报告
        print_backtest_report(result)

        return result

    def _run_comparison(self, ticks: List):
        """运行对比测试"""
        config = BacktestConfig(
            symbol="BTCUSDT",
            initial_capital=1000.0,
            max_position=0.1
        )

        comparator = MVPComparator()
        report = comparator.run_comparison(ticks, config, n_runs=2)

        # 打印报告
        print_comparison_report(report)

        return report

    def _optimize_parameters(self, ticks: List) -> Dict:
        """参数优化"""
        config = BacktestConfig(
            symbol="BTCUSDT",
            initial_capital=1000.0,
            max_position=0.1
        )

        engine = MVPBacktestEngine(config)
        optimizer = MVPParameterOptimizer(engine)

        # 小规模网格搜索
        param_grid = {
            'queue_target_ratio': [0.2, 0.3, 0.4],
            'toxic_threshold': [0.25, 0.3, 0.35],
            'min_spread_ticks': [1, 2, 3]
        }

        # 只用前1000个tick做快速优化
        best_params = optimizer.grid_search(param_grid, ticks[:1000])

        print("\n" + "-" * 70)
        print("参数优化结果")
        print("-" * 70)
        print(f"最优参数: {best_params}")

        # 打印Top 3
        top3 = optimizer.get_top_results(3)
        print("\nTop 3 参数组合:")
        for i, (params, result) in enumerate(top3, 1):
            print(f"  {i}. {params} -> Sharpe: {result.sharpe_ratio:.2f}, PnL: ${result.total_pnl:.2f}")

        return best_params

    def _optimize_toxic_detection(self, ticks: List) -> Dict:
        """优化毒流检测阈值"""
        logger.info("测试不同毒流检测阈值...")

        thresholds = [0.2, 0.25, 0.3, 0.35, 0.4]
        results = []

        for threshold in thresholds:
            config = BacktestConfig(
                symbol="BTCUSDT",
                initial_capital=1000.0,
                max_position=0.1,
                toxic_threshold=threshold
            )

            engine = MVPBacktestEngine(config)
            engine.load_data(ticks[:1000])  # 使用子集快速测试
            result = engine.run(progress_interval=10000)

            results.append({
                'threshold': threshold,
                'pnl': result.total_pnl,
                'sharpe': result.sharpe_ratio,
                'blocks': result.toxic_blocks,
                'block_rate': result.toxic_alert_rate
            })

        # 找到最优阈值
        best = max(results, key=lambda x: x['sharpe'])

        print("\n毒流检测阈值优化结果:")
        print("-" * 70)
        print(f"{'阈值':<10} {'盈亏':<12} {'夏普':<10} {'阻止次数':<10} {'阻止率':<10}")
        print("-" * 70)
        for r in results:
            marker = " *" if r['threshold'] == best['threshold'] else ""
            print(f"{r['threshold']:<10.2f} ${r['pnl']:<11.2f} {r['sharpe']:<10.2f} {r['blocks']:<10} {r['block_rate']:<10.2%}{marker}")
        print("-" * 70)
        print(f"* 最优阈值: {best['threshold']}")

        return best

    def _result_to_dict(self, result: MVPBacktestResult) -> Dict:
        """转换结果为字典"""
        return {
            'total_pnl': result.total_pnl,
            'total_pnl_pct': result.total_pnl_pct,
            'sharpe_ratio': result.sharpe_ratio,
            'max_drawdown_pct': result.max_drawdown_pct,
            'win_rate': result.win_rate,
            'profit_factor': result.profit_factor,
            'total_orders': result.total_orders,
            'total_fills': result.total_fills,
            'fill_rate': result.fill_rate,
            'avg_latency_ms': result.avg_latency_ms,
            'toxic_blocks': result.toxic_blocks,
            'spread_captures': result.spread_captures,
            'pnl_components': result.pnl_components
        }

    def _comparison_to_dict(self, report) -> Dict:
        """转换对比报告为字典"""
        return {
            'mvp_score': report.mvp_score,
            'full_score': report.full_score,
            'overall_winner': report.overall_winner,
            'metrics': [
                {
                    'name': m.metric_name,
                    'mvp': m.mvp_value,
                    'full': m.full_system_value,
                    'winner': m.winner
                }
                for m in report.metrics
            ]
        }

    def _save_reports(self):
        """保存报告到文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # JSON报告
        json_path = os.path.join(self.output_dir, f"phase1_report_{timestamp}.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)

        logger.info(f"\n报告已保存: {json_path}")

        # 生成Markdown摘要
        md_path = os.path.join(self.output_dir, f"phase1_summary_{timestamp}.md")
        self._generate_markdown_summary(md_path)

    def _generate_markdown_summary(self, path: str):
        """生成Markdown摘要"""
        r = self.results

        md = f"""# Phase 1 回测报告

## 测试信息

- **时间**: {r['timestamp']}
- **数据源**: {r['data_source']}
- **Tick数量**: {r['n_ticks']}

## MVP回测结果

| 指标 | 数值 |
|------|------|
| 总盈亏 | ${r['mvp_result']['total_pnl']:.4f} ({r['mvp_result']['total_pnl_pct']:.2%}) |
| 夏普比率 | {r['mvp_result']['sharpe_ratio']:.2f} |
| 最大回撤 | {r['mvp_result']['max_drawdown_pct']:.2%} |
| 胜率 | {r['mvp_result']['win_rate']:.1%} |
| 盈亏比 | {r['mvp_result']['profit_factor']:.2f} |
| 成交率 | {r['mvp_result']['fill_rate']:.1%} |
| 平均延迟 | {r['mvp_result']['avg_latency_ms']:.3f} ms |
| 毒流阻止 | {r['mvp_result']['toxic_blocks']} 次 |
| 点差捕获 | {r['mvp_result']['spread_captures']} 次 |

## 对比分析

**综合评分**: MVP {r['comparison']['mvp_score']:.1f} vs 完整系统 {r['comparison']['full_score']:.1f}

**胜出**: {'MVP' if r['comparison']['overall_winner'] == 'mvp' else '完整系统'}

### 详细对比

| 指标 | MVP | 完整系统 | 胜出 |
|------|-----|----------|------|
"""

        for m in r['comparison']['metrics']:
            winner = "MVP" if m['winner'] == 'mvp' else "完整" if m['winner'] == 'full' else "平"
            md += f"| {m['name']} | {m['mvp']:.2f} | {m['full']:.2f} | {winner} |\n"

        md += f"""
## 最优参数配置

```json
{json.dumps(r['optimal_params'], indent=2)}
```

## 毒流检测优化

- **最优阈值**: {r['toxic_optimal']['threshold']}
- **对应夏普**: {r['toxic_optimal']['sharpe']:.2f}
- **阻止率**: {r['toxic_optimal']['block_rate']:.2%}

## 结论

MVP系统在历史数据回测中表现{'良好' if r['mvp_result']['sharpe_ratio'] > 1 else '一般'}，
夏普比率为 {r['mvp_result']['sharpe_ratio']:.2f}，
最大回撤控制在 {r['mvp_result']['max_drawdown_pct']:.2%} 以内。

{'建议进入Phase 2小资金实盘测试。' if r['mvp_result']['sharpe_ratio'] > 0.5 and r['mvp_result']['max_drawdown_pct'] > -0.1 else '建议继续优化参数后再进行实盘测试。'}
"""

        with open(path, 'w', encoding='utf-8') as f:
            f.write(md)

        logger.info(f"摘要已保存: {path}")


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='Phase 1 MVP回测')
    parser.add_argument('--data', type=str, default='synthetic',
                       choices=['synthetic', 'postgresql', 'csv', 'binance'],
                       help='数据源')
    parser.add_argument('--ticks', type=int, default=5000,
                       help='Tick数量')
    parser.add_argument('--output', type=str, default='./phase1_results',
                       help='输出目录')

    args = parser.parse_args()

    # 运行Phase 1
    runner = Phase1Runner(output_dir=args.output)

    data_params = None
    if args.data == 'synthetic':
        data_params = {'base_price': 50000.0, 'volatility': 0.001}

    results = runner.run_full_suite(
        data_source=args.data,
        data_params=data_params,
        n_ticks=args.ticks
    )

    # 打印最终结论
    print("\n" + "=" * 70)
    print("Phase 1 完成")
    print("=" * 70)

    if results:
        print(f"\n关键结果:")
        print(f"  MVP夏普比率: {results['mvp_result']['sharpe_ratio']:.2f}")
        print(f"  总盈亏: ${results['mvp_result']['total_pnl']:.4f}")
        print(f"  胜出方: {'MVP' if results['comparison']['overall_winner'] == 'mvp' else '完整系统'}")
        print(f"\n下一步: {'进入Phase 2' if results['mvp_result']['sharpe_ratio'] > 0.5 else '继续优化'}")


if __name__ == "__main__":
    main()
