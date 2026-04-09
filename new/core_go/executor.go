package main

import (
	"context"
	"fmt"
	"log"
	"strconv"
	"sync"
	"time"
)

/*
executor.go - Order Execution Engine

Handles order execution with support for:
- Paper trading (simulated fills)
- Live trading (Binance API)
- Order state tracking
- Position management
*/

type OrderSide int

const (
	SideBuy OrderSide = iota
	SideSell
)

type OrderType int

const (
	TypeMarket OrderType = iota
	TypeLimit
	TypeStopMarket
)

type OrderStatus int

const (
	StatusPending OrderStatus = iota
	StatusOpen
	StatusPartiallyFilled
	StatusFilled
	StatusCancelled
	StatusRejected
)

type Order struct {
	ID            string
	Symbol        string
	Side          OrderSide
	Type          OrderType
	Price         float64 // 0 for market orders
	Size          float64
	Filled        float64
	AvgPrice      float64
	Status        OrderStatus
	CreatedAt     time.Time
	UpdatedAt     time.Time
	BinanceOrderID int64 // For live trading
}

type Position struct {
	Symbol      string
	Size        float64 // positive for long, negative for short
	AvgPrice    float64
	RealizedPnL float64
	OpenOrders  []*Order
	mu          sync.RWMutex
}

type OrderExecutor struct {
	symbol        string
	paperTrading  bool
	position      *Position
	orders        map[string]*Order
	ordersMu      sync.RWMutex
	history       []*Order
	binanceClient *BinanceClient // Binance API client for live trading
	wal           *WAL           // Write-ahead logging for order persistence
	stopSync      chan struct{}  // Stop signal for order sync loop
	stp           *SelfTradePrevention // Self-trade prevention
}

func NewOrderExecutor(symbol string, paperTrading bool, apiKey, apiSecret string, logDir string) *OrderExecutor {
	return NewOrderExecutorWithSTP(symbol, paperTrading, apiKey, apiSecret, logDir, nil)
}

// NewOrderExecutorWithSTP creates a new order executor with self-trade prevention
func NewOrderExecutorWithSTP(symbol string, paperTrading bool, apiKey, apiSecret string, logDir string, stpConfig *STPConfig) *OrderExecutor {
	executor := &OrderExecutor{
		symbol:       symbol,
		paperTrading: paperTrading,
		position: &Position{
			Symbol:     symbol,
			OpenOrders: make([]*Order, 0),
		},
		orders:   make(map[string]*Order),
		history:  make([]*Order, 0),
		stopSync: make(chan struct{}),
	}

	// Initialize STP
	executor.stp = NewSelfTradePrevention(stpConfig)

	// Initialize WAL for order persistence
	if logDir == "" {
		logDir = "./logs"
	}
	wal, err := NewWAL(logDir)
	if err != nil {
		log.Printf("[EXEC] Failed to initialize WAL: %v", err)
	} else {
		executor.wal = wal
	}

	// Initialize Binance client for live trading
	if !paperTrading {
		executor.binanceClient = NewBinanceClient(apiKey, apiSecret, false)
	}

	// Start order status sync loop for live trading
	if !paperTrading {
		go executor.orderSyncLoop()
	}

	return executor
}

func (e *OrderExecutor) PlaceLimitBuy(price, size float64, postOnly bool) error {
	if e.paperTrading {
		return e.simulateLimitOrder(SideBuy, price, size, postOnly)
	}
	return e.placeLiveLimitOrder(SideBuy, price, size, postOnly)
}

func (e *OrderExecutor) PlaceLimitSell(price, size float64, postOnly bool) error {
	if e.paperTrading {
		return e.simulateLimitOrder(SideSell, price, size, postOnly)
	}
	return e.placeLiveLimitOrder(SideSell, price, size, postOnly)
}

func (e *OrderExecutor) PlaceMarketBuy(size float64) error {
	if e.paperTrading {
		return e.simulateMarketOrder(SideBuy, size)
	}
	return e.placeLiveMarketOrder(SideBuy, size)
}

func (e *OrderExecutor) PlaceMarketSell(size float64) error {
	if e.paperTrading {
		return e.simulateMarketOrder(SideSell, size)
	}
	return e.placeLiveMarketOrder(SideSell, size)
}

