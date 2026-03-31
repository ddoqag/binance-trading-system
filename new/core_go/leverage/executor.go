package leverage

import (
	"fmt"
	"log"
	"sync"
	"time"
)

// Executor 杠杆交易执行器
type Executor struct {
	symbol       string
	paperTrading bool
	maxLeverage  float64

	// 组件
	positionManager *PositionManager
	calculator      *Calculator

	// 持仓
	position   *LeveragedPosition
	positionMu sync.RWMutex

	// 订单管理
	orders   map[string]*Order
	ordersMu sync.RWMutex
	history  []*Order

	// 风控
	liquidationRisk bool
	minMarginLevel  float64

	// 配置
	commissionRate float64
	slippage       float64

	// 同步
	stopSync chan struct{}

	// 价格源
	getCurrentPrice func() float64
}

// NewExecutor 创建杠杆交易执行器
func NewExecutor(symbol string, paperTrading bool, maxLeverage float64) *Executor {
	if maxLeverage <= 0 || maxLeverage > 10 {
		maxLeverage = 3.0 // 默认3倍杠杆
	}

	executor := &Executor{
		symbol:          symbol,
		paperTrading:    paperTrading,
		maxLeverage:     maxLeverage,
		positionManager: NewPositionManager(),
		calculator:      NewCalculator(),
		orders:          make(map[string]*Order),
		history:         make([]*Order, 0),
		commissionRate:  0.001, // 0.1%
		slippage:        0.0005, // 0.05%
		minMarginLevel:  1.25,   // 最低保证金率 125%
		stopSync:        make(chan struct{}),
		getCurrentPrice: func() float64 { return 50000.0 }, // 默认价格
	}

	// 设置默认配置
	executor.positionManager.SetDefaultConfig(maxLeverage, ModeIsolated)

	log.Printf("[LEVERAGE] Executor initialized: symbol=%s maxLeverage=%.1fx paperTrading=%v",
		symbol, maxLeverage, paperTrading)

	return executor
}

// SetPriceSource 设置价格源
func (e *Executor) SetPriceSource(fn func() float64) {
	e.getCurrentPrice = fn
}

// OpenLong 开多仓
func (e *Executor) OpenLong(size float64, isMarket bool, price float64, leverage float64) error {
	if leverage == 0 {
		leverage = e.maxLeverage
	}

	params := OrderParams{
		Symbol:   e.symbol,
		Side:     SideLong,
		Size:     size,
		Price:    price,
		Leverage: leverage,
		IsMarket: isMarket,
	}

	if isMarket {
		params.Price = e.getCurrentPrice()
	}

	if e.paperTrading {
		return e.simulateOpenPosition(params)
	}
	return e.placeLiveOrder(params)
}

// OpenShort 开空仓
func (e *Executor) OpenShort(size float64, isMarket bool, price float64, leverage float64) error {
	if leverage == 0 {
		leverage = e.maxLeverage
	}

	params := OrderParams{
		Symbol:   e.symbol,
		Side:     SideShort,
		Size:     size,
		Price:    price,
		Leverage: leverage,
		IsMarket: isMarket,
	}

	if isMarket {
		params.Price = e.getCurrentPrice()
	}

	if e.paperTrading {
		return e.simulateOpenPosition(params)
	}
	return e.placeLiveOrder(params)
}

// ClosePosition 平仓
func (e *Executor) ClosePosition(isMarket bool, exitPrice float64) error {
	e.positionMu.RLock()
	pos := e.position
	e.positionMu.RUnlock()

	if pos == nil || pos.Status != PositionOpen {
		return fmt.Errorf("no open position to close")
	}

	price := exitPrice
	if isMarket || price == 0 {
		price = e.getCurrentPrice()
	}

	if e.paperTrading {
		return e.simulateClosePosition(price)
	}
	return e.placeLiveCloseOrder(price)
}

