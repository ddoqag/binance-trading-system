package main

import (
	"fmt"
	"log"
	"sync"
	"time"

	"github.com/adshao/go-binance/v2"
)

// ConnectionState represents the WebSocket connection state
type ConnectionState int

const (
	StateDisconnected ConnectionState = iota
	StateConnecting
	StateConnected
)

func (s ConnectionState) String() string {
	switch s {
	case StateDisconnected:
		return "Disconnected"
	case StateConnecting:
		return "Connecting"
	case StateConnected:
		return "Connected"
	default:
		return "Unknown"
	}
}

// StreamType represents the type of WebSocket stream
type StreamType int

const (
	StreamDepth StreamType = iota
	StreamTrade
	StreamBookTicker
	StreamUserData
)

func (t StreamType) String() string {
	switch t {
	case StreamDepth:
		return "Depth"
	case StreamTrade:
		return "Trade"
	case StreamBookTicker:
		return "BookTicker"
	case StreamUserData:
		return "UserData"
	default:
		return "Unknown"
	}
}

// ReconnectConfig holds configuration for reconnection behavior
type ReconnectConfig struct {
	InitialDelay    time.Duration
	MaxDelay        time.Duration
	Multiplier      float64
	MaxAttempts     int
	HealthInterval  time.Duration
	StaleThreshold  time.Duration
}

// DefaultReconnectConfig returns the default reconnection configuration
func DefaultReconnectConfig() *ReconnectConfig {
	return &ReconnectConfig{
		InitialDelay:   1 * time.Second,
		MaxDelay:       60 * time.Second,
		Multiplier:     2.0,
		MaxAttempts:    10,
		HealthInterval: 30 * time.Second,
		StaleThreshold: 60 * time.Second,
	}
}

// MessageHandler is a generic message handler type
type MessageHandler interface{}

// StateChangeCallback is called when connection state changes
type StateChangeCallback func(streamID string, state ConnectionState)

// ReconnectableWebSocket wraps a WebSocket connection with automatic reconnection
type ReconnectableWebSocket struct {
	streamID    string
	symbol      string
	streamType  StreamType
	listenKey   string // For user data stream
	client      *LiveAPIClient

	// State
	state      ConnectionState
	stateMu    sync.RWMutex

	// Reconnection control
	config         *ReconnectConfig
	reconnectDelay time.Duration
	reconnectCount int
	isRunning      bool
	runningMu      sync.RWMutex

	// Channels
	stopCh      chan struct{}
	reconnectCh chan struct{}
	msgCh       chan interface{}

	// Handlers
	depthHandler      func(*binance.WsDepthEvent)
	tradeHandler      func(*binance.WsTradeEvent)
	bookTickerHandler func(*binance.WsBookTickerEvent)
	userDataHandler   func(*binance.WsUserDataEvent)
	errorHandler      func(error)
	stateChangeCb     StateChangeCallback

	// Health check
	lastMessageTime time.Time
	healthTicker    *time.Ticker

	// SDK connection control
	sdkStopCh chan struct{}
}

// NewReconnectableWebSocket creates a new reconnectable WebSocket
func NewReconnectableWebSocket(streamID string, streamType StreamType, symbol string, client *LiveAPIClient) *ReconnectableWebSocket {
	return &ReconnectableWebSocket{
		streamID:       streamID,
		streamType:     streamType,
		symbol:         symbol,
		client:         client,
		config:         DefaultReconnectConfig(),
		reconnectDelay: DefaultReconnectConfig().InitialDelay,
		state:          StateDisconnected,
		stopCh:         make(chan struct{}),
		reconnectCh:    make(chan struct{}, 1),
		msgCh:          make(chan interface{}, 100),
		sdkStopCh:      make(chan struct{}),
	}
}

// SetDepthHandler sets the depth update handler
func (rw *ReconnectableWebSocket) SetDepthHandler(handler func(*binance.WsDepthEvent)) {
	rw.depthHandler = handler
}

// SetTradeHandler sets the trade update handler
func (rw *ReconnectableWebSocket) SetTradeHandler(handler func(*binance.WsTradeEvent)) {
	rw.tradeHandler = handler
}

// SetBookTickerHandler sets the book ticker handler
func (rw *ReconnectableWebSocket) SetBookTickerHandler(handler func(*binance.WsBookTickerEvent)) {
	rw.bookTickerHandler = handler
}

