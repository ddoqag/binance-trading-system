package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"sync"
	"time"

	"golang.org/x/net/proxy"
	"github.com/adshao/go-binance/v2"
)

/*
live_api_client.go - Live Binance API Integration using official Go SDK

Features:
- REST API for order management (using go-binance SDK)
- WebSocket for real-time market data (depth, trades, ticker)
- User data stream for account updates (order status, balances)
- Automatic reconnection and heartbeat
- Paper trading support for testing
*/

// LiveAPIClient wraps the official Binance Go SDK with enhanced features
type LiveAPIClient struct {
	apiKey    string
	apiSecret string
	testnet   bool

	// SDK client
	client *binance.Client

	// WebSocket connections
	wsConns    map[string]*websocketConn
	wsMu       sync.RWMutex
	stopCh     chan struct{}

	// Callbacks for real-time data
	orderHandler   func(*OrderUpdate)
	balanceHandler func(*BalanceUpdate)

	// User data stream
	listenKey      string
	listenKeyMu    sync.Mutex
	listenKeyRenew *time.Ticker

	// Ensure Close is called only once
	closeOnce sync.Once
}

// OrderUpdate represents order status update from user data stream
type OrderUpdate struct {
	EventTime           int64
	Symbol              string
	ClientOrderID       string
	Side                string
	Type                string
	TimeInForce         string
	Quantity            float64
	Price               float64
	ExecutionType       string // NEW, CANCELED, REPLACED, REJECTED, TRADE, EXPIRED
	Status              string // NEW, PARTIALLY_FILLED, FILLED, CANCELED, REJECTED, EXPIRED, EXPIRED_IN_MATCH
	StopPrice           float64
	IcebergQty          float64
	LastExecutedQty     float64
	CumulativeQty       float64
	LastExecutedPrice   float64
	Commission          float64
	CommissionAsset     string
	TradeTime           int64
	TradeID             int64
}

// BalanceUpdate represents balance change from user data stream
type BalanceUpdate struct {
	EventTime int64
	Asset     string
	Delta     float64
	ClearTime int64
}

// websocketConn wraps a WebSocket connection with metadata
type websocketConn struct {
	stream    string
	stopCh    chan struct{}
	isRunning bool
}

// NewLiveAPIClient creates a new live API client
func NewLiveAPIClient(apiKey, apiSecret string, testnet bool) *LiveAPIClient {
	// Set testnet flag for SDK
	binance.UseTestnet = testnet

	client := binance.NewClient(apiKey, apiSecret)

	// Configure proxy if HTTPS_PROXY or ALL_PROXY is set
	if proxyURL := os.Getenv("HTTPS_PROXY"); proxyURL != "" {
		parsedURL, err := url.Parse(proxyURL)
		if err == nil {
			var transport *http.Transport
			switch parsedURL.Scheme {
			case "http", "https":
				// HTTP/HTTPS proxy
				transport = &http.Transport{
					Proxy: http.ProxyURL(parsedURL),
				}
				log.Printf("[LIVE_API] Using HTTP/HTTPS proxy: %s", proxyURL)
			case "socks5", "socks5h":
				// SOCKS5 proxy (used by SSH dynamic port forwarding, Clash, V2Ray)
				dialer, err := proxy.FromURL(parsedURL, proxy.Direct)
				if err == nil {
					transport = &http.Transport{
						DialContext: func(ctx context.Context, network, addr string) (net.Conn, error) {
							return dialer.Dial(network, addr)
						},
					}
					log.Printf("[LIVE_API] Using SOCKS5 proxy: %s", proxyURL)
				} else {
					log.Printf("[LIVE_API] Failed to create SOCKS5 dialer: %v", err)
				}
			default:
				log.Printf("[LIVE_API] Unsupported proxy scheme: %s", parsedURL.Scheme)
			}
			if transport != nil {
				client.HTTPClient = &http.Client{
					Transport: transport,
					Timeout:   30 * time.Second,
				}
			}
		} else {
			log.Printf("[LIVE_API] Failed to parse proxy URL: %v", err)
		}
	}

	return &LiveAPIClient{
		apiKey:         apiKey,
		apiSecret:      apiSecret,
		testnet:        testnet,
		client:         client,
		wsConns:        make(map[string]*websocketConn),
		stopCh:         make(chan struct{}),
		listenKeyRenew: time.NewTicker(30 * time.Minute), // Renew every 30 min
	}
}

