package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"math"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"runtime"
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
	shm            *SHMManager
	apiClient      *LiveAPIClient
	wsManager      *WebSocketManager
	executor       *OrderExecutor
	marginExecutor *MarginExecutor // 杠杆交易执行器
	riskMgr        *RiskManager
	wal            *WAL // Write-ahead logging
	degradeMgr     *EnhancedDegradeManager // System degradation and circuit breaker
	metrics        *MetricsCollector // Prometheus metrics collector

	// WebSocket handlers
	depthHandler   func(bestBid, bestAsk float64, ofi float64)
	tradeHandler   func(price, qty float64, isBuyerMaker bool)

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
	UseMargin        bool    // 使用杠杆交易
	MaxLeverage      float64 // 最大杠杆倍数
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
		UseMargin:     false, // 默认不使用杠杆
		MaxLeverage:   3.0,   // 默认3倍杠杆
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
		metrics:  NewMetricsCollector(DefaultMetricsConfig()),
	}

	// Initialize WebSocket manager with LiveAPIClient
	engine.wsManager = NewWebSocketManager(config.Symbol, nil) // Will set apiClient after creation

	// Initialize order executor
	apiKey := os.Getenv("BINANCE_API_KEY")
	apiSecret := os.Getenv("BINANCE_API_SECRET")
	logDir := os.Getenv("HFT_LOG_DIR")
	if logDir == "" {
		logDir = "./logs"
	}
	engine.executor = NewOrderExecutor(config.Symbol, config.PaperTrading, apiKey, apiSecret, logDir)

	// Initialize margin executor if enabled
	if config.UseMargin {
		engine.marginExecutor = NewMarginExecutor(config.Symbol, config.PaperTrading, apiKey, apiSecret, config.MaxLeverage, engine.wsManager)
		log.Printf("[ENGINE] Margin trading enabled with %.1fx leverage", config.MaxLeverage)
	}

	// Initialize risk manager
	engine.riskMgr = NewRiskManager(config.MaxPosition)

	// Register kill switch callbacks for emergency stop
	engine.riskMgr.RegisterKillSwitchCallback(func() {
		if err := engine.executor.CancelAll(); err != nil {
			log.Printf("[RISK] Failed to cancel all orders: %v", err)
		}
		log.Println("[RISK] Kill switch: all open orders cancelled")
	})

	if config.UseMargin && engine.marginExecutor != nil {
		engine.riskMgr.RegisterKillSwitchCallback(func() {
			if err := engine.marginExecutor.ClosePosition(true); err != nil {
				log.Printf("[RISK] Failed to close margin position: %v", err)
			} else {
				log.Println("[RISK] Kill switch: margin position closed")
			}
		})
	}

	// Initialize WAL for disaster recovery
	walDir := os.Getenv("HFT_WAL_DIR")
	if walDir == "" {
		walDir = filepath.Join(logDir, "wal")
	}
	wal, err := NewWAL(walDir)
	if err != nil {
		cancel()
		return nil, fmt.Errorf("failed to initialize WAL: %w", err)
	}
	engine.wal = wal

	// Initialize degradation manager (system protection)
	degradeConfig := DefaultDegradeConfig()
	engine.degradeMgr = NewEnhancedDegradeManager(degradeConfig)

	// Start degradation monitoring
	engine.degradeMgr.Start()

	log.Printf("[ENGINE] Degradation manager started with default config")

	return engine, nil
}

