package main

import (
	"context"
	"fmt"
	"sync"
	"time"
)

// DefenseManager 防御管理器 - 整合FSM和毒流检测
type DefenseManager struct {
	fsm           *OrderDefenseFSM
	toxicDetector *ToxicDetector
	lastUpdate    time.Time
	config        DefenseManagerConfig
	mu            sync.RWMutex

	// 数据通道
	tradeChan chan TradeTick
	tickChan  chan MarketTick

	// 控制
	ctx    context.Context
	cancel context.CancelFunc
	wg     sync.WaitGroup

	// 回调
	onModeChange func(from, to MarketMode, reason string)
	onCancel     func(orderID string, reason string)
}

// DefenseManagerConfig 防御管理器配置
type DefenseManagerConfig struct {
	UpdateInterval      time.Duration
	TradeBufferSize     int
	TickBufferSize      int
	EnableAutoCancel    bool
	MaxOrdersPerSecond  int
	EmergencyThreshold  float64
}

// DefaultDefenseManagerConfig 默认配置
func DefaultDefenseManagerConfig() DefenseManagerConfig {
	return DefenseManagerConfig{
		UpdateInterval:     50 * time.Millisecond,
		TradeBufferSize:    1000,
		TickBufferSize:     500,
		EnableAutoCancel:   true,
		MaxOrdersPerSecond: 10,
		EmergencyThreshold: 0.9,
	}
}

// NewDefenseManager 创建防御管理器
func NewDefenseManager(config DefenseManagerConfig) *DefenseManager {
	ctx, cancel := context.WithCancel(context.Background())

	dm := &DefenseManager{
		fsm:           NewOrderDefenseFSM(),
		toxicDetector: NewToxicDetector(DefaultToxicConfig()),
		config:        config,
		tradeChan:     make(chan TradeTick, config.TradeBufferSize),
		tickChan:      make(chan MarketTick, config.TickBufferSize),
		ctx:           ctx,
		cancel:        cancel,
		lastUpdate:    time.Now(),
	}

	// 启动后台处理循环
	dm.wg.Add(2)
	go dm.dataIngestionLoop()
	go dm.defenseLoop()

	return dm
}

// Close 关闭防御管理器
func (dm *DefenseManager) Close() {
	dm.cancel()
	dm.wg.Wait()
	close(dm.tradeChan)
	close(dm.tickChan)
}

// SetModeChangeCallback 设置模式切换回调
func (dm *DefenseManager) SetModeChangeCallback(cb func(from, to MarketMode, reason string)) {
	dm.mu.Lock()
	defer dm.mu.Unlock()
	dm.onModeChange = cb
}

// SetCancelCallback 设置撤单回调
func (dm *DefenseManager) SetCancelCallback(cb func(orderID string, reason string)) {
	dm.mu.Lock()
	defer dm.mu.Unlock()
	dm.onCancel = cb
}

// dataIngestionLoop 数据摄取循环
func (dm *DefenseManager) dataIngestionLoop() {
	defer dm.wg.Done()

	for {
		select {
		case <-dm.ctx.Done():
			return
		case trade := <-dm.tradeChan:
			dm.toxicDetector.AddTrade(trade)
		case tick := <-dm.tickChan:
			dm.toxicDetector.AddMarketTick(tick)
		}
	}
}

// defenseLoop 防御主循环
func (dm *DefenseManager) defenseLoop() {
	defer dm.wg.Done()

	ticker := time.NewTicker(dm.config.UpdateInterval)
	defer ticker.Stop()

	for {
		select {
		case <-dm.ctx.Done():
			return
		case <-ticker.C:
			dm.updateDefense()
		}
	}
}

// updateDefense 更新防御状态
func (dm *DefenseManager) updateDefense() {
	// 执行毒流检测
	detection := dm.toxicDetector.Detect()

	// 获取当前市场数据
	marketState := dm.buildMarketState(detection)

	// 获取当前模式（用于检测模式变化）
	oldState := dm.fsm.GetCurrentState()
	oldMode := ModeNormal
	if mode, ok := oldState["mode"].(string); ok {
		switch mode {
		case "DEFENSIVE":
			oldMode = ModeDefensive
		case "TOXIC":
			oldMode = ModeToxic
		}
	}

	// 更新FSM
	dm.fsm.UpdateMarketState(marketState)

	// 检查模式变化
	newState := dm.fsm.GetCurrentState()
	if newMode, ok := newState["mode"].(string); ok {
		var newModeEnum MarketMode
		switch newMode {
		case "DEFENSIVE":
			newModeEnum = ModeDefensive
		case "TOXIC":
			newModeEnum = ModeToxic
		default:
			newModeEnum = ModeNormal
		}

		if newModeEnum != oldMode && dm.onModeChange != nil {
			reason := "toxic_detection"
			if detection.ToxicScore < 0.6 {
				reason = "conditions_normalized"
			}
			dm.onModeChange(oldMode, newModeEnum, reason)
		}
	}

	// 处理撤单
	if dm.config.EnableAutoCancel {
		dm.processCancellations()
	}

	dm.lastUpdate = time.Now()
}