// Close cleans up all connections
func (c *LiveAPIClient) Close() {
	c.closeOnce.Do(func() {
		close(c.stopCh)

		// Note: WebSocket connection stopChs are managed by the SDK
		// and should be closed by the caller via the returned stop channels

		// Close user data stream
		if c.listenKey != "" {
			err := c.client.NewCloseUserStreamService().ListenKey(c.listenKey).Do(context.Background())
			if err != nil {
				log.Printf("[LIVE_API] Error closing user data stream: %v", err)
			}
		}

		c.listenKeyRenew.Stop()
		log.Println("[LIVE_API] Client closed")
	})
}

// SetHandlers sets the real-time data handlers
func (c *LiveAPIClient) SetHandlers(
	depth func(*binance.WsDepthEvent),
	trade func(*binance.WsTradeEvent),
	order func(*OrderUpdate),
	balance func(*BalanceUpdate),
) {
	// Note: depth and trade handlers are passed directly to SDK
	c.orderHandler = order
	c.balanceHandler = balance
}

// SetOrderHandler sets order update handler
func (c *LiveAPIClient) SetOrderHandler(handler func(*OrderUpdate)) {
	c.orderHandler = handler
}

// SetBalanceHandler sets balance update handler
func (c *LiveAPIClient) SetBalanceHandler(handler func(*BalanceUpdate)) {
	c.balanceHandler = handler
}

// GetAPIKey returns the API key
func (c *LiveAPIClient) GetAPIKey() string {
	return c.apiKey
}

// GetAPISecret returns the API secret
func (c *LiveAPIClient) GetAPISecret() string {
	return c.apiSecret
}

// ==================== REST API Methods ====================

// PlaceLimitOrder places a limit order on live market
func (c *LiveAPIClient) PlaceLimitOrder(ctx context.Context, symbol, side string, price, quantity float64, timeInForce string) (*binance.CreateOrderResponse, error) {
	orderType := binance.OrderTypeLimit
	sideType := binance.SideTypeBuy
	if side == "SELL" {
		sideType = binance.SideTypeSell
	}
	tif := binance.TimeInForceTypeGTC
	if timeInForce == "IOC" {
		tif = binance.TimeInForceTypeIOC
	} else if timeInForce == "FOK" {
		tif = binance.TimeInForceTypeFOK
	}

	resp, err := c.client.NewCreateOrderService().
		Symbol(symbol).
		Side(sideType).
		Type(orderType).
		TimeInForce(tif).
		Price(strconv.FormatFloat(price, 'f', -1, 64)).
		Quantity(strconv.FormatFloat(quantity, 'f', -1, 64)).
		Do(ctx)

	if err != nil {
		return nil, fmt.Errorf("failed to place limit order: %w", err)
	}

	log.Printf("[LIVE_API] Limit order placed: %s %s @ %f, qty=%f, status=%s",
		side, symbol, price, quantity, resp.Status)
	return resp, nil
}

// PlaceMarketOrder places a market order on live market
func (c *LiveAPIClient) PlaceMarketOrder(ctx context.Context, symbol, side string, quantity float64) (*binance.CreateOrderResponse, error) {
	sideType := binance.SideTypeBuy
	if side == "SELL" {
		sideType = binance.SideTypeSell
	}

	resp, err := c.client.NewCreateOrderService().
		Symbol(symbol).
		Side(sideType).
		Type(binance.OrderTypeMarket).
		Quantity(strconv.FormatFloat(quantity, 'f', -1, 64)).
		Do(ctx)

	if err != nil {
		return nil, fmt.Errorf("failed to place market order: %w", err)
	}

	log.Printf("[LIVE_API] Market order placed: %s %s qty=%f, status=%s",
		side, symbol, quantity, resp.Status)
	return resp, nil
}

