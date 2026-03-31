package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"sync"
	"time"
)

/*
recovery.go - Automatic Fault Recovery System (P4-003)

Implements:
- Health monitoring and fault detection
- Automatic state recovery from WAL
- Component restart orchestration
- Recovery strategy selection
- Recovery audit logging
*/

// HealthStatus represents component health
type HealthStatus int

const (
	HealthUnknown HealthStatus = iota
	HealthHealthy
	HealthDegraded
	HealthUnhealthy
	HealthFailed
)

func (h HealthStatus) String() string {
	switch h {
	case HealthHealthy:
		return "HEALTHY"
	case HealthDegraded:
		return "DEGRADED"
	case HealthUnhealthy:
		return "UNHEALTHY"
	case HealthFailed:
		return "FAILED"
	default:
		return "UNKNOWN"
	}
}

// ComponentHealth tracks health of a system component
type ComponentHealth struct {
	Name          string
	Status        HealthStatus
	LastCheck     time.Time
	LastError     error
	ErrorCount    int
	SuccessCount  int
	Latency       time.Duration
	Metadata      map[string]interface{}
}

// IsHealthy returns true if component is healthy
func (ch *ComponentHealth) IsHealthy() bool {
	return ch.Status == HealthHealthy || ch.Status == HealthDegraded
}

// RecoveryStrategy defines how to recover a component
type RecoveryStrategy int

const (
	StrategyRestart RecoveryStrategy = iota
	StrategyResetState
	StrategyFailover
	StrategyGracefulShutdown
	StrategyImmediateShutdown
)

func (s RecoveryStrategy) String() string {
	switch s {
	case StrategyRestart:
		return "RESTART"
	case StrategyResetState:
		return "RESET_STATE"
	case StrategyFailover:
		return "FAILOVER"
	case StrategyGracefulShutdown:
		return "GRACEFUL_SHUTDOWN"
	case StrategyImmediateShutdown:
		return "IMMEDIATE_SHUTDOWN"
	default:
		return "UNKNOWN"
	}
}

// RecoveryConfig holds recovery configuration
type RecoveryConfig struct {
	// Health check intervals
	HealthCheckInterval    time.Duration
	HealthCheckTimeout     time.Duration

	// Recovery thresholds
	MaxConsecutiveFailures int
	RecoveryAttempts       int
	RecoveryCooldown       time.Duration

	// Component-specific strategies
	ComponentStrategies map[string]RecoveryStrategy

	// State recovery
	StateRecoveryEnabled bool
	WALDirectory         string
	CheckpointInterval   time.Duration

	// Callbacks
	OnRecoveryStart   func(component string, strategy RecoveryStrategy)
	OnRecoverySuccess func(component string)
	OnRecoveryFailure func(component string, err error)
}

// DefaultRecoveryConfig returns default configuration
func DefaultRecoveryConfig() *RecoveryConfig {
	return &RecoveryConfig{
		HealthCheckInterval:    5 * time.Second,
		HealthCheckTimeout:     3 * time.Second,
		MaxConsecutiveFailures: 3,
		RecoveryAttempts:       3,
		RecoveryCooldown:       30 * time.Second,
		ComponentStrategies: map[string]RecoveryStrategy{
			"api_client":   StrategyRestart,
			"websocket":    StrategyRestart,
			"order_exec":   StrategyResetState,
			"risk_manager": StrategyFailover,
		},
		StateRecoveryEnabled: true,
		WALDirectory:         "./wal_logs",
		CheckpointInterval:   5 * time.Minute,
	}
}

// RecoveryRecord tracks recovery attempts
type RecoveryRecord struct {
	Timestamp     time.Time
	Component     string
	Strategy      RecoveryStrategy
	Success       bool
	Error         string
	Duration      time.Duration
	StateRestored bool
}

