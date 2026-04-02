package main

import (
	"context"
	"fmt"
	"log"
	"math"
	"sync"
	"time"

	"hft_engine/leverage"
)

/*
margin_executor.go - Margin Trading Executor

支持现货全仓杠杆交易：
- 做多（Long）
- 做空（Short）
- 自动借贷/还款
- 强平风险监控
*/

// MarginSide 杠杆交易方向
type MarginSide int

const (
	MarginLong MarginSide = iota  // 做多
	MarginShort                    // 做空
)

// MarginPositionInfo 杠杆持仓信息
type MarginPositionInfo struct {
	Symbol           string
	Position         float64 // 正数=多头，负数=空头
	EntryPrice       float64
	Leverage         float64
	Margin           float64 // 已用保证金
	AvailableMargin  float64 // 可用保证金
	UnrealizedPnL    float64 // 未实现盈亏
	LiquidationPrice float64 // 强平价格
	Borrowed         float64 // 借入数量
	LastUpdated      time.Time
}

// MarginExecutor 杠杆交易执行器
type MarginExecutor struct {
	symbol       string
	paperTrading bool
	maxLeverage  float64

	// 客户端
	marginClient *MarginClient

	// WebSocket 管理器（获取实时价格）
	wsManager *WebSocketManager

	// 持仓管理
	position     *MarginPositionInfo
	positionMu   sync.RWMutex

	// 订单管理
	orders       map[string]*Order
	ordersMu     sync.RWMutex
	history      []*Order

	// 风控
	liquidationRisk bool
	minMarginLevel  float64

	// 杠杆计算器
	calculator *leverage.Calculator

	// 配置
	commissionRate float64
	slippage       float64

	// 同步
	stopSync chan struct{}
}

// NewMarginExecutor 创建杠杆交易执行器
func NewMarginExecutor(symbol string, paperTrading bool, apiKey, apiSecret string, maxLeverage float64, wsManager *WebSocketManager) *MarginExecutor {
	if maxLeverage <= 0 || maxLeverage > 10 {
		maxLeverage = 3.0 // 默认3倍杠杆
	}

	executor := &MarginExecutor{
		symbol:         symbol,
		paperTrading:   paperTrading,
		maxLeverage:    maxLeverage,
		wsManager:      wsManager,
		position:       &MarginPositionInfo{Symbol: symbol},
		orders:         make(map[string]*Order),
		history:        make([]*Order, 0),
		commissionRate: 0.001, // 0.1%
		slippage:       0.0005, // 0.05%
		minMarginLevel: 1.25,  // 最低保证金率 125%
		calculator:      leverage.NewCalculator(),
		stopSync:       make(chan struct{}),
	}

	// 设置计算器参数
	executor.calculator.SetDefaultParams(0.005, executor.minMarginLevel)

	// 初始化杠杆客户端
	if !paperTrading {
		executor.marginClient = NewMarginClient(apiKey, apiSecret, false)
		// 启动同步循环
		go executor.syncLoop()
	}

	log.Printf("[MARGIN] MarginExecutor initialized: symbol=%s maxLeverage=%.1fx paperTrading=%v",
		symbol, maxLeverage, paperTrading)

	return executor
}

// PlaceLongOrder 开多/平空
func (e *MarginExecutor) PlaceLongOrder(size float64, isMarket bool, price float64) error {
	if e.paperTrading {
		return e.simulateMarginOrder(MarginLong, size, isMarket, price)
	}
	return e.placeLiveMarginOrder(MarginLong, size, isMarket, price)
}

// PlaceShortOrder 开空/平多
func (e *MarginExecutor) PlaceShortOrder(size float64, isMarket bool, price float64) error {
	if e.paperTrading {
		return e.simulateMarginOrder(MarginShort, size, isMarket, price)
	}
	return e.placeLiveMarginOrder(MarginShort, size, isMarket, price)
}

// ClosePosition 平仓
func (e *MarginExecutor) ClosePosition(isMarket bool) error {
	e.positionMu.RLock()
	posSize := e.position.Position
	e.positionMu.RUnlock()

	if posSize == 0 {
		return fmt.Errorf("no position to close")
	}

	if posSize > 0 {
		// 多头平仓 = 卖出
		return e.PlaceShortOrder(posSize, isMarket, 0)
	} else {
		// 空头平仓 = 买入
		return e.PlaceLongOrder(-posSize, isMarket, 0)
	}
}

// 实盘交易

