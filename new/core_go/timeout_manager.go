package main

import (
	"context"
	"fmt"
	"log"
	"sync"
	"time"
)

/*
timeout_manager.go - Order Timeout Management System (P5-104)

Handles automatic timeout detection and cancellation for orders:
- Limit order timeout detection (default 5 minutes)
- Partial fill timeout handling
- Configurable timeout per order type
- Automatic cancellation with retry
- Timeout statistics and reporting

Integration:
- Monitors OrderExecutor for open orders
- Uses LiveAPIClient to cancel timed-out orders
- Logs timeout events to WAL for audit
- Updates order state via OrderFSM
*/

// TimeoutManager manages order timeouts and automatic cancellation
type TimeoutManager struct {
	executor *OrderExecutor
	client   *LiveAPIClient
	wal      *WAL

	// Configuration
	limitOrderTimeout    time.Duration // Timeout for limit orders (default 5m)
	partialFillTimeout   time.Duration // Timeout for partially filled orders (default 10m)
	checkInterval        time.Duration // How often to check for timeouts (default 10s)
	autoCancel           bool          // Automatically cancel timed-out orders
	maxCancelRetries     int           // Max retries for cancellation (default 3)

	// Runtime state
	isRunning bool
	stopCh    chan struct{}
	wg        sync.WaitGroup
	mu        sync.Mutex

	// Tracked orders with timeout info
	trackedOrders map[string]*TimeoutInfo
	ordersMu      sync.RWMutex

	// Statistics
	stats   TimeoutStats
	statsMu sync.RWMutex
}

// TimeoutInfo tracks timeout information for an order
type TimeoutInfo struct {
	OrderID       string
	Symbol        string
	CreatedAt     time.Time
	Deadline      time.Time       // When timeout occurs
	Status        OrderStatus     // Status when tracking started
	FilledAtStart float64         // Filled amount when tracking started
	IsPartial     bool            // Whether this is a partial fill timeout
	RetryCount    int             // Cancel retry attempts
	LastCancelAt  *time.Time      // Last cancellation attempt time
}

// TimeoutStats tracks timeout statistics
type TimeoutStats struct {
	TotalTimeouts     int64
	TotalCancelled    int64
	CancelFailures    int64
	PartialTimeouts   int64
	RetrySuccesses    int64
	LastTimeoutAt     *time.Time
	LastCheckDuration time.Duration
	OrdersBeingTracked int
}

// TimeoutResult contains the result of a timeout check
type TimeoutResult struct {
	Timestamp    time.Time
	Checked      int           // Number of orders checked
	TimedOut     []TimedOutOrder // List of timed out orders
	Cancelled    int           // Number successfully cancelled
	Failed       int           // Number of cancel failures
	Errors       []error
}

// TimedOutOrder represents an order that has timed out
type TimedOutOrder struct {
	OrderID    string
	Symbol     string
	CreatedAt  time.Time
	TimeoutAt  time.Time
	Filled     float64
	Size       float64
	IsPartial  bool
	Reason     string
}

// TimeoutConfig configuration for timeout manager
type TimeoutConfig struct {
	LimitOrderTimeout  time.Duration // How long before limit order times out (default 5m)
	PartialFillTimeout time.Duration // How long before partial fill times out (default 10m)
	CheckInterval      time.Duration // How often to check (default 10s)
	AutoCancel         bool          // Auto-cancel timed out orders (default true)
	MaxCancelRetries   int           // Max cancel retries (default 3)
}

// DefaultTimeoutConfig returns default configuration
func DefaultTimeoutConfig() *TimeoutConfig {
	return &TimeoutConfig{
		LimitOrderTimeout:  5 * time.Minute,
		PartialFillTimeout: 10 * time.Minute,
		CheckInterval:      10 * time.Second,
		AutoCancel:         true,
		MaxCancelRetries:   3,
	}
}

