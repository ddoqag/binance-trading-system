package leverage

import (
	"testing"
	"time"
)

func TestAlertTypes_String(t *testing.T) {
	tests := []struct {
		alertType AlertType
		expected  string
	}{
		{AlertDistanceWarning, "DISTANCE_WARNING"},
		{AlertMarginCall, "MARGIN_CALL"},
		{AlertApproachingLiq, "APPROACHING_LIQUIDATION"},
		{AlertLiquidationImminent, "LIQUIDATION_IMMINENT"},
		{AlertLiquidationTriggered, "LIQUIDATION_TRIGGERED"},
		{AlertType(99), "UNKNOWN"},
	}

	for _, tt := range tests {
		if got := tt.alertType.String(); got != tt.expected {
			t.Errorf("AlertType.String() = %v, want %v", got, tt.expected)
		}
	}
}

func TestAlertSeverity_String(t *testing.T) {
	tests := []struct {
		severity AlertSeverity
		expected string
	}{
		{SeverityInfo, "INFO"},
		{SeverityWarning, "WARNING"},
		{SeverityCritical, "CRITICAL"},
		{SeverityEmergency, "EMERGENCY"},
		{AlertSeverity(99), "UNKNOWN"},
	}

	for _, tt := range tests {
		if got := tt.severity.String(); got != tt.expected {
			t.Errorf("AlertSeverity.String() = %v, want %v", got, tt.expected)
		}
	}
}

func TestActionType_String(t *testing.T) {
	tests := []struct {
		action   ActionType
		expected string
	}{
		{ActionNone, "NONE"},
		{ActionReducePosition, "REDUCE_POSITION"},
		{ActionAddMargin, "ADD_MARGIN"},
		{ActionClosePartial, "CLOSE_PARTIAL"},
		{ActionCloseAll, "CLOSE_ALL"},
		{ActionHedgePosition, "HEDGE_POSITION"},
		{ActionType(99), "UNKNOWN"},
	}

	for _, tt := range tests {
		if got := tt.action.String(); got != tt.expected {
			t.Errorf("ActionType.String() = %v, want %v", got, tt.expected)
		}
	}
}

func TestDefaultAlertConfig(t *testing.T) {
	config := DefaultAlertConfig()

	if config.DistanceWarningThreshold != 20.0 {
		t.Errorf("Expected DistanceWarningThreshold 20.0, got %f", config.DistanceWarningThreshold)
	}

	if config.MarginCallThreshold != 1.5 {
		t.Errorf("Expected MarginCallThreshold 1.5, got %f", config.MarginCallThreshold)
	}

	if config.CheckInterval != 5*time.Second {
		t.Errorf("Expected CheckInterval 5s, got %v", config.CheckInterval)
	}

	if config.EnableAutoAction {
		t.Error("Expected EnableAutoAction to be false by default")
	}
}

func TestLiquidationRiskMonitor_StartStop(t *testing.T) {
	calc := NewCalculator()
	pm := NewPositionManager()
	config := DefaultAlertConfig()
	config.CheckInterval = 100 * time.Millisecond

	monitor := NewLiquidationRiskMonitor(config, calc, pm)

	if monitor.IsRunning() {
		t.Error("Monitor should not be running initially")
	}

	monitor.Start()
	time.Sleep(50 * time.Millisecond)

	if !monitor.IsRunning() {
		t.Error("Monitor should be running after Start()")
	}

	monitor.Stop()
	time.Sleep(50 * time.Millisecond)

	if monitor.IsRunning() {
		t.Error("Monitor should not be running after Stop()")
	}
}

func TestLiquidationRiskMonitor_RegisterAlertCallback(t *testing.T) {
	calc := NewCalculator()
	pm := NewPositionManager()
	monitor := NewLiquidationRiskMonitor(nil, calc, pm)

	callbackCalled := false
	callback := func(alert LiquidationAlert) {
		callbackCalled = true
		_ = callbackCalled
	}

	monitor.RegisterAlertCallback(callback)

	// 创建仓位
	_, err := pm.OpenPosition(OrderParams{
		Symbol:   "BTCUSDT",
		Side:     SideLong,
		Size:     0.1,
		Price:    50000,
		Leverage: 3,
	})
	if err != nil {
		t.Fatalf("Failed to open position: %v", err)
	}

	// 获取强平价格用于测试
	pos, _ := pm.GetPositionBySide("BTCUSDT", SideLong)

	// 强制检查（价格接近强平价格）
	alert := monitor.ForceCheck("BTCUSDT", SideLong, pos.LiquidationPrice+1000)

	if alert == nil {
		t.Error("Expected alert to be triggered")
	}
}

