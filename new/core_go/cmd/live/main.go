package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"syscall"
	"time"

	"github.com/adshao/go-binance/v2"
	"github.com/joho/godotenv"
)

// loadEnvFromMultipleLocations tries to load .env from multiple possible locations
func loadEnvFromMultipleLocations() {
	// Try possible locations in order:
	// 1. ../../../.env (project root from cmd/live)
	// 2. ../../.env
	// 3. ./.env (current directory)
	// 4. $HOME/.env for this project

	candidates := []string{
		"../../../.env",
		"../../.env",
		"./.env",
		filepath.Join(os.Getenv("HOME"), ".env"),
	}

	loaded := false
	for _, path := range candidates {
		if _, err := os.Stat(path); err == nil {
			err := godotenv.Load(path)
			if err == nil {
				log.Printf("[Env] Loaded environment from %s", path)
				loaded = true
				break
			} else {
				log.Printf("[Env] Failed to load from %s: %v", path, err)
			}
		}
	}

	if !loaded {
		log.Printf("[Env] No .env file found, using system environment variables")
	}
}

// LiveTradingEngine 实盘交易引擎
type LiveTradingEngine struct {
	client          *binance.Client
	orderManager    *OrderManager
	positionManager *PositionManager
	tradeExecutor   *TradeExecutor
	strategyManager *StrategyManager
	wsClient        *WebSocketClient
	riskGuard       *LiveRiskGuard
	alertMgr        *AlertManager
	stopLossMgr     *AutoStopLossManager
	profitMonitor   *ProfitMonitor         // 盈利监控器
	verification    *VerificationIntegration // 验证系统集成

	symbol          string
	capital         float64

	isRunning       bool
	stopCh          chan struct{}
}

func main() {
	// Load environment variables from .env file
	// Try multiple locations: project root, parent directories, current directory
	loadEnvFromMultipleLocations()

	// 解析参数
	mode := os.Getenv("MODE")
	if mode == "" {
		mode = "demo"
	}
	symbol := os.Getenv("SYMBOL")
	if symbol == "" {
		symbol = "BTCUSDT"
	}
	
	switch mode {
	case "live":
		runLiveMode(symbol)
	case "demo":
		runDemoMode(symbol)
	default:
		log.Printf("Unknown mode: %s. Use 'live' or 'demo'", mode)
		os.Exit(1)
	}
}

func runLiveMode(symbol string) {
	log.Printf("========================================")
	log.Printf("  HFT Live Trading Engine")
	log.Printf("========================================")
	log.Printf("")
	log.Printf("⚠️  WARNING: This is LIVE trading!")
	log.Printf("   Real money will be used!")
	log.Printf("")
	
	// 确认
	if os.Getenv("CONFIRM_LIVE_TRADING") != "YES" {
		log.Printf("❌ Set CONFIRM_LIVE_TRADING=YES to confirm live trading")
		os.Exit(1)
	}
	
	if err := runLiveTrading(symbol); err != nil {
		log.Fatalf("Live trading failed: %v", err)
	}
	
	os.Exit(0)
}

func runDemoMode(symbol string) {
	log.Printf("========================================")
	log.Printf("  HFT Demo Trading Engine")
	log.Printf("========================================")
	log.Printf("")
	log.Printf("🧪 This is DEMO mode - No real money at risk!")
	log.Printf("")

	// Read initial capital from environment, default to 10000 if not set
	capital := 10000.0
	if capitalStr := os.Getenv("INITIAL_CAPITAL"); capitalStr != "" {
		if parsed, err := strconv.ParseFloat(capitalStr, 64); err == nil {
			capital = parsed
			log.Printf("[Config] Using INITIAL_CAPITAL=%.2f from environment", capital)
		}
	}

	engine, err := NewDemoTradingEngine(symbol, capital)
	if err != nil {
		log.Fatalf("Failed to create demo engine: %v", err)
	}
	
	if err := engine.Start(); err != nil {
		log.Fatalf("Failed to start demo engine: %v", err)
	}
	
	// 等待中断信号
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	
	log.Printf("")
	log.Printf("⏳ Demo running on http://localhost:8081")
	log.Printf("   Press Ctrl+C to stop")
	log.Printf("")
	
	<-sigChan
	log.Printf("\n🛑 Shutting down...")
	
	engine.Stop()
	
	os.Exit(0)
}

