package main

import (
	"fmt"
	"log"
	"time"
)

/*
engine_defense_integration.go - Defense FSM Integration with HFTEngine

Integrates the order defense state machine with the main HFT engine:
- Injects market data into toxic flow detector
- Checks defense state before executing orders
- Manages order lifecycle with defense-aware cancel logic
- Provides defense metrics for monitoring
*/

// DefenseIntegratedEngine extends HFTEngine with defense capabilities
type DefenseIntegratedEngine struct {
	*HFTEngine
	defenseMgr *DefenseManager
	config     *DefenseIntegrationConfig
}

// DefenseIntegrationConfig configuration for defense integration
type DefenseIntegrationConfig struct {
	Enabled              bool
	AutoCancelOnToxic    bool
	MaxOrdersInToxicMode int
	EnableSideControl    bool
	LogDefenseEvents     bool
}

// DefaultDefenseIntegrationConfig returns default config
func DefaultDefenseIntegrationConfig() *DefenseIntegrationConfig {
	return &DefenseIntegrationConfig{
		Enabled:              true,
		AutoCancelOnToxic:    true,
		MaxOrdersInToxicMode: 2,
		EnableSideControl:    true,
		LogDefenseEvents:     true,
	}
}

// NewDefenseIntegratedEngine creates a new engine with defense integration
func NewDefenseIntegratedEngine(config *EngineConfig, defenseConfig *DefenseIntegrationConfig) (*DefenseIntegratedEngine, error) {
	if defenseConfig == nil {
		defenseConfig = DefaultDefenseIntegrationConfig()
	}

	// Create base engine
	baseEngine, err := NewHFTEngine(config)
	if err != nil {
		return nil, fmt.Errorf("failed to create base engine: %w", err)
	}

	// Create defense manager
	dmConfig := DefaultDefenseManagerConfig()
	dmConfig.EnableAutoCancel = defenseConfig.AutoCancelOnToxic
	defenseMgr := NewDefenseManager(dmConfig)

	engine := &DefenseIntegratedEngine{
		HFTEngine:  baseEngine,
		defenseMgr: defenseMgr,
		config:     defenseConfig,
	}

	// Set up defense callbacks
	engine.setupDefenseCallbacks()

	return engine, nil
}

// setupDefenseCallbacks sets up callbacks between defense manager and engine
func (e *DefenseIntegratedEngine) setupDefenseCallbacks() {
	// Mode change callback
	e.defenseMgr.SetModeChangeCallback(func(from, to MarketMode, reason string) {
		if e.config.LogDefenseEvents {
			log.Printf("[DEFENSE] Mode transition: %s -> %s (reason: %s)",
				from.String(), to.String(), reason)
		}

		// Handle mode-specific actions
		switch to {
		case ModeToxic:
			if e.config.AutoCancelOnToxic {
				e.handleToxicModeEntry()
			}
		case ModeDefensive:
			e.handleDefensiveModeEntry()
		case ModeNormal:
			e.handleNormalModeEntry()
		}
	})

	// Cancel callback - execute actual cancel via executor
	e.defenseMgr.SetCancelCallback(func(orderID, reason string) {
		if e.config.LogDefenseEvents {
			log.Printf("[DEFENSE] Cancelling order %s: %s", orderID, reason)
		}

		// Try to find and cancel the order
		if err := e.cancelOrderByID(orderID); err != nil {
			log.Printf("[DEFENSE] Failed to cancel order %s: %v", orderID, err)
		}
	})
}

// handleToxicModeEntry handles entering toxic mode
func (e *DefenseIntegratedEngine) handleToxicModeEntry() {
	// Get toxic state
	toxicState := e.defenseMgr.GetToxicState()

	// Cancel all orders on the dangerous side
	openOrders := e.executor.GetOpenOrders()
	for _, order := range openOrders {
		shouldCancel := false

		switch toxicState.ToxicSide {
		case SideBuyPressure:
			// Buy pressure means sell orders are at risk
			if order.Side == SideSell {
				shouldCancel = true
			}
		case SideSellPressure:
			// Sell pressure means buy orders are at risk
			if order.Side == SideBuy {
				shouldCancel = true
			}
		case SideNeutral:
			// Both sides at risk in neutral toxic mode
			shouldCancel = true
		}

		if shouldCancel {
			e.executor.CancelOrder(order.BinanceOrderID)
		}
	}

	log.Printf("[DEFENSE] Entered TOXIC mode, cancelled vulnerable orders")
}

// handleDefensiveModeEntry handles entering defensive mode
func (e *DefenseIntegratedEngine) handleDefensiveModeEntry() {
	// Reduce order sizes or cancel older orders
	openOrders := e.executor.GetOpenOrders()
	now := time.Now()

	for _, order := range openOrders {
		// Cancel orders that have been open for more than 1 second
		if now.Sub(order.CreatedAt) > 1*time.Second {
			e.executor.CancelOrder(order.BinanceOrderID)
		}
	}
}

// handleNormalModeEntry handles entering normal mode
func (e *DefenseIntegratedEngine) handleNormalModeEntry() {
	// Resume normal operations
	log.Printf("[DEFENSE] Conditions normalized, resuming normal operations")
}

