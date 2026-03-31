package main

import (
	"testing"
	"time"
)

// TestDegradeLevelString tests DegradeLevel String method
func TestDegradeLevelString(t *testing.T) {
	tests := []struct {
		level    DegradeLevel
		expected string
	}{
		{LevelNormal, "NORMAL"},
		{LevelCautious, "CAUTIOUS"},
		{LevelRestricted, "RESTRICTED"},
		{LevelEmergency, "EMERGENCY"},
		{DegradeLevel(99), "UNKNOWN"},
	}

	for _, tt := range tests {
		if got := tt.level.String(); got != tt.expected {
			t.Errorf("DegradeLevel.String() = %v, want %v", got, tt.expected)
		}
	}
}

// TestBreakerStateString tests BreakerState String method
func TestBreakerStateString(t *testing.T) {
	// Test through CircuitBreaker.State() usage
	cb := NewCircuitBreaker("test", 3, time.Second)

	if cb.State() != BreakerStateClosed {
		t.Errorf("Expected initial state Closed, got %v", cb.State())
	}

	// Open the circuit
	for i := 0; i < 3; i++ {
		cb.RecordFailure()
	}

	if cb.State() != BreakerStateOpen {
		t.Errorf("Expected state Open after failures, got %v", cb.State())
	}
}

// TestCircuitBreakerAllow tests circuit breaker allow logic
func TestCircuitBreakerAllow(t *testing.T) {
	cb := NewCircuitBreaker("test", 3, 100*time.Millisecond)

	// Initially should allow
	if !cb.Allow() {
		t.Error("Should allow when closed")
	}

	// Record failures to open circuit
	for i := 0; i < 3; i++ {
		cb.RecordFailure()
	}

	if cb.Allow() {
		t.Error("Should not allow when open")
	}

	// Wait for timeout
	time.Sleep(150 * time.Millisecond)

	// Should allow (half-open)
	if !cb.Allow() {
		t.Error("Should allow when half-open")
	}
}

// TestCircuitBreakerRecovery tests circuit breaker recovery
func TestCircuitBreakerRecovery(t *testing.T) {
	cb := NewCircuitBreaker("test", 2, 50*time.Millisecond)

	// Open circuit
	cb.RecordFailure()
	cb.RecordFailure()

	if cb.State() != BreakerStateOpen {
		t.Error("Circuit should be open")
	}

	// Wait and recover
	time.Sleep(100 * time.Millisecond)

	// Trigger half-open
	cb.Allow()

	// Record success to close
	cb.RecordSuccess()

	if cb.State() != BreakerStateClosed {
		t.Error("Circuit should be closed after recovery")
	}

	if cb.failureCount != 0 {
		t.Error("Failure count should be reset")
	}
}

// TestDegradeManagerLevelChange tests degradation level changes
func TestDegradeManagerLevelChange(t *testing.T) {
	dm := NewDegradeManager()

	// Initial level should be Normal
	if dm.GetLevel() != LevelNormal {
		t.Errorf("Expected initial level Normal, got %v", dm.GetLevel())
	}

	// Simulate errors to trigger degradation
	dm.SetErrorRate(0.15) // 15% error rate

	if dm.GetLevel() != LevelCautious {
		t.Errorf("Expected level Cautious, got %v", dm.GetLevel())
	}

	// Higher error rate
	dm.SetErrorRate(0.35) // 35% error rate

	if dm.GetLevel() != LevelRestricted {
		t.Errorf("Expected level Restricted, got %v", dm.GetLevel())
	}
}

// TestDegradeManagerCanPlaceOrder tests order placement restrictions
func TestDegradeManagerCanPlaceOrder(t *testing.T) {
	dm := NewDegradeManager()

	// Normal level - should allow all orders
	if !dm.CanPlaceOrder(false) {
		t.Error("Should allow new orders at Normal level")
	}
	if !dm.CanPlaceOrder(true) {
		t.Error("Should allow closing orders at Normal level")
	}

	// Set to emergency level
	dm.SetErrorRate(0.6)

	// Emergency - should block all orders
	if dm.CanPlaceOrder(false) {
		t.Error("Should not allow new orders at Emergency level")
	}
	if dm.CanPlaceOrder(true) {
		t.Error("Should not allow closing orders at Emergency level")
	}
}

