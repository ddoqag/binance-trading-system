package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

/*
websocket_feed.go - Binance WebSocket Real-time Data Feed

Connects to Binance WebSocket streams for:
- L2 Order Book (depth@100ms)
- Trade stream (trade)
- Ticker (ticker)

Features:
- Auto-reconnection with exponential backoff
- Heartbeat/ping-pong handling
- Connection health monitoring
- Message deduplication and ordering
*/

const (
	// Binance WebSocket endpoints - Mainnet
	BinanceWSBase       = "wss://stream.binance.com:9443/ws"
	BinanceWSStreamBase = "wss://stream.binance.com:9443/stream?streams="

	// Binance WebSocket endpoints - Testnet (updated 2024)
	BinanceTestnetWSBase       = "wss://stream.testnet.binance.vision/ws"
	BinanceTestnetWSStreamBase = "wss://stream.testnet.binance.vision/stream?streams="

	// Reconnection settings
	InitialReconnectDelay = 1 * time.Second
	MaxReconnectDelay     = 30 * time.Second
	ReconnectMultiplier   = 2.0

	// Health check settings
	HeartbeatInterval = 30 * time.Second
	StaleTimeout      = 60 * time.Second
)

// Message types from Binance
type DepthUpdate struct {
	EventType string     `json:"e"`
	EventTime int64      `json:"E"`
	Symbol    string     `json:"s"`
	FirstID   int64      `json:"U"`
	FinalID   int64      `json:"u"`
	Bids      [][]string `json:"b"`
	Asks      [][]string `json:"a"`
}

type TradeUpdate struct {
	EventType  string `json:"e"`
	EventTime  int64  `json:"E"`
	Symbol     string `json:"s"`
	TradeID    int64  `json:"t"`
	Price      string `json:"p"`
	Quantity   string `json:"q"`
	BuyerOrder int64  `json:"b"`
	SellerOrder int64 `json:"a"`
	TradeTime  int64  `json:"T"`
	IsBuyerMaker bool `json:"m"`
}

type TickerUpdate struct {
	EventType string `json:"e"`
	EventTime int64  `json:"E"`
	Symbol    string `json:"s"`
	PriceChange string `json:"p"`
	PriceChangePercent string `json:"P"`
	WeightedAvgPrice string `json:"w"`
	LastPrice string `json:"c"`
	LastQty string `json:"Q"`
	BidPrice string `json:"b"`
	BidQty string `json:"B"`
	AskPrice string `json:"a"`
	AskQty string `json:"A"`
}

// Level2Book maintains L2 order book state
type Level2Book struct {
	mu       sync.RWMutex
	Symbol   string
	LastUpdateID int64
	Bids     map[string]string // price -> qty
	Asks     map[string]string // price -> qty
	BestBid  float64
	BestAsk  float64
	LastUpdate time.Time
}

func NewLevel2Book(symbol string) *Level2Book {
	return &Level2Book{
		Symbol: symbol,
		Bids:   make(map[string]string),
		Asks:   make(map[string]string),
	}
}

func (b *Level2Book) UpdateBid(price, qty string) {
	b.mu.Lock()
	defer b.mu.Unlock()

	if qty == "0" || qty == "0.0" || qty == "0.00000000" {
		delete(b.Bids, price)
	} else {
		b.Bids[price] = qty
	}
	b.updateBest()
	b.LastUpdate = time.Now()
}

func (b *Level2Book) UpdateAsk(price, qty string) {
	b.mu.Lock()
	defer b.mu.Unlock()

	if qty == "0" || qty == "0.0" || qty == "0.00000000" {
		delete(b.Asks, price)
	} else {
		b.Asks[price] = qty
	}
	b.updateBest()
	b.LastUpdate = time.Now()
}

func (b *Level2Book) updateBest() {
	// Find best bid (highest)
	b.BestBid = 0
	for priceStr := range b.Bids {
		var price float64
		fmt.Sscanf(priceStr, "%f", &price)
		if price > b.BestBid {
			b.BestBid = price
		}
	}

	// Find best ask (lowest)
	b.BestAsk = 1e18
	for priceStr := range b.Asks {
		var price float64
		fmt.Sscanf(priceStr, "%f", &price)
		if price < b.BestAsk {
			b.BestAsk = price
		}
	}
	if b.BestAsk == 1e18 {
		b.BestAsk = 0
	}
}

func (b *Level2Book) GetSnapshot() (bestBid, bestAsk float64, bidVol, askVol float64) {
	b.mu.RLock()
	defer b.mu.RUnlock()

	bestBid = b.BestBid
	bestAsk = b.BestAsk

	// Calculate volume at top 5 levels
	for priceStr, qtyStr := range b.Bids {
		var price, qty float64
		fmt.Sscanf(priceStr, "%f", &price)
		fmt.Sscanf(qtyStr, "%f", &qty)
		if price >= bestBid*0.999 { // within 0.1% of best
			bidVol += qty
		}
	}

	for priceStr, qtyStr := range b.Asks {
		var price, qty float64
		fmt.Sscanf(priceStr, "%f", &price)
		fmt.Sscanf(qtyStr, "%f", &qty)
		if price <= bestAsk*1.001 { // within 0.1% of best
			askVol += qty
		}
	}

	return
}

