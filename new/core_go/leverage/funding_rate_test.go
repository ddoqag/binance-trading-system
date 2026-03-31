package leverage

import (
	"math"
	"testing"
	"time"
)

func TestDefaultFundingRateConfig(t *testing.T) {
	config := DefaultFundingRateConfig()

	if config.SettlementInterval != 8*time.Hour {
		t.Errorf("Expected settlement interval 8h, got %v", config.SettlementInterval)
	}

	if config.MaxFundingRate != 0.01 {
		t.Errorf("Expected max funding rate 0.01, got %f", config.MaxFundingRate)
	}

	if config.MinFundingRate != -0.01 {
		t.Errorf("Expected min funding rate -0.01, got %f", config.MinFundingRate)
	}
}

func TestFundingRateCalculator_CalculateFundingRate(t *testing.T) {
	calc := NewFundingRateCalculator(nil)

	tests := []struct {
		premiumIndex  float64
		expectedRange []float64 // [min, max]
	}{
		{0.0005, []float64{0.00005, 0.0010}},  // 溢价0.05%，资金费受clamp限制
		{-0.0005, []float64{-0.0010, 0.00015}}, // 溢价-0.05%
		{0.0, []float64{0.0000, 0.0002}},      // 无溢价
	}

	for _, tt := range tests {
		rate := calc.CalculateFundingRate(tt.premiumIndex)
		if rate < tt.expectedRange[0] || rate > tt.expectedRange[1] {
			t.Errorf("Premium %.4f: expected rate in [%.4f, %.4f], got %.4f",
				tt.premiumIndex, tt.expectedRange[0], tt.expectedRange[1], rate)
		}
	}
}

func TestFundingRateCalculator_CalculateFundingPaymentWithRate(t *testing.T) {
	calc := NewFundingRateCalculator(nil)

	position := &LeveragedPosition{
		Symbol:     "BTCUSDT",
		Side:       SideLong,
		Size:       0.1,
		EntryPrice: 50000,
		Leverage:   3,
		Margin:     50000 * 0.1 / 3,
		Status:     PositionOpen,
	}

	markPrice := 50000.0
	fundingRate := 0.001 // 0.1%

	payment := calc.CalculateFundingPaymentWithRate(position, markPrice, fundingRate)

	if payment == nil {
		t.Fatal("Expected payment to not be nil")
	}

	// 名义价值 = 0.1 * 50000 = 5000
	// 资金费 = 5000 * 0.001 = 5
	expectedAmount := 5.0
	if math.Abs(payment.Amount-expectedAmount) > 0.01 {
		t.Errorf("Expected payment %.2f, got %.2f", expectedAmount, payment.Amount)
	}

	if payment.Rate != fundingRate {
		t.Errorf("Expected rate %.4f, got %.4f", fundingRate, payment.Rate)
	}
}

func TestFundingRateCalculator_CalculateFundingPaymentWithRate_Short(t *testing.T) {
	calc := NewFundingRateCalculator(nil)

	position := &LeveragedPosition{
		Symbol:     "BTCUSDT",
		Side:       SideShort,
		Size:       0.1,
		EntryPrice: 50000,
		Leverage:   3,
		Margin:     50000 * 0.1 / 3,
		Status:     PositionOpen,
	}

	markPrice := 50000.0
	fundingRate := 0.001 // 0.1%

	payment := calc.CalculateFundingPaymentWithRate(position, markPrice, fundingRate)

	if payment == nil {
		t.Fatal("Expected payment to not be nil")
	}

	// 空头在正资金费率时收入
	expectedAmount := -5.0 // 负号表示收入
	if payment.Amount > 0 {
		t.Errorf("Expected negative amount for short, got %.2f", payment.Amount)
	}
	if math.Abs(payment.Amount-expectedAmount) > 0.01 {
		t.Errorf("Expected payment %.2f, got %.2f", expectedAmount, payment.Amount)
	}
}