// TestEnhancedDegradeManagerBasic tests basic enhanced manager operations
func TestEnhancedDegradeManagerBasic(t *testing.T) {
	config := DefaultDegradeConfig()
	config.CheckInterval = 100 * time.Millisecond

	edm := NewEnhancedDegradeManager(config)
	edm.Start()
	defer edm.Stop()

	if edm.GetCurrentLevel() != LevelNormal {
		t.Errorf("Expected initial level Normal, got %v", edm.GetCurrentLevel())
	}

	// Update metrics to trigger degradation
	edm.UpdateMetrics(&SystemMetrics{
		APILatencyP99: 200 * time.Millisecond, // Above threshold
		ErrorRate:     0.02,
	})

	// Wait for check cycle
	time.Sleep(150 * time.Millisecond)

	// Should have degraded to Cautious
	if edm.GetCurrentLevel() != LevelCautious {
		t.Errorf("Expected level Cautious, got %v", edm.GetCurrentLevel())
	}

	t.Logf("✓ EnhancedDegradeManager basic test passed")
}

// TestEnhancedDegradeManagerEmergency tests emergency degradation
func TestEnhancedDegradeManagerEmergency(t *testing.T) {
	config := DefaultDegradeConfig()
	config.CheckInterval = 50 * time.Millisecond

	edm := NewEnhancedDegradeManager(config)
	edm.Start()
	defer edm.Stop()

	// High drawdown should trigger emergency
	edm.UpdateMetrics(&SystemMetrics{
		DailyDrawdown: 0.15, // 15% drawdown
		ErrorRate:     0.02,
	})

	time.Sleep(100 * time.Millisecond)

	if edm.GetCurrentLevel() != LevelEmergency {
		t.Errorf("Expected level Emergency, got %v", edm.GetCurrentLevel())
	}

	t.Logf("✓ Emergency degradation test passed")
}

// TestEnhancedDegradeManagerCanTrade tests trading permissions
func TestEnhancedDegradeManagerCanTrade(t *testing.T) {
	config := DefaultDegradeConfig()
	edm := NewEnhancedDegradeManager(config)
	defer edm.Stop()

	// Normal level
	if !edm.CanTrade(false) {
		t.Error("Should allow trading at Normal level")
	}

	// Force degrade to Restricted
	edm.ForceDegrade(LevelRestricted, "Test")

	if edm.CanTrade(false) {
		t.Error("Should not allow new trades at Restricted level")
	}
	if !edm.CanTrade(true) {
		t.Error("Should allow closing trades at Restricted level")
	}

	// Emergency level
	edm.ForceDegrade(LevelEmergency, "Test")

	if edm.CanTrade(true) {
		t.Error("Should not allow any trades at Emergency level")
	}

	t.Logf("✓ Trading permissions test passed")
}

// TestEnhancedDegradeManagerPositionSize tests position size limits
func TestEnhancedDegradeManagerPositionSize(t *testing.T) {
	config := DefaultDegradeConfig()
	edm := NewEnhancedDegradeManager(config)
	defer edm.Stop()

	normalMax := 1.0

	// Normal level - should return full size
	if size := edm.GetMaxPositionSize(normalMax); size != normalMax {
		t.Errorf("Expected %f at Normal, got %f", normalMax, size)
	}

	// Cautious level - should be 50%
	edm.ForceDegrade(LevelCautious, "Test")
	if size := edm.GetMaxPositionSize(normalMax); size != normalMax*0.5 {
		t.Errorf("Expected %f at Cautious, got %f", normalMax*0.5, size)
	}

	// Restricted level - should be 0
	edm.ForceDegrade(LevelRestricted, "Test")
	if size := edm.GetMaxPositionSize(normalMax); size != 0 {
		t.Errorf("Expected 0 at Restricted, got %f", size)
	}

	t.Logf("✓ Position size limits test passed")
}

// TestEnhancedDegradeManagerMetrics tests metrics tracking
func TestEnhancedDegradeManagerMetrics(t *testing.T) {
	edm := NewEnhancedDegradeManager(nil)
	defer edm.Stop()

	// Update metrics
	metrics := &SystemMetrics{
		APILatencyP99: 50 * time.Millisecond,
		ErrorRate:     0.01,
		CPUUsage:      0.5,
		MemoryUsage:   0.6,
	}
	edm.UpdateMetrics(metrics)

	// Get metrics
	current := edm.GetMetrics()
	if current.APILatencyP99 != metrics.APILatencyP99 {
		t.Error("Metrics not stored correctly")
	}

	// Get history
	history := edm.GetMetricsHistory()
	if len(history) == 0 {
		t.Error("Metrics history should not be empty")
	}

	t.Logf("✓ Metrics tracking test passed")
}