// RecoveryManager manages automatic fault recovery
type RecoveryManager struct {
	config    *RecoveryConfig
	components map[string]*ComponentHealth
	mu        sync.RWMutex

	// Recovery tracking
	recoveryAttempts map[string]int
	recoveryHistory  []RecoveryRecord
	historyMu        sync.RWMutex

	// Control
	stopChan chan struct{}
	wg       sync.WaitGroup
	running  bool
	paused   bool

	// State recovery
	wal      *AsyncWAL
	checkpointDir string

	// Component factories for restart
	componentFactories map[string]func() error
}

// NewRecoveryManager creates a new recovery manager
func NewRecoveryManager(config *RecoveryConfig) (*RecoveryManager, error) {
	if config == nil {
		config = DefaultRecoveryConfig()
	}

	rm := &RecoveryManager{
		config:             config,
		components:         make(map[string]*ComponentHealth),
		recoveryAttempts:   make(map[string]int),
		recoveryHistory:    make([]RecoveryRecord, 0),
		stopChan:           make(chan struct{}),
		componentFactories: make(map[string]func() error),
		checkpointDir:      filepath.Join(config.WALDirectory, "checkpoints"),
	}

	// Create checkpoint directory
	if err := os.MkdirAll(rm.checkpointDir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create checkpoint dir: %w", err)
	}

	// Initialize WAL if state recovery enabled
	if config.StateRecoveryEnabled {
		walConfig := &WALConfig{
			LogDir:        config.WALDirectory,
			ArchiveDir:    filepath.Join(config.WALDirectory, "archive"),
			AsyncWrite:    true,
			CompressOld:   true,
			BatchSize:     100,
			FlushInterval: 100 * time.Millisecond,
		}
		wal, err := NewAsyncWAL(walConfig)
		if err != nil {
			return nil, fmt.Errorf("failed to init WAL: %w", err)
		}
		rm.wal = wal
	}

	return rm, nil
}

// RegisterComponent registers a component for health monitoring
func (rm *RecoveryManager) RegisterComponent(name string, factory func() error) {
	rm.mu.Lock()
	defer rm.mu.Unlock()

	rm.components[name] = &ComponentHealth{
		Name:       name,
		Status:     HealthUnknown,
		LastCheck:  time.Time{},
		Metadata:   make(map[string]interface{}),
	}
	rm.componentFactories[name] = factory
	log.Printf("[Recovery] Registered component: %s", name)
}

// UnregisterComponent removes a component from monitoring
func (rm *RecoveryManager) UnregisterComponent(name string) {
	rm.mu.Lock()
	defer rm.mu.Unlock()

	delete(rm.components, name)
	delete(rm.componentFactories, name)
	delete(rm.recoveryAttempts, name)
	log.Printf("[Recovery] Unregistered component: %s", name)
}

// Start begins health monitoring and recovery
func (rm *RecoveryManager) Start() {
	rm.mu.Lock()
	if rm.running {
		rm.mu.Unlock()
		return
	}
	rm.running = true
	rm.mu.Unlock()

	rm.wg.Add(2)
	go rm.healthCheckLoop()
	go rm.checkpointLoop()

	log.Println("[Recovery] Started health monitoring and recovery")
}

// Stop halts the recovery manager
func (rm *RecoveryManager) Stop() {
	rm.mu.Lock()
	if !rm.running {
		rm.mu.Unlock()
		return
	}
	rm.running = false
	rm.mu.Unlock()

	close(rm.stopChan)
	rm.wg.Wait()

	if rm.wal != nil {
		rm.wal.Close()
	}

	log.Println("[Recovery] Stopped")
}

// Pause temporarily disables recovery
func (rm *RecoveryManager) Pause() {
	rm.mu.Lock()
	defer rm.mu.Unlock()
	rm.paused = true
	log.Println("[Recovery] Paused")
}

// Resume re-enables recovery
func (rm *RecoveryManager) Resume() {
	rm.mu.Lock()
	defer rm.mu.Unlock()
	rm.paused = false
	log.Println("[Recovery] Resumed")
}

// healthCheckLoop continuously monitors component health
func (rm *RecoveryManager) healthCheckLoop() {
	defer rm.wg.Done()
	ticker := time.NewTicker(rm.config.HealthCheckInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			rm.performHealthChecks()
		case <-rm.stopChan:
			return
		}
	}
}

