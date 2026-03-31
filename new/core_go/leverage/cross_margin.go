package leverage

import (
	"fmt"
	"math"
	"sync"
	"time"
)

// CrossMarginAccount 全仓保证金账户
type CrossMarginAccount struct {
	mu sync.RWMutex

	// 账户总权益
	totalEquity float64 // 总权益 = 钱包余额 + 所有未实现盈亏

	// 保证金使用情况
	totalUsedMargin      float64            // 总已用保证金
	symbolUsedMargin     map[string]float64 // 各交易对已用保证金
	symbolUnrealizedPnL  map[string]float64 // 各交易对未实现盈亏

	// 仓位管理
	positions map[string]map[Side]*LeveragedPosition // symbol -> side -> position

	// 配置
	maxLeverage        float64
	maintenanceRate    float64
	minMarginLevel     float64

	// 风险状态
	liquidationRisk    bool
	lastCheckTime      time.Time
}

// NewCrossMarginAccount 创建全仓保证金账户
func NewCrossMarginAccount(initialEquity float64) *CrossMarginAccount {
	return &CrossMarginAccount{
		totalEquity:         initialEquity,
		totalUsedMargin:     0,
		symbolUsedMargin:    make(map[string]float64),
		symbolUnrealizedPnL: make(map[string]float64),
		positions:           make(map[string]map[Side]*LeveragedPosition),
		maxLeverage:         3.0,
		maintenanceRate:     0.005,
		minMarginLevel:      1.25,
		lastCheckTime:       time.Now(),
	}
}

// SetMaxLeverage 设置最大杠杆
func (cma *CrossMarginAccount) SetMaxLeverage(leverage float64) error {
	if leverage <= 0 || leverage > 10 {
		return fmt.Errorf("leverage must be between 0 and 10")
	}
	cma.maxLeverage = leverage
	return nil
}

// Deposit 存入保证金
func (cma *CrossMarginAccount) Deposit(amount float64) {
	cma.mu.Lock()
	defer cma.mu.Unlock()
	cma.totalEquity += amount
}

// Withdraw 提取保证金
func (cma *CrossMarginAccount) Withdraw(amount float64) error {
	cma.mu.Lock()
	defer cma.mu.Unlock()

	available := cma.calculateAvailableMarginUnsafe()
	if amount > available {
		return fmt.Errorf("insufficient available margin: %.2f < %.2f", available, amount)
	}

	cma.totalEquity -= amount
	return nil
}

// OpenPosition 开仓
func (cma *CrossMarginAccount) OpenPosition(params OrderParams) (*LeveragedPosition, error) {
	if err := params.Validate(); err != nil {
		return nil, err
	}

	cma.mu.Lock()
	defer cma.mu.Unlock()

	// 计算所需保证金
	notional := params.Size * params.Price
	requiredMargin := notional / params.Leverage

	// 检查可用保证金
	available := cma.calculateAvailableMarginUnsafe()
	if requiredMargin > available {
		return nil, fmt.Errorf("insufficient margin: required %.2f, available %.2f", requiredMargin, available)
	}

	// 获取或创建该交易对的仓位映射
	sidePositions, ok := cma.positions[params.Symbol]
	if !ok {
		sidePositions = make(map[Side]*LeveragedPosition)
		cma.positions[params.Symbol] = sidePositions
	}

	// 检查是否已有同向持仓
	if existing, ok := sidePositions[params.Side]; ok && existing.Status == PositionOpen {
		return cma.addToPositionUnsafe(existing, params)
	}

	// 创建新仓位
	position := &LeveragedPosition{
		Symbol:          params.Symbol,
		Side:            params.Side,
		Size:            params.Size,
		EntryPrice:      params.Price,
		Leverage:        params.Leverage,
		MarginMode:      ModeCross,
		Margin:          requiredMargin,
		Status:          PositionOpen,
		MaintenanceRate: cma.maintenanceRate,
		OpenedAt:        time.Now(),
		UpdatedAt:       time.Now(),
	}

	// 计算全仓模式下的强平价格
	position.LiquidationPrice = cma.calculateCrossLiquidationPriceUnsafe(position)

	// 更新保证金使用
	sidePositions[params.Side] = position
	cma.symbolUsedMargin[params.Symbol] += requiredMargin
	cma.totalUsedMargin += requiredMargin

	return position, nil
}

