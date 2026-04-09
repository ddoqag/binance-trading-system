package verification

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/prometheus/client_golang/prometheus"
)

/*
verification_test.go - 执行层真实性检验套件测试

测试覆盖：
1. ShadowMatcher - 订单影子匹配验证
2. LatencyTracker - 延迟测量与归因
3. StateConsistencyChecker - 状态一致性检查
*/

// TestShadowMatcher_Basic 测试影子匹配器基本功能
func TestShadowMatcher_Basic(t *testing.T) {
	registry := prometheus.NewRegistry()
	config := DefaultShadowMatcherConfig()
	config.RetentionPeriod = 1 * time.Minute

	sm := NewShadowMatcher(config, registry)
	defer sm.Stop()

	sm.Start()

	// 记录预期订单
	order := &OrderState{
		OrderID:           "test-order-1",
		Symbol:            "BTCUSDT",
		Side:              "BUY",
		Price:             50000.0,
		Quantity:          0.1,
		ExpectedFillPrice: 50000.0,
		ExpectedFillTime:  time.Now().Add(100 * time.Millisecond),
		QueuePosition:     0.3,
	}

	sm.RecordExpectedOrder(order)

	// 记录实际成交
	fill := &FillRecord{
		OrderID:    "test-order-1",
		Symbol:     "BTCUSDT",
		Side:       "BUY",
		Price:      50001.0, // 轻微滑点
		Quantity:   0.1,
		FillTime:   time.Now(),
		Commission: 0.5,
		IsMaker:    true,
		LatencyMs:  50.0,
	}

	sm.RecordActualFill(fill)

	// 等待处理
	time.Sleep(50 * time.Millisecond)

	// 验证质量分析
	quality, ok := sm.GetFillQuality("test-order-1")
	if !ok {
		t.Fatal("Expected fill quality to be available")
	}

	if quality.OrderID != "test-order-1" {
		t.Errorf("Expected order ID test-order-1, got %s", quality.OrderID)
	}

	// 滑点应该在可接受范围内
	if quality.SlippageBPS < 0 || quality.SlippageBPS > 1 {
		t.Errorf("Unexpected slippage: %.2f bps", quality.SlippageBPS)
	}

	// 质量分数应该较高
	if quality.QualityScore < 0.8 {
		t.Errorf("Quality score too low: %.2f", quality.QualityScore)
	}

	// 不应该检测到异常
	if quality.AnomalyDetected {
		t.Error("Should not detect anomaly for normal fill")
	}
}

// TestShadowMatcher_AnomalyDetection 测试异常检测
func TestShadowMatcher_AnomalyDetection(t *testing.T) {
	registry := prometheus.NewRegistry()
	config := DefaultShadowMatcherConfig()
	config.MaxPriceDeviationBPS = 5.0 // 严格阈值

	sm := NewShadowMatcher(config, registry)
	defer sm.Stop()

	// 记录预期订单
	order := &OrderState{
		OrderID:           "test-order-anomaly",
		Symbol:            "BTCUSDT",
		Side:              "BUY",
		Price:             50000.0,
		Quantity:          0.1,
		ExpectedFillPrice: 50000.0,
		QueuePosition:     0.3,
	}

	sm.RecordExpectedOrder(order)

	// 记录异常成交（大幅滑点）
	fill := &FillRecord{
		OrderID:    "test-order-anomaly",
		Symbol:     "BTCUSDT",
		Side:       "BUY",
		Price:      50100.0, // 100点滑点 = 20bps
		Quantity:   0.1,
		FillTime:   time.Now(),
		Commission: 0.5,
		IsMaker:    false,
		LatencyMs:  500.0,
	}

	sm.RecordActualFill(fill)

	// 验证异常检测
	quality, ok := sm.GetFillQuality("test-order-anomaly")
	if !ok {
		t.Fatal("Expected fill quality to be available")
	}

	if !quality.AnomalyDetected {
		t.Error("Should detect anomaly for large slippage")
	}

	if quality.SlippageBPS < 15 {
		t.Errorf("Expected large slippage, got %.2f bps", quality.SlippageBPS)
	}

	// 质量分数应该较低
	if quality.QualityScore > 0.5 {
		t.Errorf("Expected low quality score, got %.2f", quality.QualityScore)
	}
}

