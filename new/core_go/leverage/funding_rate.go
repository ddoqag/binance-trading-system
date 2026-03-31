package leverage

import (
	"fmt"
	"math"
	"sync"
	"time"
)

// FundingRateConfig 资金费率配置
type FundingRateConfig struct {
	SettlementInterval time.Duration // 结算间隔 (默认8小时)
	MaxFundingRate     float64       // 最大资金费率
	MinFundingRate     float64       // 最小资金费率
	InterestRate       float64       // 固定利率 (默认0.01%)
	PremiumIndexWindow int           // 溢价指数窗口期 (分钟)
}

// DefaultFundingRateConfig 默认资金费率配置
func DefaultFundingRateConfig() *FundingRateConfig {
	return &FundingRateConfig{
		SettlementInterval: 8 * time.Hour,
		MaxFundingRate:     0.01,   // 1%
		MinFundingRate:     -0.01,  // -1%
		InterestRate:       0.0001, // 0.01%
		PremiumIndexWindow: 5,      // 5分钟
	}
}

// FundingRateCalculator 资金费率计算器
type FundingRateCalculator struct {
	config *FundingRateConfig
}

// NewFundingRateCalculator 创建资金费率计算器
func NewFundingRateCalculator(config *FundingRateConfig) *FundingRateCalculator {
	if config == nil {
		config = DefaultFundingRateConfig()
	}
	return &FundingRateCalculator{config: config}
}

// CalculateFundingRate 计算资金费率
// 公式: Funding Rate = Premium Index + clamp(Interest Rate - Premium Index, 0.05%, -0.05%)
func (c *FundingRateCalculator) CalculateFundingRate(premiumIndex float64) float64 {
	// 计算利率差值
	rateDiff := c.config.InterestRate - premiumIndex

	// 限制差值范围在 ±0.05%
	clampedDiff := math.Max(-0.0005, math.Min(0.0005, rateDiff))

	// 计算资金费率
	fundingRate := premiumIndex + clampedDiff

	// 限制最大/最小资金费率
	return math.Max(c.config.MinFundingRate, math.Min(c.config.MaxFundingRate, fundingRate))
}

// CalculateFundingPayment 计算资金费支付金额
// 公式: Payment = Position Size * Mark Price * Funding Rate
func (c *FundingRateCalculator) CalculateFundingPayment(position *LeveragedPosition, markPrice float64) *FundingPayment {
	if position == nil || position.Status != PositionOpen {
		return nil
	}

	notional := position.Size * markPrice
	amount := notional * 0 // 实际资金费率应该从FundingRate获取

	// 根据方向调整金额符号
	// 多头在资金费率为正时支付，为负时收入
	// 空头相反
	if position.Side == SideShort {
		amount = -amount // 空头方向相反
	}

	return &FundingPayment{
		Symbol:       position.Symbol,
		PositionID:   position.ID,
		Side:         position.Side,
		Amount:       amount,
		Rate:         0, // 实际费率
		PositionSize: position.Size,
		Timestamp:    time.Now(),
	}
}

// CalculateFundingPaymentWithRate 使用指定费率计算资金费
func (c *FundingRateCalculator) CalculateFundingPaymentWithRate(
	position *LeveragedPosition,
	markPrice float64,
	fundingRate float64,
) *FundingPayment {
	if position == nil || position.Status != PositionOpen {
		return nil
	}

	notional := position.Size * markPrice
	amount := notional * fundingRate

	// 根据方向调整
	if position.Side == SideShort {
		amount = -amount
	}

	return &FundingPayment{
		Symbol:       position.Symbol,
		PositionID:   position.ID,
		Side:         position.Side,
		Amount:       amount,
		Rate:         fundingRate,
		PositionSize: position.Size,
		Timestamp:    time.Now(),
	}
}

// EstimateDailyFundingCost 估算每日资金费成本
func (c *FundingRateCalculator) EstimateDailyFundingCost(
	positionSize float64,
	markPrice float64,
	fundingRate float64,
	side Side,
) float64 {
	notional := positionSize * markPrice
	dailyRate := fundingRate * 3 // 每天3次结算 (8小时一次)

	amount := notional * dailyRate
	if side == SideShort {
		amount = -amount
	}
	return amount
}

// CalculatePremiumIndex 计算溢价指数
// Premium Index = (Max(0, Impact Bid Price - Mark Price) - Max(0, Mark Price - Impact Ask Price)) / Mark Price
func (c *FundingRateCalculator) CalculatePremiumIndex(
	impactBidPrice float64,
	impactAskPrice float64,
	markPrice float64,
) float64 {
	if markPrice <= 0 {
		return 0
	}

	premiumBid := math.Max(0, impactBidPrice-markPrice)
	premiumAsk := math.Max(0, markPrice-impactAskPrice)

	return (premiumBid - premiumAsk) / markPrice
}

// FundingRateManager 资金费率管理器
type FundingRateManager struct {
	config          *FundingRateConfig
	calculator      *FundingRateCalculator
	currentRates    map[string]*FundingRate
	history         map[string][]*FundingRate
	payments        []*FundingPayment
	positionMgr     *PositionManager
	settlementTimer *time.Timer
	callbacks       []func(*FundingPayment)
	mu              sync.RWMutex
	running         bool
}

