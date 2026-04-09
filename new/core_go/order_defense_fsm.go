package main

import (
	"container/heap"
	"fmt"
	"sync"
	"time"
)

// 市场模式定义
type MarketMode int

const (
	ModeNormal MarketMode = iota
	ModeDefensive
	ModeToxic
)

func (m MarketMode) String() string {
	switch m {
	case ModeNormal:
		return "NORMAL"
	case ModeDefensive:
		return "DEFENSIVE"
	case ModeToxic:
		return "TOXIC"
	default:
		return "UNKNOWN"
	}
}

// DefenseOrderPriority 防御订单优先级定义
type DefenseOrderPriority int

const (
	DefensePriorityCritical DefenseOrderPriority = iota // 危险订单，必须1ms内撤
	DefensePriorityNormal                               // 中性订单
	DefensePrioritySafe                                 // 安全订单
)

// 市场方向
type MarketSide int

const (
	SideNeutral MarketSide = iota
	SideBuyPressure
	SideSellPressure
)

func (s MarketSide) String() string {
	switch s {
	case SideNeutral:
		return "NEUTRAL"
	case SideBuyPressure:
		return "BUY_PRESSURE"
	case SideSellPressure:
		return "SELL_PRESSURE"
	default:
		return "UNKNOWN"
	}
}

// ManagedOrder 受管理的订单
type ManagedOrder struct {
	ID             string
	Symbol         string
	Side           string  // "buy" or "sell"
	Price          float64
	Quantity       float64
	CreatedAt      time.Time
	UpdatedAt      time.Time
	FilledQty      float64
	Priority       DefenseOrderPriority
	IsActive       bool
	IsCanceled     bool
	AlphaAtEntry   float64
	QueuePosition  float64
	TimeInQueue    time.Duration
	ToxicExposure  float64
	CancelPriority int
	index          int // 用于堆的内部索引
}

// DefenseMarketState 防御市场状态
type DefenseMarketState struct {
	Timestamp        time.Time
	ToxicScore       float64
	ToxicSide        MarketSide
	QueuePressure    float64
	AlphaSignal      float64
	MidPrice         float64
	BidAskSpread     float64
	RecentVolatility float64
	OFI              float64 // Order Flow Imbalance
}

// ExecutionPolicy 执行策略
type ExecutionPolicy struct {
	EnableBid            bool
	EnableAsk            bool
	SpreadMultiplier     float64
	SizeMultiplier       float64
	MaxOrderAge          time.Duration
	CancelAggressiveness float64
	Mode                 MarketMode
	MinSpreadBPS         float64
}

// OrderQueue 订单优先级队列
type OrderQueue []*ManagedOrder

func (oq OrderQueue) Len() int { return len(oq) }

func (oq OrderQueue) Less(i, j int) bool {
	// 高优先级排在前面
	if oq[i].Priority != oq[j].Priority {
		return oq[i].Priority < oq[j].Priority
	}
	return oq[i].CancelPriority > oq[j].CancelPriority
}

func (oq OrderQueue) Swap(i, j int) {
	oq[i], oq[j] = oq[j], oq[i]
	oq[i].index = i
	oq[j].index = j
}

func (oq *OrderQueue) Push(x interface{}) {
	n := len(*oq)
	item := x.(*ManagedOrder)
	item.index = n
	*oq = append(*oq, item)
}

func (oq *OrderQueue) Pop() interface{} {
	old := *oq
	n := len(old)
	item := old[n-1]
	old[n-1] = nil
	item.index = -1
	*oq = old[0 : n-1]
	return item
}

// ModeTransition 模式转换记录
type ModeTransition struct {
	Timestamp   time.Time
	From        MarketMode
	To          MarketMode
	ToxicScore  float64
	ToxicSide   MarketSide
	AlphaSignal float64
	Reason      string
}

// FSMStats 状态机统计
type FSMStats struct {
	TotalOrders       int
	OrdersCanceled    int
	OrdersRejected    int
	ModeChanges       int
	AvgCancelLatency  time.Duration
	MaxCancelLatency  time.Duration
	LastCancelTime    time.Time
	CriticalCancels   int
	NormalCancels     int
	SafeCancels       int
}