// TestShadowMatcher_Stats 测试统计功能
func TestShadowMatcher_Stats(t *testing.T) {
	sm := NewShadowMatcher(nil, nil)
	defer sm.Stop()

	// 添加多个订单
	for i := 0; i < 5; i++ {
		order := &OrderState{
			OrderID:  fmt.Sprintf("order-%d", i),
			Symbol:   "BTCUSDT",
			Side:     "BUY",
			Price:    50000.0,
			Quantity: 0.1,
		}
		sm.RecordExpectedOrder(order)

		fill := &FillRecord{
			OrderID:  fmt.Sprintf("order-%d", i),
			Symbol:   "BTCUSDT",
			Side:     "BUY",
			Price:    50000.0,
			Quantity: 0.1,
			FillTime: time.Now(),
		}
		sm.RecordActualFill(fill)
	}

	stats := sm.GetStats()

	if stats["expected_orders"] != 5 {
		t.Errorf("Expected 5 orders, got %v", stats["expected_orders"])
	}

	if stats["actual_fills"] != 5 {
		t.Errorf("Expected 5 fills, got %v", stats["actual_fills"])
	}
}

// TestLatencyTracker_Basic 测试延迟追踪器基本功能
func TestLatencyTracker_Basic(t *testing.T) {
	registry := prometheus.NewRegistry()
	config := DefaultLatencyTrackerConfig()

	lt := NewLatencyTracker(config, registry)
	defer lt.Stop()

	lt.Start()

	// 开始测量
	traceID := "test-trace-1"
	_ = lt.StartMeasurement(traceID, map[string]string{"symbol": "BTCUSDT"})

	// 模拟各阶段
	time.Sleep(1 * time.Millisecond)
	lt.RecordStage(traceID, StageDecision, 1*time.Millisecond)

	time.Sleep(2 * time.Millisecond)
	lt.RecordStage(traceID, StageNetworkSend, 2*time.Millisecond)

	time.Sleep(5 * time.Millisecond)
	lt.RecordStage(traceID, StageExchangeProcess, 5*time.Millisecond)

	time.Sleep(2 * time.Millisecond)
	lt.RecordStage(traceID, StageNetworkRecv, 2*time.Millisecond)

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

	// 验证各阶段记录
	if len(completed.Stages) != 4 {
		t.Errorf("Expected 4 stages, got %d", len(completed.Stages))
	}
}

// TestLatencyTracker_Breakdown 测试延迟分解
func TestLatencyTracker_Breakdown(t *testing.T) {
	lt := NewLatencyTracker(nil, nil)
	defer lt.Stop()

	// 创建测量
	traceID := "test-breakdown"
	m := &LatencyMeasurement{
		TraceID:   traceID,
		StartTime: time.Now(),
		Stages: map[LatencyStage]time.Duration{
			StageDecision:        1 * time.Millisecond,
			StageSerialization:   1 * time.Millisecond,
			StageNetworkSend:     2 * time.Millisecond,
			StageExchangeProcess: 10 * time.Millisecond,
			StageNetworkRecv:     2 * time.Millisecond,
			StageExecution:       1 * time.Millisecond,
		},
		TotalLatency: 17 * time.Millisecond,
	}

	breakdown := lt.AnalyzeBreakdown(m)

	if breakdown.TraceID != traceID {
		t.Errorf("Expected trace ID %s, got %s", traceID, breakdown.TraceID)
	}

	// 验证延迟分解
	expectedInternal := 3 * time.Millisecond // 1 + 1 + 1
	if breakdown.InternalLatency != expectedInternal {
		t.Errorf("Expected internal latency %v, got %v", expectedInternal, breakdown.InternalLatency)
	}

	expectedNetwork := 4 * time.Millisecond // 2 + 2
	if breakdown.NetworkLatency != expectedNetwork {
		t.Errorf("Expected network latency %v, got %v", expectedNetwork, breakdown.NetworkLatency)
	}

	if breakdown.ExchangeLatency != 10*time.Millisecond {
		t.Errorf("Expected exchange latency 10ms, got %v", breakdown.ExchangeLatency)
	}

	// 验证瓶颈检测
	if breakdown.BottleneckStage != StageExchangeProcess {
		t.Errorf("Expected bottleneck to be exchange_process, got %v", breakdown.BottleneckStage)
	}
}

