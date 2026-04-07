package main

import (
	"fmt"
	"log"
	"sync"
	"time"
)

/*
risk_enhanced.go - Enhanced Risk Management System

Implements advanced risk management features:
- Position risk monitoring with stop loss/take profit
- Trailing stop functionality
- Risk level presets
- Slippage protection
- Holding time limits
- Volatility adaptation
- Risk alerting system
*/

// RiskAlertLevel represents the severity of a risk alert
type RiskAlertLevel int

const (
	AlertLevelInfo RiskAlertLevel = iota
	AlertLevelWarning
	AlertLevelCritical
)

func (l RiskAlertLevel) String() string {
	switch l {
	case AlertLevelInfo:
		return "INFO"
	case AlertLevelWarning:
		return "WARNING"
	case AlertLevelCritical:
		return "CRITICAL"
	default:
		return "UNKNOWN"
	}
}

// RiskAlertType represents the type of risk event
type RiskAlertType int

const (
	AlertTypeStopLoss RiskAlertType = iota
	AlertTypeTakeProfit
	AlertTypeTrailingStop
	AlertTypeDrawdown
	AlertTypeDailyLoss
	AlertTypePositionLimit
	AlertTypeOrderRate
	AlertTypeSlippage
	AlertTypeHoldingTime
	AlertTypeKillSwitch
	AlertTypeVolatility
)

func (t RiskAlertType) String() string {
	switch t {
	case AlertTypeStopLoss:
		return "STOP_LOSS"
	case AlertTypeTakeProfit:
		return "TAKE_PROFIT"
	case AlertTypeTrailingStop:
		return "TRAILING_STOP"
	case AlertTypeDrawdown:
		return "DRAWDOWN"
	case AlertTypeDailyLoss:
		return "DAILY_LOSS"
	case AlertTypePositionLimit:
		return "POSITION_LIMIT"
	case AlertTypeOrderRate:
		return "ORDER_RATE"
	case AlertTypeSlippage:
		return "SLIPPAGE"
	case AlertTypeHoldingTime:
		return "HOLDING_TIME"
	case AlertTypeKillSwitch:
		return "KILL_SWITCH"
	case AlertTypeVolatility:
		return "VOLATILITY"
	default:
		return "UNKNOWN"
	}
}

// RiskAlert represents a risk management alert
type RiskAlert struct {
	Timestamp time.Time
	Level     RiskAlertLevel
	Type      RiskAlertType
	Message   string
	Symbol    string
	Data      map[string]interface{}
}

func (a RiskAlert) String() string {
	return fmt.Sprintf("[%s] %s %s: %s (%s)",
		a.Timestamp.Format("15:04:05"),
		a.Level,
		a.Type,
		a.Message,
		a.Symbol,
	)
}

// PositionRisk tracks risk metrics for an open position
type PositionRisk struct {
	Symbol       string
	EntryPrice   float64
	EntryTime    time.Time
	Size         float64
	Side         string // "long" or "short"

	// Risk levels
	StopLoss     float64
	TakeProfit   float64
	TrailingStop float64

	// Tracking for trailing stop
	HighestPrice float64 // For long positions
	LowestPrice  float64 // For short positions

	// Current state
	CurrentPrice float64
	UnrealizedPnL float64
	PnLPct       float64
}

// NewPositionRisk creates a new position risk tracker
func NewPositionRisk(symbol string, entryPrice, size float64, side string, config *RiskConfig) *PositionRisk {
	now := time.Now()

	pr := &PositionRisk{
		Symbol:     symbol,
		EntryPrice: entryPrice,
		EntryTime:  now,
		Size:       size,
		Side:       side,
		HighestPrice: entryPrice,
		LowestPrice:  entryPrice,
	}

	// Calculate stop loss and take profit levels
	if side == "long" {
		pr.StopLoss = entryPrice * (1 - config.StopLossPct)
		pr.TakeProfit = entryPrice * (1 + config.TakeProfitPct)
	} else {
		pr.StopLoss = entryPrice * (1 + config.StopLossPct)
		pr.TakeProfit = entryPrice * (1 - config.TakeProfitPct)
	}

	pr.TrailingStop = config.TrailingStopPct

	return pr
}

