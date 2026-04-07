package main

import (
	"context"
	"fmt"
	"log"
	"math"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/fsnotify/fsnotify"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

/*
model_manager.go - ONNX Model Hot Reload System (P5-001)

Implements:
- Hot reloading of ONNX models without restart
- Model versioning and rollback support
- A/B testing framework for models
- Prediction latency monitoring
- Model health checking
- Performance decay detection
- Auto-rollback on performance degradation
- Online learning integration
*/

// Prometheus metrics for model manager
var (
	modelsLoaded = promauto.NewCounter(prometheus.CounterOpts{
		Name: "hft_model_manager_models_loaded_total",
		Help: "Total number of models loaded",
	})

	modelsReloaded = promauto.NewCounter(prometheus.CounterOpts{
		Name: "hft_model_manager_models_reloaded_total",
		Help: "Total number of models reloaded (hot reload)",
	})

	modelsUnloaded = promauto.NewCounter(prometheus.CounterOpts{
		Name: "hft_model_manager_models_unloaded_total",
		Help: "Total number of models unloaded",
	})

	modelPerformanceDecayDetected = promauto.NewCounter(prometheus.CounterOpts{
		Name: "hft_model_manager_decay_detected_total",
		Help: "Total number of performance decay events detected",
	})

	modelAutoRollback = promauto.NewCounter(prometheus.CounterOpts{
		Name: "hft_model_manager_auto_rollback_total",
		Help: "Total number of automatic rollbacks executed",
	})

	currentActiveModel = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "hft_model_manager_active_model",
		Help: "Currently active model version (0 for none)",
	})

	modelTotalPredictions = promauto.NewGaugeVec(prometheus.GaugeOpts{
		Name: "hft_model_predictions_total",
		Help: "Total number of predictions per model",
	}, []string{"model_id"})

	modelAverageLatencyMs = promauto.NewGaugeVec(prometheus.GaugeOpts{
		Name: "hft_model_average_latency_ms",
		Help: "Average prediction latency in milliseconds per model",
	}, []string{"model_id"})
)

// ModelType represents the type of ML model
type ModelType int

const (
	ModelTypeDQN ModelType = iota
	ModelTypePPO
	ModelTypeSAC
	ModelTypeCustom
)

func (mt ModelType) String() string {
	switch mt {
	case ModelTypeDQN:
		return "DQN"
	case ModelTypePPO:
		return "PPO"
	case ModelTypeSAC:
		return "SAC"
	case ModelTypeCustom:
		return "CUSTOM"
	default:
		return "UNKNOWN"
	}
}

// ModelVersion represents a specific model version
type ModelVersion struct {
	ID          string
	Name        string
	Version     string
	Path        string
	Type        ModelType
	LoadedAt    time.Time
	CheckSum    string
	Size        int64
	Metadata    map[string]interface{}
	Active      bool
	Performance ModelPerformance
}

// ModelPerformance tracks model inference metrics
type ModelPerformance struct {
	TotalPredictions uint64
	TotalPnL         float64       // Cumulative PnL from predictions
	TotalLatency     time.Duration
	Errors           uint64
	LastPrediction   time.Time
	AvgLatency       time.Duration
	P99Latency       time.Duration
}

// ModelABTestConfig holds A/B testing configuration for models
type ModelABTestConfig struct {
	Enabled     bool
	VariantA    string  // Model ID for variant A
	VariantB    string  // Model ID for variant B
	SplitRatio  float64 // 0.0 - 1.0, traffic to variant B
	StartTime   time.Time
	EndTime     *time.Time
	Description string
}

// ModelABTestResult tracks A/B test metrics for models
type ModelABTestResult struct {
	Variant           string
	Requests          uint64
	Errors            uint64
	AvgLatency        time.Duration
	TotalLatency      time.Duration
	LastRequestTime   time.Time
}

