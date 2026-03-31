/*
types.go - Leverage Trading Types

基础类型定义:
- Side (做多/做空)
- MarginMode (隔离/全仓)
- Position 基础结构
- Order 类型
*/

package leverage

import (
	"fmt"
	"time"
)

// Side 交易方向
type Side int

const (
	SideLong Side = iota  // 做多
	SideShort             // 做空
)

func (s Side) String() string {
	switch s {
	case SideLong:
		return "LONG"
	case SideShort:
		return "SHORT"
	default:
		return "UNKNOWN"
	}
}

// MarginMode 保证金模式
type MarginMode int

const (
	ModeIsolated MarginMode = iota  // 隔离模式
	ModeCross                        // 全仓模式
)

func (m MarginMode) String() string {
	switch m {
	case ModeIsolated:
		return "ISOLATED"
	case ModeCross:
		return "CROSS"
	default:
		return "UNKNOWN"
	}
}

// OrderType 订单类型
type OrderType int

const (
	OrderMarket OrderType = iota
	OrderLimit
	OrderStopLoss
	OrderTakeProfit
)

// PositionMode 仓位模式 (单向/对冲)
type PositionMode int

const (
	PositionModeOneWay PositionMode = iota // 单向模式 - 只能持有一个方向
	PositionModeHedge                      // 对冲模式 - 可同时持有多空
)

func (p PositionMode) String() string {
	switch p {
	case PositionModeOneWay:
		return "ONE_WAY"
	case PositionModeHedge:
		return "HEDGE"
	default:
		return "UNKNOWN"
	}
}

// PositionStatus 仓位状态
type PositionStatus int

const (
	PositionOpen PositionStatus = iota
	PositionClosing
	PositionClosed
	PositionLiquidating // 强平中
)

// LeveragedPosition 杠杆仓位
type LeveragedPosition struct {
	ID           string      `json:"id"`
	Symbol       string      `json:"symbol"`
	Side         Side        `json:"side"`
	Size         float64     `json:"size"`          // 仓位大小
	EntryPrice   float64     `json:"entry_price"`   // 开仓价格
	Leverage     float64     `json:"leverage"`      // 杠杆倍数
	MarginMode   MarginMode  `json:"margin_mode"`   // 保证金模式
	Margin       float64     `json:"margin"`        // 已用保证金
	Status       PositionStatus `json:"status"`
	CreatedAt    time.Time   `json:"created_at"`
	UpdatedAt    time.Time   `json:"updated_at"`

	// 盈亏相关
	RealizedPnL   float64     `json:"realized_pnl"`   // 已实现盈亏
	ClosedAt      *time.Time  `json:"closed_at"`      // 平仓时间

	// 运行时计算字段
	MarkPrice         float64 `json:"-"`  // 标记价格
	UnrealizedPnL     float64 `json:"-"`  // 未实现盈亏
	LiquidationPrice  float64 `json:"-"`  // 强平价格
	MarginRatio       float64 `json:"-"`  // 保证金率
	MaintenanceRate   float64 `json:"-"`  // 维持保证金率
}

// OpenedAt 返回仓位开仓时间（与 CreatedAt 相同，用于兼容）
func (p *LeveragedPosition) OpenedAt() time.Time {
	return p.CreatedAt
}

// PositionUpdate 仓位更新
type PositionUpdate struct {
	PositionID    string
	MarkPrice     float64
	UnrealizedPnL float64
	Timestamp     time.Time
}

// MarginInfo 保证金信息
type MarginInfo struct {
	InitialMargin     float64 `json:"initial_margin"`      // 初始保证金
	MaintenanceMargin float64 `json:"maintenance_margin"`  // 维持保证金
	AvailableMargin   float64 `json:"available_margin"`    // 可用保证金
	MarginLevel       float64 `json:"margin_level"`        // 保证金率
}