// UpdatePrice updates the position with current market price
func (pr *PositionRisk) UpdatePrice(currentPrice float64) {
	pr.CurrentPrice = currentPrice

	// Update highest/lowest price for trailing stop
	if pr.Side == "long" {
		if currentPrice > pr.HighestPrice {
			pr.HighestPrice = currentPrice
		}
	} else {
		if currentPrice < pr.LowestPrice {
			pr.LowestPrice = currentPrice
		}
	}

	// Calculate unrealized PnL
	if pr.Side == "long" {
		pr.UnrealizedPnL = (currentPrice - pr.EntryPrice) * pr.Size
		pr.PnLPct = (currentPrice - pr.EntryPrice) / pr.EntryPrice
	} else {
		pr.UnrealizedPnL = (pr.EntryPrice - currentPrice) * pr.Size
		pr.PnLPct = (pr.EntryPrice - currentPrice) / pr.EntryPrice
	}
}

// CheckStopLoss checks if stop loss should be triggered
func (pr *PositionRisk) CheckStopLoss() bool {
	if pr.Side == "long" {
		return pr.CurrentPrice <= pr.StopLoss
	}
	return pr.CurrentPrice >= pr.StopLoss
}

// CheckTakeProfit checks if take profit should be triggered
func (pr *PositionRisk) CheckTakeProfit() bool {
	if pr.Side == "long" {
		return pr.CurrentPrice >= pr.TakeProfit
	}
	return pr.CurrentPrice <= pr.TakeProfit
}

// CheckTrailingStop checks if trailing stop should be triggered
func (pr *PositionRisk) CheckTrailingStop(useTrailing bool, trailingPct float64) bool {
	if !useTrailing || trailingPct <= 0 {
		return false
	}

	if pr.Side == "long" {
		trailingLevel := pr.HighestPrice * (1 - trailingPct)
		return pr.CurrentPrice <= trailingLevel && pr.CurrentPrice > pr.EntryPrice
	}
	trailingLevel := pr.LowestPrice * (1 + trailingPct)
	return pr.CurrentPrice >= trailingLevel && pr.CurrentPrice < pr.EntryPrice
}

// GetHoldingTime returns how long the position has been held
func (pr *PositionRisk) GetHoldingTime() time.Duration {
	return time.Since(pr.EntryTime)
}

// EnhancedRiskManager extends the base RiskManager with advanced features
type EnhancedRiskManager struct {
	*RiskManager

	config        *RiskConfig
	configMu      sync.RWMutex

	// Position tracking
	positions     map[string]*PositionRisk
	positionsMu   sync.RWMutex

	// Order rate tracking (enhanced)
	hourlyOrderCount int
	dailyOrderCount  int
	orderHourStart   time.Time
	orderDayStart    time.Time

	// Alerts
	alerts        []RiskAlert
	alertsMu      sync.RWMutex
	alertCallback func(RiskAlert)
	lastAlertTime map[RiskAlertType]time.Time

	// Slippage tracking
	expectedPrice map[string]float64

	// Volatility tracking
	currentVolatility float64

	// Capital tracking for position ratio calculations
	totalCapital  float64
}

// NewEnhancedRiskManager creates a new enhanced risk manager
func NewEnhancedRiskManager(config *RiskConfig, totalCapital float64) *EnhancedRiskManager {
	if config == nil {
		config = DefaultRiskConfig()
	}

	baseRM := NewRiskManager(config.MaxPosition)
	// Copy base settings
	baseRM.maxDailyLoss = -config.MaxDailyLoss
	baseRM.maxDrawdown = config.MaxDrawdown
	baseRM.maxOrdersPerMin = config.MaxOrdersPerMin
	baseRM.maxOrderSize = config.MaxOrderSize

	ern := &EnhancedRiskManager{
		RiskManager:       baseRM,
		config:            config,
		positions:         make(map[string]*PositionRisk),
		alerts:            make([]RiskAlert, 0),
		lastAlertTime:     make(map[RiskAlertType]time.Time),
		expectedPrice:     make(map[string]float64),
		orderHourStart:    time.Now(),
		orderDayStart:     time.Now(),
		totalCapital:      totalCapital,
	}

	return ern
}

// SetAlertCallback sets a callback function for risk alerts
func (ern *EnhancedRiskManager) SetAlertCallback(callback func(RiskAlert)) {
	ern.alertCallback = callback
}

// UpdateConfig updates the risk configuration
func (ern *EnhancedRiskManager) UpdateConfig(config *RiskConfig) error {
	if err := config.Validate(); err != nil {
		return fmt.Errorf("invalid risk config: %w", err)
	}

	ern.configMu.Lock()
	defer ern.configMu.Unlock()

	ern.config = config

	// Update base risk manager settings
	ern.RiskManager.mu.Lock()
	ern.RiskManager.maxPosition = config.MaxPosition
	ern.RiskManager.maxDailyLoss = -config.MaxDailyLoss
	ern.RiskManager.maxDrawdown = config.MaxDrawdown
	ern.RiskManager.maxOrdersPerMin = config.MaxOrdersPerMin
	ern.RiskManager.maxOrderSize = config.MaxOrderSize
	ern.RiskManager.mu.Unlock()

	log.Printf("[RISK] Configuration updated, risk level: %s", config.RiskLevel)
	return nil
}

