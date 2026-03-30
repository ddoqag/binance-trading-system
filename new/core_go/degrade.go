package main

import (
	"log"
	"sync"
	"time"
)

/*
degrade.go - System Degradation and Circuit Breaker

Implements automatic degradation strategies:
- API rate limit detection and backoff
- Circuit breaker for failing components
- Graceful degradation modes
- Emergency shutdown procedures
*/

// DegradeLevel represents system degradation level
type DegradeLevel int

const (
	LevelNormal DegradeLevel = iota
	LevelCautious
	LevelRestricted
	LevelEmergency
)

func (d DegradeLevel) String() string {
	switch d {
	case LevelNormal:
		return "NORMAL"
	case LevelCautious:
		return "CAUTIOUS"
	case LevelRestricted:
		return "RESTRICTED"
	case LevelEmergency:
		return "EMERGENCY"
	default:
		return "UNKNOWN"
	}
}

// CircuitBreaker implements the circuit breaker pattern
type CircuitBreaker struct {
	name          string
	failureCount  int
	failureThreshold int
	timeout       time.Duration
	lastFailure   time.Time
	state         BreakerState
	mu            sync.RWMutex
}

type BreakerState int

const (
	StateClosed BreakerState = iota    // Normal operation
	StateOpen                          // Failing, reject requests
	StateHalfOpen                      // Testing if recovered
)

func NewCircuitBreaker(name string, threshold int, timeout time.Duration) *CircuitBreaker {
	return &CircuitBreaker{
		name:             name,
		failureThreshold: threshold,
		timeout:          timeout,
		state:            StateClosed,
	}
}

func (cb *CircuitBreaker) Allow() bool {
	cb.mu.RLock()
	defer cb.mu.RUnlock()

	switch cb.state {
	case StateClosed:
		return true
	case StateOpen:
		// Check if timeout has passed
		if time.Since(cb.lastFailure) > cb.timeout {
			cb.mu.RUnlock()
			cb.mu.Lock()
			cb.state = StateHalfOpen
			cb.mu.Unlock()
			cb.mu.RLock()
			return true
		}
		return false
	case StateHalfOpen:
		return true
	default:
		return false
	}
}

func (cb *CircuitBreaker) RecordSuccess() {
	cb.mu.Lock()
	defer cb.mu.Unlock()

	if cb.state == StateHalfOpen {
		cb.state = StateClosed
		cb.failureCount = 0
		log.Printf("[CB] %s: Recovered, closing circuit", cb.name)
	}
}

func (cb *CircuitBreaker) RecordFailure() {
	cb.mu.Lock()
	defer cb.mu.Unlock()

	cb.failureCount++
	cb.lastFailure = time.Now()

	if cb.state == StateHalfOpen {
		cb.state = StateOpen
		log.Printf("[CB] %s: Still failing, opening circuit", cb.name)
	} else if cb.failureCount >= cb.failureThreshold {
		cb.state = StateOpen
		log.Printf("[CB] %s: Failure threshold reached (%d), opening circuit",
			cb.name, cb.failureCount)
	}
}

func (cb *CircuitBreaker) State() BreakerState {
	cb.mu.RLock()
	defer cb.mu.RUnlock()
	return cb.state
}

// DegradeManager manages system-wide degradation
type DegradeManager struct {
	// Circuit breakers
	apiCB       *CircuitBreaker
	orderCB     *CircuitBreaker
	websocketCB *CircuitBreaker
	shmCB       *CircuitBreaker

	// Current level
	currentLevel DegradeLevel
	mu           sync.RWMutex

	// Metrics
	apiLatency    time.Duration
	errorRate     float64
	lastAPIError  time.Time
}

func NewDegradeManager() *DegradeManager {
	return &DegradeManager{
		apiCB:       NewCircuitBreaker("api", 5, 30*time.Second),
		orderCB:     NewCircuitBreaker("order", 3, 60*time.Second),
		websocketCB: NewCircuitBreaker("websocket", 10, 10*time.Second),
		shmCB:       NewCircuitBreaker("shm", 5, 5*time.Second),
		currentLevel: LevelNormal,
	}
}