// addToPositionUnsafe 加仓（非线程安全）
func (cma *CrossMarginAccount) addToPositionUnsafe(existing *LeveragedPosition, params OrderParams) (*LeveragedPosition, error) {
	// 计算新增保证金
	additionalNotional := params.Size * params.Price
	additionalMargin := additionalNotional / params.Leverage

	// 检查可用保证金
	available := cma.calculateAvailableMarginUnsafe()
	if additionalMargin > available {
		return nil, fmt.Errorf("insufficient margin for adding position")
	}

	// 计算新的持仓均价
	totalSize := existing.Size + params.Size
	totalValue := existing.Size*existing.EntryPrice + params.Size*params.Price
	existing.EntryPrice = totalValue / totalSize
	existing.Size = totalSize
	existing.Margin += additionalMargin
	existing.UpdatedAt = time.Now()

	// 重新计算强平价格
	existing.LiquidationPrice = cma.calculateCrossLiquidationPriceUnsafe(existing)

	// 更新保证金使用
	cma.symbolUsedMargin[params.Symbol] += additionalMargin
	cma.totalUsedMargin += additionalMargin

	return existing, nil
}

// ClosePosition 平仓
func (cma *CrossMarginAccount) ClosePosition(symbol string, side Side, exitPrice float64) (*LeveragedPosition, error) {
	cma.mu.Lock()
	defer cma.mu.Unlock()

	sidePositions, ok := cma.positions[symbol]
	if !ok {
		return nil, fmt.Errorf("no positions found for %s", symbol)
	}

	position, ok := sidePositions[side]
	if !ok || position.Status != PositionOpen {
		return nil, fmt.Errorf("no open %s position found for %s", side, symbol)
	}

	// 计算盈亏
	unrealizedPnL := position.calculateUnrealizedPnL(exitPrice)
	position.calculateRealizedPnL(exitPrice)
	position.Status = PositionClosed
	now := time.Now()
	position.ClosedAt = &now
	position.UpdatedAt = now

	// 更新账户权益
	cma.totalEquity += unrealizedPnL

	// 释放保证金
	cma.symbolUsedMargin[symbol] -= position.Margin
	cma.totalUsedMargin -= position.Margin

	if cma.symbolUsedMargin[symbol] <= 0 {
		delete(cma.symbolUsedMargin, symbol)
	}

	return position, nil
}

// UpdatePrices 更新价格并重新计算所有未实现盈亏
func (cma *CrossMarginAccount) UpdatePrices(prices map[string]float64) {
	cma.mu.Lock()
	defer cma.mu.Unlock()

	totalUnrealizedPnL := 0.0

	for symbol, sidePositions := range cma.positions {
		price, ok := prices[symbol]
		if !ok {
			continue
		}

		symbolPnL := 0.0
		for _, position := range sidePositions {
			if position.Status == PositionOpen {
				unrealizedPnL := position.calculateUnrealizedPnL(price)
				position.UnrealizedPnL = unrealizedPnL
				symbolPnL += unrealizedPnL
			}
		}
		cma.symbolUnrealizedPnL[symbol] = symbolPnL
		totalUnrealizedPnL += symbolPnL
	}

	cma.lastCheckTime = time.Now()
}

// GetAccountSummary 获取账户摘要
type CrossMarginAccountSummary struct {
	TotalEquity         float64            `json:"total_equity"`
	TotalUsedMargin     float64            `json:"total_used_margin"`
	TotalAvailableMargin float64           `json:"total_available_margin"`
	TotalUnrealizedPnL  float64            `json:"total_unrealized_pnl"`
	MarginLevel         float64            `json:"margin_level"`
	LiquidationRisk     bool               `json:"liquidation_risk"`
	OpenPositions       int                `json:"open_positions"`
	SymbolMargins       map[string]float64 `json:"symbol_margins"`
}

func (cma *CrossMarginAccount) GetAccountSummary() *CrossMarginAccountSummary {
	cma.mu.RLock()
	defer cma.mu.RUnlock()

	available := cma.calculateAvailableMarginUnsafe()
	totalUnrealizedPnL := cma.calculateTotalUnrealizedPnLUnsafe()
	marginLevel := cma.calculateMarginLevelUnsafe()

	// 复制 symbol margins
	symbolMargins := make(map[string]float64)
	for k, v := range cma.symbolUsedMargin {
		symbolMargins[k] = v
	}

	return &CrossMarginAccountSummary{
		TotalEquity:          cma.totalEquity,
		TotalUsedMargin:      cma.totalUsedMargin,
		TotalAvailableMargin: available,
		TotalUnrealizedPnL:   totalUnrealizedPnL,
		MarginLevel:          marginLevel,
		LiquidationRisk:      cma.liquidationRisk,
		OpenPositions:        cma.countOpenPositionsUnsafe(),
		SymbolMargins:        symbolMargins,
	}
}

