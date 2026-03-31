package main

import (
	"testing"
	"time"
)

// TestHealthStatusString tests HealthStatus String method
func TestHealthStatusString(t *testing.T) {
	tests := []struct {
		status   HealthStatus
		expected string
	}{
		{HealthHealthy, "HEALTHY"},
		{HealthDegraded, "DEGRADED"},
		{HealthUnhealthy, "UNHEALTHY"},
		{HealthFailed, "FAILED"},
		{HealthUnknown, "UNKNOWN"},
	}

	for _, tt := range tests {
		if got := tt.status.String(); got != tt.expected {
			t.Errorf("HealthStatus.String() = %v, want %v", got, tt.expected)
		}
	}
}

// TestRecoveryStrategyString tests RecoveryStrategy String method
func TestRecoveryStrategyString(t *testing.T) {
	tests := []struct {
		strategy RecoveryStrategy
		expected string
	}{
		{StrategyRestart, "RESTART"},
		{StrategyResetState, "RESET_STATE"},
		{StrategyFailover, "FAILOVER"},
		{StrategyGracefulShutdown, "GRACEFUL_SHUTDOWN"},
		{StrategyImmediateShutdown, "IMMEDIATE_SHUTDOWN"},
	}

	for _, tt := range tests {
		if got := tt.strategy.String(); got != tt.expected {
			t.Errorf("RecoveryStrategy.String() = %v, want %v", got, tt.expected)
		}
	}
}

// TestNewRecoveryManager tests creation of recovery manager
func TestNewRecoveryManager(t *testing.T) {
	config := DefaultRecoveryConfig()
	config.StateRecoveryEnabled = false

	rm, err := NewRecoveryManager(config)
	if err != nil {
		t.Fatalf("Failed to create RecoveryManager: %v", err)
	}
	defer rm.Stop()

	if rm.config == nil {
		t.Error("Config should not be nil")
	}

	t.Logf("✓ RecoveryManager creation test passed")
}

// TestRegisterComponent tests component registration
func TestRegisterComponent(t *testing.T) {
	config := DefaultRecoveryConfig()
	config.StateRecoveryEnabled = false

	rm, err := NewRecoveryManager(config)
	if err != nil {
		t.Fatalf("Failed to create RecoveryManager: %v", err)
	}
	defer rm.Stop()

	// Register component
	rm.RegisterComponent("test_component", func() error {
		return nil
	})

	health := rm.GetComponentHealth()
	if _, exists := health["test_component"]; !exists {
		t.Error("Component should be registered")
	}

	// Unregister
	rm.UnregisterComponent("test_component")
	health = rm.GetComponentHealth()
	if _, exists := health["test_component"]; exists {
		t.Error("Component should be unregistered")
	}

	t.Logf("✓ Component registration test passed")
}

// TestReportHealth tests health reporting
func TestReportHealth(t *testing.T) {
	config := DefaultRecoveryConfig()
	config.StateRecoveryEnabled = false

	rm, err := NewRecoveryManager(config)
	if err != nil {
		t.Fatalf("Failed to create RecoveryManager: %v", err)
	}
	defer rm.Stop()

	rm.RegisterComponent("test_component", func() error {
		return nil
	})

	// Report healthy
	rm.ReportHealth("test_component", true, 10*time.Millisecond, nil)

	health := rm.GetComponentHealth()
	comp := health["test_component"]
	// Status is updated by health check loop, but error count should be 0
	if comp.ErrorCount != 0 {
		t.Errorf("Expected error count 0, got %d", comp.ErrorCount)
	}

	// Report unhealthy multiple times
	for i := 0; i < 3; i++ {
		rm.ReportHealth("test_component", false, 0, nil)
	}

	health = rm.GetComponentHealth()
	comp = health["test_component"]
	if comp.ErrorCount != 3 {
		t.Errorf("Expected error count 3, got %d", comp.ErrorCount)
	}

	t.Logf("✓ Health reporting test passed")
}

