package main

import (
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// TestOrderState_String tests state string representation
func TestOrderState_String(t *testing.T) {
	tests := []struct {
		state    OrderState
		expected string
	}{
		{OrderStatePending, "Pending"},
		{OrderStateOpen, "Open"},
		{OrderStatePartiallyFilled, "PartiallyFilled"},
		{OrderStateFilled, "Filled"},
		{OrderStateCancelled, "Cancelled"},
		{OrderStateRejected, "Rejected"},
		{OrderStateExpired, "Expired"},
		{OrderState(999), "Unknown"},
	}

	for _, tc := range tests {
		if got := tc.state.String(); got != tc.expected {
			t.Errorf("State %d: expected %s, got %s", tc.state, tc.expected, got)
		}
	}
}

// TestOrderState_IsTerminal tests terminal state detection
func TestOrderState_IsTerminal(t *testing.T) {
	terminalStates := []OrderState{OrderStateFilled, OrderStateCancelled, OrderStateRejected, OrderStateExpired}
	nonTerminalStates := []OrderState{OrderStatePending, OrderStateOpen, OrderStatePartiallyFilled}

	for _, s := range terminalStates {
		if !s.IsTerminal() {
			t.Errorf("State %s should be terminal", s.String())
		}
	}

	for _, s := range nonTerminalStates {
		if s.IsTerminal() {
			t.Errorf("State %s should not be terminal", s.String())
		}
	}
}

// TestIsValidOrderTransition tests state transition validation
func TestIsValidOrderTransition(t *testing.T) {
	// Valid transitions
	validTransitions := []struct {
		from OrderState
		to   OrderState
	}{
		{OrderStatePending, OrderStateOpen},
		{OrderStatePending, OrderStateCancelled},
		{OrderStatePending, OrderStateRejected},
		{OrderStateOpen, OrderStatePartiallyFilled},
		{OrderStateOpen, OrderStateFilled},
		{OrderStateOpen, OrderStateCancelled},
		{OrderStateOpen, OrderStateExpired},
		{OrderStatePartiallyFilled, OrderStateFilled},
		{OrderStatePartiallyFilled, OrderStateCancelled},
	}

	for _, tc := range validTransitions {
		if !IsValidOrderTransition(tc.from, tc.to) {
			t.Errorf("Transition %s → %s should be valid", tc.from.String(), tc.to.String())
		}
	}

	// Invalid transitions
	invalidTransitions := []struct {
		from OrderState
		to   OrderState
	}{
		// Same state
		{OrderStatePending, OrderStatePending},
		// Terminal states cannot transition
		{OrderStateFilled, OrderStateCancelled},
		{OrderStateCancelled, OrderStateFilled},
		{OrderStateRejected, OrderStateOpen},
		{OrderStateExpired, OrderStateFilled},
		// Illegal transitions
		{OrderStatePending, OrderStateFilled},
		{OrderStatePending, OrderStatePartiallyFilled},
		{OrderStateOpen, OrderStatePending},
		{OrderStatePartiallyFilled, OrderStateOpen},
		{OrderStatePartiallyFilled, OrderStatePending},
		{OrderStatePartiallyFilled, OrderStateExpired},
	}

	for _, tc := range invalidTransitions {
		if IsValidOrderTransition(tc.from, tc.to) {
			t.Errorf("Transition %s → %s should be invalid", tc.from.String(), tc.to.String())
		}
	}
}

// TestOrderFSM_Transition tests basic state transitions
func TestOrderFSM_Transition(t *testing.T) {
	fsm := NewOrderFSM("order-1", nil)

	// Initial state should be Pending
	if fsm.Current() != OrderStatePending {
		t.Errorf("Initial state should be Pending, got %s", fsm.Current().String())
	}

	// Valid transition: Pending → Open
	if err := fsm.Transition(OrderStateOpen, "order accepted"); err != nil {
		t.Errorf("Failed to transition to Open: %v", err)
	}
	if fsm.Current() != OrderStateOpen {
		t.Errorf("Current state should be Open, got %s", fsm.Current().String())
	}

	// Valid transition: Open → Filled
	if err := fsm.Transition(OrderStateFilled, "fully filled"); err != nil {
		t.Errorf("Failed to transition to Filled: %v", err)
	}
	if fsm.Current() != OrderStateFilled {
		t.Errorf("Current state should be Filled, got %s", fsm.Current().String())
	}

	// Invalid transition: Filled → Cancelled
	if err := fsm.Transition(OrderStateCancelled, "try cancel"); err == nil {
		t.Error("Should fail to transition from Filled to Cancelled")
	}

	// Check history
	history := fsm.GetHistory()
	if len(history) != 2 {
		t.Errorf("History should have 2 transitions, got %d", len(history))
	}

	// Check first transition
	if history[0].From != OrderStatePending || history[0].To != OrderStateOpen {
		t.Error("First transition should be Pending → Open")
	}
	if history[0].Reason != "order accepted" {
		t.Errorf("First transition reason should be 'order accepted', got %s", history[0].Reason)
	}

	// Check second transition
	if history[1].From != OrderStateOpen || history[1].To != OrderStateFilled {
		t.Error("Second transition should be Open → Filled")
	}
}

// TestOrderFSM_CanTransition tests CanTransition method
func TestOrderFSM_CanTransition(t *testing.T) {
	fsm := NewOrderFSM("order-1", nil)

	if !fsm.CanTransition(OrderStateOpen) {
		t.Error("Should be able to transition from Pending to Open")
	}

	if fsm.CanTransition(OrderStateFilled) {
		t.Error("Should not be able to transition from Pending to Filled")
	}

	// Transition to Open
	fsm.Transition(OrderStateOpen, "")

	if !fsm.CanTransition(OrderStateFilled) {
		t.Error("Should be able to transition from Open to Filled")
	}

	// Transition to Filled
	fsm.Transition(OrderStateFilled, "")

	if fsm.CanTransition(OrderStateCancelled) {
		t.Error("Should not be able to transition from Filled (terminal)")
	}
}

// TestOrderFSM_ForceTransition tests force transition
func TestOrderFSM_ForceTransition(t *testing.T) {
	fsm := NewOrderFSM("order-1", nil)

	// Normal transition
	fsm.Transition(OrderStateOpen, "normal")
	fsm.Transition(OrderStateFilled, "filled")

	// Force transition from terminal state
	fsm.ForceTransition(OrderStateCancelled, "manual override")

	if fsm.Current() != OrderStateCancelled {
		t.Errorf("After force transition, state should be Cancelled, got %s", fsm.Current().String())
	}

	// Check history
	history := fsm.GetHistory()
	if len(history) != 3 {
		t.Errorf("History should have 3 transitions, got %d", len(history))
	}

	// Last transition should be marked as FORCE
	if history[2].Reason != "FORCE: manual override" {
		t.Errorf("Force transition reason should start with 'FORCE:', got %s", history[2].Reason)
	}
}

// TestOrderFSM_Callback tests state change callback
func TestOrderFSM_Callback(t *testing.T) {
	fsm := NewOrderFSM("order-1", nil)

	var callbackOrderID string
	var callbackFrom, callbackTo OrderState
	var callbackReason string
	var callbackCount int32

	fsm.SetStateChangeCallback(func(orderID string, from, to OrderState, reason string) {
		atomic.AddInt32(&callbackCount, 1)
		callbackOrderID = orderID
		callbackFrom = from
		callbackTo = to
		callbackReason = reason
	})

	// Trigger transition
	fsm.Transition(OrderStateOpen, "test reason")

	// Wait for callback (it's in a goroutine)
	time.Sleep(50 * time.Millisecond)

	if atomic.LoadInt32(&callbackCount) != 1 {
		t.Errorf("Callback should be called once, got %d", callbackCount)
	}

	if callbackOrderID != "order-1" {
		t.Errorf("Callback orderID should be 'order-1', got %s", callbackOrderID)
	}

	if callbackFrom != OrderStatePending {
		t.Errorf("Callback from state should be Pending, got %s", callbackFrom.String())
	}

	if callbackTo != OrderStateOpen {
		t.Errorf("Callback to state should be Open, got %s", callbackTo.String())
	}

	if callbackReason != "test reason" {
		t.Errorf("Callback reason should be 'test reason', got %s", callbackReason)
	}
}

// TestOrderFSM_IsTerminal tests terminal state detection
func TestOrderFSM_IsTerminal(t *testing.T) {
	fsm := NewOrderFSM("order-1", nil)

	if fsm.IsTerminal() {
		t.Error("Pending should not be terminal")
	}

	fsm.Transition(OrderStateOpen, "")
	if fsm.IsTerminal() {
		t.Error("Open should not be terminal")
	}

	fsm.Transition(OrderStateFilled, "")
	if !fsm.IsTerminal() {
		t.Error("Filled should be terminal")
	}
}

// TestOrderFSM_ConcurrentAccess tests thread safety
func TestOrderFSM_ConcurrentAccess(t *testing.T) {
	fsm := NewOrderFSM("order-1", nil)
	fsm.Transition(OrderStateOpen, "")

	var wg sync.WaitGroup
	numGoroutines := 10
	numIterations := 100

	// Concurrent reads
	wg.Add(numGoroutines)
	for i := 0; i < numGoroutines; i++ {
		go func() {
			defer wg.Done()
			for j := 0; j < numIterations; j++ {
				_ = fsm.Current()
				_ = fsm.GetHistory()
				_ = fsm.GetTimeInState()
				_ = fsm.IsExpired()
				_ = fsm.IsTerminal()
				_ = fsm.CanTransition(OrderStateFilled)
			}
		}()
	}

	wg.Wait()
}

// TestOrderFSMManager tests FSM manager
func TestOrderFSMManager(t *testing.T) {
	manager := NewOrderFSMManager(nil)

	// Create FSMs
	fsm1 := manager.CreateFSM("order-1")
	fsm2 := manager.CreateFSM("order-2")

	if fsm1 == nil || fsm2 == nil {
		t.Error("CreateFSM should return non-nil FSMs")
	}

	// Get FSM
	gotFsm, ok := manager.GetFSM("order-1")
	if !ok {
		t.Error("Should find order-1")
	}
	if gotFsm != fsm1 {
		t.Error("Got wrong FSM for order-1")
	}

	// Get non-existent FSM
	_, ok = manager.GetFSM("order-999")
	if ok {
		t.Error("Should not find order-999")
	}

	// Remove FSM
	manager.RemoveFSM("order-1")
	_, ok = manager.GetFSM("order-1")
	if ok {
		t.Error("Should not find order-1 after removal")
	}
}

// TestOrderFSMManager_GlobalCallback tests global callback
func TestOrderFSMManager_GlobalCallback(t *testing.T) {
	manager := NewOrderFSMManager(nil)

	var callbackCount int32
	manager.SetGlobalStateChangeCallback(func(orderID string, from, to OrderState, reason string) {
		atomic.AddInt32(&callbackCount, 1)
	})

	fsm := manager.CreateFSM("order-1")
	fsm.Transition(OrderStateOpen, "")

	time.Sleep(50 * time.Millisecond)

	if atomic.LoadInt32(&callbackCount) != 1 {
		t.Errorf("Global callback should be called once, got %d", callbackCount)
	}
}

// TestOrderFSMManager_GetStats tests statistics
func TestOrderFSMManager_GetStats(t *testing.T) {
	manager := NewOrderFSMManager(nil)

	// Create FSMs and transition to different states
	fsm1 := manager.CreateFSM("order-1")
	fsm1.Transition(OrderStateOpen, "")
	fsm1.Transition(OrderStateFilled, "")

	fsm2 := manager.CreateFSM("order-2")
	fsm2.Transition(OrderStateOpen, "")

	fsm3 := manager.CreateFSM("order-3")
	fsm3.Transition(OrderStateCancelled, "")

	manager.CreateFSM("order-4") // Pending

	stats := manager.GetStats()

	if stats["Total"] != 4 {
		t.Errorf("Total should be 4, got %d", stats["Total"])
	}
	if stats["Filled"] != 1 {
		t.Errorf("Filled should be 1, got %d", stats["Filled"])
	}
	if stats["Open"] != 1 {
		t.Errorf("Open should be 1, got %d", stats["Open"])
	}
	if stats["Cancelled"] != 1 {
		t.Errorf("Cancelled should be 1, got %d", stats["Cancelled"])
	}
	if stats["Pending"] != 1 {
		t.Errorf("Pending should be 1, got %d", stats["Pending"])
	}
}

// TestDefaultFSMConfig tests default configuration
func TestDefaultFSMConfig(t *testing.T) {
	config := DefaultFSMConfig()

	if config.PendingTimeout != 30*time.Second {
		t.Errorf("PendingTimeout should be 30s, got %v", config.PendingTimeout)
	}

	if config.OpenTimeout != 24*time.Hour {
		t.Errorf("OpenTimeout should be 24h, got %v", config.OpenTimeout)
	}
}

// TestOrderFSM_Lifecycle tests complete order lifecycle scenarios
func TestOrderFSM_Lifecycle(t *testing.T) {
	// Scenario 1: Market order lifecycle (Pending → Open → Filled)
	t.Run("MarketOrder", func(t *testing.T) {
		fsm := NewOrderFSM("market-order", nil)

		steps := []struct {
			to     OrderState
			reason string
		}{
			{OrderStateOpen, "order accepted by exchange"},
			{OrderStateFilled, "fully executed"},
		}

		for _, step := range steps {
			if err := fsm.Transition(step.to, step.reason); err != nil {
				t.Fatalf("Failed to transition to %s: %v", step.to.String(), err)
			}
		}

		if !fsm.IsTerminal() {
			t.Error("Market order should end in terminal state")
		}

		history := fsm.GetHistory()
		if len(history) != 2 {
			t.Errorf("Should have 2 transitions, got %d", len(history))
		}
	})

	// Scenario 2: Limit order lifecycle with partial fill
	t.Run("LimitOrderPartialFill", func(t *testing.T) {
		fsm := NewOrderFSM("limit-order", nil)

		steps := []struct {
			to     OrderState
			reason string
		}{
			{OrderStateOpen, "limit order placed"},
			{OrderStatePartiallyFilled, "50% filled"},
			{OrderStateFilled, "remaining 50% filled"},
		}

		for _, step := range steps {
			if err := fsm.Transition(step.to, step.reason); err != nil {
				t.Fatalf("Failed to transition to %s: %v", step.to.String(), err)
			}
		}

		if fsm.Current() != OrderStateFilled {
			t.Errorf("Final state should be Filled, got %s", fsm.Current().String())
		}
	})

	// Scenario 3: Cancelled order
	t.Run("CancelledOrder", func(t *testing.T) {
		fsm := NewOrderFSM("cancelled-order", nil)

		if err := fsm.Transition(OrderStateOpen, "order placed"); err != nil {
			t.Fatal(err)
		}

		if err := fsm.Transition(OrderStateCancelled, "user cancelled"); err != nil {
			t.Fatal(err)
		}

		// Try to fill cancelled order
		if err := fsm.Transition(OrderStateFilled, "late fill"); err == nil {
			t.Error("Should not be able to fill cancelled order")
		}
	})

	// Scenario 4: Rejected order
	t.Run("RejectedOrder", func(t *testing.T) {
		fsm := NewOrderFSM("rejected-order", nil)

		if err := fsm.Transition(OrderStateRejected, "insufficient funds"); err != nil {
			t.Fatal(err)
		}

		if !fsm.IsTerminal() {
			t.Error("Rejected order should be in terminal state")
		}
	})

	// Scenario 5: Expired order
	t.Run("ExpiredOrder", func(t *testing.T) {
		fsm := NewOrderFSM("expired-order", nil)

		if err := fsm.Transition(OrderStateOpen, "GTC order placed"); err != nil {
			t.Fatal(err)
		}

		if err := fsm.Transition(OrderStateExpired, "IOC order expired"); err != nil {
			t.Fatal(err)
		}

		if fsm.Current() != OrderStateExpired {
			t.Errorf("Final state should be Expired, got %s", fsm.Current().String())
		}
	})
}
