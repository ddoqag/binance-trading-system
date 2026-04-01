package main

import (
	"context"
	"errors"
	"fmt"
	"log"
	"net/http"
	"strings"
	"sync"
	"time"
)

/*
retry.go - Intelligent Error Retry Mechanism

Implements smart retry strategies for API calls:
- Exponential backoff with jitter
- Retryable error classification
- Per-endpoint retry policies
- Integration with circuit breaker
- Context-aware cancellation
- Max retry limits with decay

Retryable Errors:
- 5xx Server errors (500, 502, 503, 504)
- 429 Rate limit (with retry-after)
- Network timeouts
- Temporary connection errors

Non-Retryable Errors:
- 4xx Client errors (400, 401, 403, 404)
- Invalid signature
- Insufficient balance
- Invalid parameters
*/

// RetryPolicy defines retry behavior for different error types
type RetryPolicy struct {
	MaxRetries       int           // Maximum number of retry attempts
	InitialDelay     time.Duration // Initial delay between retries
	MaxDelay         time.Duration // Maximum delay cap
	BackoffMultiplier float64      // Exponential backoff multiplier
	JitterFactor     float64       // Random jitter factor (0-1)
}

// DefaultRetryPolicy returns default retry configuration
func DefaultRetryPolicy() *RetryPolicy {
	return &RetryPolicy{
		MaxRetries:        3,
		InitialDelay:      500 * time.Millisecond,
		MaxDelay:          30 * time.Second,
		BackoffMultiplier: 2.0,
		JitterFactor:      0.2,
	}
}

// AggressiveRetryPolicy for critical operations (orders)
func AggressiveRetryPolicy() *RetryPolicy {
	return &RetryPolicy{
		MaxRetries:        5,
		InitialDelay:      200 * time.Millisecond,
		MaxDelay:          10 * time.Second,
		BackoffMultiplier: 1.5,
		JitterFactor:      0.1,
	}
}

// ConservativeRetryPolicy for non-critical operations
func ConservativeRetryPolicy() *RetryPolicy {
	return &RetryPolicy{
		MaxRetries:        2,
		InitialDelay:      1 * time.Second,
		MaxDelay:          60 * time.Second,
		BackoffMultiplier: 2.0,
		JitterFactor:      0.3,
	}
}

// RetryableErrorType categorizes errors for retry decisions
type RetryableErrorType int

const (
	RetryableErrorNone RetryableErrorType = iota
	RetryableErrorServer          // 5xx errors
	RetryableErrorRateLimit       // 429 errors
	RetryableErrorNetwork         // Network/timeout errors
	RetryableErrorTemporary       // Temporary errors
)

func (t RetryableErrorType) String() string {
	switch t {
	case RetryableErrorNone:
		return "NonRetryable"
	case RetryableErrorServer:
		return "ServerError"
	case RetryableErrorRateLimit:
		return "RateLimit"
	case RetryableErrorNetwork:
		return "NetworkError"
	case RetryableErrorTemporary:
		return "Temporary"
	default:
		return "Unknown"
	}
}

// ErrorClassifier analyzes errors and determines retryability
type ErrorClassifier struct {
	// Custom error patterns for classification
	retryablePatterns []string
	nonRetryablePatterns []string
}

// NewErrorClassifier creates a new error classifier
func NewErrorClassifier() *ErrorClassifier {
	return &ErrorClassifier{
		retryablePatterns: []string{
			"connection reset",
			"connection refused",
			"timeout",
			"temporary",
			"server error",
			"service unavailable",
			"gateway",
			"rate limit",
		},
		nonRetryablePatterns: []string{
			"invalid api key",
			"invalid signature",
			"insufficient balance",
			"invalid symbol",
			"min notional",
			"precision",
			"unauthorized",
			"forbidden",
			"not found",
		},
	}
}

