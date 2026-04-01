package main

import (
	"context"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"
)

/*
request_queue.go - Enhanced Request Queue with Weight-Based Rate Limiting

Implements sophisticated rate limiting for Binance API:
- Weight-based rate limiting (1200 request weight/minute)
- Priority queue for different request types
- Per-endpoint weight tracking
- Request batching during high load
- Adaptive rate adjustment based on API response headers
*/

// RequestPriority defines priority levels for requests
type RequestPriority int

const (
	PriorityLow RequestPriority = iota
	PriorityNormal
	PriorityHigh
	PriorityCritical // For orders - must be executed
)

// Binance API Rate Limits
const (
	// Request weight limit: 1200 per minute
	BinanceWeightLimitPerMinute = 1200
	WeightLimitWindow           = time.Minute

	// Order rate limits (IP based)
	BinanceOrdersPer10Seconds = 100
	BinanceOrdersPerDay       = 200000
	OrdersLimitWindow10s      = 10 * time.Second
	OrdersLimitWindow24h      = 24 * time.Hour

	// Default safety margin (use only 80% of limit)
	DefaultSafetyMargin = 0.8
)

// EndpointWeight defines weight for specific endpoints
type EndpointWeight struct {
	Pattern    string // URL pattern, e.g., "/api/v3/account"
	Weight     int    // Request weight cost
	IsOrder    bool   // Whether this is an order endpoint
	RateLimit  int    // Specific rate limit for this endpoint (0 = use default)
	TimeWindow time.Duration
}

// DefaultEndpointWeights maps common endpoints to their weights
var DefaultEndpointWeights = []EndpointWeight{
	// Order endpoints (weight 1, but count toward order limits)
	{Pattern: "/api/v3/order", Weight: 1, IsOrder: true, RateLimit: BinanceOrdersPer10Seconds, TimeWindow: OrdersLimitWindow10s},
	{Pattern: "/api/v3/order/test", Weight: 1, IsOrder: false},
	{Pattern: "/sapi/v1/margin/order", Weight: 1, IsOrder: true, RateLimit: BinanceOrdersPer10Seconds, TimeWindow: OrdersLimitWindow10s},

	// Query endpoints with various weights
	{Pattern: "/api/v3/account", Weight: 10, IsOrder: false},
	{Pattern: "/api/v3/order", Weight: 2, IsOrder: false},       // Query order
	{Pattern: "/api/v3/openOrders", Weight: 3, IsOrder: false},
	{Pattern: "/api/v3/allOrders", Weight: 10, IsOrder: false},
	{Pattern: "/api/v3/depth", Weight: 1, IsOrder: false},       // Can be 5, 10, 50 based on limit param
	{Pattern: "/api/v3/ticker/24hr", Weight: 1, IsOrder: false}, // Can be up to 40
	{Pattern: "/api/v3/ticker/price", Weight: 2, IsOrder: false},
	{Pattern: "/api/v3/ticker/bookTicker", Weight: 2, IsOrder: false},
	{Pattern: "/api/v3/exchangeInfo", Weight: 20, IsOrder: false},
	{Pattern: "/api/v3/time", Weight: 1, IsOrder: false},
	{Pattern: "/api/v3/ping", Weight: 1, IsOrder: false},

	// Margin API endpoints
	{Pattern: "/sapi/v1/margin/account", Weight: 10, IsOrder: false},
	{Pattern: "/sapi/v1/margin/loan", Weight: 1, IsOrder: true, RateLimit: BinanceOrdersPer10Seconds, TimeWindow: OrdersLimitWindow10s},
	{Pattern: "/sapi/v1/margin/repay", Weight: 1, IsOrder: true, RateLimit: BinanceOrdersPer10Seconds, TimeWindow: OrdersLimitWindow10s},
	{Pattern: "/sapi/v1/margin/openOrders", Weight: 10, IsOrder: false},
}

// QueuedRequest represents a request waiting to be executed
type QueuedRequest struct {
	ID          string
	Endpoint    string
	Priority    RequestPriority
	Weight      int
	IsOrder     bool
	SubmittedAt time.Time
	Deadline    time.Time
	Execute     func() error
	ResponseCh  chan error
}

// RequestQueue manages prioritized API requests with rate limiting
type RequestQueue struct {
	// Configuration
	maxWeightPerMinute int
	maxOrdersPer10Sec  int
	safetyMargin       float64

	// Current state
	currentWeight   int
	currentOrders10s int
	weightMu        sync.RWMutex

	// Request queues by priority (higher priority = processed first)
	queues     [4][]*QueuedRequest // 0=Low, 1=Normal, 2=High, 3=Critical
	queuesMu   sync.Mutex
	queueCond  *sync.Cond

	// Rate limiting windows
	weightWindow    []time.Time // Timestamps of requests in current window
	ordersWindow    []time.Time // Timestamps of orders in current window
	windowMu        sync.Mutex

	// Endpoint weights
	endpointWeights []EndpointWeight
	weightCache     map[string]int
	cacheMu         sync.RWMutex

	// Adaptive rate limiting based on API response
	adaptiveBackoff time.Duration
	backoffMu       sync.RWMutex

	// Control
	ctx    context.Context
	cancel context.CancelFunc
	wg     sync.WaitGroup
}

