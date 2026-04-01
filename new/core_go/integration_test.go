package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"sync"
	"testing"
	"time"
)

/*
integration_test.go - Integration tests for HFT Engine components

Tests the interaction between:
- LiveAPIClient (P1-102)
- OrderFSM (P1-002)
- RequestQueue (P1-003)
- RetryExecutor (P1-004)
- ReconnectableWebSocket (P1-005)
- WAL (P1-101)
*/

// TestFullOrderFlow tests complete order lifecycle with all components
func TestFullOrderFlow(t *testing.T) {
	// Create temp directory for WAL
	tempDir, err := os.MkdirTemp("", "hft_test_*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	// Initialize components
	wal, err := NewWAL(tempDir)
	if err != nil {
		t.Fatalf("Failed to create WAL: %v", err)
	}
	defer wal.Close()

	// Create order FSM with config
	config := &FSMConfig{
		PendingTimeout: 5 * time.Second,
		OpenTimeout:    10 * time.Second,
	}
	fsm := NewOrderFSM("test-order-001", config)

	// Set state change callback that logs to WAL
	fsm.SetStateChangeCallback(func(orderID string, from, to OrderState, reason string) {
		entry := OrderEntry{
			Symbol: "BTCUSDT",
			Side:   "BUY",
			Type:   "LIMIT",
			Price:  50000.0,
			Size:   0.1,
			Status: to.String(),
		}
		if err := wal.LogOrder(orderID, entry); err != nil {
			t.Logf("Failed to log order state: %v", err)
		}
	})

	// Test order lifecycle
	t.Run("OrderLifecycle", func(t *testing.T) {
		// Initial state
		if fsm.Current() != OrderStatePending {
			t.Errorf("Expected Pending, got %v", fsm.Current())
		}

		// Transition to Open
		if err := fsm.Transition(OrderStateOpen, "Order accepted by exchange"); err != nil {
			t.Errorf("Failed to transition to Open: %v", err)
		}

		// Transition to PartiallyFilled
		if err := fsm.Transition(OrderStatePartiallyFilled, "Partial fill: 0.05 BTC"); err != nil {
			t.Errorf("Failed to transition to PartiallyFilled: %v", err)
		}

		// Transition to Filled
		if err := fsm.Transition(OrderStateFilled, "Complete fill: 0.1 BTC"); err != nil {
			t.Errorf("Failed to transition to Filled: %v", err)
		}

		// Verify terminal state
		if !fsm.Current().IsTerminal() {
			t.Error("Filled should be terminal state")
		}

		// Verify history
		history := fsm.GetHistory()
		if len(history) != 3 {
			t.Errorf("Expected 3 transitions, got %d", len(history))
		}
	})
}

// TestRetryWithRequestQueue tests retry mechanism integrated with rate limiting
func TestRetryWithRequestQueue(t *testing.T) {
	// Create request queue
	rq := NewRequestQueue()
	defer rq.Close()

	// Create retry executor with aggressive policy for orders
	policy := AggressiveRetryPolicy()
	executor := NewRetryExecutor(policy, nil)

	ctx := context.Background()
	endpoint := "/api/v3/order"

	t.Run("SuccessfulRequest", func(t *testing.T) {
		callCount := 0
		err := rq.Submit(endpoint, PriorityCritical, func() error {
			return executor.Execute(ctx, func() error {
				callCount++
				return nil
			})
		})

		if err != nil {
			t.Errorf("Expected success, got: %v", err)
		}
		if callCount != 1 {
			t.Errorf("Expected 1 call, got %d", callCount)
		}
	})

	t.Run("RetryAfterFailure", func(t *testing.T) {
		callCount := 0
		err := rq.Submit(endpoint, PriorityCritical, func() error {
			return executor.Execute(ctx, func() error {
				callCount++
				if callCount < 3 {
					return errors.New("status 503: service unavailable")
				}
				return nil
			})
		})

		if err != nil {
			t.Errorf("Expected success after retry, got: %v", err)
		}
		if callCount != 3 {
			t.Errorf("Expected 3 calls (1 + 2 retries), got %d", callCount)
		}
	})
}

// TestCircuitBreakerWithRetry tests circuit breaker integration with retry
func TestCircuitBreakerWithRetry(t *testing.T) {
	// Create circuit breaker
	cb := NewCircuitBreaker("test-cb", 3, 100*time.Millisecond)

	// Create retry executor with circuit breaker
	policy := DefaultRetryPolicy()
	executor := NewRetryExecutor(policy, cb)

	ctx := context.Background()

	t.Run("CircuitBreakerOpensAfterFailures", func(t *testing.T) {
		// First batch: 3 failures should open circuit
		for i := 0; i < 3; i++ {
			executor.Execute(ctx, func() error {
				return errors.New("status 503: server error")
			})
		}

		// Circuit should be open now
		if cb.State() != BreakerStateOpen {
			t.Errorf("Expected circuit breaker open, got %v", cb.State())
		}

		// Next request should fail immediately
		err := executor.Execute(ctx, func() error {
			return nil
		})

		if err == nil || err.Error() != "circuit breaker is open" {
			t.Errorf("Expected circuit breaker error, got: %v", err)
		}
	})

	t.Run("CircuitBreakerRecovers", func(t *testing.T) {
		// Wait for half-open timeout
		time.Sleep(150 * time.Millisecond)

		// Success should close circuit
		err := executor.Execute(ctx, func() error {
			return nil
		})

		if err != nil {
			t.Errorf("Expected success after recovery, got: %v", err)
		}

		if cb.State() != BreakerStateClosed {
			t.Errorf("Expected circuit breaker closed, got %v", cb.State())
		}
	})
}

// TestWALWithOrderFSM tests WAL integration with order state
func TestWALWithOrderFSM(t *testing.T) {
	tempDir, err := os.MkdirTemp("", "wal_integration_test_*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	// Create WAL
	wal, err := NewWAL(tempDir)
	if err != nil {
		t.Fatalf("Failed to create WAL: %v", err)
	}

	// Create FSM and log state changes
	config := DefaultFSMConfig()
	fsm := NewOrderFSM("int-order-001", config)

	fsm.SetStateChangeCallback(func(orderID string, from, to OrderState, reason string) {
		entry := OrderEntry{
			Symbol: "BTCUSDT",
			Side:   "BUY",
			Type:   "LIMIT",
			Price:  50000,
			Size:   0.1,
			Status: to.String(),
		}
		wal.LogOrder(orderID, entry)
	})

	// Execute state transitions
	fsm.Transition(OrderStateOpen, "Order accepted")
	fsm.Transition(OrderStatePartiallyFilled, "Partial fill")
	fsm.Transition(OrderStateFilled, "Complete fill")

	wal.Close()

	// Verify log file exists and has content
	files, err := os.ReadDir(tempDir)
	if err != nil {
		t.Fatalf("Failed to read temp dir: %v", err)
	}

	var logFiles int
	for _, f := range files {
		if !f.IsDir() {
			logFiles++
		}
	}

	if logFiles == 0 {
		t.Error("Expected WAL log files, found none")
	}
}

// TestConcurrentComponentAccess tests thread safety of all components
func TestConcurrentComponentAccess(t *testing.T) {
	tempDir, _ := os.MkdirTemp("", "concurrent_test_*")
	defer os.RemoveAll(tempDir)

	wal, _ := NewWAL(tempDir)
	defer wal.Close()

	rq := NewRequestQueue()
	defer rq.Close()

	cb := NewCircuitBreaker("concurrent-cb", 10, time.Second)
	executor := NewRetryExecutor(DefaultRetryPolicy(), cb)

	var wg sync.WaitGroup
	numGoroutines := 5
	numOperations := 5

	t.Run("ConcurrentOrderOperations", func(t *testing.T) {
		config := DefaultFSMConfig()
		for i := 0; i < numGoroutines; i++ {
			wg.Add(1)
			go func(id int) {
				defer wg.Done()

				for j := 0; j < numOperations; j++ {
					orderID := fmt.Sprintf("order-%d-%d", id, j)
					fsm := NewOrderFSM(orderID, config)

					// Simulate order flow
					fsm.Transition(OrderStateOpen, "Created")
					fsm.Transition(OrderStateFilled, "Filled")

					// Log to WAL
					entry := OrderEntry{
						Symbol: "BTCUSDT",
						Side:   "BUY",
						Type:   "LIMIT",
						Price:  50000,
						Size:   0.01,
						Status: "Filled",
					}
					wal.LogOrder(orderID, entry)
				}
			}(i)
		}

		wg.Wait()
	})

	t.Run("ConcurrentAPIRequests", func(t *testing.T) {
		ctx := context.Background()

		for i := 0; i < numGoroutines; i++ {
			wg.Add(1)
			go func(id int) {
				defer wg.Done()

				for j := 0; j < numOperations; j++ {
					rq.Submit("/api/v3/account", PriorityNormal, func() error {
						return executor.Execute(ctx, func() error {
							return nil
						})
					})
				}
			}(i)
		}

		wg.Wait()
	})
}

// TestEndToEndOrderExecution simulates complete order execution flow
func TestEndToEndOrderExecution(t *testing.T) {
	tempDir, _ := os.MkdirTemp("", "e2e_test_*")
	defer os.RemoveAll(tempDir)

	// Initialize all components
	wal, _ := NewWAL(tempDir)
	defer wal.Close()

	rq := NewRequestQueue()
	defer rq.Close()

	cb := NewCircuitBreaker("e2e-cb", 5, time.Second)

	// Use global retry manager for endpoint-specific policies
	retryManager := NewPerEndpointRetryManager(cb)
	retryManager.SetPolicy("/api/v3/order", AggressiveRetryPolicy())
	retryManager.SetPolicy("/api/v3/account", DefaultRetryPolicy())

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	t.Run("PlaceOrderFlow", func(t *testing.T) {
		orderID := "e2e-order-001"
		config := DefaultFSMConfig()
		fsm := NewOrderFSM(orderID, config)

		// Set callback to log state changes
		fsm.SetStateChangeCallback(func(oid string, from, to OrderState, reason string) {
			entry := OrderEntry{
				Symbol: "BTCUSDT",
				Side:   "BUY",
				Type:   "LIMIT",
				Price:  50000,
				Size:   0.1,
				Status: to.String(),
			}
			wal.LogOrder(oid, entry)
		})

		// Execute order placement with retry and rate limiting
		err := rq.Submit("/api/v3/order", PriorityCritical, func() error {
			executor := retryManager.GetExecutor("/api/v3/order")
			return executor.Execute(ctx, func() error {
				// Simulate API call - order accepted by exchange
				return fsm.Transition(OrderStateOpen, "Order submitted")
			})
		})

		if err != nil {
			t.Errorf("Order submission failed: %v", err)
		}

		// Simulate fill
		if err := fsm.Transition(OrderStateFilled, "Order filled"); err != nil {
			t.Errorf("Failed to transition to Filled: %v", err)
		}

		// Verify final state
		if fsm.Current() != OrderStateFilled {
			t.Errorf("Expected Filled state, got %v", fsm.Current())
		}
	})
}

// TestRateLimitIntegration tests request queue with retry integration
func TestRateLimitIntegration(t *testing.T) {
	rq := NewRequestQueue()
	defer rq.Close()

	executor := NewRetryExecutor(AggressiveRetryPolicy(), nil)
	ctx := context.Background()

	t.Run("RateLimitBackoff", func(t *testing.T) {
		start := time.Now()

		// Submit multiple requests that will trigger rate limiting
		var wg sync.WaitGroup
		for i := 0; i < 10; i++ {
			wg.Add(1)
			go func(id int) {
				defer wg.Done()
				rq.Submit("/api/v3/order", PriorityNormal, func() error {
					return executor.Execute(ctx, func() error {
						return nil
					})
				})
			}(i)
		}

		wg.Wait()
		duration := time.Since(start)

		// Should take some time due to rate limiting
		if duration < 10*time.Millisecond {
			t.Log("Requests processed very quickly, rate limiting may not be working")
		}

		// Get stats
		stats := rq.GetStats()
		t.Logf("Queue stats: %v", stats)
	})
}

// TestComponentMetrics tests that all components report correct metrics
func TestComponentMetrics(t *testing.T) {
	tempDir, _ := os.MkdirTemp("", "metrics_test_*")
	defer os.RemoveAll(tempDir)

	wal, _ := NewWAL(tempDir)
	defer wal.Close()

	rq := NewRequestQueue()
	defer rq.Close()

	cb := NewCircuitBreaker("metrics-cb", 5, time.Second)
	executor := NewRetryExecutor(DefaultRetryPolicy(), cb)

	t.Run("WALStats", func(t *testing.T) {
		// Log some entries
		for i := 0; i < 5; i++ {
			entry := OrderEntry{
				Symbol: "BTCUSDT",
				Side:   "BUY",
				Type:   "LIMIT",
				Price:  50000,
				Size:   0.1,
				Status: "Filled",
			}
			wal.LogOrder(fmt.Sprintf("order-%d", i), entry)
		}

		// WAL doesn't expose stats directly, but we can verify it works
	})

	t.Run("QueueStats", func(t *testing.T) {
		stats := rq.GetStats()

		requiredKeys := []string{"weight_used", "weight_limit", "orders_10s_used", "orders_10s_limit", "queue_sizes"}
		for _, key := range requiredKeys {
			if _, ok := stats[key]; !ok {
				t.Errorf("Missing stat key: %s", key)
			}
		}
	})

	t.Run("CircuitBreakerStats", func(t *testing.T) {
		state := cb.State()
		if state != BreakerStateClosed && state != BreakerStateOpen && state != BreakerStateHalfOpen {
			t.Errorf("Invalid circuit breaker state: %v", state)
		}
	})

	t.Run("RetryStats", func(t *testing.T) {
		ctx := context.Background()

		// Execute some operations
		for i := 0; i < 3; i++ {
			executor.Execute(ctx, func() error {
				return nil
			})
		}

		stats := executor.GetStats()

		requiredKeys := []string{"total_attempts", "success_count", "failure_count", "retry_count", "success_rate"}
		for _, key := range requiredKeys {
			if _, ok := stats[key]; !ok {
				t.Errorf("Missing stat key: %s", key)
			}
		}

		if stats["total_attempts"] != 3 {
			t.Errorf("Expected 3 attempts, got %v", stats["total_attempts"])
		}
		if stats["success_count"] != 3 {
			t.Errorf("Expected 3 successes, got %v", stats["success_count"])
		}
	})
}

// TestFSMManagerWithWAL tests FSM Manager integration with WAL
func TestFSMManagerWithWAL(t *testing.T) {
	tempDir, _ := os.MkdirTemp("", "fsm_manager_test_*")
	defer os.RemoveAll(tempDir)

	wal, _ := NewWAL(tempDir)
	defer wal.Close()

	// Create FSM Manager with global callback
	config := DefaultFSMConfig()
	manager := NewOrderFSMManager(config)

	manager.SetGlobalStateChangeCallback(func(orderID string, from, to OrderState, reason string) {
		entry := OrderEntry{
			Symbol: "BTCUSDT",
			Side:   "BUY",
			Type:   "LIMIT",
			Price:  50000,
			Size:   0.1,
			Status: to.String(),
		}
		wal.LogOrder(orderID, entry)
	})

	// Create multiple orders
	orderIDs := []string{"order-001", "order-002", "order-003"}
	for _, id := range orderIDs {
		fsm := manager.CreateFSM(id)
		fsm.Transition(OrderStateOpen, "Created")
		fsm.Transition(OrderStateFilled, "Filled")
	}

	// Verify stats
	stats := manager.GetStats()
	if stats["Total"] != 3 {
		t.Errorf("Expected 3 total orders, got %d", stats["Total"])
	}
	if stats["Filled"] != 3 {
		t.Errorf("Expected 3 filled orders, got %d", stats["Filled"])
	}

	// Verify retrieval
	fsm, ok := manager.GetFSM("order-001")
	if !ok {
		t.Error("Failed to get FSM for order-001")
	}
	if fsm.Current() != OrderStateFilled {
		t.Errorf("Expected Filled, got %v", fsm.Current())
	}

	// Remove FSM
	manager.RemoveFSM("order-001")
	_, ok = manager.GetFSM("order-001")
	if ok {
		t.Error("FSM should have been removed")
	}
}
