// queue_dynamics.go
// P3-002 Queue Dynamics v3 Core Engine
// Hazard Rate based probability filling model
//
// Implements:
//   - HazardRateModel: λ = base × exp(-α·queue_ratio) × (1 + β·OFI) × (1 + γ·trade_intensity)
//   - QueuePositionTracker: Real-time queue position tracking
//   - AdverseSelectionDetector: Toxic flow detection
//   - PartialFillModel: Partial fill probability modeling
//

package main

import (
	"math"
	"sync"
	"time"
)

// HazardRateModel implements the hazard rate probability model
//
// λ = base_rate × exp(-α × queue_ratio) × (1 + β × OFI) × (1 + γ × trade_intensity)
// P(fill in dt) = 1 - exp(-λ × dt)
type HazardRateModel struct {
	BaseRate      float64 // 基础成交率 (per second)
	Alpha         float64 // 队列位置衰减系数
	Beta          float64 // OFI 影响系数
	Gamma         float64 // 交易强度影响系数
}

// DefaultHazardRateModel returns default parameters
func DefaultHazardRateModel() *HazardRateModel {
	// Typical calibrated values
	return &HazardRateModel{
		BaseRate: 2.0,   // 2.0 per second = 50% chance to fill in 0.35s
		Alpha:    3.0,   // 强衰减：queue_ratio=1 → exp(-3) ≈ 0.05 → 5% of base rate
		Beta:     1.0,   // OFI=+1 → 2x rate, OFI=-1 → 0x rate
		Gamma:    0.5,   // 交易强度影响温和
	}
}

// Compute calculates current hazard rate
func (m *HazardRateModel) Compute(queueRatio, ofi, tradeIntensity float64) float64 {
	// Clamp inputs
	queueRatio = clamp(queueRatio, 0.0, 1.0)
	ofi = clamp(ofi, -1.0, 1.0)
	tradeIntensity = clamp(tradeIntensity, 0.0, 10.0)

	lambda := m.BaseRate *
		math.Exp(-m.Alpha*queueRatio) *
		(1.0 + m.Beta*ofi) *
		(1.0 + m.Gamma*tradeIntensity)

	// Ensure non-negative
	return math.Max(lambda, 1e-9)
}

// FillProbability computes probability of filling within dt seconds
func (m *HazardRateModel) FillProbability(lambda, dt float64) float64 {
	return 1.0 - math.Exp(-lambda*dt)
}

// QueuePositionTracker tracks the current position of an order in the queue
//
// Updates when new orders arrive at the same price level
type QueuePositionTracker struct {
	// For each price level, track total quantity and our position
	positions map[float64]*QueueLevel
	mu         sync.RWMutex
}

// QueueLevel represents a single price level's queue state
type QueueLevel struct {
	TotalQuantity float64   // Total quantity at this price
	OurQuantity   float64   // Our quantity at this price
	OurPosition   float64   // Current position (cumulative quantity before our order)
	LastUpdate    time.Time // Last update time
}

// NewQueuePositionTracker creates a new tracker
func NewQueuePositionTracker() *QueuePositionTracker {
	return &QueuePositionTracker{
		positions: make(map[float64]*QueueLevel),
	}
}

// UpdateOnArrival updates when a new order arrives at this price level
func (t *QueuePositionTracker) UpdateOnArrival(price float64, qty float64, isOur bool) {
	t.mu.Lock()
	defer t.mu.Unlock()

	level, exists := t.positions[price]
	if !exists {
		level = &QueueLevel{
			TotalQuantity: 0,
			OurQuantity:   0,
			OurPosition:   0,
			LastUpdate:    time.Now(),
		}
		t.positions[price] = level
	}

	level.TotalQuantity += qty
	level.LastUpdate = time.Now()

	if !isOur {
		// New order ahead of us? No - FIFO: new orders go to the end
		// If we already have quantity at this level, new orders go after us
		// So our position doesn't change
	} else {
		// Our order arrives - our position is after all existing quantity
		level.OurQuantity += qty
		// Our position is whatever was there before we arrived
	}
}

// GetQueueRatio returns the queue position ratio for our order
// ratio = (quantity before us) / total quantity → [0, 1]
func (t *QueuePositionTracker) GetQueueRatio(price float64) float64 {
	t.mu.RLock()
	defer t.mu.RUnlock()

	level, exists := t.positions[price]
	if !exists || level.TotalQuantity <= 0 {
		return 0.0 // No queue → we're first
	}

	ratio := level.OurPosition / level.TotalQuantity
	return clamp(ratio, 0.0, 1.0)
}

