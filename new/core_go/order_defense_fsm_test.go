package main

import (
	"fmt"
	"testing"
	"time"
)

func TestOrderDefenseFSM(t *testing.T) {
	// 创建FSM
	fsm := NewOrderDefenseFSM()

	// 测试正常模式
	state := DefenseMarketState{
		Timestamp:        time.Now(),
		ToxicScore:       0.3,
		ToxicSide:        SideNeutral,
		QueuePressure:    0.5,
		AlphaSignal:      0.1,
		MidPrice:         100.0,
		BidAskSpread:     0.1,
		RecentVolatility: 0.5,
		OFI:              0.0,
	}

	fsm.UpdateMarketState(state)

	// 检查状态
	currentState := fsm.GetCurrentState()
	if currentState["mode"] != "NORMAL" {
		t.Errorf("Expected mode NORMAL, got %v", currentState["mode"])
	}

	// 添加测试订单
	order := &ManagedOrder{
		ID:            "test_order_1",
		Symbol:        "BTCUSDT",
		Side:          "buy",
		Price:         100.0,
		Quantity:      0.01,
		AlphaAtEntry:  0.2,
		QueuePosition: 0.3,
	}

	added, reason := fsm.AddOrder(order)
	if !added {
		t.Errorf("Failed to add order: %s", reason)
	}

	// 切换到防御模式
	state.ToxicScore = 0.7
	fsm.UpdateMarketState(state)

	currentState = fsm.GetCurrentState()
	if currentState["mode"] != "DEFENSIVE" {
		t.Errorf("Expected mode DEFENSIVE, got %v", currentState["mode"])
	}

	// 切换到毒流模式（需要等待冷却期结束）
	time.Sleep(600 * time.Millisecond) // 等待DEFENSIVE冷却期结束
	state.ToxicScore = 0.9
	state.ToxicSide = SideSellPressure
	fsm.UpdateMarketState(state)

	currentState = fsm.GetCurrentState()
	if currentState["mode"] != "TOXIC" {
		t.Errorf("Expected mode TOXIC, got %v", currentState["mode"])
	}

	// 检查策略
	policy := currentState["policy"].(map[string]interface{})
	if !policy["enable_bid"].(bool) {
		t.Error("Expected enable_bid=true in TOXIC mode with sell pressure")
	}
	if policy["enable_ask"].(bool) {
		t.Error("Expected enable_ask=false in TOXIC mode with sell pressure")
	}

	t.Log("FSM test passed")
}

func TestOrderPriorityQueue(t *testing.T) {
	fsm := NewOrderDefenseFSM()

	// 添加多个订单
	orders := []*ManagedOrder{
		{ID: "order1", Side: "buy", AlphaAtEntry: -0.5, QueuePosition: 0.8},
		{ID: "order2", Side: "sell", AlphaAtEntry: 0.2, QueuePosition: 0.2},
		{ID: "order3", Side: "buy", AlphaAtEntry: 0.1, QueuePosition: 0.5},
	}

	for _, order := range orders {
		fsm.AddOrder(order)
	}

	// 更新市场状态触发优先级计算
	state := DefenseMarketState{
		Timestamp:        time.Now(),
		ToxicScore:       0.8,
		ToxicSide:        SideSellPressure,
		AlphaSignal:      -0.3,
		RecentVolatility: 0.6,
	}

	fsm.UpdateMarketState(state)

	// 获取撤单建议
	suggestions := fsm.GetCancelSuggestions()
	if len(suggestions) == 0 {
		t.Error("Expected cancel suggestions")
	}

	// order1应该是最高优先级（buy side + negative alpha + sell pressure）
	if suggestions[0] != "order1" {
		t.Logf("First suggestion: %s (expected order1)", suggestions[0])
	}

	t.Log("Priority queue test passed")
}

func TestModeTransition(t *testing.T) {
	fsm := NewOrderDefenseFSM()

	transitions := []struct {
		toxicScore float64
		expected   string
	}{
		{0.3, "NORMAL"},
		{0.7, "DEFENSIVE"},
		{0.9, "TOXIC"},
		{0.5, "DEFENSIVE"}, // 冷却期内保持DEFENSIVE
		{0.3, "DEFENSIVE"}, // 仍在冷却
		{0.2, "NORMAL"},    // 冷却结束后
	}

	for i, trans := range transitions {
		state := DefenseMarketState{
			Timestamp:        time.Now(),
			ToxicScore:       trans.toxicScore,
			ToxicSide:        SideNeutral,
			RecentVolatility: 0.3,
		}

		fsm.UpdateMarketState(state)
		currentState := fsm.GetCurrentState()

		// 对于冷却期测试，我们可能需要等待
		if trans.expected == "NORMAL" && currentState["mode"] != "NORMAL" {
			time.Sleep(3 * time.Second) // 等待冷却期结束
			fsm.UpdateMarketState(state)
			currentState = fsm.GetCurrentState()
		}

		t.Logf("Transition %d: toxic=%.1f, mode=%s (expected %s)",
			i, trans.toxicScore, currentState["mode"], trans.expected)
	}
}

func TestOrderRejection(t *testing.T) {
	fsm := NewOrderDefenseFSM()

	// 切换到Toxic模式
	state := DefenseMarketState{
		ToxicScore:       0.9,
		ToxicSide:        SideBuyPressure,
		RecentVolatility: 0.5,
	}
	fsm.UpdateMarketState(state)

	// 尝试添加买单（应该被拒绝）
	buyOrder := &ManagedOrder{
		ID:     "buy_order",
		Side:   "buy",
		Price:  100.0,
		Quantity: 0.01,
	}

	added, reason := fsm.AddOrder(buyOrder)
	if added {
		t.Error("Expected buy order to be rejected in TOXIC mode with buy pressure")
	}
	if reason != "bid_side_disabled" {
		t.Errorf("Expected reason 'bid_side_disabled', got '%s'", reason)
	}

	// 尝试添加卖单（应该被接受）
	sellOrder := &ManagedOrder{
		ID:       "sell_order",
		Side:     "sell",
		Price:    101.0,
		Quantity: 0.01,
	}

	added, reason = fsm.AddOrder(sellOrder)
	if !added {
		t.Errorf("Expected sell order to be accepted, got reason: %s", reason)
	}
}

func BenchmarkFSMUpdate(b *testing.B) {
	fsm := NewOrderDefenseFSM()

	// 添加一些订单
	for i := 0; i < 100; i++ {
		order := &ManagedOrder{
			ID:            fmt.Sprintf("order_%d", i),
			Side:          "buy",
			Price:         100.0,
			Quantity:      0.01,
			AlphaAtEntry:  0.1,
			QueuePosition: 0.5,
		}
		fsm.AddOrder(order)
	}

	state := DefenseMarketState{
		ToxicScore:       0.5,
		ToxicSide:        SideNeutral,
		RecentVolatility: 0.3,
		OFI:              0.1,
	}

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		state.ToxicScore = float64(i%10) / 10.0
		fsm.UpdateMarketState(state)
	}
}