// NewTimeoutManager creates a new timeout manager
func NewTimeoutManager(executor *OrderExecutor, client *LiveAPIClient, wal *WAL, config *TimeoutConfig) *TimeoutManager {
	if config == nil {
		config = DefaultTimeoutConfig()
	}

	return &TimeoutManager{
		executor:           executor,
		client:             client,
		wal:                wal,
		limitOrderTimeout:  config.LimitOrderTimeout,
		partialFillTimeout: config.PartialFillTimeout,
		checkInterval:      config.CheckInterval,
		autoCancel:         config.AutoCancel,
		maxCancelRetries:   config.MaxCancelRetries,
		stopCh:             make(chan struct{}),
		trackedOrders:      make(map[string]*TimeoutInfo),
	}
}

// Start starts the timeout monitoring loop
func (tm *TimeoutManager) Start() error {
	tm.mu.Lock()
	if tm.isRunning {
		tm.mu.Unlock()
		return fmt.Errorf("timeout manager already running")
	}
	tm.isRunning = true
	tm.stopCh = make(chan struct{})
	tm.mu.Unlock()

	// Start timeout check loop
	tm.wg.Add(1)
	go tm.timeoutLoop()

	log.Printf("[TimeoutManager] Started with check interval %v", tm.checkInterval)
	log.Printf("[TimeoutManager] Limit order timeout: %v, Partial fill timeout: %v",
		tm.limitOrderTimeout, tm.partialFillTimeout)
	return nil
}

// Stop stops the timeout manager
func (tm *TimeoutManager) Stop() {
	tm.mu.Lock()
	if !tm.isRunning {
		tm.mu.Unlock()
		return
	}
	tm.isRunning = false
	close(tm.stopCh)
	tm.mu.Unlock()

	tm.wg.Wait()
	log.Println("[TimeoutManager] Stopped")
}

// IsRunning returns whether the timeout manager is running
func (tm *TimeoutManager) IsRunning() bool {
	tm.mu.Lock()
	defer tm.mu.Unlock()
	return tm.isRunning
}

// timeoutLoop runs timeout checks periodically
func (tm *TimeoutManager) timeoutLoop() {
	defer tm.wg.Done()

	ticker := time.NewTicker(tm.checkInterval)
	defer ticker.Stop()

	// Run immediately on start
	tm.runTimeoutCheck()

	for {
		select {
		case <-tm.stopCh:
			return
		case <-ticker.C:
			tm.runTimeoutCheck()
		}
	}
}

// runTimeoutCheck performs a single timeout check
func (tm *TimeoutManager) runTimeoutCheck() {
	start := time.Now()

	ctx, cancel := context.WithTimeout(context.Background(), tm.checkInterval)
	defer cancel()

	result, err := tm.CheckTimeouts(ctx)
	if err != nil {
		log.Printf("[TimeoutManager] Timeout check failed: %v", err)
		return
	}

	duration := time.Since(start)

	// Update statistics
	tm.statsMu.Lock()
	tm.stats.LastCheckDuration = duration
	if len(result.TimedOut) > 0 {
		tm.stats.TotalTimeouts += int64(len(result.TimedOut))
		tm.stats.LastTimeoutAt = &result.Timestamp
		tm.stats.TotalCancelled += int64(result.Cancelled)
	}
	tm.stats.OrdersBeingTracked = len(tm.trackedOrders)
	tm.statsMu.Unlock()

	// Log results
	if len(result.TimedOut) > 0 {
		log.Printf("[TimeoutManager] Found %d timed out orders, cancelled %d, failed %d (took %v)",
			len(result.TimedOut), result.Cancelled, result.Failed, duration)
		for _, to := range result.TimedOut {
			log.Printf("[TimeoutManager] Timed out: %s %s (filled: %.4f/%.4f, reason: %s)",
				to.OrderID, to.Symbol, to.Filled, to.Size, to.Reason)
		}
	}
}