// OrderDefenseFSM 订单防御状态机
type OrderDefenseFSM struct {
	mu              sync.RWMutex
	currentMode     MarketMode
	modeHistory     []ModeTransition
	activeOrders    map[string]*ManagedOrder
	orderQueue      OrderQueue
	lastModeChange  time.Time
	modeChangeCount int
	cooldownUntil   time.Time
	policy          ExecutionPolicy
	stats           FSMStats
	cancelChan      chan string
	enabled         bool
}

// NewOrderDefenseFSM 创建订单防御状态机
func NewOrderDefenseFSM() *OrderDefenseFSM {
	fsm := &OrderDefenseFSM{
		currentMode:  ModeNormal,
		activeOrders: make(map[string]*ManagedOrder),
		orderQueue:   make(OrderQueue, 0),
		policy:       getDefaultDefensePolicy(ModeNormal),
		stats:        FSMStats{},
		cancelChan:   make(chan string, 1000),
		enabled:      true,
	}

	heap.Init(&fsm.orderQueue)

	return fsm
}

// SetEnabled 启用/禁用FSM
func (fsm *OrderDefenseFSM) SetEnabled(enabled bool) {
	fsm.mu.Lock()
	defer fsm.mu.Unlock()
	fsm.enabled = enabled
}

// getDefaultDefensePolicy 获取默认防御策略
func getDefaultDefensePolicy(mode MarketMode) ExecutionPolicy {
	switch mode {
	case ModeNormal:
		return ExecutionPolicy{
			EnableBid:            true,
			EnableAsk:            true,
			SpreadMultiplier:     1.0,
			SizeMultiplier:       1.0,
			MaxOrderAge:          5 * time.Second,
			CancelAggressiveness: 0.2,
			Mode:                 mode,
			MinSpreadBPS:         2.0,
		}

	case ModeDefensive:
		return ExecutionPolicy{
			EnableBid:            true,
			EnableAsk:            true,
			SpreadMultiplier:     1.5,
			SizeMultiplier:       0.5,
			MaxOrderAge:          2 * time.Second,
			CancelAggressiveness: 0.6,
			Mode:                 mode,
			MinSpreadBPS:         3.0,
		}

	case ModeToxic:
		return ExecutionPolicy{
			EnableBid:            false,
			EnableAsk:            false,
			SpreadMultiplier:     2.0,
			SizeMultiplier:       0.3,
			MaxOrderAge:          500 * time.Millisecond,
			CancelAggressiveness: 0.95,
			Mode:                 mode,
			MinSpreadBPS:         5.0,
		}

	default:
		return getDefaultDefensePolicy(ModeNormal)
	}
}

// UpdateMarketState 更新市场状态（主入口）
func (fsm *OrderDefenseFSM) UpdateMarketState(state DefenseMarketState) {
	fsm.mu.Lock()
	defer fsm.mu.Unlock()

	if !fsm.enabled {
		return
	}

	// 检查冷却
	if time.Now().Before(fsm.cooldownUntil) {
		return
	}

	// 决定新状态
	newMode := fsm.decideMode(state)

	// 如果状态变化，处理切换
	if newMode != fsm.currentMode {
		fsm.handleModeTransition(newMode, state)
	}

	// 更新当前策略
	fsm.updatePolicyForMode(fsm.currentMode, state)

	// 根据当前策略调整订单
	fsm.adjustOrders(state)
}

// decideMode 决定市场模式
func (fsm *OrderDefenseFSM) decideMode(state DefenseMarketState) MarketMode {
	// 高毒流分数进入Toxic模式
	if state.ToxicScore > 0.8 {
		return ModeToxic
	}

	// 中等毒流分数进入Defensive模式
	if state.ToxicScore > 0.6 {
		return ModeDefensive
	}

	// 极高波动率进入Defensive模式
	if state.RecentVolatility > 0.8 && fsm.currentMode != ModeToxic {
		return ModeDefensive
	}

	// 如果刚从Toxic模式切换出来，进入Defensive模式冷却
	if fsm.currentMode == ModeToxic && time.Since(fsm.lastModeChange) < 3*time.Second {
		return ModeDefensive
	}

	// 如果刚从Defensive模式切换出来，短暂冷却
	if fsm.currentMode == ModeDefensive && time.Since(fsm.lastModeChange) < 500*time.Millisecond {
		return ModeDefensive
	}

	// 否则进入Normal模式
	return ModeNormal
}

