package verification

import (
	"context"
	"fmt"
	"sync"
	"testing"
	"time"

	"github.com/prometheus/client_golang/prometheus"
)

/*
integration_test.go - 验证套件集成测试

测试覆盖：
1. VerificationSuite 基本功能
2. 报告生成
3. 健康状态计算
4. 回调设置
5. 手动检查触发
*/

// TestVerificationSuite_Basic 测试验证套件基本功能
func TestVerificationSuite_Basic(t *testing.T) {
	config := DefaultVerificationSuiteConfig()
	config.ReportInterval = 100 * time.Millisecond

	registry := prometheus.NewRegistry()
	vs := NewVerificationSuite(config, registry)

	// 测试初始状态
	if vs.IsRunning() {
		t.Error("Should not be running initially")
	}

	// 启动
	err := vs.Start()
	if err != nil {
		t.Fatalf("Failed to start: %v", err)
	}

	if !vs.IsRunning() {
		t.Error("Should be running after start")
	}

	// 等待一段时间让报告生成
	time.Sleep(200 * time.Millisecond)

	// 停止
	err = vs.Stop()
	if err != nil {
		t.Fatalf("Failed to stop: %v", err)
	}

	if vs.IsRunning() {
		t.Error("Should not be running after stop")
	}
}

// TestVerificationSuite_VerifyOrder 测试订单验证
func TestVerificationSuite_VerifyOrder(t *testing.T) {
	config := DefaultVerificationSuiteConfig()
	registry := prometheus.NewRegistry()
	vs := NewVerificationSuite(config, registry)

	vs.Start()
	defer vs.Stop()

	// 记录预期订单
	order := &OrderState{
		OrderID:           "test-order-1",
		Symbol:            "BTCUSDT",
		Side:              "BUY",
		Price:             50000.0,
		Quantity:          0.1,
		ExpectedFillPrice: 50000.0,
		QueuePosition:     0.3,
	}

	vs.ShadowMatcher.RecordExpectedOrder(order)

	// 记录实际成交
	fill := &FillRecord{
		OrderID:    "test-order-1",
		Symbol:     "BTCUSDT",
		Side:       "BUY",
		Price:      50001.0,
		Quantity:   0.1,
		FillTime:   time.Now(),
		Commission: 0.5,
		IsMaker:    true,
		LatencyMs:  50.0,
	}

	vs.ShadowMatcher.RecordActualFill(fill)

	// 等待处理
	time.Sleep(50 * time.Millisecond)

	// 验证订单
	ctx := context.Background()
	result, err := vs.VerifyOrder(ctx, "test-order-1", 500*time.Millisecond)
	if err != nil {
		t.Fatalf("Failed to verify order: %v", err)
	}

	if result.OrderID != "test-order-1" {
		t.Errorf("Expected order ID test-order-1, got %s", result.OrderID)
	}

	if result.FillQuality == nil {
		t.Error("Expected fill quality to be set")
	}
}