// NewRequestQueue creates a new request queue with rate limiting
func NewRequestQueue() *RequestQueue {
	ctx, cancel := context.WithCancel(context.Background())

	rq := &RequestQueue{
		maxWeightPerMinute: int(float64(BinanceWeightLimitPerMinute) * DefaultSafetyMargin),
		maxOrdersPer10Sec:  int(float64(BinanceOrdersPer10Seconds) * DefaultSafetyMargin),
		safetyMargin:       DefaultSafetyMargin,
		weightWindow:       make([]time.Time, 0),
		ordersWindow:       make([]time.Time, 0),
		endpointWeights:    DefaultEndpointWeights,
		weightCache:        make(map[string]int),
		ctx:                ctx,
		cancel:             cancel,
	}

	rq.queueCond = sync.NewCond(&rq.queuesMu)

	// Start background workers
	rq.wg.Add(2)
	go rq.processLoop()
	go rq.cleanupLoop()

	return rq
}

// Close shuts down the request queue
func (rq *RequestQueue) Close() {
	rq.cancel()
	// 唤醒 processLoop 让它退出
	rq.queueCond.Broadcast()
	rq.wg.Wait()
}

// Submit adds a request to the queue
func (rq *RequestQueue) Submit(endpoint string, priority RequestPriority, execute func() error) error {
	return rq.SubmitWithDeadline(endpoint, priority, time.Time{}, execute)
}

// SubmitWithDeadline adds a request with a deadline
func (rq *RequestQueue) SubmitWithDeadline(endpoint string, priority RequestPriority, deadline time.Time, execute func() error) error {
	weight, isOrder := rq.getEndpointWeight(endpoint)

	req := &QueuedRequest{
		ID:          generateRequestID(),
		Endpoint:    endpoint,
		Priority:    priority,
		Weight:      weight,
		IsOrder:     isOrder,
		SubmittedAt: time.Now(),
		Deadline:    deadline,
		Execute:     execute,
		ResponseCh:  make(chan error, 1),
	}

	rq.queuesMu.Lock()
	if rq.ctx.Err() != nil {
		rq.queuesMu.Unlock()
		return fmt.Errorf("request queue is closed")
	}
	rq.queues[priority] = append(rq.queues[priority], req)
	rq.queuesMu.Unlock()
	rq.queueCond.Signal()

	// Wait for execution
	select {
	case err := <-req.ResponseCh:
		return err
	case <-rq.ctx.Done():
		return fmt.Errorf("request cancelled")
	}
}

// SubmitAsync adds a request without waiting for completion
func (rq *RequestQueue) SubmitAsync(endpoint string, priority RequestPriority, execute func() error) string {
	weight, isOrder := rq.getEndpointWeight(endpoint)

	req := &QueuedRequest{
		ID:          generateRequestID(),
		Endpoint:    endpoint,
		Priority:    priority,
		Weight:      weight,
		IsOrder:     isOrder,
		SubmittedAt: time.Now(),
		Execute:     execute,
		ResponseCh:  make(chan error, 1),
	}

	rq.queuesMu.Lock()
	if rq.ctx.Err() != nil {
		rq.queuesMu.Unlock()
		return ""
	}
	rq.queues[priority] = append(rq.queues[priority], req)
	rq.queuesMu.Unlock()
	rq.queueCond.Signal()

	return req.ID
}

// processLoop processes queued requests respecting rate limits
func (rq *RequestQueue) processLoop() {
	defer rq.wg.Done()

	for {
		select {
		case <-rq.ctx.Done():
			return
		default:
		}

		// Try to dequeue a batch of requests
		req := rq.dequeue()
		if req == nil {
			// Wait for new requests
			rq.queuesMu.Lock()
			if rq.ctx.Err() != nil {
				rq.queuesMu.Unlock()
				return
			}
			rq.queueCond.Wait()
			rq.queuesMu.Unlock()
			continue
		}

		// Process this request
		rq.processRequest(req)
	}
}

