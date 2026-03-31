package leverage

import (
	"testing"
	"time"
)

func TestCalculator_CalculateRealTimeMargin(t *testing.T) {
	calc := NewCalculator()

	position := &LeveragedPosition{
		Symbol:     "BTCUSDT",
		Side:       SideLong,
		Size:       0.1,
		EntryPrice: 50000,
		Leverage:   3,
		Margin:     50000 * 0.1 / 3,
		Status:     PositionOpen,
	}
	position.calculateLiquidationPrice()

	info := calc.CalculateRealTimeMargin(position, 50000)

	if info.Symbol != "BTCUSDT" {
		t.Errorf("Expected symbol BTCUSDT, got %s", info.Symbol)
	}

	if info.Side != SideLong {
		t.Error("Expected SideLong")
	}

	if info.UnrealizedPnL != 0 {
		t.Errorf("Expected unrealized PnL 0 at entry, got %f", info.UnrealizedPnL)
	}

	if info.MarginLevel != 1.0 {
		t.Errorf("Expected margin level 1.0 at entry, got %f", info.MarginLevel)
	}

	info = calc.CalculateRealTimeMargin(position, 55000)
	if info.UnrealizedPnL != 500.0 {
		t.Errorf("Expected unrealized PnL 500, got %f", info.UnrealizedPnL)
	}

	if info.MarginLevel <= 1.0 {
		t.Errorf("Expected margin level > 1.0 when profitable, got %f", info.MarginLevel)
	}
}

func TestRealTimeMarginMonitor(t *testing.T) {
	calc := NewCalculator()
	monitor := NewRealTimeMarginMonitor(calc)

	position := &LeveragedPosition{
		Symbol:     "BTCUSDT",
		Side:       SideLong,
		Size:       0.1,
		EntryPrice: 50000,
		Leverage:   3,
		Margin:     50000 * 0.1 / 3,
		Status:     PositionOpen,
	}
	position.calculateLiquidationPrice()

	monitor.RegisterPosition(position)
	monitor.UpdateMarkPrice("BTCUSDT", 52000)

	infos := monitor.GetAllMarginInfo()
	if len(infos) != 1 {
		t.Errorf("Expected 1 margin info, got %d", len(infos))
	}

	monitor.UnregisterPosition("BTCUSDT", SideLong)
	infos = monitor.GetAllMarginInfo()
	if len(infos) != 0 {
		t.Errorf("Expected 0 margin info after unregister, got %d", len(infos))
	}
}

func TestRealTimeMarginMonitor_StartStop(t *testing.T) {
	calc := NewCalculator()
	monitor := NewRealTimeMarginMonitor(calc)

	position := &LeveragedPosition{
		Symbol:     "BTCUSDT",
		Side:       SideLong,
		Size:       0.1,
		EntryPrice: 50000,
		Leverage:   3,
		Margin:     50000 * 0.1 / 3,
		Status:     PositionOpen,
	}

	monitor.RegisterPosition(position)
	monitor.UpdateMarkPrice("BTCUSDT", 50000)

	monitor.Start()
	time.Sleep(50 * time.Millisecond)
	monitor.Stop()
}
