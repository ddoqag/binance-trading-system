package main

import (
	"context"
	"fmt"
	"log"
	"strconv"
	"sync"
	"time"

	"github.com/adshao/go-binance/v2"
)

/*
reconciler.go - Order Reconciliation System (P5-102)

Ensures consistency between local order state and exchange state:
- Periodic reconciliation of open orders
- Mismatch detection and automatic repair
- Missing order detection (orders on exchange but not local)
- Orphan order detection (local orders not on exchange)
- Audit logging for all reconciliation actions

Integration:
- Works with OrderExecutor to sync order state
- Uses LiveAPIClient for exchange queries
- Logs discrepancies to WAL for audit
*/

// Reconciler manages order state synchronization
type Reconciler struct {
	executor *OrderExecutor
	client   *LiveAPIClient
	wal      *WAL

	// Configuration
	interval   time.Duration // Reconciliation interval
	timeout    time.Duration // API call timeout
	autoRepair bool          // Automatically fix mismatches

	// Runtime state
	isRunning bool
	stopCh    chan struct{}
	wg        sync.WaitGroup
	mu        sync.Mutex

	// Statistics
	stats   ReconcilerStats
	statsMu sync.RWMutex
}

// ReconcilerStats tracks reconciliation metrics
type ReconcilerStats struct {
	TotalRuns       int64
	MismatchesFound int64
	MismatchesFixed int64
	MissingOrders   int64
	OrphanOrders    int64
	LastRun         time.Time
	LastMismatch    time.Time
	LastError       string
	LastErrorTime   time.Time
}

// ReconciliationResult contains the results of a reconciliation run
type ReconciliationResult struct {
	Timestamp  time.Time
	Duration   time.Duration
	Checked    int              // Number of orders checked
	Mismatches []OrderMismatch  // List of mismatches found
	Missing    []MissingOrder   // Orders on exchange but not local
	Orphans    []OrphanOrder    // Local orders not on exchange
	Fixed      int              // Number of issues auto-fixed
	Errors     []error          // Any errors encountered
}

// OrderMismatch represents a state mismatch between local and exchange
type OrderMismatch struct {
	OrderID       string
	LocalState    OrderStatus
	ExchangeState string
	ExchangeOrder *binance.Order
	Reason        string
}

// MissingOrder represents an order on exchange but not tracked locally
type MissingOrder struct {
	ExchangeOrder *binance.Order
	Reason        string
}

// OrphanOrder represents a local order not found on exchange
type OrphanOrder struct {
	OrderID    string
	LocalState OrderStatus
	Reason     string
}

// ReconcilerConfig configuration for reconciler
type ReconcilerConfig struct {
	Interval   time.Duration // How often to reconcile (default 30s)
	Timeout    time.Duration // API timeout (default 10s)
	AutoRepair bool          // Auto-fix mismatches (default true)
}

// DefaultReconcilerConfig returns default configuration
func DefaultReconcilerConfig() *ReconcilerConfig {
	return &ReconcilerConfig{
		Interval:   30 * time.Second,
		Timeout:    10 * time.Second,
		AutoRepair: true,
	}
}

// NewReconciler creates a new order reconciler
func NewReconciler(executor *OrderExecutor, client *LiveAPIClient, wal *WAL, config *ReconcilerConfig) *Reconciler {
	if config == nil {
		config = DefaultReconcilerConfig()
	}

	return &Reconciler{
		executor:   executor,
		client:     client,
		wal:        wal,
		interval:   config.Interval,
		timeout:    config.Timeout,
		autoRepair: config.AutoRepair,
		stopCh:     make(chan struct{}),
	}
}

// Start starts the periodic reconciliation loop
func (r *Reconciler) Start() error {
	r.mu.Lock()
	if r.isRunning {
		r.mu.Unlock()
		return fmt.Errorf("reconciler already running")
	}
	r.isRunning = true
	r.stopCh = make(chan struct{})
	r.mu.Unlock()

	r.wg.Add(1)
	go r.reconcileLoop()

	log.Printf("[Reconciler] Started with interval %v", r.interval)
	return nil
}