// CheckLiquidationRisk 检查全仓强平风险
func (cma *CrossMarginAccount) CheckLiquidationRisk() *LiquidationRisk {
	cma.mu.RLock()
	defer cma.mu.RUnlock()

	marginLevel := cma.calculateMarginLevelUnsafe()
	isAtRisk := marginLevel < cma.minMarginLevel

	recommendation := ""
	if isAtRisk {
		recommendation = fmt.Sprintf("全仓保证金率 %.2f%% 低于最低要求 %.2f%%，建议追加保证金或减少仓位",
			marginLevel*100, cma.minMarginLevel*100)
	} else if marginLevel < cma.minMarginLevel*1.2 {
		recommendation = fmt.Sprintf("全仓保证金率 %.2f%% 接近警戒线，建议关注", marginLevel*100)
	} else {
		recommendation = fmt.Sprintf("全仓保证金率 %.2f%% 安全", marginLevel*100)
	}

	cma.liquidationRisk = isAtRisk

	return &LiquidationRisk{
		IsAtRisk:       isAtRisk,
		MarginLevel:    marginLevel,
		MinMarginLevel: cma.minMarginLevel,
		Recommendation: recommendation,
	}
}

// GetPosition 获取仓位
func (cma *CrossMarginAccount) GetPosition(symbol string, side Side) (*LeveragedPosition, bool) {
	cma.mu.RLock()
	defer cma.mu.RUnlock()

	sidePositions, ok := cma.positions[symbol]
	if !ok {
		return nil, false
	}

	pos, ok := sidePositions[side]
	if !ok || pos.Status != PositionOpen {
		return nil, false
	}
	return pos, true
}

// GetAllPositions 获取所有持仓
func (cma *CrossMarginAccount) GetAllPositions() []*LeveragedPosition {
	cma.mu.RLock()
	defer cma.mu.RUnlock()

	var positions []*LeveragedPosition
	for _, sidePositions := range cma.positions {
		for _, pos := range sidePositions {
			if pos.Status == PositionOpen {
				positions = append(positions, pos)
			}
		}
	}
	return positions
}

// calculateCrossLiquidationPriceUnsafe 计算全仓模式强平价格（非线程安全）
// 全仓模式下，强平价格取决于账户整体保证金率，而非单个仓位
func (cma *CrossMarginAccount) calculateCrossLiquidationPriceUnsafe(position *LeveragedPosition) float64 {
	if position.Size == 0 || position.EntryPrice == 0 {
		return 0
	}

	// 全仓模式强平价格计算
	// 当账户保证金率降至维持保证金率时触发强平
	// 简化计算：考虑该仓位对整体保证金率的贡献

	// 当前账户权益（不含该仓位当前未实现盈亏）
	currentEquity := cma.totalEquity + cma.calculateTotalUnrealizedPnLUnsafe() - position.UnrealizedPnL

	// 维持保证金要求
	maintenanceMarginRate := cma.maintenanceRate

	// 计算使账户保证金率降至维持水平的标记价格
	// marginLevel = (equity + unrealizedPnL) / usedMargin = maintenanceRate
	// 解出 unrealizedPnL = maintenanceRate * usedMargin - equity
	// 再根据 unrealizedPnL 反推价格

	if position.Side == SideLong {
		// 多头：unrealizedPnL = (price - entry) * size
		// price = entry + unrealizedPnL / size
		targetUnrealizedPnL := maintenanceMarginRate*cma.totalUsedMargin - currentEquity
		liqPrice := position.EntryPrice + targetUnrealizedPnL/position.Size
		return math.Max(0, liqPrice)
	}

	// 空头：unrealizedPnL = (entry - price) * size
	// price = entry - unrealizedPnL / size
	targetUnrealizedPnL := maintenanceMarginRate*cma.totalUsedMargin - currentEquity
	liqPrice := position.EntryPrice - targetUnrealizedPnL/position.Size
	return math.Max(0, liqPrice)
}

// calculateAvailableMarginUnsafe 计算可用保证金（非线程安全）
func (cma *CrossMarginAccount) calculateAvailableMarginUnsafe() float64 {
	totalUnrealizedPnL := cma.calculateTotalUnrealizedPnLUnsafe()
	available := cma.totalEquity + totalUnrealizedPnL - cma.totalUsedMargin
	return math.Max(0, available)
}

// calculateTotalUnrealizedPnLUnsafe 计算总未实现盈亏（非线程安全）
func (cma *CrossMarginAccount) calculateTotalUnrealizedPnLUnsafe() float64 {
	total := 0.0
	for _, pnl := range cma.symbolUnrealizedPnL {
		total += pnl
	}
	return total
}

// calculateMarginLevelUnsafe 计算保证金率（非线程安全）
func (cma *CrossMarginAccount) calculateMarginLevelUnsafe() float64 {
	if cma.totalUsedMargin <= 0 {
		return math.Inf(1)
	}
	totalUnrealizedPnL := cma.calculateTotalUnrealizedPnLUnsafe()
	effectiveEquity := cma.totalEquity + totalUnrealizedPnL
	return effectiveEquity / cma.totalUsedMargin
}

