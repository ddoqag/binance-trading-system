package main

import (
	"fmt"
	"time"
)

/*
risk_config.go - Risk Management Configuration

Defines configuration structures and risk level presets for the enhanced risk management system.
*/

// RiskLevelType represents the risk tolerance level
type RiskLevelType int

const (
	RiskLevelConservative RiskLevelType = iota // Conservative: low risk, strict limits
	RiskLevelBalanced                          // Balanced: moderate risk
	RiskLevelAggressive                        // Aggressive: high risk tolerance
)

func (r RiskLevelType) String() string {
	switch r {
	case RiskLevelConservative:
		return "Conservative"
	case RiskLevelBalanced:
		return "Balanced"
	case RiskLevelAggressive:
		return "Aggressive"
	default:
		return "Unknown"
	}
}

// RiskConfig contains all risk management configuration parameters
type RiskConfig struct {
	// Basic position limits
	MaxPosition       float64 // Maximum position size in base asset (e.g., BTC)
	MaxSinglePosition float64 // Max single position as ratio of total capital (0.0-1.0)
	MaxTotalPosition  float64 // Max total position as ratio of total capital (0.0-1.0)
	MaxOrderSize      float64 // Maximum order size in base asset

	// Stop loss and take profit
	StopLossPct     float64 // Stop loss percentage (e.g., 0.02 = 2%)
	TakeProfitPct   float64 // Take profit percentage (e.g., 0.05 = 5%)
	TrailingStopPct float64 // Trailing stop percentage (e.g., 0.015 = 1.5%)
	UseTrailingStop bool    // Enable trailing stop

	// Loss limits
	MaxDailyLoss float64 // Maximum daily loss in currency
	MaxDrawdown  float64 // Maximum drawdown percentage (e.g., 0.15 = 15%)

	// Rate limiting
	MaxOrdersPerMin  int // Maximum orders per minute
	MaxOrdersPerHour int // Maximum orders per hour
	MaxOrdersPerDay  int // Maximum orders per day

	// Slippage protection
	MaxSlippagePct    float64 // Maximum allowed slippage percentage
	EnableSlippageCheck bool  // Enable slippage protection

	// Position holding limits
	MaxHoldingTime    time.Duration // Maximum position holding time
	EnableHoldingLimit bool         // Enable holding time limit

	// Volatility adaptation
	EnableVolatilityAdaption bool // Adjust risk parameters based on volatility
	VolatilityMultiplier     float64 // Risk parameter multiplier during high volatility

	// Risk level
	RiskLevel RiskLevelType // Overall risk level preset

	// Alert settings
	AlertCooldown time.Duration // Minimum time between alerts
}

// DefaultRiskConfig returns default risk configuration
func DefaultRiskConfig() *RiskConfig {
	return &RiskConfig{
		MaxPosition:              1.0,
		MaxSinglePosition:        0.2,
		MaxTotalPosition:         0.8,
		MaxOrderSize:             1.0,
		StopLossPct:              0.02,
		TakeProfitPct:            0.05,
		TrailingStopPct:          0.015,
		UseTrailingStop:          false,
		MaxDailyLoss:             10000.0,
		MaxDrawdown:              0.15,
		MaxOrdersPerMin:          60,
		MaxOrdersPerHour:         1000,
		MaxOrdersPerDay:          5000,
		MaxSlippagePct:           0.001, // 0.1%
		EnableSlippageCheck:      true,
		MaxHoldingTime:           time.Hour * 24,
		EnableHoldingLimit:       false,
		EnableVolatilityAdaption: false,
		VolatilityMultiplier:     1.5,
		RiskLevel:                RiskLevelBalanced,
		AlertCooldown:            time.Minute * 5,
	}
}

// RiskConfigFromConfigManager creates RiskConfig from ConfigManager
func RiskConfigFromConfigManager(cm *ConfigManager) *RiskConfig {
	config := DefaultRiskConfig()

	// Load from config manager with defaults
	config.MaxPosition = cm.GetFloat64("risk.max_position")
	if config.MaxPosition == 0 {
		config.MaxPosition = cm.GetFloat64("position.max_position")
	}

	config.MaxSinglePosition = cm.GetFloat64("risk.max_single_position")
	config.MaxTotalPosition = cm.GetFloat64("risk.max_total_position")
	config.MaxOrderSize = cm.GetFloat64("risk.max_order_size")
	config.StopLossPct = cm.GetFloat64("risk.stop_loss_pct")
	config.TakeProfitPct = cm.GetFloat64("risk.take_profit_pct")
	config.TrailingStopPct = cm.GetFloat64("risk.trailing_stop_pct")
	config.UseTrailingStop = cm.GetBool("risk.use_trailing_stop")
	config.MaxDailyLoss = cm.GetFloat64("risk.max_daily_loss_usd")
	if config.MaxDailyLoss == 0 {
		// Convert percentage to USD (assuming 100k capital)
		config.MaxDailyLoss = cm.GetFloat64("risk.max_daily_loss") * 100000
	}
	config.MaxDrawdown = cm.GetFloat64("risk.max_drawdown")
	config.MaxOrdersPerMin = cm.GetInt("risk.max_orders_per_min")
	config.MaxOrdersPerHour = cm.GetInt("risk.max_orders_per_hour")
	config.MaxOrdersPerDay = cm.GetInt("risk.max_orders_per_day")
	config.MaxSlippagePct = cm.GetFloat64("risk.max_slippage_pct")
	config.EnableSlippageCheck = cm.GetBool("risk.enable_slippage_check")
	config.EnableHoldingLimit = cm.GetBool("risk.enable_holding_limit")
	config.EnableVolatilityAdaption = cm.GetBool("risk.enable_volatility_adaption")

	// Parse risk level
	riskLevelStr := cm.GetString("risk.risk_level")
	switch riskLevelStr {
	case "conservative":
		config.RiskLevel = RiskLevelConservative
	case "aggressive":
		config.RiskLevel = RiskLevelAggressive
	default:
		config.RiskLevel = RiskLevelBalanced
	}

	// Apply risk level preset
	config.ApplyRiskLevel(config.RiskLevel)

	return config
}

