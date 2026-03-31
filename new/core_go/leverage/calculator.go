package leverage

import (
	"fmt"
	"math"
	"sync"
	"time"
)

// Calculator 保证金计算器
type Calculator struct {
	// 默认参数
	defaultMaintenanceRate float64 // 默认维持保证金率
	minMarginLevel         float64 // 最低保证金率要求
}

// NewCalculator 创建计算器
func NewCalculator() *Calculator {
	return &Calculator{
		defaultMaintenanceRate: 0.005, // 0.5%
		minMarginLevel:         1.25,  // 125%
	}
}

// SetDefaultParams 设置默认参数
func (c *Calculator) SetDefaultParams(maintenanceRate, minMarginLevel float64) {
	c.defaultMaintenanceRate = maintenanceRate
	c.minMarginLevel = minMarginLevel
}

// CalculateMargin 计算所需保证金
func (c *Calculator) CalculateMargin(notional, leverage float64) float64 {
	if leverage <= 0 {
		return 0
	}
	return notional / leverage
}

// CalculateNotional 计算名义价值
func (c *Calculator) CalculateNotional(size, price float64) float64 {
	return size * price
}

// CalculateLiquidationPrice 计算强平价格
func (c *Calculator) CalculateLiquidationPrice(entryPrice float64, leverage float64, side Side, marginMode MarginMode) float64 {
	if entryPrice <= 0 || leverage <= 0 {
		return 0
	}

	maintenanceRate := c.defaultMaintenanceRate

	if side == SideLong {
		// 多头强平价格
		liqPrice := entryPrice * (1 - 1/leverage + maintenanceRate)
		return math.Max(0, liqPrice)
	}

	// 空头强平价格
	liqPrice := entryPrice * (1 + 1/leverage - maintenanceRate)
	return math.Max(0, liqPrice)
}

// CalculateLiquidationPriceIsolated 计算隔离模式强平价格
func (c *Calculator) CalculateLiquidationPriceIsolated(entryPrice, size, margin float64, side Side) float64 {
	if entryPrice <= 0 || size <= 0 || margin <= 0 {
		return 0
	}

	maintenanceRate := c.defaultMaintenanceRate
	notional := entryPrice * size
	leverage := notional / margin

	if side == SideLong {
		liqPrice := entryPrice * (1 - 1/leverage + maintenanceRate)
		return math.Max(0, liqPrice)
	}

	liqPrice := entryPrice * (1 + 1/leverage - maintenanceRate)
	return math.Max(0, liqPrice)
}

// CalculateUnrealizedPnL 计算未实现盈亏
func (c *Calculator) CalculateUnrealizedPnL(entryPrice, markPrice, size float64, side Side) float64 {
	if side == SideLong {
		return (markPrice - entryPrice) * size
	}
	return (entryPrice - markPrice) * size
}

// CalculateROE 计算权益回报率 (Return on Equity)
func (c *Calculator) CalculateROE(entryPrice, markPrice float64, leverage float64, side Side) float64 {
	if entryPrice <= 0 || leverage <= 0 {
		return 0
	}

	priceChange := 0.0
	if side == SideLong {
		priceChange = (markPrice - entryPrice) / entryPrice
	} else {
		priceChange = (entryPrice - markPrice) / entryPrice
	}

	return priceChange * leverage
}

// CalculateMarginLevel 计算保证金率
func (c *Calculator) CalculateMarginLevel(equity, usedMargin float64) float64 {
	if usedMargin <= 0 {
		return math.Inf(1)
	}
	return equity / usedMargin
}

// CalculateMaxPositionSize 计算最大可开仓数量
func (c *Calculator) CalculateMaxPositionSize(availableMargin, price, leverage float64) float64 {
	if price <= 0 || leverage <= 0 {
		return 0
	}
	// 可用保证金 * 杠杆 / 价格
	return availableMargin * leverage / price
}

// CalculateAvailableMargin 计算可用保证金
func (c *Calculator) CalculateAvailableMargin(totalMargin, usedMargin, unrealizedPnL float64) float64 {
	available := totalMargin - usedMargin + unrealizedPnL
	return math.Max(0, available)
}

// CheckMarginCall 检查是否触发追加保证金
func (c *Calculator) CheckMarginCall(equity, usedMargin float64) (bool, float64) {
	marginLevel := c.CalculateMarginLevel(equity, usedMargin)
	return marginLevel < c.minMarginLevel, marginLevel
}