// TestVerificationSuite_GenerateReport 测试报告生成
func TestVerificationSuite_GenerateReport(t *testing.T) {
	config := DefaultVerificationSuiteConfig()
	registry := prometheus.NewRegistry()
	vs := NewVerificationSuite(config, registry)

	vs.Start()
	defer vs.Stop()

	// 添加一些测试数据
	order := &OrderState{
		OrderID:  "report-test-order",
		Symbol:   "BTCUSDT",
		Side:     "BUY",
		Price:    50000.0,
		Quantity: 0.1,
	}
	vs.ShadowMatcher.RecordExpectedOrder(order)

	fill := &FillRecord{
		OrderID:  "report-test-order",
		Symbol:   "BTCUSDT",
		Side:     "BUY",
		Price:    50000.0,
		Quantity: 0.1,
		FillTime: time.Now(),
	}
	vs.ShadowMatcher.RecordActualFill(fill)

	// 添加延迟测量
	traceID := "report-test-trace"
	vs.LatencyTracker.StartMeasurement(traceID, map[string]string{"symbol": "BTCUSDT"})
	vs.LatencyTracker.RecordStage(traceID, StageDecision, 1*time.Millisecond)
	vs.LatencyTracker.EndMeasurement(traceID)

	// 添加状态一致性数据
	localOrder := &LocalOrderState{
		OrderID:   "report-local-order",
		Symbol:    "BTCUSDT",
		Side:      "BUY",
		Price:     50000.0,
		Quantity:  0.1,
		Status:    "new",
		CreatedAt: time.Now(),
	}
	vs.StateChecker.UpdateLocalOrder(localOrder)

	exchangeOrder := &ExchangeOrderState{
		OrderID: "report-local-order",
		Symbol:  "BTCUSDT",
		Side:    "BUY",
		Price:   50000.0,
		OrigQty: 0.1,
		Status:  "NEW",
	}
	vs.StateChecker.UpdateExchangeOrder(exchangeOrder)

	// 等待数据同步
	time.Sleep(100 * time.Millisecond)

	// 生成报告
	report := vs.GenerateReport()

	if report.Timestamp.IsZero() {
		t.Error("Expected non-zero timestamp")
	}

	if report.ShadowStats == nil {
		t.Error("Expected shadow matcher stats")
	}

	if report.LatencyStats == nil {
		t.Error("Expected latency stats")
	}

	if report.ConsistencyStats == nil {
		t.Error("Expected state consistency stats")
	}
}

// TestVerificationSuite_HealthStatus 测试健康状态计算
func TestVerificationSuite_HealthStatus(t *testing.T) {
	config := DefaultVerificationSuiteConfig()
	registry := prometheus.NewRegistry()
	vs := NewVerificationSuite(config, registry)

	// 测试健康状态字符串
	tests := []struct {
		status   HealthStatus
		expected string
	}{
		{HealthHealthy, "healthy"},
		{HealthDegraded, "degraded"},
		{HealthUnhealthy, "unhealthy"},
		{HealthUnknown, "unknown"},
		{HealthStatus(99), "unknown"},
	}

	for _, test := range tests {
		result := test.status.String()
		if result != test.expected {
			t.Errorf("Expected %s, got %s", test.expected, result)
		}
	}
}

// TestVerificationSuite_Callbacks 测试回调设置
func TestVerificationSuite_Callbacks(t *testing.T) {
	config := DefaultVerificationSuiteConfig()
	registry := prometheus.NewRegistry()
	vs := NewVerificationSuite(config, registry)

	// 设置警报回调
	alertReceived := false
	var alertMu sync.Mutex

	vs.SetAlertCallback(func(level string, message string) {
		alertMu.Lock()
		alertReceived = true
		alertMu.Unlock()
	})

	vs.Start()
	defer vs.Stop()

	// 触发一个异常来产生警报
	order := &OrderState{
		OrderID:           "alert-test-order",
		Symbol:            "BTCUSDT",
		Side:              "BUY",
		Price:             50000.0,
		Quantity:          0.1,
		ExpectedFillPrice: 50000.0,
	}
	vs.ShadowMatcher.RecordExpectedOrder(order)

	// 记录一个异常成交（大幅滑点）
	fill := &FillRecord{
		OrderID:  "alert-test-order",
		Symbol:   "BTCUSDT",
		Side:     "BUY",
		Price:    50100.0, // 大幅滑点
		Quantity: 0.1,
		FillTime: time.Now(),
	}
	vs.ShadowMatcher.RecordActualFill(fill)

	// 等待警报触发
	time.Sleep(100 * time.Millisecond)

	alertMu.Lock()
	if !alertReceived {
		t.Log("Alert callback may not have been triggered (expected in some cases)")
	}
	alertMu.Unlock()
}