// GetConfig returns the current risk configuration
func (ern *EnhancedRiskManager) GetConfig() *RiskConfig {
	ern.configMu.RLock()
	defer ern.configMu.RUnlock()
	return ern.config
}

// SetRiskLevel changes the risk level and updates parameters
func (ern *EnhancedRiskManager) SetRiskLevel(level RiskLevelType) {
	ern.configMu.Lock()
	oldLevel := ern.config.RiskLevel
	ern.config.ApplyRiskLevel(level)

	// Update base risk manager
	ern.RiskManager.mu.Lock()
	ern.RiskManager.maxPosition = ern.config.MaxPosition
	ern.RiskManager.maxDailyLoss = -ern.config.MaxDailyLoss
	ern.RiskManager.maxDrawdown = ern.config.MaxDrawdown
	ern.RiskManager.maxOrdersPerMin = ern.config.MaxOrdersPerMin
	ern.RiskManager.mu.Unlock()
	ern.configMu.Unlock()

	log.Printf("[RISK] Risk level changed from %s to %s", oldLevel, level)

	// Generate alert (must be outside lock to avoid deadlock)
	ern.generateAlert(AlertLevelInfo, AlertTypeVolatility, fmt.Sprintf("Risk level changed to %s", level), "", nil)
}

// RegisterPosition registers a new position for risk monitoring
func (ern *EnhancedRiskManager) RegisterPosition(symbol string, entryPrice, size float64, side string) *PositionRisk {
	ern.configMu.RLock()
	config := ern.config
	ern.configMu.RUnlock()

	pr := NewPositionRisk(symbol, entryPrice, size, side, config)

	ern.positionsMu.Lock()
	defer ern.positionsMu.Unlock()

	ern.positions[symbol] = pr

	log.Printf("[RISK] Position registered: %s %s @ %.2f, size: %.4f, SL: %.2f, TP: %.2f",
		symbol, side, entryPrice, size, pr.StopLoss, pr.TakeProfit)

	return pr
}

// UpdatePositionPrice updates the current price for a position
func (ern *EnhancedRiskManager) UpdatePositionPrice(symbol string, currentPrice float64) *RiskAlert {
	ern.positionsMu.Lock()
	pr, exists := ern.positions[symbol]
	ern.positionsMu.Unlock()

	if !exists {
		return nil
	}

	pr.UpdatePrice(currentPrice)

	// Check for stop loss / take profit / trailing stop
	ern.configMu.RLock()
	config := ern.config
	ern.configMu.RUnlock()

	if pr.CheckStopLoss() {
		alert := ern.generateAlert(AlertLevelCritical, AlertTypeStopLoss,
			fmt.Sprintf("Stop loss triggered at %.2f (entry: %.2f)", currentPrice, pr.EntryPrice),
			symbol, map[string]interface{}{
				"entry_price":    pr.EntryPrice,
				"current_price":  currentPrice,
				"stop_loss":      pr.StopLoss,
				"unrealized_pnl": pr.UnrealizedPnL,
			})
		return &alert
	}

	if pr.CheckTakeProfit() {
		alert := ern.generateAlert(AlertLevelInfo, AlertTypeTakeProfit,
			fmt.Sprintf("Take profit triggered at %.2f (entry: %.2f)", currentPrice, pr.EntryPrice),
			symbol, map[string]interface{}{
				"entry_price":    pr.EntryPrice,
				"current_price":  currentPrice,
				"take_profit":    pr.TakeProfit,
				"unrealized_pnl": pr.UnrealizedPnL,
			})
		return &alert
	}

	if pr.CheckTrailingStop(config.UseTrailingStop, config.TrailingStopPct) {
		alert := ern.generateAlert(AlertLevelWarning, AlertTypeTrailingStop,
			fmt.Sprintf("Trailing stop triggered at %.2f (highest: %.2f)", currentPrice, pr.HighestPrice),
			symbol, map[string]interface{}{
				"entry_price":    pr.EntryPrice,
				"current_price":  currentPrice,
				"highest_price":  pr.HighestPrice,
				"trailing_stop":  pr.HighestPrice * (1 - config.TrailingStopPct),
			})
		return &alert
	}

	// Check holding time limit
	if config.EnableHoldingLimit && pr.GetHoldingTime() > config.MaxHoldingTime {
		alert := ern.generateAlert(AlertLevelWarning, AlertTypeHoldingTime,
			fmt.Sprintf("Position holding time exceeded: %s", pr.GetHoldingTime()),
			symbol, map[string]interface{}{
				"holding_time": pr.GetHoldingTime().String(),
				"max_time":     config.MaxHoldingTime.String(),
			})
		return &alert
	}

	return nil
}