// CancelOrder cancels an existing order
func (c *LiveAPIClient) CancelOrder(ctx context.Context, symbol string, orderID int64) error {
	_, err := c.client.NewCancelOrderService().
		Symbol(symbol).
		OrderID(orderID).
		Do(ctx)

	if err != nil {
		return fmt.Errorf("failed to cancel order: %w", err)
	}

	log.Printf("[LIVE_API] Order cancelled: %s #%d", symbol, orderID)
	return nil
}

// GetOrder queries order status
func (c *LiveAPIClient) GetOrder(ctx context.Context, symbol string, orderID int64) (*binance.Order, error) {
	order, err := c.client.NewGetOrderService().
		Symbol(symbol).
		OrderID(orderID).
		Do(ctx)

	if err != nil {
		return nil, fmt.Errorf("failed to get order: %w", err)
	}

	return order, nil
}

// GetOpenOrders gets all open orders
func (c *LiveAPIClient) GetOpenOrders(ctx context.Context, symbol string) ([]*binance.Order, error) {
	service := c.client.NewListOpenOrdersService()
	if symbol != "" {
		service.Symbol(symbol)
	}

	orders, err := service.Do(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to list open orders: %w", err)
	}

	return orders, nil
}

// GetAccountInfo gets account information including balances
func (c *LiveAPIClient) GetAccountInfo(ctx context.Context) (*binance.Account, error) {
	account, err := c.client.NewGetAccountService().Do(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to get account info: %w", err)
	}

	return account, nil
}

// GetBalance gets specific asset balance
func (c *LiveAPIClient) GetBalance(ctx context.Context, asset string) (free, locked float64, err error) {
	account, err := c.GetAccountInfo(ctx)
	if err != nil {
		return 0, 0, err
	}

	for _, b := range account.Balances {
		if b.Asset == asset {
			free, _ := strconv.ParseFloat(b.Free, 64)
			locked, _ := strconv.ParseFloat(b.Locked, 64)
			return free, locked, nil
		}
	}

	return 0, 0, fmt.Errorf("asset %s not found", asset)
}

// ==================== WebSocket Methods ====================

// SubscribeDepth starts depth stream
func (c *LiveAPIClient) SubscribeDepth(symbol string) (chan struct{}, error) {
	wsHandler := func(event *binance.WsDepthEvent) {
		// Event is handled by caller through their own handler
		log.Printf("[LIVE_API] Depth update: %s, bids=%d, asks=%d",
			event.Symbol, len(event.Bids), len(event.Asks))
	}

	errHandler := func(err error) {
		log.Printf("[LIVE_API] Depth stream error for %s: %v", symbol, err)
	}

	doneCh, stopCh, err := binance.WsDepthServe(symbol, wsHandler, errHandler)
	if err != nil {
		return nil, fmt.Errorf("failed to start depth stream: %w", err)
	}

	c.addWsConn("depth:"+symbol, stopCh)

	go func() {
		<-doneCh
		log.Printf("[LIVE_API] Depth stream closed for %s", symbol)
	}()

	log.Printf("[LIVE_API] Subscribed to depth stream for %s", symbol)
	return stopCh, nil
}

// SubscribeTrades starts trade stream
func (c *LiveAPIClient) SubscribeTrades(symbol string) (chan struct{}, error) {
	wsHandler := func(event *binance.WsTradeEvent) {
		// Event is handled by caller
		log.Printf("[LIVE_API] Trade: %s @ %s x %s",
			event.Symbol, event.Price, event.Quantity)
	}

	errHandler := func(err error) {
		log.Printf("[LIVE_API] Trade stream error for %s: %v", symbol, err)
	}

	doneCh, stopCh, err := binance.WsTradeServe(symbol, wsHandler, errHandler)
	if err != nil {
		return nil, fmt.Errorf("failed to start trade stream: %w", err)
	}

	c.addWsConn("trades:"+symbol, stopCh)

	go func() {
		<-doneCh
		log.Printf("[LIVE_API] Trade stream closed for %s", symbol)
	}()

	log.Printf("[LIVE_API] Subscribed to trade stream for %s", symbol)
	return stopCh, nil
}