// Classify analyzes an error and returns its retry type
func (ec *ErrorClassifier) Classify(err error) RetryableErrorType {
	if err == nil {
		return RetryableErrorNone
	}

	errStr := strings.ToLower(err.Error())

	// Check HTTP status codes first
	if strings.Contains(errStr, "status 429") ||
		strings.Contains(errStr, "rate limit") ||
		strings.Contains(errStr, "too many requests") {
		return RetryableErrorRateLimit
	}

	if strings.Contains(errStr, "status 503") ||
		strings.Contains(errStr, "status 504") ||
		strings.Contains(errStr, "status 502") ||
		strings.Contains(errStr, "status 500") {
		return RetryableErrorServer
	}

	// Check for network errors
	if strings.Contains(errStr, "timeout") ||
		strings.Contains(errStr, "connection reset") ||
		strings.Contains(errStr, "connection refused") ||
		strings.Contains(errStr, "no such host") ||
		strings.Contains(errStr, "network is unreachable") {
		return RetryableErrorNetwork
	}

	// Check non-retryable patterns
	for _, pattern := range ec.nonRetryablePatterns {
		if strings.Contains(errStr, pattern) {
			return RetryableErrorNone
		}
	}

	// Check retryable patterns
	for _, pattern := range ec.retryablePatterns {
		if strings.Contains(errStr, pattern) {
			return RetryableErrorTemporary
		}
	}

	// Check for context cancellation
	if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
		// Context errors from our side are not retryable
		return RetryableErrorNone
	}

	return RetryableErrorTemporary
}

// IsRetryable checks if an error should be retried
func (ec *ErrorClassifier) IsRetryable(err error) bool {
	return ec.Classify(err) != RetryableErrorNone
}

// RetryStats tracks retry statistics
type RetryStats struct {
	TotalAttempts   int
	SuccessCount    int
	FailureCount    int
	RetryCount      int
	LastRetryAt     time.Time
	LastError       error
	mu              sync.RWMutex
}

// RecordAttempt records a retry attempt
func (rs *RetryStats) RecordAttempt(err error) {
	rs.mu.Lock()
	defer rs.mu.Unlock()

	rs.TotalAttempts++
	if err != nil {
		rs.FailureCount++
		rs.LastError = err
	} else {
		rs.SuccessCount++
	}
	rs.LastRetryAt = time.Now()
}

// RecordRetry records that a retry was performed
func (rs *RetryStats) RecordRetry() {
	rs.mu.Lock()
	defer rs.mu.Unlock()
	rs.RetryCount++
}

// GetStats returns current statistics
func (rs *RetryStats) GetStats() map[string]interface{} {
	rs.mu.RLock()
	defer rs.mu.RUnlock()

	successRate := 0.0
	if rs.TotalAttempts > 0 {
		successRate = float64(rs.SuccessCount) / float64(rs.TotalAttempts) * 100
	}

	return map[string]interface{}{
		"total_attempts": rs.TotalAttempts,
		"success_count":  rs.SuccessCount,
		"failure_count":  rs.FailureCount,
		"retry_count":    rs.RetryCount,
		"success_rate":   fmt.Sprintf("%.1f%%", successRate),
		"last_retry_at":  rs.LastRetryAt,
		"last_error":     rs.LastError,
	}
}

// RetryExecutor executes functions with retry logic
type RetryExecutor struct {
	policy     *RetryPolicy
	classifier *ErrorClassifier
	stats      *RetryStats
	cb         *CircuitBreaker // Optional circuit breaker
}

// NewRetryExecutor creates a new retry executor
func NewRetryExecutor(policy *RetryPolicy, cb *CircuitBreaker) *RetryExecutor {
	if policy == nil {
		policy = DefaultRetryPolicy()
	}
	return &RetryExecutor{
		policy:     policy,
		classifier: NewErrorClassifier(),
		stats:      &RetryStats{},
		cb:         cb,
	}
}

// Execute runs a function with retry logic
func (re *RetryExecutor) Execute(ctx context.Context, operation func() error) error {
	_, err := re.ExecuteWithResult(ctx, func() (interface{}, error) {
		return nil, operation()
	})
	return err
}