// TestLatencyTracker_AnomalyDetection 测试延迟异常检测
func TestLatencyTracker_AnomalyDetection(t *testing.T) {
	registry := prometheus.NewRegistry()
	config := DefaultLatencyTrackerConfig()
	config.AnomalyThreshold = 50 * time.Millisecond

	lt := NewLatencyTracker(config, registry)
	defer lt.Stop()

	lt.Start()

	anomalyCh := make(chan bool, 1)
	lt.SetAnomalyCallback(func(measurement *LatencyMeasurement, breakdown *LatencyBreakdown) {
		anomalyCh <- true
	})

	// 记录异常延迟
	traceID := "test-anomaly"
	lt.StartMeasurement(traceID, nil)
	time.Sleep(100 * time.Millisecond)
	lt.EndMeasurement(traceID)

	// 等待处理
	select {
	case <-anomalyCh:
		// 异常已检测
	case <-time.After(100 * time.Millisecond):
		t.Error("Should detect latency anomaly")
	}

	// 验证异常记录
	anomalies := lt.GetAnomalies(10)
	if len(anomalies) == 0 {
		t.Error("Expected anomalies to be recorded")
	}
}

// TestLatencyTracker_Percentiles 测试百分位数计算
func TestLatencyTracker_Percentiles(t *testing.T) {
	lt := NewLatencyTracker(nil, nil)
	defer lt.Stop()

	// 添加多个测量
	for i := 0; i < 100; i++ {
		traceID := fmt.Sprintf("trace-%d", i)
		m := &LatencyMeasurement{
			TraceID:      traceID,
			StartTime:    time.Now(),
			EndTime:      time.Now().Add(time.Duration(i) * time.Millisecond),
			TotalLatency: time.Duration(i) * time.Millisecond,
			Stages:       make(map[LatencyStage]time.Duration),
		}

		lt.completedMu.Lock()
		lt.completedMeasurements = append(lt.completedMeasurements, m)
		lt.completedMu.Unlock()
	}

	percentiles := lt.GetPercentiles()

	if percentiles["p50"] == 0 {
		t.Error("Expected p50 to be calculated")
	}

	if percentiles["p90"] == 0 {
		t.Error("Expected p90 to be calculated")
	}
}

// TestStateConsistency_Basic 测试状态一致性检查器基本功能
func TestStateConsistency_Basic(t *testing.T) {
	registry := prometheus.NewRegistry()
	config := DefaultStateConsistencyConfig()
	config.CheckInterval = 100 * time.Millisecond

	sc := NewStateConsistencyChecker(config, registry)
	defer sc.Stop()

	sc.Start()

	// 更新本地订单
	localOrder := &LocalOrderState{
		OrderID:        "order-1",
		Symbol:         "BTCUSDT",
		Side:           "BUY",
		Price:          50000.0,
		Quantity:       0.1,
		FilledQuantity: 0.0,
		Status:         "new",
		CreatedAt:      time.Now(),
	}
	sc.UpdateLocalOrder(localOrder)

	// 更新交易所订单（一致）
	exchangeOrder := &ExchangeOrderState{
		OrderID:     "order-1",
		Symbol:      "BTCUSDT",
		Side:        "BUY",
		Price:       50000.0,
		OrigQty:     0.1,
		ExecutedQty: 0.0,
		Status:      "NEW",
	}
	sc.UpdateExchangeOrder(exchangeOrder)

	// 等待检查
	time.Sleep(150 * time.Millisecond)

	// 验证没有差异
	diffs := sc.GetDiffs()
	if len(diffs) > 0 {
		t.Errorf("Expected no diffs for consistent state, got %d", len(diffs))
	}
}