// Stop stops the reconciliation loop
func (r *Reconciler) Stop() {
	r.mu.Lock()
	if !r.isRunning {
		r.mu.Unlock()
		return
	}
	r.isRunning = false
	close(r.stopCh)
	r.mu.Unlock()

	r.wg.Wait()
	log.Println("[Reconciler] Stopped")
}

// IsRunning returns whether the reconciler is running
func (r *Reconciler) IsRunning() bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.isRunning
}

// reconcileLoop runs reconciliation periodically
func (r *Reconciler) reconcileLoop() {
	defer r.wg.Done()

	ticker := time.NewTicker(r.interval)
	defer ticker.Stop()

	// Run immediately on start
	r.runReconciliation()

	for {
		select {
		case <-r.stopCh:
			return
		case <-ticker.C:
			r.runReconciliation()
		}
	}
}

// runReconciliation performs a single reconciliation run
func (r *Reconciler) runReconciliation() {
	start := time.Now()

	ctx, cancel := context.WithTimeout(context.Background(), r.timeout*3)
	defer cancel()

	result, err := r.Reconcile(ctx)
	if err != nil {
		r.statsMu.Lock()
		r.stats.LastError = err.Error()
		r.stats.LastErrorTime = time.Now()
		r.statsMu.Unlock()
		log.Printf("[Reconciler] Reconciliation failed: %v", err)
		return
	}

	duration := time.Since(start)

	// Update statistics
	r.statsMu.Lock()
	r.stats.TotalRuns++
	r.stats.LastRun = time.Now()
	if len(result.Mismatches) > 0 {
		r.stats.MismatchesFound += int64(len(result.Mismatches))
		r.stats.LastMismatch = time.Now()
	}
	r.stats.MismatchesFixed += int64(result.Fixed)
	r.stats.MissingOrders += int64(len(result.Missing))
	r.stats.OrphanOrders += int64(len(result.Orphans))
	r.statsMu.Unlock()

	// Log results
	if len(result.Mismatches) > 0 || len(result.Missing) > 0 || len(result.Orphans) > 0 {
		log.Printf("[Reconciler] Issues found in %v: %d mismatches, %d missing, %d orphans (fixed: %d)",
			duration, len(result.Mismatches), len(result.Missing), len(result.Orphans), result.Fixed)
	} else {
		log.Printf("[Reconciler] Reconciliation completed in %v, %d orders checked, no issues", duration, result.Checked)
	}
}