// handleModeTransition 处理模式切换
func (fsm *OrderDefenseFSM) handleModeTransition(newMode MarketMode, state DefenseMarketState) {
	transition := ModeTransition{
		Timestamp:   time.Now(),
		From:        fsm.currentMode,
		To:          newMode,
		ToxicScore:  state.ToxicScore,
		ToxicSide:   state.ToxicSide,
		AlphaSignal: state.AlphaSignal,
		Reason:      fsm.getTransitionReason(fsm.currentMode, newMode, state),
	}

	fsm.modeHistory = append(fsm.modeHistory, transition)

	// 更新状态
	fsm.currentMode = newMode
	fsm.lastModeChange = time.Now()
	fsm.modeChangeCount++
	fsm.stats.ModeChanges++

	// 设置冷却时间
	switch newMode {
	case ModeToxic:
		fsm.cooldownUntil = time.Now().Add(2 * time.Second)
	case ModeDefensive:
		fsm.cooldownUntil = time.Now().Add(500 * time.Millisecond)
	default:
		fsm.cooldownUntil = time.Time{}
	}

	// 记录切换
	fsm.logModeTransition(transition)

	// 立即触发撤单
	fsm.immediateCancelOnTransition(newMode, state)
}

// immediateCancelOnTransition 模式切换时立即撤单
func (fsm *OrderDefenseFSM) immediateCancelOnTransition(newMode MarketMode, state DefenseMarketState) {
	switch newMode {
	case ModeToxic:
		// Toxic模式下立即撤所有危险订单
		for _, order := range fsm.activeOrders {
			if !order.IsActive || order.IsCanceled {
				continue
			}
			// 检查是否处于毒流方向
			if (order.Side == "buy" && state.ToxicSide == SideSellPressure) ||
				(order.Side == "sell" && state.ToxicSide == SideBuyPressure) {
				select {
				case fsm.cancelChan <- order.ID:
					order.Priority = DefensePriorityCritical
				default:
				}
			}
		}

	case ModeDefensive:
		// Defensive模式下撤高风险的订单
		for _, order := range fsm.activeOrders {
			if !order.IsActive || order.IsCanceled {
				continue
			}
			// 检查Alpha信号是否反转
			if (order.Side == "buy" && order.AlphaAtEntry < -0.1) ||
				(order.Side == "sell" && order.AlphaAtEntry > 0.1) {
				select {
				case fsm.cancelChan <- order.ID:
					order.Priority = DefensePriorityNormal
				default:
				}
			}
		}
	}
}

// getTransitionReason 获取切换原因
func (fsm *OrderDefenseFSM) getTransitionReason(from, to MarketMode, state DefenseMarketState) string {
	switch to {
	case ModeToxic:
		if state.ToxicScore > 0.8 {
			return "toxic_score_critical"
		}
		return "toxic_conditions"
	case ModeDefensive:
		if state.ToxicScore > 0.6 {
			return "toxic_score_elevated"
		}
		if state.RecentVolatility > 0.8 {
			return "extreme_volatility"
		}
		if state.OFI > 0.7 || state.OFI < -0.7 {
			return "high_ofi_pressure"
		}
		return "post_toxic_cooldown"
	case ModeNormal:
		if from == ModeToxic {
			return "toxic_resolved"
		}
		return "conditions_normalized"
	default:
		return "unknown"
	}
}

// logModeTransition 记录模式切换
func (fsm *OrderDefenseFSM) logModeTransition(transition ModeTransition) {
	fmt.Printf("[DEFENSE-FSM] %s -> %s | toxic=%.3f side=%s reason=%s\n",
		transition.From.String(),
		transition.To.String(),
		transition.ToxicScore,
		transition.ToxicSide.String(),
		transition.Reason)
}