func (e *OrderExecutor) CancelAll() error {
	e.ordersMu.Lock()
	defer e.ordersMu.Unlock()

	for _, order := range e.orders {
		if order.Status == StatusOpen || order.Status == StatusPending {
			order.Status = StatusCancelled
			order.UpdatedAt = time.Now()
			log.Printf("[EXEC] Cancelled order %s", order.ID)
		}
	}

	return nil
}

func (e *OrderExecutor) PartialExit(amount float64) error {
	// Close portion of position
	e.position.mu.RLock()
	posSize := e.position.Size
	e.position.mu.RUnlock()

	if posSize > 0 {
		// Long position - sell
		sellSize := amount
		if sellSize > posSize {
			sellSize = posSize
		}
		return e.PlaceMarketSell(sellSize)
	} else if posSize < 0 {
		// Short position - buy to cover
		buySize := amount
		if buySize > -posSize {
			buySize = -posSize
		}
		return e.PlaceMarketBuy(buySize)
	}

	return nil
}

// Paper trading simulations

func (e *OrderExecutor) simulateMarketOrder(side OrderSide, size float64) error {
	// Simulate immediate fill at current market price
	// In real implementation, would get price from order book
	fillPrice := e.getCurrentPrice()

	// Add slippage for market orders
	if side == SideBuy {
		fillPrice *= 1.0002 // 0.02% slippage
	} else {
		fillPrice *= 0.9998
	}

	order := &Order{
		ID:        generateOrderID(),
		Symbol:    e.symbol,
		Side:      side,
		Type:      TypeMarket,
		Size:      size,
		Filled:    size,
		AvgPrice:  fillPrice,
		Status:    StatusFilled,
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
	}

	e.recordOrder(order)
	e.updatePosition(order)

	log.Printf("[PAPER] Market %s: %.4f @ %.2f",
		sideToString(side), size, fillPrice)

	return nil
}

func (e *OrderExecutor) simulateLimitOrder(side OrderSide, price, size float64, postOnly bool) error {
	order := &Order{
		ID:        generateOrderID(),
		Symbol:    e.symbol,
		Side:      side,
		Type:      TypeLimit,
		Price:     price,
		Size:      size,
		Status:    StatusOpen,
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
	}

	e.recordOrder(order)

	// In a real implementation, would check if limit can be filled immediately
	// and monitor for fills

	postOnlyStr := ""
	if postOnly {
		postOnlyStr = " POST_ONLY"
	}
	log.Printf("[PAPER] Limit %s%s: %.4f @ %.2f (order %s)",
		sideToString(side), postOnlyStr, size, price, order.ID)

	return nil
}

// Live trading with Binance API