// ApplyRiskLevel applies risk level preset to configuration
func (rc *RiskConfig) ApplyRiskLevel(level RiskLevelType) {
	rc.RiskLevel = level

	switch level {
	case RiskLevelConservative:
		// Conservative: strict limits
		rc.MaxSinglePosition = 0.1
		rc.MaxTotalPosition = 0.5
		rc.StopLossPct = 0.01
		rc.TakeProfitPct = 0.03
		rc.MaxDailyLoss = 5000.0
		rc.MaxDrawdown = 0.10
		rc.MaxOrdersPerMin = 30
		rc.MaxSlippagePct = 0.0005
		rc.UseTrailingStop = true
		rc.TrailingStopPct = 0.01

	case RiskLevelBalanced:
		// Balanced: moderate limits (use current or default values)
		if rc.MaxSinglePosition == 0 || rc.MaxSinglePosition > 0.2 {
			rc.MaxSinglePosition = 0.2
		}
		if rc.MaxTotalPosition == 0 || rc.MaxTotalPosition > 0.8 {
			rc.MaxTotalPosition = 0.8
		}
		if rc.StopLossPct == 0 {
			rc.StopLossPct = 0.02
		}
		if rc.TakeProfitPct == 0 {
			rc.TakeProfitPct = 0.05
		}
		if rc.MaxDailyLoss == 0 {
			rc.MaxDailyLoss = 10000.0
		}
		if rc.MaxDrawdown == 0 {
			rc.MaxDrawdown = 0.15
		}

	case RiskLevelAggressive:
		// Aggressive: relaxed limits
		rc.MaxSinglePosition = 0.3
		rc.MaxTotalPosition = 1.0
		rc.StopLossPct = 0.03
		rc.TakeProfitPct = 0.08
		rc.MaxDailyLoss = 20000.0
		rc.MaxDrawdown = 0.25
		rc.MaxOrdersPerMin = 120
		rc.MaxSlippagePct = 0.002
		rc.UseTrailingStop = false
	}
}

// Validate validates the risk configuration
func (rc *RiskConfig) Validate() error {
	if rc.MaxPosition <= 0 {
		return fmt.Errorf("max_position must be positive")
	}
	if rc.MaxSinglePosition <= 0 || rc.MaxSinglePosition > 1 {
		return fmt.Errorf("max_single_position must be between 0 and 1")
	}
	if rc.MaxTotalPosition <= 0 || rc.MaxTotalPosition > 1 {
		return fmt.Errorf("max_total_position must be between 0 and 1")
	}
	if rc.MaxTotalPosition < rc.MaxSinglePosition {
		return fmt.Errorf("max_total_position must be >= max_single_position")
	}
	if rc.StopLossPct < 0 || rc.StopLossPct > 1 {
		return fmt.Errorf("stop_loss_pct must be between 0 and 1")
	}
	if rc.TakeProfitPct < 0 || rc.TakeProfitPct > 1 {
		return fmt.Errorf("take_profit_pct must be between 0 and 1")
	}
	if rc.MaxDrawdown < 0 || rc.MaxDrawdown > 1 {
		return fmt.Errorf("max_drawdown must be between 0 and 1")
	}
	if rc.MaxOrdersPerMin <= 0 {
		return fmt.Errorf("max_orders_per_min must be positive")
	}
	return nil
}

// GetRiskMultiplier returns a multiplier based on risk level
// Used for adjusting position sizes or order frequencies
func (rc *RiskConfig) GetRiskMultiplier() float64 {
	switch rc.RiskLevel {
	case RiskLevelConservative:
		return 0.5
	case RiskLevelBalanced:
		return 1.0
	case RiskLevelAggressive:
		return 1.5
	default:
		return 1.0
	}
}