func runLiveTrading(symbol string) error {
	apiKey := os.Getenv("BINANCE_API_KEY")
	apiSecret := os.Getenv("BINANCE_API_SECRET")

	if apiKey == "" || apiSecret == "" {
		return fmt.Errorf("BINANCE_API_KEY and BINANCE_API_SECRET must be set")
	}

	// 创建引擎
	engine, err := NewLiveTradingEngine(apiKey, apiSecret, symbol)
	if err != nil {
		return fmt.Errorf("failed to create engine: %w", err)
	}
	
	// 启动引擎
	if err := engine.Start(); err != nil {
		return fmt.Errorf("failed to start engine: %w", err)
	}
	
	// 等待中断信号
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	
	log.Printf("")
	log.Printf("⏳ System running. Press Ctrl+C to stop")
	log.Printf("")
	
	<-sigChan
	log.Printf("\n🛑 Shutting down...")
	
	engine.Stop()
	
	return nil
}

// NewLiveTradingEngine 创建实盘交易引擎
func NewLiveTradingEngine(apiKey, apiSecret, symbol string) (*LiveTradingEngine, error) {
	// 检查是否使用Testnet
	useTestnet := os.Getenv("USE_TESTNET") == "true"
	if useTestnet {
		binance.UseTestnet = true
		log.Printf("🧪 Using Binance Testnet")
	}

	// 创建Binance客户端
	client := binance.NewClient(apiKey, apiSecret)

	// 配置代理
	if proxyURL := os.Getenv("HTTPS_PROXY"); proxyURL != "" {
		parsedURL, err := url.Parse(proxyURL)
		if err == nil {
			transport := &http.Transport{
				Proxy: http.ProxyURL(parsedURL),
			}
			client.HTTPClient = &http.Client{
				Transport: transport,
				Timeout:   30 * time.Second,
			}
		}
	}

	// 测试连接（带重试）并获取账户信息
	var account *binance.Account
	var err error

	for i := 0; i < 3; i++ {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		account, err = client.NewGetAccountService().Do(ctx)
		cancel()

		if err == nil {
			break
		}

		log.Printf("⚠️ Connection attempt %d failed: %v", i+1, err)
		time.Sleep(2 * time.Second)
	}

	if err != nil {
		return nil, fmt.Errorf("failed to connect to Binance after 3 attempts: %w", err)
	}

	log.Printf("✅ Connected to Binance")
	log.Printf("   Can Trade: %v", account.CanTrade)

	// Calculate actual total USDT balance from account
	var capital float64 = 10000.0 // Default fallback

	// If INITIAL_CAPITAL is set in environment, use it (override)
	if capitalStr := os.Getenv("INITIAL_CAPITAL"); capitalStr != "" {
		if parsed, errParse := strconv.ParseFloat(capitalStr, 64); errParse == nil {
			capital = parsed
			log.Printf("[Config] Using INITIAL_CAPITAL=%.2f from environment (overrides account balance)", capital)
		}
	} else if os.Getenv("USE_LEVERAGE") == "true" {
		// When leverage is enabled, get balance from margin account
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		marginAccount, err := client.NewGetMarginAccountService().Do(ctx)
		cancel()

		if err != nil {
			log.Printf("[Config] Failed to get margin account: %v, using spot balance", err)
			// Fallback to spot balance
			for _, bal := range account.Balances {
				if bal.Asset == "USDT" {
					free, errFree := strconv.ParseFloat(bal.Free, 64)
					locked, errLocked := strconv.ParseFloat(bal.Locked, 64)
					if errFree == nil && errLocked == nil {
						capital = free + locked
						log.Printf("[Config] Auto-detected spot USDT balance (fallback): %.2f", capital)
						break
					}
				}
			}
		} else {
			// For cross-margin (full leverage) account, use total collateral value in USDT
			// This is the total net equity of the entire margin account
			if marginAccount.TotalCollateralValueInUSDT != "" {
				if totalVal, err := strconv.ParseFloat(marginAccount.TotalCollateralValueInUSDT, 64); err == nil {
					capital = totalVal
					log.Printf("[Config] Auto-detected LEVERAGE account total collateral: %.2f USDT (using TotalCollateralValueInUSDT)", capital)
				}
			} else {
				// Fallback: search for USDT asset and use NetAsset
				for _, bal := range marginAccount.UserAssets {
					if bal.Asset == "USDT" {
						// Try NetAsset first (this is the actual net equity)
						if bal.NetAsset != "" {
							if netAsset, errNet := strconv.ParseFloat(bal.NetAsset, 64); errNet == nil {
								capital = netAsset
								log.Printf("[Config] Auto-detected LEVERAGE account USDT net equity: %.2f (using NetAsset field)", capital)
								break
							}
						}
						// Fallback to free + locked if NetAsset is empty
						free, errFree := strconv.ParseFloat(bal.Free, 64)
						locked, errLocked := strconv.ParseFloat(bal.Locked, 64)
						if errFree == nil && errLocked == nil {
							capital = free + locked
							log.Printf("[Config] Auto-detected LEVERAGE account USDT balance (free+locked): %.2f", capital)
							break
						}
					}
				}
			}
		}
	} else {
		// Sum all USDT balances (free + locked) from spot account
		for _, bal := range account.Balances {
			if bal.Asset == "USDT" {
				free, errFree := strconv.ParseFloat(bal.Free, 64)
				locked, errLocked := strconv.ParseFloat(bal.Locked, 64)
				if errFree == nil && errLocked == nil {
					capital = free + locked
					log.Printf("[Config] Auto-detected spot USDT balance: %.2f", capital)
					break
				}
			}
		}
	}

	// 创建引擎
	engine := &LiveTradingEngine{
		client:  client,
		symbol:  symbol,
		capital: capital,
		stopCh:  make(chan struct{}),
	}

	// 8. 创建WebSocket客户端 - reuse already proxy-configured client
	engine.wsClient = NewWebSocketClient(
		client,
		os.Getenv("BINANCE_API_KEY"),
		os.Getenv("BINANCE_API_SECRET"),
		engine.symbol, false,
	)

	// 初始化组件
	engine.initComponents()

	return engine, nil
}