// LiquidationInfo 强平信息
type LiquidationInfo struct {
	LiquidationPrice float64 `json:"liquidation_price"`
	Distance         float64 `json:"distance"`           // 距离强平的百分比
	RiskLevel        RiskLevel `json:"risk_level"`
}

// RiskLevel 风险等级
type RiskLevel int

const (
	RiskSafe RiskLevel = iota
	RiskLow
	RiskMedium
	RiskHigh
	RiskCritical      // 即将强平
	RiskLiquidation   // 已触发强平
)

func (r RiskLevel) String() string {
	switch r {
	case RiskSafe:
		return "SAFE"
	case RiskLow:
		return "LOW"
	case RiskMedium:
		return "MEDIUM"
	case RiskHigh:
		return "HIGH"
	case RiskCritical:
		return "CRITICAL"
	case RiskLiquidation:
		return "LIQUIDATION"
	default:
		return "UNKNOWN"
	}
}

// Order 杠杆订单
type Order struct {
	ID        string    `json:"id"`
	Symbol    string    `json:"symbol"`
	Side      Side      `json:"side"`
	Type      OrderType `json:"type"`
	Size      float64   `json:"size"`
	Price     float64   `json:"price"`
	Leverage  float64   `json:"leverage"`
	Status    string    `json:"status"`
	CreatedAt time.Time `json:"created_at"`
}

// PositionConfig 仓位配置
type PositionConfig struct {
	Symbol         string
	Side           Side
	Size           float64
	EntryPrice     float64
	Leverage       float64
	MarginMode     MarginMode
	StopLossPrice  float64
	TakeProfitPrice float64
}

// FundingRate 资金费率
type FundingRate struct {
	Symbol      string    `json:"symbol"`
	Rate        float64   `json:"rate"`         // 资金费率 (正数=多头付空头，负数=空头付多头)
	NextFunding time.Time `json:"next_funding"` // 下次结算时间
	Timestamp   time.Time `json:"timestamp"`    // 数据时间戳
}

// FundingPayment 资金费支付记录
type FundingPayment struct {
	ID           string    `json:"id"`
	Symbol       string    `json:"symbol"`
	PositionID   string    `json:"position_id"`
	Side         Side      `json:"side"`
	Amount       float64   `json:"amount"`        // 支付金额 (正数=收入，负数=支出)
	Rate         float64   `json:"rate"`          // 结算时的资金费率
	PositionSize float64   `json:"position_size"` // 结算时的持仓数量
	Timestamp    time.Time `json:"timestamp"`
}

// OrderParams 订单参数
type OrderParams struct {
	Symbol   string
	Side     Side
	Size     float64
	Price    float64
	Leverage float64
	IsMarket bool
}

func (p OrderParams) Validate() error {
	if p.Symbol == "" {
		return fmt.Errorf("symbol is required")
	}
	if p.Size <= 0 {
		return fmt.Errorf("size must be positive")
	}
	if p.Leverage < 0 || p.Leverage > 10 {
		return fmt.Errorf("leverage must be between 0 and 10")
	}
	if !p.IsMarket && p.Price <= 0 {
		return fmt.Errorf("price must be positive for limit order")
	}
	return nil
}

// PositionSummary 仓位摘要
type PositionSummary struct {
	Symbol           string
	Side             Side
	Size             float64
	EntryPrice       float64
	MarkPrice        float64
	Leverage         float64
	MarginMode       MarginMode
	UnrealizedPnL    float64
	UnrealizedPnLPct float64
	LiquidationPrice float64
}

// PnLResult 盈亏计算结果
type PnLResult struct {
	UnrealizedPnL    float64
	UnrealizedPnLPct float64
	RealizedPnL      float64
	RealizedPnLPct   float64
	ROE              float64 // Return on Equity
}

// LiquidationRisk 强平风险
type LiquidationRisk struct {
	IsAtRisk         bool
	DistanceToLiq    float64 // 距离强平价格的百分比距离
	MarginLevel      float64 // 当前保证金率
	MinMarginLevel   float64 // 最低保证金率要求
	Recommendation   string  // 建议
}