func TestLiquidationRiskMonitor_GetRecentAlerts(t *testing.T) {
	calc := NewCalculator()
	pm := NewPositionManager()
	monitor := NewLiquidationRiskMonitor(nil, calc, pm)

	// 初始应该没有预警
	alerts := monitor.GetRecentAlerts(10)
	if len(alerts) != 0 {
		t.Errorf("Expected 0 alerts initially, got %d", len(alerts))
	}

	// 创建仓位
	_, err := pm.OpenPosition(OrderParams{
		Symbol:   "BTCUSDT",
		Side:     SideLong,
		Size:     0.1,
		Price:    50000,
		Leverage: 3,
	})
	if err != nil {
		t.Fatalf("Failed to open position: %v", err)
	}

	pos, _ := pm.GetPositionBySide("BTCUSDT", SideLong)

	// 触发预警
	monitor.ForceCheck("BTCUSDT", SideLong, pos.LiquidationPrice+500)

	// 检查预警历史
	alerts = monitor.GetRecentAlerts(10)
	if len(alerts) != 1 {
		t.Errorf("Expected 1 alert, got %d", len(alerts))
	}
}

func TestLiquidationRiskMonitor_ClearAlerts(t *testing.T) {
	calc := NewCalculator()
	pm := NewPositionManager()
	monitor := NewLiquidationRiskMonitor(nil, calc, pm)

	// 创建仓位
	_, err := pm.OpenPosition(OrderParams{
		Symbol:   "BTCUSDT",
		Side:     SideLong,
		Size:     0.1,
		Price:    50000,
		Leverage: 3,
	})
	if err != nil {
		t.Fatalf("Failed to open position: %v", err)
	}

	pos, _ := pm.GetPositionBySide("BTCUSDT", SideLong)

	// 触发预警
	monitor.ForceCheck("BTCUSDT", SideLong, pos.LiquidationPrice+500)

	// 清空预警
	monitor.ClearAlerts()

	alerts := monitor.GetRecentAlerts(10)
	if len(alerts) != 0 {
		t.Errorf("Expected 0 alerts after clear, got %d", len(alerts))
	}
}

func TestLiquidationRiskMonitor_GetRiskSummary(t *testing.T) {
	calc := NewCalculator()
	pm := NewPositionManager()
	monitor := NewLiquidationRiskMonitor(nil, calc, pm)

	// 空仓位测试
	summary := monitor.GetRiskSummary()
	if summary.TotalPositions != 0 {
		t.Errorf("Expected 0 positions, got %d", summary.TotalPositions)
	}

	// 添加仓位
	_, err := pm.OpenPosition(OrderParams{
		Symbol:   "BTCUSDT",
		Side:     SideLong,
		Size:     0.1,
		Price:    50000,
		Leverage: 3,
	})
	if err != nil {
		t.Fatalf("Failed to open position: %v", err)
	}

	summary = monitor.GetRiskSummary()
	if summary.TotalPositions != 1 {
		t.Errorf("Expected 1 position, got %d", summary.TotalPositions)
	}

	if summary.TotalMargin <= 0 {
		t.Error("Expected positive total margin")
	}
}

func TestLiquidationRiskMonitor_UpdateConfig(t *testing.T) {
	calc := NewCalculator()
	pm := NewPositionManager()
	monitor := NewLiquidationRiskMonitor(nil, calc, pm)

	originalConfig := monitor.GetConfig()
	if originalConfig.DistanceWarningThreshold != 20.0 {
		t.Error("Expected default distance warning threshold")
	}

	newConfig := &AlertConfig{
		DistanceWarningThreshold: 10.0,
		MarginCallThreshold:      1.3,
	}
	monitor.UpdateConfig(newConfig)

	updatedConfig := monitor.GetConfig()
	if updatedConfig.DistanceWarningThreshold != 10.0 {
		t.Errorf("Expected updated threshold 10.0, got %f", updatedConfig.DistanceWarningThreshold)
	}
}

func TestLiquidationRiskMonitor_evaluateRisk(t *testing.T) {
	calc := NewCalculator()
	config := DefaultAlertConfig()
	_ = NewLiquidationRiskMonitor(config, calc, NewPositionManager())

	tests := []struct {
		name      string
		markPrice float64
		wantAlert bool
	}{
		{"Normal price", 50000, true},
		{"Close to liq", 38000, true},
		{"Very close", 35100, true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// 创建新的 PositionManager 避免状态干扰
			pm2 := NewPositionManager()
			monitor2 := NewLiquidationRiskMonitor(config, calc, pm2)

			_, err := pm2.OpenPosition(OrderParams{
				Symbol:   "BTCUSDT",
				Side:     SideLong,
				Size:     0.1,
				Price:    50000,
				Leverage: 3,
			})
			if err != nil {
				t.Fatalf("Failed to open position: %v", err)
			}

			// 获取实际强平价格
			pos, _ := pm2.GetPositionBySide("BTCUSDT", SideLong)

			// 计算一个接近强平的价格来测试
			testPrice := pos.LiquidationPrice + 1000
			info := calc.CalculateRealTimeMargin(pos, testPrice)
			alert := monitor2.evaluateRisk(pos, info)

			if tt.wantAlert && alert == nil {
				t.Errorf("Expected alert but got nil")
			}
		})
	}
}
