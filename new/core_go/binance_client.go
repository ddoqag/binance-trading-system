package main

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	BinanceBaseURL    = "https://api.binance.com"
	BinanceTestnetURL = "https://testnet.binance.vision"
)

// RateLimiter implements token bucket for API rate limiting
type RateLimiter struct {
	rate       int           // tokens per second
	tokens     float64
	lastUpdate time.Time
	mu         sync.Mutex
}

func NewRateLimiter(rate int) *RateLimiter {
	return &RateLimiter{
		rate:       rate,
		tokens:     float64(rate),
		lastUpdate: time.Now(),
	}
}

func (rl *RateLimiter) Allow() bool {
	rl.mu.Lock()
	defer rl.mu.Unlock()

	now := time.Now()
	elapsed := now.Sub(rl.lastUpdate).Seconds()
	rl.tokens += elapsed * float64(rl.rate)
	if rl.tokens > float64(rl.rate) {
		rl.tokens = float64(rl.rate)
	}
	rl.lastUpdate = now

	if rl.tokens >= 1 {
		rl.tokens--
		return true
	}
	return false
}

func (rl *RateLimiter) Wait(ctx context.Context) error {
	for {
		if rl.Allow() {
			return nil
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(10 * time.Millisecond):
		}
	}
}

// BinanceClient handles all Binance API interactions
type BinanceClient struct {
	apiKey     string
	apiSecret  string
	baseURL    string
	httpClient *http.Client

	// Enhanced request queue with priority and weight-based rate limiting
	requestQueue *RequestQueue

	// Legacy rate limiters (kept for compatibility during transition)
	orderLimiter *RateLimiter // 100 orders/10s (spot)
	queryLimiter *RateLimiter // 1200 request weight/minute

	// Test mode
	testnet bool
}

// BinanceOrderResponse represents the API response for order creation
type BinanceOrderResponse struct {
	Symbol              string `json:"symbol"`
	OrderID             int64  `json:"orderId"`
	ClientOrderID       string `json:"clientOrderId"`
	TransactTime        int64  `json:"transactTime"`
	Price               string `json:"price"`
	OrigQty             string `json:"origQty"`
	ExecutedQty         string `json:"executedQty"`
	CummulativeQuoteQty string `json:"cummulativeQuoteQty"`
	Status              string `json:"status"`
	TimeInForce         string `json:"timeInForce"`
	Type                string `json:"type"`
	Side                string `json:"side"`
	AvgPrice            string `json:"avgPrice"`
}

// BinanceAccount represents account information
type BinanceAccount struct {
	MakerCommission  int    `json:"makerCommission"`
	TakerCommission  int    `json:"takerCommission"`
	BuyerCommission  int    `json:"buyerCommission"`
	SellerCommission int    `json:"sellerCommission"`
	CanTrade         bool   `json:"canTrade"`
	CanWithdraw      bool   `json:"canWithdraw"`
	CanDeposit       bool   `json:"canDeposit"`
	UpdateTime       int64  `json:"updateTime"`
	AccountType      string `json:"accountType"`
	Balances         []struct {
		Asset  string `json:"asset"`
		Free   string `json:"free"`
		Locked string `json:"locked"`
	} `json:"balances"`
}

func NewBinanceClient(apiKey, apiSecret string, testnet bool) *BinanceClient {
	baseURL := BinanceBaseURL
	if testnet {
		baseURL = BinanceTestnetURL
	}

	client := &BinanceClient{
		apiKey:       apiKey,
		apiSecret:    apiSecret,
		baseURL:      baseURL,
		httpClient:   &http.Client{Timeout: 10 * time.Second},
		requestQueue: NewRequestQueue(),
		orderLimiter: NewRateLimiter(10), // Conservative: 10 orders/sec
		queryLimiter: NewRateLimiter(20), // Conservative: 20 queries/sec
		testnet:      testnet,
	}

	return client
}

func (c *BinanceClient) generateSignature(queryString string) string {
	mac := hmac.New(sha256.New, []byte(c.apiSecret))
	mac.Write([]byte(queryString))
	return hex.EncodeToString(mac.Sum(nil))
}

