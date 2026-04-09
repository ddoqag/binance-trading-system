"""
test_verification.py - 执行层真实性检验套件测试

测试组件:
- ExecutionValidator
- SlippageAnalyzer
- AnomalyDetector
"""

import time
import pytest
import numpy as np
from datetime import datetime

from verification import (
    ExecutionValidator, ValidationResult, ExecutionMetrics,
    SlippageAnalyzer, SlippageReport, SlippageDataPoint,
    AnomalyDetector, Anomaly, AnomalyType
)
from shared.protocol import OrderStatusUpdate, TradeExecution


class TestExecutionValidator:
    """执行验证器测试"""

    def test_basic_validation(self):
        """测试基本验证功能"""
        validator = ExecutionValidator()

        expected = ExecutionMetrics(
            order_id=1,
            expected_price=50000.0,
            expected_quantity=1.0,
            expected_side=1,
            expected_order_type=1
        )

        actual = OrderStatusUpdate(
            order_id=1,
            command_id=1,
            timestamp_ns=time.time_ns(),
            side=1,
            type=1,
            status=3,  # FILLED
            price=50000.0,
            original_quantity=1.0,
            filled_quantity=1.0,
            remaining_quantity=0.0,
            average_fill_price=50000.0,
            latency_us=500.0,
            is_maker=True
        )

        result = validator.validate_execution(expected, actual)

        assert result.is_valid is True
        assert result.price_valid is True
        assert result.quantity_valid is True
        assert result.latency_ms == 0.5

    def test_price_deviation_detection(self):
        """测试价格偏差检测"""
        validator = ExecutionValidator()

        expected = ExecutionMetrics(
            order_id=2,
            expected_price=50000.0,
            expected_quantity=1.0
        )

        # 价格偏差 1% = 100 bps
        actual = OrderStatusUpdate(
            order_id=2,
            command_id=2,
            timestamp_ns=time.time_ns(),
            side=1,
            type=1,
            status=3,
            price=50500.0,
            original_quantity=1.0,
            filled_quantity=1.0,
            remaining_quantity=0.0,
            average_fill_price=50500.0,
            latency_us=500.0,
            is_maker=True
        )

        result = validator.validate_execution(expected, actual)

        assert result.is_valid is False  # 超过 50 bps 阈值
        assert result.price_valid is False
        assert result.price_deviation_bps == pytest.approx(100.0, rel=1e-3)

    def test_latency_validation(self):
        """测试延迟验证"""
        validator = ExecutionValidator()

        expected = ExecutionMetrics(
            order_id=3,
            expected_price=50000.0,
            expected_quantity=1.0
        )

        # 延迟 150ms，超过 100ms 阈值
        actual = OrderStatusUpdate(
            order_id=3,
            command_id=3,
            timestamp_ns=time.time_ns(),
            side=1,
            type=1,
            status=3,
            price=50000.0,
            original_quantity=1.0,
            filled_quantity=1.0,
            remaining_quantity=0.0,
            average_fill_price=50000.0,
            latency_us=150000.0,
            is_maker=True
        )

        result = validator.validate_execution(expected, actual)

        assert result.is_valid is False
        assert result.latency_valid is False
        assert result.latency_ms == 150.0

    def test_trade_execution_validation(self):
        """测试 TradeExecution 验证"""
        validator = ExecutionValidator()

        expected = ExecutionMetrics(
            order_id=4,
            expected_price=50000.0,
            expected_quantity=0.5
        )

        actual = TradeExecution(
            trade_id=1,
            order_id=4,
            timestamp_ns=time.time_ns(),
            side=1,
            price=50000.0,
            quantity=0.5,
            commission=0.001,
            realized_pnl=0.0,
            adverse_selection=0.0,
            is_maker=True
        )

        result = validator.validate_execution(expected, actual)

        assert result.is_valid is True
        assert result.quantity_valid is True

    def test_stats_calculation(self):
        """测试统计计算"""
        validator = ExecutionValidator()

        # 模拟多次验证
        for i in range(10):
            expected = ExecutionMetrics(
                order_id=i,
                expected_price=50000.0,
                expected_quantity=1.0
            )

            actual = OrderStatusUpdate(
                order_id=i,
                command_id=i,
                timestamp_ns=time.time_ns(),
                side=1,
                type=1,
                status=3,
                price=50000.0 + i * 10,
                original_quantity=1.0,
                filled_quantity=1.0,
                remaining_quantity=0.0,
                average_fill_price=50000.0 + i * 10,
                latency_us=50000.0 + i * 1000,
                is_maker=True
            )

            validator.validate_execution(expected, actual)

        stats = validator.get_stats()

        assert stats['total_validations'] == 10
        assert stats['valid_count'] <= 10
        assert 'avg_latency_ms' in stats
        assert 'avg_price_deviation_bps' in stats

    def test_callback_registration(self):
        """测试回调注册"""
        validator = ExecutionValidator()

        validation_called = [False]
        error_called = [False]

        def on_validation(result):
            validation_called[0] = True

        def on_error(result):
            error_called[0] = True

        validator.on_validation(on_validation)
        validator.on_error(on_error)

        # 触发一次验证
        expected = ExecutionMetrics(order_id=1, expected_price=50000.0)
        actual = OrderStatusUpdate(
            order_id=1, command_id=1, timestamp_ns=time.time_ns(),
            side=1, type=1, status=3, price=50000.0,
            original_quantity=1.0, filled_quantity=1.0,
            remaining_quantity=0.0, average_fill_price=50000.0,
            latency_us=500.0, is_maker=True
        )

        validator.validate_execution(expected, actual)

        assert validation_called[0] is True