// CheckTimeouts checks for timed out orders and cancels them
func (tm *TimeoutManager) CheckTimeouts(ctx context.Context) (*TimeoutResult, error) {
	result := &TimeoutResult{
		Timestamp: time.Now(),
		TimedOut:  make([]TimedOutOrder, 0),
		Errors:    make([]error, 0),
	}

	// Get open orders from executor
	tm.executor.ordersMu.RLock()
	orders := make([]*Order, 0)
	for _, order := range tm.executor.orders {
		// Only check non-terminal orders
		if order.Status == StatusOpen || order.Status == StatusPartiallyFilled {
			orders = append(orders, order)
		}
	}
	tm.executor.ordersMu.RUnlock()

	result.Checked = len(orders)
	now := time.Now()

	for _, order := range orders {
		// Determine timeout based on order status
		timeout := tm.limitOrderTimeout
		isPartial := false

		if order.Status == StatusPartiallyFilled {
			timeout = tm.partialFillTimeout
			isPartial = true
		}

		// Check if order has timed out
		deadline := order.CreatedAt.Add(timeout)
		if now.After(deadline) {
			timedOut := TimedOutOrder{
				OrderID:   order.ID,
				Symbol:    order.Symbol,
				CreatedAt: order.CreatedAt,
				TimeoutAt: now,
				Filled:    order.Filled,
				Size:      order.Size,
				IsPartial: isPartial,
			}

			if isPartial {
				timedOut.Reason = fmt.Sprintf("Partial fill timeout after %v (%.2f%% filled)",
					timeout, (order.Filled/order.Size)*100)
			} else {
				timedOut.Reason = fmt.Sprintf("Limit order timeout after %v", timeout)
			}

			result.TimedOut = append(result.TimedOut, timedOut)

			// Track this timeout
			tm.trackTimeout(order, isPartial, now)

			// Auto-cancel if enabled
			if tm.autoCancel {
				if err := tm.cancelOrder(ctx, order); err != nil {
					result.Errors = append(result.Errors,
						fmt.Errorf("failed to cancel order %s: %w", order.ID, err))
					result.Failed++
					tm.statsMu.Lock()
					tm.stats.CancelFailures++
					tm.statsMu.Unlock()
				} else {
					result.Cancelled++
				}
			}
		}
	}

	// Clean up old tracked orders
	tm.cleanupTrackedOrders()

	return result, nil
}

// trackTimeout tracks a timeout event
func (tm *TimeoutManager) trackTimeout(order *Order, isPartial bool, timeoutAt time.Time) {
	tm.ordersMu.Lock()
	defer tm.ordersMu.Unlock()

	tm.trackedOrders[order.ID] = &TimeoutInfo{
		OrderID:       order.ID,
		Symbol:        order.Symbol,
		CreatedAt:     order.CreatedAt,
		Deadline:      timeoutAt,
		Status:        order.Status,
		FilledAtStart: order.Filled,
		IsPartial:     isPartial,
	}
}

// cleanupTrackedOrders removes completed/cancelled orders from tracking
func (tm *TimeoutManager) cleanupTrackedOrders() {
	tm.ordersMu.Lock()
	defer tm.ordersMu.Unlock()

	toRemove := make([]string, 0)
	for id, _ := range tm.trackedOrders {
		// Check if order still exists and needs tracking
		tm.executor.ordersMu.RLock()
		order, exists := tm.executor.orders[id]
		tm.executor.ordersMu.RUnlock()

		if !exists {
			toRemove = append(toRemove, id)
			continue
		}

		// Remove if order is in terminal state
		if order.Status == StatusFilled || order.Status == StatusCancelled ||
			order.Status == StatusRejected {
			toRemove = append(toRemove, id)
		}
	}

	for _, id := range toRemove {
		delete(tm.trackedOrders, id)
	}
}

// cancelOrder cancels a timed out order
func (tm *TimeoutManager) cancelOrder(ctx context.Context, order *Order) error {
	log.Printf("[TimeoutManager] Cancelling timed out order %s (%s)", order.ID, order.Symbol)

	// Get timeout info for retry tracking
	tm.ordersMu.RLock()
	timeoutInfo := tm.trackedOrders[order.ID]
	tm.ordersMu.RUnlock()

	// Try to cancel the order
	var lastErr error
	for attempt := 0; attempt <= tm.maxCancelRetries; attempt++ {
		if attempt > 0 {
			log.Printf("[TimeoutManager] Retry %d/%d for cancelling order %s",
				attempt, tm.maxCancelRetries, order.ID)
			time.Sleep(time.Duration(attempt) * time.Second) // Exponential backoff
		}

		err := tm.tryCancelOrder(ctx, order)
		if err == nil {
			// Success
			if attempt > 0 {
				tm.statsMu.Lock()
				tm.stats.RetrySuccesses++
				tm.statsMu.Unlock()
			}
			return nil
		}

		lastErr = err

		// Update retry count
		if timeoutInfo != nil {
			tm.ordersMu.Lock()
			timeoutInfo.RetryCount = attempt + 1
			now := time.Now()
			timeoutInfo.LastCancelAt = &now
			tm.ordersMu.Unlock()
		}

		// Check if order is already cancelled/filled
		tm.executor.ordersMu.RLock()
		currentOrder, exists := tm.executor.orders[order.ID]
		tm.executor.ordersMu.RUnlock()

		if !exists || currentOrder.Status == StatusCancelled ||
			currentOrder.Status == StatusFilled {
			log.Printf("[TimeoutManager] Order %s no longer needs cancellation (status: %d)",
				order.ID, currentOrder.Status)
			return nil
		}
	}

	return fmt.Errorf("failed to cancel after %d retries: %w", tm.maxCancelRetries, lastErr)
}