// NewFundingRateManager 创建资金费率管理器
func NewFundingRateManager(
	config *FundingRateConfig,
	calculator *FundingRateCalculator,
	positionMgr *PositionManager,
) *FundingRateManager {
	if config == nil {
		config = DefaultFundingRateConfig()
	}
	if calculator == nil {
		calculator = NewFundingRateCalculator(config)
	}

	return &FundingRateManager{
		config:       config,
		calculator:   calculator,
		currentRates: make(map[string]*FundingRate),
		history:      make(map[string][]*FundingRate),
		payments:     make([]*FundingPayment, 0),
		positionMgr:  positionMgr,
		callbacks:    make([]func(*FundingPayment), 0),
	}
}

// Start 开始资金费率管理
func (m *FundingRateManager) Start() {
	m.mu.Lock()
	defer m.mu.Unlock()

	if m.running {
		return
	}

	m.running = true
	m.scheduleNextSettlement()
}

// Stop 停止资金费率管理
func (m *FundingRateManager) Stop() {
	m.mu.Lock()
	defer m.mu.Unlock()

	if !m.running {
		return
	}

	m.running = false
	if m.settlementTimer != nil {
		m.settlementTimer.Stop()
	}
}

// IsRunning 检查是否运行中
func (m *FundingRateManager) IsRunning() bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.running
}

// scheduleNextSettlement 安排下次结算
func (m *FundingRateManager) scheduleNextSettlement() {
	if !m.running {
		return
	}

	// 计算到下一个8点、16点、0点(UTC)的时间
	now := time.Now().UTC()
	nextHour := ((now.Hour()/8 + 1) * 8) % 24
	nextSettlement := time.Date(now.Year(), now.Month(), now.Day(), nextHour, 0, 0, 0, time.UTC)
	if nextSettlement.Before(now) || nextSettlement.Equal(now) {
		nextSettlement = nextSettlement.Add(24 * time.Hour)
	}

	duration := nextSettlement.Sub(now)

	m.settlementTimer = time.AfterFunc(duration, func() {
		m.executeSettlement()
		m.scheduleNextSettlement()
	})
}

// executeSettlement 执行资金费结算
func (m *FundingRateManager) executeSettlement() {
	m.mu.Lock()
	defer m.mu.Unlock()

	positions := m.positionMgr.GetAllPositions()
	for _, position := range positions {
		m.settlePosition(position)
	}
}

// settlePosition 结算单个仓位
func (m *FundingRateManager) settlePosition(position *LeveragedPosition) {
	// 获取当前资金费率
	rate := m.GetCurrentRate(position.Symbol)
	if rate == nil {
		return
	}

	// 获取当前标记价格
	markPrice := position.MarkPrice
	if markPrice <= 0 {
		markPrice = position.EntryPrice
	}

	// 计算资金费
	payment := m.calculator.CalculateFundingPaymentWithRate(
		position,
		markPrice,
		rate.Rate,
	)

	if payment == nil {
		return
	}

	// 生成支付ID
	payment.ID = generateFundingPaymentID(position.Symbol, position.Side)
	payment.Timestamp = time.Now()

	// 记录支付
	m.payments = append(m.payments, payment)

	// 更新仓位已实现盈亏
	position.RealizedPnL += payment.Amount
	position.UpdatedAt = time.Now()

	// 触发回调
	for _, callback := range m.callbacks {
		go callback(payment)
	}

	// 记录日志
	direction := "支付"
	if payment.Amount > 0 {
		direction = "收入"
	}
	fmt.Printf("[FundingRate] %s %s 资金费: %.4f %s (费率: %.6f%%)\n",
		position.Symbol, position.Side, math.Abs(payment.Amount), direction, rate.Rate*100)
}

// generateFundingPaymentID 生成资金费支付ID
func generateFundingPaymentID(symbol string, side Side) string {
	return fmt.Sprintf("funding_%s_%s_%d", symbol, side, time.Now().UnixNano())
}

// UpdateFundingRate 更新资金费率
func (m *FundingRateManager) UpdateFundingRate(symbol string, rate float64, nextFunding time.Time) {
	m.mu.Lock()
	defer m.mu.Unlock()

	fundingRate := &FundingRate{
		Symbol:      symbol,
		Rate:        rate,
		NextFunding: nextFunding,
		Timestamp:   time.Now(),
	}

	m.currentRates[symbol] = fundingRate

	// 添加到历史记录
	if m.history[symbol] == nil {
		m.history[symbol] = make([]*FundingRate, 0)
	}
	m.history[symbol] = append(m.history[symbol], fundingRate)

	// 只保留最近100条历史记录
	if len(m.history[symbol]) > 100 {
		m.history[symbol] = m.history[symbol][len(m.history[symbol])-100:]
	}
}

// GetCurrentRate 获取当前资金费率
func (m *FundingRateManager) GetCurrentRate(symbol string) *FundingRate {
	m.mu.RLock()
	defer m.mu.RUnlock()

	return m.currentRates[symbol]
}