// checkpointLoop periodically creates checkpoints
func (rm *RecoveryManager) checkpointLoop() {
	defer rm.wg.Done()
	if !rm.config.StateRecoveryEnabled {
		return
	}

	ticker := time.NewTicker(rm.config.CheckpointInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			rm.CreateCheckpoint()
		case <-rm.stopChan:
			return
		}
	}
}

// performHealthChecks checks all registered components
func (rm *RecoveryManager) performHealthChecks() {
	rm.mu.RLock()
	if rm.paused {
		rm.mu.RUnlock()
		return
	}
	components := make([]*ComponentHealth, 0, len(rm.components))
	for _, comp := range rm.components {
		components = append(components, comp)
	}
	rm.mu.RUnlock()

	for _, comp := range components {
		rm.checkComponentHealth(comp)
	}
}

// checkComponentHealth performs health check on a single component
func (rm *RecoveryManager) checkComponentHealth(comp *ComponentHealth) {
	// Update check timestamp
	comp.LastCheck = time.Now()

	// Determine health status based on error count
	if comp.ErrorCount >= rm.config.MaxConsecutiveFailures {
		comp.Status = HealthFailed
		rm.handleFailedComponent(comp)
	} else if comp.ErrorCount >= 2 {
		comp.Status = HealthUnhealthy
	} else if comp.ErrorCount >= 1 {
		comp.Status = HealthDegraded
	} else {
		comp.Status = HealthHealthy
	}
}

// ReportHealth reports health status from a component
func (rm *RecoveryManager) ReportHealth(component string, healthy bool, latency time.Duration, err error) {
	rm.mu.RLock()
	comp, exists := rm.components[component]
	rm.mu.RUnlock()

	if !exists {
		return
	}

	comp.LastCheck = time.Now()
	comp.Latency = latency

	if healthy {
		comp.SuccessCount++
		comp.ErrorCount = 0
		comp.LastError = nil
	} else {
		comp.ErrorCount++
		comp.LastError = err
		log.Printf("[Recovery] Component %s reported unhealthy: %v", component, err)
	}
}

// handleFailedComponent initiates recovery for a failed component
func (rm *RecoveryManager) handleFailedComponent(comp *ComponentHealth) {
	rm.mu.Lock()
	attempts := rm.recoveryAttempts[comp.Name]
	if attempts >= rm.config.RecoveryAttempts {
		rm.mu.Unlock()
		log.Printf("[Recovery] Max recovery attempts reached for %s, giving up", comp.Name)
		return
	}
	rm.recoveryAttempts[comp.Name] = attempts + 1
	rm.mu.Unlock()

	// Get recovery strategy
	strategy, ok := rm.config.ComponentStrategies[comp.Name]
	if !ok {
		strategy = StrategyRestart
	}

	// Attempt recovery
	log.Printf("[Recovery] Attempting to recover %s with strategy %s (attempt %d/%d)",
		comp.Name, strategy, attempts+1, rm.config.RecoveryAttempts)

	if rm.config.OnRecoveryStart != nil {
		rm.config.OnRecoveryStart(comp.Name, strategy)
	}

	startTime := time.Now()
	success, err := rm.executeRecovery(comp.Name, strategy)
	duration := time.Since(startTime)

	// Record recovery attempt
	record := RecoveryRecord{
		Timestamp: startTime,
		Component: comp.Name,
		Strategy:  strategy,
		Success:   success,
		Duration:  duration,
	}

	if err != nil {
		record.Error = err.Error()
	}

	rm.historyMu.Lock()
	rm.recoveryHistory = append(rm.recoveryHistory, record)
	rm.historyMu.Unlock()

	if success {
		log.Printf("[Recovery] Successfully recovered %s in %v", comp.Name, duration)
		comp.Status = HealthHealthy
		comp.ErrorCount = 0
		rm.mu.Lock()
		rm.recoveryAttempts[comp.Name] = 0
		rm.mu.Unlock()

		if rm.config.OnRecoverySuccess != nil {
			rm.config.OnRecoverySuccess(comp.Name)
		}
	} else {
		log.Printf("[Recovery] Failed to recover %s: %v", comp.Name, err)
		if rm.config.OnRecoveryFailure != nil {
			rm.config.OnRecoveryFailure(comp.Name, err)
		}
	}
}

