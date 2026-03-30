package main

import (
	"fmt"
	"log"
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
	symbol       string
	paperTrading bool
	position     *Position
	orders       map[string]*Order
	ordersMu     sync.RWMutex
	history      []*Order
	apiClient    interface{} // Would be *binance.Client for live trading
}

func NewOrderExecutor(symbol string, paperTrading bool) *OrderExecutor {
	return &OrderExecutor{
		symbol:       symbol,
		paperTrading: paperTrading,
		position: &Position{
			Symbol:     symbol,
			OpenOrders: make([]*Order, 0),
		},
		orders:  make(map[string]*Order),
		history: make([]*Order, 0),
	}
}

func (e *OrderExecutor) PlaceLimitBuy(price, size float64) error {
	if e.paperTrading {
		return e.simulateLimitOrder(SideBuy, price, size)
	}
	return e.placeLiveLimitOrder(SideBuy, price, size)
}

func (e *OrderExecutor) PlaceLimitSell(price, size float64) error {
	if e.paperTrading {
		return e.simulateLimitOrder(SideSell, price, size)
	}
	return e.placeLiveLimitOrder(SideSell, price, size)
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

func (e *OrderExecutor) simulateLimitOrder(side OrderSide, price, size float64) error {
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

	log.Printf("[PAPER] Limit %s: %.4f @ %.2f (order %s)",
		sideToString(side), size, price, order.ID)

	return nil
}

// Live trading (would integrate with Binance API)

func (e *OrderExecutor) placeLiveMarketOrder(side OrderSide, size float64) error {
	// TODO: Integrate with Binance API
	// This would use the official Binance Go SDK or REST API
	return fmt.Errorf("live trading not yet implemented")
}

func (e *OrderExecutor) placeLiveLimitOrder(side OrderSide, price, size float64) error {
	// TODO: Integrate with Binance API
	return fmt.Errorf("live trading not yet implemented")
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