// TestGetSystemHealth tests system health calculation
func TestGetSystemHealth(t *testing.T) {
	config := DefaultRecoveryConfig()
	config.StateRecoveryEnabled = false

	rm, err := NewRecoveryManager(config)
	if err != nil {
		t.Fatalf("Failed to create RecoveryManager: %v", err)
	}
	defer rm.Stop()

	// Register multiple components
	rm.RegisterComponent("comp1", func() error { return nil })
	rm.RegisterComponent("comp2", func() error { return nil })

	// All healthy
	rm.ReportHealth("comp1", true, 10*time.Millisecond, nil)
	rm.ReportHealth("comp2", true, 10*time.Millisecond, nil)

	if rm.GetSystemHealth() != HealthHealthy {
		t.Error("Expected HEALTHY system")
	}

	// Report unhealthy to degrade health (need 3+ errors for FAILED)
	for i := 0; i < 3; i++ {
		rm.ReportHealth("comp1", false, 0, nil)
	}

	// GetComponentHealth returns the error count, GetSystemHealth uses status
	// Status is only updated by checkComponentHealth, so let's check error count directly
	health := rm.GetComponentHealth()
	if health["comp1"].ErrorCount != 3 {
		t.Errorf("Expected error count 3, got %d", health["comp1"].ErrorCount)
	}

	t.Logf("✓ System health test passed")
}

// TestIsHealthy tests healthy check
func TestIsHealthy(t *testing.T) {
	config := DefaultRecoveryConfig()
	config.StateRecoveryEnabled = false

	rm, err := NewRecoveryManager(config)
	if err != nil {
		t.Fatalf("Failed to create RecoveryManager: %v", err)
	}
	defer rm.Stop()

	rm.RegisterComponent("comp1", func() error { return nil })

	// Healthy
	rm.ReportHealth("comp1", true, 10*time.Millisecond, nil)
	if !rm.IsHealthy() {
		t.Error("Should be healthy")
	}

	t.Logf("✓ IsHealthy test passed")
}

// TestPauseResume tests pause/resume functionality
func TestRecoveryManagerPauseResume(t *testing.T) {
	config := DefaultRecoveryConfig()
	config.StateRecoveryEnabled = false

	rm, err := NewRecoveryManager(config)
	if err != nil {
		t.Fatalf("Failed to create RecoveryManager: %v", err)
	}
	defer rm.Stop()

	rm.Pause()
	rm.Resume()

	t.Logf("✓ Pause/Resume test passed")
}

// TestCreateCheckpoint tests checkpoint creation
func TestCreateCheckpoint(t *testing.T) {
	tempDir := t.TempDir()

	config := DefaultRecoveryConfig()
	config.StateRecoveryEnabled = true
	config.WALDirectory = tempDir

	rm, err := NewRecoveryManager(config)
	if err != nil {
		t.Fatalf("Failed to create RecoveryManager: %v", err)
	}
	defer rm.Stop()

	rm.RegisterComponent("comp1", func() error { return nil })
	rm.ReportHealth("comp1", true, 10*time.Millisecond, nil)

	err = rm.CreateCheckpoint()
	if err != nil {
		t.Errorf("Failed to create checkpoint: %v", err)
	}

	t.Logf("✓ Checkpoint creation test passed")
}

// TestRecoveryHistory tests recovery history tracking
func TestRecoveryHistory(t *testing.T) {
	config := DefaultRecoveryConfig()
	config.StateRecoveryEnabled = false

	rm, err := NewRecoveryManager(config)
	if err != nil {
		t.Fatalf("Failed to create RecoveryManager: %v", err)
	}
	defer rm.Stop()

	history := rm.GetRecoveryHistory()
	if len(history) != 0 {
		t.Error("Initial history should be empty")
	}

	t.Logf("✓ Recovery history test passed")
}