// simulateOpenPosition 模拟开仓
func (e *Executor) simulateOpenPosition(params OrderParams) error {
	fillPrice := params.Price

	if params.IsMarket {
		// 市价单滑点
		if params.Side == SideLong {
			fillPrice *= (1 + e.slippage)
		} else {
			fillPrice *= (1 - e.slippage)
		}
	}

	// 使用 PositionManager 开仓
	params.Price = fillPrice
	position, err := e.positionManager.OpenPosition(params)
	if err != nil {
		return err
	}

	e.positionMu.Lock()
	e.position = position
	e.positionMu.Unlock()

	// 创建订单记录
	orderType := OrderLimit
	if params.IsMarket {
		orderType = OrderMarket
	}

	order := &Order{
		ID:        generateOrderID(),
		Symbol:    e.symbol,
		Side:      params.Side,
		Type:      orderType,
		Size:      params.Size,
		Price:     fillPrice,
		Leverage:  params.Leverage,
		Status:    "FILLED",
		CreatedAt: time.Now(),
	}

	e.recordOrder(order)

	log.Printf("[LEVERAGE:PAPER] OPEN %s: size=%.4f leverage=%.1fx entry=%.2f",
		params.Side, params.Size, params.Leverage, fillPrice)

	return nil
}

// simulateClosePosition 模拟平仓
func (e *Executor) simulateClosePosition(exitPrice float64) error {
	e.positionMu.Lock()
	defer e.positionMu.Unlock()

	if e.position == nil || e.position.Status != PositionOpen {
		return fmt.Errorf("no open position to close")
	}

	// 计算盈亏
	pnl := e.calculator.CalculateUnrealizedPnL(
		e.position.EntryPrice,
		exitPrice,
		e.position.Size,
		e.position.Side,
	)

	// 平仓
	closedPos, err := e.positionManager.ClosePosition(e.symbol, exitPrice)
	if err != nil {
		return err
	}

	// 更新本地持仓
	e.position = closedPos

	// 创建订单记录
	closeSide := SideShort
	if e.position.Side == SideShort {
		closeSide = SideLong
	}

	order := &Order{
		ID:        generateOrderID(),
		Symbol:    e.symbol,
		Side:      closeSide,
		Type:      OrderMarket,
		Size:      closedPos.Size,
		Price:     exitPrice,
		Status:    "FILLED",
		CreatedAt: time.Now(),
	}

	e.recordOrder(order)

	log.Printf("[LEVERAGE:PAPER] CLOSE: exit=%.2f pnl=%.2f (%+.2f%%)",
		exitPrice, closedPos.RealizedPnL, pnl/closedPos.Margin*100)

	return nil
}

// placeLiveOrder 实盘下单（占位符）
func (e *Executor) placeLiveOrder(params OrderParams) error {
	// TODO: 集成 MarginClient 进行实盘交易
	return fmt.Errorf("live trading not implemented in leverage module")
}

// placeLiveCloseOrder 实盘平仓（占位符）
func (e *Executor) placeLiveCloseOrder(exitPrice float64) error {
	// TODO: 集成 MarginClient 进行实盘交易
	return fmt.Errorf("live trading not implemented in leverage module")
}

// GetPosition 获取当前持仓
func (e *Executor) GetPosition() *LeveragedPosition {
	e.positionMu.RLock()
	defer e.positionMu.RUnlock()

	if e.position == nil {
		return nil
	}

	// 更新未实现盈亏
	markPrice := e.getCurrentPrice()
	e.position.UnrealizedPnL = e.calculator.CalculateUnrealizedPnL(
		e.position.EntryPrice,
		markPrice,
		e.position.Size,
		e.position.Side,
	)

	return e.position
}

// GetPositionSummary 获取仓位摘要
func (e *Executor) GetPositionSummary() (*PositionSummary, error) {
	markPrice := e.getCurrentPrice()
	return e.positionManager.GetPositionSummary(e.symbol, markPrice)
}

// CheckLiquidationRisk 检查强平风险
func (e *Executor) CheckLiquidationRisk() (*LiquidationRisk, error) {
	e.positionMu.RLock()
	pos := e.position
	e.positionMu.RUnlock()

	if pos == nil || pos.Status != PositionOpen {
		return nil, fmt.Errorf("no open position")
	}

	markPrice := e.getCurrentPrice()
	return e.calculator.EstimateLiquidationRisk(pos, markPrice), nil
}

// HasLiquidationRisk 是否有强平风险
func (e *Executor) HasLiquidationRisk() bool {
	risk, err := e.CheckLiquidationRisk()
	if err != nil {
		return false
	}
	return risk.IsAtRisk
}

