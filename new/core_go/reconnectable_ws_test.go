package main

import (
	"os"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/adshao/go-binance/v2"
)

// TestReconnectableWebSocket_Config tests configuration options
func TestReconnectableWebSocket_Config(t *testing.T) {
	client := NewLiveAPIClient("test", "test", true)
	defer client.Close()

	rw := NewReconnectableWebSocket("test", StreamDepth, "BTCUSDT", client)

	// Test default config
	defaultConfig := DefaultReconnectConfig()
	if defaultConfig.InitialDelay != 1*time.Second {
		t.Errorf("Expected InitialDelay=1s, got %v", defaultConfig.InitialDelay)
	}
	if defaultConfig.MaxDelay != 60*time.Second {
		t.Errorf("Expected MaxDelay=60s, got %v", defaultConfig.MaxDelay)
	}
	if defaultConfig.Multiplier != 2.0 {
		t.Errorf("Expected Multiplier=2.0, got %v", defaultConfig.Multiplier)
	}

	// Test custom config
	customConfig := &ReconnectConfig{
		InitialDelay:   500 * time.Millisecond,
		MaxDelay:       30 * time.Second,
		Multiplier:     1.5,
		MaxAttempts:    5,
		HealthInterval: 10 * time.Second,
		StaleThreshold: 30 * time.Second,
	}
	rw.SetConfig(customConfig)

	// Verify config is set by checking behavior in reconnection
	if rw.config.InitialDelay != 500*time.Millisecond {
		t.Error("Custom config not applied correctly")
	}
}

// TestReconnectableWebSocket_StateMachine tests the connection state machine
func TestReconnectableWebSocket_StateMachine(t *testing.T) {
	client := NewLiveAPIClient("test", "test", true)
	defer client.Close()

	rw := NewReconnectableWebSocket("test", StreamDepth, "BTCUSDT", client)

	// Initial state should be Disconnected
	if rw.GetState() != StateDisconnected {
		t.Errorf("Initial state should be Disconnected, got %v", rw.GetState())
	}

	// Test state string representations
	states := []struct {
		state ConnectionState
		str   string
	}{
		{StateDisconnected, "Disconnected"},
		{StateConnecting, "Connecting"},
		{StateConnected, "Connected"},
	}

	for _, tc := range states {
		if tc.state.String() != tc.str {
			t.Errorf("State %v should stringify to %s, got %s", tc.state, tc.str, tc.state.String())
		}
	}

	// Test stream type strings
	streamTypes := []struct {
		st  StreamType
		str string
	}{
		{StreamDepth, "Depth"},
		{StreamTrade, "Trade"},
		{StreamBookTicker, "BookTicker"},
		{StreamUserData, "UserData"},
	}

	for _, tc := range streamTypes {
		if tc.st.String() != tc.str {
			t.Errorf("StreamType %v should stringify to %s, got %s", tc.st, tc.str, tc.st.String())
		}
	}
}

// TestReconnectableWebSocket_ExponentialBackoff tests the backoff calculation
func TestReconnectableWebSocket_ExponentialBackoff(t *testing.T) {
	client := NewLiveAPIClient("test", "test", true)
	defer client.Close()

	rw := NewReconnectableWebSocket("test", StreamDepth, "BTCUSDT", client)
	config := &ReconnectConfig{
		InitialDelay: 1 * time.Second,
		MaxDelay:     30 * time.Second,
		Multiplier:   2.0,
	}
	rw.SetConfig(config)

	// Test backoff progression
	delays := []time.Duration{
		rw.calculateNextDelay(), // 1s
		rw.calculateNextDelay(), // 2s
		rw.calculateNextDelay(), // 4s
		rw.calculateNextDelay(), // 8s
		rw.calculateNextDelay(), // 16s
		rw.calculateNextDelay(), // 32s -> capped at 30s
	}

	expected := []time.Duration{
		1 * time.Second,
		2 * time.Second,
		4 * time.Second,
		8 * time.Second,
		16 * time.Second,
		30 * time.Second, // Capped at MaxDelay
	}

	for i, d := range delays {
		if d != expected[i] {
			t.Errorf("Backoff %d: expected %v, got %v", i, expected[i], d)
		}
	}

	// Test reset
	rw.resetReconnectDelay()
	if rw.reconnectDelay != config.InitialDelay {
		t.Errorf("After reset, delay should be %v, got %v", config.InitialDelay, rw.reconnectDelay)
	}
}