// updatePolicyForMode 根据模式更新策略
func (fsm *OrderDefenseFSM) updatePolicyForMode(mode MarketMode, state DefenseMarketState) {
	policy := getDefaultDefensePolicy(mode)

	// 在Toxic模式下，根据毒流方向决定开启哪一侧
	if mode == ModeToxic {
		switch state.ToxicSide {
		case SideBuyPressure:
			// 买压大，只开启卖单（吃买盘的返佣）
			policy.EnableBid = false
			policy.EnableAsk = true
		case SideSellPressure:
			// 卖压大，只开启买单（吃卖盘的返佣）
			policy.EnableBid = true
			policy.EnableAsk = false
		default:
			// 中性，双边关闭
			policy.EnableBid = false
			policy.EnableAsk = false
		}
	}

	// 动态调整撤单攻击性
	if state.ToxicScore > 0.9 {
		policy.CancelAggressiveness = 1.0
	}

	fsm.policy = policy
}

// adjustOrders 调整订单
func (fsm *OrderDefenseFSM) adjustOrders(state DefenseMarketState) {
	startTime := time.Now()

	// 重新计算每个订单的优先级
	fsm.calculateOrderPriorities(state)

	// 执行撤单
	fsm.executeCancellations(state)

	// 记录延迟
	latency := time.Since(startTime)
	if latency > fsm.stats.MaxCancelLatency {
		fsm.stats.MaxCancelLatency = latency
	}
	if fsm.stats.OrdersCanceled > 0 {
		fsm.stats.AvgCancelLatency = (fsm.stats.AvgCancelLatency*time.Duration(fsm.stats.OrdersCanceled) + latency) /
			time.Duration(fsm.stats.OrdersCanceled+1)
	}
}

// calculateOrderPriorities 计算订单优先级
func (fsm *OrderDefenseFSM) calculateOrderPriorities(state DefenseMarketState) {
	// 清空优先级队列
	fsm.orderQueue = fsm.orderQueue[:0]
	heap.Init(&fsm.orderQueue)

	for _, order := range fsm.activeOrders {
		if !order.IsActive || order.IsCanceled {
			continue
		}

		// 计算时间风险
		order.TimeInQueue = time.Since(order.CreatedAt)
		timeRisk := 0.0
		if order.TimeInQueue > fsm.policy.MaxOrderAge {
			timeRisk = 1.0
		} else {
			timeRisk = float64(order.TimeInQueue) / float64(fsm.policy.MaxOrderAge)
		}

		// 计算Alpha方向风险
		alphaRisk := 0.0
		if (order.Side == "buy" && order.AlphaAtEntry < -0.2) ||
			(order.Side == "sell" && order.AlphaAtEntry > 0.2) {
			alphaRisk = 1.0
		} else if (order.Side == "buy" && order.AlphaAtEntry < 0) ||
			(order.Side == "sell" && order.AlphaAtEntry > 0) {
			alphaRisk = 0.5
		}

		// 计算队列位置风险（越靠后风险越高）
		queueRisk := order.QueuePosition

		// 计算毒流暴露风险
		toxicRisk := 0.0
		if (order.Side == "buy" && state.ToxicSide == SideSellPressure) ||
			(order.Side == "sell" && state.ToxicSide == SideBuyPressure) {
			toxicRisk = state.ToxicScore
		} else if state.ToxicScore > 0.5 {
			toxicRisk = state.ToxicScore * 0.3
		}

		// 计算价差风险
		spreadRisk := 0.0
		if state.BidAskSpread > 0.001 { // 10bps
			spreadRisk = defenseMin(1.0, state.BidAskSpread/0.003)
		}

		// 计算OFI风险
		ofiRisk := 0.0
		if (order.Side == "buy" && state.OFI < -0.5) ||
			(order.Side == "sell" && state.OFI > 0.5) {
			ofiRisk = defenseAbs(state.OFI)
		}

		// 计算综合风险分数（加权）
		riskScore := 0.25*timeRisk +
			0.25*alphaRisk +
			0.15*queueRisk +
			0.20*toxicRisk +
			0.10*spreadRisk +
			0.05*ofiRisk

		// 决定优先级
		if riskScore > 0.7 {
			order.Priority = DefensePriorityCritical
			order.CancelPriority = 100 + int(riskScore*100)
		} else if riskScore > 0.4 {
			order.Priority = DefensePriorityNormal
			order.CancelPriority = 50 + int(riskScore*50)
		} else {
			order.Priority = DefensePrioritySafe
			order.CancelPriority = int(riskScore * 50)
		}

		// 添加到优先级队列
		heap.Push(&fsm.orderQueue, order)
	}
}