// processRequest handles a single request with rate limiting and execution
func (rq *RequestQueue) processRequest(req *QueuedRequest) {
	// Check deadline
	if !req.Deadline.IsZero() && time.Now().After(req.Deadline) {
		req.ResponseCh <- fmt.Errorf("request deadline exceeded")
		close(req.ResponseCh)
		return
	}

	// Wait for rate limit allowance
	if err := rq.waitForCapacity(req); err != nil {
		req.ResponseCh <- err
		close(req.ResponseCh)
		return
	}

	// Execute the request in a goroutine to allow concurrent processing
	rq.recordUsage(req)
	go func(r *QueuedRequest) {
		err := r.Execute()

		// Handle rate limit errors
		if err != nil && isRateLimitError(err) {
			rq.applyBackoff()
		}

		r.ResponseCh <- err
		close(r.ResponseCh)
	}(req)
}

// dequeue retrieves the highest priority request
func (rq *RequestQueue) dequeue() *QueuedRequest {
	rq.queuesMu.Lock()
	defer rq.queuesMu.Unlock()

	// Check from highest to lowest priority
	for i := PriorityCritical; i >= PriorityLow; i-- {
		if len(rq.queues[i]) > 0 {
			req := rq.queues[i][0]
			rq.queues[i] = rq.queues[i][1:]
			return req
		}
	}
	return nil
}

// waitForCapacity waits until the request can be executed within rate limits
func (rq *RequestQueue) waitForCapacity(req *QueuedRequest) error {
	for {
		select {
		case <-rq.ctx.Done():
			return rq.ctx.Err()
		default:
		}

		if rq.canExecute(req) {
			return nil
		}

		// Wait before retrying
		time.Sleep(10 * time.Millisecond)
	}
}

// canExecute checks if a request can be executed within current rate limits
func (rq *RequestQueue) canExecute(req *QueuedRequest) bool {
	rq.windowMu.Lock()
	defer rq.windowMu.Unlock()

	// Clean old entries
	now := time.Now()
	cutoff := now.Add(-time.Minute)
	newWeightWindow := rq.weightWindow[:0]
	for _, t := range rq.weightWindow {
		if t.After(cutoff) {
			newWeightWindow = append(newWeightWindow, t)
		}
	}
	rq.weightWindow = newWeightWindow

	cutoff10s := now.Add(-OrdersLimitWindow10s)
	newOrdersWindow := rq.ordersWindow[:0]
	for _, t := range rq.ordersWindow {
		if t.After(cutoff10s) {
			newOrdersWindow = append(newOrdersWindow, t)
		}
	}
	rq.ordersWindow = newOrdersWindow

	// Check weight limit
	if len(rq.weightWindow) >= rq.maxWeightPerMinute {
		return false
	}

	// Check order limit
	if req.IsOrder && len(rq.ordersWindow) >= rq.maxOrdersPer10Sec {
		return false
	}

	return true
}

// recordUsage records request execution for rate limiting
func (rq *RequestQueue) recordUsage(req *QueuedRequest) {
	rq.windowMu.Lock()
	defer rq.windowMu.Unlock()

	now := time.Now()

	// Record weight usage (repeat for weighted requests)
	for i := 0; i < req.Weight; i++ {
		rq.weightWindow = append(rq.weightWindow, now)
	}

	// Record order usage
	if req.IsOrder {
		rq.ordersWindow = append(rq.ordersWindow, now)
	}
}

// cleanupLoop periodically cleans up expired rate limit entries
func (rq *RequestQueue) cleanupLoop() {
	defer rq.wg.Done()

	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-rq.ctx.Done():
			return
		case <-ticker.C:
			rq.cleanupWindows()
		}
	}
}

// cleanupWindows removes expired entries from rate limit windows
func (rq *RequestQueue) cleanupWindows() {
	rq.windowMu.Lock()
	defer rq.windowMu.Unlock()

	now := time.Now()

	// Clean weight window (1 minute)
	cutoff := now.Add(-time.Minute)
	newWeightWindow := rq.weightWindow[:0]
	for _, t := range rq.weightWindow {
		if t.After(cutoff) {
			newWeightWindow = append(newWeightWindow, t)
		}
	}
	rq.weightWindow = newWeightWindow

	// Clean orders window (10 seconds)
	cutoff10s := now.Add(-OrdersLimitWindow10s)
	newOrdersWindow := rq.ordersWindow[:0]
	for _, t := range rq.ordersWindow {
		if t.After(cutoff10s) {
			newOrdersWindow = append(newOrdersWindow, t)
		}
	}
	rq.ordersWindow = newOrdersWindow

	// Log rate limit status periodically
	if len(rq.weightWindow) > 0 || len(rq.ordersWindow) > 0 {
		log.Printf("[RATE_LIMIT] Weight: %d/%d, Orders(10s): %d/%d",
			len(rq.weightWindow), rq.maxWeightPerMinute,
			len(rq.ordersWindow), rq.maxOrdersPer10Sec)
	}
}