// Reconcile performs a single reconciliation between local and exchange state
func (r *Reconciler) Reconcile(ctx context.Context) (*ReconciliationResult, error) {
	result := &ReconciliationResult{
		Timestamp:  time.Now(),
		Mismatches: make([]OrderMismatch, 0),
		Missing:    make([]MissingOrder, 0),
		Orphans:    make([]OrphanOrder, 0),
		Errors:     make([]error, 0),
	}

	start := time.Now()

	// Get open orders from exchange
	exchangeOrders, err := r.client.GetOpenOrders(ctx, "")
	if err != nil {
		result.Errors = append(result.Errors, fmt.Errorf("failed to get exchange orders: %w", err))
		return result, err
	}

	// Build map of exchange orders by ClientOrderID
	exchangeMap := make(map[string]*binance.Order)
	for _, eo := range exchangeOrders {
		if eo.ClientOrderID != "" {
			exchangeMap[eo.ClientOrderID] = eo
		}
	}

	// Get local orders from executor
	r.executor.ordersMu.RLock()
	localOrders := make([]*Order, 0)
	for _, order := range r.executor.orders {
		if order.Status == StatusOpen || order.Status == StatusPending || order.Status == StatusPartiallyFilled {
			localOrders = append(localOrders, order)
		}
	}
	r.executor.ordersMu.RUnlock()

	result.Checked = len(localOrders)

	// Build map of local orders
	localMap := make(map[string]*Order)
	for _, lo := range localOrders {
		localMap[lo.ID] = lo
	}

	// Check 1: Compare local orders with exchange
	for _, local := range localOrders {
		exchangeOrder, exists := exchangeMap[local.ID]
		if !exists {
			// Local order not found on exchange - might be filled/cancelled
			orphan := OrphanOrder{
				OrderID:    local.ID,
				LocalState: local.Status,
				Reason:     "Order not found on exchange",
			}
			result.Orphans = append(result.Orphans, orphan)

			if r.autoRepair {
				if err := r.handleOrphanOrder(ctx, local); err != nil {
					result.Errors = append(result.Errors, err)
				} else {
					result.Fixed++
				}
			}
			continue
		}

		// Check for state mismatch
		exchangeState := r.mapBinanceStatusToOrderStatus(string(exchangeOrder.Status))
		if local.Status != exchangeState {
			mismatch := OrderMismatch{
				OrderID:       local.ID,
				LocalState:    local.Status,
				ExchangeState: string(exchangeOrder.Status),
				ExchangeOrder: exchangeOrder,
				Reason:        fmt.Sprintf("State mismatch: local=%d, exchange=%s", local.Status, exchangeOrder.Status),
			}
			result.Mismatches = append(result.Mismatches, mismatch)

			if r.autoRepair {
				if err := r.fixMismatch(local, exchangeOrder); err != nil {
					result.Errors = append(result.Errors, err)
				} else {
					result.Fixed++
				}
			}
		}
	}

	// Check 2: Find orders on exchange but not tracked locally
	for clientID, exchangeOrder := range exchangeMap {
		if _, exists := localMap[clientID]; !exists {
			missing := MissingOrder{
				ExchangeOrder: exchangeOrder,
				Reason:        "Order on exchange but not tracked locally",
			}
			result.Missing = append(result.Missing, missing)

			if r.autoRepair {
				if err := r.handleMissingOrder(exchangeOrder); err != nil {
					result.Errors = append(result.Errors, err)
				} else {
					result.Fixed++
				}
			}
		}
	}

	result.Duration = time.Since(start)

	// Log to WAL
	if r.wal != nil && (len(result.Mismatches) > 0 || len(result.Missing) > 0 || len(result.Orphans) > 0) {
		r.logReconciliationResult(result)
	}

	return result, nil
}

// handleOrphanOrder handles a local order not found on exchange
func (r *Reconciler) handleOrphanOrder(ctx context.Context, local *Order) error {
	log.Printf("[Reconciler] Handling orphan order %s (local state: %d)", local.ID, local.Status)

	// Query order details from exchange using BinanceOrderID
	if local.BinanceOrderID > 0 {
		order, err := r.client.GetOrder(ctx, local.Symbol, local.BinanceOrderID)
		if err != nil {
			log.Printf("[Reconciler] Failed to query orphan order %d: %v", local.BinanceOrderID, err)
			return err
		}

		// Update local state based on exchange
		newStatus := r.mapBinanceStatusToOrderStatus(string(order.Status))
		if newStatus != local.Status {
			r.executor.ordersMu.Lock()
			local.Status = newStatus
			local.UpdatedAt = time.Now()
			r.executor.ordersMu.Unlock()

			log.Printf("[Reconciler] Updated orphan order %s to status %d", local.ID, newStatus)

			// Log to WAL
			if r.wal != nil {
				r.wal.LogOrder(local.ID, OrderEntry{
					Symbol: local.Symbol,
					Side:   sideToString(local.Side),
					Type:   typeToString(local.Type),
					Price:  local.Price,
					Size:   local.Size,
					Status: string(order.Status),
				})
			}
		}
	}

	return nil
}

// fixMismatch fixes a state mismatch
func (r *Reconciler) fixMismatch(local *Order, exchangeOrder *binance.Order) error {
	log.Printf("[Reconciler] Fixing mismatch for order %s: local=%d, exchange=%s",
		local.ID, local.Status, exchangeOrder.Status)

	// Update local order state to match exchange
	newStatus := r.mapBinanceStatusToOrderStatus(string(exchangeOrder.Status))

	r.executor.ordersMu.Lock()
	local.Status = newStatus
	local.UpdatedAt = time.Now()
	// Update filled amount and average price
	if exchangeOrder.ExecutedQuantity != "" {
		executedQty, _ := strconv.ParseFloat(exchangeOrder.ExecutedQuantity, 64)
		local.Filled = executedQty
	}
	if exchangeOrder.Price != "" {
		avgPrice, _ := strconv.ParseFloat(exchangeOrder.Price, 64)
		local.AvgPrice = avgPrice
	}
	r.executor.ordersMu.Unlock()

	// Log to WAL
	if r.wal != nil {
		r.wal.LogOrder(local.ID, OrderEntry{
			Symbol: local.Symbol,
			Side:   sideToString(local.Side),
			Type:   typeToString(local.Type),
			Price:  local.Price,
			Size:   local.Size,
			Status: string(exchangeOrder.Status),
		})
	}

	return nil
}

