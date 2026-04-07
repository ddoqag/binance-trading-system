package main

import (
	"testing"
	"time"
)

func TestDefenseIntegratedEngine(t *testing.T) {
	// Create engine config
	engineConfig := DefaultConfig("BTCUSDT")
	engineConfig.PaperTrading = true

	// Create defense config
	defenseConfig := DefaultDefenseIntegrationConfig()
	defenseConfig.Enabled = true
	defenseConfig.LogDefenseEvents = false

	// Create integrated engine
	engine, err := NewDefenseIntegratedEngine(engineConfig, defenseConfig)
	if err != nil {
		t.Fatalf("Failed to create engine: %v", err)
	}

	// Test defense status
	status := engine.GetDefenseStatus()
	// Check if FSM state exists
	if _, ok := status["fsm"]; !ok {
		t.Error("Expected FSM status to be present")
	}

	t.Log("Defense integrated engine created successfully")
}

func TestCanPlaceOrder(t *testing.T) {
	engineConfig := DefaultConfig("BTCUSDT")
	engineConfig.PaperTrading = true

	defenseConfig := DefaultDefenseIntegrationConfig()
	defenseConfig.Enabled = true
	defenseConfig.LogDefenseEvents = false

	engine, err := NewDefenseIntegratedEngine(engineConfig, defenseConfig)
	if err != nil {
		t.Fatalf("Failed to create engine: %v", err)
	}

	// Initially should allow all orders
	canPlace, reason := engine.CanPlaceOrder("buy", 0.01)
	if !canPlace {
		t.Errorf("Expected to allow buy order initially, got reason: %s", reason)
	}

	// Simulate toxic mode with buy pressure
	fsmState := DefenseMarketState{
		ToxicScore:       0.9,
		ToxicSide:        SideBuyPressure,
		RecentVolatility: 0.5,
	}
	engine.defenseMgr.fsm.UpdateMarketState(fsmState)

	// In toxic mode with buy pressure:
	// - Buy pressure means many buy orders in market
	// - Should ALLOW sell orders (can be filled by buyers, earn rebate)
	// - Should BLOCK buy orders (dangerous to buy when buy pressure is high)
	canPlace, reason = engine.CanPlaceOrder("sell", 0.01)
	if !canPlace {
		t.Error("Expected to ALLOW sell orders in toxic mode with buy pressure (safe side)")
	}

	// Buy orders should be blocked
	canPlace, reason = engine.CanPlaceOrder("buy", 0.01)
	if canPlace {
		t.Error("Expected to block buy orders in toxic mode with buy pressure")
	}
	if reason != "bid_side_disabled_by_defense" {
		t.Errorf("Expected reason 'bid_side_disabled_by_defense', got '%s'", reason)
	}
}

func TestProcessDecisionWithDefense(t *testing.T) {
	engineConfig := DefaultConfig("BTCUSDT")
	engineConfig.PaperTrading = true

	defenseConfig := DefaultDefenseIntegrationConfig()
	defenseConfig.Enabled = true
	defenseConfig.LogDefenseEvents = false
	defenseConfig.MaxOrdersInToxicMode = 2

	engine, err := NewDefenseIntegratedEngine(engineConfig, defenseConfig)
	if err != nil {
		t.Fatalf("Failed to create engine: %v", err)
	}

	// In normal mode, should allow decisions
	if !engine.ProcessDecisionWithDefense() {
		t.Error("Expected to allow decisions in normal mode")
	}

	// Simulate toxic mode
	fsmState := DefenseMarketState{
		ToxicScore:       0.9,
		ToxicSide:        SideNeutral,
		RecentVolatility: 0.5,
	}
	engine.defenseMgr.fsm.UpdateMarketState(fsmState)

	// Still should allow (no orders yet)
	if !engine.ProcessDecisionWithDefense() {
		t.Error("Expected to allow decisions when under max orders limit")
	}
}

func TestDefenseModeTransitions(t *testing.T) {
	engineConfig := DefaultConfig("BTCUSDT")
	engineConfig.PaperTrading = true

	defenseConfig := DefaultDefenseIntegrationConfig()
	defenseConfig.Enabled = true
	defenseConfig.LogDefenseEvents = true

	engine, err := NewDefenseIntegratedEngine(engineConfig, defenseConfig)
	if err != nil {
		t.Fatalf("Failed to create engine: %v", err)
	}

	// Test mode transitions
	testCases := []struct {
		toxicScore float64
		expected   string
	}{
		{0.3, "NORMAL"},
		{0.7, "DEFENSIVE"},
		{0.9, "TOXIC"},
	}

	for _, tc := range testCases {
		fsmState := DefenseMarketState{
			ToxicScore:       tc.toxicScore,
			RecentVolatility: 0.3,
		}

		if tc.toxicScore > 0.8 {
			// Wait for defensive cooldown
			time.Sleep(600 * time.Millisecond)
		}

		engine.defenseMgr.fsm.UpdateMarketState(fsmState)

		status := engine.GetDefenseStatus()
		fsmStatus, ok := status["fsm"].(map[string]interface{})
		if !ok {
			t.Error("Failed to get FSM status")
			continue
		}

		mode := fsmStatus["mode"].(string)
		t.Logf("Toxic score %.1f -> Mode: %s (expected: %s)",
			tc.toxicScore, mode, tc.expected)
	}
}

func TestDefenseCallbacks(t *testing.T) {
	engineConfig := DefaultConfig("BTCUSDT")
	engineConfig.PaperTrading = true

	defenseConfig := DefaultDefenseIntegrationConfig()
	defenseConfig.Enabled = true
	defenseConfig.AutoCancelOnToxic = true
	defenseConfig.LogDefenseEvents = false

	engine, err := NewDefenseIntegratedEngine(engineConfig, defenseConfig)
	if err != nil {
		t.Fatalf("Failed to create engine: %v", err)
	}

	// Track mode changes
	modeChanges := make([]string, 0)
	engine.defenseMgr.SetModeChangeCallback(func(from, to MarketMode, reason string) {
		modeChanges = append(modeChanges, from.String()+"->"+to.String())
	})

	// Trigger mode changes
	engine.defenseMgr.fsm.UpdateMarketState(DefenseMarketState{
		ToxicScore: 0.3,
	})

	time.Sleep(100 * time.Millisecond)

	engine.defenseMgr.fsm.UpdateMarketState(DefenseMarketState{
		ToxicScore: 0.7,
	})

	time.Sleep(600 * time.Millisecond)

	engine.defenseMgr.fsm.UpdateMarketState(DefenseMarketState{
		ToxicScore: 0.9,
	})

	if len(modeChanges) == 0 {
		t.Error("Expected mode change callbacks to be triggered")
	}

	for _, change := range modeChanges {
		t.Logf("Mode change: %s", change)
	}
}

func BenchmarkDefenseDecision(b *testing.B) {
	engineConfig := DefaultConfig("BTCUSDT")
	engineConfig.PaperTrading = true

	defenseConfig := DefaultDefenseIntegrationConfig()
	defenseConfig.Enabled = true
	defenseConfig.LogDefenseEvents = false

	engine, err := NewDefenseIntegratedEngine(engineConfig, defenseConfig)
	if err != nil {
		b.Fatalf("Failed to create engine: %v", err)
	}

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		engine.CanPlaceOrder("buy", 0.01)
	}
}
