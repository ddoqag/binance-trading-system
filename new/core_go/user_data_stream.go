package main

import (
	"fmt"
	"log"
	"sync"
	"time"
)

/*
user_data_stream.go - WebSocket User Data Stream Manager (P5-101)

Manages Binance user data stream for real-time order lifecycle:
- ListenKey lifecycle management (create, renew, close)
- Order update event routing to OrderFSM
- Balance update handling
- Automatic reconnection on failure
- Thread-safe event distribution

Integration:
- Connects LiveAPIClient WebSocket to OrderFSM state machine
- Provides callback registration for order/balance updates
- Supports graceful shutdown and recovery
*/

// UserDataStreamManager manages the user data WebSocket stream
type UserDataStreamManager struct {
	client      *LiveAPIClient
	orderFSM    map[string]*OrderFSM // orderID -> FSM
	fsmMu       sync.RWMutex

	// Event handlers
	onOrderUpdate   func(*OrderUpdate)
	onBalanceUpdate func(*BalanceUpdate)
	onError         func(error)

	// Connection state
	isRunning bool
	stopCh    chan struct{}
	wg        sync.WaitGroup
	mu        sync.Mutex

	// Reconnection config
	reconnectInterval time.Duration
	maxReconnectDelay time.Duration
}

// UserDataStreamConfig configuration for user data stream
type UserDataStreamConfig struct {
	ReconnectInterval time.Duration // Initial reconnect interval (default 5s)
	MaxReconnectDelay time.Duration // Max reconnect delay (default 60s)
}

// DefaultUserDataStreamConfig returns default configuration
func DefaultUserDataStreamConfig() *UserDataStreamConfig {
	return &UserDataStreamConfig{
		ReconnectInterval: 5 * time.Second,
		MaxReconnectDelay: 60 * time.Second,
	}
}

// NewUserDataStreamManager creates a new user data stream manager
func NewUserDataStreamManager(client *LiveAPIClient, config *UserDataStreamConfig) *UserDataStreamManager {
	if config == nil {
		config = DefaultUserDataStreamConfig()
	}

	return &UserDataStreamManager{
		client:            client,
		orderFSM:          make(map[string]*OrderFSM),
		stopCh:            make(chan struct{}),
		reconnectInterval: config.ReconnectInterval,
		maxReconnectDelay: config.MaxReconnectDelay,
	}
}

// SetHandlers sets event handlers
func (m *UserDataStreamManager) SetHandlers(
	onOrder func(*OrderUpdate),
	onBalance func(*BalanceUpdate),
	onError func(error),
) {
	m.onOrderUpdate = onOrder
	m.onBalanceUpdate = onBalance
	m.onError = onError
}

// RegisterOrderFSM registers an OrderFSM for order lifecycle management
func (m *UserDataStreamManager) RegisterOrderFSM(orderID string, fsm *OrderFSM) {
	m.fsmMu.Lock()
	defer m.fsmMu.Unlock()
	m.orderFSM[orderID] = fsm
	log.Printf("[UserDataStream] Registered FSM for order %s", orderID)
}

// UnregisterOrderFSM removes an OrderFSM registration
func (m *UserDataStreamManager) UnregisterOrderFSM(orderID string) {
	m.fsmMu.Lock()
	defer m.fsmMu.Unlock()
	delete(m.orderFSM, orderID)
	log.Printf("[UserDataStream] Unregistered FSM for order %s", orderID)
}

// GetOrderFSM gets the FSM for an order
func (m *UserDataStreamManager) GetOrderFSM(orderID string) *OrderFSM {
	m.fsmMu.RLock()
	defer m.fsmMu.RUnlock()
	return m.orderFSM[orderID]
}

// Start starts the user data stream with automatic reconnection
func (m *UserDataStreamManager) Start() error {
	m.mu.Lock()
	if m.isRunning {
		m.mu.Unlock()
		return fmt.Errorf("user data stream already running")
	}
	m.isRunning = true
	m.stopCh = make(chan struct{})
	m.mu.Unlock()

	// Set up client handlers
	m.client.SetOrderHandler(m.handleOrderUpdate)
	m.client.SetBalanceHandler(m.handleBalanceUpdate)

	// Start connection manager
	m.wg.Add(1)
	go m.connectionManager()

	log.Println("[UserDataStream] Manager started")
	return nil
}