// GetRateHistory 获取资金费率历史
func (m *FundingRateManager) GetRateHistory(symbol string, since time.Time) []*FundingRate {
	m.mu.RLock()
	defer m.mu.RUnlock()

	history := m.history[symbol]
	if history == nil {
		return nil
	}

	var result []*FundingRate
	for _, rate := range history {
		if rate.Timestamp.After(since) {
			result = append(result, rate)
		}
	}
	return result
}

// GetAllCurrentRates 获取所有当前资金费率
func (m *FundingRateManager) GetAllCurrentRates() map[string]*FundingRate {
	m.mu.RLock()
	defer m.mu.RUnlock()

	result := make(map[string]*FundingRate)
	for symbol, rate := range m.currentRates {
		result[symbol] = rate
	}
	return result
}

// GetPayments 获取资金费支付记录
func (m *FundingRateManager) GetPayments(symbol string, since time.Time) []*FundingPayment {
	m.mu.RLock()
	defer m.mu.RUnlock()

	var result []*FundingPayment
	for _, payment := range m.payments {
		if (symbol == "" || payment.Symbol == symbol) && payment.Timestamp.After(since) {
			result = append(result, payment)
		}
	}
	return result
}

// GetTotalFundingCost 获取总资金费成本
func (m *FundingRateManager) GetTotalFundingCost(symbol string) float64 {
	m.mu.RLock()
	defer m.mu.RUnlock()

	total := 0.0
	for _, payment := range m.payments {
		if symbol == "" || payment.Symbol == symbol {
			total += payment.Amount
		}
	}
	return total
}

// RegisterCallback 注册资金费结算回调
func (m *FundingRateManager) RegisterCallback(callback func(*FundingPayment)) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.callbacks = append(m.callbacks, callback)
}

// EstimateNextPayment 预估下次资金费
func (m *FundingRateManager) EstimateNextPayment(position *LeveragedPosition) *FundingPaymentEstimate {
	if position == nil || position.Status != PositionOpen {
		return nil
	}

	rate := m.GetCurrentRate(position.Symbol)
	if rate == nil {
		return nil
	}

	markPrice := position.MarkPrice
	if markPrice <= 0 {
		markPrice = position.EntryPrice
	}

	notional := position.Size * markPrice
	amount := notional * rate.Rate

	if position.Side == SideShort {
		amount = -amount
	}

	return &FundingPaymentEstimate{
		Symbol:      position.Symbol,
		Side:        position.Side,
		Amount:      amount,
		Rate:        rate.Rate,
		NextFunding: rate.NextFunding,
		PositionSize: position.Size,
		MarkPrice:   markPrice,
	}
}

// FundingPaymentEstimate 资金费预估
type FundingPaymentEstimate struct {
	Symbol       string    `json:"symbol"`
	Side         Side      `json:"side"`
	Amount       float64   `json:"amount"`
	Rate         float64   `json:"rate"`
	NextFunding  time.Time `json:"next_funding"`
	PositionSize float64   `json:"position_size"`
	MarkPrice    float64   `json:"mark_price"`
}

// IsReceiving 是否收入资金费
func (e *FundingPaymentEstimate) IsReceiving() bool {
	return e.Amount > 0
}

// GetDailyEstimate 获取每日预估
func (e *FundingPaymentEstimate) GetDailyEstimate() float64 {
	return e.Amount * 3 // 每天3次
}

// GetWeeklyEstimate 获取每周预估
func (e *FundingPaymentEstimate) GetWeeklyEstimate() float64 {
	return e.GetDailyEstimate() * 7
}

// FundingSummary 资金费汇总
type FundingSummary struct {
	Symbol           string  `json:"symbol"`
	TotalPaid        float64 `json:"total_paid"`
	TotalReceived    float64 `json:"total_received"`
	NetFunding       float64 `json:"net_funding"`
	SettlementCount  int     `json:"settlement_count"`
	AverageRate      float64 `json:"average_rate"`
	CurrentRate      float64 `json:"current_rate"`
	NextEstimated    float64 `json:"next_estimated"`
}

// GetFundingSummary 获取资金费汇总
func (m *FundingRateManager) GetFundingSummary(symbol string) *FundingSummary {
	m.mu.RLock()
	defer m.mu.RUnlock()

	summary := &FundingSummary{
		Symbol: symbol,
	}

	// 统计支付记录
	var totalRate float64
	for _, payment := range m.payments {
		if payment.Symbol != symbol {
			continue
		}

		summary.SettlementCount++
		totalRate += payment.Rate

		if payment.Amount > 0 {
			summary.TotalReceived += payment.Amount
		} else {
			summary.TotalPaid += -payment.Amount
		}
	}

	summary.NetFunding = summary.TotalReceived - summary.TotalPaid

	if summary.SettlementCount > 0 {
		summary.AverageRate = totalRate / float64(summary.SettlementCount)
	}

	// 当前费率
	if rate := m.currentRates[symbol]; rate != nil {
		summary.CurrentRate = rate.Rate
	}

	return summary
}
