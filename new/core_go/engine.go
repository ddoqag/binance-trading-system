package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"
)

/*
engine.go - HFT Execution Engine Core

Main engine that coordinates:
- WebSocket data feed from Binance
- Shared memory communication with Python AI
- Order execution and management
- Risk management
*/

type HFTEngine struct {
	// Configuration
	symbol string
	config *EngineConfig

	// Subsystems
	shm      *SHMManager
	ws       *WebSocketClient
	executor *OrderExecutor
	riskMgr  *RiskManager

	// State
	inventory     float64
	unrealizedPnL float64
	lastDecision  time.Time
	decisionMu    sync.RWMutex

	// Control
	ctx    context.Context
	cancel context.CancelFunc
	wg     sync.WaitGroup
}

type EngineConfig struct {
	Symbol           string
	SHMPath          string
	MaxPosition      float64
	BaseOrderSize    float64
	HeartbeatMs      int
	PaperTrading     bool
}

func DefaultConfig(symbol string) *EngineConfig {
	// 从环境变量读取 SHM 路径，默认为 /tmp/hft_trading_shm
	shmPath := os.Getenv("HFT_SHM_PATH")
	if shmPath == "" {
		shmPath = "/tmp/hft_trading_shm"
	}

	return &EngineConfig{
		Symbol:        symbol,
		SHMPath:       shmPath,
		MaxPosition:   1.0,  // max 1 BTC position
		BaseOrderSize: 0.01, // 0.01 BTC per order
		HeartbeatMs:   100,
		PaperTrading:  true,
	}
}

func NewHFTEngine(config *EngineConfig) (*HFTEngine, error) {
	ctx, cancel := context.WithCancel(context.Background())

	// Initialize shared memory
	shm, err := NewSHMManager(config.SHMPath)
	if err != nil {
		cancel()
		return nil, fmt.Errorf("failed to initialize SHM: %w", err)
	}

	engine := &HFTEngine{
		symbol:   config.Symbol,
		config:   config,
		shm:      shm,
		ctx:      ctx,
		cancel:   cancel,
	}

	// Initialize WebSocket client (use testnet with proxy)
	engine.ws = NewTestnetWebSocketClient(config.Symbol)

	// Initialize order executor
	engine.executor = NewOrderExecutor(config.Symbol, config.PaperTrading)

	// Initialize risk manager
	engine.riskMgr = NewRiskManager(config.MaxPosition)

	return engine, nil
}

func (e *HFTEngine) Start() error {
	log.Printf("[ENGINE] Starting HFT Engine for %s", e.symbol)

	// Set up WebSocket handlers
	e.ws.SetDepthHandler(e.onDepthUpdate)
	e.ws.SetTradeHandler(e.onTradeUpdate)

	// Connect to Binance
	if err := e.ws.Connect(); err != nil {
		return fmt.Errorf("failed to connect WebSocket: %w", err)
	}

	// Start main loops
	e.wg.Add(3)
	go e.decisionLoop()
	go e.marketDataLoop()
	go e.monitorLoop()

	log.Println("[ENGINE] HFT Engine started successfully")
	return nil
}

func (e *HFTEngine) Stop() {
	log.Println("[ENGINE] Stopping HFT Engine...")
	e.cancel()
	e.ws.Close()
	e.wg.Wait()
	e.shm.Close()
	log.Println("[ENGINE] HFT Engine stopped")
}

func (e *HFTEngine) onDepthUpdate(bestBid, bestAsk float64, ofi float64) {
	// Calculate micro-price (volume-weighted mid)
	microPrice := (bestBid + bestAsk) / 2

	// Get queue positions (simplified - would need real queue tracking)
	bidQueuePos := float32(0.5)
	askQueuePos := float32(0.5)

	// Get trade imbalance from OFI calculator
	tradeImb := e.ws.GetOFI()

	// Write to shared memory
	e.shm.WriteMarketData(
		bestBid, bestAsk, microPrice,
		ofi, tradeImb,
		bidQueuePos, askQueuePos,
	)
}

func (e *HFTEngine) onTradeUpdate(price, qty float64, isBuyerMaker bool) {
	// Update position PnL if we have a position
	if e.inventory != 0 {
		if e.inventory > 0 {
			// Long position
			e.unrealizedPnL = (price - e.getEntryPrice()) * e.inventory
		} else {
			// Short position
			e.unrealizedPnL = (e.getEntryPrice() - price) * (-e.inventory)
		}

		// Update SHM with new PnL - disabled (fields removed from shared memory)
		// e.shm.UpdateInventory(e.inventory, e.unrealizedPnL)
	}
}

func (e *HFTEngine) decisionLoop() {
	defer e.wg.Done()

	ticker := time.NewTicker(time.Duration(e.config.HeartbeatMs) * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-e.ctx.Done():
			return
		case <-ticker.C:
			e.processDecision()
		}
	}
}

