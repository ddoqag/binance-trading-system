package main

import (
	"testing"
	"time"
)

// TestRiskLevelType_String tests risk level string representation
func TestRiskLevelType_String(t *testing.T) {
	tests := []struct {
		level    RiskLevelType
		expected string
	}{
		{RiskLevelConservative, "Conservative"},
		{RiskLevelBalanced, "Balanced"},
		{RiskLevelAggressive, "Aggressive"},
		{RiskLevelType(99), "Unknown"},
	}

	for _, tc := range tests {
		result := tc.level.String()
		if result != tc.expected {
			t.Errorf("RiskLevelType(%d).String() = %s, expected %s", tc.level, result, tc.expected)
		}
	}
}

// TestDefaultRiskConfig tests default risk configuration
func TestDefaultRiskConfig(t *testing.T) {
	config := DefaultRiskConfig()

	if config.MaxPosition != 1.0 {
		t.Errorf("Expected MaxPosition=1.0, got %f", config.MaxPosition)
	}

	if config.MaxSinglePosition != 0.2 {
		t.Errorf("Expected MaxSinglePosition=0.2, got %f", config.MaxSinglePosition)
	}

	if config.StopLossPct != 0.02 {
		t.Errorf("Expected StopLossPct=0.02, got %f", config.StopLossPct)
	}

	if config.RiskLevel != RiskLevelBalanced {
		t.Errorf("Expected RiskLevel=Balanced, got %v", config.RiskLevel)
	}
}

// TestRiskConfig_Validate tests configuration validation
func TestRiskConfig_Validate(t *testing.T) {
	tests := []struct {
		name      string
		config    *RiskConfig
		wantError bool
	}{
		{
			name:      "valid config",
			config:    DefaultRiskConfig(),
			wantError: false,
		},
		{
			name: "negative max position",
			config: func() *RiskConfig {
				c := DefaultRiskConfig()
				c.MaxPosition = -1
				return c
			}(),
			wantError: true,
		},
		{
			name: "single position > 1",
			config: func() *RiskConfig {
				c := DefaultRiskConfig()
				c.MaxSinglePosition = 1.5
				return c
			}(),
			wantError: true,
		},
		{
			name: "total < single position",
			config: func() *RiskConfig {
				c := DefaultRiskConfig()
				c.MaxSinglePosition = 0.5
				c.MaxTotalPosition = 0.3
				return c
			}(),
			wantError: true,
		},
		{
			name: "stop loss > 1",
			config: func() *RiskConfig {
				c := DefaultRiskConfig()
				c.StopLossPct = 1.5
				return c
			}(),
			wantError: true,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			err := tc.config.Validate()
			if tc.wantError && err == nil {
				t.Errorf("Expected error, got nil")
			}
			if !tc.wantError && err != nil {
				t.Errorf("Unexpected error: %v", err)
			}
		})
	}
}

// TestRiskConfig_ApplyRiskLevel tests risk level preset application
func TestRiskConfig_ApplyRiskLevel(t *testing.T) {
	config := DefaultRiskConfig()

	// Test conservative preset
	config.ApplyRiskLevel(RiskLevelConservative)
	if config.RiskLevel != RiskLevelConservative {
		t.Errorf("Expected RiskLevel=Conservative, got %v", config.RiskLevel)
	}
	if config.MaxSinglePosition != 0.1 {
		t.Errorf("Expected MaxSinglePosition=0.1 for conservative, got %f", config.MaxSinglePosition)
	}
	if config.StopLossPct != 0.01 {
		t.Errorf("Expected StopLossPct=0.01 for conservative, got %f", config.StopLossPct)
	}

	// Test aggressive preset
	config.ApplyRiskLevel(RiskLevelAggressive)
	if config.RiskLevel != RiskLevelAggressive {
		t.Errorf("Expected RiskLevel=Aggressive, got %v", config.RiskLevel)
	}
	if config.MaxSinglePosition != 0.3 {
		t.Errorf("Expected MaxSinglePosition=0.3 for aggressive, got %f", config.MaxSinglePosition)
	}
	if config.MaxOrdersPerMin != 120 {
		t.Errorf("Expected MaxOrdersPerMin=120 for aggressive, got %d", config.MaxOrdersPerMin)
	}
}