// SetUserDataHandler sets the user data handler
func (rw *ReconnectableWebSocket) SetUserDataHandler(handler func(*binance.WsUserDataEvent)) {
	rw.userDataHandler = handler
}

// SetErrorHandler sets the error handler
func (rw *ReconnectableWebSocket) SetErrorHandler(handler func(error)) {
	rw.errorHandler = handler
}

// SetStateChangeCallback sets the state change callback
func (rw *ReconnectableWebSocket) SetStateChangeCallback(callback StateChangeCallback) {
	rw.stateChangeCb = callback
}

// SetListenKey sets the listen key for user data stream
func (rw *ReconnectableWebSocket) SetListenKey(listenKey string) {
	rw.listenKey = listenKey
}

// SetConfig sets the reconnection configuration
func (rw *ReconnectableWebSocket) SetConfig(config *ReconnectConfig) {
	rw.config = config
	rw.reconnectDelay = config.InitialDelay
}

// Start begins the WebSocket connection with automatic reconnection
func (rw *ReconnectableWebSocket) Start() error {
	rw.runningMu.Lock()
	defer rw.runningMu.Unlock()

	if rw.isRunning {
		return fmt.Errorf("websocket already running")
	}

	rw.isRunning = true
	rw.stopCh = make(chan struct{})
	rw.reconnectCh = make(chan struct{}, 1)

	// Initial connection
	rw.setState(StateConnecting)
	if err := rw.connect(); err != nil {
		rw.isRunning = false
		rw.setState(StateDisconnected)
		return fmt.Errorf("initial connection failed: %w", err)
	}

	// Start reconnection goroutine
	go rw.reconnectLoop()

	// Start health check
	if rw.config.HealthInterval > 0 {
		rw.healthTicker = time.NewTicker(rw.config.HealthInterval)
		go rw.healthCheckLoop()
	}

	log.Printf("[RECONNECTABLE_WS] Started %s stream for %s", rw.streamType, rw.symbol)
	return nil
}

// Stop gracefully stops the WebSocket connection
func (rw *ReconnectableWebSocket) Stop() {
	rw.runningMu.Lock()
	if !rw.isRunning {
		rw.runningMu.Unlock()
		return
	}
	rw.isRunning = false
	rw.runningMu.Unlock()

	close(rw.stopCh)

	if rw.healthTicker != nil {
		rw.healthTicker.Stop()
	}

	// Close SDK connection
	close(rw.sdkStopCh)

	rw.setState(StateDisconnected)
	log.Printf("[RECONNECTABLE_WS] Stopped %s stream for %s", rw.streamType, rw.symbol)
}

// IsRunning returns whether the websocket is running
func (rw *ReconnectableWebSocket) IsRunning() bool {
	rw.runningMu.RLock()
	defer rw.runningMu.RUnlock()
	return rw.isRunning
}

// GetState returns the current connection state
func (rw *ReconnectableWebSocket) GetState() ConnectionState {
	rw.stateMu.RLock()
	defer rw.stateMu.RUnlock()
	return rw.state
}

// GetReconnectCount returns the number of reconnection attempts
func (rw *ReconnectableWebSocket) GetReconnectCount() int {
	rw.stateMu.RLock()
	defer rw.stateMu.RUnlock()
	return rw.reconnectCount
}

// setState updates the connection state and notifies callback
func (rw *ReconnectableWebSocket) setState(state ConnectionState) {
	rw.stateMu.Lock()
	oldState := rw.state
	rw.state = state
	rw.stateMu.Unlock()

	if oldState != state && rw.stateChangeCb != nil {
		rw.stateChangeCb(rw.streamID, state)
	}
}

// updateLastMessageTime updates the last message timestamp
func (rw *ReconnectableWebSocket) updateLastMessageTime() {
	rw.stateMu.Lock()
	rw.lastMessageTime = time.Now()
	rw.stateMu.Unlock()
}

// connect establishes the WebSocket connection
func (rw *ReconnectableWebSocket) connect() error {
	// Create new stop channel for this connection attempt
	rw.sdkStopCh = make(chan struct{})

	switch rw.streamType {
	case StreamDepth:
		return rw.connectDepth()
	case StreamTrade:
		return rw.connectTrade()
	case StreamBookTicker:
		return rw.connectBookTicker()
	case StreamUserData:
		return rw.connectUserData()
	default:
		return fmt.Errorf("unknown stream type: %v", rw.streamType)
	}
}

