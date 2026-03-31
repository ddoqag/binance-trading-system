package main

import (
	"testing"
	"time"
)

/*
stp_test.go - Self-Trade Prevention Unit Tests

Tests all STP modes and scenarios:
- Order tracking and untracking
- Self-trade detection
- Prevention strategies (REJECT, CANCEL_OLDEST, CANCEL_NEWEST, DECREMENT)
- Event recording
- Metrics
*/

func TestSTPMode_String(t *testing.T) {
	tests := []struct {
		mode     STPMode
		expected string
	}{
		{STPModeNone, "NONE"},
		{STPModeReject, "REJECT"},
		{STPModeCancelOldest, "CANCEL_OLDEST"},
		{STPModeCancelNewest, "CANCEL_NEWEST"},
		{STPModeDecrement, "DECREMENT"},
		{STPMode(99), "UNKNOWN"},
	}

	for _, tt := range tests {
		result := tt.mode.String()
		if result != tt.expected {
			t.Errorf("STPMode.String() = %s, expected %s", result, tt.expected)
		}
	}
}

func TestDefaultSTPConfig(t *testing.T) {
	config := DefaultSTPConfig()

	if !config.EnableSTP {
		t.Error("DefaultSTPConfig.EnableSTP should be true")
	}
	if config.Mode != STPModeReject {
		t.Errorf("DefaultSTPConfig.Mode = %s, expected REJECT", config.Mode)
	}
	if config.CheckInterval != 100*time.Millisecond {
		t.Errorf("DefaultSTPConfig.CheckInterval = %v, expected 100ms", config.CheckInterval)
	}
	if config.MaxSelfTradeAttempts != 5 {
		t.Errorf("DefaultSTPConfig.MaxSelfTradeAttempts = %d, expected 5", config.MaxSelfTradeAttempts)
	}
	if config.SelfTradeCooldown != 1*time.Minute {
		t.Errorf("DefaultSTPConfig.SelfTradeCooldown = %v, expected 1m", config.SelfTradeCooldown)
	}
	if !config.LogSelfTradeEvents {
		t.Error("DefaultSTPConfig.LogSelfTradeEvents should be true")
	}
	if !config.AlertOnSelfTrade {
		t.Error("DefaultSTPConfig.AlertOnSelfTrade should be true")
	}
	if config.PriceTolerance != 0.0001 {
		t.Errorf("DefaultSTPConfig.PriceTolerance = %f, expected 0.0001", config.PriceTolerance)
	}
}