// cancelOrderByID cancels an order by its ID
func (e *DefenseIntegratedEngine) cancelOrderByID(orderID string) error {
	// Try to find order in executor
	if order, exists := e.executor.GetOrderByID(orderID); exists {
		if order.BinanceOrderID != 0 {
			return e.executor.CancelOrder(order.BinanceOrderID)
		}
	}
	return fmt.Errorf("order not found: %s", orderID)
}

// Start starts the engine with defense
func (e *DefenseIntegratedEngine) Start() error {
	// Start base engine
	if err := e.HFTEngine.Start(); err != nil {
		return err
	}

	// Start defense manager
	if e.config.Enabled {
		e.defenseMgr.Enable()
		log.Println("[DEFENSE] Defense system enabled")
	}

	return nil
}

// Stop stops the engine with defense cleanup
func (e *DefenseIntegratedEngine) Stop() {
	// Disable defense
	if e.defenseMgr != nil {
		e.defenseMgr.Disable()
		e.defenseMgr.Close()
	}

	// Stop base engine
	e.HFTEngine.Stop()
}

// OnDepthUpdateWithDefense processes depth updates with defense injection
func (e *DefenseIntegratedEngine) OnDepthUpdateWithDefense(bestBid, bestAsk float64, ofi float64) {
	// Call base handler
	e.onDepthUpdate(bestBid, bestAsk, ofi)

	// Inject into defense system
	if e.config.Enabled {
		midPrice := (bestBid + bestAsk) / 2
		spread := bestAsk - bestBid
		spreadBPS := spread / midPrice * 10000

		e.defenseMgr.OnMarketTick(MarketTick{
			Timestamp: time.Now(),
			MidPrice:  midPrice,
			BidPrice:  bestBid,
			AskPrice:  bestAsk,
			BidQty:    0, // Would need actual quantity from book
			AskQty:    0,
		})

		// Update FSM state with spread info
		fsmState := DefenseMarketState{
			Timestamp:    time.Now(),
			MidPrice:     midPrice,
			BidAskSpread: spreadBPS / 10000,
			OFI:          ofi,
		}
		e.defenseMgr.fsm.UpdateMarketState(fsmState)
	}
}

// OnTradeUpdateWithDefense processes trade updates with defense injection
func (e *DefenseIntegratedEngine) OnTradeUpdateWithDefense(price, qty float64, isBuyerMaker bool) {
	// Call base handler
	e.onTradeUpdate(price, qty, isBuyerMaker)

	// Inject into defense system
	if e.config.Enabled {
		side := "sell"
		if isBuyerMaker {
			side = "buy"
		}

		e.defenseMgr.OnTrade(TradeTick{
			Timestamp: time.Now(),
			Side:      side,
			Price:     price,
			Quantity:  qty,
			IsMaker:   isBuyerMaker,
		})
	}
}

// ProcessDecisionWithDefense processes decision with defense checks
func (e *DefenseIntegratedEngine) ProcessDecisionWithDefense() bool {
	if !e.config.Enabled {
		return true // Allow if defense disabled
	}

	// Get current defense state
	fsmState := e.defenseMgr.GetFSMState()
	mode := "NORMAL"
	if m, ok := fsmState["mode"].(string); ok {
		mode = m
	}

	// Check if we can execute based on mode
	switch mode {
	case "TOXIC":
		// In toxic mode, check if we have too many orders
		openOrders := e.executor.GetOpenOrders()
		if len(openOrders) >= e.config.MaxOrdersInToxicMode {
			return false
		}
	case "DEFENSIVE":
		// In defensive mode, allow but with caution
		return true
	default:
		// Normal mode - allow
		return true
	}

	return true
}

// CanPlaceOrder checks if an order can be placed in current defense state
func (e *DefenseIntegratedEngine) CanPlaceOrder(side string, size float64) (bool, string) {
	if !e.config.Enabled {
		return true, ""
	}

	// Get current FSM state
	fsmState := e.defenseMgr.GetFSMState()
	policy, ok := fsmState["policy"].(map[string]interface{})
	if !ok {
		return true, ""
	}

	// Check if side is enabled
	if side == "buy" {
		if enabled, ok := policy["enable_bid"].(bool); ok && !enabled {
			return false, "bid_side_disabled_by_defense"
		}
	} else if side == "sell" {
		if enabled, ok := policy["enable_ask"].(bool); ok && !enabled {
			return false, "ask_side_disabled_by_defense"
		}
	}

	return true, ""
}

// GetDefenseStatus returns current defense status for monitoring
func (e *DefenseIntegratedEngine) GetDefenseStatus() map[string]interface{} {
	if !e.config.Enabled {
		return map[string]interface{}{
			"enabled": false,
		}
	}

	return e.defenseMgr.GetCurrentState()
}

// EnableDefense enables defense system
func (e *DefenseIntegratedEngine) EnableDefense() {
	e.config.Enabled = true
	e.defenseMgr.Enable()
	log.Println("[DEFENSE] Defense system enabled")
}

// DisableDefense disables defense system
func (e *DefenseIntegratedEngine) DisableDefense() {
	e.config.Enabled = false
	e.defenseMgr.Disable()
	log.Println("[DEFENSE] Defense system disabled")
}
