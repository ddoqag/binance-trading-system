package main

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
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
	BreakerStateClosed BreakerState = iota    // Normal operation
	BreakerStateOpen                          // Failing, reject requests
	BreakerStateHalfOpen                      // Testing if recovered
)

func NewCircuitBreaker(name string, threshold int, timeout time.Duration) *CircuitBreaker {
	return &CircuitBreaker{
		name:             name,
		failureThreshold: threshold,
		timeout:          timeout,
		state:            BreakerStateClosed,
	}
}

func (cb *CircuitBreaker) Allow() bool {
	cb.mu.RLock()
	defer cb.mu.RUnlock()

	switch cb.state {
	case BreakerStateClosed:
		return true
	case BreakerStateOpen:
		// Check if timeout has passed
		if time.Since(cb.lastFailure) > cb.timeout {
			cb.mu.RUnlock()
			cb.mu.Lock()
			cb.state = BreakerStateHalfOpen
			cb.mu.Unlock()
			cb.mu.RLock()
			return true
		}
		return false
	case BreakerStateHalfOpen:
		return true
	default:
		return false
	}
}

func (cb *CircuitBreaker) RecordSuccess() {
	cb.mu.Lock()
	defer cb.mu.Unlock()

	if cb.state == BreakerStateHalfOpen {
		cb.state = BreakerStateClosed
		cb.failureCount = 0
		log.Printf("[CB] %s: Recovered, closing circuit", cb.name)
	}
}