// OnFill updates queue when some quantity gets filled
func (t *QueuePositionTracker) OnFill(price float64, filledQty float64, isOur bool) {
	t.mu.Lock()
	defer t.mu.Unlock()

	level, exists := t.positions[price]
	if !exists {
		return
	}

	// Fills happen from front to back (FIFO)
	if !isOur {
		// Someone ahead of us got filled → our position improves
		if filledQty >= level.OurPosition {
			level.OurPosition = 0
		} else {
			level.OurPosition -= filledQty
		}
	} else {
		// We got filled partially
		level.OurQuantity -= filledQty
	}

	level.TotalQuantity -= filledQty
	level.LastUpdate = time.Now()

	// Cleanup if empty
	if level.TotalQuantity <= 0 {
		delete(t.positions, price)
	}
}

// RemoveOrder removes our order from the tracker (canceled)
func (t *QueuePositionTracker) RemoveOrder(price float64, qty float64) {
	t.mu.Lock()
	defer t.mu.Unlock()

	level, exists := t.positions[price]
	if !exists {
		return
	}

	level.TotalQuantity -= qty
	level.OurQuantity -= qty

	if level.TotalQuantity <= 0 {
		delete(t.positions, price)
	}
}

// Clear clears all tracking (new trading day)
func (t *QueuePositionTracker) Clear() {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.positions = make(map[float64]*QueueLevel)
}

// AdverseSelectionDetector detects toxic flow (adverse selection)
//
// Toxic flow = you get filled and then price immediately goes against you
//   - Buy filled → price drops (you bought high)
//   - Sell filled → price rises (you sold low)
type AdverseSelectionDetector struct {
	windowSize       int
	lookaheadMs      int
	adverseThreshold float64
	recentFills      []AdverseEvent
	mu               sync.RWMutex
}

// AdverseEvent records an adverse selection event
type AdverseEvent struct {
	Timestamp   time.Time
	Side        int // 1=buy, 2=sell
	FillPrice   float64
	FuturePrice float64
	AdverseCost float64 // positive = adverse
}

// NewAdverseSelectionDetector creates a new detector
func NewAdverseSelectionDetector(windowSize int, lookaheadMs int, threshold float64) *AdverseSelectionDetector {
	return &AdverseSelectionDetector{
		windowSize:       windowSize,
		lookaheadMs:      lookaheadMs,
		adverseThreshold: threshold,
		recentFills:      make([]AdverseEvent, 0, windowSize),
	}
}

// DefaultAdverseSelectionDetector returns default settings
func DefaultAdverseSelectionDetector() *AdverseSelectionDetector {
	return NewAdverseSelectionDetector(20, 5000, 0.3)
}

// RecordFill records a fill for later adverse calculation
func (d *AdverseSelectionDetector) RecordFill(side int, fillPrice float64) int {
	d.mu.Lock()
	defer d.mu.Unlock()

	event := AdverseEvent{
		Timestamp:   time.Now(),
		Side:        side,
		FillPrice:   fillPrice,
		FuturePrice: 0,
		AdverseCost: 0,
	}

	d.recentFills = append(d.recentFills, event)

	// Trim window
	if len(d.recentFills) > d.windowSize {
		d.recentFills = d.recentFills[1:]
	}

	return len(d.recentFills) - 1
}

// UpdateFuturePrice updates the future price and calculates adverse cost
func (d *AdverseSelectionDetector) UpdateFuturePrice(idx int, futurePrice float64) {
	d.mu.Lock()
	defer d.mu.Unlock()

	if idx < 0 || idx >= len(d.recentFills) {
		return
	}

	event := &d.recentFills[idx]
	event.FuturePrice = futurePrice

	// Calculate adverse cost
	// Buy: adverse = fill_price - future_price → positive = price went down after we bought
	// Sell: adverse = future_price - fill_price → positive = price went up after we sold
	if event.Side == 1 { // Buy
		event.AdverseCost = event.FillPrice - futurePrice
	} else { // Sell
		event.AdverseCost = futurePrice - event.FillPrice
	}

	// Normalize by price
	if event.FillPrice > 0 {
		event.AdverseCost /= event.FillPrice
	}
}

// GetAverageAdverseScore returns average adverse cost over recent fills
func (d *AdverseSelectionDetector) GetAverageAdverseScore() float64 {
	d.mu.RLock()
	defer d.mu.RUnlock()

	if len(d.recentFills) == 0 {
		return 0.0
	}

	sum := 0.0
	count := 0
	for _, event := range d.recentFills {
		if event.FuturePrice > 0 { // Only count events with future price
			sum += event.AdverseCost
			count++
		}
	}

	if count == 0 {
		return 0.0
	}

	return sum / float64(count)
}

// IsToxicFlow checks if we're currently in toxic flow environment
func (d *AdverseSelectionDetector) IsToxicFlow() bool {
	avg := d.GetAverageAdverseScore()
	return avg > d.adverseThreshold
}

// GetToxicProbability estimates probability of toxic flow
func (d *AdverseSelectionDetector) GetToxicProbability() float64 {
	avg := d.GetAverageAdverseScore()
	// Sigmoid mapping
	return 1.0 / (1.0 + math.Exp(-(avg - d.adverseThreshold) * 10.0))
}