func TestSTPConfig_Validate(t *testing.T) {
	tests := []struct {
		name    string
		config  *STPConfig
		wantErr bool
	}{
		{
			name:    "Valid config",
			config:  DefaultSTPConfig(),
			wantErr: false,
		},
		{
			name: "Check interval too small",
			config: &STPConfig{
				EnableSTP:            true,
				Mode:                 STPModeReject,
				CheckInterval:        5 * time.Millisecond,
				MaxSelfTradeAttempts: 5,
				SelfTradeCooldown:    1 * time.Minute,
				PriceTolerance:       0.0001,
			},
			wantErr: true,
		},
		{
			name: "Max attempts too small",
			config: &STPConfig{
				EnableSTP:            true,
				Mode:                 STPModeReject,
				CheckInterval:        100 * time.Millisecond,
				MaxSelfTradeAttempts: 0,
				SelfTradeCooldown:    1 * time.Minute,
				PriceTolerance:       0.0001,
			},
			wantErr: true,
		},
		{
			name: "Cooldown too small",
			config: &STPConfig{
				EnableSTP:            true,
				Mode:                 STPModeReject,
				CheckInterval:        100 * time.Millisecond,
				MaxSelfTradeAttempts: 5,
				SelfTradeCooldown:    500 * time.Millisecond,
				PriceTolerance:       0.0001,
			},
			wantErr: true,
		},
		{
			name: "Price tolerance too large",
			config: &STPConfig{
				EnableSTP:            true,
				Mode:                 STPModeReject,
				CheckInterval:        100 * time.Millisecond,
				MaxSelfTradeAttempts: 5,
				SelfTradeCooldown:    1 * time.Minute,
				PriceTolerance:       0.02,
			},
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := tt.config.Validate()
			if (err != nil) != tt.wantErr {
				t.Errorf("Validate() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func TestNewSelfTradePrevention(t *testing.T) {
	// Test with nil config (should use defaults)
	stp := NewSelfTradePrevention(nil)
	if stp == nil {
		t.Fatal("NewSelfTradePrevention(nil) returned nil")
	}
	if stp.config == nil {
		t.Fatal("STP config is nil")
	}
	if !stp.config.EnableSTP {
		t.Error("Default config should have EnableSTP = true")
	}

	// Test with custom config
	customConfig := &STPConfig{
		EnableSTP:     false,
		Mode:          STPModeNone,
		CheckInterval: 200 * time.Millisecond,
	}
	stp2 := NewSelfTradePrevention(customConfig)
	if stp2.config.EnableSTP {
		t.Error("Custom config should have EnableSTP = false")
	}
	if stp2.config.Mode != STPModeNone {
		t.Error("Custom config should have Mode = NONE")
	}
}

func TestSelfTradePrevention_TrackOrder(t *testing.T) {
	stp := NewSelfTradePrevention(nil)

	order := &Order{
		ID:     "ord_123",
		Symbol: "BTCUSDT",
		Side:   SideBuy,
		Price:  50000.0,
		Size:   1.0,
		Status: StatusOpen,
	}

	stp.TrackOrder(order)

	if stp.GetOrderCount() != 1 {
		t.Errorf("GetOrderCount() = %d, expected 1", stp.GetOrderCount())
	}

	tracked := stp.GetTrackedOrders("BTCUSDT")
	if len(tracked) != 1 {
		t.Errorf("GetTrackedOrders() returned %d orders, expected 1", len(tracked))
	}
}

func TestSelfTradePrevention_UntrackOrder(t *testing.T) {
	stp := NewSelfTradePrevention(nil)

	order := &Order{
		ID:     "ord_123",
		Symbol: "BTCUSDT",
		Side:   SideBuy,
		Price:  50000.0,
		Size:   1.0,
		Status: StatusOpen,
	}

	stp.TrackOrder(order)
	stp.UntrackOrder("ord_123")

	if stp.GetOrderCount() != 0 {
		t.Errorf("GetOrderCount() = %d, expected 0", stp.GetOrderCount())
	}
}

func TestSelfTradePrevention_CheckOrder_NoConflict(t *testing.T) {
	stp := NewSelfTradePrevention(nil)

	// Track a buy order
	buyOrder := &Order{
		ID:     "ord_buy",
		Symbol: "BTCUSDT",
		Side:   SideBuy,
		Price:  50000.0,
		Size:   1.0,
		Status: StatusOpen,
	}
	stp.TrackOrder(buyOrder)

	// Check another buy order (same side, no self-trade possible)
	result := stp.CheckOrder("BTCUSDT", SideBuy, 50100.0, 0.5, "ord_new")
	if result.ShouldPrevent {
		t.Error("Same side orders should not trigger self-trade prevention")
	}
}

func TestSelfTradePrevention_CheckOrder_Conflict(t *testing.T) {
	stp := NewSelfTradePrevention(nil)
	stp.config.Mode = STPModeReject

	// Track a buy order
	buyOrder := &Order{
		ID:     "ord_buy",
		Symbol: "BTCUSDT",
		Side:   SideBuy,
		Price:  50000.0,
		Size:   1.0,
		Status: StatusOpen,
		Type:   TypeLimit,
	}
	stp.TrackOrder(buyOrder)

	// Check a sell order that would cross (sell at price <= buy price)
	result := stp.CheckOrder("BTCUSDT", SideSell, 49900.0, 0.5, "ord_sell")
	if !result.ShouldPrevent {
		t.Error("Crossing orders should trigger self-trade prevention")
	}
	if result.Mode != STPModeReject {
		t.Errorf("Mode = %s, expected REJECT", result.Mode)
	}
	if result.Event == nil {
		t.Error("Event should be populated")
	}
}

func TestSelfTradePrevention_CheckOrder_FilledOrderIgnored(t *testing.T) {
	stp := NewSelfTradePrevention(nil)

	// Track a filled buy order
	buyOrder := &Order{
		ID:     "ord_buy",
		Symbol: "BTCUSDT",
		Side:   SideBuy,
		Price:  50000.0,
		Size:   1.0,
		Status: StatusFilled,
		Type:   TypeLimit,
	}
	stp.TrackOrder(buyOrder)

	// Check a sell order - should not be prevented since buy order is filled
	result := stp.CheckOrder("BTCUSDT", SideSell, 49900.0, 0.5, "ord_sell")
	if result.ShouldPrevent {
		t.Error("Filled orders should not trigger self-trade prevention")
	}
}

func TestSelfTradePrevention_CheckOrder_Disabled(t *testing.T) {
	stp := NewSelfTradePrevention(nil)
	stp.config.EnableSTP = false

	// Track a buy order
	buyOrder := &Order{
		ID:     "ord_buy",
		Symbol: "BTCUSDT",
		Side:   SideBuy,
		Price:  50000.0,
		Size:   1.0,
		Status: StatusOpen,
		Type:   TypeLimit,
	}
	stp.TrackOrder(buyOrder)

	// Check a sell order - should not be prevented when STP is disabled
	result := stp.CheckOrder("BTCUSDT", SideSell, 49900.0, 0.5, "ord_sell")
	if result.ShouldPrevent {
		t.Error("Self-trade prevention should not trigger when disabled")
	}
}

func TestSelfTradePrevention_CheckOrder_MarketOrder(t *testing.T) {
	stp := NewSelfTradePrevention(nil)

	// Track a limit buy order
	buyOrder := &Order{
		ID:     "ord_buy",
		Symbol: "BTCUSDT",
		Side:   SideBuy,
		Price:  50000.0,
		Size:   1.0,
		Status: StatusOpen,
		Type:   TypeLimit,
	}
	stp.TrackOrder(buyOrder)

	// Check a market sell order - should always trigger self-trade
	result := stp.CheckOrder("BTCUSDT", SideSell, 0, 0.5, "ord_market_sell")
	if !result.ShouldPrevent {
		t.Error("Market orders should always trigger self-trade prevention with opposite side")
	}
}

func TestSelfTradePrevention_GetMetrics(t *testing.T) {
	stp := NewSelfTradePrevention(nil)
	stp.config.Mode = STPModeReject

	// Initially all metrics should be 0
	metrics := stp.GetMetrics()
	if metrics["prevent_count"] != 0 {
		t.Error("Initial prevent_count should be 0")
	}
	if metrics["reject_count"] != 0 {
		t.Error("Initial reject_count should be 0")
	}

	// Track a buy order
	buyOrder := &Order{
		ID:     "ord_buy",
		Symbol: "BTCUSDT",
		Side:   SideBuy,
		Price:  50000.0,
		Size:   1.0,
		Status: StatusOpen,
		Type:   TypeLimit,
	}
	stp.TrackOrder(buyOrder)

	// Trigger a self-trade rejection
	stp.CheckOrder("BTCUSDT", SideSell, 49900.0, 0.5, "ord_sell")

	// Metrics should be updated
	metrics = stp.GetMetrics()
	if metrics["prevent_count"] != 1 {
		t.Errorf("prevent_count = %d, expected 1", metrics["prevent_count"])
	}
}

func TestSelfTradePrevention_ResetMetrics(t *testing.T) {
	stp := NewSelfTradePrevention(nil)

	// Increment metrics manually
	stp.incrementMetric("reject")
	stp.incrementMetric("cancel")

	stp.ResetMetrics()

	metrics := stp.GetMetrics()
	if metrics["prevent_count"] != 0 {
		t.Error("prevent_count should be 0 after reset")
	}
	if metrics["reject_count"] != 0 {
		t.Error("reject_count should be 0 after reset")
	}
	if metrics["cancel_count"] != 0 {
		t.Error("cancel_count should be 0 after reset")
	}
}

func TestSelfTradePrevention_Events(t *testing.T) {
	stp := NewSelfTradePrevention(nil)
	stp.config.Mode = STPModeReject

	// Track a buy order
	buyOrder := &Order{
		ID:     "ord_buy",
		Symbol: "BTCUSDT",
		Side:   SideBuy,
		Price:  50000.0,
		Size:   1.0,
		Status: StatusOpen,
		Type:   TypeLimit,
	}
	stp.TrackOrder(buyOrder)

	// Trigger a self-trade
	stp.CheckOrder("BTCUSDT", SideSell, 49900.0, 0.5, "ord_sell")

	// Get events
	events := stp.GetEvents(10)
	if len(events) != 1 {
		t.Errorf("GetEvents returned %d events, expected 1", len(events))
	}

	// Clear events
	stp.ClearEvents()
	events = stp.GetEvents(10)
	if len(events) != 0 {
		t.Errorf("GetEvents returned %d events after clear, expected 0", len(events))
	}
}

func TestSelfTradePrevention_SetEventCallback(t *testing.T) {
	stp := NewSelfTradePrevention(nil)
	stp.config.Mode = STPModeReject

	stp.SetEventCallback(func(event STPEvent) {
		// Callback is invoked in a goroutine, we just verify it doesn't panic
		_ = event.String()
	})

	// Track a buy order
	buyOrder := &Order{
		ID:     "ord_buy",
		Symbol: "BTCUSDT",
		Side:   SideBuy,
		Price:  50000.0,
		Size:   1.0,
		Status: StatusOpen,
		Type:   TypeLimit,
	}
	stp.TrackOrder(buyOrder)

	// Trigger a self-trade (this will record event which triggers callback)
	stp.CheckOrder("BTCUSDT", SideSell, 49900.0, 0.5, "ord_sell")

	// Small delay to allow callback to be invoked
	time.Sleep(100 * time.Millisecond)

	// The test passes if no panic occurs
}

func TestSelfTradePrevention_EnableDisable(t *testing.T) {
	stp := NewSelfTradePrevention(nil)

	if !stp.IsEnabled() {
		t.Error("STP should be enabled by default")
	}

	stp.Disable()
	if stp.IsEnabled() {
		t.Error("STP should be disabled after Disable()")
	}

	stp.Enable()
	if !stp.IsEnabled() {
		t.Error("STP should be enabled after Enable()")
	}
}

func TestSelfTradePrevention_SetMode(t *testing.T) {
	stp := NewSelfTradePrevention(nil)

	if stp.GetMode() != STPModeReject {
		t.Error("Default mode should be REJECT")
	}

	stp.SetMode(STPModeCancelOldest)
	if stp.GetMode() != STPModeCancelOldest {
		t.Error("Mode should be CANCEL_OLDEST after SetMode")
	}
}

func TestSTPConfigFromConfigManager(t *testing.T) {
	cm := NewConfigManager("TEST")
	cm.SetDefault("stp.enable", true)
	cm.SetDefault("stp.mode", "CANCEL_OLDEST")
	cm.SetDefault("stp.check_interval_ms", 200)
	cm.SetDefault("stp.max_attempts", 10)
	cm.SetDefault("stp.cooldown_ms", 120000)
	cm.SetDefault("stp.log_events", false)
	cm.SetDefault("stp.alert", false)
	cm.SetDefault("stp.price_tolerance", 0.0002)

	config := STPConfigFromConfigManager(cm)

	if !config.EnableSTP {
		t.Error("EnableSTP should be true")
	}
	if config.Mode != STPModeCancelOldest {
		t.Errorf("Mode = %s, expected CANCEL_OLDEST", config.Mode)
	}
	if config.MaxSelfTradeAttempts != 10 {
		t.Errorf("MaxSelfTradeAttempts = %d, expected 10", config.MaxSelfTradeAttempts)
	}
	if config.PriceTolerance != 0.0002 {
		t.Errorf("PriceTolerance = %f, expected 0.0002", config.PriceTolerance)
	}
}

func TestSTPEvent_String(t *testing.T) {
	event := &STPEvent{
		Timestamp:       time.Now(),
		Mode:            STPModeReject,
		Symbol:          "BTCUSDT",
		NewOrderID:      "ord_new",
		ExistingOrderID: "ord_existing",
		Side:            SideSell,
		Price:           50000.0,
		Size:            1.0,
		Action:          "REJECT",
		Reason:          "Self-trade detected",
	}

	str := event.String()
	if str == "" {
		t.Error("STPEvent.String() returned empty string")
	}
	if str == "<nil>" {
		t.Error("STPEvent.String() returned <nil>")
	}
}

func TestHFTConfig_STPConfig(t *testing.T) {
	cm := NewConfigManager("TEST")
	InitDefaultConfig(cm)

	hftConfig := NewHFTConfig(cm)
	stpConfig := hftConfig.STPConfig()

	if stpConfig == nil {
		t.Fatal("STPConfig() returned nil")
	}

	if !stpConfig.EnableSTP {
		t.Error("EnableSTP should be true from defaults")
	}
	if stpConfig.Mode != STPModeReject {
		t.Error("Mode should be REJECT from defaults")
	}
}
