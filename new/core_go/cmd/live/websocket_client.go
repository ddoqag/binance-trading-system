package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"net/url"
	"os"
	"sync"
	"time"

	"github.com/adshao/go-binance/v2"
	"github.com/gorilla/websocket"
)

// WebSocketClient WebSocket客户端
type WebSocketClient struct {
	apiKey     string
	apiSecret  string
	symbol     string
	testnet    bool
	client     *binance.Client  // 重用已配置代理的client

	// 连接
	wsConn     *websocket.Conn
	mu         sync.RWMutex

	// 状态
	isRunning  bool
	stopCh     chan struct{}
	reconnectCh chan struct{}

	// 处理器
	priceHandler    func(bid, ask float64)
	tradeHandler    func(trade *WsTrade)
	orderHandler    func(exec *binance.WsUserDataEvent)

	// 统计
	lastPingTime    time.Time
	reconnectCount  int
}

// WsTrade WebSocket交易数据
type WsTrade struct {
	Symbol    string
	Price     float64
	Quantity  float64
	Time      int64
	IsBuyerMaker bool
}

// NewWebSocketClient 创建WebSocket客户端
// client: 已配置代理的binance client（从live_api_client重用）
func NewWebSocketClient(client *binance.Client, apiKey, apiSecret, symbol string, testnet bool) *WebSocketClient {
	// 检查环境变量
	if os.Getenv("USE_TESTNET") == "true" {
		testnet = true
	}

	return &WebSocketClient{
		apiKey:      apiKey,
		apiSecret:   apiSecret,
		symbol:      symbol,
		testnet:     testnet,
		client:      client,  // 重用已配置代理的client
		stopCh:      make(chan struct{}),
		reconnectCh: make(chan struct{}, 1),
	}
}

// SetPriceHandler 设置价格处理器
func (wsc *WebSocketClient) SetPriceHandler(handler func(bid, ask float64)) {
	wsc.priceHandler = handler
}

// SetTradeHandler 设置交易处理器
func (wsc *WebSocketClient) SetTradeHandler(handler func(trade *WsTrade)) {
	wsc.tradeHandler = handler
}

// SetOrderHandler 设置订单处理器
func (wsc *WebSocketClient) SetOrderHandler(handler func(exec *binance.WsUserDataEvent)) {
	wsc.orderHandler = handler
}

// Start 启动WebSocket连接
func (wsc *WebSocketClient) Start() error {
	wsc.mu.Lock()
	defer wsc.mu.Unlock()
	
	if wsc.isRunning {
		return nil
	}
	
	wsc.isRunning = true
	
	// 启动Book Ticker连接
	go wsc.runBookTicker()
	
	// 启动用户数据流
	go wsc.runUserDataStream()
	
	log.Printf("[WebSocket] Started for %s", wsc.symbol)
	return nil
}

// Stop 停止WebSocket连接
func (wsc *WebSocketClient) Stop() {
	wsc.mu.Lock()
	defer wsc.mu.Unlock()
	
	if !wsc.isRunning {
		return
	}
	
	wsc.isRunning = false
	close(wsc.stopCh)
	
	if wsc.wsConn != nil {
		wsc.wsConn.Close()
	}
	
	log.Printf("[WebSocket] Stopped")
}

// runBookTicker 运行Book Ticker WebSocket
func (wsc *WebSocketClient) runBookTicker() {
	for {
		select {
		case <-wsc.stopCh:
			return
		default:
		}
		
		err := wsc.connectBookTicker()
		if err != nil {
			log.Printf("[WebSocket] BookTicker error: %v, reconnecting...", err)
			time.Sleep(5 * time.Second)
			continue
		}
		
		// 等待重连信号或停止信号
		select {
		case <-wsc.stopCh:
			return
		case <-wsc.reconnectCh:
			log.Printf("[WebSocket] Reconnecting BookTicker...")
			time.Sleep(1 * time.Second)
		}
	}
}

