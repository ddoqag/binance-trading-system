package main

import (
	"testing"
	"time"

	"github.com/prometheus/client_golang/prometheus/testutil"
)

// TestNewMetricsCollector tests creation of metrics collector
func TestNewMetricsCollector(t *testing.T) {
	config := DefaultMetricsConfig()
	config.Enabled = false // Don't start server in tests

	mc := NewMetricsCollector(config)
	if mc == nil {
		t.Fatal("Failed to create MetricsCollector")
	}

	if mc.config == nil {
		t.Error("Config should not be nil")
	}

	if mc.reg == nil {
		t.Error("Registry should not be nil")
	}

	t.Logf("✓ MetricsCollector creation test passed")
}

// TestMetricsRecordOrder tests order recording
func TestMetricsRecordOrder(t *testing.T) {
	config := DefaultMetricsConfig()
	config.Enabled = true

	mc := NewMetricsCollector(config)

	// Record some orders
	mc.RecordOrder("BTCUSDT", "BUY", "FILLED")
	mc.RecordOrder("BTCUSDT", "SELL", "FILLED")
	mc.RecordOrder("BTCUSDT", "BUY", "CANCELLED")

	// Verify metric was recorded
	counter, err := mc.ordersTotal.GetMetricWithLabelValues("BTCUSDT", "BUY", "FILLED")
	if err != nil {
		t.Errorf("Failed to get metric: %v", err)
	}

	// Check value
	if testutil.ToFloat64(counter) != 1 {
		t.Errorf("Expected counter value 1, got %f", testutil.ToFloat64(counter))
	}

	t.Logf("✓ Order recording test passed")
}

// TestMetricsRecordFill tests fill recording
func TestMetricsRecordFill(t *testing.T) {
	config := DefaultMetricsConfig()
	config.Enabled = true

	mc := NewMetricsCollector(config)

	// Record fills
	mc.RecordFill("BTCUSDT", "BUY", 0.5, 0.001)
	mc.RecordFill("BTCUSDT", "SELL", 0.3, 0.002)

	t.Logf("✓ Fill recording test passed")
}

// TestMetricsPnL tests PnL recording
func TestMetricsPnL(t *testing.T) {
	config := DefaultMetricsConfig()
	config.Enabled = true

	mc := NewMetricsCollector(config)

	// Set PnL values
	mc.SetUnrealizedPnL("BTCUSDT", 150.5)
	mc.SetRealizedPnL("BTCUSDT", 200.0)

	// Get gauge values
	gauge, _ := mc.unrealizedPnL.GetMetricWithLabelValues("BTCUSDT")
	if testutil.ToFloat64(gauge) != 150.5 {
		t.Errorf("Expected unrealized PnL 150.5, got %f", testutil.ToFloat64(gauge))
	}

	gauge, _ = mc.realizedPnL.GetMetricWithLabelValues("BTCUSDT")
	if testutil.ToFloat64(gauge) != 200.0 {
		t.Errorf("Expected realized PnL 200.0, got %f", testutil.ToFloat64(gauge))
	}

	t.Logf("✓ PnL recording test passed")
}

// TestMetricsPosition tests position metrics
func TestMetricsPosition(t *testing.T) {
	config := DefaultMetricsConfig()
	config.Enabled = true

	mc := NewMetricsCollector(config)

	// Set position metrics
	mc.SetPositionSize("BTCUSDT", "LONG", 0.5)
	mc.SetPositionCount(2)
	mc.SetOpenOrdersCount(5)

	// Verify
	if testutil.ToFloat64(mc.positionCount) != 2 {
		t.Errorf("Expected position count 2, got %f", testutil.ToFloat64(mc.positionCount))
	}

	if testutil.ToFloat64(mc.openOrdersCount) != 5 {
		t.Errorf("Expected open orders count 5, got %f", testutil.ToFloat64(mc.openOrdersCount))
	}

	t.Logf("✓ Position metrics test passed")
}