// TestRiskConfig_GetRiskMultiplier tests risk multiplier
func TestRiskConfig_GetRiskMultiplier(t *testing.T) {
	tests := []struct {
		level    RiskLevelType
		expected float64
	}{
		{RiskLevelConservative, 0.5},
		{RiskLevelBalanced, 1.0},
		{RiskLevelAggressive, 1.5},
	}

	for _, tc := range tests {
		config := DefaultRiskConfig()
		config.RiskLevel = tc.level
		result := config.GetRiskMultiplier()
		if result != tc.expected {
			t.Errorf("RiskLevel %v: expected multiplier %f, got %f", tc.level, tc.expected, result)
		}
	}
}

// TestNewPositionRisk tests position risk creation
func TestNewPositionRisk(t *testing.T) {
	config := DefaultRiskConfig()
	pr := NewPositionRisk("BTCUSDT", 50000.0, 0.5, "long", config)

	if pr.Symbol != "BTCUSDT" {
		t.Errorf("Expected Symbol=BTCUSDT, got %s", pr.Symbol)
	}

	if pr.EntryPrice != 50000.0 {
		t.Errorf("Expected EntryPrice=50000.0, got %f", pr.EntryPrice)
	}

	if pr.Side != "long" {
		t.Errorf("Expected Side=long, got %s", pr.Side)
	}

	// Check stop loss calculation for long position
	expectedSL := 50000.0 * (1 - config.StopLossPct) // 49000
	if pr.StopLoss != expectedSL {
		t.Errorf("Expected StopLoss=%f, got %f", expectedSL, pr.StopLoss)
	}

	// Check take profit calculation for long position
	expectedTP := 50000.0 * (1 + config.TakeProfitPct) // 52500
	if pr.TakeProfit != expectedTP {
		t.Errorf("Expected TakeProfit=%f, got %f", expectedTP, pr.TakeProfit)
	}
}

// TestNewPositionRisk_Short tests position risk for short position
func TestNewPositionRisk_Short(t *testing.T) {
	config := DefaultRiskConfig()
	pr := NewPositionRisk("BTCUSDT", 50000.0, 0.5, "short", config)

	// For short: stop loss is above entry
	expectedSL := 50000.0 * (1 + config.StopLossPct) // 51000
	if pr.StopLoss != expectedSL {
		t.Errorf("Expected StopLoss=%f for short, got %f", expectedSL, pr.StopLoss)
	}

	// For short: take profit is below entry
	expectedTP := 50000.0 * (1 - config.TakeProfitPct) // 47500
	if pr.TakeProfit != expectedTP {
		t.Errorf("Expected TakeProfit=%f for short, got %f", expectedTP, pr.TakeProfit)
	}
}

// TestPositionRisk_UpdatePrice tests price update and PnL calculation
func TestPositionRisk_UpdatePrice(t *testing.T) {
	config := DefaultRiskConfig()
	pr := NewPositionRisk("BTCUSDT", 50000.0, 1.0, "long", config)

	// Price goes up 10%
	pr.UpdatePrice(55000.0)

	expectedPnL := (55000.0 - 50000.0) * 1.0 // 5000
	if pr.UnrealizedPnL != expectedPnL {
		t.Errorf("Expected UnrealizedPnL=%f, got %f", expectedPnL, pr.UnrealizedPnL)
	}

	expectedPnLPct := (55000.0 - 50000.0) / 50000.0 // 0.10
	if pr.PnLPct != expectedPnLPct {
		t.Errorf("Expected PnLPct=%f, got %f", expectedPnLPct, pr.PnLPct)
	}

	if pr.HighestPrice != 55000.0 {
		t.Errorf("Expected HighestPrice=55000.0, got %f", pr.HighestPrice)
	}
}

// TestPositionRisk_CheckStopLoss tests stop loss triggering
func TestPositionRisk_CheckStopLoss(t *testing.T) {
	config := DefaultRiskConfig()
	pr := NewPositionRisk("BTCUSDT", 50000.0, 1.0, "long", config)

	// Price above stop loss - should not trigger
	pr.UpdatePrice(49500.0)
	if pr.CheckStopLoss() {
		t.Error("Stop loss should not trigger above stop level")
	}

	// Price at stop loss - should trigger
	pr.UpdatePrice(pr.StopLoss)
	if !pr.CheckStopLoss() {
		t.Error("Stop loss should trigger at stop level")
	}

	// Price below stop loss - should trigger
	pr.UpdatePrice(48000.0)
	if !pr.CheckStopLoss() {
		t.Error("Stop loss should trigger below stop level")
	}
}

