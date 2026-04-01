package main

import (
	"fmt"
	"log"
	"strconv"
	"sync"
	"time"

	"github.com/adshao/go-binance/v2"
)

/*
websocket_manager.go - WebSocket Feed Manager

Wraps LiveAPIClient to provide high-level market data functionality:
- Order book management
- OFI (Order Flow Imbalance) calculation
- Trade flow tracking
- Connection state management
*/

// OrderBook represents a simple price level order book
type OrderBook struct {
	mu      sync.RWMutex
	bids    map[float64]float64 // price -> quantity
	asks    map[float64]float64 // price -> quantity
	bestBid float64
	bestAsk float64
}

// NewOrderBook creates a new order book
func NewOrderBook() *OrderBook {
	return &OrderBook{
		bids: make(map[float64]float64),
		asks: make(map[float64]float64),
	}
}

// UpdateBids updates bid side
func (ob *OrderBook) UpdateBids(bids []binance.Bid) {
	ob.mu.Lock()
	defer ob.mu.Unlock()

	for _, b := range bids {
		price, _ := strconv.ParseFloat(b.Price, 64)
		qty, _ := strconv.ParseFloat(b.Quantity, 64)
		if qty == 0 {
			delete(ob.bids, price)
		} else {
			ob.bids[price] = qty
		}
	}

	// Update best bid
	ob.bestBid = 0
	for price := range ob.bids {
		if price > ob.bestBid {
			ob.bestBid = price
		}
	}
}

// UpdateAsks updates ask side
func (ob *OrderBook) UpdateAsks(asks []binance.Ask) {
	ob.mu.Lock()
	defer ob.mu.Unlock()

	for _, a := range asks {
		price, _ := strconv.ParseFloat(a.Price, 64)
		qty, _ := strconv.ParseFloat(a.Quantity, 64)
		if qty == 0 {
			delete(ob.asks, price)
		} else {
			ob.asks[price] = qty
		}
	}

	// Update best ask
	ob.bestAsk = 0
	for price := range ob.asks {
		if ob.bestAsk == 0 || price < ob.bestAsk {
			ob.bestAsk = price
		}
	}
}

// GetSnapshot returns current best bid/ask and volumes
func (ob *OrderBook) GetSnapshot() (bestBid, bestAsk, bidVol, askVol float64) {
	ob.mu.RLock()
	defer ob.mu.RUnlock()

	return ob.bestBid, ob.bestAsk, ob.bids[ob.bestBid], ob.asks[ob.bestAsk]
}

// OFICalculator calculates Order Flow Imbalance
type OFICalculator struct {
	mu           sync.RWMutex
	lastBidPrice float64
	lastBidQty   float64
	lastAskPrice float64
	lastAskQty   float64
	ofi          float64
	tradeFlow    float64
}

// NewOFICalculator creates a new OFI calculator
func NewOFICalculator() *OFICalculator {
	return &OFICalculator{}
}

// UpdateDepth updates OFI from depth change
func (o *OFICalculator) UpdateDepth(bestBid, bestAsk, bidQty, askQty float64) {
	o.mu.Lock()
	defer o.mu.Unlock()

	// Calculate OFI components
	if bestBid > o.lastBidPrice {
		o.ofi += bidQty
	} else if bestBid < o.lastBidPrice {
		o.ofi -= o.lastBidQty
	}

	if bestAsk < o.lastAskPrice {
		o.ofi -= askQty
	} else if bestAsk > o.lastAskPrice {
		o.ofi += o.lastAskQty
	}

	o.lastBidPrice = bestBid
	o.lastBidQty = bidQty
	o.lastAskPrice = bestAsk
	o.lastAskQty = askQty
}

// UpdateTrade updates trade flow from trade
func (o *OFICalculator) UpdateTrade(price, qty float64, isBuyerMaker bool) {
	o.mu.Lock()
	defer o.mu.Unlock()

	if isBuyerMaker {
		o.tradeFlow -= qty // Seller initiated
	} else {
		o.tradeFlow += qty // Buyer initiated
	}
}

// GetOFI returns current OFI value
func (o *OFICalculator) GetOFI() float64 {
	o.mu.RLock()
	defer o.mu.RUnlock()
	return o.ofi
}

// GetTradeFlow returns current trade flow
func (o *OFICalculator) GetTradeFlow() float64 {
	o.mu.RLock()
	defer o.mu.RUnlock()
	return o.tradeFlow
}