// initComponents 初始化组件
func (e *LiveTradingEngine) initComponents() {
	// 1. 风控配置（优化参数）
	riskConfig := &RiskConfig{
		MaxDailyLoss:     50.0,   // 降低日亏损限制
		MaxDrawdown:      0.03,   // 降低最大回撤
		MaxPositionSize:  e.capital * 0.03,  // 降低单仓位限制到3%
		MaxTotalExposure: e.capital * 0.10,  // 降低总敞口到10%
		MinOrderSize:     10.0,
		MaxOrdersPerMin:  5,      // 降低交易频率
	}
	
	// 2. 止损配置（优化参数）
	stopLossConfig := &StopLossConfig{
		FixedStopLoss:   0.008,  // 降低固定止损到0.8%
		TrailingStop:    0.005,  // 降低移动止损到0.5%
		TakeProfit:      0.016,  // 降低止盈到1.6% (2:1盈亏比)
		TimeStopMinutes: 30,     // 缩短时间止损
	}
	
	// 3. 创建组件
	e.stopLossMgr = NewAutoStopLossManager(stopLossConfig)
	e.alertMgr = NewAlertManager()
	
	enhancedRM := NewEnhancedRiskManager(riskConfig)
	e.riskGuard = NewLiveRiskGuard(riskConfig, enhancedRM, e.stopLossMgr, e.alertMgr)
	
	e.orderManager = NewOrderManager(e.client)
	e.positionManager = NewPositionManager(e.stopLossMgr)
	
	e.tradeExecutor = NewTradeExecutor(
		e.client, e.orderManager, e.positionManager,
		e.riskGuard, e.alertMgr, e.symbol, e.capital,
	)
	
	// 4. 创建策略管理器
	e.strategyManager = NewStrategyManager(e.tradeExecutor)
	
	// 添加优化后的趋势策略（不再使用冲突的均值回归策略）
	strategyConfig := DefaultStrategyConfig()
	strategyConfig.PositionSizeBase = 0.001
	strategyConfig.PositionSizeMax = 0.003
	e.strategyManager.AddStrategy(NewOptimizedTrendStrategy(e.symbol, strategyConfig))
	
	// 添加突破策略作为辅助
	e.strategyManager.AddStrategy(NewBreakoutStrategy(e.symbol, 0.001))
	
	// 6. 创建盈利监控器
	e.profitMonitor = NewProfitMonitor(DefaultProfitMonitorConfig())
	e.profitMonitor.Start()
	
	// 7. 创建验证系统集成（从环境变量读取是否启用）
	verificationEnabled := os.Getenv("ENABLE_VERIFICATION") == "true"
	e.verification = NewVerificationIntegration(verificationEnabled)
	e.verification.SetComponents(e.orderManager, e.positionManager, e.tradeExecutor)
	
	
	// 设置WebSocket处理器
	e.wsClient.SetPriceHandler(func(bid, ask float64) {
		// 更新交易执行器价格
		e.tradeExecutor.UpdatePrice(bid, ask)
		
		// 更新策略
		e.strategyManager.UpdatePrice(bid, ask)
		
		// 更新止损管理器
		midPrice := (bid + ask) / 2
		e.stopLossMgr.UpdatePrice(e.symbol, midPrice)
		
		// 检查止损
		if alert := e.stopLossMgr.CheckStopLoss(e.symbol, midPrice); alert != nil {
			e.handleStopLossAlert(alert)
		}
	})
	
	e.wsClient.SetOrderHandler(func(event *binance.WsUserDataEvent) {
		exec := event.OrderUpdate
		
		// 更新订单管理器
		e.orderManager.UpdateOrderFromExecution(event)
		
		// 更新验证系统
		e.verification.ProcessUserDataEvent(event)
		
		// 更新仓位
		if exec.Status == "FILLED" || exec.Status == "PARTIALLY_FILLED" {
			side := OrderSideBuy
			if exec.Side == "SELL" {
				side = OrderSideSell
			}
			size := parseFloat(exec.LatestVolume)
			price := parseFloat(exec.LatestPrice)
			
			e.positionManager.UpdatePosition(e.symbol, side, size, price, 0)
		}
	})
}