// CalculateDistanceToLiquidation 计算距离强平的百分比距离
func (c *Calculator) CalculateDistanceToLiquidation(currentPrice, liqPrice float64, side Side) float64 {
	if currentPrice <= 0 || liqPrice <= 0 {
		return 0
	}

	distance := math.Abs(currentPrice-liqPrice) / currentPrice
	return distance * 100 // 返回百分比
}

// CalculateLeverageFromMargin 从保证金计算杠杆
func (c *Calculator) CalculateLeverageFromMargin(notional, margin float64) float64 {
	if margin <= 0 {
		return 0
	}
	return notional / margin
}

// CalculateMaintenanceMargin 计算维持保证金
func (c *Calculator) CalculateMaintenanceMargin(notional float64) float64 {
	return notional * c.defaultMaintenanceRate
}

// ValidateLeverage 验证杠杆倍数是否有效
func (c *Calculator) ValidateLeverage(leverage float64) error {
	if leverage <= 0 {
		return fmt.Errorf("leverage must be positive")
	}
	if leverage > 10 {
		return fmt.Errorf("leverage cannot exceed 10x")
	}
	return nil
}

// ValidateMarginMode 验证保证金模式
func (c *Calculator) ValidateMarginMode(mode MarginMode) error {
	switch mode {
	case ModeIsolated, ModeCross:
		return nil
	default:
		return fmt.Errorf("invalid margin mode: %v", mode)
	}
}

// EstimateLiquidationRisk 评估强平风险
func (c *Calculator) EstimateLiquidationRisk(position *LeveragedPosition, markPrice float64) *LiquidationRisk {
	distance := c.CalculateDistanceToLiquidation(markPrice, position.LiquidationPrice, position.Side)

	// 计算当前保证金率
	// 计算未实现盈亏
	unrealizedPnL := position.calculateUnrealizedPnL(markPrice)
	// 保证金率 = (保证金 + 未实现盈亏) / 保证金
	// 入场时 = 1.0 (100%), 随着盈亏变化
	marginLevel := c.CalculateMarginLevel(position.Margin+unrealizedPnL, position.Margin)

	isAtRisk := marginLevel < c.minMarginLevel || distance < 5.0 // 距离小于5%视为风险

	recommendation := ""
	if isAtRisk {
		if marginLevel < c.minMarginLevel {
			recommendation = "保证金率过低，建议追加保证金或减少仓位"
		} else {
			recommendation = "接近强平价格，建议监控风险"
		}
	} else if distance < 10.0 {
		recommendation = "风险适中，建议保持关注"
	} else {
		recommendation = "风险较低"
	}

	return &LiquidationRisk{
		IsAtRisk:       isAtRisk,
		DistanceToLiq:  distance,
		MarginLevel:    marginLevel,
		MinMarginLevel: c.minMarginLevel,
		Recommendation: recommendation,
	}
}

// CalculateCrossMarginRisk 计算全仓模式风险
func (c *Calculator) CalculateCrossMarginRisk(totalEquity, totalNotional, totalUsedMargin float64) *LiquidationRisk {
	marginLevel := c.CalculateMarginLevel(totalEquity, totalUsedMargin)
	isAtRisk := marginLevel < c.minMarginLevel

	recommendation := ""
	if isAtRisk {
		recommendation = "全仓保证金率过低，建议减少总仓位或追加保证金"
	} else {
		recommendation = "全仓风险可控"
	}

	return &LiquidationRisk{
		IsAtRisk:       isAtRisk,
		MarginLevel:    marginLevel,
		MinMarginLevel: c.minMarginLevel,
		Recommendation: recommendation,
	}
}

// RealTimeMarginInfo 实时保证金信息
type RealTimeMarginInfo struct {
	Symbol           string    `json:"symbol"`
	Side             Side      `json:"side"`
	PositionSize     float64   `json:"position_size"`
	EntryPrice       float64   `json:"entry_price"`
	MarkPrice        float64   `json:"mark_price"`
	Margin           float64   `json:"margin"`           // 已用保证金
	UnrealizedPnL    float64   `json:"unrealized_pnl"`   // 未实现盈亏
	RealizedPnL      float64   `json:"realized_pnl"`     // 已实现盈亏
	MarginLevel      float64   `json:"margin_level"`     // 当前保证金率
	MaintenanceMargin float64  `json:"maintenance_margin"` // 维持保证金
	AvailableMargin  float64   `json:"available_margin"` // 可用保证金
	LiquidationPrice float64   `json:"liquidation_price"`
	DistanceToLiq    float64   `json:"distance_to_liq"`  // 距离强平百分比
	IsAtRisk         bool      `json:"is_at_risk"`
	RiskLevel        RiskLevel `json:"risk_level"`
	Timestamp        time.Time `json:"timestamp"`
}