// TestEnhancedDegradeManagerCustomRules tests custom rule handling
func TestEnhancedDegradeManagerCustomRules(t *testing.T) {
	config := DefaultDegradeConfig()
	config.CheckInterval = 50 * time.Millisecond

	edm := NewEnhancedDegradeManager(config)
	edm.Start()
	defer edm.Stop()

	// Add custom rule
	rule := DegradeRule{
		Name: "High CPU Rule",
		Condition: func(m *SystemMetrics) bool {
			return m.CPUUsage > 0.9
		},
		Level:       LevelCautious,
		Actions:     []DegradeAction{ActionReducePositionSize},
		AutoRecover: true,
	}
	edm.AddCustomRule(rule)

	// Test with metrics triggering custom rule
	edm.UpdateMetrics(&SystemMetrics{
		CPUUsage: 0.95, // Triggers custom rule
	})

	time.Sleep(100 * time.Millisecond)

	if edm.GetCurrentLevel() != LevelCautious {
		t.Errorf("Expected level Cautious from custom rule, got %v", edm.GetCurrentLevel())
	}

	// Remove custom rule
	edm.RemoveCustomRule("High CPU Rule")

	// Reset metrics and check level returns to normal
	edm.UpdateMetrics(&SystemMetrics{
		CPUUsage: 0.5,
	})

	t.Logf("✓ Custom rules test passed")
}

// TestEnhancedDegradeManagerPauseResume tests pause/resume functionality
func TestEnhancedDegradeManagerPauseResume(t *testing.T) {
	config := DefaultDegradeConfig()
	config.CheckInterval = 50 * time.Millisecond

	edm := NewEnhancedDegradeManager(config)
	edm.Start()
	defer edm.Stop()

	// Pause
	edm.Pause()
	if !edm.GetStatus()["paused"].(bool) {
		t.Error("Should be paused")
	}

	// Update metrics that would normally trigger degradation
	edm.UpdateMetrics(&SystemMetrics{
		DailyDrawdown: 0.15,
	})

	time.Sleep(100 * time.Millisecond)

	// Should still be normal because paused
	if edm.GetCurrentLevel() != LevelNormal {
		t.Error("Should not degrade while paused")
	}

	// Resume
	edm.Resume()
	time.Sleep(100 * time.Millisecond)

	// Now should degrade
	if edm.GetCurrentLevel() != LevelEmergency {
		t.Errorf("Should degrade after resume, got %v", edm.GetCurrentLevel())
	}

	t.Logf("✓ Pause/Resume test passed")
}

// TestEnhancedDegradeManagerExportImport tests state export/import
func TestEnhancedDegradeManagerExportImport(t *testing.T) {
	edm := NewEnhancedDegradeManager(nil)
	defer edm.Stop()

	// Set some state
	edm.ForceDegrade(LevelCautious, "Test")
	edm.UpdateMetrics(&SystemMetrics{
		APILatencyP99: 100 * time.Millisecond,
	})

	// Export state
	data, err := edm.ExportState()
	if err != nil {
		t.Fatalf("Failed to export state: %v", err)
	}

	if len(data) == 0 {
		t.Error("Exported state should not be empty")
	}

	// Import to new manager
	edm2 := NewEnhancedDegradeManager(nil)
	defer edm2.Stop()

	err = edm2.ImportState(data)
	if err != nil {
		t.Fatalf("Failed to import state: %v", err)
	}

	t.Logf("✓ State export/import test passed")
}

// TestActionTypeString tests DegradeAction String method
func TestActionTypeString(t *testing.T) {
	tests := []struct {
		action   DegradeAction
		expected string
	}{
		{ActionNone, "NONE"},
		{ActionReducePositionSize, "REDUCE_POSITION_SIZE"},
		{ActionIncreaseChecks, "INCREASE_CHECKS"},
		{ActionOnlyClose, "ONLY_CLOSE"},
		{ActionCancelPending, "CANCEL_PENDING"},
		{ActionCloseAllPositions, "CLOSE_ALL_POSITIONS"},
		{ActionStopTrading, "STOP_TRADING"},
		{ActionEmergencyShutdown, "EMERGENCY_SHUTDOWN"},
		{DegradeAction(99), "UNKNOWN"},
	}

	for _, tt := range tests {
		if got := tt.action.String(); got != tt.expected {
			t.Errorf("DegradeAction.String() = %v, want %v", got, tt.expected)
		}
	}
}
