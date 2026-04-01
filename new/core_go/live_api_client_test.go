package main

import (
	"context"
	"os"
	"testing"
	"time"
)

// TestLiveAPIConnection tests basic connection to Binance API
func TestLiveAPIConnection(t *testing.T) {
	// Skip if no API credentials
	apiKey := os.Getenv("BINANCE_API_KEY")
	apiSecret := os.Getenv("BINANCE_API_SECRET")
	if apiKey == "" || apiSecret == "" {
		t.Skip("Skipping live API test: BINANCE_API_KEY and BINANCE_API_SECRET not set")
	}

	// Use testnet for testing
	client := NewLiveAPIClient(apiKey, apiSecret, true)
	defer client.Close()

	// Test connection
	err := client.TestConnection()
	if err != nil {
		t.Errorf("Connection test failed: %v", err)
	}

	t.Log("✓ Live API connection test passed")
}

// TestLiveAPIAccountInfoMainnet tests getting account information on mainnet
func TestLiveAPIAccountInfoMainnet(t *testing.T) {
	apiKey := os.Getenv("BINANCE_API_KEY")
	apiSecret := os.Getenv("BINANCE_API_SECRET")
	if apiKey == "" || apiSecret == "" {
		t.Skip("Skipping live API test: API credentials not set")
	}

	// Use mainnet for testing
	client := NewLiveAPIClient(apiKey, apiSecret, false)
	defer client.Close()

	// Sync time first
	if err := client.SyncTime(); err != nil {
		t.Logf("Time sync warning: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	account, err := client.GetAccountInfo(ctx)
	if err != nil {
		t.Errorf("Failed to get account info on mainnet: %v", err)
		return
	}

	if account.MakerCommission < 0 {
		t.Error("Invalid maker commission")
	}

	t.Logf("✓ Mainnet account info test passed, can trade: %v", account.CanTrade)
}

// TestLiveAPIGetBalance tests balance retrieval
func TestLiveAPIGetBalance(t *testing.T) {
	apiKey := os.Getenv("BINANCE_API_KEY")
	apiSecret := os.Getenv("BINANCE_API_SECRET")
	if apiKey == "" || apiSecret == "" {
		t.Skip("Skipping live API test: API credentials not set")
	}

	// Use mainnet for testing
	client := NewLiveAPIClient(apiKey, apiSecret, false)
	defer client.Close()

	// Sync time first
	if err := client.SyncTime(); err != nil {
		t.Logf("Time sync warning: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	free, locked, err := client.GetBalance(ctx, "USDT")
	if err != nil {
		t.Errorf("Failed to get balance: %v", err)
		return
	}

	t.Logf("✓ Balance test passed: free=%.2f, locked=%.2f", free, locked)
}

// TestLiveAPIExchangeInfo tests exchange info retrieval
func TestLiveAPIExchangeInfo(t *testing.T) {
	apiKey := os.Getenv("BINANCE_API_KEY")
	apiSecret := os.Getenv("BINANCE_API_SECRET")
	if apiKey == "" || apiSecret == "" {
		t.Skip("Skipping live API test: API credentials not set")
	}

	client := NewLiveAPIClient(apiKey, apiSecret, true)
	defer client.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	info, err := client.GetExchangeInfo(ctx)
	if err != nil {
		t.Errorf("Failed to get exchange info: %v", err)
		return
	}

	if len(info.Symbols) == 0 {
		t.Error("No symbols in exchange info")
	}

	t.Logf("✓ Exchange info test passed, %d symbols available", len(info.Symbols))
}

// TestLiveAPIGetSymbolFilters tests symbol filter retrieval
func TestLiveAPIGetSymbolFilters(t *testing.T) {
	apiKey := os.Getenv("BINANCE_API_KEY")
	apiSecret := os.Getenv("BINANCE_API_SECRET")
	if apiKey == "" || apiSecret == "" {
		t.Skip("Skipping live API test: API credentials not set")
	}

	client := NewLiveAPIClient(apiKey, apiSecret, true)
	defer client.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	filters, err := client.GetSymbolFilters(ctx, "BTCUSDT")
	if err != nil {
		t.Errorf("Failed to get symbol filters: %v", err)
		return
	}

	if len(filters) == 0 {
		t.Error("No filters found for BTCUSDT")
	}

	t.Logf("✓ Symbol filters test passed, %d filters found", len(filters))
}

// TestLiveAPIWebSocketDepth tests WebSocket depth stream
func TestLiveAPIWebSocketDepth(t *testing.T) {
	apiKey := os.Getenv("BINANCE_API_KEY")
	apiSecret := os.Getenv("BINANCE_API_SECRET")
	if apiKey == "" || apiSecret == "" {
		t.Skip("Skipping live API test: API credentials not set")
	}

	client := NewLiveAPIClient(apiKey, apiSecret, true)
	defer client.Close()

	// Subscribe to depth stream
	stopCh, err := client.SubscribeDepth("BTCUSDT")
	if err != nil {
		t.Errorf("Failed to subscribe to depth stream: %v", err)
		return
	}

	// Wait a bit for updates
	time.Sleep(3 * time.Second)

	// Stop the stream
	close(stopCh)

	t.Log("✓ Depth stream test passed")
}

// TestLiveAPIWebSocketTrades tests WebSocket trade stream
func TestLiveAPIWebSocketTrades(t *testing.T) {
	apiKey := os.Getenv("BINANCE_API_KEY")
	apiSecret := os.Getenv("BINANCE_API_SECRET")
	if apiKey == "" || apiSecret == "" {
		t.Skip("Skipping live API test: API credentials not set")
	}

	client := NewLiveAPIClient(apiKey, apiSecret, true)
	defer client.Close()

	// Subscribe to trade stream
	stopCh, err := client.SubscribeTrades("BTCUSDT")
	if err != nil {
		t.Errorf("Failed to subscribe to trade stream: %v", err)
		return
	}

	// Wait a bit for updates
	time.Sleep(3 * time.Second)

	// Stop the stream
	close(stopCh)

	t.Log("✓ Trade stream test passed")
}

// TestLiveAPIWebSocketBookTicker tests WebSocket book ticker stream
func TestLiveAPIWebSocketBookTicker(t *testing.T) {
	apiKey := os.Getenv("BINANCE_API_KEY")
	apiSecret := os.Getenv("BINANCE_API_SECRET")
	if apiKey == "" || apiSecret == "" {
		t.Skip("Skipping live API test: API credentials not set")
	}

	client := NewLiveAPIClient(apiKey, apiSecret, true)
	defer client.Close()

	// Subscribe to book ticker stream
	stopCh, err := client.SubscribeBookTicker("BTCUSDT")
	if err != nil {
		t.Errorf("Failed to subscribe to book ticker stream: %v", err)
		return
	}

	// Wait a bit for updates
	time.Sleep(3 * time.Second)

	// Stop the stream
	close(stopCh)

	t.Log("✓ Book ticker stream test passed")
}

// TestLiveAPIUserDataStream tests user data stream
func TestLiveAPIUserDataStream(t *testing.T) {
	apiKey := os.Getenv("BINANCE_API_KEY")
	apiSecret := os.Getenv("BINANCE_API_SECRET")
	if apiKey == "" || apiSecret == "" {
		t.Skip("Skipping live API test: API credentials not set")
	}

	// Skip this test - Binance deprecated the user data stream endpoint (returns 410 Gone)
	t.Skip("Skipping: User data stream API endpoint deprecated by Binance (410 Gone)")

	client := NewLiveAPIClient(apiKey, apiSecret, true)
	defer client.Close()

	// Set up handlers
	client.SetOrderHandler(func(update *OrderUpdate) {
		t.Logf("Order update: %s %s, status=%s", update.Symbol, update.Side, update.Status)
	})
	client.SetBalanceHandler(func(update *BalanceUpdate) {
		t.Logf("Balance update: %s delta=%.4f", update.Asset, update.Delta)
	})

	// Start user data stream
	err := client.StartUserDataStream()
	if err != nil {
		t.Errorf("Failed to start user data stream: %v", err)
		return
	}

	// Stream started successfully (wait a bit to ensure it's working)
	time.Sleep(2 * time.Second)
	t.Log("✓ User data stream test passed")
}

// TestLiveAPIOpenOrders tests getting open orders
func TestLiveAPIOpenOrders(t *testing.T) {
	apiKey := os.Getenv("BINANCE_API_KEY")
	apiSecret := os.Getenv("BINANCE_API_SECRET")
	if apiKey == "" || apiSecret == "" {
		t.Skip("Skipping live API test: API credentials not set")
	}

	// Use mainnet for testing
	client := NewLiveAPIClient(apiKey, apiSecret, false)
	defer client.Close()

	// Sync time first
	if err := client.SyncTime(); err != nil {
		t.Logf("Time sync warning: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	orders, err := client.GetOpenOrders(ctx, "")
	if err != nil {
		t.Errorf("Failed to get open orders: %v", err)
		return
	}

	t.Logf("✓ Open orders test passed, %d orders found", len(orders))
}

// BenchmarkLiveAPIGetAccount benchmarks account info retrieval
func BenchmarkLiveAPIGetAccount(b *testing.B) {
	apiKey := os.Getenv("BINANCE_API_KEY")
	apiSecret := os.Getenv("BINANCE_API_SECRET")
	if apiKey == "" || apiSecret == "" {
		b.Skip("Skipping benchmark: API credentials not set")
	}

	client := NewLiveAPIClient(apiKey, apiSecret, true)
	defer client.Close()

	ctx := context.Background()

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		_, err := client.GetAccountInfo(ctx)
		if err != nil {
			b.Errorf("Failed: %v", err)
		}
	}
}