// GetOpenOrders 获取未成交订单
func (e *Executor) GetOpenOrders() []*Order {
	e.ordersMu.RLock()
	defer e.ordersMu.RUnlock()

	var open []*Order
	for _, order := range e.orders {
		if order.Status == "OPEN" || order.Status == "PENDING" {
			open = append(open, order)
		}
	}
	return open
}

// GetOrderHistory 获取订单历史
func (e *Executor) GetOrderHistory() []*Order {
	e.ordersMu.RLock()
	defer e.ordersMu.RUnlock()

	result := make([]*Order, len(e.history))
	copy(result, e.history)
	return result
}

// UpdateMarkPrice 更新标记价格
func (e *Executor) UpdateMarkPrice(markPrice float64) {
	e.positionManager.UpdateMarkPrice(e.symbol, markPrice)
}

// SetMarginMode 设置保证金模式
func (e *Executor) SetMarginMode(mode MarginMode) error {
	if err := e.calculator.ValidateMarginMode(mode); err != nil {
		return err
	}
	e.positionManager.SetDefaultConfig(e.maxLeverage, mode)
	return nil
}

// SetLeverage 设置杠杆倍数
func (e *Executor) SetLeverage(leverage float64) error {
	if err := e.calculator.ValidateLeverage(leverage); err != nil {
		return err
	}
	e.maxLeverage = leverage
	e.positionManager.SetDefaultConfig(leverage, ModeIsolated)
	return nil
}

// Close 关闭执行器
func (e *Executor) Close() {
	close(e.stopSync)
}

// 辅助函数

func (e *Executor) recordOrder(order *Order) {
	e.ordersMu.Lock()
	defer e.ordersMu.Unlock()

	e.orders[order.ID] = order
	e.history = append(e.history, order)
}

func generateOrderID() string {
	return fmt.Sprintf("LEV_%d", time.Now().UnixNano())
}

// IsolatedMarginExecutor 隔离模式执行器
type IsolatedMarginExecutor struct {
	*Executor
}

// NewIsolatedMarginExecutor 创建隔离模式执行器
func NewIsolatedMarginExecutor(symbol string, paperTrading bool, leverage float64) *IsolatedMarginExecutor {
	executor := NewExecutor(symbol, paperTrading, leverage)
	executor.SetMarginMode(ModeIsolated)
	return &IsolatedMarginExecutor{Executor: executor}
}

// CrossMarginExecutor 全仓模式执行器
type CrossMarginExecutor struct {
	*Executor
	totalMargin     float64
	usedMargin      float64
	availableMargin float64
}

// NewCrossMarginExecutor 创建全仓模式执行器
func NewCrossMarginExecutor(symbol string, paperTrading bool, leverage float64, totalMargin float64) *CrossMarginExecutor {
	executor := NewExecutor(symbol, paperTrading, leverage)
	executor.SetMarginMode(ModeCross)
	return &CrossMarginExecutor{
		Executor:        executor,
		totalMargin:     totalMargin,
		availableMargin: totalMargin,
	}
}

// SetTotalMargin 设置全仓总保证金
func (c *CrossMarginExecutor) SetTotalMargin(total float64) {
	c.totalMargin = total
	c.recalculateAvailableMargin()
}

// recalculateAvailableMargin 重新计算可用保证金
func (c *CrossMarginExecutor) recalculateAvailableMargin() {
	c.availableMargin = c.totalMargin - c.usedMargin
	if c.availableMargin < 0 {
		c.availableMargin = 0
	}
}

// CheckCrossMarginRisk 检查全仓风险
func (c *CrossMarginExecutor) CheckCrossMarginRisk() *LiquidationRisk {
	return c.calculator.CalculateCrossMarginRisk(
		c.totalMargin,
		c.usedMargin*c.maxLeverage,
		c.usedMargin,
	)
}

// GetMarginInfo 获取保证金信息
func (c *CrossMarginExecutor) GetMarginInfo() *MarginInfo {
	marginLevel := c.calculator.CalculateMarginLevel(c.totalMargin, c.usedMargin)
	maintenanceMargin := c.calculator.CalculateMaintenanceMargin(c.usedMargin * c.maxLeverage)

	return &MarginInfo{
		InitialMargin:     c.usedMargin,
		MaintenanceMargin: maintenanceMargin,
		AvailableMargin:   c.availableMargin,
		MarginLevel:       marginLevel,
	}
}