// ModelConfig holds model manager configuration
type ModelConfig struct {
	ModelDir           string
	WatchEnabled       bool
	WatchInterval      time.Duration
	MaxVersions        int
	HealthCheckInterval time.Duration
	ABTestEnabled      bool

	// Online learning / performance decay detection
	DecayDetectionEnabled    bool
	DecayThresholdPnL         float64   // Performance decay threshold (cumulative PnL drop)
	DecayThresholdSharpe       float64   // Sharpe ratio decay threshold
	MinSamplesForDecayCheck    int       // Minimum samples before checking decay
	AutoRollbackOnDecay        bool      // Auto rollback if decay detected
}

// DefaultModelConfig returns default configuration
func DefaultModelConfig() *ModelConfig {
	return &ModelConfig{
		ModelDir:             "./models",
		WatchEnabled:         true,
		WatchInterval:        5 * time.Second,
		MaxVersions:          5,
		HealthCheckInterval:  30 * time.Second,
		ABTestEnabled:        false,
		DecayDetectionEnabled: true,
		DecayThresholdPnL:    -0.05,  // -5% cumulative PnL decay triggers alert
		DecayThresholdSharpe: -0.3,   // 0.3 Sharpe drop triggers alert
		MinSamplesForDecayCheck:  50,
		AutoRollbackOnDecay:      true,
	}
}

// ModelManager manages ONNX models with hot reload support
type ModelManager struct {
	config    *ModelConfig
	models    map[string]*ModelVersion
	current   *ModelVersion
	mu        sync.RWMutex

	// Unique ID generation
	loadCounter uint64

	// A/B testing
	abTest    *ModelABTestConfig
	abResults map[string]*ModelABTestResult
	abMu      sync.RWMutex

	// File watching
	watcher   *fsnotify.Watcher
	watchStop chan struct{}

	// Health check
	healthStop chan struct{}
	wg         sync.WaitGroup

	// Callbacks
	onLoad    func(*ModelVersion)
	onUnload  func(*ModelVersion)
	onError   func(error)
}

// NewModelManager creates a new model manager
func NewModelManager(config *ModelConfig) (*ModelManager, error) {
	if config == nil {
		config = DefaultModelConfig()
	}

	// Create model directory if not exists
	if err := os.MkdirAll(config.ModelDir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create model dir: %w", err)
	}

	mm := &ModelManager{
		config:     config,
		models:     make(map[string]*ModelVersion),
		abResults:  make(map[string]*ModelABTestResult),
		watchStop:  make(chan struct{}),
		healthStop: make(chan struct{}),
	}

	// Initialize file watcher if enabled
	if config.WatchEnabled {
		watcher, err := fsnotify.NewWatcher()
		if err != nil {
			return nil, fmt.Errorf("failed to create watcher: %w", err)
		}
		mm.watcher = watcher

		// Watch model directory
		if err := watcher.Add(config.ModelDir); err != nil {
			watcher.Close()
			return nil, fmt.Errorf("failed to watch directory: %w", err)
		}
	}

	return mm, nil
}

// Start starts the model manager
func (mm *ModelManager) Start() {
	if mm.watcher != nil {
		mm.wg.Add(1)
		go mm.watchLoop()
	}

	mm.wg.Add(1)
	go mm.healthCheckLoop()

	log.Println("[ModelManager] Started")
}

// Stop stops the model manager
func (mm *ModelManager) Stop() {
	close(mm.watchStop)
	close(mm.healthStop)

	if mm.watcher != nil {
		mm.watcher.Close()
	}

	mm.wg.Wait()
	log.Println("[ModelManager] Stopped")
}