// Start 启动引擎
func (e *LiveTradingEngine) Start() error {
	if e.isRunning {
		return nil
	}
	
	e.isRunning = true
	
	log.Printf("🚀 Starting Live Trading Engine")
	log.Printf("   Symbol: %s", e.symbol)
	log.Printf("   Capital: %.2f USDT", e.capital)
	log.Printf("")
	
	// 启动组件
	e.orderManager.Start()
	e.positionManager.Start()
	e.tradeExecutor.Start()
	e.strategyManager.Start()
	
	// 启动验证系统
	if err := e.verification.Start(); err != nil {
		log.Printf("[Warning] Failed to start verification: %v", err)
	}
	
	// 启动WebSocket
	if err := e.wsClient.Start(); err != nil {
		return fmt.Errorf("failed to start WebSocket: %w", err)
	}
	
	// 同步数据
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	e.tradeExecutor.SyncWithBinance(ctx)

	// Get initial price from REST API before starting dashboard
	// This ensures dashboard shows current price immediately instead of 0.00
	service := e.client.NewListPricesService()
	service = service.Symbol(e.symbol)
	prices, err := service.Do(ctx)
	if err == nil && len(prices) > 0 {
		if price, errParse := strconv.ParseFloat(prices[0].Price, 64); errParse == nil {
			// Update price to all components
			bid := price
			ask := price
			midPrice := price
			e.tradeExecutor.UpdatePrice(bid, ask)
			e.strategyManager.UpdatePrice(bid, ask)
			e.stopLossMgr.UpdatePrice(e.symbol, midPrice)
			log.Printf("[Init] Got initial price: %.2f", price)
		}
	} else if err != nil {
		log.Printf("[Warning] Failed to get initial price: %v", err)
	}
	cancel()

	// 启动HTTP服务器（使用环境变量指定端口）
	go e.startHTTPServer()
	
	// 启动主循环
	go e.mainLoop()
	
	log.Printf("✅ All components started")
	log.Printf("📊 Dashboard: http://localhost:8080")
	
	return nil
}