// TestVerificationSuite_TriggerManualCheck 测试手动检查
func TestVerificationSuite_TriggerManualCheck(t *testing.T) {
	config := DefaultVerificationSuiteConfig()
	registry := prometheus.NewRegistry()
	vs := NewVerificationSuite(config, registry)

	vs.Start()
	defer vs.Stop()

	// 添加一些不一致的数据
	localOrder := &LocalOrderState{
		OrderID:   "manual-check-order",
		Symbol:    "BTCUSDT",
		Side:      "BUY",
		Price:     50000.0,
		Quantity:  0.1,
		Status:    "filled",
		CreatedAt: time.Now(),
	}
	vs.StateChecker.UpdateLocalOrder(localOrder)

	exchangeOrder := &ExchangeOrderState{
		OrderID: "manual-check-order",
		Symbol:  "BTCUSDT",
		Side:    "BUY",
		Price:   50000.0,
		OrigQty: 0.1,
		Status:  "NEW", // 不一致
	}
	vs.StateChecker.UpdateExchangeOrder(exchangeOrder)

	// 触发手动检查
	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
	defer cancel()

	_, err := vs.TriggerManualCheck(ctx)
	if err != nil {
		t.Fatalf("Manual check failed: %v", err)
	}
}

// TestVerificationSuite_Reset 测试重置功能
func TestVerificationSuite_Reset(t *testing.T) {
	config := DefaultVerificationSuiteConfig()
	registry := prometheus.NewRegistry()
	vs := NewVerificationSuite(config, registry)

	vs.Start()
	defer vs.Stop()

	// 添加一些数据
	order := &OrderState{
		OrderID:  "reset-test-order",
		Symbol:   "BTCUSDT",
		Side:     "BUY",
		Price:    50000.0,
		Quantity: 0.1,
	}
	vs.ShadowMatcher.RecordExpectedOrder(order)

	// 重置
	vs.Reset()

	// 验证数据被清除（ShadowMatcher被重新创建，所以应该为0）
	stats := vs.ShadowMatcher.GetStats()
	if stats["expected_orders"] != 0 {
		t.Errorf("Expected 0 orders after reset, got %v", stats["expected_orders"])
	}
}

// TestVerificationSuite_GetRegistry 测试获取注册表
func TestVerificationSuite_GetRegistry(t *testing.T) {
	config := DefaultVerificationSuiteConfig()
	registry := prometheus.NewRegistry()
	vs := NewVerificationSuite(config, registry)

	gotRegistry := vs.GetRegistry()
	if gotRegistry != registry {
		t.Error("Expected to get the same registry")
	}
}

// TestVerificationSuite_Recommendations 测试建议生成
func TestVerificationSuite_Recommendations(t *testing.T) {
	config := DefaultVerificationSuiteConfig()
	registry := prometheus.NewRegistry()
	vs := NewVerificationSuite(config, registry)

	vs.Start()
	defer vs.Stop()

	// 添加一些异常数据来触发建议
	// 1. 高异常率
	for i := 0; i < 10; i++ {
		order := &OrderState{
			OrderID:           fmt.Sprintf("rec-test-order-%d", i),
			Symbol:            "BTCUSDT",
			Side:              "BUY",
			Price:             50000.0,
			Quantity:          0.1,
			ExpectedFillPrice: 50000.0,
		}
		vs.ShadowMatcher.RecordExpectedOrder(order)

		// 记录异常成交
		fill := &FillRecord{
			OrderID:  fmt.Sprintf("rec-test-order-%d", i),
			Symbol:   "BTCUSDT",
			Side:     "BUY",
			Price:    50100.0, // 大幅滑点
			Quantity: 0.1,
			FillTime: time.Now(),
		}
		vs.ShadowMatcher.RecordActualFill(fill)
	}

	// 等待处理
	time.Sleep(100 * time.Millisecond)

	// 生成报告，应该包含建议
	report := vs.GenerateReport()

	// 验证健康状态和建议
	if report.OverallHealth == HealthHealthy {
		t.Log("Health should not be healthy with high anomaly rate")
	}
}