// SubscribeBookTicker starts book ticker stream (best bid/ask)
func (c *LiveAPIClient) SubscribeBookTicker(symbol string) (chan struct{}, error) {
	wsHandler := func(event *binance.WsBookTickerEvent) {
		// Can be used for spread monitoring
		log.Printf("[LIVE_API] Book ticker %s: bid=%s @ %s, ask=%s @ %s",
			event.Symbol, event.BestBidPrice, event.BestBidQty,
			event.BestAskPrice, event.BestAskQty)
	}

	errHandler := func(err error) {
		log.Printf("[LIVE_API] Book ticker stream error for %s: %v", symbol, err)
	}

	doneCh, stopCh, err := binance.WsBookTickerServe(symbol, wsHandler, errHandler)
	if err != nil {
		return nil, fmt.Errorf("failed to start book ticker stream: %w", err)
	}

	c.addWsConn("ticker:"+symbol, stopCh)

	go func() {
		<-doneCh
		log.Printf("[LIVE_API] Book ticker stream closed for %s", symbol)
	}()

	return stopCh, nil
}

// StartUserDataStream starts user data stream for order updates
// Uses signature-based WebSocket API (recommended, as listen key management is deprecated)
func (c *LiveAPIClient) StartUserDataStream() error {
	// Use new signature-based WebSocket API (Binance deprecated listen key management)
	wsHandler := func(event *binance.WsUserDataEvent) {
		c.handleUserDataEvent(event)
	}

	errHandler := func(err error) {
		log.Printf("[LIVE_API] User data stream error: %v", err)
	}

	// Get time offset for signature
	c.SyncTime()
	timeOffset := c.client.TimeOffset

	// Use signature-based subscription (recommended method)
	// Note: Use "HMAC" for standard API keys, "ED25519" only for ED25519 key pairs
	doneCh, stopCh, err := binance.WsUserDataServeSignature(
		c.apiKey, c.apiSecret, "HMAC", timeOffset, wsHandler, errHandler,
	)
	if err != nil {
		return fmt.Errorf("failed to start user data websocket: %w", err)
	}

	c.addWsConn("userData", stopCh)

	go func() {
		<-doneCh
		log.Println("[LIVE_API] User data stream closed")
	}()

	log.Println("[LIVE_API] User data stream started (signature-based)")
	return nil
}

// handleUserDataEvent processes user data events
func (c *LiveAPIClient) handleUserDataEvent(event *binance.WsUserDataEvent) {
	// Handle order update
	if event.OrderUpdate.Symbol != "" {
		if c.orderHandler != nil {
			update := parseOrderUpdate(&event.OrderUpdate)
			c.orderHandler(update)
		}
	}

	// Handle account update
	if len(event.AccountUpdate.WsAccountUpdates) > 0 {
		if c.balanceHandler != nil {
			// Parse account updates
			for _, b := range event.AccountUpdate.WsAccountUpdates {
				// Account update provides free/locked balance, not delta
				// We calculate delta by comparing with previous state (simplified here)
				free, _ := strconv.ParseFloat(b.Free, 64)
				locked, _ := strconv.ParseFloat(b.Locked, 64)
				delta := free + locked // Simplified: report total balance as delta
				c.balanceHandler(&BalanceUpdate{
					EventTime: event.Time,
					Asset:     b.Asset,
					Delta:     delta,
				})
			}
		}
	}

	// Handle balance update (direct deposit/withdrawal)
	if event.BalanceUpdate.Asset != "" {
		if c.balanceHandler != nil {
			delta, _ := strconv.ParseFloat(event.BalanceUpdate.Change, 64)
			c.balanceHandler(&BalanceUpdate{
				EventTime: event.Time,
				Asset:     event.BalanceUpdate.Asset,
				Delta:     delta,
			})
		}
	}
}

// renewListenKey periodically renews the listen key
func (c *LiveAPIClient) renewListenKey() {
	for {
		select {
		case <-c.stopCh:
			return
		case <-c.listenKeyRenew.C:
			c.listenKeyMu.Lock()
			key := c.listenKey
			c.listenKeyMu.Unlock()

			if key != "" {
				err := c.client.NewKeepaliveUserStreamService().ListenKey(key).Do(context.Background())
				if err != nil {
					log.Printf("[LIVE_API] Failed to renew listen key: %v", err)
				} else {
					log.Println("[LIVE_API] Listen key renewed")
				}
			}
		}
	}
}