// TestPositionRisk_CheckTakeProfit tests take profit triggering
func TestPositionRisk_CheckTakeProfit(t *testing.T) {
	config := DefaultRiskConfig()
	pr := NewPositionRisk("BTCUSDT", 50000.0, 1.0, "long", config)

	// Price below take profit - should not trigger
	pr.UpdatePrice(51000.0)
	if pr.CheckTakeProfit() {
		t.Error("Take profit should not trigger below take profit level")
	}

	// Price at take profit - should trigger
	pr.UpdatePrice(pr.TakeProfit)
	if !pr.CheckTakeProfit() {
		t.Error("Take profit should trigger at take profit level")
	}
}

// TestPositionRisk_CheckTrailingStop tests trailing stop logic
func TestPositionRisk_CheckTrailingStop(t *testing.T) {
	config := DefaultRiskConfig()
	config.TrailingStopPct = 0.05 // 5% trailing stop
	pr := NewPositionRisk("BTCUSDT", 50000.0, 1.0, "long", config)

	// Price rises to 55000 (10% gain)
	pr.UpdatePrice(55000.0)

	// Price drops 3% to 53350 - should not trigger trailing stop (within 5%)
	pr.UpdatePrice(53350.0)
	if pr.CheckTrailingStop(true, config.TrailingStopPct) {
		t.Error("Trailing stop should not trigger within trailing percentage")
	}

	// Price drops 6% from peak to 51700 - should trigger trailing stop
	pr.UpdatePrice(51700.0)
	if !pr.CheckTrailingStop(true, config.TrailingStopPct) {
		t.Error("Trailing stop should trigger when price drops more than trailing percentage")
	}
}

// TestPositionRisk_GetHoldingTime tests holding time calculation
func TestPositionRisk_GetHoldingTime(t *testing.T) {
	config := DefaultRiskConfig()
	pr := NewPositionRisk("BTCUSDT", 50000.0, 1.0, "long", config)

	// Wait a small amount of time
	time.Sleep(10 * time.Millisecond)

	holdingTime := pr.GetHoldingTime()
	if holdingTime < 10*time.Millisecond {
		t.Errorf("Expected holding time >= 10ms, got %v", holdingTime)
	}
}

// TestNewEnhancedRiskManager tests enhanced risk manager creation
func TestNewEnhancedRiskManager(t *testing.T) {
	config := DefaultRiskConfig()
	erm := NewEnhancedRiskManager(config, 100000.0)

	if erm == nil {
		t.Fatal("Expected non-nil EnhancedRiskManager")
	}

	if erm.RiskManager == nil {
		t.Error("Expected embedded RiskManager to be initialized")
	}

	if erm.totalCapital != 100000.0 {
		t.Errorf("Expected totalCapital=100000.0, got %f", erm.totalCapital)
	}

	if erm.config.RiskLevel != RiskLevelBalanced {
		t.Errorf("Expected default RiskLevel=Balanced, got %v", erm.config.RiskLevel)
	}
}

// TestEnhancedRiskManager_RegisterPosition tests position registration
func TestEnhancedRiskManager_RegisterPosition(t *testing.T) {
	config := DefaultRiskConfig()
	erm := NewEnhancedRiskManager(config, 100000.0)

	pr := erm.RegisterPosition("BTCUSDT", 50000.0, 0.5, "long")

	if pr == nil {
		t.Fatal("Expected non-nil PositionRisk")
	}

	if pr.Symbol != "BTCUSDT" {
		t.Errorf("Expected Symbol=BTCUSDT, got %s", pr.Symbol)
	}

	// Verify position is tracked
	retrieved := erm.GetPositionRisk("BTCUSDT")
	if retrieved == nil {
		t.Error("Expected position to be tracked")
	}
}

// TestEnhancedRiskManager_UpdatePositionPrice tests position price updates
func TestEnhancedRiskManager_UpdatePositionPrice(t *testing.T) {
	config := DefaultRiskConfig()
	erm := NewEnhancedRiskManager(config, 100000.0)

	erm.RegisterPosition("BTCUSDT", 50000.0, 1.0, "long")

	// Update with normal price - no alert
	alert := erm.UpdatePositionPrice("BTCUSDT", 51000.0)
	if alert != nil {
		t.Errorf("Expected no alert for normal price update, got %v", alert)
	}

	// Update with stop loss trigger price
	alert = erm.UpdatePositionPrice("BTCUSDT", 48000.0)
	if alert == nil {
		t.Error("Expected stop loss alert")
	}
	if alert.Type != AlertTypeStopLoss {
		t.Errorf("Expected alert type STOP_LOSS, got %v", alert.Type)
	}
}