// connectDepth establishes depth stream connection
func (rw *ReconnectableWebSocket) connectDepth() error {
	wsHandler := func(event *binance.WsDepthEvent) {
		rw.updateLastMessageTime()
		if rw.depthHandler != nil {
			rw.depthHandler(event)
		}
	}

	errHandler := func(err error) {
		log.Printf("[RECONNECTABLE_WS] Depth stream error for %s: %v", rw.symbol, err)
		if rw.errorHandler != nil {
			rw.errorHandler(err)
		}
		rw.triggerReconnect()
	}

	doneCh, _, err := binance.WsDepthServe(rw.symbol, wsHandler, errHandler)
	if err != nil {
		return err
	}

	rw.setState(StateConnected)
	rw.resetReconnectDelay()

	// Monitor connection
	go func() {
		select {
		case <-doneCh:
			log.Printf("[RECONNECTABLE_WS] Depth stream closed for %s", rw.symbol)
			if rw.IsRunning() {
				rw.triggerReconnect()
			}
		case <-rw.sdkStopCh:
			return
		}
	}()

	return nil
}

// connectTrade establishes trade stream connection
func (rw *ReconnectableWebSocket) connectTrade() error {
	wsHandler := func(event *binance.WsTradeEvent) {
		rw.updateLastMessageTime()
		if rw.tradeHandler != nil {
			rw.tradeHandler(event)
		}
	}

	errHandler := func(err error) {
		log.Printf("[RECONNECTABLE_WS] Trade stream error for %s: %v", rw.symbol, err)
		if rw.errorHandler != nil {
			rw.errorHandler(err)
		}
		rw.triggerReconnect()
	}

	doneCh, _, err := binance.WsTradeServe(rw.symbol, wsHandler, errHandler)
	if err != nil {
		return err
	}

	rw.setState(StateConnected)
	rw.resetReconnectDelay()

	go func() {
		select {
		case <-doneCh:
			log.Printf("[RECONNECTABLE_WS] Trade stream closed for %s", rw.symbol)
			if rw.IsRunning() {
				rw.triggerReconnect()
			}
		case <-rw.sdkStopCh:
			return
		}
	}()

	return nil
}

// connectBookTicker establishes book ticker stream connection
func (rw *ReconnectableWebSocket) connectBookTicker() error {
	wsHandler := func(event *binance.WsBookTickerEvent) {
		rw.updateLastMessageTime()
		if rw.bookTickerHandler != nil {
			rw.bookTickerHandler(event)
		}
	}

	errHandler := func(err error) {
		log.Printf("[RECONNECTABLE_WS] Book ticker stream error for %s: %v", rw.symbol, err)
		if rw.errorHandler != nil {
			rw.errorHandler(err)
		}
		rw.triggerReconnect()
	}

	doneCh, _, err := binance.WsBookTickerServe(rw.symbol, wsHandler, errHandler)
	if err != nil {
		return err
	}

	rw.setState(StateConnected)
	rw.resetReconnectDelay()

	go func() {
		select {
		case <-doneCh:
			log.Printf("[RECONNECTABLE_WS] Book ticker stream closed for %s", rw.symbol)
			if rw.IsRunning() {
				rw.triggerReconnect()
			}
		case <-rw.sdkStopCh:
			return
		}
	}()

	return nil
}

// connectUserData establishes user data stream connection
func (rw *ReconnectableWebSocket) connectUserData() error {
	if rw.listenKey == "" {
		return fmt.Errorf("listen key required for user data stream")
	}

	wsHandler := func(event *binance.WsUserDataEvent) {
		rw.updateLastMessageTime()
		if rw.userDataHandler != nil {
			rw.userDataHandler(event)
		}
	}

	errHandler := func(err error) {
		log.Printf("[RECONNECTABLE_WS] User data stream error: %v", err)
		if rw.errorHandler != nil {
			rw.errorHandler(err)
		}
		rw.triggerReconnect()
	}

	doneCh, _, err := binance.WsUserDataServe(rw.listenKey, wsHandler, errHandler)
	if err != nil {
		return err
	}

	rw.setState(StateConnected)
	rw.resetReconnectDelay()

	go func() {
		select {
		case <-doneCh:
			log.Printf("[RECONNECTABLE_WS] User data stream closed")
			if rw.IsRunning() {
				rw.triggerReconnect()
			}
		case <-rw.sdkStopCh:
			return
		}
	}()

	return nil
}