// connectBookTicker 连接Book Ticker
func (wsc *WebSocketClient) connectBookTicker() error {
	// 构建WebSocket URL
	wsURL := fmt.Sprintf("wss://stream.binance.com:9443/ws/%s@bookTicker", 
		wsc.symbol)
	if wsc.testnet {
		wsURL = fmt.Sprintf("wss://testnet.binance.vision/ws/%s@bookTicker",
			wsc.symbol)
	}
	
	// 使用代理
	dialer := websocket.DefaultDialer
	if proxyURL := os.Getenv("HTTPS_PROXY"); proxyURL != "" {
		parsedURL, err := url.Parse(proxyURL)
		if err == nil {
			dialer.Proxy = http.ProxyURL(parsedURL)
		}
	}
	
	conn, _, err := dialer.Dial(wsURL, nil)
	if err != nil {
		return fmt.Errorf("failed to dial: %w", err)
	}
	defer conn.Close()
	
	wsc.mu.Lock()
	wsc.wsConn = conn
	wsc.mu.Unlock()
	
	log.Printf("[WebSocket] BookTicker connected")
	
	// 读取消息
	for {
		select {
		case <-wsc.stopCh:
			return nil
		default:
		}
		
		conn.SetReadDeadline(time.Now().Add(30 * time.Second))
		
		messageType, data, err := conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseAbnormalClosure) {
				log.Printf("[WebSocket] Read error: %v", err)
			}
			return err
		}
		
		if messageType != websocket.TextMessage {
			continue
		}
		
		// 解析Book Ticker数据
		var ticker struct {
			Symbol   string `json:"s"`
			BidPrice string `json:"b"`
			BidQty   string `json:"B"`
			AskPrice string `json:"a"`
			AskQty   string `json:"A"`
		}
		
		if err := json.Unmarshal(data, &ticker); err != nil {
			continue
		}
		
		bid := parseFloat(ticker.BidPrice)
		ask := parseFloat(ticker.AskPrice)
		
		// 调用处理器
		if wsc.priceHandler != nil {
			wsc.priceHandler(bid, ask)
		}
	}
}

// runUserDataStream 运行用户数据流
func (wsc *WebSocketClient) runUserDataStream() {
	for {
		select {
		case <-wsc.stopCh:
			return
		default:
		}
		
		err := wsc.connectUserDataStream()
		if err != nil {
			log.Printf("[WebSocket] UserDataStream error: %v, reconnecting...", err)
			time.Sleep(10 * time.Second)
			continue
		}
		
		// 等待停止信号
		select {
		case <-wsc.stopCh:
			return
		}
	}
}

// connectUserDataStream 连接用户数据流 (使用签名认证，Binance已废弃listen key)
func (wsc *WebSocketClient) connectUserDataStream() error {
	// 使用签名认证的WebSocket API (推荐方式，listen key管理已被废弃)
	errHandler := func(err error) {
		log.Printf("[WebSocket] User data stream error: %v", err)
	}

	// 获取服务器时间并同步
	serverTime, err := wsc.client.NewServerTimeService().Do(context.Background())
	if err != nil {
		return fmt.Errorf("failed to get server time: %w", err)
	}
	localTime := time.Now().UnixMilli()
	timeOffset := serverTime - localTime

	// 使用签名方式订阅用户数据流 (HMAC用于标准API密钥)
	doneCh, _, err := binance.WsUserDataServeSignature(
		wsc.apiKey, wsc.apiSecret, "HMAC", timeOffset,
		func(event *binance.WsUserDataEvent) {
			// 处理订单更新
			if event.OrderUpdate.Symbol != "" && wsc.orderHandler != nil {
				wsc.orderHandler(event)
			}
			// 处理账户更新
			if len(event.AccountUpdate.WsAccountUpdates) > 0 {
				log.Printf("[WebSocket] Account position updated")
			}
		},
		errHandler,
	)
	if err != nil {
		return fmt.Errorf("failed to start user data stream: %w", err)
	}

	log.Printf("[WebSocket] UserDataStream connected (signature-based)")

	// 等待连接关闭或停止信号
	select {
	case <-wsc.stopCh:
		return nil
	case <-doneCh:
		return fmt.Errorf("user data stream closed")
	}
}

// IsConnected 是否已连接
func (wsc *WebSocketClient) IsConnected() bool {
	wsc.mu.RLock()
	defer wsc.mu.RUnlock()
	return wsc.wsConn != nil && wsc.isRunning
}

// GetReconnectCount 获取重连次数
func (wsc *WebSocketClient) GetReconnectCount() int {
	wsc.mu.RLock()
	defer wsc.mu.RUnlock()
	return wsc.reconnectCount
}
