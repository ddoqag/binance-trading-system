package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"math"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"sync"
	"time"

	"github.com/adshao/go-binance/v2"
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
	tickSize float64 // Price tick size for this symbol (from exchange info)

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
	defenseMgr     *DefenseManager // Defense FSM for toxic flow protection
	execOptimizer  *ExecutionOptimizer // Execution Alpha optimizer

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
		tickSize: 0.01, // Default tick size for BTCUSDT, will be updated from exchange info
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

	// Initialize execution optimizer (execution alpha)
	// Note: reversalDetector will be initialized and passed later if needed
	engine.execOptimizer = NewExecutionOptimizer(nil, engine.defenseMgr, nil)
	log.Printf("[ENGINE] Execution optimizer initialized")

	return engine, nil
}

func (e *HFTEngine) Start() error {
	// 配置 WebSocket 代理
	if proxyURL := os.Getenv("HTTPS_PROXY"); proxyURL != "" {
		if _, err := url.Parse(proxyURL); err == nil {
			binance.SetWsProxyUrl(proxyURL)
			log.Printf("[ENGINE] WebSocket proxy configured: %s", proxyURL)
		} else {
			log.Printf("[ENGINE] Invalid WebSocket proxy URL: %v", err)
		}
	}
	// 配置 WebSocket 端口（有些网络封禁 9443/8443，改用标准 443 端口）
	binance.BaseWsMainURL = "wss://stream.binance.com:443/ws"
	log.Printf("[ENGINE] WebSocket base URL set to: %s", binance.BaseWsMainURL)

	log.Printf("[ENGINE] Starting HFT Engine for %s", e.symbol)

	// Get tick size from exchange info (only once at startup)
	if e.apiClient != nil {
		ctx, cancel := context.WithTimeout(e.ctx, 10*time.Second)
		defer cancel()
		filters, err := e.apiClient.GetSymbolFilters(ctx, e.symbol)
		if err == nil {
			if priceFilter, ok := filters["PRICE_FILTER"]; ok {
				if pf, ok := priceFilter.(map[string]interface{}); ok {
					if tickSizeStr, ok := pf["tickSize"].(string); ok {
						if tickSizeParsed, err := strconv.ParseFloat(tickSizeStr, 64); err == nil {
							e.tickSize = tickSizeParsed
							log.Printf("[ENGINE] Got tick size from exchange info: %.6f", e.tickSize)
						}
					}
				}
			}
		} else {
			log.Printf("[ENGINE] Failed to get tick size from exchange info, using default %.4f: %v", e.tickSize, err)
		}
	}

	// Set up WebSocket handlers
	e.wsManager.SetDepthHandler(e.onDepthUpdate)
	e.wsManager.SetTradeHandler(e.onTradeUpdate)

	// Connect to Binance
	if err := e.wsManager.Connect(); err != nil {
		return fmt.Errorf("failed to connect WebSocket: %w", err)
	}
	log.Println("[ENGINE] WebSocket connected successfully")

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

	// === Execution Optimizer Integration ===
	// Convert action to OrderSide for optimizer
	var side OrderSide
	var urgency float64 = float64(confidence) // Use AI confidence as base urgency

	switch action {
	case ActionCrossBuy, ActionJoinBid:
		side = SideBuy
	case ActionCrossSell, ActionJoinAsk:
		side = SideSell
	default:
		// For cancel/partial exit, use inventory direction
		if e.inventory > 0 {
			side = SideSell
		} else {
			side = SideBuy
		}
	}

	// Create AI command for optimizer
	cmd := AICommand{
		Side:       side,
		Size:       targetSize,
		Price:      limitPrice,
		Confidence: float64(confidence),
		Urgency:    urgency,
	}

	// Get optimized order parameters
	optimizedParams, err := e.execOptimizer.Optimize(cmd, e.inventory)
	if err != nil {
		log.Printf("[OPTIMIZER] Failed to optimize order: %v", err)
		return
	}

	// Check if optimizer cancelled the order (nil return or quantity = 0)
	if optimizedParams == nil || optimizedParams.Quantity <= 0 {
		log.Printf("[OPTIMIZER] Order cancelled by optimizer (size too small or risk limits)")
		return
	}

	log.Printf("[OPTIMIZER] Optimized: side=%v type=%v price=%.2f qty=%.4f urgency=%.2f mode=%s",
		optimizedParams.Side, optimizedParams.Type, optimizedParams.Price,
		optimizedParams.Quantity, optimizedParams.Urgency, optimizedParams.Metadata.DefenseMode)

	// Execute decision with optimized parameters
	if e.config.UseMargin && e.marginExecutor != nil {
		// Use margin trading executor with optimized params
		err = e.executeMarginDecisionOptimized(optimizedParams)
	} else {
		// Use regular spot executor with optimized params
		err = e.executeSpotDecisionOptimized(optimizedParams)
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
// 强制使用LIMIT+POST_ONLY订单，确保maker费率(0-2bps)甚至返佣
func (e *HFTEngine) executeSpotDecision(action int32, targetSize float64, limitPrice float64) error {
	// 强制maker订单，使用POST_ONLY获取maker费率或返佣
	forceMaker := true

	// 获取当前订单簿数据用于价格优化
	book := e.wsManager.GetBook()
	var bestBid, bestAsk float64

	if book != nil {
		bestBid, bestAsk, _, _ = book.GetSnapshot()
	}

	switch action {
	case ActionJoinBid:
		// 买单：挂最优买价减1tick，争取maker返佣
		price := limitPrice
		if bestBid > 0 {
			price = bestBid - e.tickSize // 比最优买价更优1tick
		}
		return e.executor.PlaceLimitBuy(price, targetSize, forceMaker)
	case ActionJoinAsk:
		// 卖单：挂最优卖价加1tick，争取maker返佣
		price := limitPrice
		if bestAsk > 0 {
			price = bestAsk + e.tickSize // 比最优卖价更优1tick
		}
		return e.executor.PlaceLimitSell(price, targetSize, forceMaker)
	case ActionCrossBuy:
		// 即使是cross动作，也使用限价单+POST_ONLY，价格挂买一
		// 如果无法立即成交，订单会被拒绝（POST_ONLY特性），不会产生taker费用
		price := limitPrice
		if bestBid > 0 {
			price = bestBid // 挂最优买价
		}
		return e.executor.PlaceLimitBuy(price, targetSize, forceMaker)
	case ActionCrossSell:
		// 即使是cross动作，也使用限价单+POST_ONLY，价格挂卖一
		price := limitPrice
		if bestAsk > 0 {
			price = bestAsk // 挂最优卖价
		}
		return e.executor.PlaceLimitSell(price, targetSize, forceMaker)
	case ActionCancel:
		return e.executor.CancelAll()
	case ActionPartialExit:
		// 部分平仓也使用限价单
		exitSize := e.inventory * 0.5
		if exitSize > 0 {
			// 多头平仓：卖出
			price := limitPrice
			if bestAsk > 0 {
				price = bestAsk + e.tickSize
			}
			return e.executor.PlaceLimitSell(price, exitSize, forceMaker)
		} else if exitSize < 0 {
			// 空头平仓：买入
			price := limitPrice
			if bestBid > 0 {
				price = bestBid - e.tickSize
			}
			return e.executor.PlaceLimitBuy(price, -exitSize, forceMaker)
		}
		return nil
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

// executeSpotDecisionOptimized 使用优化后的参数执行现货交易决策
// 强制使用LIMIT+POST_ONLY订单，确保maker费率(0-2bps)甚至返佣
func (e *HFTEngine) executeSpotDecisionOptimized(params *OptimizedOrderParams) error {
	// 强制maker订单，使用POST_ONLY获取maker费率或返佣
	forceMaker := true

	// 获取当前订单簿数据用于价格优化
	book := e.wsManager.GetBook()
	var bestBid, bestAsk float64

	if book != nil {
		bestBid, bestAsk, _, _ = book.GetSnapshot()
	}

	switch params.Type {
	case TypeMarket:
		// 即使是市价单类型，也转换为限价单+POST_ONLY
		// 价格挂最优价，如果无法立即作为maker成交，订单会被拒绝
		if params.Side == SideBuy {
			price := params.Price
			if bestBid > 0 {
				price = bestBid // 挂最优买价
			}
			return e.executor.PlaceLimitBuy(price, params.Quantity, forceMaker)
		}
		price := params.Price
		if bestAsk > 0 {
			price = bestAsk // 挂最优卖价
		}
		return e.executor.PlaceLimitSell(price, params.Quantity, forceMaker)
	case TypeLimit:
		// 优化价格：买单减1tick，卖单加1tick
		optimizedPrice := params.Price
		if params.Side == SideBuy {
			if bestBid > 0 {
				optimizedPrice = bestBid - e.tickSize // 比最优买价更优
			}
			return e.executor.PlaceLimitBuy(optimizedPrice, params.Quantity, forceMaker)
		}
		if bestAsk > 0 {
			optimizedPrice = bestAsk + e.tickSize // 比最优卖价更优
		}
		return e.executor.PlaceLimitSell(optimizedPrice, params.Quantity, forceMaker)
	default:
		return fmt.Errorf("unknown order type: %v", params.Type)
	}
}

// executeMarginDecisionOptimized 使用优化后的参数执行杠杆交易决策
func (e *HFTEngine) executeMarginDecisionOptimized(params *OptimizedOrderParams) error {
	isMarket := params.Type == TypeMarket

	switch params.Side {
	case SideBuy:
		// 做多：买入基础资产
		return e.marginExecutor.PlaceLongOrder(params.Quantity, isMarket, params.Price)
	case SideSell:
		// 做空：卖出基础资产（自动借贷）
		return e.marginExecutor.PlaceShortOrder(params.Quantity, isMarket, params.Price)
	default:
		return fmt.Errorf("unknown side: %v", params.Side)
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

	// Market data endpoint - order book
	mux.HandleFunc("/api/v1/market/book", func(w http.ResponseWriter, r *http.Request) {
		book := e.wsManager.GetBook()
		if book == nil {
			w.WriteHeader(http.StatusServiceUnavailable)
			json.NewEncoder(w).Encode(map[string]string{"error": "order book not available"})
			return
		}

		bids, asks, _, _ := book.GetSnapshot()
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"bids":      bids,
			"asks":      asks,
			"timestamp": time.Now().UnixMilli(),
		})
	})

	// Position endpoint
	mux.HandleFunc("/api/v1/position", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")

		if e.config.UseMargin && e.marginExecutor != nil {
			pos := e.marginExecutor.GetPosition()
			json.NewEncoder(w).Encode(map[string]interface{}{
				"symbol":      pos.Symbol,
				"size":        pos.Position,
				"entry_price": pos.EntryPrice,
				"leverage":    pos.Leverage,
				"unrealized":  pos.UnrealizedPnL,
				"liquidation": pos.LiquidationPrice,
			})
		} else {
			json.NewEncoder(w).Encode(map[string]interface{}{
				"symbol":      e.symbol,
				"size":        e.inventory,
				"entry_price": 0,
				"leverage":    1.0,
				"unrealized":  e.unrealizedPnL,
				"liquidation": 0,
			})
		}
	})

	// Orders endpoint (POST to create order)
	mux.HandleFunc("/api/v1/orders", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")

		if r.Method != http.MethodPost {
			w.WriteHeader(http.StatusMethodNotAllowed)
			json.NewEncoder(w).Encode(map[string]string{"error": "only POST allowed"})
			return
		}

		var req struct {
			Side  string  `json:"side"`
			Qty   float64 `json:"qty"`
			Price float64 `json:"price,omitempty"`
			Type  string  `json:"type"`
		}

		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
			return
		}

		// Create order response
		orderID := fmt.Sprintf("order_%d", time.Now().UnixMilli())
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"id":     orderID,
			"status": "pending",
			"side":   req.Side,
			"qty":    req.Qty,
			"price":  req.Price,
		})
	})

	addr := fmt.Sprintf(":%d", port)
	log.Printf("[HTTP] Risk Kernel API server starting on %s", addr)
	go func() {
		if err := http.ListenAndServe(addr, mux); err != nil {
			log.Printf("[HTTP] Server error: %v", err)
		}
	}()
}