func (cb *CircuitBreaker) RecordFailure() {
	cb.mu.Lock()
	defer cb.mu.Unlock()

	cb.failureCount++
	cb.lastFailure = time.Now()

	if cb.state == BreakerStateHalfOpen {
		cb.state = BreakerStateOpen
		log.Printf("[CB] %s: Still failing, opening circuit", cb.name)
	} else if cb.failureCount >= cb.failureThreshold {
		cb.state = BreakerStateOpen
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
	if dm.apiCB.State() == BreakerStateOpen {
		failing++
	}
	if dm.orderCB.State() == BreakerStateOpen {
		failing++
	}
	if dm.websocketCB.State() == BreakerStateOpen {
		failing++
	}
	if dm.shmCB.State() == BreakerStateOpen {
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

// ============================================================================
// Enhanced Multi-Level Degradation Strategy (P4-002)
// ============================================================================

// DegradeAction represents the action to take at each degradation level
type DegradeAction int

const (
	ActionNone DegradeAction = iota
	ActionReducePositionSize    // Reduce max position size by 50%
	ActionIncreaseChecks        // Double risk checks
	ActionOnlyClose             // Only allow closing orders
	ActionCancelPending         // Cancel all pending orders
	ActionCloseAllPositions     // Close all positions immediately
	ActionStopTrading           // Stop all trading
	ActionEmergencyShutdown     // Emergency shutdown
)

func (a DegradeAction) String() string {
	switch a {
	case ActionNone:
		return "NONE"
	case ActionReducePositionSize:
		return "REDUCE_POSITION_SIZE"
	case ActionIncreaseChecks:
		return "INCREASE_CHECKS"
	case ActionOnlyClose:
		return "ONLY_CLOSE"
	case ActionCancelPending:
		return "CANCEL_PENDING"
	case ActionCloseAllPositions:
		return "CLOSE_ALL_POSITIONS"
	case ActionStopTrading:
		return "STOP_TRADING"
	case ActionEmergencyShutdown:
		return "EMERGENCY_SHUTDOWN"
	default:
		return "UNKNOWN"
	}
}

// DegradeRule defines a rule for triggering degradation
type DegradeRule struct {
	Name          string
	Condition     func(*SystemMetrics) bool
	Level         DegradeLevel
	Actions       []DegradeAction
	AutoRecover   bool          // Whether to auto-recover when condition clears
	RecoveryDelay time.Duration // Minimum time before recovery
}

// SystemMetrics tracks system health metrics
type SystemMetrics struct {
	Timestamp        time.Time
	APILatencyP99    time.Duration
	ErrorRate        float64       // 0-1
	CPUUsage         float64       // 0-1
	MemoryUsage      float64       // 0-1
	DiskUsage        float64       // 0-1
	DailyDrawdown    float64       // 0-1
	OpenOrders       int
	PositionCount    int
	WebSocketLatency time.Duration
	RateLimitHits    int
	CircuitBreakerOpen int
}

// DegradeConfig holds configuration for the degradation system
type DegradeConfig struct {
	// Thresholds
	LatencyThresholdP99    time.Duration // P99 latency threshold
	ErrorRateThreshold     float64       // Error rate threshold
	CPUPercentThreshold    float64       // CPU usage threshold
	MemoryPercentThreshold float64       // Memory usage threshold
	DailyDrawdownThreshold float64       // Daily drawdown threshold

	// Timing
	CheckInterval   time.Duration // How often to check metrics
	RecoveryDelay   time.Duration // Minimum time before auto-recovery
	DegradeCooldown time.Duration // Minimum time between degradations

	// Actions per level
	LevelActions map[DegradeLevel][]DegradeAction

	// Callbacks
	OnLevelChange func(oldLevel, newLevel DegradeLevel, actions []DegradeAction)
	OnAction      func(action DegradeAction, reason string)
}

// DefaultDegradeConfig returns default configuration
func DefaultDegradeConfig() *DegradeConfig {
	return &DegradeConfig{
		LatencyThresholdP99:    100 * time.Millisecond,
		ErrorRateThreshold:     0.05, // 5%
		CPUPercentThreshold:    0.8,  // 80%
		MemoryPercentThreshold: 0.85, // 85%
		DailyDrawdownThreshold: 0.05, // 5%

		CheckInterval:   5 * time.Second,
		RecoveryDelay:   30 * time.Second,
		DegradeCooldown: 10 * time.Second,

		LevelActions: map[DegradeLevel][]DegradeAction{
			LevelNormal:     {ActionNone},
			LevelCautious:   {ActionReducePositionSize, ActionIncreaseChecks},
			LevelRestricted: {ActionOnlyClose, ActionCancelPending},
			LevelEmergency:  {ActionCloseAllPositions, ActionStopTrading},
		},
	}
}

// EnhancedDegradeManager provides production-grade degradation management
type EnhancedDegradeManager struct {
	config      *DegradeConfig
	currentLevel DegradeLevel
	mu          sync.RWMutex

	// Metrics tracking
	metrics     *SystemMetrics
	metricsMu   sync.RWMutex
	metricsHistory []SystemMetrics
	maxHistorySize int

	// State tracking
	levelChangedAt  time.Time
	lastDegradedAt  time.Time
	actionHistory   []DegradeActionRecord

	// Control
	stopChan    chan struct{}
	wg          sync.WaitGroup
	paused      bool

	// Custom rules
	customRules []DegradeRule
}

// DegradeActionRecord records an action taken
type DegradeActionRecord struct {
	Timestamp time.Time
	Action    DegradeAction
	Level     DegradeLevel
	Reason    string
}

// NewEnhancedDegradeManager creates a new enhanced degradation manager
func NewEnhancedDegradeManager(config *DegradeConfig) *EnhancedDegradeManager {
	if config == nil {
		config = DefaultDegradeConfig()
	}

	edm := &EnhancedDegradeManager{
		config:         config,
		currentLevel:   LevelNormal,
		metrics:        &SystemMetrics{Timestamp: time.Now()},
		metricsHistory: make([]SystemMetrics, 0, 100),
		maxHistorySize: 1000,
		stopChan:       make(chan struct{}),
		actionHistory:  make([]DegradeActionRecord, 0),
		customRules:    make([]DegradeRule, 0),
	}

	return edm
}

// Start begins the monitoring loop
func (edm *EnhancedDegradeManager) Start() {
	edm.wg.Add(1)
	go edm.monitorLoop()
	log.Println("[EnhancedDegrade] Started monitoring")
}

// Stop halts the monitoring loop
func (edm *EnhancedDegradeManager) Stop() {
	close(edm.stopChan)
	edm.wg.Wait()
	log.Println("[EnhancedDegrade] Stopped monitoring")
}

// Pause temporarily disables degradation checks
func (edm *EnhancedDegradeManager) Pause() {
	edm.mu.Lock()
	defer edm.mu.Unlock()
	edm.paused = true
	log.Println("[EnhancedDegrade] Paused")
}

// Resume re-enables degradation checks
func (edm *EnhancedDegradeManager) Resume() {
	edm.mu.Lock()
	defer edm.mu.Unlock()
	edm.paused = false
	log.Println("[EnhancedDegrade] Resumed")
}

// monitorLoop continuously monitors system health
func (edm *EnhancedDegradeManager) monitorLoop() {
	defer edm.wg.Done()
	ticker := time.NewTicker(edm.config.CheckInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			edm.checkAndDegrade()
		case <-edm.stopChan:
			return
		}
	}
}

// checkAndDegrade evaluates metrics and triggers degradation if needed
func (edm *EnhancedDegradeManager) checkAndDegrade() {
	edm.mu.RLock()
	if edm.paused {
		edm.mu.RUnlock()
		return
	}
	edm.mu.RUnlock()

	// Get current metrics
	edm.metricsMu.RLock()
	metrics := *edm.metrics
	edm.metricsMu.RUnlock()

	// Determine appropriate level based on metrics
	newLevel := edm.determineDegradeLevel(&metrics)

	edm.mu.Lock()
	oldLevel := edm.currentLevel

	// Check cooldown
	if newLevel != oldLevel && !edm.lastDegradedAt.IsZero() {
		if time.Since(edm.lastDegradedAt) < edm.config.DegradeCooldown {
			edm.mu.Unlock()
			return
		}
	}

	if newLevel != oldLevel {
		edm.currentLevel = newLevel
		edm.levelChangedAt = time.Now()
		if newLevel > oldLevel { // Degrading (higher number = worse)
			edm.lastDegradedAt = time.Now()
		}
		edm.mu.Unlock()

		// Execute actions
		actions := edm.config.LevelActions[newLevel]
		edm.executeActions(actions, oldLevel, newLevel)

		// Notify callback
		if edm.config.OnLevelChange != nil {
			edm.config.OnLevelChange(oldLevel, newLevel, actions)
		}

		log.Printf("[EnhancedDegrade] Level changed: %s -> %s, actions: %v",
			oldLevel, newLevel, actions)
	} else {
		edm.mu.Unlock()
	}
}

// determineDegradeLevel calculates the appropriate degradation level
func (edm *EnhancedDegradeManager) determineDegradeLevel(metrics *SystemMetrics) DegradeLevel {
	// Check custom rules first
	for _, rule := range edm.customRules {
		if rule.Condition(metrics) {
			return rule.Level
		}
	}

	// Default logic based on metrics
	criticalCount := 0
	warningCount := 0

	// Check API latency
	if metrics.APILatencyP99 > edm.config.LatencyThresholdP99*2 {
		criticalCount++
	} else if metrics.APILatencyP99 > edm.config.LatencyThresholdP99 {
		warningCount++
	}

	// Check error rate
	if metrics.ErrorRate > edm.config.ErrorRateThreshold*2 {
		criticalCount++
	} else if metrics.ErrorRate > edm.config.ErrorRateThreshold {
		warningCount++
	}

	// Check drawdown
	if metrics.DailyDrawdown > edm.config.DailyDrawdownThreshold*2 {
		criticalCount++
	} else if metrics.DailyDrawdown > edm.config.DailyDrawdownThreshold {
		warningCount++
	}

	// Check circuit breakers
	if metrics.CircuitBreakerOpen >= 2 {
		criticalCount++
	} else if metrics.CircuitBreakerOpen >= 1 {
		warningCount++
	}

	// Determine level
	switch {
	case criticalCount >= 2 || metrics.DailyDrawdown > 0.1:
		return LevelEmergency
	case criticalCount >= 1 || warningCount >= 2:
		return LevelRestricted
	case warningCount >= 1:
		return LevelCautious
	default:
		return LevelNormal
	}
}

// executeActions performs the specified degradation actions
func (edm *EnhancedDegradeManager) executeActions(actions []DegradeAction, oldLevel, newLevel DegradeLevel) {
	for _, action := range actions {
		if action == ActionNone {
			continue
		}

		record := DegradeActionRecord{
			Timestamp: time.Now(),
			Action:    action,
			Level:     newLevel,
			Reason:    fmt.Sprintf("Degraded from %s to %s", oldLevel, newLevel),
		}

		edm.mu.Lock()
		edm.actionHistory = append(edm.actionHistory, record)
		edm.mu.Unlock()

		if edm.config.OnAction != nil {
			edm.config.OnAction(action, record.Reason)
		}

		log.Printf("[EnhancedDegrade] Executing action: %s", action)
	}
}

// UpdateMetrics updates the current system metrics
func (edm *EnhancedDegradeManager) UpdateMetrics(metrics *SystemMetrics) {
	edm.metricsMu.Lock()
	defer edm.metricsMu.Unlock()

	metrics.Timestamp = time.Now()
	edm.metrics = metrics

	// Add to history
	edm.metricsHistory = append(edm.metricsHistory, *metrics)
	if len(edm.metricsHistory) > edm.maxHistorySize {
		edm.metricsHistory = edm.metricsHistory[1:]
	}
}

// GetMetrics returns current metrics
func (edm *EnhancedDegradeManager) GetMetrics() SystemMetrics {
	edm.metricsMu.RLock()
	defer edm.metricsMu.RUnlock()
	return *edm.metrics
}

// GetMetricsHistory returns historical metrics
func (edm *EnhancedDegradeManager) GetMetricsHistory() []SystemMetrics {
	edm.metricsMu.RLock()
	defer edm.metricsMu.RUnlock()

	history := make([]SystemMetrics, len(edm.metricsHistory))
	copy(history, edm.metricsHistory)
	return history
}

// AddCustomRule adds a custom degradation rule
func (edm *EnhancedDegradeManager) AddCustomRule(rule DegradeRule) {
	edm.mu.Lock()
	defer edm.mu.Unlock()
	edm.customRules = append(edm.customRules, rule)
}

// RemoveCustomRule removes a custom rule by name
func (edm *EnhancedDegradeManager) RemoveCustomRule(name string) {
	edm.mu.Lock()
	defer edm.mu.Unlock()

	filtered := make([]DegradeRule, 0, len(edm.customRules))
	for _, rule := range edm.customRules {
		if rule.Name != name {
			filtered = append(filtered, rule)
		}
	}
	edm.customRules = filtered
}

// GetCurrentLevel returns current degradation level
func (edm *EnhancedDegradeManager) GetCurrentLevel() DegradeLevel {
	edm.mu.RLock()
	defer edm.mu.RUnlock()
	return edm.currentLevel
}

// GetActionHistory returns history of actions taken
func (edm *EnhancedDegradeManager) GetActionHistory() []DegradeActionRecord {
	edm.mu.RLock()
	defer edm.mu.RUnlock()

	history := make([]DegradeActionRecord, len(edm.actionHistory))
	copy(history, edm.actionHistory)
	return history
}

// GetStatus returns comprehensive status
func (edm *EnhancedDegradeManager) GetStatus() map[string]interface{} {
	edm.mu.RLock()
	edm.metricsMu.RLock()
	defer edm.mu.RUnlock()
	defer edm.metricsMu.RUnlock()

	return map[string]interface{}{
		"current_level":      edm.currentLevel.String(),
		"level_since":        edm.levelChangedAt,
		"last_degraded_at":   edm.lastDegradedAt,
		"paused":             edm.paused,
		"metrics":            edm.metrics,
		"action_count":       len(edm.actionHistory),
		"custom_rules_count": len(edm.customRules),
	}
}

// ExportState exports the current state to JSON
func (edm *EnhancedDegradeManager) ExportState() ([]byte, error) {
	edm.mu.RLock()
	edm.metricsMu.RLock()
	defer edm.mu.RUnlock()
	defer edm.metricsMu.RUnlock()

	state := map[string]interface{}{
		"current_level":   edm.currentLevel.String(),
		"level_changed_at": edm.levelChangedAt,
		"metrics":         edm.metrics,
		"action_history":  edm.actionHistory,
	}

	return json.MarshalIndent(state, "", "  ")
}

// ImportState imports state from JSON
func (edm *EnhancedDegradeManager) ImportState(data []byte) error {
	var state map[string]interface{}
	if err := json.Unmarshal(data, &state); err != nil {
		return err
	}

	// This is a simplified import - in production, parse all fields
	log.Printf("[EnhancedDegrade] State imported: %v", state)
	return nil
}

// ForceDegrade forces a specific degradation level (for manual intervention)
func (edm *EnhancedDegradeManager) ForceDegrade(level DegradeLevel, reason string) {
	edm.mu.Lock()
	oldLevel := edm.currentLevel
	edm.currentLevel = level
	edm.levelChangedAt = time.Now()
	edm.mu.Unlock()

	actions := edm.config.LevelActions[level]
	edm.executeActions(actions, oldLevel, level)

	log.Printf("[EnhancedDegrade] FORCED degrade to %s: %s", level, reason)
}

// CanTrade checks if trading is allowed at current level
func (edm *EnhancedDegradeManager) CanTrade(isClosing bool) bool {
	level := edm.GetCurrentLevel()

	switch level {
	case LevelEmergency:
		return false
	case LevelRestricted:
		return isClosing
	case LevelCautious, LevelNormal:
		return true
	default:
		return false
	}
}

// CanOpenPosition checks if opening new positions is allowed
func (edm *EnhancedDegradeManager) CanOpenPosition() bool {
	return edm.CanTrade(false)
}

// GetMaxPositionSize returns the maximum allowed position size at current level
func (edm *EnhancedDegradeManager) GetMaxPositionSize(normalMax float64) float64 {
	level := edm.GetCurrentLevel()

	switch level {
	case LevelCautious:
		return normalMax * 0.5 // 50% reduction
	case LevelRestricted, LevelEmergency:
		return 0 // No new positions
	default:
		return normalMax
	}
}

// SaveStateToFile saves state to a file
func (edm *EnhancedDegradeManager) SaveStateToFile(filepath string) error {
	data, err := edm.ExportState()
	if err != nil {
		return err
	}
	return os.WriteFile(filepath, data, 0644)
}

// LoadStateFromFile loads state from a file
func (edm *EnhancedDegradeManager) LoadStateFromFile(filepath string) error {
	data, err := os.ReadFile(filepath)
	if err != nil {
		return err
	}
	return edm.ImportState(data)
}
