package main

import (
	"context"
	"errors"
	"fmt"
	"sync/atomic"
	"testing"
	"time"
)

// TestErrorClassifier_Classify tests error classification
func TestErrorClassifier_Classify(t *testing.T) {
	ec := NewErrorClassifier()

	tests := []struct {
		name     string
		err      error
		expected RetryableErrorType
	}{
		{
			name:     "Rate limit error",
			err:      errors.New("API error (status 429): rate limit exceeded"),
			expected: RetryableErrorRateLimit,
		},
		{
			name:     "Server error 500",
			err:      errors.New("API error (status 500): internal server error"),
			expected: RetryableErrorServer,
		},
		{
			name:     "Server error 503",
			err:      errors.New("API error (status 503): service unavailable"),
			expected: RetryableErrorServer,
		},
		{
			name:     "Network timeout",
			err:      errors.New("HTTP request failed: timeout"),
			expected: RetryableErrorNetwork,
		},
		{
			name:     "Connection reset",
			err:      errors.New("connection reset by peer"),
			expected: RetryableErrorNetwork,
		},
		{
			name:     "Invalid API key",
			err:      errors.New("invalid api key"),
			expected: RetryableErrorNone,
		},
		{
			name:     "Insufficient balance",
			err:      errors.New("insufficient balance"),
			expected: RetryableErrorNone,
		},
		{
			name:     "Invalid symbol",
			err:      errors.New("invalid symbol"),
			expected: RetryableErrorNone,
		},
		{
			name:     "Context cancelled",
			err:      context.Canceled,
			expected: RetryableErrorNone,
		},
		{
			name:     "Nil error",
			err:      nil,
			expected: RetryableErrorNone,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			result := ec.Classify(tc.err)
			if result != tc.expected {
				t.Errorf("Classify(%v) = %v, expected %v", tc.err, result, tc.expected)
			}
		})
	}
}

// TestErrorClassifier_IsRetryable tests retryability check
func TestErrorClassifier_IsRetryable(t *testing.T) {
	ec := NewErrorClassifier()

	// Retryable errors
	retryable := []error{
		errors.New("status 429"),
		errors.New("status 503"),
		errors.New("timeout"),
		errors.New("connection reset"),
	}

	for _, err := range retryable {
		if !ec.IsRetryable(err) {
			t.Errorf("Expected %v to be retryable", err)
		}
	}

	// Non-retryable errors
	nonRetryable := []error{
		errors.New("invalid api key"),
		errors.New("insufficient balance"),
		errors.New("invalid signature"),
		context.Canceled,
	}

	for _, err := range nonRetryable {
		if ec.IsRetryable(err) {
			t.Errorf("Expected %v to be non-retryable", err)
		}
	}
}

// TestRetryPolicy_Default tests default retry policy
func TestRetryPolicy_Default(t *testing.T) {
	policy := DefaultRetryPolicy()

	if policy.MaxRetries != 3 {
		t.Errorf("Expected MaxRetries=3, got %d", policy.MaxRetries)
	}
	if policy.InitialDelay != 500*time.Millisecond {
		t.Errorf("Expected InitialDelay=500ms, got %v", policy.InitialDelay)
	}
	if policy.MaxDelay != 30*time.Second {
		t.Errorf("Expected MaxDelay=30s, got %v", policy.MaxDelay)
	}
}

// TestRetryPolicy_Aggressive tests aggressive retry policy
func TestRetryPolicy_Aggressive(t *testing.T) {
	policy := AggressiveRetryPolicy()

	if policy.MaxRetries != 5 {
		t.Errorf("Expected MaxRetries=5, got %d", policy.MaxRetries)
	}
	if policy.InitialDelay != 200*time.Millisecond {
		t.Errorf("Expected InitialDelay=200ms, got %v", policy.InitialDelay)
	}
}

// TestRetryExecutor_Execute_Success tests successful execution
func TestRetryExecutor_Execute_Success(t *testing.T) {
	policy := &RetryPolicy{
		MaxRetries:        3,
		InitialDelay:      10 * time.Millisecond,
		MaxDelay:          100 * time.Millisecond,
		BackoffMultiplier: 2.0,
	}

	executor := NewRetryExecutor(policy, nil)

	callCount := 0
	err := executor.Execute(context.Background(), func() error {
		callCount++
		return nil
	})

	if err != nil {
		t.Errorf("Expected no error, got %v", err)
	}
	if callCount != 1 {
		t.Errorf("Expected 1 call, got %d", callCount)
	}
}