func (e *MarginExecutor) placeLiveMarginOrder(side MarginSide, size float64, isMarket bool, price float64) error {
	if e.marginClient == nil {
		return fmt.Errorf("margin client not initialized")
	}

	// 检查保证金安全
	safe, level, err := e.marginClient.IsMarginSafe(context.Background(), e.minMarginLevel)
	if err != nil {
		log.Printf("[MARGIN] Warning: failed to check margin level: %v", err)
	} else if !safe {
		return fmt.Errorf("margin level too low: %.2f (min: %.2f)", level, e.minMarginLevel)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	// 确定买卖方向
	var sideStr string
	var autoRepay bool

	e.positionMu.RLock()
	currentPos := e.position.Position
	e.positionMu.RUnlock()

	if side == MarginLong {
		// 做多：买入基础资产
		sideStr = "BUY"
		// 如果有空头仓位，买入会自动平空（还款）
		autoRepay = currentPos < 0
	} else {
		// 做空：卖出基础资产（自动借贷）
		sideStr = "SELL"
		autoRepay = currentPos > 0
	}

	var resp *MarginOrderResponse
	if isMarket {
		resp, err = e.marginClient.PlaceMarginMarketOrder(ctx, e.symbol, sideStr, size, autoRepay)
	} else {
		resp, err = e.marginClient.PlaceMarginLimitOrder(ctx, e.symbol, sideStr, price, size, "GTC", autoRepay)
	}

	if err != nil {
		return fmt.Errorf("failed to place margin order: %w", err)
	}

	// 创建本地订单记录
	order := &Order{
		ID:             generateOrderID(),
		Symbol:         e.symbol,
		Side:           mapMarginSideToOrderSide(side, currentPos),
		Type:           mapBoolToOrderType(isMarket),
		Price:          price,
		Size:           size,
		Filled:         parseFloat64(resp.ExecutedQty),
		AvgPrice:       parseFloat64(resp.CummulativeQuoteQty) / parseFloat64(resp.ExecutedQty),
		Status:         mapBinanceStatus(resp.Status),
		CreatedAt:      time.Now(),
		UpdatedAt:      time.Now(),
		BinanceOrderID: resp.OrderID,
	}

	if isMarket || order.Status == StatusFilled {
		e.updateMarginPosition(order, side)
	}

	e.recordOrder(order)

	log.Printf("[MARGIN] %s %s: %.4f @ %.2f (Margin ID: %d, Status: %s)",
		sideStr, orderTypeToString(order.Type), size, order.AvgPrice, resp.OrderID, resp.Status)

	return nil
}

// 模拟交易

func (e *MarginExecutor) simulateMarginOrder(side MarginSide, size float64, isMarket bool, price float64) error {
	fillPrice := e.GetCurrentPrice()

	if isMarket {
		// 市价单滑点
		if side == MarginLong {
			fillPrice *= (1 + e.slippage)
		} else {
			fillPrice *= (1 - e.slippage)
		}
	} else {
		fillPrice = price
	}

	orderType := TypeLimit
	if isMarket {
		orderType = TypeMarket
	}

	order := &Order{
		ID:        generateOrderID(),
		Symbol:    e.symbol,
		Side:       mapMarginSideToOrderSide(side, 0),
		Type:      orderType,
		Price:     price,
		Size:      size,
		Filled:    size,
		AvgPrice:  fillPrice,
		Status:    StatusFilled,
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
	}

	e.recordOrder(order)
	e.updateMarginPosition(order, side)

	sideStr := "LONG"
	if side == MarginShort {
		sideStr = "SHORT"
	}

	log.Printf("[MARGIN:PAPER] %s %s: %.4f @ %.2f",
		sideStr, orderTypeToString(orderType), size, fillPrice)

	return nil
}

// 持仓管理

func (e *MarginExecutor) updateMarginPosition(order *Order, side MarginSide) {
	e.positionMu.Lock()
	defer e.positionMu.Unlock()

	if order.Status != StatusFilled {
		return
	}

	oldSize := e.position.Position
	var newSize float64

	if side == MarginLong {
		newSize = oldSize + order.Filled
	} else {
		newSize = oldSize - order.Filled
	}

	// 更新持仓均价
	if oldSize == 0 || (oldSize > 0 && side == MarginShort) || (oldSize < 0 && side == MarginLong) {
		// 新开仓或反向开仓
		e.position.EntryPrice = order.AvgPrice
	} else {
		// 加仓 - 计算新的均价
		totalValue := oldSize*e.position.EntryPrice + order.Filled*order.AvgPrice
		totalSize := oldSize + order.Filled
		if totalSize != 0 {
			e.position.EntryPrice = totalValue / totalSize
		}
	}

	e.position.Position = newSize
	e.position.LastUpdated = time.Now()

	// 计算未实现盈亏
	currentPrice := e.GetCurrentPrice()
	var levSide leverage.Side
	if newSize > 0 {
		levSide = leverage.SideLong
	} else {
		levSide = leverage.SideShort
	}

	if newSize != 0 {
		e.position.UnrealizedPnL = e.calculator.CalculateUnrealizedPnL(
			e.position.EntryPrice,
			currentPrice,
			math.Abs(newSize),
			levSide,
		)
	} else {
		e.position.UnrealizedPnL = 0
	}

	// 计算强平价格
	e.calculateLiquidationPrice()

	// 更新借入数量（用于全仓杠杆）
	if e.position.Position != 0 {
		// 借入数量 = 净仓位的绝对值（如果是空头，我们借入基础资产）
		if e.position.Position < 0 {
			e.position.Borrowed = -e.position.Position
		} else {
			e.position.Borrowed = 0
		}
	}

	log.Printf("[MARGIN] Position updated: size=%.4f entry=%.2f pnl=%.2f liq=%.2f",
		newSize, e.position.EntryPrice, e.position.UnrealizedPnL, e.position.LiquidationPrice)
}

func (e *MarginExecutor) calculateLiquidationPrice() {
	// 使用 leverage.Calculator 计算强平价格
	if e.position.Position == 0 || e.position.EntryPrice == 0 {
		e.position.LiquidationPrice = 0
		return
	}

	var levSide leverage.Side
	if e.position.Position > 0 {
		levSide = leverage.SideLong
	} else {
		levSide = leverage.SideShort
	}

	e.position.LiquidationPrice = e.calculator.CalculateLiquidationPrice(
		e.position.EntryPrice,
		e.maxLeverage,
		levSide,
		leverage.ModeCross,
	)
}

// 同步循环

func (e *MarginExecutor) syncLoop() {
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			e.syncPositionFromExchange()
			e.checkLiquidationRisk()
		case <-e.stopSync:
			return
		}
	}
}