// CalculateRealTimeMargin 计算实时保证金信息
func (c *Calculator) CalculateRealTimeMargin(position *LeveragedPosition, markPrice float64) *RealTimeMarginInfo {
	// 计算未实现盈亏
	unrealizedPnL := position.calculateUnrealizedPnL(markPrice)

	// 计算当前保证金率
	// 对于隔离模式：保证金率 = (初始保证金 + 未实现盈亏) / 初始保证金
	// 即：如果盈利，保证金率 > 1；如果亏损，保证金率 < 1
	equity := position.Margin + unrealizedPnL
	marginLevel := c.CalculateMarginLevel(equity, position.Margin)

	// 计算维持保证金
	currentNotional := markPrice * position.Size
	maintenanceMargin := c.CalculateMaintenanceMargin(currentNotional)

	// 计算可用保证金（可提取的保证金）
	// 可用 = 当前权益 - 维持保证金（不能低于维持保证金）
	availableMargin := math.Max(0, equity-maintenanceMargin)

	// 计算距离强平的百分比
	distance := c.CalculateDistanceToLiquidation(markPrice, position.LiquidationPrice, position.Side)

	// 判断风险等级
	riskLevel := c.calculateRiskLevel(marginLevel, distance)
	isAtRisk := riskLevel >= RiskHigh

	return &RealTimeMarginInfo{
		Symbol:            position.Symbol,
		Side:              position.Side,
		PositionSize:      position.Size,
		EntryPrice:        position.EntryPrice,
		MarkPrice:         markPrice,
		Margin:            position.Margin,
		UnrealizedPnL:     unrealizedPnL,
		RealizedPnL:       position.RealizedPnL,
		MarginLevel:       marginLevel,
		MaintenanceMargin: maintenanceMargin,
		AvailableMargin:   availableMargin,
		LiquidationPrice:  position.LiquidationPrice,
		DistanceToLiq:     distance,
		IsAtRisk:          isAtRisk,
		RiskLevel:         riskLevel,
		Timestamp:         time.Now(),
	}
}

// calculateRiskLevel 计算风险等级
func (c *Calculator) calculateRiskLevel(marginLevel, distanceToLiq float64) RiskLevel {
	if marginLevel < 1.1 || distanceToLiq < 1.0 {
		return RiskCritical
	}
	if marginLevel < 1.25 || distanceToLiq < 5.0 {
		return RiskHigh
	}
	if marginLevel < 1.5 || distanceToLiq < 10.0 {
		return RiskMedium
	}
	if marginLevel < 2.0 || distanceToLiq < 20.0 {
		return RiskLow
	}
	return RiskSafe
}

// CheckMarginSufficiency 检查保证金是否充足
func (c *Calculator) CheckMarginSufficiency(position *LeveragedPosition, markPrice float64) (bool, float64, error) {
	if position == nil {
		return false, 0, fmt.Errorf("position is nil")
	}

	info := c.CalculateRealTimeMargin(position, markPrice)

	// 保证金充足条件：
	// 1. 保证金率 >= 最低要求
	// 2. 可用保证金 > 0
	isSufficient := info.MarginLevel >= c.minMarginLevel && info.AvailableMargin > 0

	// 返回保证金缺口（如果不足）
	deficit := 0.0
	if !isSufficient {
		// 计算需要追加的保证金
		requiredEquity := c.minMarginLevel * position.Margin
		deficit = requiredEquity - (position.Margin + info.UnrealizedPnL)
		if deficit < 0 {
			deficit = 0
		}
	}

	return isSufficient, deficit, nil
}

// CalculateMarginChange 计算价格变动后的保证金变化
func (c *Calculator) CalculateMarginChange(position *LeveragedPosition, currentPrice, newPrice float64) *MarginChangeResult {
	currentPnL := position.calculateUnrealizedPnL(currentPrice)
	newPnL := position.calculateUnrealizedPnL(newPrice)

	currentEquity := position.Margin + currentPnL
	newEquity := position.Margin + newPnL

	currentLevel := c.CalculateMarginLevel(currentEquity, position.Margin)
	newLevel := c.CalculateMarginLevel(newEquity, position.Margin)

	return &MarginChangeResult{
		PriceChange:        newPrice - currentPrice,
		PnLChange:          newPnL - currentPnL,
		MarginLevelBefore:  currentLevel,
		MarginLevelAfter:   newLevel,
		EquityBefore:       currentEquity,
		EquityAfter:        newEquity,
		WouldBeLiquidated:  position.Side == SideLong && newPrice <= position.LiquidationPrice ||
							position.Side == SideShort && newPrice >= position.LiquidationPrice,
	}
}