// watchLoop watches for model file changes
func (mm *ModelManager) watchLoop() {
	defer mm.wg.Done()

	if mm.watcher == nil {
		return
	}

	debounce := time.NewTimer(0)
	<-debounce.C
	var pendingFile string

	for {
		select {
		case event, ok := <-mm.watcher.Events:
			if !ok {
				return
			}
			if event.Op&fsnotify.Write == fsnotify.Write ||
				event.Op&fsnotify.Create == fsnotify.Create {
				if filepath.Ext(event.Name) == ".onnx" {
					pendingFile = event.Name
					debounce.Reset(500 * time.Millisecond)
				}
			}

		case err, ok := <-mm.watcher.Errors:
			if !ok {
				return
			}
			log.Printf("[ModelManager] Watch error: %v", err)
			if mm.onError != nil {
				mm.onError(err)
			}

		case <-debounce.C:
			if pendingFile != "" {
				mm.handleFileChange(pendingFile)
				pendingFile = ""
			}

		case <-mm.watchStop:
			return
		}
	}
}

// handleFileChange handles model file changes
func (mm *ModelManager) handleFileChange(path string) {
	filename := filepath.Base(path)
	name := filename[:len(filename)-len(filepath.Ext(filename))]

	log.Printf("[ModelManager] Detected model file change: %s", filename)

	// Load new version
	ctx := context.Background()
	if err := mm.LoadModel(ctx, name, path, ModelTypeCustom); err != nil {
		log.Printf("[ModelManager] Failed to hot reload model: %v", err)
		if mm.onError != nil {
			mm.onError(err)
		}
	} else {
		log.Printf("[ModelManager] Hot reloaded model: %s", name)
	}
}

// healthCheckLoop periodically checks model health
func (mm *ModelManager) healthCheckLoop() {
	defer mm.wg.Done()

	ticker := time.NewTicker(mm.config.HealthCheckInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			mm.performHealthCheck()
		case <-mm.healthStop:
			return
		}
	}
}

// performHealthCheck checks all loaded models
func (mm *ModelManager) performHealthCheck() {
	mm.mu.RLock()
	models := make([]*ModelVersion, 0, len(mm.models))
	for _, m := range mm.models {
		models = append(models, m)
	}
	mm.mu.RUnlock()

	for _, model := range models {
		// Check if model file still exists
		if _, err := os.Stat(model.Path); os.IsNotExist(err) {
			log.Printf("[ModelManager] Model file missing: %s", model.Path)
			model.Active = false
		}
	}
}

// LoadModel loads a model from file
func (mm *ModelManager) LoadModel(ctx context.Context, name, path string, modelType ModelType) error {
	mm.mu.Lock()
	defer mm.mu.Unlock()

	// Check if file exists
	info, err := os.Stat(path)
	if err != nil {
		return fmt.Errorf("model file not found: %w", err)
	}

	// Generate version ID (using nanoseconds + counter to ensure uniqueness)
	mm.loadCounter++
	versionID := fmt.Sprintf("%s_%d_%d", name, time.Now().UnixNano(), mm.loadCounter)

	// Create model version
	model := &ModelVersion{
		ID:       versionID,
		Name:     name,
		Version:  time.Now().Format("20060102-150405"),
		Path:     path,
		Type:     modelType,
		LoadedAt: time.Now(),
		Size:     info.Size(),
		Metadata: make(map[string]interface{}),
		Active:   true,
	}

	// Calculate checksum (simplified)
	data, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("failed to read model: %w", err)
	}
	model.CheckSum = fmt.Sprintf("%x", len(data)) // Simplified checksum

	// Store model
	mm.models[versionID] = model

	// Set as current if not set
	if mm.current == nil {
		mm.current = model
	}

	// Cleanup old versions
	mm.cleanupOldVersions(name)

	// Trigger callback
	if mm.onLoad != nil {
		mm.onLoad(model)
	}

	// Record metrics (if metrics collector is available)
	// Note: metrics will be recorded via callback to avoid global dependency

	log.Printf("[ModelManager] Loaded model %s version %s (size: %d bytes)",
		name, model.Version, model.Size)

	return nil
}

// UnloadModel unloads a specific model version
func (mm *ModelManager) UnloadModel(versionID string) error {
	mm.mu.Lock()
	defer mm.mu.Unlock()

	model, exists := mm.models[versionID]
	if !exists {
		return fmt.Errorf("model version not found: %s", versionID)
	}

	model.Active = false
	delete(mm.models, versionID)

	if mm.onUnload != nil {
		mm.onUnload(model)
	}

	log.Printf("[ModelManager] Unloaded model %s version %s", model.Name, model.Version)
	return nil
}

