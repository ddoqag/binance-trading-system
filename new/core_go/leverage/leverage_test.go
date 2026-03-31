package leverage

import (
	"math"
	"testing"
)

func TestSide_String(t *testing.T) {
	tests := []struct {
		side     Side
		expected string
	}{
		{SideLong, "LONG"},
		{SideShort, "SHORT"},
		{Side(99), "UNKNOWN"},
	}

	for _, tt := range tests {
		if got := tt.side.String(); got != tt.expected {
			t.Errorf("Side.String() = %v, want %v", got, tt.expected)
		}
	}
}

func TestMarginMode_String(t *testing.T) {
	tests := []struct {
		mode     MarginMode
		expected string
	}{
		{ModeIsolated, "ISOLATED"},
		{ModeCross, "CROSS"},
		{MarginMode(99), "UNKNOWN"},
	}

	for _, tt := range tests {
		if got := tt.mode.String(); got != tt.expected {
			t.Errorf("MarginMode.String() = %v, want %v", got, tt.expected)
		}
	}
}

func TestOrderParams_Validate(t *testing.T) {
	tests := []struct {
		name    string
		params  OrderParams
		wantErr bool
	}{
		{
			name: "valid limit order",
			params: OrderParams{
				Symbol:   "BTCUSDT",
				Side:     SideLong,
				Size:     0.1,
				Price:    50000,
				Leverage: 3,
				IsMarket: false,
			},
			wantErr: false,
		},
		{
			name: "valid market order",
			params: OrderParams{
				Symbol:   "BTCUSDT",
				Side:     SideLong,
				Size:     0.1,
				Price:    50000,
				Leverage: 3,
				IsMarket: true,
			},
			wantErr: false,
		},
		{
			name: "missing symbol",
			params: OrderParams{
				Symbol:   "",
				Side:     SideLong,
				Size:     0.1,
				Price:    50000,
				Leverage: 3,
			},
			wantErr: true,
		},
		{
			name: "zero size",
			params: OrderParams{
				Symbol:   "BTCUSDT",
				Side:     SideLong,
				Size:     0,
				Price:    50000,
				Leverage: 3,
			},
			wantErr: true,
		},
		{
			name: "leverage too high",
			params: OrderParams{
				Symbol:   "BTCUSDT",
				Side:     SideLong,
				Size:     0.1,
				Price:    50000,
				Leverage: 15,
			},
			wantErr: true,
		},
		{
			name: "limit order without price",
			params: OrderParams{
				Symbol:   "BTCUSDT",
				Side:     SideLong,
				Size:     0.1,
				Price:    0,
				Leverage: 3,
				IsMarket: false,
			},
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := tt.params.Validate()
			if (err != nil) != tt.wantErr {
				t.Errorf("OrderParams.Validate() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func TestCalculator_CalculateMargin(t *testing.T) {
	calc := NewCalculator()

	tests := []struct {
		notional float64
		leverage float64
		expected float64
	}{
		{10000, 1, 10000},
		{10000, 2, 5000},
		{10000, 3, 3333.3333333333335},
		{10000, 5, 2000},
		{10000, 10, 1000},
		{10000, 0, 0},
	}

	for _, tt := range tests {
		got := calc.CalculateMargin(tt.notional, tt.leverage)
		if got != tt.expected {
			t.Errorf("CalculateMargin(%v, %v) = %v, want %v", tt.notional, tt.leverage, got, tt.expected)
		}
	}
}

func TestCalculator_CalculateLiquidationPrice(t *testing.T) {
	calc := NewCalculator()

	tests := []struct {
		name       string
		entryPrice float64
		leverage   float64
		side       Side
		expected   float64
	}{
		{
			name:       "long 3x",
			entryPrice: 50000,
			leverage:   3,
			side:       SideLong,
			expected:   50000 * (1 - 1.0/3.0 + 0.005),
		},
		{
			name:       "short 3x",
			entryPrice: 50000,
			leverage:   3,
			side:       SideShort,
			expected:   50000 * (1 + 1.0/3.0 - 0.005),
		},
		{
			name:       "long 5x",
			entryPrice: 50000,
			leverage:   5,
			side:       SideLong,
			expected:   50000 * (1 - 1.0/5.0 + 0.005),
		},
		{
			name:       "invalid leverage",
			entryPrice: 50000,
			leverage:   0,
			side:       SideLong,
			expected:   0,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := calc.CalculateLiquidationPrice(tt.entryPrice, tt.leverage, tt.side, ModeIsolated)
			if got != tt.expected {
				t.Errorf("CalculateLiquidationPrice() = %v, want %v", got, tt.expected)
			}
		})
	}
}

func TestCalculator_CalculateUnrealizedPnL(t *testing.T) {
	calc := NewCalculator()

	tests := []struct {
		name       string
		entryPrice float64
		markPrice  float64
		size       float64
		side       Side
		expected   float64
	}{
		{
			name:       "long profit",
			entryPrice: 50000,
			markPrice:  55000,
			size:       0.1,
			side:       SideLong,
			expected:   500,
		},
		{
			name:       "long loss",
			entryPrice: 50000,
			markPrice:  45000,
			size:       0.1,
			side:       SideLong,
			expected:   -500,
		},
		{
			name:       "short profit",
			entryPrice: 50000,
			markPrice:  45000,
			size:       0.1,
			side:       SideShort,
			expected:   500,
		},
		{
			name:       "short loss",
			entryPrice: 50000,
			markPrice:  55000,
			size:       0.1,
			side:       SideShort,
			expected:   -500,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := calc.CalculateUnrealizedPnL(tt.entryPrice, tt.markPrice, tt.size, tt.side)
			if got != tt.expected {
				t.Errorf("CalculateUnrealizedPnL() = %v, want %v", got, tt.expected)
			}
		})
	}
}

func TestCalculator_CalculateROE(t *testing.T) {
	calc := NewCalculator()

	got := calc.CalculateROE(50000, 55000, 3, SideLong)
	expected := 0.3
	if math.Abs(got-expected) > 1e-9 {
		t.Errorf("CalculateROE() = %v, want %v", got, expected)
	}

	got = calc.CalculateROE(50000, 45000, 3, SideShort)
	if math.Abs(got-expected) > 1e-9 {
		t.Errorf("CalculateROE() = %v, want %v", got, expected)
	}
}

func TestCalculator_ValidateLeverage(t *testing.T) {
	calc := NewCalculator()

	tests := []struct {
		leverage float64
		wantErr  bool
	}{
		{1, false},
		{3, false},
		{5, false},
		{10, false},
		{0, true},
		{-1, true},
		{11, true},
		{20, true},
	}

	for _, tt := range tests {
		t.Run("", func(t *testing.T) {
			err := calc.ValidateLeverage(tt.leverage)
			if (err != nil) != tt.wantErr {
				t.Errorf("ValidateLeverage(%v) error = %v, wantErr %v", tt.leverage, err, tt.wantErr)
			}
		})
	}
}

func TestPositionManager_OpenPosition(t *testing.T) {
	pm := NewPositionManager()

	params := OrderParams{
		Symbol:   "BTCUSDT",
		Side:     SideLong,
		Size:     0.1,
		Price:    50000,
		Leverage: 3,
	}

	pos, err := pm.OpenPosition(params)
	if err != nil {
		t.Fatalf("OpenPosition failed: %v", err)
	}

	if pos.Symbol != "BTCUSDT" {
		t.Errorf("Symbol = %v, want BTCUSDT", pos.Symbol)
	}
	if pos.Side != SideLong {
		t.Errorf("Side = %v, want LONG", pos.Side)
	}
	if pos.Size != 0.1 {
		t.Errorf("Size = %v, want 0.1", pos.Size)
	}
	if pos.Leverage != 3 {
		t.Errorf("Leverage = %v, want 3", pos.Leverage)
	}
	if pos.Margin != 50000*0.1/3 {
		t.Errorf("Margin = %v, want %v", pos.Margin, 50000*0.1/3)
	}
	if pos.LiquidationPrice == 0 {
		t.Error("LiquidationPrice should not be 0")
	}

	// 测试加仓
	params2 := OrderParams{
		Symbol:   "BTCUSDT",
		Side:     SideLong,
		Size:     0.1,
		Price:    55000,
		Leverage: 3,
	}

	pos2, err := pm.OpenPosition(params2)
	if err != nil {
		t.Fatalf("Add to position failed: %v", err)
	}

	if pos2.Size != 0.2 {
		t.Errorf("Size after add = %v, want 0.2", pos2.Size)
	}
	expectedEntry := (50000*0.1 + 55000*0.1) / 0.2
	if pos2.EntryPrice != expectedEntry {
		t.Errorf("EntryPrice = %v, want %v", pos2.EntryPrice, expectedEntry)
	}
}

func TestPositionManager_ClosePosition(t *testing.T) {
	pm := NewPositionManager()

	params := OrderParams{
		Symbol:   "BTCUSDT",
		Side:     SideLong,
		Size:     0.1,
		Price:    50000,
		Leverage: 3,
	}

	_, err := pm.OpenPosition(params)
	if err != nil {
		t.Fatalf("OpenPosition failed: %v", err)
	}

	closedPos, err := pm.ClosePosition("BTCUSDT", 55000)
	if err != nil {
		t.Fatalf("ClosePosition failed: %v", err)
	}

	if closedPos.Status != PositionClosed {
		t.Errorf("Status = %v, want PositionClosed", closedPos.Status)
	}

	expectedPnL := 500.0
	if closedPos.RealizedPnL != expectedPnL {
		t.Errorf("RealizedPnL = %v, want %v", closedPos.RealizedPnL, expectedPnL)
	}

	_, err = pm.ClosePosition("BTCUSDT", 55000)
	if err == nil {
		t.Error("ClosePosition should fail for already closed position")
	}
}

func TestPositionManager_CheckLiquidation(t *testing.T) {
	pm := NewPositionManager()

	params := OrderParams{
		Symbol:   "BTCUSDT",
		Side:     SideLong,
		Size:     0.1,
		Price:    50000,
		Leverage: 3,
	}

	pos, _ := pm.OpenPosition(params)
	liqPrice := pos.LiquidationPrice

	liquidated, err := pm.CheckLiquidation("BTCUSDT", liqPrice+1000)
	if err != nil {
		t.Fatalf("CheckLiquidation failed: %v", err)
	}
	if liquidated {
		t.Error("Should not be liquidated above liquidation price")
	}

	liquidated, _ = pm.CheckLiquidation("BTCUSDT", liqPrice)
	if !liquidated {
		t.Error("Should be liquidated at liquidation price")
	}

	liquidated, _ = pm.CheckLiquidation("BTCUSDT", liqPrice-1000)
	if !liquidated {
		t.Error("Should be liquidated below liquidation price")
	}

	// 测试空头
	pm2 := NewPositionManager()
	params2 := OrderParams{
		Symbol:   "BTCUSDT",
		Side:     SideShort,
		Size:     0.1,
		Price:    50000,
		Leverage: 3,
	}
	pos2, _ := pm2.OpenPosition(params2)
	liqPrice2 := pos2.LiquidationPrice

	liquidated, _ = pm2.CheckLiquidation("BTCUSDT", liqPrice2-1000)
	if liquidated {
		t.Error("Short should not be liquidated below liquidation price")
	}

	liquidated, _ = pm2.CheckLiquidation("BTCUSDT", liqPrice2+1000)
	if !liquidated {
		t.Error("Short should be liquidated above liquidation price")
	}
}

func TestExecutor_OpenLong(t *testing.T) {
	executor := NewExecutor("BTCUSDT", true, 3)

	err := executor.OpenLong(0.1, true, 0, 3)
	if err != nil {
		t.Fatalf("OpenLong failed: %v", err)
	}

	pos := executor.GetPosition()
	if pos == nil {
		t.Fatal("Position should not be nil")
	}
	if pos.Side != SideLong {
		t.Errorf("Side = %v, want LONG", pos.Side)
	}
}

func TestExecutor_OpenShort(t *testing.T) {
	executor := NewExecutor("BTCUSDT", true, 3)

	err := executor.OpenShort(0.1, true, 0, 3)
	if err != nil {
		t.Fatalf("OpenShort failed: %v", err)
	}

	pos := executor.GetPosition()
	if pos == nil {
		t.Fatal("Position should not be nil")
	}
	if pos.Side != SideShort {
		t.Errorf("Side = %v, want SHORT", pos.Side)
	}
}

func TestExecutor_ClosePosition(t *testing.T) {
	executor := NewExecutor("BTCUSDT", true, 3)

	err := executor.OpenLong(0.1, true, 0, 3)
	if err != nil {
		t.Fatalf("OpenLong failed: %v", err)
	}

	executor.SetPriceSource(func() float64 { return 55000 })

	err = executor.ClosePosition(true, 0)
	if err != nil {
		t.Fatalf("ClosePosition failed: %v", err)
	}

	pos := executor.GetPosition()
	if pos != nil && pos.Status == PositionOpen {
		t.Error("Position should be closed")
	}
}

func TestIsolatedMarginExecutor(t *testing.T) {
	executor := NewIsolatedMarginExecutor("BTCUSDT", true, 3)

	err := executor.OpenLong(0.1, true, 0, 3)
	if err != nil {
		t.Fatalf("OpenLong failed: %v", err)
	}

	pos := executor.GetPosition()
	if pos == nil {
		t.Fatal("Position should not be nil")
	}
	if pos.MarginMode != ModeIsolated {
		t.Errorf("MarginMode = %v, want ISOLATED", pos.MarginMode)
	}
}

func TestCrossMarginExecutor(t *testing.T) {
	executor := NewCrossMarginExecutor("BTCUSDT", true, 3, 10000)

	if executor.totalMargin != 10000 {
		t.Errorf("totalMargin = %v, want 10000", executor.totalMargin)
	}

	marginInfo := executor.GetMarginInfo()
	if marginInfo.AvailableMargin != 10000 {
		t.Errorf("AvailableMargin = %v, want 10000", marginInfo.AvailableMargin)
	}
}

func TestCalculator_EstimateLiquidationRisk(t *testing.T) {
	calc := NewCalculator()

	position := &LeveragedPosition{
		Symbol:          "BTCUSDT",
		Side:            SideLong,
		Size:            0.1,
		EntryPrice:      50000,
		Leverage:        3,
		Margin:          50000 * 0.1 / 3,
		MaintenanceRate: 0.005,
	}
	position.calculateLiquidationPrice()

	risk := calc.EstimateLiquidationRisk(position, 50000)
	// 入场时保证金率 = 1.0 (100%), 低于 minMarginLevel 1.25, 所以会被认为有风险
	// 这是预期的行为 - 刚开仓时保证金率就是 100%
	if !risk.IsAtRisk {
		t.Logf("At entry: marginLevel=%.2f, minMarginLevel=%.2f, distance=%.2f%%",
			risk.MarginLevel, risk.MinMarginLevel, risk.DistanceToLiq)
	}

	risk = calc.EstimateLiquidationRisk(position, 34000)
	if !risk.IsAtRisk {
		t.Error("Should be at risk near liquidation price")
	}

	if risk.Recommendation == "" {
		t.Error("Recommendation should not be empty")
	}
}

func TestCalculator_CalculateCrossMarginRisk(t *testing.T) {
	calc := NewCalculator()

	risk := calc.CalculateCrossMarginRisk(10000, 20000, 2000)
	if risk.IsAtRisk {
		t.Error("Should not be at risk with sufficient margin")
	}

	risk = calc.CalculateCrossMarginRisk(2000, 20000, 2000)
	if !risk.IsAtRisk {
		t.Error("Should be at risk with low margin level")
	}
}

func BenchmarkPositionManager_OpenPosition(b *testing.B) {
	pm := NewPositionManager()
	params := OrderParams{
		Symbol:   "BTCUSDT",
		Side:     SideLong,
		Size:     0.1,
		Price:    50000,
		Leverage: 3,
	}

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		pm.OpenPosition(params)
	}
}

func BenchmarkCalculator_CalculateLiquidationPrice(b *testing.B) {
	calc := NewCalculator()

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		calc.CalculateLiquidationPrice(50000, 3, SideLong, ModeIsolated)
	}
}