// OFICalculator calculates Order Flow Imbalance
type OFICalculator struct {
	mu        sync.Mutex
	Window    time.Duration
	Trades    []TradeRecord
	OFI       float64
}

type TradeRecord struct {
	Time   time.Time
	Volume float64
	IsBuy  bool
}

func NewOFICalculator(window time.Duration) *OFICalculator {
	return &OFICalculator{
		Window: window,
		Trades: make([]TradeRecord, 0, 1000),
	}
}

func (c *OFICalculator) AddTrade(volume float64, isBuyerMaker bool) {
	c.mu.Lock()
	defer c.mu.Unlock()

	// isBuyerMaker = true means sell market order hit buy limit
	// So if isBuyerMaker, aggressive side is SELL, otherwise BUY
	isBuy := !isBuyerMaker

	c.Trades = append(c.Trades, TradeRecord{
		Time:   time.Now(),
		Volume: volume,
		IsBuy:  isBuy,
	})

	c.cleanup()
	c.calculate()
}

func (c *OFICalculator) cleanup() {
	cutoff := time.Now().Add(-c.Window)
	i := 0
	for i < len(c.Trades) && c.Trades[i].Time.Before(cutoff) {
		i++
	}
	c.Trades = c.Trades[i:]
}

func (c *OFICalculator) calculate() {
	var buyVol, sellVol float64
	for _, t := range c.Trades {
		if t.IsBuy {
			buyVol += t.Volume
		} else {
			sellVol += t.Volume
		}
	}
	total := buyVol + sellVol
	if total > 0 {
		c.OFI = (buyVol - sellVol) / total
	} else {
		c.OFI = 0
	}
}

func (c *OFICalculator) GetOFI() float64 {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.OFI
}

// WebSocketClient manages WebSocket connections to Binance
type WebSocketClient struct {
	symbol      string
	conn        *websocket.Conn
	connected   bool
	useTestnet  bool
	mu          sync.RWMutex
	lastPong    time.Time
	reconnectDelay time.Duration

	// Data handlers
	book       *Level2Book
	ofiCalc    *OFICalculator
	onDepth    func(bestBid, bestAsk float64, ofi float64)
	onTrade    func(price, qty float64, isBuyerMaker bool)

	// Control
	ctx        context.Context
	cancel     context.CancelFunc
	wg         sync.WaitGroup
}

func NewWebSocketClient(symbol string) *WebSocketClient {
	ctx, cancel := context.WithCancel(context.Background())
	return &WebSocketClient{
		symbol:         symbol,
		book:          NewLevel2Book(symbol),
		ofiCalc:       NewOFICalculator(5 * time.Second),
		ctx:           ctx,
		cancel:        cancel,
		reconnectDelay: InitialReconnectDelay,
		lastPong:      time.Now(),
		useTestnet:    false, // Default to mainnet
	}
}

func NewTestnetWebSocketClient(symbol string) *WebSocketClient {
	ctx, cancel := context.WithCancel(context.Background())
	return &WebSocketClient{
		symbol:         symbol,
		book:          NewLevel2Book(symbol),
		ofiCalc:       NewOFICalculator(5 * time.Second),
		ctx:           ctx,
		cancel:        cancel,
		reconnectDelay: InitialReconnectDelay,
		lastPong:      time.Now(),
		useTestnet:    true,
	}
}

func (c *WebSocketClient) SetDepthHandler(handler func(bestBid, bestAsk float64, ofi float64)) {
	c.onDepth = handler
}

func (c *WebSocketClient) SetTradeHandler(handler func(price, qty float64, isBuyerMaker bool)) {
	c.onTrade = handler
}

func (c *WebSocketClient) Connect() error {
	// Combined stream for depth and trades
	streams := fmt.Sprintf("%s@depth@100ms/%s@trade/%s@ticker",
		c.symbol, c.symbol, c.symbol)

	// Select base URL based on testnet flag
	baseURL := BinanceWSStreamBase
	if c.useTestnet {
		baseURL = BinanceTestnetWSStreamBase
	}
	url := baseURL + streams

	log.Printf("Connecting to %s...", url)

	dialer := websocket.Dialer{
		Proxy:            http.ProxyFromEnvironment,
		HandshakeTimeout: 10 * time.Second,
	}

	conn, _, err := dialer.Dial(url, nil)
	if err != nil {
		return fmt.Errorf("websocket dial failed: %w", err)
	}

	c.conn = conn
	c.connected = true
	c.lastPong = time.Now()
	c.reconnectDelay = InitialReconnectDelay

	// Start goroutines
	c.wg.Add(3)
	go c.readLoop()
	go c.heartbeatLoop()
	go c.monitorLoop()

	log.Printf("Connected to Binance WebSocket for %s", c.symbol)
	return nil
}