// MarginChangeResult 保证金变化结果
type MarginChangeResult struct {
	PriceChange       float64 `json:"price_change"`
	PnLChange         float64 `json:"pnl_change"`
	MarginLevelBefore float64 `json:"margin_level_before"`
	MarginLevelAfter  float64 `json:"margin_level_after"`
	EquityBefore      float64 `json:"equity_before"`
	EquityAfter       float64 `json:"equity_after"`
	WouldBeLiquidated bool    `json:"would_be_liquidated"`
}

// RealTimeMarginMonitor 实时保证金监控器
type RealTimeMarginMonitor struct {
	calculator      *Calculator
	positions       map[string]*LeveragedPosition
	markPrices      map[string]float64
	callback        func(symbol string, info *RealTimeMarginInfo)
	checkInterval   time.Duration
	stopChan        chan struct{}
	mu              sync.RWMutex
}

// NewRealTimeMarginMonitor 创建实时保证金监控器
func NewRealTimeMarginMonitor(calculator *Calculator) *RealTimeMarginMonitor {
	return &RealTimeMarginMonitor{
		calculator:    calculator,
		positions:     make(map[string]*LeveragedPosition),
		markPrices:    make(map[string]float64),
		checkInterval: 1 * time.Second,
		stopChan:      make(chan struct{}),
	}
}

// RegisterPosition 注册要监控的仓位
func (m *RealTimeMarginMonitor) RegisterPosition(position *LeveragedPosition) {
	m.mu.Lock()
	defer m.mu.Unlock()

	key := fmt.Sprintf("%s_%s", position.Symbol, position.Side)
	m.positions[key] = position
}

// UnregisterPosition 取消注册仓位
func (m *RealTimeMarginMonitor) UnregisterPosition(symbol string, side Side) {
	m.mu.Lock()
	defer m.mu.Unlock()

	key := fmt.Sprintf("%s_%s", symbol, side)
	delete(m.positions, key)
}

// UpdateMarkPrice 更新标记价格
func (m *RealTimeMarginMonitor) UpdateMarkPrice(symbol string, price float64) {
	m.mu.Lock()
	defer m.mu.Unlock()

	m.markPrices[symbol] = price
}

// SetCallback 设置保证金变化回调
func (m *RealTimeMarginMonitor) SetCallback(callback func(symbol string, info *RealTimeMarginInfo)) {
	m.mu.Lock()
	defer m.mu.Unlock()

	m.callback = callback
}

// Start 开始监控
func (m *RealTimeMarginMonitor) Start() {
	go m.monitor()
}

// Stop 停止监控
func (m *RealTimeMarginMonitor) Stop() {
	close(m.stopChan)
}

// monitor 监控循环
func (m *RealTimeMarginMonitor) monitor() {
	ticker := time.NewTicker(m.checkInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			m.checkAllPositions()
		case <-m.stopChan:
			return
		}
	}
}

// checkAllPositions 检查所有仓位
func (m *RealTimeMarginMonitor) checkAllPositions() {
	m.mu.RLock()
	defer m.mu.RUnlock()

	for key, position := range m.positions {
		markPrice, ok := m.markPrices[position.Symbol]
		if !ok {
			continue
		}

		info := m.calculator.CalculateRealTimeMargin(position, markPrice)

		// 如果风险等级变化或达到高风险，触发回调
		if m.callback != nil && (info.IsAtRisk || info.RiskLevel >= RiskMedium) {
			m.callback(key, info)
		}
	}
}

// GetAllMarginInfo 获取所有仓位的保证金信息
func (m *RealTimeMarginMonitor) GetAllMarginInfo() map[string]*RealTimeMarginInfo {
	m.mu.RLock()
	defer m.mu.RUnlock()

	result := make(map[string]*RealTimeMarginInfo)
	for key, position := range m.positions {
		markPrice, ok := m.markPrices[position.Symbol]
		if !ok {
			continue
		}

		info := m.calculator.CalculateRealTimeMargin(position, markPrice)
		result[key] = info
	}

	return result
}