// SwitchModel switches to a specific model version
func (mm *ModelManager) SwitchModel(versionID string) error {
	mm.mu.Lock()
	defer mm.mu.Unlock()

	model, exists := mm.models[versionID]
	if !exists {
		return fmt.Errorf("model version not found: %s", versionID)
	}

	mm.current = model
	log.Printf("[ModelManager] Switched to model %s version %s", model.Name, model.Version)

	return nil
}

// GetCurrentModel returns the currently active model
func (mm *ModelManager) GetCurrentModel() *ModelVersion {
	mm.mu.RLock()
	defer mm.mu.RUnlock()
	return mm.current
}

// GetModel returns a specific model version
func (mm *ModelManager) GetModel(versionID string) *ModelVersion {
	mm.mu.RLock()
	defer mm.mu.RUnlock()
	return mm.models[versionID]
}

// ListModels returns all loaded models for a given name
func (mm *ModelManager) ListModels(name string) []*ModelVersion {
	mm.mu.RLock()
	defer mm.mu.RUnlock()

	var result []*ModelVersion
	for _, model := range mm.models {
		if model.Name == name {
			result = append(result, model)
		}
	}
	return result
}

// ListAllModels returns all loaded models
func (mm *ModelManager) ListAllModels() []*ModelVersion {
	mm.mu.RLock()
	defer mm.mu.RUnlock()

	result := make([]*ModelVersion, 0, len(mm.models))
	for _, model := range mm.models {
		result = append(result, model)
	}
	return result
}

// cleanupOldVersions removes old versions keeping only MaxVersions
func (mm *ModelManager) cleanupOldVersions(name string) {
	var versions []*ModelVersion
	for _, model := range mm.models {
		if model.Name == name {
			versions = append(versions, model)
		}
	}

	// Sort by loaded time (newest first)
	// Simplified - just keep last N
	if len(versions) > mm.config.MaxVersions {
		for i := mm.config.MaxVersions; i < len(versions); i++ {
			delete(mm.models, versions[i].ID)
			if mm.onUnload != nil {
				mm.onUnload(versions[i])
			}
		}
	}
}

// RecordPrediction records prediction metrics including PnL
func (mm *ModelManager) RecordPrediction(versionID string, latency time.Duration, pnl float64, err error) {
	mm.mu.Lock()
	model := mm.models[versionID]
	if model != nil {
		model.Performance.TotalPredictions++
		model.Performance.TotalPnL += pnl
		model.Performance.TotalLatency += latency
		model.Performance.LastPrediction = time.Now()
		if err != nil {
			model.Performance.Errors++
		}

		// Update average latency
		if model.Performance.TotalPredictions > 0 {
			model.Performance.AvgLatency =
				model.Performance.TotalLatency / time.Duration(model.Performance.TotalPredictions)
		}

		// Update Prometheus metrics
		modelTotalPredictions.WithLabelValues(versionID).Set(float64(model.Performance.TotalPredictions))
		modelAverageLatencyMs.WithLabelValues(versionID).Set(float64(model.Performance.AvgLatency.Seconds() * 1000))
	}
	mm.mu.Unlock()

	// Update Prometheus gauge for current active model
	if mm.current != nil {
		currentActiveModel.Set(1)
	} else {
		currentActiveModel.Set(0)
	}

	// Record A/B test metrics
	mm.abMu.Lock()
	if result, exists := mm.abResults[versionID]; exists {
		result.Requests++
		result.TotalLatency += latency
		result.LastRequestTime = time.Now()
		if err != nil {
			result.Errors++
		}
		if result.Requests > 0 {
			result.AvgLatency = result.TotalLatency / time.Duration(result.Requests)
		}
	}
	mm.abMu.Unlock()

	// Increment counters
	modelsLoaded.Inc()
}