func TestFundingRateCalculator_EstimateDailyFundingCost(t *testing.T) {
	calc := NewFundingRateCalculator(nil)

	// 每天3次结算
	dailyCost := calc.EstimateDailyFundingCost(0.1, 50000, 0.001, SideLong)
	expected := 15.0 // 5 * 3

	if math.Abs(dailyCost-expected) > 0.01 {
		t.Errorf("Expected daily cost %.2f, got %.2f", expected, dailyCost)
	}

	// 空头应该收入
	dailyCostShort := calc.EstimateDailyFundingCost(0.1, 50000, 0.001, SideShort)
	if dailyCostShort > 0 {
		t.Error("Expected negative daily cost for short")
	}
}

func TestFundingRateCalculator_CalculatePremiumIndex(t *testing.T) {
	calc := NewFundingRateCalculator(nil)

	// 合约买入价高于现货，卖出价低于现货 = 正溢价
	premium := calc.CalculatePremiumIndex(50100, 49900, 50000)
	if premium < 0 {
		t.Errorf("Expected positive or zero premium, got %.6f", premium)
	}

	// 合约买入价低于现货，卖出价高于现货 = 负溢价
	premium = calc.CalculatePremiumIndex(49900, 50100, 50000)
	if premium > 0 {
		t.Errorf("Expected negative or zero premium, got %.6f", premium)
	}

	// 价格相等，溢价为0
	premium = calc.CalculatePremiumIndex(50000, 50000, 50000)
	if premium != 0 {
		t.Errorf("Expected zero premium, got %.6f", premium)
	}
}

func TestFundingRateManager_UpdateAndGetRate(t *testing.T) {
	calc := NewFundingRateCalculator(nil)
	pm := NewPositionManager()
	manager := NewFundingRateManager(nil, calc, pm)

	// 更新资金费率
	nextFunding := time.Now().Add(8 * time.Hour)
	manager.UpdateFundingRate("BTCUSDT", 0.001, nextFunding)

	// 获取当前费率
	rate := manager.GetCurrentRate("BTCUSDT")
	if rate == nil {
		t.Fatal("Expected rate to not be nil")
	}

	if rate.Symbol != "BTCUSDT" {
		t.Errorf("Expected symbol BTCUSDT, got %s", rate.Symbol)
	}

	if rate.Rate != 0.001 {
		t.Errorf("Expected rate 0.001, got %f", rate.Rate)
	}
}

func TestFundingRateManager_GetAllCurrentRates(t *testing.T) {
	calc := NewFundingRateCalculator(nil)
	pm := NewPositionManager()
	manager := NewFundingRateManager(nil, calc, pm)

	nextFunding := time.Now().Add(8 * time.Hour)
	manager.UpdateFundingRate("BTCUSDT", 0.001, nextFunding)
	manager.UpdateFundingRate("ETHUSDT", 0.0005, nextFunding)

	rates := manager.GetAllCurrentRates()
	if len(rates) != 2 {
		t.Errorf("Expected 2 rates, got %d", len(rates))
	}

	if rates["BTCUSDT"] == nil || rates["BTCUSDT"].Rate != 0.001 {
		t.Error("BTCUSDT rate not found or incorrect")
	}
}

func TestFundingRateManager_GetRateHistory(t *testing.T) {
	calc := NewFundingRateCalculator(nil)
	pm := NewPositionManager()
	manager := NewFundingRateManager(nil, calc, pm)

	// 添加多个历史记录
	nextFunding := time.Now().Add(8 * time.Hour)
	manager.UpdateFundingRate("BTCUSDT", 0.001, nextFunding)
	time.Sleep(10 * time.Millisecond)
	manager.UpdateFundingRate("BTCUSDT", 0.0015, nextFunding)

	// 获取最近1小时的历史
	history := manager.GetRateHistory("BTCUSDT", time.Now().Add(-1*time.Hour))
	if len(history) != 2 {
		t.Errorf("Expected 2 history entries, got %d", len(history))
	}
}

