package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
)

/*
margin_client.go - Binance Margin Trading API Client

支持现货全仓杠杆交易：
- 杠杆账户查询
- 杠杆下单（自动借贷）
- 杠杆订单管理
- 仓位和保证金计算
*/

// MarginAccount 杠杆账户信息
type MarginAccount struct {
	BorrowEnabled       bool                   `json:"borrowEnabled"`
	MarginLevel         string                 `json:"marginLevel"`
	TotalAssetOfBTC     string                 `json:"totalAssetOfBtc"`
	TotalLiabilityOfBTC string                 `json:"totalLiabilityOfBtc"`
	TotalNetAssetOfBTC  string                 `json:"totalNetAssetOfBtc"`
	TradeEnabled        bool                   `json:"tradeEnabled"`
	TransferEnabled     bool                   `json:"transferEnabled"`
	UserAssets          []MarginUserAsset      `json:"userAssets"`
}

// MarginUserAsset 杠杆账户资产
type MarginUserAsset struct {
	Asset    string `json:"asset"`
	Borrowed string `json:"borrowed"`
	Free     string `json:"free"`
	Interest string `json:"interest"`
	Locked   string `json:"locked"`
	NetAsset string `json:"netAsset"`
}

// MarginOrderResponse 杠杆订单响应
type MarginOrderResponse struct {
	Symbol              string `json:"symbol"`
	OrderID             int64  `json:"orderId"`
	ClientOrderID       string `json:"clientOrderId"`
	Price               string `json:"price"`
	OrigQty             string `json:"origQty"`
	ExecutedQty         string `json:"executedQty"`
	CummulativeQuoteQty string `json:"cummulativeQuoteQty"`
	Status              string `json:"status"`
	TimeInForce         string `json:"timeInForce"`
	Type                string `json:"type"`
	Side                string `json:"side"`
	StopPrice           string `json:"stopPrice"`
	IcebergQty          string `json:"icebergQty"`
	Time                int64  `json:"time"`
	UpdateTime          int64  `json:"updateTime"`
	IsWorking           bool   `json:"isWorking"`
}

// MarginBalance 杠杆余额
type MarginBalance struct {
	Asset    string
	Free     float64
	Locked   float64
	Borrowed float64
	NetAsset float64
	Interest float64
}

// MarginPosition 杠杆持仓
type MarginPosition struct {
	Symbol     string
	BaseAsset  string
	QuoteAsset string
	Position   float64 // 正数=多头，负数=空头
	Borrowed   float64
	Free       float64
	Locked     float64
	EntryPrice float64
}

// MarginClient 杠杆交易客户端
type MarginClient struct {
	*BinanceClient // 继承基础客户端
}

// NewMarginClient 创建杠杆客户端
// 注意：杠杆API只能在主网使用，不支持测试网
func NewMarginClient(apiKey, apiSecret string, testnet bool) *MarginClient {
	// 杠杆API只能在主网使用
	client := NewBinanceClient(apiKey, apiSecret, false)
	return &MarginClient{
		BinanceClient: client,
	}
}

// GetMarginAccount 获取杠杆账户信息
func (c *MarginClient) GetMarginAccount(ctx context.Context) (*MarginAccount, error) {
	var account MarginAccount
	err := c.executeWithQueue(ctx, "/sapi/v1/margin/account", PriorityNormal, func() error {
		body, err := c.doRequest(ctx, http.MethodGet, "/sapi/v1/margin/account", url.Values{}, true)
		if err != nil {
			return fmt.Errorf("failed to get margin account: %w", err)
		}
		if err := json.Unmarshal(body, &account); err != nil {
			return fmt.Errorf("failed to parse margin account: %w", err)
		}
		return nil
	})

	if err != nil {
		return nil, err
	}
	return &account, nil
}

// GetMarginBalance 获取指定资产余额
func (c *MarginClient) GetMarginBalance(ctx context.Context, asset string) (*MarginBalance, error) {
	account, err := c.GetMarginAccount(ctx)
	if err != nil {
		return nil, err
	}

	for _, ua := range account.UserAssets {
		if ua.Asset == asset {
			return &MarginBalance{
				Asset:    ua.Asset,
				Free:     parseFloat64(ua.Free),
				Locked:   parseFloat64(ua.Locked),
				Borrowed: parseFloat64(ua.Borrowed),
				NetAsset: parseFloat64(ua.NetAsset),
				Interest: parseFloat64(ua.Interest),
			}, nil
		}
	}

	return &MarginBalance{Asset: asset}, nil
}

// GetMarginBalances 获取所有资产余额
func (c *MarginClient) GetMarginBalances(ctx context.Context) ([]MarginBalance, error) {
	account, err := c.GetMarginAccount(ctx)
	if err != nil {
		return nil, err
	}

	var balances []MarginBalance
	for _, ua := range account.UserAssets {
		balances = append(balances, MarginBalance{
			Asset:    ua.Asset,
			Free:     parseFloat64(ua.Free),
			Locked:   parseFloat64(ua.Locked),
			Borrowed: parseFloat64(ua.Borrowed),
			NetAsset: parseFloat64(ua.NetAsset),
			Interest: parseFloat64(ua.Interest),
		})
	}

	return balances, nil
}