// buildMarketState 构建市场状态
func (dm *DefenseManager) buildMarketState(detection ToxicDetection) DefenseMarketState {
	return DefenseMarketState{
		Timestamp:        time.Now(),
		ToxicScore:       detection.ToxicScore,
		ToxicSide:        detection.ToxicSide,
		AlphaSignal:      0, // 应由外部注入
		MidPrice:         0, // 应由外部注入
		BidAskSpread:     0, // 应由外部注入
		RecentVolatility: detection.Volatility,
		OFI:              detection.OFI,
	}
}

// processCancellations 处理撤单
func (dm *DefenseManager) processCancellations() {
	cancelChan := dm.fsm.GetCancelChan()

	select {
	case orderID := <-cancelChan:
		if dm.onCancel != nil {
			dm.onCancel(orderID, "defense_triggered")
		}
	default:
	}
}

// OnTrade 处理成交数据（外部调用）
func (dm *DefenseManager) OnTrade(trade TradeTick) {
	select {
	case dm.tradeChan <- trade:
	default:
		// 通道满，丢弃最旧的数据
	}
}

// OnMarketTick 处理市场数据（外部调用）
func (dm *DefenseManager) OnMarketTick(tick MarketTick) {
	select {
	case dm.tickChan <- tick:
	default:
		// 通道满，丢弃最旧的数据
	}
}

// AddOrder 添加订单
func (dm *DefenseManager) AddOrder(order *ManagedOrder) (bool, string) {
	return dm.fsm.AddOrder(order)
}

// UpdateOrderStatus 更新订单状态
func (dm *DefenseManager) UpdateOrderStatus(orderID string, filledQty, avgPrice float64) {
	dm.fsm.UpdateOrderStatus(orderID, filledQty, avgPrice)
}

// CancelOrder 请求撤单
func (dm *DefenseManager) CancelOrder(orderID string) bool {
	return dm.fsm.CancelOrder(orderID)
}

// GetCurrentState 获取当前状态
func (dm *DefenseManager) GetCurrentState() map[string]interface{} {
	dm.mu.RLock()
	defer dm.mu.RUnlock()

	fsmState := dm.fsm.GetCurrentState()
	toxicState := dm.toxicDetector.GetCurrentState()

	return map[string]interface{}{
		"fsm":        fsmState,
		"toxic":      toxicState,
		"last_update": dm.lastUpdate,
	}
}

// GetFSMState 获取FSM状态
func (dm *DefenseManager) GetFSMState() map[string]interface{} {
	return dm.fsm.GetCurrentState()
}

// GetToxicState 获取毒流状态
func (dm *DefenseManager) GetToxicState() ToxicDetection {
	return dm.toxicDetector.GetCurrentState()
}

// IsToxic 当前是否处于毒流状态
func (dm *DefenseManager) IsToxic() bool {
	return dm.toxicDetector.IsToxic()
}

// GetSafeSide 获取当前安全侧（在TOXIC模式下应该交易的方向）
// 买压大 -> 安全侧是卖 (可以吃买盘返佣)
// 卖压大 -> 安全侧是买
func (dm *DefenseManager) GetSafeSide() OrderSide {
	toxicState := dm.GetToxicState()
	switch toxicState.ToxicSide {
	case SideBuyPressure:
		return SideSell
	case SideSellPressure:
		return SideBuy
	default:
		// 中性：默认返回买
		return SideBuy
	}
}

// GetCancelSuggestions 获取撤单建议
func (dm *DefenseManager) GetCancelSuggestions() []string {
	return dm.fsm.GetCancelSuggestions()
}

// Enable 启用防御
func (dm *DefenseManager) Enable() {
	dm.fsm.SetEnabled(true)
	fmt.Println("[DefenseManager] Defense enabled")
}

// Disable 禁用防御
func (dm *DefenseManager) Disable() {
	dm.fsm.SetEnabled(false)
	fmt.Println("[DefenseManager] Defense disabled")
}

// Reset 重置所有状态
func (dm *DefenseManager) Reset() {
	dm.toxicDetector.Reset()
	dm.fsm.ResetStats()
	fmt.Println("[DefenseManager] Defense reset")
}

// GetStats 获取统计信息
func (dm *DefenseManager) GetStats() map[string]interface{} {
	return map[string]interface{}{
		"fsm_stats":  dm.fsm.GetCurrentState()["stats"],
		"detections": dm.toxicDetector.GetDetectionCount(),
	}
}