// TestMetricsMarketData tests market data metrics
func TestMetricsMarketData(t *testing.T) {
	config := DefaultMetricsConfig()
	config.Enabled = true

	mc := NewMetricsCollector(config)

	// Set market data
	mc.SetSpread("BTCUSDT", 10.5)
	mc.SetMidPrice("BTCUSDT", 50000.0)
	mc.SetVolatility("BTCUSDT", 0.02)
	mc.SetLastPrice("BTCUSDT", 50005.0)

	t.Logf("✓ Market data metrics test passed")
}

// TestMetricsDrawdown tests drawdown metrics
func TestMetricsDrawdown(t *testing.T) {
	config := DefaultMetricsConfig()
	config.Enabled = true

	mc := NewMetricsCollector(config)

	// Set drawdown
	mc.SetDailyDrawdown(0.05)  // 5%
	mc.SetMaxDrawdown(0.15)    // 15%

	if testutil.ToFloat64(mc.dailyDrawdown) != 0.05 {
		t.Errorf("Expected daily drawdown 0.05, got %f", testutil.ToFloat64(mc.dailyDrawdown))
	}

	if testutil.ToFloat64(mc.maxDrawdown) != 0.15 {
		t.Errorf("Expected max drawdown 0.15, got %f", testutil.ToFloat64(mc.maxDrawdown))
	}

	t.Logf("✓ Drawdown metrics test passed")
}

// TestMetricsMargin tests margin metrics
func TestMetricsMargin(t *testing.T) {
	config := DefaultMetricsConfig()
	config.Enabled = true

	mc := NewMetricsCollector(config)

	// Set margin metrics
	mc.SetMarginUsage(0.65)  // 65%
	mc.SetLeverage(3.0)      // 3x

	if testutil.ToFloat64(mc.marginUsage) != 0.65 {
		t.Errorf("Expected margin usage 0.65, got %f", testutil.ToFloat64(mc.marginUsage))
	}

	if testutil.ToFloat64(mc.leverage) != 3.0 {
		t.Errorf("Expected leverage 3.0, got %f", testutil.ToFloat64(mc.leverage))
	}

	t.Logf("✓ Margin metrics test passed")
}

// TestMetricsWebSocket tests WebSocket metrics
func TestMetricsWebSocket(t *testing.T) {
	config := DefaultMetricsConfig()
	config.Enabled = true

	mc := NewMetricsCollector(config)

	// Set connected
	mc.SetWebSocketConnected(true)
	if testutil.ToFloat64(mc.websocketConnected) != 1 {
		t.Errorf("Expected WebSocket connected 1, got %f", testutil.ToFloat64(mc.websocketConnected))
	}

	// Set disconnected
	mc.SetWebSocketConnected(false)
	if testutil.ToFloat64(mc.websocketConnected) != 0 {
		t.Errorf("Expected WebSocket connected 0, got %f", testutil.ToFloat64(mc.websocketConnected))
	}

	t.Logf("✓ WebSocket metrics test passed")
}

// TestMetricsAPI tests API metrics
func TestMetricsAPI(t *testing.T) {
	config := DefaultMetricsConfig()
	config.Enabled = true

	mc := NewMetricsCollector(config)

	// Record API calls
	mc.RecordAPIRequest("/api/v1/order", "200")
	mc.RecordAPIRequest("/api/v1/order", "200")
	mc.RecordAPIRequest("/api/v1/order", "429")

	mc.RecordAPIError("/api/v1/order", "rate_limit")
	mc.RecordAPILatency("/api/v1/order", 0.05)

	t.Logf("✓ API metrics test passed")
}

// TestMetricsRecovery tests recovery metrics
func TestMetricsRecovery(t *testing.T) {
	config := DefaultMetricsConfig()
	config.Enabled = true

	mc := NewMetricsCollector(config)

	// Record recovery metrics
	mc.RecordRecoveryAttempt("api_client", "restart")
	mc.RecordRecoverySuccess("api_client")
	mc.SetComponentHealth("api_client", HealthHealthy)

	t.Logf("✓ Recovery metrics test passed")
}