// GetMarginLevel 获取杠杆等级
func (c *MarginClient) GetMarginLevel(ctx context.Context) (float64, error) {
	account, err := c.GetMarginAccount(ctx)
	if err != nil {
		return 0, err
	}
	return parseFloat64(account.MarginLevel), nil
}

// PlaceMarginLimitOrder 下杠杆限价单（自动借贷）
func (c *MarginClient) PlaceMarginLimitOrder(ctx context.Context, symbol, side string, price, quantity float64, timeInForce string, autoRepay bool) (*MarginOrderResponse, error) {
	params := url.Values{}
	params.Set("symbol", symbol)
	params.Set("side", side)
	params.Set("type", "LIMIT")
	params.Set("timeInForce", timeInForce)
	params.Set("price", strconv.FormatFloat(price, 'f', -1, 64))
	params.Set("quantity", strconv.FormatFloat(quantity, 'f', -1, 64))

	// 自动借贷/还款
	if side == "SELL" && autoRepay {
		params.Set("sideEffectType", "AUTO_REPAY") // 卖出平多，自动还款
	} else if side == "SELL" {
		params.Set("sideEffectType", "MARGIN_BUY") // 做空借入基础资产
	} else if autoRepay {
		params.Set("sideEffectType", "AUTO_REPAY") // 买入平空，自动还款
	}

	var response MarginOrderResponse
	err := c.executeWithQueue(ctx, "/sapi/v1/margin/order", PriorityCritical, func() error {
		body, err := c.doRequest(ctx, http.MethodPost, "/sapi/v1/margin/order", params, true)
		if err != nil {
			return fmt.Errorf("failed to place margin limit order: %w", err)
		}
		if err := json.Unmarshal(body, &response); err != nil {
			return fmt.Errorf("failed to parse margin order response: %w", err)
		}
		return nil
	})

	if err != nil {
		return nil, err
	}
	return &response, nil
}

// PlaceMarginMarketOrder 下杠杆市价单
func (c *MarginClient) PlaceMarginMarketOrder(ctx context.Context, symbol, side string, quantity float64, autoRepay bool) (*MarginOrderResponse, error) {
	params := url.Values{}
	params.Set("symbol", symbol)
	params.Set("side", side)
	params.Set("type", "MARKET")
	params.Set("quantity", strconv.FormatFloat(quantity, 'f', -1, 64))

	// 自动借贷/还款
	if side == "SELL" && autoRepay {
		params.Set("sideEffectType", "AUTO_REPAY") // 卖出平多，自动还款
	} else if side == "SELL" {
		params.Set("sideEffectType", "MARGIN_BUY") // 做空借入基础资产
	} else if autoRepay {
		params.Set("sideEffectType", "AUTO_REPAY") // 买入平空，自动还款
	}

	var response MarginOrderResponse
	err := c.executeWithQueue(ctx, "/sapi/v1/margin/order", PriorityCritical, func() error {
		body, err := c.doRequest(ctx, http.MethodPost, "/sapi/v1/margin/order", params, true)
		if err != nil {
			return fmt.Errorf("failed to place margin market order: %w", err)
		}
		if err := json.Unmarshal(body, &response); err != nil {
			return fmt.Errorf("failed to parse margin order response: %w", err)
		}
		return nil
	})

	if err != nil {
		return nil, err
	}
	return &response, nil
}

// CancelMarginOrder 取消杠杆订单
func (c *MarginClient) CancelMarginOrder(ctx context.Context, symbol string, orderID int64) error {
	params := url.Values{}
	params.Set("symbol", symbol)
	params.Set("orderId", strconv.FormatInt(orderID, 10))

	return c.executeWithQueue(ctx, "/sapi/v1/margin/order", PriorityCritical, func() error {
		_, err := c.doRequest(ctx, http.MethodDelete, "/sapi/v1/margin/order", params, true)
		if err != nil {
			return fmt.Errorf("failed to cancel margin order: %w", err)
		}
		return nil
	})
}

// QueryMarginOrder 查询杠杆订单
func (c *MarginClient) QueryMarginOrder(ctx context.Context, symbol string, orderID int64) (*MarginOrderResponse, error) {
	params := url.Values{}
	params.Set("symbol", symbol)
	params.Set("orderId", strconv.FormatInt(orderID, 10))

	var response MarginOrderResponse
	err := c.executeWithQueue(ctx, "/sapi/v1/margin/order", PriorityNormal, func() error {
		body, err := c.doRequest(ctx, http.MethodGet, "/sapi/v1/margin/order", params, true)
		if err != nil {
			return fmt.Errorf("failed to query margin order: %w", err)
		}
		if err := json.Unmarshal(body, &response); err != nil {
			return fmt.Errorf("failed to parse margin order response: %w", err)
		}
		return nil
	})

	if err != nil {
		return nil, err
	}
	return &response, nil
}