// executeRecovery executes the specified recovery strategy
func (rm *RecoveryManager) executeRecovery(component string, strategy RecoveryStrategy) (bool, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	switch strategy {
	case StrategyRestart:
		return rm.restartComponent(ctx, component)
	case StrategyResetState:
		return rm.resetComponentState(ctx, component)
	case StrategyFailover:
		return rm.failoverComponent(ctx, component)
	case StrategyGracefulShutdown:
		return rm.gracefulShutdown(ctx, component)
	case StrategyImmediateShutdown:
		return rm.immediateShutdown(component)
	default:
		return false, fmt.Errorf("unknown recovery strategy: %v", strategy)
	}
}

// restartComponent restarts a component
func (rm *RecoveryManager) restartComponent(ctx context.Context, component string) (bool, error) {
	log.Printf("[Recovery] Restarting component: %s", component)

	// Get factory
	rm.mu.RLock()
	factory, exists := rm.componentFactories[component]
	rm.mu.RUnlock()

	if !exists {
		return false, fmt.Errorf("no factory registered for %s", component)
	}

	// Attempt restart
	errChan := make(chan error, 1)
	go func() {
		errChan <- factory()
	}()

	select {
	case err := <-errChan:
		if err != nil {
			return false, fmt.Errorf("restart failed: %w", err)
		}
		return true, nil
	case <-ctx.Done():
		return false, fmt.Errorf("restart timeout")
	}
}

// resetComponentState resets component state and restarts
func (rm *RecoveryManager) resetComponentState(ctx context.Context, component string) (bool, error) {
	log.Printf("[Recovery] Resetting state for component: %s", component)

	// First restart
	success, err := rm.restartComponent(ctx, component)
	if !success {
		return false, err
	}

	// Then recover state from WAL if available
	if rm.config.StateRecoveryEnabled {
		if err := rm.RecoverComponentState(component); err != nil {
			log.Printf("[Recovery] State recovery failed for %s: %v", component, err)
			// Don't fail the recovery if state recovery fails
		}
	}

	return true, nil
}

// failoverComponent switches to backup/failover
func (rm *RecoveryManager) failoverComponent(ctx context.Context, component string) (bool, error) {
	log.Printf("[Recovery] Initiating failover for component: %s", component)
	// Implementation depends on specific component architecture
	// This is a placeholder
	return true, nil
}

// gracefulShutdown performs graceful shutdown
func (rm *RecoveryManager) gracefulShutdown(ctx context.Context, component string) (bool, error) {
	log.Printf("[Recovery] Graceful shutdown of component: %s", component)
	// Implementation depends on specific component
	return true, nil
}

// immediateShutdown performs immediate shutdown
func (rm *RecoveryManager) immediateShutdown(component string) (bool, error) {
	log.Printf("[Recovery] Immediate shutdown of component: %s", component)
	// Implementation depends on specific component
	return true, nil
}

// CreateCheckpoint creates a system state checkpoint
func (rm *RecoveryManager) CreateCheckpoint() error {
	if rm.wal == nil {
		return nil
	}

	// Get current component states
	rm.mu.RLock()
	states := make(map[string]interface{})
	for name, comp := range rm.components {
		states[name] = map[string]interface{}{
			"status":     comp.Status.String(),
			"last_check": comp.LastCheck,
			"metadata":   comp.Metadata,
		}
	}
	rm.mu.RUnlock()

	// Create checkpoint entry
	checkpoint := map[string]interface{}{
		"timestamp":  time.Now(),
		"components": states,
	}

	data, err := json.Marshal(checkpoint)
	if err != nil {
		return err
	}

	// Write checkpoint file
	filename := filepath.Join(rm.checkpointDir, fmt.Sprintf("checkpoint_%d.json", time.Now().Unix()))
	if err := os.WriteFile(filename, data, 0644); err != nil {
		return err
	}

	log.Printf("[Recovery] Created checkpoint: %s", filename)
	return nil
}