// TestEnhancedRiskManager_CheckEnhancedCanExecute tests enhanced execution checks
func TestEnhancedRiskManager_CheckEnhancedCanExecute(t *testing.T) {
	config := DefaultRiskConfig()
	erm := NewEnhancedRiskManager(config, 100000.0)

	// Test valid execution
	canExecute, reason := erm.CheckEnhancedCanExecute("BTCUSDT", ActionJoinBid, 0.01, 50000.0, 0.0)
	if !canExecute {
		t.Errorf("Expected canExecute=true for valid order, got false: %s", reason)
	}

	// Test single position ratio limit
	// Order size: 30000 / 100000 = 30% of capital, exceeds 20% limit
	canExecute, reason = erm.CheckEnhancedCanExecute("BTCUSDT", ActionJoinBid, 0.6, 50000.0, 0.0)
	if canExecute {
		t.Error("Expected canExecute=false for position ratio exceeding limit")
	}
	if reason == "" {
		t.Error("Expected non-empty reason for rejected order")
	}
}

// TestEnhancedRiskManager_SetRiskLevel tests risk level changes
func TestEnhancedRiskManager_SetRiskLevel(t *testing.T) {
	config := DefaultRiskConfig()
	erm := NewEnhancedRiskManager(config, 100000.0)

	// Change to conservative
	erm.SetRiskLevel(RiskLevelConservative)

	if erm.config.RiskLevel != RiskLevelConservative {
		t.Errorf("Expected RiskLevel=Conservative, got %v", erm.config.RiskLevel)
	}

	// Verify base risk manager was updated
	if erm.RiskManager.maxOrdersPerMin != 30 {
		t.Errorf("Expected maxOrdersPerMin=30 for conservative, got %d", erm.RiskManager.maxOrdersPerMin)
	}
}

// TestEnhancedRiskManager_CheckSlippage tests slippage detection
func TestEnhancedRiskManager_CheckSlippage(t *testing.T) {
	config := DefaultRiskConfig()
	config.MaxSlippagePct = 0.001 // 0.1%
	config.EnableSlippageCheck = true

	erm := NewEnhancedRiskManager(config, 100000.0)

	// Store expected price
	erm.expectedPrice["BTCUSDT"] = 50000.0

	// Test acceptable slippage (0.05%)
	ok, slippage := erm.CheckSlippage("BTCUSDT", 50025.0)
	if !ok {
		t.Errorf("Expected ok=true for acceptable slippage, got false (slippage: %f)", slippage)
	}

	// Test excessive slippage (0.2%)
	ok, slippage = erm.CheckSlippage("BTCUSDT", 50100.0)
	if ok {
		t.Errorf("Expected ok=false for excessive slippage, got true (slippage: %f)", slippage)
	}
}

// TestRiskAlert_String tests alert string representation
func TestRiskAlert_String(t *testing.T) {
	alert := RiskAlert{
		Timestamp: time.Date(2024, 1, 1, 12, 0, 0, 0, time.UTC),
		Level:     AlertLevelCritical,
		Type:      AlertTypeStopLoss,
		Message:   "Stop loss triggered",
		Symbol:    "BTCUSDT",
	}

	result := alert.String()
	expected := "[12:00:00] CRITICAL STOP_LOSS: Stop loss triggered (BTCUSDT)"
	if result != expected {
		t.Errorf("Alert.String() = %s, expected %s", result, expected)
	}
}

// TestAlertLevel_String tests alert level string representation
func TestAlertLevel_String(t *testing.T) {
	tests := []struct {
		level    RiskAlertLevel
		expected string
	}{
		{AlertLevelInfo, "INFO"},
		{AlertLevelWarning, "WARNING"},
		{AlertLevelCritical, "CRITICAL"},
		{RiskAlertLevel(99), "UNKNOWN"},
	}

	for _, tc := range tests {
		result := tc.level.String()
		if result != tc.expected {
			t.Errorf("AlertLevel(%d).String() = %s, expected %s", tc.level, result, tc.expected)
		}
	}
}

// TestAlertType_String tests alert type string representation
func TestAlertType_String(t *testing.T) {
	tests := []struct {
		alertType RiskAlertType
		expected  string
	}{
		{AlertTypeStopLoss, "STOP_LOSS"},
		{AlertTypeTakeProfit, "TAKE_PROFIT"},
		{AlertTypeDrawdown, "DRAWDOWN"},
		{RiskAlertType(99), "UNKNOWN"},
	}

	for _, tc := range tests {
		result := tc.alertType.String()
		if result != tc.expected {
			t.Errorf("AlertType(%d).String() = %s, expected %s", tc.alertType, result, tc.expected)
		}
	}
}