// ExecuteWithResult runs a function that returns a result with retry logic
func (re *RetryExecutor) ExecuteWithResult(ctx context.Context, operation func() (interface{}, error)) (interface{}, error) {
	var lastErr error

	for attempt := 0; attempt <= re.policy.MaxRetries; attempt++ {
		// Check context cancellation
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		default:
		}

		// Check circuit breaker if available
		if re.cb != nil && !re.cb.Allow() {
			return nil, fmt.Errorf("circuit breaker is open")
		}

		// Execute the operation
		result, err := operation()
		re.stats.RecordAttempt(err)

		if err == nil {
			// Success
			if re.cb != nil {
				re.cb.RecordSuccess()
			}
			return result, nil
		}

		lastErr = err

		// Record failure in circuit breaker
		if re.cb != nil {
			re.cb.RecordFailure()
		}

		// Check if we should retry
		if attempt >= re.policy.MaxRetries {
			break
		}

		retryType := re.classifier.Classify(err)
		if retryType == RetryableErrorNone {
			// Non-retryable error, return immediately
			return nil, err
		}

		// Calculate backoff delay
		delay := re.calculateDelay(attempt, retryType)

		log.Printf("[RETRY] Attempt %d/%d failed (%s): %v. Retrying in %v...",
			attempt+1, re.policy.MaxRetries+1, retryType, err, delay)

		re.stats.RecordRetry()

		// Wait before retry with context awareness
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(delay):
			// Continue to next attempt
		}
	}

	return nil, fmt.Errorf("max retries (%d) exceeded: %w", re.policy.MaxRetries, lastErr)
}

// calculateDelay calculates the backoff delay for a retry attempt
func (re *RetryExecutor) calculateDelay(attempt int, retryType RetryableErrorType) time.Duration {
	// Base delay calculation with exponential backoff
	delay := re.policy.InitialDelay
	for i := 0; i < attempt; i++ {
		delay = time.Duration(float64(delay) * re.policy.BackoffMultiplier)
	}

	// Apply type-specific multipliers
	switch retryType {
	case RetryableErrorRateLimit:
		// Rate limit errors need longer waits
		delay = delay * 2
	case RetryableErrorServer:
		// Server errors may need more time
		delay = delay * 3 / 2
	}

	// Cap at max delay
	if delay > re.policy.MaxDelay {
		delay = re.policy.MaxDelay
	}

	// Add jitter to prevent thundering herd
	if re.policy.JitterFactor > 0 {
		jitter := time.Duration(float64(delay) * re.policy.JitterFactor * (0.5 + randFloat()))
		delay = delay + jitter
	}

	return delay
}

// GetStats returns retry statistics
func (re *RetryExecutor) GetStats() map[string]interface{} {
	return re.stats.GetStats()
}

// PerEndpointRetryManager manages retry policies per endpoint
type PerEndpointRetryManager struct {
	policies   map[string]*RetryPolicy
	executors  map[string]*RetryExecutor
	classifier *ErrorClassifier
	cb         *CircuitBreaker
	mu         sync.RWMutex
}

// NewPerEndpointRetryManager creates a new per-endpoint retry manager
func NewPerEndpointRetryManager(cb *CircuitBreaker) *PerEndpointRetryManager {
	return &PerEndpointRetryManager{
		policies:   make(map[string]*RetryPolicy),
		executors:  make(map[string]*RetryExecutor),
		classifier: NewErrorClassifier(),
		cb:         cb,
	}
}

// SetPolicy sets retry policy for a specific endpoint pattern
func (pm *PerEndpointRetryManager) SetPolicy(pattern string, policy *RetryPolicy) {
	pm.mu.Lock()
	defer pm.mu.Unlock()
	pm.policies[pattern] = policy
}

// GetExecutor returns the appropriate retry executor for an endpoint
func (pm *PerEndpointRetryManager) GetExecutor(endpoint string) *RetryExecutor {
	pm.mu.RLock()
	policy, exists := pm.policies[endpoint]
	pm.mu.RUnlock()

	if exists {
		return NewRetryExecutor(policy, pm.cb)
	}

	// Check for pattern matches
	pm.mu.RLock()
	for pattern, policy := range pm.policies {
		if strings.Contains(endpoint, pattern) {
			pm.mu.RUnlock()
			return NewRetryExecutor(policy, pm.cb)
		}
	}
	pm.mu.RUnlock()

	// Return default executor
	return NewRetryExecutor(DefaultRetryPolicy(), pm.cb)
}

