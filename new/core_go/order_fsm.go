package main

import (
	"fmt"
	"sync"
	"time"
)

/*
order_fsm.go - Order State Machine

Strict finite state machine for order lifecycle management:
- Prevents illegal state transitions
- Tracks state history with timestamps
- Provides timeout detection
- Supports state change callbacks
- Thread-safe for concurrent access

State Diagram:
┌─────────┐    ┌─────────┐    ┌─────────────────┐
│ Pending │───→│  Open   │───→│ PartiallyFilled │
└─────────┘    └────┬────┘    └────────┬────────┘
     │              │                   │
     │              ▼                   ▼
     │         ┌─────────┐         ┌─────────┐
     └────────→│Cancelled│         │ Filled  │
               └─────────┘         └─────────┘
                    │
                    ▼
               ┌─────────┐
               │Rejected │
               └─────────┘
*/

// OrderState 订单状态
type OrderState int

const (
	OrderStatePending OrderState = iota
	OrderStateOpen
	OrderStatePartiallyFilled
	OrderStateFilled
	OrderStateCancelled
	OrderStateRejected
	OrderStateExpired
)

func (s OrderState) String() string {
	switch s {
	case OrderStatePending:
		return "Pending"
	case OrderStateOpen:
		return "Open"
	case OrderStatePartiallyFilled:
		return "PartiallyFilled"
	case OrderStateFilled:
		return "Filled"
	case OrderStateCancelled:
		return "Cancelled"
	case OrderStateRejected:
		return "Rejected"
	case OrderStateExpired:
		return "Expired"
	default:
		return "Unknown"
	}
}

// IsTerminal 是否为终止状态（不可再转换）
func (s OrderState) IsTerminal() bool {
	switch s {
	case OrderStateFilled, OrderStateCancelled, OrderStateRejected, OrderStateExpired:
		return true
	default:
		return false
	}
}

// StateTransition 状态转换记录
type StateTransition struct {
	From      OrderState
	To        OrderState
	Timestamp time.Time
	Reason    string
}

// OrderFSM 订单状态机
type OrderFSM struct {
	orderID    string
	current    OrderState
	history    []StateTransition
	historyMu  sync.RWMutex

	// 超时配置
	pendingTimeout time.Duration
	openTimeout    time.Duration

	// 回调
	onStateChange func(orderID string, from, to OrderState, reason string)
}

// FSMConfig 状态机配置
type FSMConfig struct {
	PendingTimeout time.Duration // Pending状态超时时间
	OpenTimeout    time.Duration // Open状态超时时间
}

// DefaultFSMConfig 默认配置
func DefaultFSMConfig() *FSMConfig {
	return &FSMConfig{
		PendingTimeout: 30 * time.Second,  // 30秒Pending超时
		OpenTimeout:    24 * time.Hour,    // 24小时Open超时（对于GTC订单）
	}
}

// NewOrderFSM 创建订单状态机
func NewOrderFSM(orderID string, config *FSMConfig) *OrderFSM {
	if config == nil {
		config = DefaultFSMConfig()
	}

	return &OrderFSM{
		orderID:        orderID,
		current:        OrderStatePending,
		history:        make([]StateTransition, 0),
		pendingTimeout: config.PendingTimeout,
		openTimeout:    config.OpenTimeout,
	}
}

// SetStateChangeCallback 设置状态变更回调
func (fsm *OrderFSM) SetStateChangeCallback(cb func(orderID string, from, to OrderState, reason string)) {
	fsm.onStateChange = cb
}

// Current 获取当前状态
func (fsm *OrderFSM) Current() OrderState {
	fsm.historyMu.RLock()
	defer fsm.historyMu.RUnlock()
	return fsm.current
}

// CanTransition 检查是否允许状态转换
func (fsm *OrderFSM) CanTransition(to OrderState) bool {
	fsm.historyMu.RLock()
	from := fsm.current
	fsm.historyMu.RUnlock()

	return IsValidOrderTransition(from, to)
}

// Transition 执行状态转换
func (fsm *OrderFSM) Transition(to OrderState, reason string) error {
	fsm.historyMu.Lock()
	defer fsm.historyMu.Unlock()

	from := fsm.current

	// 检查是否允许转换
	if !IsValidOrderTransition(from, to) {
		return fmt.Errorf("illegal state transition: %s → %s", from.String(), to.String())
	}

	// 记录转换
	transition := StateTransition{
		From:      from,
		To:        to,
		Timestamp: time.Now(),
		Reason:    reason,
	}
	fsm.history = append(fsm.history, transition)
	fsm.current = to

	// 触发回调
	if fsm.onStateChange != nil {
		go fsm.onStateChange(fsm.orderID, from, to, reason)
	}

	return nil
}

// GetHistory 获取状态历史
func (fsm *OrderFSM) GetHistory() []StateTransition {
	fsm.historyMu.RLock()
	defer fsm.historyMu.RUnlock()

	// 返回副本
	history := make([]StateTransition, len(fsm.history))
	copy(history, fsm.history)
	return history
}

// GetTimeInState 获取在当前状态的持续时间
func (fsm *OrderFSM) GetTimeInState() time.Duration {
	fsm.historyMu.RLock()
	defer fsm.historyMu.RUnlock()

	if len(fsm.history) == 0 {
		return 0
	}

	lastTransition := fsm.history[len(fsm.history)-1]
	return time.Since(lastTransition.Timestamp)
}