func (e *HFTEngine) processDecision() {
	// Read decision from Python AI
	action, targetPos, targetSize, limitPrice, confidence, regime, vol, valid :=
		e.shm.ReadDecision()

	// Suppress unused variable warnings
	_ = targetPos
	_ = regime
	_ = vol

	if !valid || confidence < 0.5 {
		return
	}

	// Record decision time
	e.decisionMu.Lock()
	e.lastDecision = time.Now()
	e.decisionMu.Unlock()

	// Check risk limits
	if !e.riskMgr.CanExecute(action, targetSize, e.inventory) {
		log.Printf("[RISK] Order blocked by risk manager: action=%d size=%.4f", action, targetSize)
		return
	}

	// Execute decision
	var err error
	switch action {
	case ActionJoinBid:
		err = e.executor.PlaceLimitBuy(limitPrice, targetSize)
	case ActionJoinAsk:
		err = e.executor.PlaceLimitSell(limitPrice, targetSize)
	case ActionCrossBuy:
		err = e.executor.PlaceMarketBuy(targetSize)
	case ActionCrossSell:
		err = e.executor.PlaceMarketSell(targetSize)
	case ActionCancel:
		err = e.executor.CancelAll()
	case ActionPartialExit:
		err = e.executor.PartialExit(e.inventory * 0.5)
	}

	if err != nil {
		log.Printf("[EXEC] Execution error: %v", err)
		return
	}

	// Acknowledge decision
	e.shm.AcknowledgeDecision()

	// Update inventory tracking
	if action == ActionCrossBuy || action == ActionJoinBid {
		e.inventory += targetSize
	} else if action == ActionCrossSell || action == ActionJoinAsk {
		e.inventory -= targetSize
	}

	log.Printf("[EXEC] Executed action=%d size=%.4f price=%.2f conf=%.2f",
		action, targetSize, limitPrice, confidence)
}

func (e *HFTEngine) marketDataLoop() {
	defer e.wg.Done()

	// This loop ensures we keep writing market data even if no depth updates
	ticker := time.NewTicker(50 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-e.ctx.Done():
			return
		case <-ticker.C:
			// Refresh market data if we have a valid book
			if e.ws.IsConnected() {
				book := e.ws.GetBook()
				if book != nil {
					bestBid, bestAsk, _, _ := book.GetSnapshot()
					if bestBid > 0 && bestAsk > 0 {
						// Re-write current state to keep timestamp fresh
						e.onDepthUpdate(bestBid, bestAsk, e.ws.GetOFI())
					}
				}
			}
		}
	}
}

func (e *HFTEngine) monitorLoop() {
	defer e.wg.Done()

	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-e.ctx.Done():
			return
		case <-ticker.C:
			// Log status
			connected := e.ws.IsConnected()
			stale := e.shm.IsStale()

			if !connected {
				log.Println("[MONITOR] WARNING: WebSocket not connected")
			}
			if stale {
				log.Println("[MONITOR] WARNING: Market data stale")
			}

			log.Printf("[MONITOR] connected=%v stale=%v inventory=%.4f unrealized=%.2f",
				connected, stale, e.inventory, e.unrealizedPnL)
		}
	}
}

func (e *HFTEngine) getEntryPrice() float64 {
	// Would track actual entry price from order history
	// For now, return current mid price
	book := e.ws.GetBook()
	if book != nil {
		bid, ask, _, _ := book.GetSnapshot()
		return (bid + ask) / 2
	}
	return 0
}

// GetStatus returns current engine status
func (e *HFTEngine) GetStatus() map[string]interface{} {
	e.decisionMu.RLock()
	lastDecision := e.lastDecision
	e.decisionMu.RUnlock()

	return map[string]interface{}{
		"symbol":         e.symbol,
		"connected":      e.ws.IsConnected(),
		"stale":          e.shm.IsStale(),
		"inventory":      e.inventory,
		"unrealized_pnl": e.unrealizedPnL,
		"last_decision":  lastDecision,
	}
}

// main is the entry point for the Go HFT Engine
func main() {
	// Parse command line args
	symbol := "btcusdt"
	if len(os.Args) > 1 {
		symbol = os.Args[1]
	}

	paperTrading := true
	if len(os.Args) > 2 && os.Args[2] == "live" {
		paperTrading = false
	}

	// Create engine
	config := DefaultConfig(symbol)
	config.PaperTrading = paperTrading

	engine, err := NewHFTEngine(config)
	if err != nil {
		log.Fatalf("Failed to create engine: %v", err)
	}

	// Start engine
	if err := engine.Start(); err != nil {
		log.Fatalf("Failed to start engine: %v", err)
	}

	// Wait for interrupt
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	<-sigChan

	// Graceful shutdown
	engine.Stop()
}