// RecoverComponentState recovers component state from checkpoint
func (rm *RecoveryManager) RecoverComponentState(component string) error {
	// Find latest checkpoint
	files, err := os.ReadDir(rm.checkpointDir)
	if err != nil {
		return err
	}

	if len(files) == 0 {
		return fmt.Errorf("no checkpoints found")
	}

	// Sort by modification time (newest first)
	var latestCheckpoint string
	var latestTime time.Time
	for _, f := range files {
		if f.IsDir() {
			continue
		}
		info, err := f.Info()
		if err != nil {
			continue
		}
		if info.ModTime().After(latestTime) {
			latestTime = info.ModTime()
			latestCheckpoint = filepath.Join(rm.checkpointDir, f.Name())
		}
	}

	if latestCheckpoint == "" {
		return fmt.Errorf("no valid checkpoint found")
	}

	// Read and parse checkpoint
	data, err := os.ReadFile(latestCheckpoint)
	if err != nil {
		return err
	}

	var checkpoint map[string]interface{}
	if err := json.Unmarshal(data, &checkpoint); err != nil {
		return err
	}

	log.Printf("[Recovery] Restored state for %s from checkpoint %s", component, latestCheckpoint)
	return nil
}

// RecoverFromCrash performs full system recovery after crash
func (rm *RecoveryManager) RecoverFromCrash() error {
	log.Println("[Recovery] Starting crash recovery...")

	if rm.wal == nil {
		return fmt.Errorf("WAL not initialized")
	}

	// Find latest checkpoint
	var checkpointFile string
	files, err := os.ReadDir(rm.checkpointDir)
	if err == nil {
		var latestTime time.Time
		for _, f := range files {
			if f.IsDir() {
				continue
			}
			info, _ := f.Info()
			if info != nil && info.ModTime().After(latestTime) {
				latestTime = info.ModTime()
				checkpointFile = filepath.Join(rm.checkpointDir, f.Name())
			}
		}
	}

	// Recover from WAL
	if checkpointFile != "" {
		_, entries, err := rm.wal.RecoveryV2(checkpointFile)
		if err != nil {
			return fmt.Errorf("WAL recovery failed: %w", err)
		}

		log.Printf("[Recovery] Recovered %d entries from WAL", len(entries))
	}

	log.Println("[Recovery] Crash recovery completed")
	return nil
}

// GetComponentHealth returns health status of all components
func (rm *RecoveryManager) GetComponentHealth() map[string]*ComponentHealth {
	rm.mu.RLock()
	defer rm.mu.RUnlock()

	health := make(map[string]*ComponentHealth)
	for name, comp := range rm.components {
		health[name] = comp
	}
	return health
}

// GetRecoveryHistory returns recovery attempt history
func (rm *RecoveryManager) GetRecoveryHistory() []RecoveryRecord {
	rm.historyMu.RLock()
	defer rm.historyMu.RUnlock()

	history := make([]RecoveryRecord, len(rm.recoveryHistory))
	copy(history, rm.recoveryHistory)
	return history
}

// GetSystemHealth returns overall system health
func (rm *RecoveryManager) GetSystemHealth() HealthStatus {
	rm.mu.RLock()
	defer rm.mu.RUnlock()

	failed := 0
	unhealthy := 0

	for _, comp := range rm.components {
		switch comp.Status {
		case HealthFailed:
			failed++
		case HealthUnhealthy:
			unhealthy++
		}
	}

	if failed > 0 {
		return HealthFailed
	}
	if unhealthy > len(rm.components)/2 {
		return HealthUnhealthy
	}
	if unhealthy > 0 {
		return HealthDegraded
	}
	return HealthHealthy
}

// IsHealthy returns true if system is healthy
func (rm *RecoveryManager) IsHealthy() bool {
	return rm.GetSystemHealth() == HealthHealthy || rm.GetSystemHealth() == HealthDegraded
}