class TestSlippageAnalyzer:
    """滑点分析器测试"""

    def test_record_slippage(self):
        """测试记录滑点数据"""
        analyzer = SlippageAnalyzer()

        data = SlippageDataPoint(
            timestamp_ns=time.time_ns(),
            order_id=1,
            predicted_slippage_bps=2.0,
            actual_slippage_bps=2.5,
            order_size_usd=5000.0,
            is_maker=True
        )

        result = analyzer.record_slippage(data)
        assert result is True

    def test_slippage_analysis(self):
        """测试滑点分析"""
        analyzer = SlippageAnalyzer()

        # 添加多个数据点
        np.random.seed(42)
        for i in range(100):
            predicted = 2.0 + np.random.normal(0, 0.5)
            actual = predicted + np.random.normal(0, 1.0)

            data = SlippageDataPoint(
                timestamp_ns=time.time_ns(),
                order_id=i,
                predicted_slippage_bps=predicted,
                actual_slippage_bps=actual,
                order_size_usd=5000.0 + i * 100,
                is_maker=i % 2 == 0
            )
            analyzer.record_slippage(data)

        report = analyzer.analyze()

        assert report.total_samples == 100
        assert report.mae_bps > 0
        assert report.rmse_bps > 0
        assert 'count' in report.maker_stats
        assert 'count' in report.taker_stats

    def test_outlier_detection(self):
        """测试异常值检测"""
        analyzer = SlippageAnalyzer()

        # 添加正常数据
        for i in range(50):
            data = SlippageDataPoint(
                timestamp_ns=time.time_ns(),
                order_id=i,
                predicted_slippage_bps=2.0,
                actual_slippage_bps=2.0 + np.random.normal(0, 0.5),
                order_size_usd=5000.0,
                is_maker=True
            )
            analyzer.record_slippage(data)

        # 添加异常值
        outlier_data = SlippageDataPoint(
            timestamp_ns=time.time_ns(),
            order_id=999,
            predicted_slippage_bps=2.0,
            actual_slippage_bps=20.0,  # 异常大滑点
            order_size_usd=5000.0,
            is_maker=True
        )

        outlier_detected = [False]

        def on_outlier(data):
            outlier_detected[0] = True

        analyzer.on_outlier(on_outlier)
        analyzer.record_slippage(outlier_data)

        assert outlier_detected[0] is True

    def test_report_generation(self):
        """测试报告生成"""
        analyzer = SlippageAnalyzer()

        # 生成测试数据
        for i in range(50):
            data = SlippageDataPoint(
                timestamp_ns=time.time_ns(),
                order_id=i,
                predicted_slippage_bps=2.0,
                actual_slippage_bps=2.2 + np.random.normal(0, 0.3),
                order_size_usd=5000.0,
                is_maker=True,
                spread_bps=5.0,
                volatility=0.02
            )
            analyzer.record_slippage(data)

        report = analyzer.analyze()

        assert report.total_samples >= 10
        assert report.mean_bias_bps is not None
        assert report.p50_bias_bps is not None
        assert report.p95_bias_bps is not None
        assert report.p99_bias_bps is not None

    def test_analyze_from_arrays(self):
        """测试从数组分析"""
        analyzer = SlippageAnalyzer()

        predictions = [2.0] * 100
        actuals = [2.0 + np.random.normal(0, 0.5) for _ in range(100)]

        report = analyzer.analyze(predictions=predictions, actuals=actuals)

        assert report.total_samples == 100
        assert report.mae_bps > 0
        assert report.rmse_bps > 0