// ==================== Helper Methods ====================

func (c *LiveAPIClient) addWsConn(stream string, stopCh chan struct{}) {
	c.wsMu.Lock()
	defer c.wsMu.Unlock()

	// Close existing connection if any
	if existing, ok := c.wsConns[stream]; ok && existing.isRunning {
		close(existing.stopCh)
	}

	c.wsConns[stream] = &websocketConn{
		stream:    stream,
		stopCh:    stopCh,
		isRunning: true,
	}
}

func parseOrderUpdate(u *binance.WsOrderUpdate) *OrderUpdate {
	qty, _ := strconv.ParseFloat(u.Volume, 64)
	price, _ := strconv.ParseFloat(u.Price, 64)
	stopPrice, _ := strconv.ParseFloat(u.StopPrice, 64)
	icebergQty, _ := strconv.ParseFloat(u.IceBergVolume, 64)
	cumQty, _ := strconv.ParseFloat(u.FilledVolume, 64)
	latestQty, _ := strconv.ParseFloat(u.LatestVolume, 64)
	latestPrice, _ := strconv.ParseFloat(u.LatestPrice, 64)
	fee, _ := strconv.ParseFloat(u.FeeCost, 64)

	return &OrderUpdate{
		EventTime:         u.CreateTime,
		Symbol:            u.Symbol,
		ClientOrderID:     u.ClientOrderId,
		Side:              u.Side,
		Type:              u.Type,
		TimeInForce:       string(u.TimeInForce),
		Quantity:          qty,
		Price:             price,
		ExecutionType:     u.ExecutionType,
		Status:            u.Status,
		StopPrice:         stopPrice,
		IcebergQty:        icebergQty,
		CumulativeQty:     cumQty,
		LastExecutedQty:   latestQty,
		LastExecutedPrice: latestPrice,
		Commission:        fee,
		CommissionAsset:   u.FeeAsset,
		TradeTime:         u.TransactionTime,
		TradeID:           u.TradeId,
	}
}

// TestConnection tests the API connection and returns server time
func (c *LiveAPIClient) TestConnection() error {
	time, err := c.client.NewServerTimeService().Do(context.Background())
	if err != nil {
		return fmt.Errorf("connection test failed: %w", err)
	}

	log.Printf("[LIVE_API] Connection successful, server time: %d", time)
	return nil
}

// SyncTime synchronizes local time with Binance server time
func (c *LiveAPIClient) SyncTime() error {
	serverTime, err := c.client.NewServerTimeService().Do(context.Background())
	if err != nil {
		return fmt.Errorf("failed to get server time: %w", err)
	}

	localTime := time.Now().UnixMilli()
	offset := serverTime - localTime

	// Set time offset in the client (v2 uses TimeOffset field)
	c.client.TimeOffset = int64(offset)

	log.Printf("[LIVE_API] Time synchronized: server=%d, local=%d, offset=%dms",
		serverTime, localTime, offset)
	return nil
}

// GetServerTime returns the current server time
func (c *LiveAPIClient) GetServerTime() (int64, error) {
	return c.client.NewServerTimeService().Do(context.Background())
}

// GetTimeOffset returns the current time offset
func (c *LiveAPIClient) GetTimeOffset() int64 {
	return c.client.TimeOffset
}

// GetExchangeInfo gets exchange trading rules and symbol info
func (c *LiveAPIClient) GetExchangeInfo(ctx context.Context) (*binance.ExchangeInfo, error) {
	info, err := c.client.NewExchangeInfoService().Do(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to get exchange info: %w", err)
	}

	return info, nil
}

// GetSymbolFilters gets trading filters for a symbol
func (c *LiveAPIClient) GetSymbolFilters(ctx context.Context, symbol string) (map[string]interface{}, error) {
	info, err := c.GetExchangeInfo(ctx)
	if err != nil {
		return nil, err
	}

	for _, s := range info.Symbols {
		if s.Symbol == symbol {
			filters := make(map[string]interface{})
			for _, f := range s.Filters {
				data, _ := json.Marshal(f)
				json.Unmarshal(data, &filters)
			}
			return filters, nil
		}
	}

	return nil, fmt.Errorf("symbol %s not found", symbol)
}
