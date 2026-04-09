package main

import (
	"math"
	"sync"
	"time"
)

// ReversalSignalIntegration integrates reversal signals into the execution pipeline
type ReversalSignalIntegration struct {
	reader          *ReversalSignalReader
	config          *ReversalIntegrationConfig
	lastSignal      *ReversalSignalSHM
	signalTimestamp time.Time
	mu              sync.RWMutex
}

// ReversalIntegrationConfig configures how reversal signals affect execution
type ReversalIntegrationConfig struct {
	Enabled               bool
	MinConfidence         float64
	MinSignalStrength     float64
	UrgencyBoostFactor    float64
	MaxSignalAgeMs        int
	ReverseOnStrongSignal bool
}

// DefaultReversalIntegrationConfig returns default config
func DefaultReversalIntegrationConfig() *ReversalIntegrationConfig {
	return &ReversalIntegrationConfig{
		Enabled:               true,
		MinConfidence:         0.6,
		MinSignalStrength:     0.3,
		UrgencyBoostFactor:    0.3,
		MaxSignalAgeMs:        500,
		ReverseOnStrongSignal: true,
	}
}

// NewReversalSignalIntegration creates a new integration
func NewReversalSignalIntegration(shmPath string, config *ReversalIntegrationConfig) (*ReversalSignalIntegration, error) {
	if config == nil {
		config = DefaultReversalIntegrationConfig()
	}

	reader, err := NewReversalSignalReader(shmPath)
	if err != nil {
		return nil, err
	}

	return &ReversalSignalIntegration{
		reader: reader,
		config: config,
	}, nil
}

// Update reads the latest signal from shared memory
func (ri *ReversalSignalIntegration) Update() bool {
	if !ri.config.Enabled {
		return false
	}

	signal, ok := ri.reader.ReadSignal()
	if !ok {
		return false
	}

	if !signal.IsValid(ri.config.MinConfidence, ri.config.MinSignalStrength) {
		return false
	}

	ri.mu.Lock()
	ri.lastSignal = signal
	ri.signalTimestamp = time.Now()
	ri.mu.Unlock()

	return true
}

// GetAdjustedUrgency adjusts base urgency based on reversal signal
func (ri *ReversalSignalIntegration) GetAdjustedUrgency(baseUrgency float64, side OrderSide) float64 {
	if !ri.config.Enabled {
		return baseUrgency
	}

	ri.mu.RLock()
	signal := ri.lastSignal
	age := time.Since(ri.signalTimestamp)
	ri.mu.RUnlock()

	if signal == nil {
		return baseUrgency
	}

	if age.Milliseconds() > int64(ri.config.MaxSignalAgeMs) {
		return baseUrgency
	}

	signalDirection := signal.GetDirection()
	sideValue := 1
	if side == SideSell {
		sideValue = -1
	}

	if signalDirection == sideValue {
		boost := signal.Confidence * math.Abs(signal.SignalStrength) * ri.config.UrgencyBoostFactor
		return math.Min(1.0, baseUrgency+boost)
	}

	if ri.config.ReverseOnStrongSignal && signal.Confidence > 0.8 {
		return baseUrgency * 0.5
	}

	return baseUrgency
}

// ShouldReversePosition checks if position should be reversed
func (ri *ReversalSignalIntegration) ShouldReversePosition(currentSide OrderSide) bool {
	if !ri.config.Enabled || !ri.config.ReverseOnStrongSignal {
		return false
	}

	ri.mu.RLock()
	signal := ri.lastSignal
	age := time.Since(ri.signalTimestamp)
	ri.mu.RUnlock()

	if signal == nil {
		return false
	}

	if age.Milliseconds() > int64(ri.config.MaxSignalAgeMs) {
		return false
	}

	if signal.Confidence < 0.8 || math.Abs(signal.SignalStrength) < 0.6 {
		return false
	}

	signalDirection := signal.GetDirection()
	currentDirection := 1
	if currentSide == SideSell {
		currentDirection = -1
	}

	return signalDirection == -currentDirection
}

// GetLastSignal returns the last received signal
func (ri *ReversalSignalIntegration) GetLastSignal() (*ReversalSignalSHM, time.Time) {
	ri.mu.RLock()
	defer ri.mu.RUnlock()
	return ri.lastSignal, ri.signalTimestamp
}

// Close closes the integration
func (ri *ReversalSignalIntegration) Close() error {
	if ri.reader != nil {
		return ri.reader.Close()
	}
	return nil
}

// GetStats returns reader statistics
func (ri *ReversalSignalIntegration) GetStats() map[string]interface{} {
	if ri.reader == nil {
		return map[string]interface{}{"enabled": false}
	}
	return ri.reader.GetStats()
}