// Clear clears all recorded events
func (d *AdverseSelectionDetector) Clear() {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.recentFills = make([]AdverseEvent, 0, d.windowSize)
}

// PartialFillModel models partial fills - how much gets filled
//
// Uses exponential distribution for filled quantity
type PartialFillModel struct {
	ExpectedFillRatio float64 // Expected fraction filled when a fill happens
	MinFillRatio      float64 // Minimum fraction
	MaxFillRatio      float64 // Maximum fraction
}

// NewPartialFillModel creates a new model
func NewPartialFillModel(expectedFillRatio, minFill, maxFill float64) *PartialFillModel {
	return &PartialFillModel{
		ExpectedFillRatio: expectedFillRatio,
		MinFillRatio:      minFill,
		MaxFillRatio:      maxFill,
	}
}

// DefaultPartialFillModel returns default settings
func DefaultPartialFillModel() *PartialFillModel {
	return NewPartialFillModel(0.3, 0.05, 1.0)
}

// SampleFillSize samples a filled size given total order size
// Returns the filled quantity
func (m *PartialFillModel) SampleFillSize(totalSize float64, queuePressure float64) float64 {
	// Higher queue pressure → higher chance of larger fill
	// Exponential distribution: P(fill < x) = 1 - exp(-λx)
	// λ = 1 / mean → mean = 1/λ

	mean := m.ExpectedFillRatio * (1.0 + queuePressure*0.5)
	mean = clamp(mean, m.MinFillRatio, m.MaxFillRatio)

	// Sample from exponential: -mean * ln(U)
	// In practice, use uniform for now for simplicity
	// TODO: proper exponential sampling
	u := uniformRandom()
	fillRatio := mean * (-math.Log(u))
	fillRatio = clamp(fillRatio, m.MinFillRatio, m.MaxFillRatio)

	return fillRatio * totalSize
}

// QueueDynamicsEngine combines all components
type QueueDynamicsEngine struct {
	HazardModel    *HazardRateModel
	PositionTracker *QueuePositionTracker
	AdverseDetector *AdverseSelectionDetector
	PartialModel    *PartialFillModel
}

// NewQueueDynamicsEngine creates a new engine with default settings
func NewQueueDynamicsEngine() *QueueDynamicsEngine {
	return &QueueDynamicsEngine{
		HazardModel:     DefaultHazardRateModel(),
		PositionTracker: NewQueuePositionTracker(),
		AdverseDetector: DefaultAdverseSelectionDetector(),
		PartialModel:    DefaultPartialFillModel(),
	}
}

// ComputeHazardRate computes current hazard rate
func (e *QueueDynamicsEngine) ComputeHazardRate(price float64, ofi float64, tradeIntensity float64) float64 {
	queueRatio := e.PositionTracker.GetQueueRatio(price)
	return e.HazardModel.Compute(queueRatio, ofi, tradeIntensity)
}

// ComputeFillProbability computes fill probability for the next dt
func (e *QueueDynamicsEngine) ComputeFillProbability(price float64, ofi float64, tradeIntensity float64, dt float64) float64 {
	lambda := e.ComputeHazardRate(price, ofi, tradeIntensity)
	return e.HazardModel.FillProbability(lambda, dt)
}

// SampleFill samples whether a fill happens and how much
func (e *QueueDynamicsEngine) SampleFill(price float64, ofi float64, tradeIntensity float64, dt float64, totalSize float64, queuePressure float64) (bool, float64) {
	prob := e.ComputeFillProbability(price, ofi, tradeIntensity, dt)
	u := uniformRandom()

	if u > prob {
		return false, 0.0
	}

	filledSize := e.PartialModel.SampleFillSize(totalSize, queuePressure)
	return true, filledSize
}

// GetAdverseScore gets current adverse selection score
func (e *QueueDynamicsEngine) GetAdverseScore() float64 {
	return e.AdverseDetector.GetAverageAdverseScore()
}

// GetToxicProbability gets current toxic flow probability
func (e *QueueDynamicsEngine) GetToxicProbability() float64 {
	return e.AdverseDetector.GetToxicProbability()
}

// IsToxic checks if current environment is toxic
func (e *QueueDynamicsEngine) IsToxic() bool {
	return e.AdverseDetector.IsToxicFlow()
}

// Clear resets all tracking for new day
func (e *QueueDynamicsEngine) Clear() {
	e.PositionTracker.Clear()
	e.AdverseDetector.Clear()
}

// Helper functions

func clamp(x, minVal, maxVal float64) float64 {
	if x < minVal {
		return minVal
	}
	if x > maxVal {
		return maxVal
	}
	return x
}

// simple uniform random using global seed
// for proper production use, use proper random source
var uniformSeed = time.Now().UnixNano()

func uniformRandom() float64 {
	// LCG
	uniformSeed = uniformSeed*1664525 + 1013904223
	return float64(uniformSeed&0x7FFFFFFF) / float64(0x7FFFFFFF)
}