// TestRetryExecutor_Execute_RetrySuccess tests successful retry
func TestRetryExecutor_Execute_RetrySuccess(t *testing.T) {
	policy := &RetryPolicy{
		MaxRetries:        3,
		InitialDelay:      10 * time.Millisecond,
		MaxDelay:          100 * time.Millisecond,
		BackoffMultiplier: 2.0,
	}

	executor := NewRetryExecutor(policy, nil)

	callCount := 0
	err := executor.Execute(context.Background(), func() error {
		callCount++
		if callCount < 3 {
			return errors.New("status 503: server error")
		}
		return nil
	})

	if err != nil {
		t.Errorf("Expected no error, got %v", err)
	}
	if callCount != 3 {
		t.Errorf("Expected 3 calls, got %d", callCount)
	}

	stats := executor.GetStats()
	if stats["retry_count"] != 2 {
		t.Errorf("Expected 2 retries, got %v", stats["retry_count"])
	}
}

// TestRetryExecutor_Execute_MaxRetries tests max retries exceeded
func TestRetryExecutor_Execute_MaxRetries(t *testing.T) {
	policy := &RetryPolicy{
		MaxRetries:        2,
		InitialDelay:      10 * time.Millisecond,
		MaxDelay:          100 * time.Millisecond,
		BackoffMultiplier: 2.0,
	}

	executor := NewRetryExecutor(policy, nil)

	callCount := 0
	err := executor.Execute(context.Background(), func() error {
		callCount++
		return errors.New("status 503: server error")
	})

	if err == nil {
		t.Error("Expected error after max retries")
	}
	if callCount != 3 { // Initial + 2 retries
		t.Errorf("Expected 3 calls, got %d", callCount)
	}
}

// TestRetryExecutor_Execute_NonRetryable tests non-retryable error
func TestRetryExecutor_Execute_NonRetryable(t *testing.T) {
	policy := &RetryPolicy{
		MaxRetries:        3,
		InitialDelay:      10 * time.Millisecond,
		MaxDelay:          100 * time.Millisecond,
		BackoffMultiplier: 2.0,
	}

	executor := NewRetryExecutor(policy, nil)

	callCount := 0
	err := executor.Execute(context.Background(), func() error {
		callCount++
		return errors.New("invalid api key")
	})

	if err == nil {
		t.Error("Expected error")
	}
	if callCount != 1 { // Should not retry
		t.Errorf("Expected 1 call, got %d", callCount)
	}
}

// TestRetryExecutor_Execute_ContextCancellation tests context cancellation
func TestRetryExecutor_Execute_ContextCancellation(t *testing.T) {
	policy := &RetryPolicy{
		MaxRetries:        3,
		InitialDelay:      1 * time.Second,
		MaxDelay:          5 * time.Second,
		BackoffMultiplier: 2.0,
	}

	executor := NewRetryExecutor(policy, nil)

	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()

	err := executor.Execute(ctx, func() error {
		return errors.New("status 503: server error")
	})

	if err != context.DeadlineExceeded {
		t.Errorf("Expected DeadlineExceeded, got %v", err)
	}
}

// TestRetryExecutor_CalculateDelay tests delay calculation
func TestRetryExecutor_CalculateDelay(t *testing.T) {
	policy := &RetryPolicy{
		MaxRetries:        5,
		InitialDelay:      100 * time.Millisecond,
		MaxDelay:          1 * time.Second,
		BackoffMultiplier: 2.0,
		JitterFactor:      0.0, // Disable jitter for predictable tests
	}

	executor := NewRetryExecutor(policy, nil)

	// Test exponential backoff (use Temporary error type to avoid multipliers)
	delay0 := executor.calculateDelay(0, RetryableErrorTemporary)
	if delay0 != 100*time.Millisecond {
		t.Errorf("Expected 100ms for attempt 0, got %v", delay0)
	}

	delay1 := executor.calculateDelay(1, RetryableErrorTemporary)
	if delay1 != 200*time.Millisecond {
		t.Errorf("Expected 200ms for attempt 1, got %v", delay1)
	}

	delay2 := executor.calculateDelay(2, RetryableErrorTemporary)
	if delay2 != 400*time.Millisecond {
		t.Errorf("Expected 400ms for attempt 2, got %v", delay2)
	}

	// Test server error multiplier (1.5x)
	delayServer := executor.calculateDelay(0, RetryableErrorServer)
	if delayServer != 150*time.Millisecond { // 100ms * 1.5
		t.Errorf("Expected 150ms for server error, got %v", delayServer)
	}

	// Test rate limit multiplier
	delayRate := executor.calculateDelay(0, RetryableErrorRateLimit)
	if delayRate != 200*time.Millisecond { // 100ms * 2
		t.Errorf("Expected 200ms for rate limit, got %v", delayRate)
	}

	// Test max delay cap
	delayHigh := executor.calculateDelay(10, RetryableErrorServer)
	if delayHigh != policy.MaxDelay {
		t.Errorf("Expected max delay %v, got %v", policy.MaxDelay, delayHigh)
	}
}

