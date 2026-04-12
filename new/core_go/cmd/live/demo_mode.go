package main

import (
	"encoding/json"
	"fmt"
	"log"
	"math/rand"
	"net/http"
	"os"
	"sync"
	"time"
)

// DemoTradingEngine 演示交易引擎（本地模拟，不连接Binance）
type DemoTradingEngine struct {
	symbol          string
	capital         float64
	currentPrice    float64
	position        *Position
	orderManager    *OrderManager
	positionManager *PositionManager
	tradeExecutor   *TradeExecutor
	strategyManager *StrategyManager
	riskGuard       *LiveRiskGuard
	alertMgr        *AlertManager
	stopLossMgr     *AutoStopLossManager
	
	isRunning       bool
	stopCh          chan struct{}
	mu              sync.RWMutex
}

// NewDemoTradingEngine 创建演示交易引擎
func NewDemoTradingEngine(symbol string, capital float64) (*DemoTradingEngine, error) {
	engine := &DemoTradingEngine{
		symbol:   symbol,
		capital:  capital,
		stopCh:   make(chan struct{}),
	}
	
	// 初始化组件
	engine.initComponents()
	
	return engine, nil
}

func (e *DemoTradingEngine) initComponents() {
	// 风控配置
	riskConfig := &RiskConfig{
		MaxDailyLoss:     100.0,
		MaxDrawdown:      0.05,
		MaxPositionSize:  e.capital * 0.05,
		MaxTotalExposure: e.capital * 0.20,
		MinOrderSize:     10.0,
		MaxOrdersPerMin:  10,
	}
	
	// 止损配置
	stopLossConfig := &StopLossConfig{
		FixedStopLoss:   0.02,
		TrailingStop:    0.015,
		TakeProfit:      0.05,
		TimeStopMinutes: 60,
	}
	
	// 创建组件
	e.stopLossMgr = NewAutoStopLossManager(stopLossConfig)
	e.alertMgr = NewAlertManager()
	
	enhancedRM := NewEnhancedRiskManager(riskConfig)
	e.riskGuard = NewLiveRiskGuard(riskConfig, enhancedRM, e.stopLossMgr, e.alertMgr)
	
	// 注意：演示模式下这些组件需要特殊处理
	// 这里简化处理，实际应该创建模拟版本
	
	log.Printf("[Demo] Components initialized")
}

// Start 启动演示引擎
func (e *DemoTradingEngine) Start() error {
	if e.isRunning {
		return nil
	}
	
	e.isRunning = true
	
	log.Printf("🎮 Starting DEMO Trading Engine")
	log.Printf("   Symbol: %s", e.symbol)
	log.Printf("   Capital: %.2f USDT", e.capital)
	log.Printf("   ⚠️  This is a DEMO - No real trades will be executed!")
	log.Printf("")
	
	// 启动价格模拟
	go e.simulatePrice()
	
	// 启动HTTP服务器
	go e.startHTTPServer()
	
	log.Printf("✅ Demo engine started")
	log.Printf("📊 Dashboard: http://localhost:8080")
	
	return nil
}

// Stop 停止演示引擎
func (e *DemoTradingEngine) Stop() {
	if !e.isRunning {
		return
	}
	
	e.isRunning = false
	close(e.stopCh)
	log.Printf("✅ Demo engine stopped")
}

// simulatePrice 模拟价格变动
func (e *DemoTradingEngine) simulatePrice() {
	// 初始价格
	basePrice := 70000.0
	e.currentPrice = basePrice
	
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()
	
	for {
		select {
		case <-e.stopCh:
			return
		case <-ticker.C:
			// 随机价格变动 (-0.5% ~ +0.5%)
			change := (rand.Float64() - 0.5) * 0.01
			e.currentPrice = e.currentPrice * (1 + change)
			
			// 更新持仓盈亏
			if e.position != nil {
				e.position.MarkPrice = e.currentPrice
				if e.position.Side == PositionSideLong {
					e.position.UnrealizedPnL = (e.currentPrice - e.position.EntryPrice) * e.position.Size
				} else {
					e.position.UnrealizedPnL = (e.position.EntryPrice - e.currentPrice) * e.position.Size
				}
			}
			
			log.Printf("📊 Price: %.2f | Position: %v", e.currentPrice, e.position)
		}
	}
}