// TestMetricsDegradation tests degradation metrics
func TestMetricsDegradation(t *testing.T) {
	config := DefaultMetricsConfig()
	config.Enabled = true

	mc := NewMetricsCollector(config)

	// Set degradation metrics
	mc.SetDegradeLevel(LevelCautious)
	mc.SetCircuitBreakerState("api", BreakerStateOpen)
	mc.SetCircuitBreakerState("order", BreakerStateClosed)

	if testutil.ToFloat64(mc.degradeLevel) != float64(LevelCautious) {
		t.Errorf("Expected degrade level %d, got %f", LevelCautious, testutil.ToFloat64(mc.degradeLevel))
	}

	t.Logf("✓ Degradation metrics test passed")
}

// TestMetricsSystem tests system metrics collection
func TestMetricsSystem(t *testing.T) {
	config := DefaultMetricsConfig()
	config.Enabled = true

	mc := NewMetricsCollector(config)

	// System metrics are collected automatically
	// Just verify they're registered
	if mc.goroutines == nil {
		t.Error("Goroutines gauge should not be nil")
	}

	if mc.memoryUsage == nil {
		t.Error("Memory usage gauge should not be nil")
	}

	if mc.gcPauseNs == nil {
		t.Error("GC pause gauge should not be nil")
	}

	t.Logf("✓ System metrics test passed")
}

// TestMetricsDisabled tests disabled metrics
func TestMetricsDisabled(t *testing.T) {
	config := DefaultMetricsConfig()
	config.Enabled = false

	mc := NewMetricsCollector(config)

	// These should not panic when disabled
	mc.RecordOrder("BTCUSDT", "BUY", "FILLED")
	mc.SetPositionCount(5)
	mc.SetUnrealizedPnL("BTCUSDT", 100.0)

	t.Logf("✓ Disabled metrics test passed")
}

// TestMetricsStartStop tests server start/stop
func TestMetricsStartStop(t *testing.T) {
	config := DefaultMetricsConfig()
	config.Enabled = true
	config.Port = 19090  // Use non-standard port

	mc := NewMetricsCollector(config)

	// Start
	err := mc.Start()
	if err != nil {
		t.Fatalf("Failed to start metrics server: %v", err)
	}

	if !mc.IsRunning() {
		t.Error("Server should be running")
	}

	// Give server time to start
	time.Sleep(100 * time.Millisecond)

	// Stop
	err = mc.Stop()
	if err != nil {
		t.Errorf("Failed to stop metrics server: %v", err)
	}

	if mc.IsRunning() {
		t.Error("Server should not be running")
	}

	t.Logf("✓ Server start/stop test passed")
}

// TestDefaultMetricsConfig tests default configuration
func TestDefaultMetricsConfig(t *testing.T) {
	config := DefaultMetricsConfig()

	if !config.Enabled {
		t.Error("Metrics should be enabled by default")
	}

	if config.Port != 9090 {
		t.Errorf("Expected default port 9090, got %d", config.Port)
	}

	if config.Path != "/metrics" {
		t.Errorf("Expected default path /metrics, got %s", config.Path)
	}

	if config.Namespace != "hft" {
		t.Errorf("Expected default namespace hft, got %s", config.Namespace)
	}

	t.Logf("✓ Default config test passed")
}

// TestMetricsGetRegistry tests registry access
func TestMetricsGetRegistry(t *testing.T) {
	config := DefaultMetricsConfig()
	config.Enabled = false

	mc := NewMetricsCollector(config)

	reg := mc.GetRegistry()
	if reg == nil {
		t.Error("Registry should not be nil")
	}

	// Check if metrics are registered
	families, err := reg.Gather()
	if err != nil {
		t.Errorf("Failed to gather metrics: %v", err)
	}

	// Should have many metrics registered
	if len(families) == 0 {
		t.Error("Should have registered metrics")
	}

	t.Logf("✓ Registry access test passed, found %d metric families", len(families))
}
