package main

import (
	"fmt"
	"log"
	"sync"
	"time"
)

/*
stp.go - Self-Trade Prevention Implementation

Prevents accidental self-trading by checking for order conflicts
before order submission and applying configured prevention strategies.

Usage:
  stp := NewSelfTradePrevention(config)

  // Check before placing order
  result := stp.CheckOrder(symbol, side, price, size, existingOrders)
  if result.ShouldPrevent {
      // Handle prevention (reject, cancel, etc.)
      return stp.ApplyPrevention(result)
  }

  // Place order if safe
  placeOrder(...)

  // Track the new order
  stp.TrackOrder(orderID, symbol, side, price, size)

  // When order is filled or cancelled
  stp.UntrackOrder(orderID)
*/

// STPCheckResult represents the result of a self-trade check
type STPCheckResult struct {
	ShouldPrevent   bool
	ConflictingOrders []*Order
	Mode            STPMode
	Message         string
	Event           *STPEvent
}

// SelfTradePrevention manages self-trade prevention
type SelfTradePrevention struct {
	config      *STPConfig
	orders      map[string]*Order // tracked orders by ID
	ordersMu    sync.RWMutex
	events      []STPEvent
	eventsMu    sync.RWMutex
	eventCallback func(STPEvent)

	// Metrics
	preventCount   int64
	cancelCount    int64
	rejectCount    int64
	decrementCount int64
	metricsMu      sync.RWMutex

	// Cooldown tracking
	lastAlertTime  time.Time
}

// NewSelfTradePrevention creates a new STP manager
func NewSelfTradePrevention(config *STPConfig) *SelfTradePrevention {
	if config == nil {
		config = DefaultSTPConfig()
	}

	return &SelfTradePrevention{
		config:     config,
		orders:     make(map[string]*Order),
		events:     make([]STPEvent, 0),
		lastAlertTime: time.Time{},
	}
}

// SetEventCallback sets a callback for STP events
func (stp *SelfTradePrevention) SetEventCallback(cb func(STPEvent)) {
	eventCallback := cb
	stp.eventCallback = eventCallback
}

// TrackOrder adds an order to STP tracking
func (stp *SelfTradePrevention) TrackOrder(order *Order) {
	stp.ordersMu.Lock()
	defer stp.ordersMu.Unlock()

	stp.orders[order.ID] = order
}

// UntrackOrder removes an order from STP tracking
func (stp *SelfTradePrevention) UntrackOrder(orderID string) {
	stp.ordersMu.Lock()
	defer stp.ordersMu.Unlock()

	delete(stp.orders, orderID)
}

// UpdateOrder updates a tracked order
func (stp *SelfTradePrevention) UpdateOrder(order *Order) {
	stp.ordersMu.Lock()
	defer stp.ordersMu.Unlock()

	stp.orders[order.ID] = order
}

// GetTrackedOrders returns all tracked orders for a symbol
func (stp *SelfTradePrevention) GetTrackedOrders(symbol string) []*Order {
	stp.ordersMu.RLock()
	defer stp.ordersMu.RUnlock()

	var orders []*Order
	for _, order := range stp.orders {
		if order.Symbol == symbol {
			orders = append(orders, order)
		}
	}
	return orders
}

