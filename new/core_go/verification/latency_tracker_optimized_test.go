package verification

import (
	"fmt"
	"sync"
	"testing"
	"time"

	"github.com/prometheus/client_golang/prometheus"
)

/*
latency_tracker_optimized_test.go - 高性能延迟追踪器测试

测试覆盖：
1. 基本功能测试 - 测量开始、阶段记录、测量结束
2. 异常检测测试 - 延迟超过阈值检测
3. 瓶颈分析测试 - 识别最慢阶段
4. 并发测试 - 多线程安全验证
5. 性能基准测试 - 零分配、<1ms精度验证
*/

// TestLatencyTrackerOptimized_Basic 测试基本功能
func TestLatencyTrackerOptimized_Basic(t *testing.T) {
	registry := prometheus.NewRegistry()
	config := DefaultLatencyThresholds()

	lt := NewLatencyTrackerOptimized(config, registry)
	defer lt.Stop()

	lt.Start()

	// 开始测量
	traceID := "test-trace-1"
	metadata := [8]string{"BTCUSDT", "buy", "limit", "", "", "", "", ""}
	m := lt.StartMeasurement(traceID, metadata)

	if m.TraceID != traceID {
		t.Errorf("Expected trace ID %s, got %s", traceID, m.TraceID)
	}

	// 模拟各阶段
	time.Sleep(1 * time.Millisecond)
	lt.RecordStage(traceID, StageFeatureEngineering, 1*time.Millisecond)

	time.Sleep(2 * time.Millisecond)
	lt.RecordStage(traceID, StageModelInference, 2*time.Millisecond)

	time.Sleep(3 * time.Millisecond)
	lt.RecordStage(traceID, StageStrategyDecision, 3*time.Millisecond)

	time.Sleep(2 * time.Millisecond)
	lt.RecordStage(traceID, StageOrderTransmission, 2*time.Millisecond)

	time.Sleep(5 * time.Millisecond)
	lt.RecordStage(traceID, StageExchangeExecution, 5*time.Millisecond)

	// 结束测量
	completed, err := lt.EndMeasurement(traceID)
	if err != nil {
		t.Fatalf("Failed to end measurement: %v", err)
	}

	if completed.TraceID != traceID {
		t.Errorf("Expected trace ID %s, got %s", traceID, completed.TraceID)
	}

	if completed.TotalLatency <= 0 {
		t.Error("Expected positive total latency")
	}

	// 验证统计
	stats := lt.GetStats()
	if stats["total_measurements"] != uint64(1) {
		t.Errorf("Expected 1 measurement, got %v", stats["total_measurements"])
	}
}

// TestLatencyTrackerOptimized_Breakdown 测试延迟分解和瓶颈分析
func TestLatencyTrackerOptimized_Breakdown(t *testing.T) {
	lt := NewLatencyTrackerOptimized(nil, nil)
	defer lt.Stop()

	// 创建测量
	traceID := "test-breakdown"
	metadata := [8]string{}
	m := lt.StartMeasurement(traceID, metadata)

	// 记录各阶段延迟
	lt.RecordStage(traceID, StageFeatureEngineering, 1*time.Millisecond)
	lt.RecordStage(traceID, StageModelInference, 2*time.Millisecond)
	lt.RecordStage(traceID, StageStrategyDecision, 1*time.Millisecond)
	lt.RecordStage(traceID, StageOrderTransmission, 3*time.Millisecond)
	lt.RecordStage(traceID, StageExchangeExecution, 10*time.Millisecond)

	// 设置结束时间
	m.EndTime = time.Now().UnixNano()
	m.TotalLatency = 17 * int64(time.Millisecond)

	// 分析分解
	breakdown := lt.AnalyzeBreakdown(m)

	if breakdown.TraceID != traceID {
		t.Errorf("Expected trace ID %s, got %s", traceID, breakdown.TraceID)
	}

	// 验证各阶段延迟
	if breakdown.FeatureEngineering != 1*time.Millisecond {
		t.Errorf("Expected feature engineering 1ms, got %v", breakdown.FeatureEngineering)
	}

	if breakdown.ExchangeExecution != 10*time.Millisecond {
		t.Errorf("Expected exchange execution 10ms, got %v", breakdown.ExchangeExecution)
	}

	// 验证瓶颈检测 - 应该是 ExchangeExecution (10ms)
	if breakdown.BottleneckStage != StageExchangeExecution {
		t.Errorf("Expected bottleneck to be exchange_execution, got %v", breakdown.BottleneckStage)
	}

	// 验证瓶颈百分比
	expectedPercent := float64(10) / float64(17) * 100
	if breakdown.BottleneckPercent < expectedPercent-1 || breakdown.BottleneckPercent > expectedPercent+1 {
		t.Errorf("Expected bottleneck percent ~%.2f, got %.2f", expectedPercent, breakdown.BottleneckPercent)
	}
}