func (e *HFTEngine) Start() error {
	log.Printf("[ENGINE] Starting HFT Engine for %s", e.symbol)

	// Set up WebSocket handlers
	e.wsManager.SetDepthHandler(e.onDepthUpdate)
	e.wsManager.SetTradeHandler(e.onTradeUpdate)

	// Connect to Binance
	if err := e.wsManager.Connect(); err != nil {
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

	// Create final checkpoint before shutdown
	if e.wal != nil {
		positions := map[string]PositionEntry{
			e.symbol: {
				Symbol:      e.symbol,
				Size:        e.inventory,
				AvgPrice:    e.getEntryPrice(),
				RealizedPnL: 0, // Would track actual realized PnL
			},
		}
		if _, err := e.wal.CreateCheckpoint(positions, 0, e.unrealizedPnL); err != nil {
			log.Printf("[WAL] Failed to create shutdown checkpoint: %v", err)
		}
		e.wal.Close()
	}

	e.cancel()
	e.wsManager.Close()

	// Close margin executor if active
	if e.marginExecutor != nil {
		e.marginExecutor.Close()
	}

	e.wg.Wait()
	e.degradeMgr.Stop()
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
	tradeImb := e.wsManager.GetOFI()

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

	// Check degradation: can we place this order?
	// Determine if this is a closing order
	isClosing := false
	switch action {
	case ActionCancel, ActionPartialExit:
		isClosing = true
	}

	if !e.degradeMgr.CanTrade(isClosing) {
		log.Printf("[DEGRADE] Order blocked by degradation manager: level=%s",
			e.degradeMgr.GetCurrentLevel().String())
		return
	}

	// Get adjusted maximum position size
	maxPos := e.degradeMgr.GetMaxPositionSize(e.config.MaxPosition)
	if targetSize > maxPos && !isClosing {
		log.Printf("[DEGRADE] Position size reduced: original=%.4f adjusted=%.4f",
			targetSize, maxPos)
		targetSize = maxPos
		if targetSize <= 0 {
			return
		}
	}

	// Check risk limits
	if !e.riskMgr.CanExecute(action, targetSize, e.inventory) {
		log.Printf("[RISK] Order blocked by risk manager: action=%d size=%.4f", action, targetSize)
		return
	}

	// Execute decision
	var err error
	if e.config.UseMargin && e.marginExecutor != nil {
		// Use margin trading executor
		err = e.executeMarginDecision(action, targetSize, limitPrice)
	} else {
		// Use regular spot executor
		err = e.executeSpotDecision(action, targetSize, limitPrice)
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
			if e.wsManager.IsConnected() {
				book := e.wsManager.GetBook()
				if book != nil {
					bestBid, bestAsk, _, _ := book.GetSnapshot()
					if bestBid > 0 && bestAsk > 0 {
						// Re-write current state to keep timestamp fresh
						e.onDepthUpdate(bestBid, bestAsk, e.wsManager.GetOFI())
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
			connected := e.wsManager.IsConnected()
			stale := e.shm.IsStale()

			if !connected {
				log.Println("[MONITOR] WARNING: WebSocket not connected")
			}
			if stale {
				log.Println("[MONITOR] WARNING: Market data stale")
			}

			// Collect system metrics for degradation manager
			var m runtime.MemStats
			runtime.ReadMemStats(&m)

			openOrders := len(e.executor.GetOrders())
			if e.config.UseMargin && e.marginExecutor != nil {
				openOrders += len(e.marginExecutor.GetOpenOrders())
			}

			metrics := &SystemMetrics{
				Timestamp:        time.Now(),
				ErrorRate:        0.0, // Would be updated by API client
				DailyDrawdown:     0.0, // Would be calculated from daily PnL
				CPUUsage:          0.0, // runtime does not provide CPU usage; use gopsutil for production
				MemoryUsage:       float64(m.Alloc) / (1024 * 1024 * 1024), // GB used
				OpenOrders:        openOrders,
				PositionCount:     0,
				WebSocketLatency:   0,
				RateLimitHits:      0,
				CircuitBreakerOpen: 0,
			}

			// Update metrics in degradation manager
			e.degradeMgr.UpdateMetrics(metrics)

			// Update Prometheus margin metrics if margin enabled
			if e.config.UseMargin && e.marginExecutor != nil && e.metrics != nil {
				pos := e.marginExecutor.GetPosition()
				if pos.Position != 0 {
					// Calculate margin usage ratio based on position size and leverage
					// marginUsage = (position_size * entry_price) / (available_margin + position_size * entry_price / maxLeverage)
					currentPrice := e.marginExecutor.GetCurrentPrice()
					notional := math.Abs(pos.Position) * currentPrice
					marginRequired := notional / e.config.MaxLeverage
					if pos.AvailableMargin + pos.Margin > 0 {
						marginUsage := marginRequired / (pos.AvailableMargin + pos.Margin)
						e.metrics.SetMarginUsage(marginUsage)
					}
				} else {
					e.metrics.SetMarginUsage(0)
				}

				// Log liquidation risk warning
				if e.marginExecutor.HasLiquidationRisk() {
					log.Printf("[MONITOR] WARNING: Liquidation risk detected in margin position")
				}
			}

			// Current degradation level
			level := e.degradeMgr.GetCurrentLevel()
			if level != LevelNormal {
				log.Printf("[DEGRADE] Current degradation level: %s", level.String())
			}

			if e.config.UseMargin && e.marginExecutor != nil {
				pos := e.marginExecutor.GetPosition()
				log.Printf("[MONITOR] connected=%v stale=%v inventory=%.4f unrealized=%.2f degrade=%s margin_position=%.4f margin_pnl=%.2f liq_price=%.2f risk=%v",
					connected, stale, e.inventory, e.unrealizedPnL, level.String(),
					pos.Position, pos.UnrealizedPnL, pos.LiquidationPrice, e.marginExecutor.HasLiquidationRisk())
			} else {
				log.Printf("[MONITOR] connected=%v stale=%v inventory=%.4f unrealized=%.2f degrade=%s",
					connected, stale, e.inventory, e.unrealizedPnL, level.String())
			}
		}
	}
}

// executeSpotDecision 执行现货交易决策
func (e *HFTEngine) executeSpotDecision(action int32, targetSize float64, limitPrice float64) error {
	switch action {
	case ActionJoinBid:
		return e.executor.PlaceLimitBuy(limitPrice, targetSize)
	case ActionJoinAsk:
		return e.executor.PlaceLimitSell(limitPrice, targetSize)
	case ActionCrossBuy:
		return e.executor.PlaceMarketBuy(targetSize)
	case ActionCrossSell:
		return e.executor.PlaceMarketSell(targetSize)
	case ActionCancel:
		return e.executor.CancelAll()
	case ActionPartialExit:
		return e.executor.PartialExit(e.inventory * 0.5)
	default:
		return fmt.Errorf("unknown action: %d", action)
	}
}

// executeMarginDecision 执行杠杆交易决策
func (e *HFTEngine) executeMarginDecision(action int32, targetSize float64, limitPrice float64) error {
	switch action {
	case ActionJoinBid, ActionCrossBuy:
		// 做多：买入基础资产
		isMarket := action == ActionCrossBuy
		return e.marginExecutor.PlaceLongOrder(targetSize, isMarket, limitPrice)
	case ActionJoinAsk, ActionCrossSell:
		// 做空：卖出基础资产（自动借贷）
		isMarket := action == ActionCrossSell
		return e.marginExecutor.PlaceShortOrder(targetSize, isMarket, limitPrice)
	case ActionCancel:
		return e.executor.CancelAll()
	case ActionPartialExit:
		return e.marginExecutor.ClosePosition(true)
	default:
		return fmt.Errorf("unknown action: %d", action)
	}
}

func (e *HFTEngine) getEntryPrice() float64 {
	// Would track actual entry price from order history
	// For now, return current mid price
	book := e.wsManager.GetBook()
	if book != nil {
		bid, ask, _, _ := book.GetSnapshot()
		return (bid + ask) / 2
	}
	return 0
}

// GetStatus returns current engine status
func (e *HFTEngine) GetStatus() map[string]any {
	e.decisionMu.RLock()
	lastDecision := e.lastDecision
	e.decisionMu.RUnlock()

	return map[string]any{
		"symbol":          e.symbol,
		"connected":       e.wsManager.IsConnected(),
		"stale":           e.shm.IsStale(),
		"inventory":       e.inventory,
		"unrealized_pnl":  e.unrealizedPnL,
		"last_decision":   lastDecision,
		"degrade_level":    e.degradeMgr.GetCurrentLevel().String(),
		"degrade_status":   e.degradeMgr.GetStatus(),
	}
}

// GetRiskStats returns PnL and risk stats for Risk Kernel
func (e *HFTEngine) GetRiskStats() map[string]interface{} {
	if e.riskMgr == nil {
		return map[string]interface{}{
			"error": "risk manager not initialized",
		}
	}
	return e.riskMgr.GetDailyStats()
}

// GetSystemMetrics returns system metrics for Risk Kernel
func (e *HFTEngine) GetSystemMetrics() map[string]interface{} {
	var m runtime.MemStats
	runtime.ReadMemStats(&m)

	openOrders := len(e.executor.GetOrders())
	if e.config.UseMargin && e.marginExecutor != nil {
		openOrders += len(e.marginExecutor.GetOpenOrders())
	}

	return map[string]interface{}{
		"timestamp":          time.Now().Format(time.RFC3339),
		"memory_usage_gb":    float64(m.Alloc) / (1024 * 1024 * 1024),
		"memory_usage_percent": float64(m.Alloc) / float64(m.Sys) * 100,
		"ws_latency_ms":      0, // TODO: measure actual latency
		"rate_limit_hits_1min": 0, // TODO: track rate limit hits
		"cpu_usage":          0.0, // TODO: use gopsutil
		"open_orders":        openOrders,
	}
}

// StartHTTPServer starts HTTP API server for Risk Kernel integration
func (e *HFTEngine) StartHTTPServer(port int) {
	mux := http.NewServeMux()

	// Risk stats endpoint for Python Risk Kernel
	mux.HandleFunc("/api/v1/risk/stats", func(w http.ResponseWriter, r *http.Request) {
		// 使用非阻塞方式获取数据，避免阻塞交易goroutine
		stats := e.GetRiskStats()
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Access-Control-Allow-Origin", "*")
		
		// 如果数据过期，返回503警告
		if isStale, ok := stats["is_stale"].(bool); ok && isStale {
			w.WriteHeader(http.StatusServiceUnavailable)
		}
		
		json.NewEncoder(w).Encode(stats)
	})

	// System metrics endpoint
	mux.HandleFunc("/api/v1/system/metrics", func(w http.ResponseWriter, r *http.Request) {
		metrics := e.GetSystemMetrics()
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Access-Control-Allow-Origin", "*")
		json.NewEncoder(w).Encode(metrics)
	})

	// Engine status endpoint
	mux.HandleFunc("/api/v1/status", func(w http.ResponseWriter, r *http.Request) {
		status := e.GetStatus()
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(status)
	})

	addr := fmt.Sprintf(":%d", port)
	log.Printf("[HTTP] Risk Kernel API server starting on %s", addr)
	go func() {
		if err := http.ListenAndServe(addr, mux); err != nil {
			log.Printf("[HTTP] Server error: %v", err)
		}
	}()
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

	useMargin := false
	if len(os.Args) > 3 && os.Args[3] == "margin" {
		useMargin = true
	}

	// Create engine
	config := DefaultConfig(symbol)
	config.PaperTrading = paperTrading
	config.UseMargin = useMargin

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