// Reset resets OFI calculation
func (o *OFICalculator) Reset() {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.ofi = 0
	o.tradeFlow = 0
}

// WebSocketManager manages WebSocket connections and market data
type WebSocketManager struct {
	client   *LiveAPIClient
	symbol   string
	book     *OrderBook
	ofiCalc  *OFICalculator
	streams  map[string]*ReconnectableWebSocket // 管理所有重连流

	// Handlers
	depthHandler func(bestBid, bestAsk float64, ofi float64)
	tradeHandler func(price, qty float64, isBuyerMaker bool)

	// State
	mu         sync.RWMutex
	connected  bool
	lastUpdate time.Time

	// Callbacks
	onDisconnect func(streamID string, err error)
	onReconnect  func(streamID string, attempt int)
}

// NewWebSocketManager creates a new WebSocket manager
func NewWebSocketManager(symbol string, apiClient *LiveAPIClient) *WebSocketManager {
	return &WebSocketManager{
		client:  apiClient,
		symbol:  symbol,
		book:    NewOrderBook(),
		ofiCalc: NewOFICalculator(),
		streams: make(map[string]*ReconnectableWebSocket),
	}
}

// SetDepthHandler sets depth update handler
func (w *WebSocketManager) SetDepthHandler(handler func(bestBid, bestAsk float64, ofi float64)) {
	w.depthHandler = handler
}

// SetTradeHandler sets trade update handler
func (w *WebSocketManager) SetTradeHandler(handler func(price, qty float64, isBuyerMaker bool)) {
	w.tradeHandler = handler
}

// Connect starts WebSocket connections with auto-reconnect support
func (w *WebSocketManager) Connect() error {
	log.Printf("[WS_MANAGER] Connecting to WebSocket feeds for %s", w.symbol)

	// Create and start depth stream with auto-reconnect
	depthStream := NewReconnectableWebSocket("depth:"+w.symbol, StreamDepth, w.symbol, w.client)
	depthStream.SetDepthHandler(w.handleDepthUpdate)
	depthStream.SetErrorHandler(w.handleStreamError)
	depthStream.SetStateChangeCallback(w.handleStateChange)

	if err := depthStream.Start(); err != nil {
		return fmt.Errorf("failed to start depth stream: %w", err)
	}
	w.streams["depth"] = depthStream

	// Create and start trade stream with auto-reconnect
	tradeStream := NewReconnectableWebSocket("trade:"+w.symbol, StreamTrade, w.symbol, w.client)
	tradeStream.SetTradeHandler(w.handleTradeUpdate)
	tradeStream.SetErrorHandler(w.handleStreamError)
	tradeStream.SetStateChangeCallback(w.handleStateChange)

	if err := tradeStream.Start(); err != nil {
		w.Close()
		return fmt.Errorf("failed to start trade stream: %w", err)
	}
	w.streams["trade"] = tradeStream

	// Create and start book ticker stream with auto-reconnect
	tickerStream := NewReconnectableWebSocket("ticker:"+w.symbol, StreamBookTicker, w.symbol, w.client)
	tickerStream.SetBookTickerHandler(w.handleBookTicker)
	tickerStream.SetErrorHandler(w.handleStreamError)
	tickerStream.SetStateChangeCallback(w.handleStateChange)

	if err := tickerStream.Start(); err != nil {
		w.Close()
		return fmt.Errorf("failed to start ticker stream: %w", err)
	}
	w.streams["ticker"] = tickerStream

	w.mu.Lock()
	w.connected = true
	w.lastUpdate = time.Now()
	w.mu.Unlock()

	log.Printf("[WS_MANAGER] WebSocket feeds connected with auto-reconnect")
	return nil
}

// Close stops all WebSocket connections
func (w *WebSocketManager) Close() {
	log.Println("[WS_MANAGER] Closing WebSocket feeds")

	for name, stream := range w.streams {
		log.Printf("[WS_MANAGER] Stopping %s stream", name)
		stream.Stop()
	}

	w.mu.Lock()
	w.connected = false
	w.mu.Unlock()

	log.Println("[WS_MANAGER] All WebSocket feeds stopped")
}

// IsConnected returns connection status
func (w *WebSocketManager) IsConnected() bool {
	w.mu.RLock()
	defer w.mu.RUnlock()
	return w.connected
}

// GetBook returns the order book
func (w *WebSocketManager) GetBook() *OrderBook {
	return w.book
}

// GetOFI returns current OFI value
func (w *WebSocketManager) GetOFI() float64 {
	return w.ofiCalc.GetOFI()
}