func TestFundingRateManager_StartStop(t *testing.T) {
	calc := NewFundingRateCalculator(nil)
	pm := NewPositionManager()
	manager := NewFundingRateManager(nil, calc, pm)

	if manager.IsRunning() {
		t.Error("Manager should not be running initially")
	}

	manager.Start()
	time.Sleep(50 * time.Millisecond)

	if !manager.IsRunning() {
		t.Error("Manager should be running after Start()")
	}

	manager.Stop()

	if manager.IsRunning() {
		t.Error("Manager should not be running after Stop()")
	}
}

func TestFundingRateManager_GetTotalFundingCost(t *testing.T) {
	calc := NewFundingRateCalculator(nil)
	pm := NewPositionManager()
	manager := NewFundingRateManager(nil, calc, pm)

	// 模拟支付记录
	manager.payments = []*FundingPayment{
		{Symbol: "BTCUSDT", Amount: -5.0},  // 支出5
		{Symbol: "BTCUSDT", Amount: -3.0},  // 支出3
		{Symbol: "BTCUSDT", Amount: 2.0},   // 收入2
		{Symbol: "ETHUSDT", Amount: -1.0},  // 其他symbol
	}

	total := manager.GetTotalFundingCost("BTCUSDT")
	expected := -6.0 // -5 - 3 + 2 = -6 (净支出)

	if total != expected {
		t.Errorf("Expected total cost %.2f, got %.2f", expected, total)
	}
}

func TestFundingPaymentEstimate(t *testing.T) {
	estimate := &FundingPaymentEstimate{
		Symbol:       "BTCUSDT",
		Side:         SideLong,
		Amount:       5.0,
		Rate:         0.001,
		PositionSize: 0.1,
		MarkPrice:    50000,
	}

	if !estimate.IsReceiving() {
		t.Error("Expected IsReceiving() to be true for positive amount")
	}

	daily := estimate.GetDailyEstimate()
	expectedDaily := 15.0 // 5 * 3
	if daily != expectedDaily {
		t.Errorf("Expected daily estimate %.2f, got %.2f", expectedDaily, daily)
	}

	weekly := estimate.GetWeeklyEstimate()
	expectedWeekly := 105.0 // 15 * 7
	if weekly != expectedWeekly {
		t.Errorf("Expected weekly estimate %.2f, got %.2f", expectedWeekly, weekly)
	}
}

func TestFundingRateManager_GetFundingSummary(t *testing.T) {
	calc := NewFundingRateCalculator(nil)
	pm := NewPositionManager()
	manager := NewFundingRateManager(nil, calc, pm)

	// 添加当前费率
	nextFunding := time.Now().Add(8 * time.Hour)
	manager.UpdateFundingRate("BTCUSDT", 0.001, nextFunding)

	// 模拟支付记录
	manager.payments = []*FundingPayment{
		{Symbol: "BTCUSDT", Amount: -5.0, Rate: 0.001},
		{Symbol: "BTCUSDT", Amount: -3.0, Rate: 0.0008},
		{Symbol: "BTCUSDT", Amount: 2.0, Rate: -0.0004},
	}

	summary := manager.GetFundingSummary("BTCUSDT")

	if summary.Symbol != "BTCUSDT" {
		t.Errorf("Expected symbol BTCUSDT, got %s", summary.Symbol)
	}

	if summary.SettlementCount != 3 {
		t.Errorf("Expected 3 settlements, got %d", summary.SettlementCount)
	}

	if summary.TotalPaid != 8.0 { // 5 + 3
		t.Errorf("Expected total paid 8.0, got %.2f", summary.TotalPaid)
	}

	if summary.TotalReceived != 2.0 {
		t.Errorf("Expected total received 2.0, got %.2f", summary.TotalReceived)
	}

	if summary.NetFunding != -6.0 { // 2 - 8
		t.Errorf("Expected net funding -6.0, got %.2f", summary.NetFunding)
	}

	if summary.CurrentRate != 0.001 {
		t.Errorf("Expected current rate 0.001, got %f", summary.CurrentRate)
	}
}