// TestEnhancedRiskManager_GetAlerts tests alert retrieval
func TestEnhancedRiskManager_GetAlerts(t *testing.T) {
	config := DefaultRiskConfig()
	config.AlertCooldown = 0 // Disable cooldown for testing
	erm := NewEnhancedRiskManager(config, 100000.0)

	// Register a position and trigger alerts
	erm.RegisterPosition("BTCUSDT", 50000.0, 1.0, "long")
	erm.UpdatePositionPrice("BTCUSDT", 48000.0) // Trigger stop loss

	// Get all alerts
	alerts := erm.GetAlerts(AlertLevelInfo, 10)
	if len(alerts) == 0 {
		t.Error("Expected at least one alert")
	}

	// Get only critical alerts
	criticalAlerts := erm.GetAlerts(AlertLevelCritical, 10)
	if len(criticalAlerts) == 0 {
		t.Error("Expected at least one critical alert")
	}
}

// TestEnhancedRiskManager_ClosePosition tests position closing
func TestEnhancedRiskManager_ClosePosition(t *testing.T) {
	config := DefaultRiskConfig()
	erm := NewEnhancedRiskManager(config, 100000.0)

	erm.RegisterPosition("BTCUSDT", 50000.0, 1.0, "long")

	// Verify position exists
	if erm.GetPositionRisk("BTCUSDT") == nil {
		t.Error("Expected position to exist")
	}

	// Close position
	erm.ClosePosition("BTCUSDT")

	// Verify position is removed
	if erm.GetPositionRisk("BTCUSDT") != nil {
		t.Error("Expected position to be removed")
	}
}

// TestRiskConfigFromConfigManager tests loading config from ConfigManager
func TestRiskConfigFromConfigManager(t *testing.T) {
	cm := NewConfigManager("TEST")
	cm.SetDefault("risk.max_position", 2.0)
	cm.SetDefault("risk.stop_loss_pct", 0.03)
	cm.SetDefault("risk.risk_level", "aggressive")

	config := RiskConfigFromConfigManager(cm)

	if config.MaxPosition != 2.0 {
		t.Errorf("Expected MaxPosition=2.0, got %f", config.MaxPosition)
	}

	if config.StopLossPct != 0.03 {
		t.Errorf("Expected StopLossPct=0.03, got %f", config.StopLossPct)
	}

	if config.RiskLevel != RiskLevelAggressive {
		t.Errorf("Expected RiskLevel=Aggressive, got %v", config.RiskLevel)
	}
}

// TestHFTConfig_RiskConfig tests HFTConfig RiskConfig method
func TestHFTConfig_RiskConfig(t *testing.T) {
	cm := NewConfigManager("TEST")
	cm.SetDefault("risk.max_position", 1.5)
	cm.SetDefault("risk.stop_loss_pct", 0.025)

	hftConfig := NewHFTConfig(cm)
	riskConfig := hftConfig.RiskConfig()

	if riskConfig.MaxPosition != 1.5 {
		t.Errorf("Expected MaxPosition=1.5, got %f", riskConfig.MaxPosition)
	}

	if riskConfig.StopLossPct != 0.025 {
		t.Errorf("Expected StopLossPct=0.025, got %f", riskConfig.StopLossPct)
	}
}

// TestEnhancedRiskManager_RateLimits tests rate limiting
func TestEnhancedRiskManager_RateLimits(t *testing.T) {
	config := DefaultRiskConfig()
	config.MaxOrdersPerHour = 2
	config.MaxOrdersPerDay = 3

	erm := NewEnhancedRiskManager(config, 100000.0)

	// First two orders should pass
	ok1, _ := erm.CheckEnhancedCanExecute("BTCUSDT", ActionJoinBid, 0.01, 50000.0, 0.0)
	ok2, _ := erm.CheckEnhancedCanExecute("BTCUSDT", ActionJoinBid, 0.01, 50000.0, 0.0)

	// Third order should fail hourly limit
	ok3, reason3 := erm.CheckEnhancedCanExecute("BTCUSDT", ActionJoinBid, 0.01, 50000.0, 0.0)

	if !ok1 || !ok2 {
		t.Error("Expected first two orders to pass")
	}

	if ok3 {
		t.Error("Expected third order to fail hourly limit")
	}
	if reason3 != "Hourly order rate limit exceeded" {
		t.Errorf("Expected hourly limit message, got: %s", reason3)
	}
}