// GetOpenMarginOrders 获取未成交杠杆订单
func (c *MarginClient) GetOpenMarginOrders(ctx context.Context, symbol string) ([]MarginOrderResponse, error) {
	params := url.Values{}
	if symbol != "" {
		params.Set("symbol", symbol)
	}

	var responses []MarginOrderResponse
	err := c.executeWithQueue(ctx, "/sapi/v1/margin/openOrders", PriorityNormal, func() error {
		body, err := c.doRequest(ctx, http.MethodGet, "/sapi/v1/margin/openOrders", params, true)
		if err != nil {
			return fmt.Errorf("failed to get open margin orders: %w", err)
		}
		if err := json.Unmarshal(body, &responses); err != nil {
			return fmt.Errorf("failed to parse open orders response: %w", err)
		}
		return nil
	})

	if err != nil {
		return nil, err
	}
	return responses, nil
}

// GetMarginPosition 获取杠杆持仓（通过资产余额计算）
func (c *MarginClient) GetMarginPosition(ctx context.Context, symbol string) (*MarginPosition, error) {
	// 解析交易对
	baseAsset, quoteAsset := parseSymbol(symbol)

	// 并发获取两种资产余额
	baseBalance, err := c.GetMarginBalance(ctx, baseAsset)
	if err != nil {
		return nil, fmt.Errorf("failed to get base asset balance: %w", err)
	}

	quoteBalance, err := c.GetMarginBalance(ctx, quoteAsset)
	if err != nil {
		return nil, fmt.Errorf("failed to get quote asset balance: %w", err)
	}

	// 计算持仓：净持仓 = 可用 + 锁定 - 借入
	position := baseBalance.NetAsset

	// 如果有持仓，尝试从quote balance计算入场价格
	entryPrice := 0.0
	if position != 0 && quoteBalance.NetAsset != 0 {
		entryPrice = -quoteBalance.NetAsset / position
	}

	return &MarginPosition{
		Symbol:     symbol,
		BaseAsset:  baseAsset,
		QuoteAsset: quoteAsset,
		Position:   position,
		Borrowed:   baseBalance.Borrowed,
		Free:       baseBalance.Free,
		Locked:     baseBalance.Locked,
		EntryPrice: entryPrice,
	}, nil
}

// Borrow 借入资产
func (c *MarginClient) Borrow(ctx context.Context, asset string, amount float64) error {
	params := url.Values{}
	params.Set("asset", asset)
	params.Set("amount", strconv.FormatFloat(amount, 'f', -1, 64))

	return c.executeWithQueue(ctx, "/sapi/v1/margin/loan", PriorityHigh, func() error {
		_, err := c.doRequest(ctx, http.MethodPost, "/sapi/v1/margin/loan", params, true)
		if err != nil {
			return fmt.Errorf("failed to borrow asset: %w", err)
		}
		return nil
	})
}

// Repay 归还借款
func (c *MarginClient) Repay(ctx context.Context, asset string, amount float64) error {
	params := url.Values{}
	params.Set("asset", asset)
	params.Set("amount", strconv.FormatFloat(amount, 'f', -1, 64))

	return c.executeWithQueue(ctx, "/sapi/v1/margin/repay", PriorityHigh, func() error {
		_, err := c.doRequest(ctx, http.MethodPost, "/sapi/v1/margin/repay", params, true)
		if err != nil {
			return fmt.Errorf("failed to repay asset: %w", err)
		}
		return nil
	})
}

// parseSymbol 解析交易对（如 BTCUSDT -> BTC, USDT）
func parseSymbol(symbol string) (base, quote string) {
	// 简单实现：假设最后3-4个字符是quote asset
	// 实际应该使用交易所的symbol配置
	switch {
	case len(symbol) > 4 && symbol[len(symbol)-4:] == "USDT":
		return symbol[:len(symbol)-4], "USDT"
	case len(symbol) > 3 && symbol[len(symbol)-3:] == "BTC":
		return symbol[:len(symbol)-3], "BTC"
	case len(symbol) > 3 && symbol[len(symbol)-3:] == "ETH":
		return symbol[:len(symbol)-3], "ETH"
	case len(symbol) > 4 && symbol[len(symbol)-4:] == "BUSD":
		return symbol[:len(symbol)-4], "BUSD"
	default:
		// 默认处理：后4位为quote
		if len(symbol) > 4 {
			return symbol[:len(symbol)-4], symbol[len(symbol)-4:]
		}
		return symbol, ""
	}
}

// IsMarginSafe 检查保证金是否安全
func (c *MarginClient) IsMarginSafe(ctx context.Context, minLevel float64) (bool, float64, error) {
	level, err := c.GetMarginLevel(ctx)
	if err != nil {
		return false, 0, err
	}

	return level >= minLevel, level, nil
}