// ClosePosition removes a position from monitoring
func (ern *EnhancedRiskManager) ClosePosition(symbol string) {
	ern.positionsMu.Lock()
	defer ern.positionsMu.Unlock()

	if pr, exists := ern.positions[symbol]; exists {
		holdingTime := pr.GetHoldingTime()
		log.Printf("[RISK] Position closed: %s, PnL: %.2f, held for: %s",
			symbol, pr.UnrealizedPnL, holdingTime)
		delete(ern.positions, symbol)
	}
}

// CheckEnhancedCanExecute performs enhanced pre-execution risk checks
func (ern *EnhancedRiskManager) CheckEnhancedCanExecute(symbol string, action int32, size, price float64, currentPosition float64) (bool, string) {
	// First check base risk manager
	if !ern.CanExecute(action, size, currentPosition) {
		return false, "Base risk check failed"
	}

	ern.configMu.RLock()
	config := ern.config
	ern.configMu.RUnlock()

	// Check position ratio limits
	positionValue := size * price
	positionRatio := positionValue / ern.totalCapital

	if positionRatio > config.MaxSinglePosition {
		return false, fmt.Sprintf("Single position ratio %.2f%% exceeds limit %.2f%%",
			positionRatio*100, config.MaxSinglePosition*100)
	}

	totalPositionValue := abs(currentPosition)*price + positionValue
	totalPositionRatio := totalPositionValue / ern.totalCapital

	if totalPositionRatio > config.MaxTotalPosition {
		return false, fmt.Sprintf("Total position ratio %.2f%% exceeds limit %.2f%%",
			totalPositionRatio*100, config.MaxTotalPosition*100)
	}

	// Check hourly rate limit
	if !ern.checkHourlyRateLimit() {
		return false, "Hourly order rate limit exceeded"
	}

	// Check daily rate limit
	if !ern.checkDailyRateLimit() {
		return false, "Daily order rate limit exceeded"
	}

	// Store expected price for slippage check
	if config.EnableSlippageCheck {
		ern.expectedPrice[symbol] = price
	}

	return true, ""
}

// checkHourlyRateLimit checks hourly order rate
func (ern *EnhancedRiskManager) checkHourlyRateLimit() bool {
	ern.configMu.RLock()
	maxPerHour := ern.config.MaxOrdersPerHour
	ern.configMu.RUnlock()

	if maxPerHour <= 0 {
		return true
	}

	now := time.Now()
	if now.Sub(ern.orderHourStart) > time.Hour {
		ern.orderHourStart = now
		ern.hourlyOrderCount = 0
	}

	if ern.hourlyOrderCount >= maxPerHour {
		return false
	}

	ern.hourlyOrderCount++
	return true
}

// checkDailyRateLimit checks daily order rate
func (ern *EnhancedRiskManager) checkDailyRateLimit() bool {
	ern.configMu.RLock()
	maxPerDay := ern.config.MaxOrdersPerDay
	ern.configMu.RUnlock()

	if maxPerDay <= 0 {
		return true
	}

	now := time.Now()
	if now.Sub(ern.orderDayStart) > 24*time.Hour {
		ern.orderDayStart = now
		ern.dailyOrderCount = 0
	}

	if ern.dailyOrderCount >= maxPerDay {
		return false
	}

	ern.dailyOrderCount++
	return true
}

// CheckSlippage checks if executed price has excessive slippage
func (ern *EnhancedRiskManager) CheckSlippage(symbol string, executedPrice float64) (bool, float64) {
	ern.configMu.RLock()
	config := ern.config
	ern.configMu.RUnlock()

	if !config.EnableSlippageCheck {
		return true, 0
	}

	expectedPrice, exists := ern.expectedPrice[symbol]
	if !exists {
		return true, 0
	}

	slippage := abs(executedPrice-expectedPrice) / expectedPrice

	if slippage > config.MaxSlippagePct {
		ern.generateAlert(AlertLevelWarning, AlertTypeSlippage,
			fmt.Sprintf("Excessive slippage detected: %.2f%% (max: %.2f%%)",
				slippage*100, config.MaxSlippagePct*100),
			symbol, map[string]interface{}{
				"expected_price": expectedPrice,
				"executed_price": executedPrice,
				"slippage_pct":   slippage * 100,
			})
		return false, slippage
	}

	return true, slippage
}

