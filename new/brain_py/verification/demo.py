"""
verification/demo.py - 执行层真实性检验套件演示

演示 VerificationSuite 的完整功能：
1. 执行验证
2. 滑点分析
3. 异常检测
4. 综合报告
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import random
import logging
from datetime import datetime

from verification import (
    VerificationSuite, VerificationConfig,
    ExecutionMetrics, ExecutionValidator,
    SlippageDataPoint, SlippageAnalyzer,
    AnomalyDetector, AnomalyType
)
from shared.protocol import OrderStatusUpdate, TradeExecution

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def demo_execution_validation():
    """演示执行验证功能"""
    print("\n" + "="*60)
    print("演示 1: 执行结果验证")
    print("="*60)

    validator = ExecutionValidator()

    # 模拟预期执行
    expected = ExecutionMetrics(
        order_id=1,
        expected_price=50000.0,
        expected_quantity=0.1,
        expected_side=1,  # BUY
        expected_order_type=1  # LIMIT
    )

    # 模拟正常成交
    normal_fill = OrderStatusUpdate(
        order_id=1,
        command_id=1,
        timestamp_ns=time.time_ns(),
        side=1,
        type=1,
        status=3,  # FILLED
        price=50000.0,
        original_quantity=0.1,
        filled_quantity=0.1,
        remaining_quantity=0.0,
        average_fill_price=50001.0,  # 轻微滑点
        latency_us=50000,  # 50ms
        is_maker=True
    )

    result = validator.validate_execution(expected, normal_fill)
    print(f"正常成交验证结果:")
    print(f"  是否有效: {result.is_valid}")
    print(f"  价格偏差: {result.price_deviation_bps:.2f} bps")
    print(f"  延迟: {result.latency_ms:.2f} ms")
    print(f"  错误: {result.errors}")

    # 模拟异常成交（大幅滑点）
    bad_fill = OrderStatusUpdate(
        order_id=2,
        command_id=2,
        timestamp_ns=time.time_ns(),
        side=1,
        type=1,
        status=3,
        price=50000.0,
        original_quantity=0.1,
        filled_quantity=0.1,
        remaining_quantity=0.0,
        average_fill_price=50250.0,  # 50 bps 滑点
        latency_us=200000,  # 200ms - 高延迟
        is_maker=False
    )

    expected2 = ExecutionMetrics(
        order_id=2,
        expected_price=50000.0,
        expected_quantity=0.1,
        expected_side=1,
        expected_order_type=1
    )

    result2 = validator.validate_execution(expected2, bad_fill)
    print(f"\n异常成交验证结果:")
    print(f"  是否有效: {result2.is_valid}")
    print(f"  价格偏差: {result2.price_deviation_bps:.2f} bps")
    print(f"  延迟: {result2.latency_ms:.2f} ms")
    print(f"  错误: {result2.errors}")

    stats = validator.get_stats()
    print(f"\n验证统计:")
    print(f"  总验证次数: {stats['total_validations']}")
    print(f"  有效率: {stats['valid_rate']:.1f}%")
    print(f"  平均延迟: {stats['avg_latency_ms']:.2f} ms")


def demo_slippage_analysis():
    """演示滑点分析功能"""
    print("\n" + "="*60)
    print("演示 2: 滑点分析")
    print("="*60)

    analyzer = SlippageAnalyzer()

    # 生成模拟滑点数据
    print("生成 100 条滑点记录...")
    for i in range(100):
        # 模拟预测误差（正态分布）
        bias = random.gauss(0, 2)  # 平均 0，标准差 2 bps

        data = SlippageDataPoint(
            timestamp_ns=time.time_ns() - int((100-i) * 1e9),  # 分散在100秒内
            order_id=i,
            symbol="BTCUSDT",
            predicted_slippage_bps=1.0,
            predicted_uncertainty=0.5,
            actual_slippage_bps=1.0 + bias,
            market_impact_bps=0.5,
            order_size_usd=random.uniform(1000, 50000),
            order_type=1,
            is_maker=random.random() > 0.3,
            execution_time_ms=random.uniform(10, 100),
            spread_bps=5.0,
            volatility=0.02,
            ofi=random.uniform(-0.5, 0.5),
            queue_position=random.uniform(0, 1)
        )
        analyzer.record_slippage(data)

    # 生成分析报告
    report = analyzer.analyze()
    print(f"\n滑点分析报告:")
    print(f"  样本数: {report.total_samples}")
    print(f"  平均预测滑点: {report.mean_predicted_bps:.2f} bps")
    print(f"  平均实际滑点: {report.mean_actual_bps:.2f} bps")
    print(f"  平均偏差: {report.mean_bias_bps:.2f} bps")
    print(f"  MAE: {report.mae_bps:.2f} bps")
    print(f"  RMSE: {report.rmse_bps:.2f} bps")
    print(f"  预测效率: {report.prediction_efficiency:.2%}")
    print(f"  异常值数量: {report.outlier_count}")


def demo_anomaly_detection():
    """演示异常检测功能"""
    print("\n" + "="*60)
    print("演示 3: 异常检测")
    print("="*60)

    detector = AnomalyDetector()

    # 注册指标
    detector.register_metric('price')
    detector.register_metric('latency')
    detector.register_metric('volume')

    print("记录正常指标数据...")
    # 记录正常数据（建立基线）
    for i in range(100):
        detector.record_metric('price', random.gauss(50000, 100))
        detector.record_metric('latency', random.gauss(50, 10))
        detector.record_metric('volume', random.gauss(1000, 200))

    print("检测异常值...")
    # 检测异常值
    anomalies = []

    # 正常值
    result = detector.record_metric('price', 50100)
    if result:
        anomalies.append(result)
        print(f"  检测到异常: {result.anomaly_type.name}, 严重程度: {result.severity}")

    # 异常值（价格飙升）
    result = detector.record_metric('price', 52000)  # 4 sigma 偏差
    if result:
        anomalies.append(result)
        print(f"  检测到异常: {result.anomaly_type.name}, 严重程度: {result.severity}")

    # 异常值（延迟飙升）
    result = detector.record_metric('latency', 200)  # 高延迟
    if result:
        anomalies.append(result)
        print(f"  检测到异常: {result.anomaly_type.name}, 严重程度: {result.severity}")

    # 批量检测
    print("\n批量检测指标...")
    batch_metrics = {
        'price': 50050,
        'latency': 150,
        'volume': 5000,  # 成交量异常
        'adverse_score': 0.8,  # 毒流信号
        'toxic_probability': 0.75
    }
    batch_anomalies = detector.detect(batch_metrics)
    for anomaly in batch_anomalies:
        print(f"  检测到: {anomaly.anomaly_type.name} - {anomaly.title}")

    stats = detector.get_anomaly_stats()
    print(f"\n异常统计:")
    print(f"  总异常数: {stats['total']}")
    print(f"  按类型: {stats['by_type']}")
    print(f"  按严重程度: {stats['by_severity']}")


def demo_verification_suite():
    """演示完整验证套件"""
    print("\n" + "="*60)
    print("演示 4: 完整验证套件")
    print("="*60)

    config = VerificationConfig(
        report_interval_sec=5.0
    )

    suite = VerificationSuite(config)

    # 注册告警回调
    def on_alert(level, message):
        print(f"  [告警-{level.upper()}] {message}")

    suite.on_alert(on_alert)

    # 启动套件
    suite.start()
    print("验证套件已启动")

    try:
        # 模拟执行验证
        print("\n模拟执行验证...")
        for i in range(10):
            expected = ExecutionMetrics(
                order_id=i,
                expected_price=50000.0,
                expected_quantity=0.1,
                expected_side=1,
                expected_order_type=1
            )

            # 模拟实际执行
            actual = OrderStatusUpdate(
                order_id=i,
                command_id=i,
                timestamp_ns=time.time_ns(),
                side=1,
                type=1,
                status=3,
                price=50000.0,
                original_quantity=0.1,
                filled_quantity=0.1,
                remaining_quantity=0.0,
                average_fill_price=50000.0 + random.gauss(0, 50),
                latency_us=int(random.gauss(50000, 20000)),
                is_maker=True
            )

            result = suite.record_execution(expected, actual)
            print(f"  订单 {i}: valid={result.is_valid}, "
                  f"deviation={result.price_deviation_bps:.2f} bps")

        # 模拟滑点记录
        print("\n模拟滑点记录...")
        for i in range(20):
            data = SlippageDataPoint(
                timestamp_ns=time.time_ns(),
                order_id=i,
                symbol="BTCUSDT",
                predicted_slippage_bps=1.0,
                actual_slippage_bps=1.0 + random.gauss(0, 1),
                order_size_usd=10000.0,
                is_maker=True
            )
            suite.record_slippage(data)

        # 模拟异常检测
        print("\n模拟异常检测...")
        for i in range(50):
            metrics = {
                'price': random.gauss(50000, 100),
                'latency': random.gauss(50, 15),
                'volume': random.gauss(1000, 200)
            }
            suite.record_metrics(metrics)

        # 生成报告
        print("\n生成验证报告...")
        report = suite.generate_report()
        print(f"  整体健康状态: {report.overall_health}")
        print(f"  验证器统计: {report.validator_stats}")
        print(f"  滑点统计: {report.slippage_stats}")
        print(f"  异常统计: {report.anomaly_stats}")
        print(f"  建议: {report.recommendations}")

        # 等待一段时间让报告循环运行
        print("\n等待自动报告生成...")
        time.sleep(6)

    finally:
        suite.stop()
        print("\n验证套件已停止")


def main():
    """主函数"""
    print("="*60)
    print("执行层真实性检验套件演示")
    print("="*60)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 运行各个演示
    demo_execution_validation()
    demo_slippage_analysis()
    demo_anomaly_detection()
    demo_verification_suite()

    print("\n" + "="*60)
    print("演示完成")
    print("="*60)


if __name__ == "__main__":
    main()