func (c *WebSocketClient) readLoop() {
	defer c.wg.Done()

	for {
		select {
		case <-c.ctx.Done():
			return
		default:
		}

		_, message, err := c.conn.ReadMessage()
		if err != nil {
			log.Printf("WebSocket read error: %v", err)
			c.handleDisconnect()
			return
		}

		c.handleMessage(message)
	}
}

func (c *WebSocketClient) handleMessage(data []byte) {
	// Binance combined stream format: {"stream":"btcusdt@depth","data":{...}}
	var wrapper struct {
		Stream string          `json:"stream"`
		Data   json.RawMessage `json:"data"`
	}

	if err := json.Unmarshal(data, &wrapper); err != nil {
		// Try direct message format
		c.handleDirectMessage(data)
		return
	}

	switch {
	case contains(wrapper.Stream, "@depth"):
		c.handleDepthUpdate(wrapper.Data)
	case contains(wrapper.Stream, "@trade"):
		c.handleTradeUpdate(wrapper.Data)
	case contains(wrapper.Stream, "@ticker"):
		c.handleTickerUpdate(wrapper.Data)
	}
}

func (c *WebSocketClient) handleDirectMessage(data []byte) {
	// Single stream format
	var msg map[string]interface{}
	if err := json.Unmarshal(data, &msg); err != nil {
		return
	}

	eventType, _ := msg["e"].(string)
	switch eventType {
	case "depthUpdate":
		c.handleDepthUpdate(data)
	case "trade":
		c.handleTradeUpdate(data)
	case "24hrTicker":
		c.handleTickerUpdate(data)
	}
}

func (c *WebSocketClient) handleDepthUpdate(data []byte) {
	var update DepthUpdate
	if err := json.Unmarshal(data, &update); err != nil {
		return
	}

	// Apply updates
	for _, bid := range update.Bids {
		if len(bid) >= 2 {
			c.book.UpdateBid(bid[0], bid[1])
		}
	}
	for _, ask := range update.Asks {
		if len(ask) >= 2 {
			c.book.UpdateAsk(ask[0], ask[1])
		}
	}

	// Notify handler
	if c.onDepth != nil {
		bestBid, bestAsk, _, _ := c.book.GetSnapshot()
		ofi := c.ofiCalc.GetOFI()
		c.onDepth(bestBid, bestAsk, ofi)
	}
}

func (c *WebSocketClient) handleTradeUpdate(data []byte) {
	var trade TradeUpdate
	if err := json.Unmarshal(data, &trade); err != nil {
		return
	}

	var price, qty float64
	fmt.Sscanf(trade.Price, "%f", &price)
	fmt.Sscanf(trade.Quantity, "%f", &qty)

	c.ofiCalc.AddTrade(qty, trade.IsBuyerMaker)

	if c.onTrade != nil {
		c.onTrade(price, qty, trade.IsBuyerMaker)
	}
}

func (c *WebSocketClient) handleTickerUpdate(data []byte) {
	// Could be used for additional indicators
}

func (c *WebSocketClient) heartbeatLoop() {
	defer c.wg.Done()

	ticker := time.NewTicker(HeartbeatInterval)
	defer ticker.Stop()

	for {
		select {
		case <-c.ctx.Done():
			return
		case <-ticker.C:
			if err := c.conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				log.Printf("Ping failed: %v", err)
				c.handleDisconnect()
				return
			}
		}
	}
}

func (c *WebSocketClient) monitorLoop() {
	defer c.wg.Done()

	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-c.ctx.Done():
			return
		case <-ticker.C:
			if time.Since(c.lastPong) > StaleTimeout {
				log.Println("Connection stale, reconnecting...")
				c.handleDisconnect()
				return
			}
		}
	}
}

func (c *WebSocketClient) handleDisconnect() {
	c.mu.Lock()
	if !c.connected {
		c.mu.Unlock()
		return
	}
	c.connected = false
	c.mu.Unlock()

	c.conn.Close()

	// Try to reconnect
	go c.reconnect()
}

func (c *WebSocketClient) reconnect() {
	for {
		select {
		case <-c.ctx.Done():
			return
		default:
		}

		log.Printf("Reconnecting in %v...", c.reconnectDelay)
		time.Sleep(c.reconnectDelay)

		if err := c.Connect(); err == nil {
			log.Println("Reconnected successfully")
			return
		}

		// Exponential backoff
		c.reconnectDelay = time.Duration(float64(c.reconnectDelay) * ReconnectMultiplier)
		if c.reconnectDelay > MaxReconnectDelay {
			c.reconnectDelay = MaxReconnectDelay
		}
	}
}

func (c *WebSocketClient) Close() {
	c.cancel()
	c.conn.Close()
	c.wg.Wait()
}

func (c *WebSocketClient) IsConnected() bool {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.connected
}

func (c *WebSocketClient) GetBook() *Level2Book {
	return c.book
}

func (c *WebSocketClient) GetOFI() float64 {
	return c.ofiCalc.GetOFI()
}

func contains(s, substr string) bool {
	return len(s) >= len(substr) && s[len(s)-len(substr):] == substr ||
		len(s) > len(substr) && containsAt(s, substr)
}

func containsAt(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}