func (e *OrderExecutor) placeLiveMarketOrder(side OrderSide, size float64) error {
	if e.binanceClient == nil {
		return fmt.Errorf("binance client not initialized")
	}

	// STP check before placing order
	if e.stp != nil && e.stp.IsEnabled() {
		// Generate temporary order ID for STP check
		tempOrderID := generateOrderID()
		result := e.stp.CheckOrder(e.symbol, side, 0, size, tempOrderID)
		if result.ShouldPrevent {
			if err := e.stp.ApplyPrevention(result, e); err != nil {
				return fmt.Errorf("self-trade prevented: %w", err)
			}
			// If prevention was applied successfully (e.g., cancelled oldest), continue
			// If prevention requires rejecting this order, it returns an error
		}
	}

	sideStr := "SELL"
	if side == SideBuy {
		sideStr = "BUY"
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	resp, err := e.binanceClient.PlaceMarketOrder(ctx, e.symbol, sideStr, size)
	if err != nil {
		return fmt.Errorf("failed to place market order: %w", err)
	}

	// Parse response and create local order
	order := &Order{
		ID:             generateOrderID(),
		Symbol:         e.symbol,
		Side:           side,
		Type:           TypeMarket,
		Size:           size,
		Filled:         parseFloat64(resp.ExecutedQty),
		AvgPrice:       parseFloat64(resp.AvgPrice),
		Status:         mapBinanceStatus(resp.Status),
		CreatedAt:      time.Now(),
		UpdatedAt:      time.Now(),
		BinanceOrderID: resp.OrderID,
	}

	e.recordOrder(order)
	e.updatePosition(order)

	// Track order in STP
	if e.stp != nil {
		e.stp.TrackOrder(order)
	}

	log.Printf("[LIVE] Market %s: %.4f @ %.2f (Binance ID: %d)",
		sideStr, size, order.AvgPrice, resp.OrderID)

	return nil
}

func (e *OrderExecutor) placeLiveLimitOrder(side OrderSide, price, size float64, postOnly bool) error {
	if e.binanceClient == nil {
		return fmt.Errorf("binance client not initialized")
	}

	// STP check before placing order
	if e.stp != nil && e.stp.IsEnabled() {
		// Generate temporary order ID for STP check
		tempOrderID := generateOrderID()
		result := e.stp.CheckOrder(e.symbol, side, price, size, tempOrderID)
		if result.ShouldPrevent {
			if err := e.stp.ApplyPrevention(result, e); err != nil {
				return fmt.Errorf("self-trade prevented: %w", err)
			}
			// If prevention was applied successfully (e.g., cancelled oldest), continue
			// If prevention requires rejecting this order, it returns an error
		}
	}

	sideStr := "SELL"
	if side == SideBuy {
		sideStr = "BUY"
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	// Force maker orders with POST_ONLY time-in-force
	timeInForce := "GTC"
	if postOnly {
		timeInForce = "GTX" // POST_ONLY in Binance API
	}

	resp, err := e.binanceClient.PlaceLimitOrder(ctx, e.symbol, sideStr, price, size, timeInForce)
	if err != nil {
		return fmt.Errorf("failed to place limit order: %w", err)
	}

	// Parse response and create local order
	order := &Order{
		ID:             generateOrderID(),
		Symbol:         e.symbol,
		Side:           side,
		Type:           TypeLimit,
		Price:          price,
		Size:           size,
		Filled:         parseFloat64(resp.ExecutedQty),
		AvgPrice:       parseFloat64(resp.AvgPrice),
		Status:         mapBinanceStatus(resp.Status),
		CreatedAt:      time.Now(),
		UpdatedAt:      time.Now(),
		BinanceOrderID: resp.OrderID,
	}

	e.recordOrder(order)

	// Track order in STP
	if e.stp != nil {
		e.stp.TrackOrder(order)
	}

	postOnlyStr := ""
	if postOnly {
		postOnlyStr = " POST_ONLY"
	}
	log.Printf("[LIVE] Limit %s%s: %.4f @ %.2f (Binance ID: %d, Status: %s)",
		sideStr, postOnlyStr, size, price, resp.OrderID, resp.Status)

	return nil
}

// CancelOrder cancels an order by its Binance order ID
func (e *OrderExecutor) CancelOrder(orderID int64) error {
	if e.paperTrading {
		// For paper trading, just update local status
		e.ordersMu.Lock()
		defer e.ordersMu.Unlock()
		for _, order := range e.orders {
			if order.BinanceOrderID == orderID {
				order.Status = StatusCancelled
				order.UpdatedAt = time.Now()
				// Untrack from STP
				if e.stp != nil {
					e.stp.UntrackOrder(order.ID)
				}
				return nil
			}
		}
		return fmt.Errorf("order not found: %d", orderID)
	}

	if e.binanceClient == nil {
		return fmt.Errorf("binance client not initialized")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	err := e.binanceClient.CancelOrder(ctx, e.symbol, orderID)
	if err != nil {
		return fmt.Errorf("failed to cancel order: %w", err)
	}

	// Update local order status and untrack from STP
	e.ordersMu.Lock()
	defer e.ordersMu.Unlock()
	for _, order := range e.orders {
		if order.BinanceOrderID == orderID {
			order.Status = StatusCancelled
			order.UpdatedAt = time.Now()
			// Untrack from STP
			if e.stp != nil {
				e.stp.UntrackOrder(order.ID)
			}
			break
		}
	}

	log.Printf("[LIVE] Cancelled order %d", orderID)
	return nil
}

// SyncOrderStatus syncs order status from Binance
func (e *OrderExecutor) SyncOrderStatus(orderID int64) (*Order, error) {
	if e.binanceClient == nil {
		return nil, fmt.Errorf("binance client not initialized")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	resp, err := e.binanceClient.QueryOrder(ctx, e.symbol, orderID)
	if err != nil {
		return nil, fmt.Errorf("failed to query order: %w", err)
	}

	// Update local order
	e.ordersMu.Lock()
	defer e.ordersMu.Unlock()

	for _, order := range e.orders {
		if order.BinanceOrderID == orderID {
			order.Filled = parseFloat64(resp.ExecutedQty)
			order.AvgPrice = parseFloat64(resp.AvgPrice)
			order.Status = mapBinanceStatus(resp.Status)
			order.UpdatedAt = time.Now()
			return order, nil
		}
	}

	return nil, fmt.Errorf("order not found locally: %d", orderID)
}

// Helper functions

func parseFloat64(s string) float64 {
	v, _ := strconv.ParseFloat(s, 64)
	return v
}

func mapBinanceStatus(status string) OrderStatus {
	switch status {
	case "NEW":
		return StatusOpen
	case "PARTIALLY_FILLED":
		return StatusPartiallyFilled
	case "FILLED":
		return StatusFilled
	case "CANCELED":
		return StatusCancelled
	case "REJECTED":
		return StatusRejected
	default:
		return StatusPending
	}
}

// Position management

func (e *OrderExecutor) updatePosition(order *Order) {
	e.position.mu.Lock()
	defer e.position.mu.Unlock()

	if order.Status != StatusFilled {
		return
	}

	oldSize := e.position.Size

	if order.Side == SideBuy {
		e.position.Size += order.Filled
	} else {
		e.position.Size -= order.Filled
	}

	// Update average price
	if oldSize == 0 {
		e.position.AvgPrice = order.AvgPrice
	} else {
		// VWAP calculation
		totalValue := oldSize*e.position.AvgPrice + order.Filled*order.AvgPrice
		totalSize := oldSize + order.Filled
		if totalSize > 0 {
			e.position.AvgPrice = totalValue / totalSize
		}
	}

	// Calculate realized PnL if closing position
	if (oldSize > 0 && e.position.Size < oldSize) || (oldSize < 0 && e.position.Size > oldSize) {
		closed := oldSize - e.position.Size
		if oldSize > 0 {
			// Closed part of long
			e.position.RealizedPnL += closed * (order.AvgPrice - e.position.AvgPrice)
		} else {
			// Closed part of short
			e.position.RealizedPnL += closed * (e.position.AvgPrice - order.AvgPrice)
		}
	}
}

func (e *OrderExecutor) recordOrder(order *Order) {
	e.ordersMu.Lock()
	defer e.ordersMu.Unlock()

	e.orders[order.ID] = order
	e.history = append(e.history, order)
}

func (e *OrderExecutor) getCurrentPrice() float64 {
	// Would get from order book or last trade
	// Placeholder
	return 50000.0
}

// GetPosition returns current position
func (e *OrderExecutor) GetPosition() *Position {
	e.position.mu.RLock()
	defer e.position.mu.RUnlock()

	// Return a copy
	return &Position{
		Symbol:      e.position.Symbol,
		Size:        e.position.Size,
		AvgPrice:    e.position.AvgPrice,
		RealizedPnL: e.position.RealizedPnL,
	}
}

// GetOpenOrders returns list of open orders
func (e *OrderExecutor) GetOpenOrders() []*Order {
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

// Helpers

func generateOrderID() string {
	return fmt.Sprintf("ord_%d", time.Now().UnixNano())
}

func sideToString(side OrderSide) string {
	if side == SideBuy {
		return "BUY"
	}
	return "SELL"
}

// orderTypeToString converts OrderType to string
func orderTypeToString(t OrderType) string {
	switch t {
	case TypeMarket:
		return "MARKET"
	case TypeLimit:
		return "LIMIT"
	case TypeStopMarket:
		return "STOP_MARKET"
	default:
		return "UNKNOWN"
	}
}

// orderStatusToString converts OrderStatus to string
func orderStatusToString(s OrderStatus) string {
	switch s {
	case StatusPending:
		return "PENDING"
	case StatusOpen:
		return "OPEN"
	case StatusPartiallyFilled:
		return "PARTIALLY_FILLED"
	case StatusFilled:
		return "FILLED"
	case StatusCancelled:
		return "CANCELLED"
	case StatusRejected:
		return "REJECTED"
	default:
		return "UNKNOWN"
	}
}

// logOrderToWAL logs order event to WAL
func (e *OrderExecutor) logOrderToWAL(order *Order) {
	if e.wal == nil {
		return
	}

	entry := OrderEntry{
		Symbol: order.Symbol,
		Side:   sideToString(order.Side),
		Type:   orderTypeToString(order.Type),
		Price:  order.Price,
		Size:   order.Size,
		Status: orderStatusToString(order.Status),
	}

	if err := e.wal.LogOrder(order.ID, entry); err != nil {
		log.Printf("[EXEC] Failed to log order to WAL: %v", err)
	}
}

// logFillToWAL logs fill event to WAL
func (e *OrderExecutor) logFillToWAL(order *Order, fillPrice, fillSize, fee float64) {
	if e.wal == nil {
		return
	}

	entry := FillEntry{
		OrderID:   order.ID,
		FillPrice: fillPrice,
		FillSize:  fillSize,
		Fee:       fee,
	}

	if err := e.wal.LogFill(order.ID, entry); err != nil {
		log.Printf("[EXEC] Failed to log fill to WAL: %v", err)
	}
}

// logCancelToWAL logs cancel event to WAL
func (e *OrderExecutor) logCancelToWAL(orderID string) {
	if e.wal == nil {
		return
	}

	if err := e.wal.LogCancel(orderID); err != nil {
		log.Printf("[EXEC] Failed to log cancel to WAL: %v", err)
	}
}

// orderSyncLoop periodically syncs order status from Binance
func (e *OrderExecutor) orderSyncLoop() {
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			e.syncAllOpenOrders()
		case <-e.stopSync:
			return
		}
	}
}

// syncAllOpenOrders syncs status of all open orders from Binance
func (e *OrderExecutor) syncAllOpenOrders() {
	if e.binanceClient == nil {
		return
	}

	openOrders := e.GetOpenOrders()
	if len(openOrders) == 0 {
		return
	}

	for _, order := range openOrders {
		if order.BinanceOrderID == 0 {
			continue
		}

		updatedOrder, err := e.SyncOrderStatus(order.BinanceOrderID)
		if err != nil {
			log.Printf("[EXEC] Failed to sync order %d: %v", order.BinanceOrderID, err)
			continue
		}

		// Log status changes
		if updatedOrder.Status != order.Status {
			log.Printf("[EXEC] Order %s status changed: %s -> %s",
				order.ID, orderStatusToString(order.Status), orderStatusToString(updatedOrder.Status))

			e.logOrderToWAL(updatedOrder)

			// If filled, update position, log fill, and untrack from STP
			if updatedOrder.Status == StatusFilled {
				e.updatePosition(updatedOrder)
				fillSize := updatedOrder.Filled - order.Filled
				if fillSize > 0 {
					e.logFillToWAL(updatedOrder, updatedOrder.AvgPrice, fillSize, 0)
				}
				// Untrack from STP when order is fully filled
				if e.stp != nil {
					e.stp.UntrackOrder(order.ID)
				}
			}

			// If cancelled, untrack from STP
			if updatedOrder.Status == StatusCancelled {
				if e.stp != nil {
					e.stp.UntrackOrder(order.ID)
				}
			}
		}
	}
}

// Close cleans up executor resources
func (e *OrderExecutor) Close() {
	// Stop sync loop
	close(e.stopSync)

	// Close WAL
	if e.wal != nil {
		if err := e.wal.Close(); err != nil {
			log.Printf("[EXEC] Failed to close WAL: %v", err)
		}
	}
}

// GetOrderHistory returns order history
func (e *OrderExecutor) GetOrderHistory() []*Order {
	e.ordersMu.RLock()
	defer e.ordersMu.RUnlock()

	// Return copy
	history := make([]*Order, len(e.history))
	copy(history, e.history)
	return history
}

// GetSTP returns the self-trade prevention instance
func (e *OrderExecutor) GetSTP() *SelfTradePrevention {
	return e.stp
}

// GetOrderByID returns order by ID
func (e *OrderExecutor) GetOrderByID(orderID string) (*Order, bool) {
	e.ordersMu.RLock()
	defer e.ordersMu.RUnlock()

	order, exists := e.orders[orderID]
	return order, exists
}

// GetOrders returns all orders (count for metrics)
func (e *OrderExecutor) GetOrders() map[string]*Order {
	e.ordersMu.RLock()
	defer e.ordersMu.RUnlock()

	return e.orders
}