// StartABTest starts an A/B test between two model versions
func (mm *ModelManager) StartABTest(config *ModelABTestConfig) error {
	if config == nil || !config.Enabled {
		return fmt.Errorf("invalid A/B test config")
	}

	mm.abMu.Lock()
	defer mm.abMu.Unlock()

	// Verify both models exist
	mm.mu.RLock()
	_, existsA := mm.models[config.VariantA]
	_, existsB := mm.models[config.VariantB]
	mm.mu.RUnlock()

	if !existsA {
		return fmt.Errorf("variant A model not found: %s", config.VariantA)
	}
	if !existsB {
		return fmt.Errorf("variant B model not found: %s", config.VariantB)
	}

	mm.abTest = config
	mm.abResults[config.VariantA] = &ModelABTestResult{Variant: "A"}
	mm.abResults[config.VariantB] = &ModelABTestResult{Variant: "B"}

	log.Printf("[ModelManager] Started A/B test: %s vs %s (split: %.2f)",
		config.VariantA, config.VariantB, config.SplitRatio)

	return nil
}

// StopABTest stops the current A/B test
func (mm *ModelManager) StopABTest() *ModelABTestConfig {
	mm.abMu.Lock()
	defer mm.abMu.Unlock()

	test := mm.abTest
	mm.abTest = nil

	if test != nil {
		log.Printf("[ModelManager] Stopped A/B test")
	}

	return test
}

// GetABTestConfig returns current A/B test config
func (mm *ModelManager) GetABTestConfig() *ModelABTestConfig {
	mm.abMu.RLock()
	defer mm.abMu.RUnlock()
	return mm.abTest
}

// GetABTestResults returns A/B test results
func (mm *ModelManager) GetABTestResults() map[string]*ModelABTestResult {
	mm.abMu.RLock()
	defer mm.abMu.RUnlock()

	result := make(map[string]*ModelABTestResult)
	for k, v := range mm.abResults {
		result[k] = v
	}
	return result
}

// SelectModelForPrediction selects which model to use for prediction
// Returns model ID and whether it's part of A/B test
func (mm *ModelManager) SelectModelForPrediction() (string, bool) {
	mm.abMu.RLock()
	abTest := mm.abTest
	mm.abMu.RUnlock()

	if abTest != nil && abTest.Enabled {
		// Simple random split based on ratio
		// In production, use consistent hashing based on request ID
		if time.Now().UnixNano()%100 < int64(abTest.SplitRatio*100) {
			return abTest.VariantB, true
		}
		return abTest.VariantA, true
	}

	mm.mu.RLock()
	defer mm.mu.RUnlock()

	if mm.current != nil {
		return mm.current.ID, false
	}

	return "", false
}

// SetCallbacks sets event callbacks
func (mm *ModelManager) SetCallbacks(onLoad, onUnload func(*ModelVersion), onError func(error)) {
	mm.onLoad = onLoad
	mm.onUnload = onUnload
	mm.onError = onError
}

// GetStats returns model manager statistics
func (mm *ModelManager) GetStats() map[string]any {
	mm.mu.RLock()
	mm.abMu.RLock()
	defer mm.mu.RUnlock()
	defer mm.abMu.RUnlock()

	activeCount := 0
	for _, m := range mm.models {
		if m.Active {
			activeCount++
		}
	}

	return map[string]any{
		"total_models":   len(mm.models),
		"active_models":  activeCount,
		"current_model":  mm.current,
		"ab_test_active": mm.abTest != nil,
		"watch_enabled":  mm.watcher != nil,
		"decay_detection_enabled": mm.config.DecayDetectionEnabled,
	}
}