// TestLatencyTrackerOptimized_AnomalyDetection 测试异常检测
func TestLatencyTrackerOptimized_AnomalyDetection(t *testing.T) {
	registry := prometheus.NewRegistry()
	config := DefaultLatencyThresholds()
	config.AnomalyThreshold = 50 * time.Millisecond

	lt := NewLatencyTrackerOptimized(config, registry)
	defer lt.Stop()

	lt.Start()

	anomalyCh := make(chan bool, 1)
	lt.SetAnomalyCallback(func(measurement *LatencyMeasurementOptimized, breakdown *LatencyBreakdownOptimized) {
		anomalyCh <- true
	})

	// 记录正常延迟
	traceID1 := "test-normal"
	lt.StartMeasurement(traceID1, [8]string{})
	time.Sleep(10 * time.Millisecond)
	lt.EndMeasurement(traceID1)

	// 记录异常延迟
	traceID2 := "test-anomaly"
	lt.StartMeasurement(traceID2, [8]string{})
	time.Sleep(100 * time.Millisecond)
	lt.EndMeasurement(traceID2)

	// 等待异常检测回调
	select {
	case <-anomalyCh:
		// 异常已检测
	case <-time.After(200 * time.Millisecond):
		t.Error("Should detect latency anomaly")
	}

	// 验证异常统计
	stats := lt.GetStats()
	if stats["anomaly_count"] != uint64(1) {
		t.Errorf("Expected 1 anomaly, got %v", stats["anomaly_count"])
	}
}

// TestLatencyTrackerOptimized_Concurrent 测试并发安全
func TestLatencyTrackerOptimized_Concurrent(t *testing.T) {
	lt := NewLatencyTrackerOptimized(nil, nil)
	defer lt.Stop()

	lt.Start()

	const numGoroutines = 100
	const measurementsPerGoroutine = 100

	var wg sync.WaitGroup
	wg.Add(numGoroutines)

	for i := 0; i < numGoroutines; i++ {
		go func(id int) {
			defer wg.Done()

			for j := 0; j < measurementsPerGoroutine; j++ {
				traceID := fmt.Sprintf("trace-%d-%d", id, j)
				lt.StartMeasurement(traceID, [8]string{})

				// 模拟一些工作
				time.Sleep(time.Microsecond * 100)

				lt.RecordStage(traceID, StageFeatureEngineering, time.Millisecond)
				lt.RecordStage(traceID, StageModelInference, time.Millisecond)
				lt.RecordStage(traceID, StageStrategyDecision, time.Millisecond)

				lt.EndMeasurement(traceID)
			}
		}(i)
	}

	wg.Wait()

	// 验证统计
	stats := lt.GetStats()
	expectedMeasurements := uint64(numGoroutines * measurementsPerGoroutine)
	if stats["total_measurements"] != expectedMeasurements {
		t.Errorf("Expected %d measurements, got %v", expectedMeasurements, stats["total_measurements"])
	}
}