// executeCancellations 执行撤单
func (fsm *OrderDefenseFSM) executeCancellations(state DefenseMarketState) {
	// 根据当前模式的攻击性决定撤单数量
	cancelRate := fsm.policy.CancelAggressiveness
	queueLen := fsm.orderQueue.Len()
	ordersToCancel := int(float64(queueLen) * cancelRate)

	if ordersToCancel == 0 && queueLen > 0 && cancelRate > 0.5 {
		ordersToCancel = 1 // 至少撤一个
	}

	for i := 0; i < ordersToCancel && fsm.orderQueue.Len() > 0; i++ {
		order := heap.Pop(&fsm.orderQueue).(*ManagedOrder)

		// 检查订单是否仍然活跃
		if !order.IsActive || order.IsCanceled {
			continue
		}

		// 检查是否允许撤单
		if !fsm.shouldCancelOrder(order, state) {
			continue
		}

		// 执行撤单
		if fsm.cancelOrder(order) {
			order.IsCanceled = true
			order.UpdatedAt = time.Now()
			fsm.stats.OrdersCanceled++
			fsm.stats.LastCancelTime = time.Now()

			// 统计优先级
			switch order.Priority {
			case DefensePriorityCritical:
				fsm.stats.CriticalCancels++
			case DefensePriorityNormal:
				fsm.stats.NormalCancels++
			case DefensePrioritySafe:
				fsm.stats.SafeCancels++
			}
		}
	}

	// 处理紧急撤单通道
	select {
	case orderID := <-fsm.cancelChan:
		if order, exists := fsm.activeOrders[orderID]; exists && order.IsActive && !order.IsCanceled {
			if fsm.cancelOrder(order) {
				order.IsCanceled = true
				order.UpdatedAt = time.Now()
				fsm.stats.OrdersCanceled++
				fsm.stats.CriticalCancels++
			}
		}
	default:
	}
}

// shouldCancelOrder 检查是否应撤单
func (fsm *OrderDefenseFSM) shouldCancelOrder(order *ManagedOrder, state DefenseMarketState) bool {
	// 检查当前模式是否允许此方向的订单
	if order.Side == "buy" && !fsm.policy.EnableBid {
		return true
	}
	if order.Side == "sell" && !fsm.policy.EnableAsk {
		return true
	}

	// 检查订单是否已过期
	if time.Since(order.CreatedAt) > fsm.policy.MaxOrderAge {
		return true
	}

	// 检查Alpha信号是否已反转（超过阈值）
	if (order.Side == "buy" && order.AlphaAtEntry < -0.1 && state.AlphaSignal < -0.2) ||
		(order.Side == "sell" && order.AlphaAtEntry > 0.1 && state.AlphaSignal > 0.2) {
		return true
	}

	// 检查毒流风险
	if (order.Side == "buy" && state.ToxicSide == SideSellPressure && state.ToxicScore > 0.7) ||
		(order.Side == "sell" && state.ToxicSide == SideBuyPressure && state.ToxicScore > 0.7) {
		return true
	}

	// 检查OFI压力
	if (order.Side == "buy" && state.OFI < -0.7) ||
		(order.Side == "sell" && state.OFI > 0.7) {
		return true
	}

	return false
}

// cancelOrder 取消订单（实际应调用交易所API）
func (fsm *OrderDefenseFSM) cancelOrder(order *ManagedOrder) bool {
	// 这里应该调用实际的交易所API取消订单
	// 返回true表示撤单请求已发送
	return true
}

// AddOrder 添加新订单
func (fsm *OrderDefenseFSM) AddOrder(order *ManagedOrder) (bool, string) {
	fsm.mu.Lock()
	defer fsm.mu.Unlock()

	if !fsm.enabled {
		return false, "fsm_disabled"
	}

	// 检查是否允许此方向的订单
	if order.Side == "buy" && !fsm.policy.EnableBid {
		fsm.stats.OrdersRejected++
		return false, "bid_side_disabled"
	}
	if order.Side == "sell" && !fsm.policy.EnableAsk {
		fsm.stats.OrdersRejected++
		return false, "ask_side_disabled"
	}

	// 设置订单属性
	order.CreatedAt = time.Now()
	order.UpdatedAt = time.Now()
	order.IsActive = true
	order.IsCanceled = false

	// 添加到活动订单列表
	fsm.activeOrders[order.ID] = order
	fsm.stats.TotalOrders++

	return true, ""
}