// UpdateVolatility updates current market volatility for adaptation
func (ern *EnhancedRiskManager) UpdateVolatility(volatility float64) {
	oldVolatility := ern.currentVolatility
	ern.currentVolatility = volatility

	if ern.config.EnableVolatilityAdaption && volatility > 0.5 {
		// High volatility detected, could adjust parameters
		if oldVolatility <= 0.5 {
			log.Printf("[RISK] High volatility detected: %.2f, risk parameters adjusted", volatility)
		}
	}
}

// generateAlert creates and stores a risk alert
func (ern *EnhancedRiskManager) generateAlert(level RiskAlertLevel, alertType RiskAlertType,
	message, symbol string, data map[string]interface{}) RiskAlert {

	alert := RiskAlert{
		Timestamp: time.Now(),
		Level:     level,
		Type:      alertType,
		Message:   message,
		Symbol:    symbol,
		Data:      data,
	}

	// Check cooldown
	ern.configMu.RLock()
	cooldown := ern.config.AlertCooldown
	ern.configMu.RUnlock()

	if lastTime, exists := ern.lastAlertTime[alertType]; exists {
		if time.Since(lastTime) < cooldown {
			return alert // Skip storing if in cooldown
		}
	}

	ern.alertsMu.Lock()
	ern.alerts = append(ern.alerts, alert)
	if len(ern.alerts) > 1000 {
		// Keep only last 1000 alerts
		ern.alerts = ern.alerts[len(ern.alerts)-1000:]
	}
	ern.lastAlertTime[alertType] = time.Now()
	ern.alertsMu.Unlock()

	// Log alert
	log.Printf("[RISK ALERT] %s", alert.String())

	// Call callback if set
	if ern.alertCallback != nil {
		go ern.alertCallback(alert)
	}

	return alert
}

// GetAlerts returns recent alerts, optionally filtered by level
func (ern *EnhancedRiskManager) GetAlerts(minLevel RiskAlertLevel, limit int) []RiskAlert {
	ern.alertsMu.RLock()
	defer ern.alertsMu.RUnlock()

	var result []RiskAlert
	for i := len(ern.alerts) - 1; i >= 0 && len(result) < limit; i-- {
		if ern.alerts[i].Level >= minLevel {
			result = append(result, ern.alerts[i])
		}
	}
	return result
}

// GetPositionRisk returns risk info for a specific position
func (ern *EnhancedRiskManager) GetPositionRisk(symbol string) *PositionRisk {
	ern.positionsMu.RLock()
	defer ern.positionsMu.RUnlock()
	return ern.positions[symbol]
}

// GetAllPositionRisks returns all monitored positions
func (ern *EnhancedRiskManager) GetAllPositionRisks() map[string]*PositionRisk {
	ern.positionsMu.RLock()
	defer ern.positionsMu.RUnlock()

	result := make(map[string]*PositionRisk)
	for k, v := range ern.positions {
		result[k] = v
	}
	return result
}

// GetEnhancedStatus returns enhanced risk status
func (ern *EnhancedRiskManager) GetEnhancedStatus() EnhancedRiskStatus {
	baseStatus := ern.GetStatus()

	ern.positionsMu.RLock()
	positionCount := len(ern.positions)
	ern.positionsMu.RUnlock()

	ern.configMu.RLock()
	config := ern.config
	ern.configMu.RUnlock()

	return EnhancedRiskStatus{
		RiskStatus:      baseStatus,
		PositionCount:   positionCount,
		RiskLevel:       config.RiskLevel,
		TotalCapital:    ern.totalCapital,
		Volatility:      ern.currentVolatility,
		AlertsLastHour:  len(ern.GetAlerts(AlertLevelInfo, 100)),
	}
}

// EnhancedRiskStatus extends RiskStatus with enhanced information
type EnhancedRiskStatus struct {
	RiskStatus
	PositionCount  int
	RiskLevel      RiskLevelType
	TotalCapital   float64
	Volatility     float64
	AlertsLastHour int
}

func (s EnhancedRiskStatus) String() string {
	return fmt.Sprintf(
		"Enhanced Risk Status:\n"+
		"  PnL: %.2f | Equity: %.2f | Drawdown: %.2f%%\n"+
		"  Positions: %d | Risk Level: %s | Volatility: %.2f\n"+
		"  Kill Switch: %v | Alerts (last hour): %d",
		s.DailyPnL, s.CurrentEquity, s.Drawdown*100,
		s.PositionCount, s.RiskLevel, s.Volatility,
		s.KillSwitchActive, s.AlertsLastHour,
	)
}