// CheckOrder checks if a new order would cause self-trade
func (stp *SelfTradePrevention) CheckOrder(symbol string, side OrderSide, price, size float64, newOrderID string) *STPCheckResult {
	// If STP is disabled, allow all orders
	if !stp.config.EnableSTP || stp.config.Mode == STPModeNone {
		return &STPCheckResult{ShouldPrevent: false}
	}

	// Get opposite side
	oppositeSide := SideSell
	if side == SideSell {
		oppositeSide = SideBuy
	}

	// Get tracked orders for this symbol
	existingOrders := stp.GetTrackedOrders(symbol)

	var conflicts []*Order

	for _, existing := range existingOrders {
		// Skip if same side (can't self-trade with same side)
		if existing.Side != oppositeSide {
			continue
		}

		// Skip filled or cancelled orders
		if existing.Status == StatusFilled || existing.Status == StatusCancelled {
			continue
		}

		// Check if prices cross (would result in self-trade)
		if stp.wouldSelfTrade(side, price, existing) {
			conflicts = append(conflicts, existing)
		}
	}

	if len(conflicts) == 0 {
		return &STPCheckResult{ShouldPrevent: false}
	}

	// Build event
	oldestConflict := conflicts[0]
	event := &STPEvent{
		Timestamp:       time.Now(),
		Mode:            stp.config.Mode,
		Symbol:          symbol,
		NewOrderID:      newOrderID,
		ExistingOrderID: oldestConflict.ID,
		Side:            side,
		Price:           price,
		Size:            size,
	}

	// Determine action based on mode
	result := &STPCheckResult{
		ShouldPrevent:     true,
		ConflictingOrders: conflicts,
		Mode:              stp.config.Mode,
		Event:             event,
	}

	switch stp.config.Mode {
	case STPModeReject:
		event.Action = "REJECT"
		event.Reason = fmt.Sprintf("Self-trade detected with order %s", oldestConflict.ID)
		result.Message = fmt.Sprintf("Order rejected: would self-trade with %s", oldestConflict.ID)

	case STPModeCancelOldest:
		event.Action = "CANCEL_OLDEST"
		event.Reason = fmt.Sprintf("Cancelling oldest order %s to accept new order", oldestConflict.ID)
		result.Message = fmt.Sprintf("Will cancel order %s and accept new order", oldestConflict.ID)

	case STPModeCancelNewest:
		event.Action = "CANCEL_NEWEST"
		event.Reason = "New order rejected (cancel newest policy)"
		result.Message = "Order rejected: cancel newest policy"

	case STPModeDecrement:
		event.Action = "DECREMENT"
		event.Reason = fmt.Sprintf("Reducing quantities for self-trade with %s", oldestConflict.ID)
		result.Message = fmt.Sprintf("Will reduce order sizes to prevent self-trade with %s", oldestConflict.ID)
	}

	return result
}

// wouldSelfTrade checks if a new order would self-trade with an existing order
func (stp *SelfTradePrevention) wouldSelfTrade(newSide OrderSide, newPrice float64, existing *Order) bool {
	tolerance := stp.config.PriceTolerance

	switch existing.Type {
	case TypeLimit:
		// For limit orders, check if prices cross
		if newSide == SideBuy {
			// Buy order: self-trade if buy price >= existing sell price
			if newPrice*(1+tolerance) >= existing.Price*(1-tolerance) {
				return true
			}
		} else {
			// Sell order: self-trade if sell price <= existing buy price
			if newPrice*(1-tolerance) <= existing.Price*(1+tolerance) {
				return true
			}
		}

	case TypeMarket:
		// Market orders always self-trade with opposite side
		return true
	}

	return false
}

// ApplyPrevention applies the configured prevention strategy
func (stp *SelfTradePrevention) ApplyPrevention(result *STPCheckResult, executor *OrderExecutor) error {
	if !result.ShouldPrevent {
		return nil
	}

	// Record event
	stp.recordEvent(*result.Event)

	// Log if enabled
	if stp.config.LogSelfTradeEvents {
		log.Printf("[STP] %s", result.Event.String())
	}

	// Apply prevention strategy
	switch result.Mode {
	case STPModeReject:
		stp.incrementMetric("reject")
		return fmt.Errorf("%s", result.Message)

	case STPModeCancelOldest:
		if len(result.ConflictingOrders) > 0 {
			oldest := result.ConflictingOrders[0]
			// Find oldest by creation time
			for _, order := range result.ConflictingOrders {
				if order.CreatedAt.Before(oldest.CreatedAt) {
					oldest = order
				}
			}

			if executor != nil && oldest.BinanceOrderID != 0 {
				if err := executor.CancelOrder(oldest.BinanceOrderID); err != nil {
					return fmt.Errorf("failed to cancel oldest order: %w", err)
				}
			}

			stp.UntrackOrder(oldest.ID)
			stp.incrementMetric("cancel")
		}
		return nil

	case STPModeCancelNewest:
		stp.incrementMetric("cancel")
		return fmt.Errorf("%s", result.Message)

	case STPModeDecrement:
		// For decrement mode, we need to reduce quantities
		// This is complex and typically requires exchange support
		// For now, reject the order
		stp.incrementMetric("decrement")
		return fmt.Errorf("DECREMENT mode not fully implemented, order rejected")
	}

	return nil
}