class TestAnomalyDetector:
    """异常检测器测试"""

    def test_metric_registration(self):
        """测试指标注册"""
        detector = AnomalyDetector()

        detector.register_metric('test_metric')

        # 添加足够的数据
        for i in range(60):
            detector.record_metric('test_metric', 100.0 + np.random.normal(0, 5))

        # 正常值不应触发异常
        anomaly = detector.record_metric('test_metric', 100.0)
        assert anomaly is None

    def test_anomaly_detection(self):
        """测试异常检测"""
        detector = AnomalyDetector()

        # 建立基线
        for i in range(60):
            detector.record_metric('price', 50000.0 + np.random.normal(0, 100))

        # 异常值应该被检测到
        anomaly = detector.record_metric('price', 55000.0)  # 5 sigma deviation

        assert anomaly is not None
        assert anomaly.anomaly_type == AnomalyType.PRICE_SPIKE
        assert anomaly.severity in ['medium', 'high', 'critical']

    def test_batch_detection(self):
        """测试批量检测"""
        detector = AnomalyDetector()

        # 先建立基线
        for i in range(60):
            detector.detect({
                'latency': 50.0 + np.random.normal(0, 5),
                'volume': 1000.0 + np.random.normal(0, 100)
            })

        # 批量检测异常
        anomalies = detector.detect({
            'latency': 200.0,  # 异常高延迟
            'volume': 5000.0   # 异常高成交量
        })

        assert len(anomalies) > 0

    def test_toxic_flow_detection(self):
        """测试毒流检测"""
        detector = AnomalyDetector()

        # 正常数据
        for i in range(50):
            detector.detect({
                'adverse_score': 0.2,
                'toxic_probability': 0.3
            })

        # 毒流数据
        anomalies = detector.detect({
            'adverse_score': 0.8,  # 超过阈值
            'toxic_probability': 0.9  # 超过阈值
        })

        toxic_anomalies = [a for a in anomalies if a.anomaly_type == AnomalyType.TOXIC_FLOW]
        assert len(toxic_anomalies) > 0

    def test_execution_failure_detection(self):
        """测试执行失败检测"""
        detector = AnomalyDetector()

        anomalies = detector.detect({
            'status': 5,  # REJECTED
            'error_code': 1001
        })

        failure_anomalies = [a for a in anomalies if a.anomaly_type == AnomalyType.EXECUTION_FAILURE]
        assert len(failure_anomalies) > 0
        assert failure_anomalies[0].severity == 'critical'

    def test_callback_and_acknowledgment(self):
        """测试回调和确认"""
        detector = AnomalyDetector()

        anomaly_received = [None]

        def on_anomaly(anomaly):
            anomaly_received[0] = anomaly

        detector.on_anomaly(on_anomaly)

        # 建立基线
        for i in range(60):
            detector.record_metric('test', 100.0)

        # 触发异常
        detector.record_metric('test', 200.0)

        assert anomaly_received[0] is not None

        # 确认异常
        anomaly_id = anomaly_received[0].anomaly_id
        result = detector.acknowledge_anomaly(anomaly_id, 'test_user')
        assert result is True

        # 验证确认状态
        recent = detector.get_recent_anomalies(n=1)
        assert recent[0].is_acknowledged is True
        assert recent[0].acknowledged_by == 'test_user'

    def test_anomaly_stats(self):
        """测试异常统计"""
        detector = AnomalyDetector()

        # 生成不同类型的异常
        for i in range(60):
            detector.record_metric('price', 100.0)
            detector.record_metric('latency', 50.0)

        # 触发异常
        detector.record_metric('price', 200.0)
        detector.record_metric('latency', 200.0)

        stats = detector.get_anomaly_stats()

        assert 'total' in stats
        assert 'by_type' in stats
        assert 'by_severity' in stats

    def test_alert_suppression(self):
        """测试告警抑制"""
        detector = AnomalyDetector()
        detector.config.alert_suppression_sec = 1.0  # 1秒抑制

        anomaly_count = [0]

        def on_anomaly(anomaly):
            anomaly_count[0] += 1

        detector.on_anomaly(on_anomaly)

        # 建立基线
        for i in range(60):
            detector.record_metric('price', 100.0)

        # 触发多次相同类型的异常
        detector.record_metric('price', 200.0)
        detector.record_metric('price', 210.0)
        detector.record_metric('price', 220.0)

        # 由于告警抑制，应该只触发一次
        assert anomaly_count[0] == 1