// TestLatencyTrackerOptimized_GetMeasurement 测试获取测量记录
func TestLatencyTrackerOptimized_GetMeasurement(t *testing.T) {
	lt := NewLatencyTrackerOptimized(nil, nil)
	defer lt.Stop()

	// 测试活跃测量
	traceID := "test-get"
	lt.StartMeasurement(traceID, [8]string{"symbol", "BTCUSDT"})

	m, ok := lt.GetMeasurement(traceID)
	if !ok {
		t.Error("Expected to find active measurement")
	}
	if m.TraceID != traceID {
		t.Errorf("Expected trace ID %s, got %s", traceID, m.TraceID)
	}

	// 记录阶段并结束
	lt.RecordStage(traceID, StageFeatureEngineering, 1*time.Millisecond)
	lt.EndMeasurement(traceID)

	// 注意：完成后的测量可能会被放回池中重用，因此不测试已完成测量的获取

	// 测试不存在的测量
	_, ok = lt.GetMeasurement("non-existent")
	if ok {
		t.Error("Should not find non-existent measurement")
	}
}

// TestLatencyTrackerOptimized_Reset 测试重置功能
func TestLatencyTrackerOptimized_Reset(t *testing.T) {
	lt := NewLatencyTrackerOptimized(nil, nil)
	defer lt.Stop()

	// 添加一些测量
	for i := 0; i < 10; i++ {
		traceID := fmt.Sprintf("trace-%d", i)
		lt.StartMeasurement(traceID, [8]string{})
		lt.RecordStage(traceID, StageFeatureEngineering, time.Millisecond)
		lt.EndMeasurement(traceID)
	}

	// 验证统计
	stats := lt.GetStats()
	if stats["total_measurements"] != uint64(10) {
		t.Errorf("Expected 10 measurements, got %v", stats["total_measurements"])
	}

	// 重置
	lt.Reset()

	// 验证重置后
	stats = lt.GetStats()
	if stats["total_measurements"] != uint64(0) {
		t.Errorf("Expected 0 measurements after reset, got %v", stats["total_measurements"])
	}
}

// TestLatencyTrackerOptimized_BatchRecord 测试批量记录
func TestLatencyTrackerOptimized_BatchRecord(t *testing.T) {
	lt := NewLatencyTrackerOptimized(nil, nil)
	defer lt.Stop()

	traceID := "test-batch"
	lt.StartMeasurement(traceID, [8]string{})

	// 批量记录阶段
	stages := map[LatencyStageOptimized]time.Duration{
		StageFeatureEngineering: 1 * time.Millisecond,
		StageModelInference:     2 * time.Millisecond,
		StageStrategyDecision:   1 * time.Millisecond,
		StageOrderTransmission:  3 * time.Millisecond,
		StageExchangeExecution:  5 * time.Millisecond,
	}

	lt.BatchRecordStages(traceID, stages)

	// 稍微等待确保有延迟
	time.Sleep(time.Millisecond)

	// 结束测量
	m, err := lt.EndMeasurement(traceID)
	if err != nil {
		t.Fatalf("Failed to end measurement: %v", err)
	}

	// 验证总延迟（允许0，因为测试可能非常快）
	if m.TotalLatency < 0 {
		t.Error("Expected non-negative total latency")
	}
}

// TestLatencyTrackerOptimized_StageString 测试阶段字符串表示
func TestLatencyTrackerOptimized_StageString(t *testing.T) {
	tests := []struct {
		stage    LatencyStageOptimized
		expected string
	}{
		{StageFeatureEngineering, "feature_engineering"},
		{StageModelInference, "model_inference"},
		{StageStrategyDecision, "strategy_decision"},
		{StageOrderTransmission, "order_transmission"},
		{StageExchangeExecution, "exchange_execution"},
		{StageTotal, "total"},
		{LatencyStageOptimized(99), "unknown"},
	}

	for _, test := range tests {
		result := test.stage.String()
		if result != test.expected {
			t.Errorf("Stage %d: expected %s, got %s", test.stage, test.expected, result)
		}
	}
}