// CheckPerformanceDecay checks if current model performance has decayed
// Returns true if decay detected and handled (rolled back)
func (mm *ModelManager) CheckPerformanceDecay() (bool, string) {
	if !mm.config.DecayDetectionEnabled {
		return false, "decay detection disabled"
	}

	mm.mu.Lock()
	defer mm.mu.Unlock()

	if mm.current == nil {
		return false, "no active model"
	}

	perf := &mm.current.Performance
	if perf.TotalPredictions < uint64(mm.config.MinSamplesForDecayCheck) {
		return false, fmt.Sprintf("not enough samples (%d < %d)",
			perf.TotalPredictions, mm.config.MinSamplesForDecayCheck)
	}

	// Find baseline (best performing previous version)
	var best *ModelVersion
	maxSharpe := -math.MaxFloat64

	for _, m := range mm.models {
		if m == mm.current || !m.Active {
			continue
		}

		// Compare based on average PnL as proxy for sharpe ratio
		if m.Performance.TotalPredictions > 0 {
			avgPnL := m.Performance.TotalPnL / float64(m.Performance.TotalPredictions)
			if avgPnL > maxSharpe {
				maxSharpe = avgPnL
				best = m
			}
		}
	}

	if best == nil {
		return false, "no alternative versions found"
	}

	// Check current model performance vs baseline
	current := mm.current
	currentAvg := float64(current.Performance.TotalPnL) / float64(current.Performance.TotalPredictions)
	bestAvg := float64(best.Performance.TotalPnL) / float64(best.Performance.TotalPredictions)

	decayPnL := currentAvg - bestAvg
	decaySharpe := currentAvg - bestAvg  // Using avg as proxy for sharpe

	if decayPnL >= mm.config.DecayThresholdPnL && decaySharpe >= mm.config.DecayThresholdSharpe {
		// No significant decay
		return false, fmt.Sprintf("no significant decay detected: current avg PnL %.6f, best avg PnL %.6f",
			currentAvg, bestAvg)
	}

	// Performance decay detected
	modelPerformanceDecayDetected.Inc()
	log.Printf("[ModelManager] Performance decay detected: current=%s (avg=%.6f), best=%s (avg=%.6f)",
		current.ID, currentAvg, best.ID, bestAvg)

	if !mm.config.AutoRollbackOnDecay {
		return true, "decay detected, auto-rollback disabled"
	}

	// Auto rollback to best version
	log.Printf("[ModelManager] Auto-rolling back to best version: %s", best.ID)
	err := mm.SwitchModel(best.ID)
	if err != nil {
		log.Printf("[ModelManager] Auto-rollback failed: %v", err)
		return true, fmt.Sprintf("decay detected, rollback failed: %v", err)
	}

	modelAutoRollback.Inc()
	return true, fmt.Sprintf("decay detected, auto-rolled back to %s", best.ID)
}

// GetPerformanceDecayStatus returns decay status for all models
func (mm *ModelManager) GetPerformanceDecayStatus() map[string]any {
	mm.mu.RLock()
	defer mm.mu.RUnlock()

	status := make(map[string]any)
	for id, m := range mm.models {
		perf := m.Performance
		status[id] = map[string]any{
			"active":            m.Active,
			"total_predictions": perf.TotalPredictions,
			"total_errors":      perf.Errors,
			"avg_latency_ms":    perf.AvgLatency.Seconds() * 1000,
			"p99_latency_ms":    perf.P99Latency.Seconds() * 1000,
		}
	}

	if mm.current != nil {
		status["current_model"] = mm.current.ID
	}

	status["decay_detection_enabled"] = mm.config.DecayDetectionEnabled
	return status
}

// TriggerReload triggers a manual reload of all models
func (mm *ModelManager) TriggerReload() error {
	log.Printf("[ModelManager] Triggering manual reload of all models")

	mm.mu.Lock()
	defer mm.mu.Unlock()

	// For manual reload, just re-add the directory watch
	// File change events will trigger individual model reloads
	if mm.watcher != nil {
		// Remove existing watch and re-add
		_ = mm.watcher.Remove(mm.config.ModelDir)
		if err := mm.watcher.Add(mm.config.ModelDir); err != nil {
			return fmt.Errorf("failed to re-add directory watch: %w", err)
		}
	}

	return nil
}