class TestIntegration:
    """集成测试"""

    def test_full_workflow(self):
        """测试完整工作流"""
        validator = ExecutionValidator()
        slippage_analyzer = SlippageAnalyzer()
        anomaly_detector = AnomalyDetector()

        # 模拟交易执行流程
        for i in range(20):
            # 1. 注册预期执行
            expected = ExecutionMetrics(
                order_id=i,
                expected_price=50000.0,
                expected_quantity=1.0,
                expected_side=1
            )
            validator.register_expected_execution(expected)

            # 2. 模拟实际执行
            actual_price = 50000.0 + np.random.normal(0, 50)
            actual = OrderStatusUpdate(
                order_id=i,
                command_id=i,
                timestamp_ns=time.time_ns(),
                side=1,
                type=1,
                status=3,
                price=actual_price,
                original_quantity=1.0,
                filled_quantity=1.0,
                remaining_quantity=0.0,
                average_fill_price=actual_price,
                latency_us=50000.0 + np.random.normal(0, 10000),
                is_maker=True
            )

            # 3. 验证执行
            validation_result = validator.validate_execution(expected, actual)

            # 4. 记录滑点
            slippage_bps = (actual_price - expected.expected_price) / expected.expected_price * 10000
            slippage_data = SlippageDataPoint(
                timestamp_ns=time.time_ns(),
                order_id=i,
                predicted_slippage_bps=0.0,
                actual_slippage_bps=slippage_bps,
                order_size_usd=50000.0,
                is_maker=True
            )
            slippage_analyzer.record_slippage(slippage_data)

            # 5. 检测异常
            anomaly_detector.detect({
                'execution_latency': actual.latency_us / 1000.0,
                'price_deviation': abs(slippage_bps),
                'fill_rate': 1.0
            })

        # 验证结果
        validator_stats = validator.get_stats()
        slippage_report = slippage_analyzer.analyze()
        anomaly_stats = anomaly_detector.get_anomaly_stats()

        assert validator_stats['total_validations'] == 20
        assert slippage_report.total_samples == 20

    def test_report_generation(self):
        """测试报告生成"""
        validator = ExecutionValidator()
        slippage_analyzer = SlippageAnalyzer()
        anomaly_detector = AnomalyDetector()

        # 生成一些数据
        for i in range(30):
            expected = ExecutionMetrics(order_id=i, expected_price=50000.0)
            actual = OrderStatusUpdate(
                order_id=i, command_id=i, timestamp_ns=time.time_ns(),
                side=1, type=1, status=3, price=50000.0,
                original_quantity=1.0, filled_quantity=1.0,
                remaining_quantity=0.0, average_fill_price=50000.0,
                latency_us=50000.0, is_maker=True
            )
            validator.validate_execution(expected, actual)

        # 生成报告
        validator_report = validator.generate_report()
        anomaly_report = anomaly_detector.generate_report()

        assert 'timestamp' in validator_report
        assert 'statistics' in validator_report
        assert 'timestamp' in anomaly_report
        assert 'statistics' in anomaly_report


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