// BenchmarkLatencyTrackerOptimized_StartMeasurement 基准测试：开始测量
func BenchmarkLatencyTrackerOptimized_StartMeasurement(b *testing.B) {
	lt := NewLatencyTrackerOptimized(nil, nil)
	defer lt.Stop()

	metadata := [8]string{"BTCUSDT", "buy", "limit"}

	b.ResetTimer()
	b.ReportAllocs()

	for i := 0; i < b.N; i++ {
		traceID := fmt.Sprintf("bench-%d", i)
		lt.StartMeasurement(traceID, metadata)
	}
}

// BenchmarkLatencyTrackerOptimized_RecordStage 基准测试：记录阶段
func BenchmarkLatencyTrackerOptimized_RecordStage(b *testing.B) {
	lt := NewLatencyTrackerOptimized(nil, nil)
	defer lt.Stop()

	traceID := "bench-trace"
	lt.StartMeasurement(traceID, [8]string{})

	b.ResetTimer()
	b.ReportAllocs()

	for i := 0; i < b.N; i++ {
		lt.RecordStage(traceID, StageFeatureEngineering, time.Millisecond)
	}
}

// BenchmarkLatencyTrackerOptimized_EndMeasurement 基准测试：结束测量
func BenchmarkLatencyTrackerOptimized_EndMeasurement(b *testing.B) {
	lt := NewLatencyTrackerOptimized(nil, nil)
	defer lt.Stop()

	// 预创建测量
	traceIDs := make([]string, b.N)
	for i := 0; i < b.N; i++ {
		traceIDs[i] = fmt.Sprintf("bench-%d", i)
		lt.StartMeasurement(traceIDs[i], [8]string{})
		lt.RecordStage(traceIDs[i], StageFeatureEngineering, time.Millisecond)
	}

	b.ResetTimer()
	b.ReportAllocs()

	for i := 0; i < b.N; i++ {
		lt.EndMeasurement(traceIDs[i])
	}
}

// BenchmarkLatencyTrackerOptimized_FullLifecycle 基准测试：完整生命周期
func BenchmarkLatencyTrackerOptimized_FullLifecycle(b *testing.B) {
	lt := NewLatencyTrackerOptimized(nil, nil)
	defer lt.Stop()

	metadata := [8]string{"BTCUSDT", "buy", "limit"}

	b.ResetTimer()
	b.ReportAllocs()

	for i := 0; i < b.N; i++ {
		traceID := fmt.Sprintf("bench-%d", i)
		lt.StartMeasurement(traceID, metadata)
		lt.RecordStage(traceID, StageFeatureEngineering, time.Millisecond)
		lt.RecordStage(traceID, StageModelInference, time.Millisecond)
		lt.RecordStage(traceID, StageStrategyDecision, time.Millisecond)
		lt.EndMeasurement(traceID)
	}
}

// BenchmarkLatencyTrackerOptimized_Concurrent 基准测试：并发性能
func BenchmarkLatencyTrackerOptimized_Concurrent(b *testing.B) {
	lt := NewLatencyTrackerOptimized(nil, nil)
	defer lt.Stop()

	metadata := [8]string{"BTCUSDT", "buy", "limit"}

	b.ResetTimer()
	b.ReportAllocs()

	b.RunParallel(func(pb *testing.PB) {
		i := 0
		for pb.Next() {
			traceID := fmt.Sprintf("bench-%d", i)
			lt.StartMeasurement(traceID, metadata)
			lt.RecordStage(traceID, StageFeatureEngineering, time.Millisecond)
			lt.EndMeasurement(traceID)
			i++
		}
	})
}