// Stop 停止引擎
func (e *LiveTradingEngine) Stop() {
	if !e.isRunning {
		return
	}
	
	e.isRunning = false
	close(e.stopCh)
	
	// 停止组件
	e.wsClient.Stop()
	e.strategyManager.Stop()
	e.tradeExecutor.Stop()
	e.positionManager.Stop()
	e.orderManager.Stop()
	
	// 停止盈利监控器并生成最终报告
	if e.profitMonitor != nil {
		e.profitMonitor.generateReport()
		e.profitMonitor.Stop()
	}
	
	// 停止验证系统
	if e.verification != nil {
		if err := e.verification.Stop(); err != nil {
			log.Printf("[Warning] Error stopping verification: %v", err)
		}
	}
	
	log.Printf("✅ Engine stopped")
}

// mainLoop 主循环
func (e *LiveTradingEngine) mainLoop() {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()
	
	// 盈利检查ticker
	profitCheckTicker := time.NewTicker(1 * time.Minute)
	defer profitCheckTicker.Stop()
	
	for {
		select {
		case <-e.stopCh:
			return
		case <-ticker.C:
			e.reportStatus()
		case <-profitCheckTicker.C:
			e.checkProfitStatus()
		}
	}
}

// checkProfitStatus 检查盈利状态
func (e *LiveTradingEngine) checkProfitStatus() {
	if e.profitMonitor == nil {
		return
	}
	
	// 检查是否应该停止交易
	if e.profitMonitor.ShouldStopTrading() {
		log.Printf("🛑 PROFIT GUARD: Trading stopped due to loss limits")
		
		// 发送告警
		if e.alertMgr != nil {
			e.alertMgr.SendAlert(ALERT_CRITICAL, ALERT_EMERGENCY,
				"Trading Halted",
				"Daily loss limit or consecutive loss limit reached",
				nil)
		}
		
		// 平仓所有持仓
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		e.tradeExecutor.ClosePosition(ctx)
	}
	
	// 检查日盈利目标
	stats := e.profitMonitor.GetDailyStats()
	if stats.TotalPnL >= e.profitMonitor.config.DailyProfitTarget {
		log.Printf("🎯 PROFIT TARGET REACHED: $%.2f", stats.TotalPnL)
	}
}

// reportStatus 报告状态
func (e *LiveTradingEngine) reportStatus() {
	position := e.positionManager.GetPosition(e.symbol)
	unrealizedPnL := e.positionManager.GetTotalUnrealizedPnL()
	realizedPnL := e.positionManager.GetTotalRealizedPnL()
	
	if position != nil {
		log.Printf("📈 Position: %s %.6f @ %.2f | Unrealized: %.2f | Realized: %.2f",
			position.Side.String(), position.Size, position.EntryPrice,
			unrealizedPnL, realizedPnL)
	} else {
		log.Printf("📈 No position | Realized PnL: %.2f", realizedPnL)
	}
}

// handleStopLossAlert 处理止损告警
func (e *LiveTradingEngine) handleStopLossAlert(alert *StopLossAlert) {
	log.Printf("🚨 STOP LOSS: %s", alert.Reason)
	
	// 发送告警
	if e.alertMgr != nil {
		e.alertMgr.SendAlert(ALERT_CRITICAL, ALERT_STOP_LOSS,
			"Stop Loss Triggered",
			fmt.Sprintf("%s at %.2f, PnL: %.2f", alert.Symbol, alert.CurrentPrice, alert.UnrealizedPnL),
			map[string]interface{}{
				"symbol": alert.Symbol,
				"price":  alert.CurrentPrice,
				"pnl":    alert.UnrealizedPnL,
			})
	}
	
	// 自动平仓
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	
	result := e.tradeExecutor.ClosePosition(ctx)
	if result.Error != nil {
		log.Printf("❌ Failed to close position: %v", result.Error)
	} else {
		log.Printf("✅ Position closed by stop loss")
	}
}