// TestStateConsistency_StatusMismatch 测试状态不一致检测
func TestStateConsistency_StatusMismatch(t *testing.T) {
	sc := NewStateConsistencyChecker(nil, nil)
	defer sc.Stop()

	diffDetected := false
	sc.SetDiffCallback(func(diff StateDiff) {
		if diff.DiffType == DiffTypeStatus {
			diffDetected = true
		}
	})

	// 更新本地订单
	localOrder := &LocalOrderState{
		OrderID:        "order-mismatch",
		Symbol:         "BTCUSDT",
		Side:           "BUY",
		Price:          50000.0,
		Quantity:       0.1,
		FilledQuantity: 0.0,
		Status:         "filled", // 本地认为已成交
		CreatedAt:      time.Now(),
	}
	sc.UpdateLocalOrder(localOrder)

	// 更新交易所订单（不一致）
	exchangeOrder := &ExchangeOrderState{
		OrderID:     "order-mismatch",
		Symbol:      "BTCUSDT",
		Side:        "BUY",
		Price:       50000.0,
		OrigQty:     0.1,
		ExecutedQty: 0.0,
		Status:      "NEW", // 交易所仍为NEW
	}
	sc.UpdateExchangeOrder(exchangeOrder)

	// 手动触发检查
	sc.performCheck()

	if !diffDetected {
		t.Error("Should detect status mismatch")
	}

	// 验证差异记录
	diffs := sc.GetDiffs()
	if len(diffs) == 0 {
		t.Fatal("Expected diffs to be recorded")
	}

	diff := diffs[0]
	if diff.DiffType != DiffTypeStatus {
		t.Errorf("Expected diff type status_mismatch, got %v", diff.DiffType)
	}

	if diff.Severity != SeverityCritical {
		t.Errorf("Expected critical severity for status mismatch, got %v", diff.Severity)
	}
}

// TestStateConsistency_PositionMismatch 测试仓位不一致检测
func TestStateConsistency_PositionMismatch(t *testing.T) {
	sc := NewStateConsistencyChecker(nil, nil)
	defer sc.Stop()

	// 更新本地仓位
	localPos := &PositionState{
		Symbol:      "BTCUSDT",
		PositionAmt: 1.0,
		EntryPrice:  50000.0,
	}
	sc.UpdateLocalPosition(localPos)

	// 更新交易所仓位（不一致）
	exchangePos := &PositionState{
		Symbol:      "BTCUSDT",
		PositionAmt: 0.5, // 仓位不一致
		EntryPrice:  50000.0,
	}
	sc.UpdateExchangePosition(exchangePos)

	// 手动触发检查
	sc.performCheck()

	// 验证差异
	diffs := sc.GetDiffs()
	if len(diffs) == 0 {
		t.Fatal("Expected position diff to be detected")
	}

	found := false
	for _, diff := range diffs {
		if diff.Field == "position_amount" {
			found = true
			if diff.Severity != SeverityHigh && diff.Severity != SeverityCritical {
				t.Errorf("Expected high/critical severity for position mismatch, got %v", diff.Severity)
			}
		}
	}

	if !found {
		t.Error("Expected position amount diff to be recorded")
	}
}

// TestStateConsistency_OrphanOrder 测试孤儿订单检测
func TestStateConsistency_OrphanOrder(t *testing.T) {
	sc := NewStateConsistencyChecker(nil, nil)
	defer sc.Stop()

	// 只在交易所有订单，本地没有
	exchangeOrder := &ExchangeOrderState{
		OrderID:     "orphan-order",
		Symbol:      "BTCUSDT",
		Side:        "SELL",
		Price:       51000.0,
		OrigQty:     0.1,
		ExecutedQty: 0.0,
		Status:      "NEW",
	}
	sc.UpdateExchangeOrder(exchangeOrder)

	// 手动触发检查
	sc.performCheck()

	// 验证孤儿订单检测
	diffs := sc.GetDiffs()
	found := false
	for _, diff := range diffs {
		if diff.DiffType == DiffTypeOrphan {
			found = true
			if diff.OrderID != "orphan-order" {
				t.Errorf("Expected orphan order ID orphan-order, got %s", diff.OrderID)
			}
		}
	}

	if !found {
		t.Error("Should detect orphan order")
	}
}