// Execute executes an operation for a specific endpoint with appropriate retry policy
func (pm *PerEndpointRetryManager) Execute(ctx context.Context, endpoint string, operation func() error) error {
	executor := pm.GetExecutor(endpoint)
	return executor.Execute(ctx, operation)
}

// ExecuteWithResult executes an operation with result for a specific endpoint
func (pm *PerEndpointRetryManager) ExecuteWithResult(ctx context.Context, endpoint string, operation func() (interface{}, error)) (interface{}, error) {
	executor := pm.GetExecutor(endpoint)
	return executor.ExecuteWithResult(ctx, operation)
}

// Helper function for random float between 0 and 1
func randFloat() float64 {
	// Simple pseudo-random using time
	return float64(time.Now().UnixNano()%1000) / 1000.0
}

// BinanceAPIError represents a structured Binance API error
type BinanceAPIError struct {
	Code    int    `json:"code"`
	Message string `json:"msg"`
	Status  int    // HTTP status code
}

func (e *BinanceAPIError) Error() string {
	return fmt.Sprintf("Binance API error (code=%d, status=%d): %s", e.Code, e.Status, e.Message)
}

// IsRetryable checks if this error should be retried
func (e *BinanceAPIError) IsRetryable() bool {
	// Known retryable error codes
	retryableCodes := map[int]bool{
		-1001: true, // Internal error
		-1003: true, // Rate limit exceeded
		-1006: true, // Server busy
		-1007: true, // Timeout
		-1016: true, // Service shutting down
		-1021: true, // Timestamp error (might be retryable)
	}

	if retryableCodes[e.Code] {
		return true
	}

	// 5xx status codes are retryable
	if e.Status >= 500 && e.Status < 600 {
		return true
	}

	// 429 is rate limit
	if e.Status == http.StatusTooManyRequests {
		return true
	}

	return false
}

// ParseBinanceError parses an error and extracts Binance API error if present
func ParseBinanceError(err error, statusCode int) *BinanceAPIError {
	if err == nil {
		return nil
	}

	// Try to extract error code from message
	errStr := err.Error()

	// Check if it's already a BinanceAPIError
	var apiErr *BinanceAPIError
	if errors.As(err, &apiErr) {
		return apiErr
	}

	return &BinanceAPIError{
		Code:    -1, // Unknown
		Message: errStr,
		Status:  statusCode,
	}
}

// RetryWithBinanceClient wraps a BinanceClient operation with retry logic
func RetryWithBinanceClient(ctx context.Context, client *BinanceClient, endpoint string, priority RequestPriority, operation func() error) error {
	// Get appropriate retry policy based on endpoint
	var policy *RetryPolicy
	if strings.Contains(endpoint, "/order") {
		policy = AggressiveRetryPolicy() // Orders need aggressive retry
	} else if strings.Contains(endpoint, "/account") {
		policy = DefaultRetryPolicy()
	} else {
		policy = ConservativeRetryPolicy()
	}

	executor := NewRetryExecutor(policy, nil)

	return executor.Execute(ctx, func() error {
		return client.executeWithQueue(ctx, endpoint, priority, operation)
	})
}

// Global retry manager instance
var (
	globalRetryManager *PerEndpointRetryManager
	globalRetryOnce    sync.Once
)

// GetGlobalRetryManager returns the singleton retry manager
func GetGlobalRetryManager() *PerEndpointRetryManager {
	globalRetryOnce.Do(func() {
		globalRetryManager = NewPerEndpointRetryManager(nil)
		// Configure default policies
		globalRetryManager.SetPolicy("/api/v3/order", AggressiveRetryPolicy())
		globalRetryManager.SetPolicy("/api/v3/account", DefaultRetryPolicy())
	})
	return globalRetryManager
}