// startHTTPServer 启动HTTP服务器
func (e *LiveTradingEngine) startHTTPServer() {
	mux := http.NewServeMux()
	
	// 健康检查
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(map[string]interface{}{
			"status":    "ok",
			"symbol":    e.symbol,
			"mode":      "live",
			"timestamp": time.Now().Unix(),
		})
	})
	
	// 状态API
	mux.HandleFunc("/api/status", func(w http.ResponseWriter, r *http.Request) {
		position := e.positionManager.GetPosition(e.symbol)
		stats := e.tradeExecutor.GetStats()
		
		json.NewEncoder(w).Encode(map[string]interface{}{
			"symbol":          e.symbol,
			"mode":            "live",
			"is_running":      e.isRunning,
			"current_price":   e.tradeExecutor.GetCurrentPrice(),
			"position":        position,
			"unrealized_pnl":  e.positionManager.GetTotalUnrealizedPnL(),
			"realized_pnl":    e.positionManager.GetTotalRealizedPnL(),
			"executor_stats":  stats,
			"timestamp":       time.Now().Unix(),
		})
	})
	
	// 风控状态
	mux.HandleFunc("/api/risk", func(w http.ResponseWriter, r *http.Request) {
		if e.riskGuard != nil {
			json.NewEncoder(w).Encode(e.riskGuard.GetStats())
		} else {
			json.NewEncoder(w).Encode(map[string]string{"error": "risk guard not initialized"})
		}
	})
	
	// 策略状态
	mux.HandleFunc("/api/strategies", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(e.strategyManager.GetStates())
	})
	
	// 盈利监控API
	mux.HandleFunc("/api/profit/daily", func(w http.ResponseWriter, r *http.Request) {
		if e.profitMonitor != nil {
			json.NewEncoder(w).Encode(e.profitMonitor.GetDailyStats())
		} else {
			json.NewEncoder(w).Encode(map[string]string{"error": "profit monitor not initialized"})
		}
	})
	
	mux.HandleFunc("/api/profit/report", func(w http.ResponseWriter, r *http.Request) {
		if e.profitMonitor != nil {
			json.NewEncoder(w).Encode(e.profitMonitor.GetFullReport())
		} else {
			json.NewEncoder(w).Encode(map[string]string{"error": "profit monitor not initialized"})
		}
	})
	
	// 验证系统API
	mux.HandleFunc("/api/verification/status", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(map[string]interface{}{
			"enabled":     e.verification.IsEnabled(),
			"health":      e.verification.GetHealthStatus(),
			"timestamp":   time.Now().Unix(),
		})
	})
	
	mux.HandleFunc("/api/verification/stats", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(e.verification.GetStats())
	})
	
	mux.HandleFunc("/api/verification/report", func(w http.ResponseWriter, r *http.Request) {
		report := e.verification.GetReport()
		if report != nil {
			json.NewEncoder(w).Encode(report)
		} else {
			json.NewEncoder(w).Encode(map[string]string{"error": "verification disabled or report not available"})
		}
	})
	
	mux.HandleFunc("/api/verification/check", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		
		report, err := e.verification.TriggerManualCheck(ctx)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		
		json.NewEncoder(w).Encode(report)
	})
	
	// 手动交易API
	mux.HandleFunc("/api/trade", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		
		var req struct {
			Action string  `json:"action"`
			Size   float64 `json:"size"`
		}
		
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		
		var result *TradeResult
		switch req.Action {
		case "buy":
			result = e.tradeExecutor.Buy(ctx, req.Size, 0, OrderTypeMarket)
		case "sell":
			result = e.tradeExecutor.Sell(ctx, req.Size, 0, OrderTypeMarket)
		case "close":
			result = e.tradeExecutor.ClosePosition(ctx)
		default:
			http.Error(w, "Invalid action", http.StatusBadRequest)
			return
		}
		
		if result.Error != nil {
			http.Error(w, result.Error.Error(), http.StatusInternalServerError)
			return
		}
		
		json.NewEncoder(w).Encode(result)
	})
	
	// 首页 - 使用dashboard.go中的renderDashboard
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		e.renderDashboard(w)
	})
	
	port := ":8080"
	if envPort := os.Getenv("PORT"); envPort != "" {
		port = ":" + envPort
	}
	
	server := &http.Server{
		Addr:    port,
		Handler: mux,
	}
	
	log.Printf("📊 Dashboard started: http://localhost%s", port)
	if err := server.ListenAndServe(); err != nil {
		log.Printf("HTTP server error: %v", err)
	}
}

// parseFloat 解析float64
func parseFloat(s string) float64 {
	var f float64
	fmt.Sscanf(s, "%f", &f)
	return f
}