// TestStateConsistency_Stats 测试统计功能
func TestStateConsistency_Stats(t *testing.T) {
	sc := NewStateConsistencyChecker(nil, nil)
	defer sc.Stop()

	// 添加订单和仓位
	for i := 0; i < 5; i++ {
		order := &LocalOrderState{
			OrderID:   fmt.Sprintf("order-%d", i),
			Symbol:    "BTCUSDT",
			Status:    "new",
			CreatedAt: time.Now(),
		}
		sc.UpdateLocalOrder(order)

		exchangeOrder := &ExchangeOrderState{
			OrderID: fmt.Sprintf("order-%d", i),
			Symbol:  "BTCUSDT",
			Status:  "NEW",
		}
		sc.UpdateExchangeOrder(exchangeOrder)
	}

	sc.UpdateLocalPosition(&PositionState{Symbol: "BTCUSDT", PositionAmt: 1.0})
	sc.UpdateExchangePosition(&PositionState{Symbol: "BTCUSDT", PositionAmt: 1.0})

	stats := sc.GetStats()

	if stats["local_orders"] != 5 {
		t.Errorf("Expected 5 local orders, got %v", stats["local_orders"])
	}

	if stats["exchange_orders"] != 5 {
		t.Errorf("Expected 5 exchange orders, got %v", stats["exchange_orders"])
	}
}

// TestStateConsistency_TriggerManualCheck 测试手动检查
func TestStateConsistency_TriggerManualCheck(t *testing.T) {
	sc := NewStateConsistencyChecker(nil, nil)
	defer sc.Stop()

	// 添加不一致的订单
	sc.UpdateLocalOrder(&LocalOrderState{
		OrderID:   "manual-test",
		Symbol:    "BTCUSDT",
		Status:    "filled",
		CreatedAt: time.Now(),
	})

	sc.UpdateExchangeOrder(&ExchangeOrderState{
		OrderID: "manual-test",
		Symbol:  "BTCUSDT",
		Status:  "NEW",
	})

	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
	defer cancel()

	err := sc.TriggerManualCheck(ctx)
	if err != nil {
		t.Fatalf("Manual check failed: %v", err)
	}

	// 验证差异被检测
	diffs := sc.GetDiffs()
	if len(diffs) == 0 {
		t.Error("Expected diffs after manual check")
	}
}

// BenchmarkShadowMatcher_RecordFill 基准测试
func BenchmarkShadowMatcher_RecordFill(b *testing.B) {
	sm := NewShadowMatcher(nil, nil)
	defer sm.Stop()

	order := &OrderState{
		OrderID:           "bench-order",
		Symbol:            "BTCUSDT",
		Side:              "BUY",
		Price:             50000.0,
		Quantity:          0.1,
		ExpectedFillPrice: 50000.0,
	}
	sm.RecordExpectedOrder(order)

	fill := &FillRecord{
		OrderID:  "bench-order",
		Symbol:   "BTCUSDT",
		Side:     "BUY",
		Price:    50000.0,
		Quantity: 0.1,
		FillTime: time.Now(),
	}

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		fill.OrderID = fmt.Sprintf("bench-order-%d", i)
		sm.RecordActualFill(fill)
	}
}

// BenchmarkLatencyTracker_RecordStage 基准测试
func BenchmarkLatencyTracker_RecordStage(b *testing.B) {
	lt := NewLatencyTracker(nil, nil)
	defer lt.Stop()

	traceID := "bench-trace"
	lt.StartMeasurement(traceID, nil)

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		lt.RecordStage(traceID, StageDecision, 1*time.Millisecond)
	}
}

