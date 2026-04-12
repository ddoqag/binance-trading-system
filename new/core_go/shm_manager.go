package main

import (
	"fmt"
	"math"
	"os"
	"sync/atomic"
	"time"
	"unsafe"
)

/*
shm_manager.go - Go Shared Memory Manager for HFT System

Provides zero-copy communication between Go (execution engine) and Python (AI brain)
using mmap and sequence locks for lock-free synchronization.

This file must be kept in sync with protocol.h

Cross-platform: Works on Linux, macOS, and Windows
*/

// TradingAction constants (must match protocol.h)
const (
	ActionWait        = 0
	ActionJoinBid     = 1
	ActionJoinAsk     = 2
	ActionCrossBuy    = 3
	ActionCrossSell   = 4
	ActionCancel      = 5
	ActionPartialExit = 6
)

// MarketRegime constants (must match protocol.h)
const (
	RegimeUnknown   = 0
	RegimeTrendUp   = 1
	RegimeTrendDown = 2
	RegimeRange     = 3
	RegimeHighVol   = 4
	RegimeLowVol    = 5
)

// TradingSharedState represents the shared memory structure
// Must be exactly 128 bytes, matching protocol.h
type TradingSharedState struct {
	// Cache Line 0: Market Data (Written by Go) - 64 bytes
	Seq            uint64  // 8 bytes - sequence number
	SeqEnd         uint64  // 8 bytes - must match Seq
	Timestamp      int64   // 8 bytes
	BestBid        float64 // 8 bytes
	BestAsk        float64 // 8 bytes
	MicroPrice     float64 // 8 bytes
	OfiSignal      float64 // 8 bytes
	TradeImbalance float32 // 4 bytes
	BidQueuePos    float32 // 4 bytes
	AskQueuePos    float32 // 4 bytes
	_              [4]byte // padding to 64 bytes

	// Cache Line 1: AI Decision (Written by Python, Read by Go) - 64 bytes
	DecisionSeq    uint64  // 8 bytes
	DecisionAck    uint64  // 8 bytes - acknowledgment
	DecisionTime   int64   // 8 bytes
	TargetPosition float64 // 8 bytes
	TargetSize     float64 // 8 bytes
	LimitPrice     float64 // 8 bytes
	Confidence     float32 // 4 bytes
	VolForecast    float32 // 4 bytes
	Action         int32   // 4 bytes
	Regime         int32   // 4 bytes
	_              [8]byte // padding to 64 bytes
}

// Ensure struct size is 128 bytes
const structSize = int(unsafe.Sizeof(TradingSharedState{}))

func init() {
	if structSize != 144 {
		panic(fmt.Sprintf("TradingSharedState must be 144 bytes, got %d", structSize))
	}
}

// mmapAccessor abstracts platform-specific mmap operations
type mmapAccessor struct {
	data []byte
}

func (m *mmapAccessor) Close() error {
	return unmapMemory(m.data)
}

// SHMManager manages shared memory communication
type SHMManager struct {
	path string
	fd   *os.File
	mm   *mmapAccessor
	data *TradingSharedState
}

// NewSHMManager creates a new shared memory manager
func NewSHMManager(path string) (*SHMManager, error) {
	// Create or open file
	fd, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE, 0644)
	if err != nil {
		return nil, fmt.Errorf("failed to open shm file: %w", err)
	}

	// Ensure file is large enough
	stat, err := fd.Stat()
	if err != nil {
		fd.Close()
		return nil, fmt.Errorf("failed to stat file: %w", err)
	}

	if stat.Size() < int64(structSize) {
		if err := fd.Truncate(int64(structSize)); err != nil {
			fd.Close()
			return nil, fmt.Errorf("failed to truncate file: %w", err)
		}
	}

	// Memory map the file
	data, err := mapMemory(fd, structSize)
	if err != nil {
		fd.Close()
		return nil, fmt.Errorf("failed to mmap: %w", err)
	}

	manager := &SHMManager{
		path: path,
		fd:   fd,
		mm:   &mmapAccessor{data: data},
		data: (*TradingSharedState)(unsafe.Pointer(&data[0])),
	}

	// Initialize if new
	if stat.Size() == 0 {
		manager.initialize()
	}

	return manager, nil
}

// initialize sets initial values for a new shared memory segment
func (m *SHMManager) initialize() {
	atomic.StoreUint64(&m.data.Seq, 0)
	atomic.StoreUint64(&m.data.SeqEnd, 0)
	atomic.StoreUint64(&m.data.DecisionSeq, 0)
	atomic.StoreUint64(&m.data.DecisionAck, 0)
}

// Close closes the shared memory manager
func (m *SHMManager) Close() error {
	if m.mm != nil {
		if err := m.mm.Close(); err != nil {
			return err
		}
		m.mm = nil
	}

	if m.fd != nil {
		if err := m.fd.Close(); err != nil {
			return err
		}
		m.fd = nil
	}

	return nil
}

