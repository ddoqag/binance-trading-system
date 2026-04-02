package main

import (
	"fmt"
	"log"
	"sync"
	"time"
)

/*
risk_manager.go - Risk Management System

Implements:
- Position limits
- Daily loss limits
- Kill switch (emergency stop)
- Order rate limiting
- Drawdown monitoring
*/

type RiskManager struct {
	// Limits
	maxPosition       float64
	maxDailyLoss      float64
	maxDrawdown       float64
	maxOrdersPerMin   int
	maxOrderSize      float64

	// State
	dailyPnL          float64
	peakEquity        float64
	currentEquity     float64
	orderCount        int
	orderWindowStart  time.Time
	killSwitchActive  bool
	lastUpdated       time.Time

	// Kill switch callbacks
	killSwitchCallbacks []func()

	// Mutex
	mu                sync.RWMutex
}

func NewRiskManager(maxPosition float64) *RiskManager {
	return &RiskManager{
		maxPosition:      maxPosition,
		maxDailyLoss:     -10000.0, // $10k max daily loss
		maxDrawdown:      0.15,     // 15% max drawdown
		maxOrdersPerMin:  60,       // 1 order per second max
		maxOrderSize:     1.0,      // 1 BTC max per order
		peakEquity:       100000.0, // Starting equity
		currentEquity:    100000.0,
		orderWindowStart: time.Now(),
		lastUpdated:      time.Now(),
	}
}

// CanExecute checks if an order can be executed based on risk limits
func (r *RiskManager) CanExecute(action int32, size float64, currentPosition float64) bool {
	r.mu.RLock()
	defer r.mu.RUnlock()

	// Check kill switch
	if r.killSwitchActive {
		log.Println("[RISK] Kill switch active - all orders blocked")
		return false
	}

	// Check order size
	if size > r.maxOrderSize {
		log.Printf("[RISK] Order size %.4f exceeds max %.4f", size, r.maxOrderSize)
		return false
	}

	// Check rate limiting
	if !r.checkRateLimit() {
		log.Println("[RISK] Rate limit exceeded")
		return false
	}

	// Check position limits
	newPosition := currentPosition
	switch action {
	case ActionJoinBid, ActionCrossBuy:
		newPosition += size
	case ActionJoinAsk, ActionCrossSell:
		newPosition -= size
	}

	if abs(newPosition) > r.maxPosition {
		log.Printf("[RISK] Position %.4f would exceed max %.4f", newPosition, r.maxPosition)
		return false
	}

	// Check daily loss limit
	if r.dailyPnL < r.maxDailyLoss {
		log.Printf("[RISK] Daily loss limit reached: %.2f", r.dailyPnL)
		r.mu.RUnlock()
		r.activateKillSwitch("daily_loss_limit")
		return false
	}

	// Check drawdown
	if r.currentEquity > 0 {
		drawdown := (r.peakEquity - r.currentEquity) / r.peakEquity
		if drawdown > r.maxDrawdown {
			log.Printf("[RISK] Max drawdown reached: %.2f%%", drawdown*100)
			r.mu.RUnlock()
			r.activateKillSwitch("max_drawdown")
			return false
		}
	}

	return true
}

// UpdatePnL updates the risk manager with new PnL information
func (r *RiskManager) UpdatePnL(realizedPnL, unrealizedPnL float64) {
	r.mu.Lock()
	defer r.mu.Unlock()

	r.dailyPnL += realizedPnL
	r.currentEquity += realizedPnL

	// Update peak equity
	if r.currentEquity > r.peakEquity {
		r.peakEquity = r.currentEquity
	}

	r.lastUpdated = time.Now()
}

// UpdateEquity updates current equity (e.g., from exchange balance)
func (r *RiskManager) UpdateEquity(equity float64) {
	r.mu.Lock()
	defer r.mu.Unlock()

	r.currentEquity = equity
	if r.currentEquity > r.peakEquity {
		r.peakEquity = r.currentEquity
	}
}

// checkRateLimit checks if we're within order rate limits
func (r *RiskManager) checkRateLimit() bool {
	now := time.Now()

	// Reset window if minute has passed
	if now.Sub(r.orderWindowStart) > time.Minute {
		r.orderWindowStart = now
		r.orderCount = 0
	}

	if r.orderCount >= r.maxOrdersPerMin {
		return false
	}

	r.orderCount++
	return true
}

// RegisterKillSwitchCallback registers a callback to be invoked when kill switch is activated
func (r *RiskManager) RegisterKillSwitchCallback(cb func()) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.killSwitchCallbacks = append(r.killSwitchCallbacks, cb)
}

// ActivateKillSwitch activates the emergency stop
func (r *RiskManager) activateKillSwitch(reason string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	if r.killSwitchActive {
		return
	}

	r.killSwitchActive = true
	log.Printf("[RISK] KILL SWITCH ACTIVATED: %s", reason)

	for _, cb := range r.killSwitchCallbacks {
		go cb()
	}
}

// DeactivateKillSwitch deactivates the kill switch (requires manual intervention)
func (r *RiskManager) DeactivateKillSwitch() {
	r.mu.Lock()
	defer r.mu.Unlock()

	r.killSwitchActive = false
	r.dailyPnL = 0 // Reset daily PnL
	log.Println("[RISK] Kill switch deactivated")
}

// ResetDailyStats resets daily statistics (call at market open)
func (r *RiskManager) ResetDailyStats() {
	r.mu.Lock()
	defer r.mu.Unlock()

	r.dailyPnL = 0
	r.orderCount = 0
	r.orderWindowStart = time.Now()
	log.Println("[RISK] Daily stats reset")
}

// GetStatus returns current risk status
func (r *RiskManager) GetStatus() RiskStatus {
	r.mu.RLock()
	defer r.mu.RUnlock()

	drawdown := 0.0
	if r.peakEquity > 0 {
		drawdown = (r.peakEquity - r.currentEquity) / r.peakEquity
	}

	return RiskStatus{
		DailyPnL:         r.dailyPnL,
		PeakEquity:       r.peakEquity,
		CurrentEquity:    r.currentEquity,
		Drawdown:         drawdown,
		KillSwitchActive: r.killSwitchActive,
		OrdersThisMinute: r.orderCount,
	}
}

// RiskStatus represents current risk metrics
type RiskStatus struct {
	DailyPnL         float64
	PeakEquity       float64
	CurrentEquity    float64
	Drawdown         float64
	KillSwitchActive bool
	OrdersThisMinute int
}

func (s RiskStatus) String() string {
	return fmt.Sprintf(
		"Risk Status: PnL=%.2f Equity=%.2f Drawdown=%.2f%% KillSwitch=%v",
		s.DailyPnL, s.CurrentEquity, s.Drawdown*100, s.KillSwitchActive,
	)
}

// Helper function
func abs(x float64) float64 {
	if x < 0 {
		return -x
	}
	return x
}