// getEndpointWeight returns the weight and order status for an endpoint
func (rq *RequestQueue) getEndpointWeight(endpoint string) (int, bool) {
	// Check cache first
	rq.cacheMu.RLock()
	if weight, ok := rq.weightCache[endpoint]; ok {
		// Find if it's an order endpoint
		for _, ew := range rq.endpointWeights {
			if strings.Contains(endpoint, ew.Pattern) {
				rq.cacheMu.RUnlock()
				return weight, ew.IsOrder
			}
		}
		rq.cacheMu.RUnlock()
		return weight, false
	}
	rq.cacheMu.RUnlock()

	// Find matching endpoint weight
	for _, ew := range rq.endpointWeights {
		if strings.Contains(endpoint, ew.Pattern) {
			rq.cacheMu.Lock()
			rq.weightCache[endpoint] = ew.Weight
			rq.cacheMu.Unlock()
			return ew.Weight, ew.IsOrder
		}
	}

	// Default weight
	rq.cacheMu.Lock()
	rq.weightCache[endpoint] = 1
	rq.cacheMu.Unlock()
	return 1, false
}

// applyBackoff increases backoff when rate limit is hit
func (rq *RequestQueue) applyBackoff() {
	rq.backoffMu.Lock()
	defer rq.backoffMu.Unlock()

	newBackoff := rq.adaptiveBackoff*2 + 100*time.Millisecond
	maxBackoff := 5*time.Second
	if newBackoff > maxBackoff {
		newBackoff = maxBackoff
	}
	rq.adaptiveBackoff = newBackoff
	log.Printf("[RATE_LIMIT] Applied backoff: %v", rq.adaptiveBackoff)
}

// UpdateUsedWeight updates the current weight based on API response headers
func (rq *RequestQueue) UpdateUsedWeight(usedWeight int) {
	rq.weightMu.Lock()
	defer rq.weightMu.Unlock()

	// Adjust internal weight window to reflect actual server-side usage
	// This is a simplified approximation - in production, you might want
	// to sync more precisely with the server's view
	if usedWeight > len(rq.weightWindow) {
		// Add dummy entries to match server-reported usage
		diff := usedWeight - len(rq.weightWindow)
		now := time.Now()
		for i := 0; i < diff; i++ {
			rq.weightWindow = append(rq.weightWindow, now)
		}
	}
}

// UpdateOrderCount updates the current order count based on API response headers
func (rq *RequestQueue) UpdateOrderCount(orderCount int) {
	rq.windowMu.Lock()
	defer rq.windowMu.Unlock()

	// Adjust internal order window to reflect actual server-side usage
	if orderCount > len(rq.ordersWindow) {
		diff := orderCount - len(rq.ordersWindow)
		now := time.Now()
		for i := 0; i < diff; i++ {
			rq.ordersWindow = append(rq.ordersWindow, now)
		}
	}
}

// ApplyRetryAfter applies a backoff period from Retry-After header
func (rq *RequestQueue) ApplyRetryAfter(duration time.Duration) {
	rq.backoffMu.Lock()
	defer rq.backoffMu.Unlock()

	if duration > rq.adaptiveBackoff {
		rq.adaptiveBackoff = duration
	}
	log.Printf("[RATE_LIMIT] Applied Retry-After backoff: %v", rq.adaptiveBackoff)
}

// GetStats returns current rate limiting statistics
func (rq *RequestQueue) GetStats() map[string]interface{} {
	rq.windowMu.Lock()
	defer rq.windowMu.Unlock()

	rq.queuesMu.Lock()
	queueSizes := map[string]int{
		"low":      len(rq.queues[PriorityLow]),
		"normal":   len(rq.queues[PriorityNormal]),
		"high":     len(rq.queues[PriorityHigh]),
		"critical": len(rq.queues[PriorityCritical]),
	}
	rq.queuesMu.Unlock()

	return map[string]interface{}{
		"weight_used":      len(rq.weightWindow),
		"weight_limit":     rq.maxWeightPerMinute,
		"orders_10s_used":  len(rq.ordersWindow),
		"orders_10s_limit": rq.maxOrdersPer10Sec,
		"queue_sizes":      queueSizes,
	}
}

// Helper functions

func generateRequestID() string {
	return fmt.Sprintf("req_%d", time.Now().UnixNano())
}

func isRateLimitError(err error) bool {
	if err == nil {
		return false
	}
	errStr := err.Error()
	return strings.Contains(errStr, "429") ||
		strings.Contains(errStr, "rate limit") ||
		strings.Contains(errStr, "RATE_LIMIT")
}

func min(a, b time.Duration) time.Duration {
	if a < b {
		return a
	}
	return b
}