// UpdateLevel updates degradation level based on system health
func (dm *DegradeManager) UpdateLevel() {
	dm.mu.Lock()
	defer dm.mu.Unlock()

	// Count failing components
	failing := 0
	if dm.apiCB.State() == StateOpen {
		failing++
	}
	if dm.orderCB.State() == StateOpen {
		failing++
	}
	if dm.websocketCB.State() == StateOpen {
		failing++
	}
	if dm.shmCB.State() == StateOpen {
		failing++
	}

	// Determine level
	oldLevel := dm.currentLevel

	switch {
	case failing >= 3 || dm.errorRate > 0.5:
		dm.currentLevel = LevelEmergency
	case failing >= 2 || dm.errorRate > 0.3:
		dm.currentLevel = LevelRestricted
	case failing >= 1 || dm.errorRate > 0.1:
		dm.currentLevel = LevelCautious
	default:
		dm.currentLevel = LevelNormal
	}

	if oldLevel != dm.currentLevel {
		log.Printf("[DEGRADE] Level changed: %s -> %s", oldLevel, dm.currentLevel)
		dm.onLevelChange(oldLevel, dm.currentLevel)
	}
}

func (dm *DegradeManager) onLevelChange(old, new DegradeLevel) {
	switch new {
	case LevelEmergency:
		log.Println("[DEGRADE] EMERGENCY: Stopping all trading activity")
		// Emergency stop all trading

	case LevelRestricted:
		log.Println("[DEGRADE] RESTRICTED: Only closing positions, no new orders")
		// Only allow closing orders

	case LevelCautious:
		log.Println("[DEGRADE] CAUTIOUS: Reduced order size, increased checks")
		// Reduce position sizes

	case LevelNormal:
		log.Println("[DEGRADE] NORMAL: Full operation resumed")
		// Resume normal operation
	}
}

// CanPlaceOrder checks if orders are allowed at current level
func (dm *DegradeManager) CanPlaceOrder(isClosing bool) bool {
	dm.mu.RLock()
	defer dm.mu.RUnlock()

	switch dm.currentLevel {
	case LevelEmergency:
		return false
	case LevelRestricted:
		return isClosing // Only closing orders allowed
	case LevelCautious, LevelNormal:
		return dm.orderCB.Allow()
	default:
		return false
	}
}

// GetCircuitBreakers returns all circuit breakers for status reporting
func (dm *DegradeManager) GetCircuitBreakers() map[string]BreakerState {
	return map[string]BreakerState{
		"api":       dm.apiCB.State(),
		"order":     dm.orderCB.State(),
		"websocket": dm.websocketCB.State(),
		"shm":       dm.shmCB.State(),
	}
}

// RecordAPIError records an API error
func (dm *DegradeManager) RecordAPIError() {
	dm.apiCB.RecordFailure()
	dm.lastAPIError = time.Now()
	dm.UpdateLevel()
}

// RecordAPISuccess records a successful API call
func (dm *DegradeManager) RecordAPISuccess() {
	dm.apiCB.RecordSuccess()
}

// RecordOrderError records an order execution error
func (dm *DegradeManager) RecordOrderError() {
	dm.orderCB.RecordFailure()
	dm.UpdateLevel()
}

// RecordOrderSuccess records a successful order
func (dm *DegradeManager) RecordOrderSuccess() {
	dm.orderCB.RecordSuccess()
}

// RecordWebSocketError records a WebSocket error
func (dm *DegradeManager) RecordWebSocketError() {
	dm.websocketCB.RecordFailure()
	dm.UpdateLevel()
}

// RecordWebSocketSuccess records a successful WebSocket operation
func (dm *DegradeManager) RecordWebSocketSuccess() {
	dm.websocketCB.RecordSuccess()
}

// SetAPILatency updates API latency metric
func (dm *DegradeManager) SetAPILatency(latency time.Duration) {
	dm.mu.Lock()
	dm.apiLatency = latency
	dm.mu.Unlock()

	// High latency can trigger degradation
	if latency > 500*time.Millisecond {
		dm.RecordAPIError()
	}
}

// SetErrorRate updates error rate metric
func (dm *DegradeManager) SetErrorRate(rate float64) {
	dm.mu.Lock()
	dm.errorRate = rate
	dm.mu.Unlock()
	dm.UpdateLevel()
}

// GetLevel returns current degradation level
func (dm *DegradeManager) GetLevel() DegradeLevel {
	dm.mu.RLock()
	defer dm.mu.RUnlock()
	return dm.currentLevel
}

// GetStatus returns full degradation status
func (dm *DegradeManager) GetStatus() map[string]interface{} {
	dm.mu.RLock()
	defer dm.mu.RUnlock()

	return map[string]interface{}{
		"level":            dm.currentLevel.String(),
		"api_latency_ms":   dm.apiLatency.Milliseconds(),
		"error_rate":       dm.errorRate,
		"circuit_breakers": dm.GetCircuitBreakers(),
	}
}