func (e *MarginExecutor) syncPositionFromExchange() {
	if e.marginClient == nil {
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	// 同步持仓
	pos, err := e.marginClient.GetMarginPosition(ctx, e.symbol)
	if err != nil {
		log.Printf("[MARGIN] Failed to sync position: %v", err)
		return
	}

	e.positionMu.Lock()
	e.position.Position = pos.Position
	e.position.LastUpdated = time.Now()
	e.positionMu.Unlock()
}

func (e *MarginExecutor) checkLiquidationRisk() {
	if e.marginClient == nil {
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	safe, level, err := e.marginClient.IsMarginSafe(ctx, e.minMarginLevel)
	if err != nil {
		log.Printf("[MARGIN] Failed to check margin level: %v", err)
		return
	}

	if !safe {
		log.Printf("[MARGIN:WARNING] Low margin level: %.2f (min: %.2f). Consider reducing position!", level, e.minMarginLevel)
		e.liquidationRisk = true
	} else {
		e.liquidationRisk = false
	}
}

// 查询接口

func (e *MarginExecutor) GetPosition() *MarginPositionInfo {
	e.positionMu.RLock()
	defer e.positionMu.RUnlock()

	return &MarginPositionInfo{
		Symbol:           e.position.Symbol,
		Position:         e.position.Position,
		EntryPrice:       e.position.EntryPrice,
		Leverage:         e.position.Leverage,
		Margin:           e.position.Margin,
		AvailableMargin:  e.position.AvailableMargin,
		UnrealizedPnL:    e.position.UnrealizedPnL,
		LiquidationPrice: e.position.LiquidationPrice,
		Borrowed:         e.position.Borrowed,
		LastUpdated:      e.position.LastUpdated,
	}
}

func (e *MarginExecutor) GetOpenOrders() []*Order {
	e.ordersMu.RLock()
	defer e.ordersMu.RUnlock()

	var open []*Order
	for _, order := range e.orders {
		if order.Status == StatusOpen || order.Status == StatusPending {
			open = append(open, order)
		}
	}
	return open
}

func (e *MarginExecutor) HasLiquidationRisk() bool {
	return e.liquidationRisk
}

func (e *MarginExecutor) Close() {
	close(e.stopSync)
}

// 辅助函数

func (e *MarginExecutor) recordOrder(order *Order) {
	e.ordersMu.Lock()
	defer e.ordersMu.Unlock()

	e.orders[order.ID] = order
	e.history = append(e.history, order)
}

// GetCurrentPrice 获取当前价格（从order book）
func (e *MarginExecutor) GetCurrentPrice() float64 {
	// 从 WebSocket order book 获取当前中间价
	if e.wsManager != nil {
		book := e.wsManager.GetBook()
		if book != nil {
			bestBid, bestAsk, _, _ := book.GetSnapshot()
			if bestBid > 0 && bestAsk > 0 {
				return (bestBid + bestAsk) / 2
			}
		}
	}
	// 后备：如果没有order book，返回入场价格（模拟
	e.positionMu.RLock()
	entryPrice := e.position.EntryPrice
	e.positionMu.RUnlock()
	if entryPrice > 0 {
		return entryPrice
	}
	// 极端情况，返回默认值（仅模拟交易）
	return 50000.0
}

func mapMarginSideToOrderSide(marginSide MarginSide, currentPos float64) OrderSide {
	if marginSide == MarginLong {
		return SideBuy
	}
	return SideSell
}

func mapBoolToOrderType(isMarket bool) OrderType {
	if isMarket {
		return TypeMarket
	}
	return TypeLimit
}
