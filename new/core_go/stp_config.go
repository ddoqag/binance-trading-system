package main

import (
	"fmt"
	"time"
)

/*
stp_config.go - Self-Trade Prevention Configuration

Defines configuration for self-trade prevention (STP) mechanisms
to prevent accidental self-trading between own orders.
*/

// STPMode defines the self-trade prevention mode
type STPMode int

const (
	// STPModeNone - No self-trade prevention
	STPModeNone STPMode = iota
	// STPModeReject - Reject new orders that would self-trade
	STPModeReject
	// STPModeCancelOldest - Cancel oldest order and accept new order
	STPModeCancelOldest
	// STPModeCancelNewest - Cancel newest order (new order rejected)
	STPModeCancelNewest
	// STPModeDecrement - Reduce both orders' quantities
	STPModeDecrement
)

func (m STPMode) String() string {
	switch m {
	case STPModeNone:
		return "NONE"
	case STPModeReject:
		return "REJECT"
	case STPModeCancelOldest:
		return "CANCEL_OLDEST"
	case STPModeCancelNewest:
		return "CANCEL_NEWEST"
	case STPModeDecrement:
		return "DECREMENT"
	default:
		return "UNKNOWN"
	}
}

// STPConfig holds self-trade prevention configuration
type STPConfig struct {
	// EnableSTP enables self-trade prevention
	EnableSTP bool

	// Mode determines the STP behavior
	Mode STPMode

	// CheckInterval is how often to check for self-trade conditions
	CheckInterval time.Duration

	// MaxSelfTradeAttempts before triggering alerts
	MaxSelfTradeAttempts int

	// SelfTradeCooldown is the minimum time between self-trade alerts
	SelfTradeCooldown time.Duration

	// LogSelfTradeEvents enables logging of all self-trade prevention events
	LogSelfTradeEvents bool

	// AlertOnSelfTrade sends alert when self-trade is prevented
	AlertOnSelfTrade bool

	// PriceTolerance is the price difference tolerance for self-trade detection
	// (e.g., 0.0001 = 0.01% price difference allowed)
	PriceTolerance float64
}

// DefaultSTPConfig returns default STP configuration
func DefaultSTPConfig() *STPConfig {
	return &STPConfig{
		EnableSTP:            true,
		Mode:                 STPModeReject,
		CheckInterval:        100 * time.Millisecond,
		MaxSelfTradeAttempts: 5,
		SelfTradeCooldown:    1 * time.Minute,
		LogSelfTradeEvents:   true,
		AlertOnSelfTrade:     true,
		PriceTolerance:       0.0001, // 0.01%
	}
}

// Validate checks if the STP configuration is valid
func (c *STPConfig) Validate() error {
	if c.CheckInterval < 10*time.Millisecond {
		return fmt.Errorf("check interval must be at least 10ms")
	}
	if c.MaxSelfTradeAttempts < 1 {
		return fmt.Errorf("max self-trade attempts must be at least 1")
	}
	if c.SelfTradeCooldown < time.Second {
		return fmt.Errorf("self-trade cooldown must be at least 1 second")
	}
	if c.PriceTolerance < 0 || c.PriceTolerance > 0.01 {
		return fmt.Errorf("price tolerance must be between 0 and 0.01 (1 percent)")
	}
	return nil
}

// STPConfigFromConfigManager creates STP config from ConfigManager
func STPConfigFromConfigManager(cm *ConfigManager) *STPConfig {
	modeStr := cm.GetString("stp.mode")
	var mode STPMode
	switch modeStr {
	case "NONE":
		mode = STPModeNone
	case "CANCEL_OLDEST":
		mode = STPModeCancelOldest
	case "CANCEL_NEWEST":
		mode = STPModeCancelNewest
	case "DECREMENT":
		mode = STPModeDecrement
	default:
		mode = STPModeReject
	}

	return &STPConfig{
		EnableSTP:            cm.GetBool("stp.enable"),
		Mode:                 mode,
		CheckInterval:        cm.GetDuration("stp.check_interval_ms"),
		MaxSelfTradeAttempts: cm.GetInt("stp.max_attempts"),
		SelfTradeCooldown:    cm.GetDuration("stp.cooldown_ms"),
		LogSelfTradeEvents:   cm.GetBool("stp.log_events"),
		AlertOnSelfTrade:     cm.GetBool("stp.alert"),
		PriceTolerance:       cm.GetFloat64("stp.price_tolerance"),
	}
}

// STPEvent represents a self-trade prevention event
type STPEvent struct {
	Timestamp   time.Time
	Mode        STPMode
	Symbol      string
	NewOrderID  string
	ExistingOrderID string
	Side        OrderSide
	Price       float64
	Size        float64
	Action      string
	Reason      string
}

// String returns string representation of STP event
func (e *STPEvent) String() string {
	return fmt.Sprintf("STP[%s] %s: %s order %s would self-trade with %s at %.2f (size=%.4f, action=%s)",
		e.Timestamp.Format("15:04:05.000"),
		e.Mode,
		e.Symbol,
		e.NewOrderID,
		e.ExistingOrderID,
		e.Price,
		e.Size,
		e.Action,
	)
}