// tryCancelOrder attempts a single cancellation
func (tm *TimeoutManager) tryCancelOrder(ctx context.Context, order *Order) error {
	// Update local state first
	tm.executor.ordersMu.Lock()
	order.Status = StatusCancelled
	order.UpdatedAt = time.Now()
	tm.executor.ordersMu.Unlock()

	// Log to WAL
	if tm.wal != nil {
		tm.wal.LogOrder(order.ID, OrderEntry{
			Symbol: order.Symbol,
			Side:   sideToString(order.Side),
			Type:   typeToString(order.Type),
			Price:  order.Price,
			Size:   order.Size,
			Status: "TIMEOUT_CANCELLED",
		})
	}

	// Cancel on exchange if live trading
	if !tm.executor.paperTrading && tm.client != nil && order.BinanceOrderID > 0 {
		if err := tm.client.CancelOrder(ctx, order.Symbol, order.BinanceOrderID); err != nil {
			// Revert local state on failure
			tm.executor.ordersMu.Lock()
			order.Status = StatusOpen
			order.UpdatedAt = time.Now()
			tm.executor.ordersMu.Unlock()
			return fmt.Errorf("exchange cancel failed: %w", err)
		}
	}

	log.Printf("[TimeoutManager] Successfully cancelled order %s", order.ID)
	return nil
}

// ForceCheck triggers an immediate timeout check
func (tm *TimeoutManager) ForceCheck(ctx context.Context) (*TimeoutResult, error) {
	return tm.CheckTimeouts(ctx)
}

// GetStats returns timeout statistics
func (tm *TimeoutManager) GetStats() TimeoutStats {
	tm.statsMu.RLock()
	defer tm.statsMu.RUnlock()

	// Update current tracking count
	stats := tm.stats
	tm.ordersMu.RLock()
	stats.OrdersBeingTracked = len(tm.trackedOrders)
	tm.ordersMu.RUnlock()

	return stats
}

// SetAutoCancel enables/disables automatic cancellation
func (tm *TimeoutManager) SetAutoCancel(enabled bool) {
	tm.mu.Lock()
	defer tm.mu.Unlock()
	tm.autoCancel = enabled
	log.Printf("[TimeoutManager] Auto cancel %v", enabled)
}

// UpdateTimeouts updates timeout durations dynamically
func (tm *TimeoutManager) UpdateTimeouts(limitOrderTimeout, partialFillTimeout time.Duration) {
	tm.mu.Lock()
	defer tm.mu.Unlock()

	if limitOrderTimeout > 0 {
		tm.limitOrderTimeout = limitOrderTimeout
	}
	if partialFillTimeout > 0 {
		tm.partialFillTimeout = partialFillTimeout
	}

	log.Printf("[TimeoutManager] Updated timeouts - Limit: %v, Partial: %v",
		tm.limitOrderTimeout, tm.partialFillTimeout)
}

// GetTrackedOrders returns information about currently tracked orders
func (tm *TimeoutManager) GetTrackedOrders() []TimeoutInfo {
	tm.ordersMu.RLock()
	defer tm.ordersMu.RUnlock()

	result := make([]TimeoutInfo, 0, len(tm.trackedOrders))
	for _, info := range tm.trackedOrders {
		result = append(result, *info)
	}
	return result
}