// triggerReconnect signals the reconnection goroutine to reconnect
func (rw *ReconnectableWebSocket) triggerReconnect() {
	select {
	case rw.reconnectCh <- struct{}{}:
	default:
		// Channel already has a pending reconnect
	}
}

// reconnectLoop handles automatic reconnection with exponential backoff
func (rw *ReconnectableWebSocket) reconnectLoop() {
	for {
		select {
		case <-rw.stopCh:
			return
		case <-rw.reconnectCh:
			rw.performReconnect()
		}
	}
}

// performReconnect performs a single reconnection attempt
func (rw *ReconnectableWebSocket) performReconnect() {
	rw.setState(StateConnecting)

	// Check max attempts
	if rw.config.MaxAttempts > 0 && rw.reconnectCount >= rw.config.MaxAttempts {
		err := fmt.Errorf("max reconnect attempts (%d) reached for %s", rw.config.MaxAttempts, rw.streamID)
		log.Printf("[RECONNECTABLE_WS] %v", err)
		rw.setState(StateDisconnected)
		if rw.errorHandler != nil {
			rw.errorHandler(err)
		}
		return
	}

	// Calculate backoff delay
	delay := rw.calculateNextDelay()
	log.Printf("[RECONNECTABLE_WS] Reconnecting to %s in %v (attempt %d/%d)",
		rw.streamID, delay, rw.reconnectCount+1, rw.config.MaxAttempts)

	// Wait with cancellation support
	select {
	case <-time.After(delay):
		// Continue to reconnect
	case <-rw.stopCh:
		return
	}

	// Attempt connection
	if err := rw.connect(); err != nil {
		rw.reconnectCount++
		log.Printf("[RECONNECTABLE_WS] Reconnect attempt %d failed for %s: %v",
			rw.reconnectCount, rw.streamID, err)
		if rw.errorHandler != nil {
			rw.errorHandler(fmt.Errorf("reconnect attempt %d failed: %w", rw.reconnectCount, err))
		}
		// Trigger another reconnect attempt
		rw.triggerReconnect()
		return
	}

	// Success
	log.Printf("[RECONNECTABLE_WS] Successfully reconnected to %s", rw.streamID)
}

// calculateNextDelay returns the next reconnection delay using exponential backoff
func (rw *ReconnectableWebSocket) calculateNextDelay() time.Duration {
	delay := rw.reconnectDelay
	rw.reconnectDelay = time.Duration(float64(rw.reconnectDelay) * rw.config.Multiplier)
	if rw.reconnectDelay > rw.config.MaxDelay {
		rw.reconnectDelay = rw.config.MaxDelay
	}
	return delay
}

// resetReconnectDelay resets the reconnection delay to initial value
func (rw *ReconnectableWebSocket) resetReconnectDelay() {
	rw.stateMu.Lock()
	rw.reconnectDelay = rw.config.InitialDelay
	rw.reconnectCount = 0
	rw.stateMu.Unlock()
}

// healthCheckLoop periodically checks connection health
func (rw *ReconnectableWebSocket) healthCheckLoop() {
	for {
		select {
		case <-rw.stopCh:
			return
		case <-rw.healthTicker.C:
			rw.checkHealth()
		}
	}
}

// checkHealth checks if the connection is healthy
func (rw *ReconnectableWebSocket) checkHealth() {
	rw.stateMu.RLock()
	lastMsg := rw.lastMessageTime
	state := rw.state
	rw.stateMu.RUnlock()

	// Only check if we're supposed to be connected
	if state != StateConnected {
		return
	}

	// Check if data is stale
	if time.Since(lastMsg) > rw.config.StaleThreshold {
		log.Printf("[RECONNECTABLE_WS] Connection %s appears stale (last message %v ago), triggering reconnect",
			rw.streamID, time.Since(lastMsg))
		if rw.errorHandler != nil {
			rw.errorHandler(fmt.Errorf("connection stale: no messages for %v", time.Since(lastMsg)))
		}
		rw.triggerReconnect()
	}
}