// IsExpired 检查是否超时
func (fsm *OrderFSM) IsExpired() bool {
	fsm.historyMu.RLock()
	defer fsm.historyMu.RUnlock()

	current := fsm.current

	// 终止状态不会超时
	if current.IsTerminal() {
		return false
	}

	// 计算当前状态持续时间
	var duration time.Duration
	if len(fsm.history) == 0 {
		duration = 0
	} else {
		lastTransition := fsm.history[len(fsm.history)-1]
		duration = time.Since(lastTransition.Timestamp)
	}

	switch current {
	case OrderStatePending:
		return duration > fsm.pendingTimeout
	case OrderStateOpen:
		return duration > fsm.openTimeout
	default:
		return false
	}
}

// IsTerminal 当前是否为终止状态
func (fsm *OrderFSM) IsTerminal() bool {
	return fsm.Current().IsTerminal()
}

// ForceTransition 强制状态转换（用于异常恢复）
func (fsm *OrderFSM) ForceTransition(to OrderState, reason string) {
	fsm.historyMu.Lock()
	defer fsm.historyMu.Unlock()

	from := fsm.current
	transition := StateTransition{
		From:      from,
		To:        to,
		Timestamp: time.Now(),
		Reason:    "FORCE: " + reason,
	}
	fsm.history = append(fsm.history, transition)
	fsm.current = to

	if fsm.onStateChange != nil {
		go fsm.onStateChange(fsm.orderID, from, to, "FORCE: "+reason)
	}
}

// IsValidOrderTransition 检查状态转换是否合法
func IsValidOrderTransition(from, to OrderState) bool {
	// 相同状态不允许转换
	if from == to {
		return false
	}

	// 终止状态不能再转换（除非是强制转换）
	if from.IsTerminal() {
		return false
	}

	switch from {
	case OrderStatePending:
		// Pending 可以转到：Open, Cancelled, Rejected
		return to == OrderStateOpen || to == OrderStateCancelled || to == OrderStateRejected

	case OrderStateOpen:
		// Open 可以转到：PartiallyFilled, Filled, Cancelled, Expired
		return to == OrderStatePartiallyFilled || to == OrderStateFilled ||
			to == OrderStateCancelled || to == OrderStateExpired

	case OrderStatePartiallyFilled:
		// PartiallyFilled 可以转到：Filled, Cancelled
		return to == OrderStateFilled || to == OrderStateCancelled

	default:
		return false
	}
}

// OrderFSMManager 订单状态机管理器
type OrderFSMManager struct {
	fsms    map[string]*OrderFSM
	fsmsMu  sync.RWMutex
	config  *FSMConfig

	// 全局回调
	onStateChange func(orderID string, from, to OrderState, reason string)
}

// NewOrderFSMManager 创建状态机管理器
func NewOrderFSMManager(config *FSMConfig) *OrderFSMManager {
	return &OrderFSMManager{
		fsms:   make(map[string]*OrderFSM),
		config: config,
	}
}

// SetGlobalStateChangeCallback 设置全局状态变更回调
func (m *OrderFSMManager) SetGlobalStateChangeCallback(cb func(orderID string, from, to OrderState, reason string)) {
	m.onStateChange = cb
}

// CreateFSM 为订单创建状态机
func (m *OrderFSMManager) CreateFSM(orderID string) *OrderFSM {
	m.fsmsMu.Lock()
	defer m.fsmsMu.Unlock()

	fsm := NewOrderFSM(orderID, m.config)
	if m.onStateChange != nil {
		fsm.SetStateChangeCallback(m.onStateChange)
	}
	m.fsms[orderID] = fsm
	return fsm
}

// GetFSM 获取订单状态机
func (m *OrderFSMManager) GetFSM(orderID string) (*OrderFSM, bool) {
	m.fsmsMu.RLock()
	defer m.fsmsMu.RUnlock()
	fsm, ok := m.fsms[orderID]
	return fsm, ok
}

// RemoveFSM 移除订单状态机
func (m *OrderFSMManager) RemoveFSM(orderID string) {
	m.fsmsMu.Lock()
	defer m.fsmsMu.Unlock()
	delete(m.fsms, orderID)
}

// GetAllExpired 获取所有超时的订单
func (m *OrderFSMManager) GetAllExpired() []string {
	m.fsmsMu.RLock()
	defer m.fsmsMu.RUnlock()

	var expired []string
	for orderID, fsm := range m.fsms {
		if fsm.IsExpired() {
			expired = append(expired, orderID)
		}
	}
	return expired
}

// GetStats 获取统计信息
func (m *OrderFSMManager) GetStats() map[string]int {
	m.fsmsMu.RLock()
	defer m.fsmsMu.RUnlock()

	stats := map[string]int{
		"Pending":          0,
		"Open":             0,
		"PartiallyFilled":  0,
		"Filled":           0,
		"Cancelled":        0,
		"Rejected":         0,
		"Expired":          0,
		"Total":            len(m.fsms),
	}

	for _, fsm := range m.fsms {
		stats[fsm.Current().String()]++
	}

	return stats
}