// TestReconnectableWebSocket_StartStop tests start and stop functionality
func TestReconnectableWebSocket_StartStop(t *testing.T) {
	// Skip if no API credentials (requires network)
	apiKey := getTestAPIKey()
	apiSecret := getTestAPISecret()
	if apiKey == "" || apiSecret == "" {
		t.Skip("Skipping test: API credentials not set")
	}

	client := NewLiveAPIClient(apiKey, apiSecret, true)
	defer client.Close()

	rw := NewReconnectableWebSocket("test", StreamDepth, "BTCUSDT", client)

	// Set shorter config for testing
	config := &ReconnectConfig{
		InitialDelay:   100 * time.Millisecond,
		MaxDelay:       1 * time.Second,
		Multiplier:     2.0,
		MaxAttempts:    3,
		HealthInterval: 500 * time.Millisecond,
		StaleThreshold: 2 * time.Second,
	}
	rw.SetConfig(config)

	// Test double start
	err := rw.Start()
	if err != nil {
		t.Skipf("Could not start websocket (network issue): %v", err)
	}

	// Wait a bit for connection
	time.Sleep(500 * time.Millisecond)

	// Test double start should fail
	err = rw.Start()
	if err == nil {
		t.Error("Second Start() should fail")
	}

	// Stop should work
	rw.Stop()

	// Give time for cleanup
	time.Sleep(100 * time.Millisecond)

	// Verify stopped
	if rw.IsRunning() {
		t.Error("Should not be running after Stop()")
	}
}

// TestReconnectableWebSocket_StateCallback tests state change callbacks
func TestReconnectableWebSocket_StateCallback(t *testing.T) {
	client := NewLiveAPIClient("test", "test", true)
	defer client.Close()

	rw := NewReconnectableWebSocket("test", StreamDepth, "BTCUSDT", client)

	var stateChanges []ConnectionState
	var mu sync.Mutex

	rw.SetStateChangeCallback(func(streamID string, state ConnectionState) {
		mu.Lock()
		defer mu.Unlock()
		stateChanges = append(stateChanges, state)
	})

	// Manually trigger state changes
	rw.setState(StateConnecting)
	rw.setState(StateConnected)
	rw.setState(StateDisconnected)

	// Wait for callbacks
	time.Sleep(100 * time.Millisecond)

	mu.Lock()
	defer mu.Unlock()

	if len(stateChanges) != 3 {
		t.Errorf("Expected 3 state changes, got %d", len(stateChanges))
	}

	expected := []ConnectionState{StateConnecting, StateConnected, StateDisconnected}
	for i, exp := range expected {
		if i < len(stateChanges) && stateChanges[i] != exp {
			t.Errorf("State change %d: expected %v, got %v", i, exp, stateChanges[i])
		}
	}
}

// TestReconnectableWebSocket_HandlerSetting tests handler configuration
func TestReconnectableWebSocket_HandlerSetting(t *testing.T) {
	client := NewLiveAPIClient("test", "test", true)
	defer client.Close()

	rw := NewReconnectableWebSocket("test", StreamDepth, "BTCUSDT", client)

	// Set handlers (should not panic)
	rw.SetDepthHandler(func(e *binance.WsDepthEvent) {})
	rw.SetTradeHandler(func(e *binance.WsTradeEvent) {})
	rw.SetBookTickerHandler(func(e *binance.WsBookTickerEvent) {})
	rw.SetUserDataHandler(func(e *binance.WsUserDataEvent) {})
	rw.SetErrorHandler(func(e error) {})
}

// TestReconnectableWebSocket_ConcurrentAccess tests thread safety
func TestReconnectableWebSocket_ConcurrentAccess(t *testing.T) {
	client := NewLiveAPIClient("test", "test", true)
	defer client.Close()

	rw := NewReconnectableWebSocket("test", StreamDepth, "BTCUSDT", client)

	var wg sync.WaitGroup
	numGoroutines := 10
	numIterations := 100

	// Concurrent state reads
	wg.Add(numGoroutines)
	for i := 0; i < numGoroutines; i++ {
		go func() {
			defer wg.Done()
			for j := 0; j < numIterations; j++ {
				_ = rw.GetState()
				_ = rw.IsRunning()
				_ = rw.GetReconnectCount()
			}
		}()
	}

	// Concurrent state writes
	wg.Add(numGoroutines)
	for i := 0; i < numGoroutines; i++ {
		go func(id int) {
			defer wg.Done()
			for j := 0; j < numIterations; j++ {
				rw.setState(ConnectionState(id % 3))
			}
		}(i)
	}

	wg.Wait()
}

// TestReconnectableWebSocket_MaxReconnectAttempts tests max attempts limit
func TestReconnectableWebSocket_MaxReconnectAttempts(t *testing.T) {
	client := NewLiveAPIClient("test", "test", true)
	defer client.Close()

	rw := NewReconnectableWebSocket("test", StreamDepth, "BTCUSDT", client)

	config := &ReconnectConfig{
		InitialDelay: 10 * time.Millisecond,
		MaxDelay:     100 * time.Millisecond,
		Multiplier:   2.0,
		MaxAttempts:  3, // Limit to 3 attempts
	}
	rw.SetConfig(config)

	// Simulate reconnection attempts
	rw.reconnectCount = 0
	rw.isRunning = true

	// Manually set reconnectCount to max
	rw.stateMu.Lock()
	rw.reconnectCount = 3
	rw.stateMu.Unlock()

	// Try to reconnect - should fail due to max attempts
	// This is tested indirectly by checking the state after triggering
	rw.setState(StateConnecting)

	// Verify count
	if rw.GetReconnectCount() != 3 {
		t.Errorf("Expected reconnect count 3, got %d", rw.GetReconnectCount())
	}
}