// parseRateLimitHeaders parses Binance rate limit headers and updates the rate limiter
func (c *BinanceClient) parseRateLimitHeaders(headers http.Header) {
	// Parse X-MBX-USED-WEIGHT-1M (weight used in the last minute)
	if weightStr := headers.Get("X-MBX-USED-WEIGHT-1M"); weightStr != "" {
		if weight, err := strconv.Atoi(weightStr); err == nil {
			c.requestQueue.UpdateUsedWeight(weight)
		}
	}

	// Parse X-MBX-ORDER-COUNT-10S (orders placed in the last 10 seconds)
	if orderCountStr := headers.Get("X-MBX-ORDER-COUNT-10S"); orderCountStr != "" {
		if count, err := strconv.Atoi(orderCountStr); err == nil {
			c.requestQueue.UpdateOrderCount(count)
		}
	}

	// Parse Retry-After header (for 429 responses)
	if retryAfter := headers.Get("Retry-After"); retryAfter != "" {
		if seconds, err := strconv.Atoi(retryAfter); err == nil {
			log.Printf("[RATE_LIMIT] Retry-After header received: %d seconds", seconds)
			c.requestQueue.ApplyRetryAfter(time.Duration(seconds) * time.Second)
		}
	}
}
func (c *BinanceClient) Close() {
	if c.requestQueue != nil {
		c.requestQueue.Close()
	}
}

// executeWithQueue executes an API request through the priority queue
func (c *BinanceClient) executeWithQueue(ctx context.Context, endpoint string, priority RequestPriority, execute func() error) error {
	if c.requestQueue == nil {
		return execute()
	}
	return c.requestQueue.Submit(endpoint, priority, execute)
}

// GetRateLimitStats returns current rate limiting statistics
func (c *BinanceClient) GetRateLimitStats() map[string]interface{} {
	if c.requestQueue == nil {
		return map[string]interface{}{"status": "queue not initialized"}
	}
	return c.requestQueue.GetStats()
}

func (c *BinanceClient) doRequest(ctx context.Context, method, endpoint string, params url.Values, signed bool) ([]byte, error) {
	// Apply rate limiting for query endpoints
	if strings.Contains(endpoint, "/api/v3/account") || strings.Contains(endpoint, "/api/v3/order") {
		if err := c.queryLimiter.Wait(ctx); err != nil {
			return nil, err
		}
	}

	fullURL := c.baseURL + endpoint

	if signed {
		params.Set("timestamp", strconv.FormatInt(time.Now().UnixMilli(), 10))
		params.Set("recvWindow", "5000")
		signature := c.generateSignature(params.Encode())
		params.Set("signature", signature)
	}

	var body io.Reader
	if method == http.MethodPost || method == http.MethodPut {
		body = strings.NewReader(params.Encode())
	} else if len(params) > 0 {
		fullURL = fullURL + "?" + params.Encode()
	}

	req, err := http.NewRequestWithContext(ctx, method, fullURL, body)
	if err != nil {
		return nil, err
	}

	req.Header.Set("X-MBX-APIKEY", c.apiKey)
	if method == http.MethodPost {
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("HTTP request failed: %w", err)
	}
	defer resp.Body.Close()

	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response body: %w", err)
	}

	// Parse rate limit headers and update rate limiter
	c.parseRateLimitHeaders(resp.Header)

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("API error (status %d): %s", resp.StatusCode, string(bodyBytes))
	}

	return bodyBytes, nil
}

// PlaceLimitOrder creates a new limit order with priority queue
func (c *BinanceClient) PlaceLimitOrder(ctx context.Context, symbol string, side string, price, quantity float64, timeInForce string) (*BinanceOrderResponse, error) {
	params := url.Values{}
	params.Set("symbol", symbol)
	params.Set("side", side)
	params.Set("type", "LIMIT")
	params.Set("timeInForce", timeInForce)
	params.Set("price", strconv.FormatFloat(price, 'f', -1, 64))
	params.Set("quantity", strconv.FormatFloat(quantity, 'f', -1, 64))

	var response BinanceOrderResponse
	err := c.executeWithQueue(ctx, "/api/v3/order", PriorityCritical, func() error {
		body, err := c.doRequest(ctx, http.MethodPost, "/api/v3/order", params, true)
		if err != nil {
			return fmt.Errorf("failed to place limit order: %w", err)
		}
		if err := json.Unmarshal(body, &response); err != nil {
			return fmt.Errorf("failed to parse response: %w", err)
		}
		return nil
	})

	if err != nil {
		return nil, err
	}
	return &response, nil
}