// TestRetryExecutor_WithCircuitBreaker tests circuit breaker integration
func TestRetryExecutor_WithCircuitBreaker(t *testing.T) {
	cb := NewCircuitBreaker("test", 2, 100*time.Millisecond)

	policy := &RetryPolicy{
		MaxRetries:        5,
		InitialDelay:      10 * time.Millisecond,
		MaxDelay:          100 * time.Millisecond,
		BackoffMultiplier: 2.0,
	}

	executor := NewRetryExecutor(policy, cb)

	// First two failures should trigger circuit breaker
	for i := 0; i < 2; i++ {
		executor.Execute(context.Background(), func() error {
			return errors.New("status 503: server error")
		})
	}

	// Circuit breaker should be open now
	if cb.State() != BreakerStateOpen {
		t.Errorf("Expected circuit breaker to be open, got %v", cb.State())
	}

	// Next execution should fail immediately
	err := executor.Execute(context.Background(), func() error {
		return nil
	})

	if err == nil || err.Error() != "circuit breaker is open" {
		t.Errorf("Expected circuit breaker error, got %v", err)
	}
}

// TestRetryStats tests retry statistics
func TestRetryStats(t *testing.T) {
	stats := &RetryStats{}

	// Record successes
	stats.RecordAttempt(nil)
	stats.RecordAttempt(nil)

	// Record failures
	stats.RecordAttempt(errors.New("error 1"))
	stats.RecordAttempt(errors.New("error 2"))

	// Record retries
	stats.RecordRetry()
	stats.RecordRetry()
	stats.RecordRetry()

	result := stats.GetStats()

	if result["total_attempts"] != 4 {
		t.Errorf("Expected 4 total attempts, got %v", result["total_attempts"])
	}
	if result["success_count"] != 2 {
		t.Errorf("Expected 2 successes, got %v", result["success_count"])
	}
	if result["failure_count"] != 2 {
		t.Errorf("Expected 2 failures, got %v", result["failure_count"])
	}
	if result["retry_count"] != 3 {
		t.Errorf("Expected 3 retries, got %v", result["retry_count"])
	}

	successRate := result["success_rate"].(string)
	if successRate != "50.0%" {
		t.Errorf("Expected 50.0%% success rate, got %v", successRate)
	}
}

// TestPerEndpointRetryManager tests per-endpoint retry management
func TestPerEndpointRetryManager(t *testing.T) {
	manager := NewPerEndpointRetryManager(nil)

	// Set custom policy for orders
	manager.SetPolicy("/api/v3/order", AggressiveRetryPolicy())

	// Set custom policy for account
	manager.SetPolicy("/api/v3/account", ConservativeRetryPolicy())

	// Test order endpoint gets aggressive policy
	orderExecutor := manager.GetExecutor("/api/v3/order")
	if orderExecutor.policy.MaxRetries != 5 {
		t.Errorf("Expected 5 retries for orders, got %d", orderExecutor.policy.MaxRetries)
	}

	// Test account endpoint gets conservative policy
	accountExecutor := manager.GetExecutor("/api/v3/account")
	if accountExecutor.policy.MaxRetries != 2 {
		t.Errorf("Expected 2 retries for account, got %d", accountExecutor.policy.MaxRetries)
	}

	// Test unknown endpoint gets default policy
	otherExecutor := manager.GetExecutor("/api/v3/ticker")
	if otherExecutor.policy.MaxRetries != 3 {
		t.Errorf("Expected 3 retries for default, got %d", otherExecutor.policy.MaxRetries)
	}
}

// TestBinanceAPIError tests Binance API error parsing
func TestBinanceAPIError(t *testing.T) {
	// Test retryable error codes
	retryableCodes := []int{-1001, -1003, -1006, -1007, -1016}
	for _, code := range retryableCodes {
		err := &BinanceAPIError{
			Code:   code,
			Status: 200,
		}
		if !err.IsRetryable() {
			t.Errorf("Expected code %d to be retryable", code)
		}
	}

	// Test 5xx status codes
	err5xx := &BinanceAPIError{
		Code:   -1,
		Status: 503,
	}
	if !err5xx.IsRetryable() {
		t.Error("Expected 503 error to be retryable")
	}

	// Test 429 status code
	err429 := &BinanceAPIError{
		Code:   -1,
		Status: 429,
	}
	if !err429.IsRetryable() {
		t.Error("Expected 429 error to be retryable")
	}

	// Test non-retryable 4xx
	err400 := &BinanceAPIError{
		Code:   -1,
		Status: 400,
	}
	if err400.IsRetryable() {
		t.Error("Expected 400 error to be non-retryable")
	}
}