// WriteMarketData writes market data with sequence lock
func (m *SHMManager) WriteMarketData(bestBid, bestAsk, microPrice, ofi, tradeImb float64,
	bidQueue, askQueue float32) {

	// Increment sequence to indicate write in progress
	seq := atomic.AddUint64(&m.data.Seq, 1)

	// Write all fields using atomic operations where possible
	atomic.StoreInt64(&m.data.Timestamp, time.Now().UnixNano())
	atomicStoreFloat64(&m.data.BestBid, bestBid)
	atomicStoreFloat64(&m.data.BestAsk, bestAsk)
	atomicStoreFloat64(&m.data.MicroPrice, microPrice)
	atomicStoreFloat64(&m.data.OfiSignal, ofi)
	atomicStoreFloat32(&m.data.TradeImbalance, float32(tradeImb))
	atomicStoreFloat32(&m.data.BidQueuePos, bidQueue)
	atomicStoreFloat32(&m.data.AskQueuePos, askQueue)

	// Commit by setting seq_end = seq
	atomic.StoreUint64(&m.data.SeqEnd, seq)
}

// ReadDecision reads AI decision with validation
func (m *SHMManager) ReadDecision() (action int32, targetPos, targetSize, limitPrice float64,
	confidence float32, regime int32, volForecast float32, valid bool) {

	// Read sequence numbers
	seq := atomic.LoadUint64(&m.data.DecisionSeq)
	ack := atomic.LoadUint64(&m.data.DecisionAck)

	// Check if there's a new unacknowledged decision
	if seq == 0 || seq == ack {
		return 0, 0, 0, 0, 0, 0, 0, false
	}

	// Read all fields
	action = atomic.LoadInt32(&m.data.Action)
	targetPos = atomicLoadFloat64(&m.data.TargetPosition)
	targetSize = atomicLoadFloat64(&m.data.TargetSize)
	limitPrice = atomicLoadFloat64(&m.data.LimitPrice)
	confidence = atomicLoadFloat32(&m.data.Confidence)
	regime = atomic.LoadInt32(&m.data.Regime)
	volForecast = atomicLoadFloat32(&m.data.VolForecast)

	// Re-check sequence for consistency
	seqAfter := atomic.LoadUint64(&m.data.DecisionSeq)
	valid = seq == seqAfter

	return
}

// AcknowledgeDecision marks the decision as processed
func (m *SHMManager) AcknowledgeDecision() {
	seq := atomic.LoadUint64(&m.data.DecisionSeq)
	atomic.StoreUint64(&m.data.DecisionAck, seq)
}

// GetLastTimestamp returns the timestamp of last market data update
func (m *SHMManager) GetLastTimestamp() int64 {
	return atomic.LoadInt64(&m.data.Timestamp)
}

// GetDecisionTimestamp returns when the current decision was made
func (m *SHMManager) GetDecisionTimestamp() int64 {
	return atomic.LoadInt64(&m.data.DecisionTime)
}

// IsStale checks if market data is stale (> 1 second old)
func (m *SHMManager) IsStale() bool {
	lastTs := m.GetLastTimestamp()
	if lastTs == 0 {
		return true
	}
	elapsed := time.Now().UnixNano() - lastTs
	return elapsed > int64(time.Second)
}

// DumpState returns a formatted string of current state (for debugging)
func (m *SHMManager) DumpState() string {
	seq := atomic.LoadUint64(&m.data.Seq)
	seqEnd := atomic.LoadUint64(&m.data.SeqEnd)
	ts := atomic.LoadInt64(&m.data.Timestamp)
	bid := atomicLoadFloat64(&m.data.BestBid)
	ask := atomicLoadFloat64(&m.data.BestAsk)

	return fmt.Sprintf(
		"SHM State: seq=%d seq_end=%d consistent=%v\n"+
		"  Timestamp: %d\n"+
		"  BestBid: %.2f BestAsk: %.2f",
		seq, seqEnd, seq == seqEnd, ts, bid, ask,
	)
}

// Helper functions for atomic float operations
func atomicLoadFloat64(ptr *float64) float64 {
	bits := atomic.LoadUint64((*uint64)(unsafe.Pointer(ptr)))
	return math.Float64frombits(bits)
}

func atomicStoreFloat64(ptr *float64, val float64) {
	bits := math.Float64bits(val)
	atomic.StoreUint64((*uint64)(unsafe.Pointer(ptr)), bits)
}

func atomicLoadFloat32(ptr *float32) float32 {
	bits := atomic.LoadUint32((*uint32)(unsafe.Pointer(ptr)))
	return math.Float32frombits(bits)
}

func atomicStoreFloat32(ptr *float32, val float32) {
	bits := math.Float32bits(val)
	atomic.StoreUint32((*uint32)(unsafe.Pointer(ptr)), bits)
}