// simulateTrade 模拟交易
func (e *DemoTradingEngine) simulateTrade(side string, size float64) {
	if side == "buy" {
		if e.position == nil {
			e.position = &Position{
				Symbol:     e.symbol,
				Side:       PositionSideLong,
				Size:       size,
				EntryPrice: e.currentPrice,
				MarkPrice:  e.currentPrice,
				OpenTime:   time.Now(),
			}
		} else if e.position.Side == PositionSideLong {
			// 加仓
			totalValue := e.position.Size*e.position.EntryPrice + size*e.currentPrice
			e.position.Size += size
			e.position.EntryPrice = totalValue / e.position.Size
		}
		log.Printf("✅ DEMO BUY: %.6f @ %.2f", size, e.currentPrice)
	} else if side == "sell" {
		if e.position != nil && e.position.Side == PositionSideLong {
			// 平仓
			pnl := (e.currentPrice - e.position.EntryPrice) * e.position.Size
			log.Printf("✅ DEMO SELL: %.6f @ %.2f | PnL: %.2f", e.position.Size, e.currentPrice, pnl)
			e.position = nil
		}
	}
}

// startHTTPServer 启动HTTP服务器
func (e *DemoTradingEngine) startHTTPServer() {
	mux := http.NewServeMux()
	
	// 健康检查
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(map[string]interface{}{
			"status":    "ok",
			"symbol":    e.symbol,
			"mode":      "demo",
			"timestamp": time.Now().Unix(),
		})
	})
	
	// 状态API
	mux.HandleFunc("/api/status", func(w http.ResponseWriter, r *http.Request) {
		positionData := map[string]interface{}{"exists": false}
		if e.position != nil {
			positionData = map[string]interface{}{
				"exists":          true,
				"symbol":          e.position.Symbol,
				"side":            e.position.Side.String(),
				"size":            e.position.Size,
				"entry_price":     e.position.EntryPrice,
				"mark_price":      e.position.MarkPrice,
				"unrealized_pnl":  e.position.UnrealizedPnL,
				"realized_pnl":    e.position.RealizedPnL,
			}
		}
		
		json.NewEncoder(w).Encode(map[string]interface{}{
			"symbol":         e.symbol,
			"mode":           "demo",
			"is_running":     e.isRunning,
			"current_price":  e.currentPrice,
			"position":       positionData,
			"timestamp":      time.Now().Unix(),
		})
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
		
		e.simulateTrade(req.Action, req.Size)
		
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success": true,
			"action":  req.Action,
			"size":    req.Size,
			"price":   e.currentPrice,
		})
	})
	
	// 首页
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		
		positionInfo := "No position"
		if e.position != nil {
			positionInfo = fmt.Sprintf("%s %.6f BTC @ %.2f (PnL: %.2f)",
				e.position.Side.String(), e.position.Size, e.position.EntryPrice, e.position.UnrealizedPnL)
		}
		
		fmt.Fprintf(w, `<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>HFT Demo Trading</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; background: #1a1a2e; color: #eee; }
        h1 { color: #00ff88; }
        .status { padding: 20px; background: #16213e; border-radius: 8px; margin: 20px 0; }
        .demo { color: #4da6ff; font-weight: bold; }
        .ok { color: #00ff88; }
        .info { color: #ffd700; }
        button { padding: 10px 20px; margin: 5px; cursor: pointer; background: #0f3460; color: white; border: none; border-radius: 4px; }
        button:hover { background: #1a4a7a; }
        .price { font-size: 24px; color: #00ff88; }
    </style>
</head>
<body>
    <h1>🎮 HFT Demo Trading Dashboard</h1>
    <div class="status">
        <p class="demo">🧪 DEMO MODE - No real money at risk</p>
        <p>Symbol: <strong>%s</strong></p>
        <p>Status: <span class="ok">● Running</span></p>
        <p>Current Price: <span class="price">%.2f</span></p>
        <p>Position: <span class="info">%s</span></p>
    </div>
    <div class="status">
        <h3>Simulated Trading</h3>
        <button onclick="trade('buy')">Buy 0.001 BTC</button>
        <button onclick="trade('sell')">Sell 0.001 BTC</button>
        <p id="result"></p>
    </div>
    <div class="status">
        <h3>System Info</h3>
        <p>Capital: 10,000 USDT (Simulated)</p>
        <p>Price updates every 2 seconds</p>
        <p>Random price movement: ±0.5%%</p>
    </div>
    <script>
        async function trade(action) {
            const result = document.getElementById('result');
            result.textContent = 'Executing...';
            try {
                const resp = await fetch('/api/trade', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({action: action, size: 0.001})
                });
                const data = await resp.json();
                result.textContent = resp.ok ? 'Success: ' + JSON.stringify(data) : 'Error: ' + JSON.stringify(data);
            } catch(e) {
                result.textContent = 'Error: ' + e.message;
            }
        }
        setInterval(() => location.reload(), 3000);
    </script>
</body>
</html>`, e.symbol, e.currentPrice, positionInfo)
	})
	
	port := ":8081"
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