// TestBinanceAPIError_Error tests error string formatting
func TestBinanceAPIError_Error(t *testing.T) {
	err := &BinanceAPIError{
		Code:    -2010,
		Message: "Insufficient balance",
		Status:  400,
	}

	expected := "Binance API error (code=-2010, status=400): Insufficient balance"
	if err.Error() != expected {
		t.Errorf("Expected %q, got %q", expected, err.Error())
	}
}

// TestRetryExecutor_ConcurrentAccess tests thread safety
func TestRetryExecutor_ConcurrentAccess(t *testing.T) {
	policy := &RetryPolicy{
		MaxRetries:        3,
		InitialDelay:      10 * time.Millisecond,
		MaxDelay:          100 * time.Millisecond,
		BackoffMultiplier: 2.0,
	}

	executor := NewRetryExecutor(policy, nil)
	var successCount int32

	// Run concurrent operations
	done := make(chan bool, 10)
	for i := 0; i < 10; i++ {
		go func() {
			err := executor.Execute(context.Background(), func() error {
				return nil
			})
			if err == nil {
				atomic.AddInt32(&successCount, 1)
			}
			done <- true
		}()
	}

	// Wait for all to complete
	for i := 0; i < 10; i++ {
		<-done
	}

	if successCount != 10 {
		t.Errorf("Expected 10 successes, got %d", successCount)
	}
}

// TestRetryableErrorType_String tests string representation
func TestRetryableErrorType_String(t *testing.T) {
	tests := []struct {
		typ      RetryableErrorType
		expected string
	}{
		{RetryableErrorNone, "NonRetryable"},
		{RetryableErrorServer, "ServerError"},
		{RetryableErrorRateLimit, "RateLimit"},
		{RetryableErrorNetwork, "NetworkError"},
		{RetryableErrorTemporary, "Temporary"},
		{RetryableErrorType(999), "Unknown"},
	}

	for _, tc := range tests {
		if got := tc.typ.String(); got != tc.expected {
			t.Errorf("%v.String() = %q, expected %q", tc.typ, got, tc.expected)
		}
	}
}

// TestParseBinanceError tests error parsing
func TestParseBinanceError(t *testing.T) {
	// Test nil error
	if ParseBinanceError(nil, 200) != nil {
		t.Error("Expected nil for nil error")
	}

	// Test regular error
	err := errors.New("some error")
	parsed := ParseBinanceError(err, 500)
	if parsed == nil {
		t.Error("Expected non-nil parsed error")
	}
	if parsed.Status != 500 {
		t.Errorf("Expected status 500, got %d", parsed.Status)
	}
	if parsed.Message != "some error" {
		t.Errorf("Expected message 'some error', got %q", parsed.Message)
	}
}

// TestGlobalRetryManager tests singleton pattern
func TestGlobalRetryManager(t *testing.T) {
	manager1 := GetGlobalRetryManager()
	manager2 := GetGlobalRetryManager()

	if manager1 != manager2 {
		t.Error("Expected singleton instances to be the same")
	}

	// Verify default policies are set
	orderExecutor := manager1.GetExecutor("/api/v3/order")
	if orderExecutor.policy.MaxRetries != 5 {
		t.Errorf("Expected aggressive policy for orders, got %d retries", orderExecutor.policy.MaxRetries)
	}
}

// TestRetryExecutor_ExecuteWithResult tests result-returning execution
func TestRetryExecutor_ExecuteWithResult(t *testing.T) {
	policy := &RetryPolicy{
		MaxRetries:        3,
		InitialDelay:      10 * time.Millisecond,
		MaxDelay:          100 * time.Millisecond,
		BackoffMultiplier: 2.0,
	}

	executor := NewRetryExecutor(policy, nil)

	expectedResult := "success data"
	callCount := 0

	result, err := executor.ExecuteWithResult(context.Background(), func() (interface{}, error) {
		callCount++
		if callCount < 2 {
			return nil, errors.New("status 503: server error")
		}
		return expectedResult, nil
	})

	if err != nil {
		t.Errorf("Expected no error, got %v", err)
	}
	if result != expectedResult {
		t.Errorf("Expected %q, got %v", expectedResult, result)
	}
	if callCount != 2 {
		t.Errorf("Expected 2 calls, got %d", callCount)
	}
}

// ExampleRetryExecutor shows example usage
func ExampleRetryExecutor() {
	policy := DefaultRetryPolicy()
	executor := NewRetryExecutor(policy, nil)

	ctx := context.Background()
	err := executor.Execute(ctx, func() error {
		// Your API call here
		return nil
	})

	if err != nil {
		fmt.Printf("Operation failed: %v\n", err)
	}
}