// recordEvent records an STP event
func (stp *SelfTradePrevention) recordEvent(event STPEvent) {
	stp.eventsMu.Lock()
	defer stp.eventsMu.Unlock()

	stp.events = append(stp.events, event)

	// Keep only last 1000 events
	if len(stp.events) > 1000 {
		stp.events = stp.events[len(stp.events)-1000:]
	}

	// Call callback if set
	if stp.eventCallback != nil {
		go stp.eventCallback(event)
	}
}

// GetEvents returns recent STP events
func (stp *SelfTradePrevention) GetEvents(limit int) []STPEvent {
	stp.eventsMu.RLock()
	defer stp.eventsMu.RUnlock()

	if limit <= 0 || limit > len(stp.events) {
		limit = len(stp.events)
	}

	// Return most recent events
	start := len(stp.events) - limit
	if start < 0 {
		start = 0
	}

	result := make([]STPEvent, limit)
	copy(result, stp.events[start:])
	return result
}

// GetMetrics returns STP prevention metrics
func (stp *SelfTradePrevention) GetMetrics() map[string]int64 {
	stp.metricsMu.RLock()
	defer stp.metricsMu.RUnlock()

	return map[string]int64{
		"prevent_count":   stp.preventCount,
		"reject_count":    stp.rejectCount,
		"cancel_count":    stp.cancelCount,
		"decrement_count": stp.decrementCount,
	}
}

// incrementMetric increments a metric counter
func (stp *SelfTradePrevention) incrementMetric(metric string) {
	stp.metricsMu.Lock()
	defer stp.metricsMu.Unlock()

	stp.preventCount++

	switch metric {
	case "reject":
		stp.rejectCount++
	case "cancel":
		stp.cancelCount++
	case "decrement":
		stp.decrementCount++
	}
}

// ResetMetrics resets all metrics
func (stp *SelfTradePrevention) ResetMetrics() {
	stp.metricsMu.Lock()
	defer stp.metricsMu.Unlock()

	stp.preventCount = 0
	stp.rejectCount = 0
	stp.cancelCount = 0
	stp.decrementCount = 0
}

// ClearEvents clears all recorded events
func (stp *SelfTradePrevention) ClearEvents() {
	stp.eventsMu.Lock()
	defer stp.eventsMu.Unlock()

	stp.events = make([]STPEvent, 0)
}

// IsEnabled returns whether STP is enabled
func (stp *SelfTradePrevention) IsEnabled() bool {
	return stp.config.EnableSTP
}

// GetMode returns the current STP mode
func (stp *SelfTradePrevention) GetMode() STPMode {
	return stp.config.Mode
}

// SetMode changes the STP mode
func (stp *SelfTradePrevention) SetMode(mode STPMode) {
	stp.config.Mode = mode
	log.Printf("[STP] Mode changed to %s", mode)
}

// Enable enables STP
func (stp *SelfTradePrevention) Enable() {
	stp.config.EnableSTP = true
	log.Println("[STP] Self-trade prevention enabled")
}

// Disable disables STP
func (stp *SelfTradePrevention) Disable() {
	stp.config.EnableSTP = false
	log.Println("[STP] Self-trade prevention disabled")
}

// GetOrderCount returns the number of tracked orders
func (stp *SelfTradePrevention) GetOrderCount() int {
	stp.ordersMu.RLock()
	defer stp.ordersMu.RUnlock()

	return len(stp.orders)
}