// UpdateOrderStatus 更新订单状态
func (fsm *OrderDefenseFSM) UpdateOrderStatus(orderID string, filledQty float64, avgPrice float64) {
	fsm.mu.Lock()
	defer fsm.mu.Unlock()

	order, exists := fsm.activeOrders[orderID]
	if !exists {
		return
	}

	order.FilledQty = filledQty
	order.UpdatedAt = time.Now()

	// 如果完全成交，从活动订单中移除
	if order.FilledQty >= order.Quantity {
		order.IsActive = false
		delete(fsm.activeOrders, orderID)
	}
}

// CancelOrder 请求撤单
func (fsm *OrderDefenseFSM) CancelOrder(orderID string) bool {
	fsm.mu.RLock()
	defer fsm.mu.RUnlock()

	if order, exists := fsm.activeOrders[orderID]; exists && order.IsActive && !order.IsCanceled {
		select {
		case fsm.cancelChan <- orderID:
			return true
		default:
			return false
		}
	}
	return false
}

// GetCurrentState 获取当前状态
func (fsm *OrderDefenseFSM) GetCurrentState() map[string]interface{} {
	fsm.mu.RLock()
	defer fsm.mu.RUnlock()

	return map[string]interface{}{
		"mode":              fsm.currentMode.String(),
		"active_orders":     len(fsm.activeOrders),
		"mode_changes":      fsm.modeChangeCount,
		"last_mode_change":  fsm.lastModeChange,
		"cooldown_until":    fsm.cooldownUntil,
		"enabled":           fsm.enabled,
		"stats":             fsm.stats,
		"policy": map[string]interface{}{
			"enable_bid":       fsm.policy.EnableBid,
			"enable_ask":       fsm.policy.EnableAsk,
			"spread_mult":      fsm.policy.SpreadMultiplier,
			"size_mult":        fsm.policy.SizeMultiplier,
			"max_order_age_ms": fsm.policy.MaxOrderAge.Milliseconds(),
			"cancel_agg":       fsm.policy.CancelAggressiveness,
		},
	}
}

// GetCancelSuggestions 获取撤单建议
func (fsm *OrderDefenseFSM) GetCancelSuggestions() []string {
	fsm.mu.RLock()
	defer fsm.mu.RUnlock()

	var suggestions []string
	for i := 0; i < 5 && i < len(fsm.orderQueue); i++ {
		order := fsm.orderQueue[i]
		suggestions = append(suggestions, order.ID)
	}

	return suggestions
}

// GetCancelChan 获取Cancel通道
func (fsm *OrderDefenseFSM) GetCancelChan() <-chan string {
	return fsm.cancelChan
}

// GetActiveOrders 获取活动订单
func (fsm *OrderDefenseFSM) GetActiveOrders() map[string]*ManagedOrder {
	fsm.mu.RLock()
	defer fsm.mu.RUnlock()

	// 返回副本
	orders := make(map[string]*ManagedOrder)
	for k, v := range fsm.activeOrders {
		orders[k] = v
	}
	return orders
}

// GetModeHistory 获取模式历史
func (fsm *OrderDefenseFSM) GetModeHistory() []ModeTransition {
	fsm.mu.RLock()
	defer fsm.mu.RUnlock()

	history := make([]ModeTransition, len(fsm.modeHistory))
	copy(history, fsm.modeHistory)
	return history
}

// ResetStats 重置统计
func (fsm *OrderDefenseFSM) ResetStats() {
	fsm.mu.Lock()
	defer fsm.mu.Unlock()

	fsm.stats = FSMStats{}
}

// min 最小值
func defenseMin(a, b float64) float64 {
	if a < b {
		return a
	}
	return b
}

// abs 绝对值
func defenseAbs(a float64) float64 {
	if a < 0 {
		return -a
	}
	return a
}