// PlaceMarketOrder creates a new market order with priority queue
func (c *BinanceClient) PlaceMarketOrder(ctx context.Context, symbol string, side string, quantity float64) (*BinanceOrderResponse, error) {
	params := url.Values{}
	params.Set("symbol", symbol)
	params.Set("side", side)
	params.Set("type", "MARKET")
	params.Set("quantity", strconv.FormatFloat(quantity, 'f', -1, 64))

	var response BinanceOrderResponse
	err := c.executeWithQueue(ctx, "/api/v3/order", PriorityCritical, func() error {
		body, err := c.doRequest(ctx, http.MethodPost, "/api/v3/order", params, true)
		if err != nil {
			return fmt.Errorf("failed to place market order: %w", err)
		}
		if err := json.Unmarshal(body, &response); err != nil {
			return fmt.Errorf("failed to parse response: %w", err)
		}
		return nil
	})

	if err != nil {
		return nil, err
	}
	return &response, nil
}

// CancelOrder cancels an existing order with priority queue
func (c *BinanceClient) CancelOrder(ctx context.Context, symbol string, orderID int64) error {
	params := url.Values{}
	params.Set("symbol", symbol)
	params.Set("orderId", strconv.FormatInt(orderID, 10))

	return c.executeWithQueue(ctx, "/api/v3/order", PriorityCritical, func() error {
		_, err := c.doRequest(ctx, http.MethodDelete, "/api/v3/order", params, true)
		if err != nil {
			return fmt.Errorf("failed to cancel order: %w", err)
		}
		return nil
	})
}

// QueryOrder queries the status of an order
func (c *BinanceClient) QueryOrder(ctx context.Context, symbol string, orderID int64) (*BinanceOrderResponse, error) {
	params := url.Values{}
	params.Set("symbol", symbol)
	params.Set("orderId", strconv.FormatInt(orderID, 10))

	var response BinanceOrderResponse
	err := c.executeWithQueue(ctx, "/api/v3/order", PriorityNormal, func() error {
		body, err := c.doRequest(ctx, http.MethodGet, "/api/v3/order", params, true)
		if err != nil {
			return fmt.Errorf("failed to query order: %w", err)
		}
		if err := json.Unmarshal(body, &response); err != nil {
			return fmt.Errorf("failed to parse response: %w", err)
		}
		return nil
	})

	if err != nil {
		return nil, err
	}
	return &response, nil
}

// GetAccount gets account information including balances
func (c *BinanceClient) GetAccount(ctx context.Context) (*BinanceAccount, error) {
	var account BinanceAccount
	err := c.executeWithQueue(ctx, "/api/v3/account", PriorityNormal, func() error {
		body, err := c.doRequest(ctx, http.MethodGet, "/api/v3/account", url.Values{}, true)
		if err != nil {
			return fmt.Errorf("failed to get account: %w", err)
		}
		if err := json.Unmarshal(body, &account); err != nil {
			return fmt.Errorf("failed to parse account: %w", err)
		}
		return nil
	})

	if err != nil {
		return nil, err
	}
	return &account, nil
}

// TestConnectivity tests API connectivity
func (c *BinanceClient) TestConnectivity(ctx context.Context) error {
	_, err := c.doRequest(ctx, http.MethodGet, "/api/v3/ping", url.Values{}, false)
	return err
}

// GetServerTime gets the current server time
func (c *BinanceClient) GetServerTime(ctx context.Context) (int64, error) {
	body, err := c.doRequest(ctx, http.MethodGet, "/api/v3/time", url.Values{}, false)
	if err != nil {
		return 0, err
	}

	var result struct {
		ServerTime int64 `json:"serverTime"`
	}
	if err := json.Unmarshal(body, &result); err != nil {
		return 0, err
	}

	return result.ServerTime, nil
}