// Stop stops the user data stream
func (m *UserDataStreamManager) Stop() {
	m.mu.Lock()
	if !m.isRunning {
		m.mu.Unlock()
		return
	}
	m.isRunning = false
	close(m.stopCh)
	m.mu.Unlock()

	// Wait for goroutines to finish
	m.wg.Wait()

	log.Println("[UserDataStream] Manager stopped")
}

// IsRunning returns whether the stream is running
func (m *UserDataStreamManager) IsRunning() bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.isRunning
}

// connectionManager manages the WebSocket connection lifecycle
func (m *UserDataStreamManager) connectionManager() {
	defer m.wg.Done()

	reconnectDelay := m.reconnectInterval

	for {
		select {
		case <-m.stopCh:
			return
		default:
		}

		// Try to connect
		log.Println("[UserDataStream] Connecting...")
		err := m.connect()
		if err != nil {
			log.Printf("[UserDataStream] Connection failed: %v", err)
			if m.onError != nil {
				m.onError(err)
			}

			// Wait before reconnecting
			select {
			case <-m.stopCh:
				return
			case <-time.After(reconnectDelay):
				// Exponential backoff
				reconnectDelay *= 2
				if reconnectDelay > m.maxReconnectDelay {
					reconnectDelay = m.maxReconnectDelay
				}
				continue
			}
		}

		// Connection successful, reset delay
		reconnectDelay = m.reconnectInterval
		log.Println("[UserDataStream] Connected successfully")

		// Wait for stop signal (connection runs in background via SDK)
		select {
		case <-m.stopCh:
			return
		}
	}
}

// connect establishes the WebSocket connection
func (m *UserDataStreamManager) connect() error {
	return m.client.StartUserDataStream()
}

// handleOrderUpdate processes order updates from WebSocket
func (m *UserDataStreamManager) handleOrderUpdate(update *OrderUpdate) {
	log.Printf("[UserDataStream] Order update: %s %s %s@%f, status=%s, filled=%f/%f",
		update.Side,
		update.Symbol,
		update.ClientOrderID,
		update.Price,
		update.Status,
		update.CumulativeQty,
		update.Quantity)

	// Route to OrderFSM if registered
	m.fsmMu.RLock()
	fsm, exists := m.orderFSM[update.ClientOrderID]
	m.fsmMu.RUnlock()

	if exists {
		// Convert WebSocket status to OrderState
		newState := m.mapBinanceStatusToState(update.Status)
		if newState != OrderStatePending {
			reason := fmt.Sprintf("%s: filled %f/%f",
				update.ExecutionType,
				update.CumulativeQty,
				update.Quantity)
			if err := fsm.Transition(newState, reason); err != nil {
				log.Printf("[UserDataStream] FSM transition failed: %v", err)
			}
		}
	}

	// Call user handler
	if m.onOrderUpdate != nil {
		m.onOrderUpdate(update)
	}
}

// handleBalanceUpdate processes balance updates from WebSocket
func (m *UserDataStreamManager) handleBalanceUpdate(update *BalanceUpdate) {
	log.Printf("[UserDataStream] Balance update: %s delta=%f",
		update.Asset,
		update.Delta)

	if m.onBalanceUpdate != nil {
		m.onBalanceUpdate(update)
	}
}

// mapBinanceStatusToState maps Binance order status to OrderState
func (m *UserDataStreamManager) mapBinanceStatusToState(status string) OrderState {
	switch status {
	case "NEW":
		return OrderStateOpen
	case "PARTIALLY_FILLED":
		return OrderStatePartiallyFilled
	case "FILLED":
		return OrderStateFilled
	case "CANCELED":
		return OrderStateCancelled
	case "REJECTED":
		return OrderStateRejected
	case "EXPIRED", "EXPIRED_IN_MATCH":
		return OrderStateExpired
	default:
		return OrderStatePending
	}
}

// GetActiveOrderCount returns the number of registered order FSMs
func (m *UserDataStreamManager) GetActiveOrderCount() int {
	m.fsmMu.RLock()
	defer m.fsmMu.RUnlock()
	return len(m.orderFSM)
}

// GetStats returns stream statistics
func (m *UserDataStreamManager) GetStats() map[string]interface{} {
	m.fsmMu.RLock()
	defer m.fsmMu.RUnlock()

	return map[string]interface{}{
		"is_running":    m.IsRunning(),
		"active_orders": len(m.orderFSM),
	}
}