// countOpenPositionsUnsafe 统计开仓数量（非线程安全）
func (cma *CrossMarginAccount) countOpenPositionsUnsafe() int {
	count := 0
	for _, sidePositions := range cma.positions {
		for _, pos := range sidePositions {
			if pos.Status == PositionOpen {
				count++
			}
		}
	}
	return count
}

// CrossMarginCalculator 全仓保证金计算器（用于独立计算）
type CrossMarginCalculator struct {
	maintenanceRate float64
	minMarginLevel  float64
}

// NewCrossMarginCalculator 创建全仓保证金计算器
func NewCrossMarginCalculator() *CrossMarginCalculator {
	return &CrossMarginCalculator{
		maintenanceRate: 0.005,
		minMarginLevel:  1.25,
	}
}

// CalculateCrossLiquidationPrice 计算全仓强平价格
// 参数：仓位方向、仓位大小、入场价、账户总权益、总已用保证金
func (cmc *CrossMarginCalculator) CalculateCrossLiquidationPrice(
	side Side,
	size float64,
	entryPrice float64,
	totalEquity float64,
	totalUsedMargin float64,
) float64 {
	if size == 0 || entryPrice == 0 || totalUsedMargin == 0 {
		return 0
	}

	// 计算使保证金率降至维持水平的盈亏
	// marginLevel = (equity + unrealizedPnL) / usedMargin = maintenanceRate
	targetPnL := cmc.minMarginLevel*totalUsedMargin - totalEquity

	if side == SideLong {
		// 多头：price = entry + pnl / size
		liqPrice := entryPrice + targetPnL/size
		return math.Max(0, liqPrice)
	}

	// 空头：price = entry - pnl / size
	liqPrice := entryPrice - targetPnL/size
	return math.Max(0, liqPrice)
}

// CalculateMaxPositionSizeCross 计算全仓模式下最大可开仓数量
func (cmc *CrossMarginCalculator) CalculateMaxPositionSizeCross(
	availableMargin float64,
	price float64,
	leverage float64,
) float64 {
	if price <= 0 || leverage <= 0 {
		return 0
	}
	return availableMargin * leverage / price
}

// CrossMarginRiskMonitor 全仓风险监控器
type CrossMarginRiskMonitor struct {
	account *CrossMarginAccount
	stopCh  chan struct{}
	mu      sync.RWMutex

	// 回调函数
	onRiskAlert     func(risk *LiquidationRisk)
	onLiquidation   func(positions []*LeveragedPosition)
}

// NewCrossMarginRiskMonitor 创建风险监控器
func NewCrossMarginRiskMonitor(account *CrossMarginAccount) *CrossMarginRiskMonitor {
	return &CrossMarginRiskMonitor{
		account:       account,
		stopCh:        make(chan struct{}),
		onRiskAlert:   func(risk *LiquidationRisk) {},
		onLiquidation: func(positions []*LeveragedPosition) {},
	}
}

// SetRiskAlertCallback 设置风险告警回调
func (cmrm *CrossMarginRiskMonitor) SetRiskAlertCallback(cb func(risk *LiquidationRisk)) {
	cmrm.mu.Lock()
	defer cmrm.mu.Unlock()
	cmrm.onRiskAlert = cb
}

// SetLiquidationCallback 设置强平回调
func (cmrm *CrossMarginRiskMonitor) SetLiquidationCallback(cb func(positions []*LeveragedPosition)) {
	cmrm.mu.Lock()
	defer cmrm.mu.Unlock()
	cmrm.onLiquidation = cb
}

// Start 启动监控
func (cmrm *CrossMarginRiskMonitor) Start(interval time.Duration) {
	if interval < time.Second {
		interval = time.Second
	}

	ticker := time.NewTicker(interval)
	go func() {
		for {
			select {
			case <-ticker.C:
				cmrm.checkRisk()
			case <-cmrm.stopCh:
				ticker.Stop()
				return
			}
		}
	}()
}

// Stop 停止监控
func (cmrm *CrossMarginRiskMonitor) Stop() {
	close(cmrm.stopCh)
}

// checkRisk 检查风险
func (cmrm *CrossMarginRiskMonitor) checkRisk() {
	risk := cmrm.account.CheckLiquidationRisk()

	if risk.IsAtRisk {
		cmrm.mu.RLock()
		callback := cmrm.onRiskAlert
		cmrm.mu.RUnlock()
		callback(risk)

		// 如果风险极高，触发强平
		if risk.MarginLevel < 1.05 {
			positions := cmrm.account.GetAllPositions()
			cmrm.mu.RLock()
			liqCallback := cmrm.onLiquidation
			cmrm.mu.RUnlock()
			liqCallback(positions)
		}
	}
}