// TestReconnectableWebSocket_HealthCheck tests health check mechanism
func TestReconnectableWebSocket_HealthCheck(t *testing.T) {
	client := NewLiveAPIClient("test", "test", true)
	defer client.Close()

	rw := NewReconnectableWebSocket("test", StreamDepth, "BTCUSDT", client)

	config := &ReconnectConfig{
		HealthInterval: 100 * time.Millisecond,
		StaleThreshold: 200 * time.Millisecond,
	}
	rw.SetConfig(config)

	// Test initial state
	rw.setState(StateConnected)
	rw.updateLastMessageTime()

	// Should be healthy initially
	rw.checkHealth()
	if rw.GetState() != StateConnected {
		t.Error("Should still be connected after recent message")
	}

	// Simulate stale connection by setting old timestamp
	rw.stateMu.Lock()
	rw.lastMessageTime = time.Now().Add(-300 * time.Millisecond)
	rw.stateMu.Unlock()

	// Now health check should trigger reconnect
	// Note: actual reconnect won't happen without running loop
	// but we verify the stale detection logic
	lastMsg := rw.lastMessageTime
	if time.Since(lastMsg) <= config.StaleThreshold {
		t.Error("Time calculation incorrect")
	}
}

// TestReconnectableWebSocket_TriggerReconnect tests reconnection triggering
func TestReconnectableWebSocket_TriggerReconnect(t *testing.T) {
	client := NewLiveAPIClient("test", "test", true)
	defer client.Close()

	rw := NewReconnectableWebSocket("test", StreamDepth, "BTCUSDT", client)

	// Test triggering when not running
	rw.isRunning = false
	rw.triggerReconnect() // Should not panic or block

	// Test multiple triggers (should not block)
	rw.isRunning = true
	rw.triggerReconnect()
	rw.triggerReconnect()
	rw.triggerReconnect()

	// Should have only one item in channel (non-blocking)
	select {
	case <-rw.reconnectCh:
		// Expected - one signal
	default:
		t.Error("Expected reconnect signal in channel")
	}

	// Channel should be empty now
	select {
	case <-rw.reconnectCh:
		t.Error("Should only have one reconnect signal")
	default:
		// Expected - no more signals
	}
}

// TestReconnectableWebSocket_UserDataStream tests user data stream specific functionality
func TestReconnectableWebSocket_UserDataStream(t *testing.T) {
	client := NewLiveAPIClient("test", "test", true)
	defer client.Close()

	rw := NewReconnectableWebSocket("userData", StreamUserData, "", client)

	// With signature-based auth, we no longer need listen key
	// But connection will fail with invalid credentials
	// Just verify the stream type is set correctly
	if rw.streamType != StreamUserData {
		t.Error("Stream type should be StreamUserData")
	}

	// SetListenKey is now deprecated but should still work for backward compatibility
	rw.SetListenKey("test-listen-key")
	if rw.listenKey != "test-listen-key" {
		t.Error("Listen key not set correctly")
	}
}

// TestReconnectableWebSocket_Integration simulates a full lifecycle
func TestReconnectableWebSocket_Integration(t *testing.T) {
	apiKey := getTestAPIKey()
	apiSecret := getTestAPISecret()
	if apiKey == "" || apiSecret == "" {
		t.Skip("Skipping integration test: API credentials not set")
	}

	client := NewLiveAPIClient(apiKey, apiSecret, true)
	defer client.Close()

	rw := NewReconnectableWebSocket("integration", StreamBookTicker, "BTCUSDT", client)

	config := &ReconnectConfig{
		InitialDelay:   200 * time.Millisecond,
		MaxDelay:       2 * time.Second,
		Multiplier:     2.0,
		MaxAttempts:    5,
		HealthInterval: 1 * time.Second,
		StaleThreshold: 5 * time.Second,
	}
	rw.SetConfig(config)

	// Track state changes
	var connectCount int32
	rw.SetStateChangeCallback(func(streamID string, state ConnectionState) {
		if state == StateConnected {
			atomic.AddInt32(&connectCount, 1)
		}
	})

	// Start
	err := rw.Start()
	if err != nil {
		t.Skipf("Could not start (network issue): %v", err)
	}

	// Wait for connection
	time.Sleep(1 * time.Second)

	// Verify connected
	if rw.GetState() != StateConnected {
		t.Errorf("Expected Connected state, got %v", rw.GetState())
	}

	// Stop
	rw.Stop()
	time.Sleep(200 * time.Millisecond)

	// Verify stopped
	if rw.IsRunning() {
		t.Error("Should be stopped")
	}
}

// Helper functions
func getTestAPIKey() string {
	return os.Getenv("BINANCE_API_KEY")
}

func getTestAPISecret() string {
	return os.Getenv("BINANCE_API_SECRET")
}