// handleMissingOrder handles an order on exchange but not tracked locally
func (r *Reconciler) handleMissingOrder(exchangeOrder *binance.Order) error {
	log.Printf("[Reconciler] Handling missing order %s (exchange status: %s)",
		exchangeOrder.ClientOrderID, exchangeOrder.Status)

	// Import order into local tracking
	// Convert exchange order to local order
	side := SideBuy
	if exchangeOrder.Side == "SELL" {
		side = SideSell
	}

	orderType := TypeLimit
	if exchangeOrder.Type == "MARKET" {
		orderType = TypeMarket
	}

	price, _ := strconv.ParseFloat(exchangeOrder.Price, 64)
	size, _ := strconv.ParseFloat(exchangeOrder.OrigQuantity, 64)
	filled, _ := strconv.ParseFloat(exchangeOrder.ExecutedQuantity, 64)
	cummQuoteQty, _ := strconv.ParseFloat(exchangeOrder.CummulativeQuoteQuantity, 64)
	// Calculate average price from cummulative quote quantity
	avgPrice := 0.0
	if filled > 0 {
		avgPrice = cummQuoteQty / filled
	}

	order := &Order{
		ID:             exchangeOrder.ClientOrderID,
		Symbol:         exchangeOrder.Symbol,
		Side:           side,
		Type:           orderType,
		Price:          price,
		Size:           size,
		Filled:         filled,
		AvgPrice:       avgPrice,
		Status:         r.mapBinanceStatusToOrderStatus(string(exchangeOrder.Status)),
		CreatedAt:      time.Unix(exchangeOrder.Time/1000, 0),
		UpdatedAt:      time.Now(),
		BinanceOrderID: exchangeOrder.OrderID,
	}

	r.executor.ordersMu.Lock()
	r.executor.orders[order.ID] = order
	r.executor.ordersMu.Unlock()

	log.Printf("[Reconciler] Imported missing order %s into local tracking", order.ID)

	return nil
}

// mapBinanceStatusToOrderStatus maps Binance status to OrderStatus
func (r *Reconciler) mapBinanceStatusToOrderStatus(status string) OrderStatus {
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
	case "EXPIRED", "EXPIRED_IN_MATCH":
		return StatusCancelled
	default:
		return StatusPending
	}
}

// logReconciliationResult logs reconciliation results to WAL
func (r *Reconciler) logReconciliationResult(result *ReconciliationResult) {
	// Log as position entry (using RECONCILIATION as symbol)
	if r.wal != nil {
		r.wal.LogPosition(PositionEntry{
			Symbol:      "RECONCILIATION",
			Size:        float64(len(result.Mismatches)),
			AvgPrice:    float64(len(result.Missing)),
			RealizedPnL: float64(result.Fixed),
		})
	}
}

// GetStats returns reconciler statistics
func (r *Reconciler) GetStats() ReconcilerStats {
	r.statsMu.RLock()
	defer r.statsMu.RUnlock()
	return r.stats
}

// ForceReconcile triggers an immediate reconciliation
func (r *Reconciler) ForceReconcile(ctx context.Context) (*ReconciliationResult, error) {
	return r.Reconcile(ctx)
}

// SetAutoRepair enables/disables automatic repair
func (r *Reconciler) SetAutoRepair(enabled bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.autoRepair = enabled
	log.Printf("[Reconciler] Auto repair %v", enabled)
}

// typeToString converts OrderType to string
func typeToString(orderType OrderType) string {
	switch orderType {
	case TypeMarket:
		return "MARKET"
	case TypeLimit:
		return "LIMIT"
	case TypeStopMarket:
		return "STOP_MARKET"
	default:
		return "LIMIT"
	}
}