// handleDepthUpdate processes depth updates
func (w *WebSocketManager) handleDepthUpdate(event *binance.WsDepthEvent) {
	w.book.UpdateBids(event.Bids)
	w.book.UpdateAsks(event.Asks)

	bestBid, bestAsk, bidVol, askVol := w.book.GetSnapshot()
	w.ofiCalc.UpdateDepth(bestBid, bestAsk, bidVol, askVol)

	w.mu.Lock()
	w.lastUpdate = time.Now()
	w.mu.Unlock()

	if w.depthHandler != nil {
		w.depthHandler(bestBid, bestAsk, w.ofiCalc.GetOFI())
	}
}

// handleTradeUpdate processes trade updates
func (w *WebSocketManager) handleTradeUpdate(event *binance.WsTradeEvent) {
	price, _ := strconv.ParseFloat(event.Price, 64)
	qty, _ := strconv.ParseFloat(event.Quantity, 64)

	w.ofiCalc.UpdateTrade(price, qty, event.IsBuyerMaker)

	w.mu.Lock()
	w.lastUpdate = time.Now()
	w.mu.Unlock()

	if w.tradeHandler != nil {
		w.tradeHandler(price, qty, event.IsBuyerMaker)
	}
}

// handleBookTicker processes book ticker updates
func (w *WebSocketManager) handleBookTicker(event *binance.WsBookTickerEvent) {
	bestBid, _ := strconv.ParseFloat(event.BestBidPrice, 64)
	bestAsk, _ := strconv.ParseFloat(event.BestAskPrice, 64)
	bidQty, _ := strconv.ParseFloat(event.BestBidQty, 64)
	askQty, _ := strconv.ParseFloat(event.BestAskQty, 64)

	w.ofiCalc.UpdateDepth(bestBid, bestAsk, bidQty, askQty)

	w.mu.Lock()
	w.lastUpdate = time.Now()
	w.mu.Unlock()

	if w.depthHandler != nil {
		w.depthHandler(bestBid, bestAsk, w.ofiCalc.GetOFI())
	}
}

// handleStreamError handles stream errors
func (w *WebSocketManager) handleStreamError(err error) {
	log.Printf("[WS_MANAGER] Stream error: %v", err)
	if w.onDisconnect != nil {
		w.onDisconnect("", err)
	}
}

// handleStateChange handles connection state changes
func (w *WebSocketManager) handleStateChange(streamID string, state ConnectionState) {
	log.Printf("[WS_MANAGER] Stream %s state changed to %s", streamID, state.String())

	switch state {
	case StateConnected:
		w.mu.Lock()
		w.connected = w.checkAllStreamsConnected()
		w.mu.Unlock()
		if w.onReconnect != nil {
			w.onReconnect(streamID, 0)
		}
	case StateDisconnected:
		w.mu.Lock()
		// Check if any stream is still connected
		anyConnected := false
		for _, stream := range w.streams {
			if stream.GetState() == StateConnected {
				anyConnected = true
				break
			}
		}
		w.connected = anyConnected
		w.mu.Unlock()
	}
}

// checkAllStreamsConnected returns true if all streams are connected
func (w *WebSocketManager) checkAllStreamsConnected() bool {
	for _, stream := range w.streams {
		if stream.GetState() != StateConnected {
			return false
		}
	}
	return len(w.streams) > 0
}

// SetDisconnectCallback sets the disconnect callback
func (w *WebSocketManager) SetDisconnectCallback(callback func(streamID string, err error)) {
	w.onDisconnect = callback
}

// SetReconnectCallback sets the reconnect callback
func (w *WebSocketManager) SetReconnectCallback(callback func(streamID string, attempt int)) {
	w.onReconnect = callback
}

// GetStreamStatus returns the status of a specific stream
func (w *WebSocketManager) GetStreamStatus(streamID string) (ConnectionState, bool) {
	w.mu.RLock()
	defer w.mu.RUnlock()
	stream, ok := w.streams[streamID]
	if !ok {
		return StateDisconnected, false
	}
	return stream.GetState(), true
}

// GetAllStreamStatuses returns status of all streams
func (w *WebSocketManager) GetAllStreamStatuses() map[string]ConnectionState {
	w.mu.RLock()
	defer w.mu.RUnlock()

	statuses := make(map[string]ConnectionState, len(w.streams))
	for id, stream := range w.streams {
		statuses[id] = stream.GetState()
	}
	return statuses
}
