package leverage

import (
	"fmt"
	"log"
	"sync"
	"time"
)

// LiquidationAlert 强平预警
type LiquidationAlert struct {
	Symbol            string        `json:"symbol"`
	Side              Side          `json:"side"`
	PositionID        string        `json:"position_id"`
	AlertType         AlertType     `json:"alert_type"`
	CurrentPrice      float64       `json:"current_price"`
	LiquidationPrice  float64       `json:"liquidation_price"`
	Distance          float64       `json:"distance"`           // 距离强平百分比
	MarginLevel       float64       `json:"margin_level"`       // 保证金率
	RecommendedAction ActionType    `json:"recommended_action"` // 建议操作
	Message           string        `json:"message"`
	Timestamp         time.Time     `json:"timestamp"`
	Severity          AlertSeverity `json:"severity"`
}

// AlertType 预警类型
type AlertType int

const (
	AlertDistanceWarning AlertType = iota // 距离预警
	AlertMarginCall                       // 追加保证金通知
	AlertApproachingLiq                   // 接近强平
	AlertLiquidationImminent              // 即将强平
	AlertLiquidationTriggered             // 已触发强平
)

func (a AlertType) String() string {
	switch a {
	case AlertDistanceWarning:
		return "DISTANCE_WARNING"
	case AlertMarginCall:
		return "MARGIN_CALL"
	case AlertApproachingLiq:
		return "APPROACHING_LIQUIDATION"
	case AlertLiquidationImminent:
		return "LIQUIDATION_IMMINENT"
	case AlertLiquidationTriggered:
		return "LIQUIDATION_TRIGGERED"
	default:
		return "UNKNOWN"
	}
}

// AlertSeverity 预警严重等级
type AlertSeverity int

const (
	SeverityInfo AlertSeverity = iota
	SeverityWarning
	SeverityCritical
	SeverityEmergency
)

func (s AlertSeverity) String() string {
	switch s {
	case SeverityInfo:
		return "INFO"
	case SeverityWarning:
		return "WARNING"
	case SeverityCritical:
		return "CRITICAL"
	case SeverityEmergency:
		return "EMERGENCY"
	default:
		return "UNKNOWN"
	}
}

// ActionType 建议操作类型
type ActionType int

const (
	ActionNone ActionType = iota
	ActionReducePosition
	ActionAddMargin
	ActionClosePartial
	ActionCloseAll
	ActionHedgePosition
)

func (a ActionType) String() string {
	switch a {
	case ActionNone:
		return "NONE"
	case ActionReducePosition:
		return "REDUCE_POSITION"
	case ActionAddMargin:
		return "ADD_MARGIN"
	case ActionClosePartial:
		return "CLOSE_PARTIAL"
	case ActionCloseAll:
		return "CLOSE_ALL"
	case ActionHedgePosition:
		return "HEDGE_POSITION"
	default:
		return "UNKNOWN"
	}
}

// AlertConfig 预警配置
type AlertConfig struct {
	DistanceWarningThreshold    float64       // 距离预警阈值（百分比）
	MarginCallThreshold         float64       // 追加保证金阈值
	ApproachingLiqThreshold     float64       // 接近强平阈值
	LiquidationImminentDistance float64       // 即将强平距离
	CheckInterval               time.Duration // 检查间隔
	EnableAutoAction            bool          // 是否启用自动操作
	AutoActionThreshold         float64       // 自动操作阈值
}

// DefaultAlertConfig 默认预警配置
func DefaultAlertConfig() *AlertConfig {
	return &AlertConfig{
		DistanceWarningThreshold:    20.0, // 距离强平20%时预警
		MarginCallThreshold:         1.5,  // 保证金率低于150%
		ApproachingLiqThreshold:     1.2,  // 保证金率低于120%
		LiquidationImminentDistance: 2.0,  // 距离强平2%时紧急预警
		CheckInterval:               5 * time.Second,
		EnableAutoAction:            false,
		AutoActionThreshold:         1.0, // 保证金率100%时自动操作
	}
}

// LiquidationRiskMonitor 强平风险监控器
type LiquidationRiskMonitor struct {
	config       *AlertConfig
	calculator   *Calculator
	positionMgr  *PositionManager
	alerts       []LiquidationAlert
	alertCallbacks []func(LiquidationAlert)
	actionCallbacks map[ActionType]func(LiquidationAlert)
	stopChan     chan struct{}
	mu           sync.RWMutex
	running      bool
}

// NewLiquidationRiskMonitor 创建强平风险监控器
func NewLiquidationRiskMonitor(config *AlertConfig, calculator *Calculator, positionMgr *PositionManager) *LiquidationRiskMonitor {
	if config == nil {
		config = DefaultAlertConfig()
	}

	return &LiquidationRiskMonitor{
		config:          config,
		calculator:      calculator,
		positionMgr:     positionMgr,
		alerts:          make([]LiquidationAlert, 0),
		alertCallbacks:  make([]func(LiquidationAlert), 0),
		actionCallbacks: make(map[ActionType]func(LiquidationAlert)),
		stopChan:        make(chan struct{}),
	}
}

// Start 开始监控
func (m *LiquidationRiskMonitor) Start() {
	m.mu.Lock()
	defer m.mu.Unlock()

	if m.running {
		return
	}

	m.running = true
	go m.monitorLoop()
	log.Println("[RiskMonitor] Started liquidation risk monitoring")
}

// Stop 停止监控
func (m *LiquidationRiskMonitor) Stop() {
	m.mu.Lock()
	defer m.mu.Unlock()

	if !m.running {
		return
	}

	m.running = false
	close(m.stopChan)
	log.Println("[RiskMonitor] Stopped liquidation risk monitoring")
}

// IsRunning 检查监控器是否运行中
func (m *LiquidationRiskMonitor) IsRunning() bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.running
}

// monitorLoop 监控循环
func (m *LiquidationRiskMonitor) monitorLoop() {
	ticker := time.NewTicker(m.config.CheckInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			m.checkAllPositions()
		case <-m.stopChan:
			return
		}
	}
}

// checkAllPositions 检查所有仓位
func (m *LiquidationRiskMonitor) checkAllPositions() {
	positions := m.positionMgr.GetAllPositions()
	for _, pos := range positions {
		m.checkPosition(pos)
	}
}

// checkPosition 检查单个仓位
func (m *LiquidationRiskMonitor) checkPosition(position *LeveragedPosition) {
	// 获取当前价格（这里使用标记价格，实际应该从市场数据获取）
	markPrice := position.MarkPrice
	if markPrice == 0 {
		markPrice = position.EntryPrice // 如果没有标记价格，使用入场价
	}

	// 计算实时保证金信息
	marginInfo := m.calculator.CalculateRealTimeMargin(position, markPrice)

	// 检查是否需要预警
	alert := m.evaluateRisk(position, marginInfo)
	if alert != nil {
		m.triggerAlert(*alert)
	}
}

// evaluateRisk 评估风险并生成预警
func (m *LiquidationRiskMonitor) evaluateRisk(position *LeveragedPosition, info *RealTimeMarginInfo) *LiquidationAlert {
	// 检查是否已经触发强平
	isLiquidated, _ := m.positionMgr.CheckLiquidationBySide(position.Symbol, position.Side, info.MarkPrice)
	if isLiquidated {
		return &LiquidationAlert{
			Symbol:            position.Symbol,
			Side:              position.Side,
			PositionID:        position.ID,
			AlertType:         AlertLiquidationTriggered,
			CurrentPrice:      info.MarkPrice,
			LiquidationPrice:  info.LiquidationPrice,
			Distance:          0,
			MarginLevel:       info.MarginLevel,
			RecommendedAction: ActionCloseAll,
			Message:           fmt.Sprintf("Position %s %s has been LIQUIDATED at price %.2f", position.Symbol, position.Side, info.MarkPrice),
			Timestamp:         time.Now(),
			Severity:          SeverityEmergency,
		}
	}

	// 检查即将强平（距离小于阈值）
	if info.DistanceToLiq <= m.config.LiquidationImminentDistance {
		return &LiquidationAlert{
			Symbol:            position.Symbol,
			Side:              position.Side,
			PositionID:        position.ID,
			AlertType:         AlertLiquidationImminent,
			CurrentPrice:      info.MarkPrice,
			LiquidationPrice:  info.LiquidationPrice,
			Distance:          info.DistanceToLiq,
			MarginLevel:       info.MarginLevel,
			RecommendedAction: ActionCloseAll,
			Message:           fmt.Sprintf("CRITICAL: %s %s is %.2f%% from liquidation! Close position immediately!", position.Symbol, position.Side, info.DistanceToLiq),
			Timestamp:         time.Now(),
			Severity:          SeverityEmergency,
		}
	}

	// 检查接近强平
	if info.MarginLevel <= m.config.ApproachingLiqThreshold {
		return &LiquidationAlert{
			Symbol:            position.Symbol,
			Side:              position.Side,
			PositionID:        position.ID,
			AlertType:         AlertApproachingLiq,
			CurrentPrice:      info.MarkPrice,
			LiquidationPrice:  info.LiquidationPrice,
			Distance:          info.DistanceToLiq,
			MarginLevel:       info.MarginLevel,
			RecommendedAction: ActionAddMargin,
			Message:           fmt.Sprintf("WARNING: %s %s margin level is %.2f%% (threshold: %.2f%%). Add margin or reduce position.", position.Symbol, position.Side, info.MarginLevel*100, m.config.ApproachingLiqThreshold*100),
			Timestamp:         time.Now(),
			Severity:          SeverityCritical,
		}
	}

	// 检查追加保证金
	if info.MarginLevel <= m.config.MarginCallThreshold {
		return &LiquidationAlert{
			Symbol:            position.Symbol,
			Side:              position.Side,
			PositionID:        position.ID,
			AlertType:         AlertMarginCall,
			CurrentPrice:      info.MarkPrice,
			LiquidationPrice:  info.LiquidationPrice,
			Distance:          info.DistanceToLiq,
			MarginLevel:       info.MarginLevel,
			RecommendedAction: ActionReducePosition,
			Message:           fmt.Sprintf("MARGIN CALL: %s %s margin level is %.2f%%. Consider adding margin or reducing position size.", position.Symbol, position.Side, info.MarginLevel*100),
			Timestamp:         time.Now(),
			Severity:          SeverityWarning,
		}
	}

	// 检查距离预警
	if info.DistanceToLiq <= m.config.DistanceWarningThreshold {
		return &LiquidationAlert{
			Symbol:            position.Symbol,
			Side:              position.Side,
			PositionID:        position.ID,
			AlertType:         AlertDistanceWarning,
			CurrentPrice:      info.MarkPrice,
			LiquidationPrice:  info.LiquidationPrice,
			Distance:          info.DistanceToLiq,
			MarginLevel:       info.MarginLevel,
			RecommendedAction: ActionNone,
			Message:           fmt.Sprintf("NOTICE: %s %s is %.2f%% from liquidation price. Monitor closely.", position.Symbol, position.Side, info.DistanceToLiq),
			Timestamp:         time.Now(),
			Severity:          SeverityInfo,
		}
	}

	return nil
}

// triggerAlert 触发预警
func (m *LiquidationRiskMonitor) triggerAlert(alert LiquidationAlert) {
	m.mu.Lock()
	m.alerts = append(m.alerts, alert)
	m.mu.Unlock()

	// 记录日志
	log.Printf("[RiskMonitor] ALERT [%s] %s: %s", alert.Severity, alert.AlertType, alert.Message)

	// 调用回调函数
	m.mu.RLock()
	callbacks := m.alertCallbacks
	m.mu.RUnlock()

	for _, callback := range callbacks {
		go callback(alert)
	}

	// 调用动作回调
	if actionCallback, ok := m.actionCallbacks[alert.RecommendedAction]; ok {
		go actionCallback(alert)
	}

	// 检查是否需要自动操作
	if m.config.EnableAutoAction && alert.MarginLevel <= m.config.AutoActionThreshold {
		m.executeAutoAction(alert)
	}
}

// executeAutoAction 执行自动操作
func (m *LiquidationRiskMonitor) executeAutoAction(alert LiquidationAlert) {
	log.Printf("[RiskMonitor] Executing auto action: %s for %s %s", alert.RecommendedAction, alert.Symbol, alert.Side)

	switch alert.RecommendedAction {
	case ActionCloseAll:
		// 自动平仓
		_, err := m.positionMgr.ClosePositionBySide(alert.Symbol, alert.Side, alert.CurrentPrice)
		if err != nil {
			log.Printf("[RiskMonitor] Auto close failed: %v", err)
		}
	case ActionClosePartial:
		// 自动减仓50%
		position, _ := m.positionMgr.GetPositionBySide(alert.Symbol, alert.Side)
		if position != nil {
			reduceSize := position.Size * 0.5
			_, err := m.positionMgr.ReducePositionBySide(alert.Symbol, alert.Side, reduceSize, alert.CurrentPrice)
			if err != nil {
				log.Printf("[RiskMonitor] Auto partial close failed: %v", err)
			}
		}
	}
}

// RegisterAlertCallback 注册预警回调
func (m *LiquidationRiskMonitor) RegisterAlertCallback(callback func(LiquidationAlert)) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.alertCallbacks = append(m.alertCallbacks, callback)
}

// RegisterActionCallback 注册操作回调
func (m *LiquidationRiskMonitor) RegisterActionCallback(action ActionType, callback func(LiquidationAlert)) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.actionCallbacks[action] = callback
}

// GetAlerts 获取历史预警
func (m *LiquidationRiskMonitor) GetAlerts(since time.Time) []LiquidationAlert {
	m.mu.RLock()
	defer m.mu.RUnlock()

	var result []LiquidationAlert
	for _, alert := range m.alerts {
		if alert.Timestamp.After(since) {
			result = append(result, alert)
		}
	}
	return result
}

// GetRecentAlerts 获取最近N条预警
func (m *LiquidationRiskMonitor) GetRecentAlerts(count int) []LiquidationAlert {
	m.mu.RLock()
	defer m.mu.RUnlock()

	if count <= 0 {
		return nil
	}

	start := len(m.alerts) - count
	if start < 0 {
		start = 0
	}

	result := make([]LiquidationAlert, len(m.alerts)-start)
	copy(result, m.alerts[start:])
	return result
}

// ClearAlerts 清空预警历史
func (m *LiquidationRiskMonitor) ClearAlerts() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.alerts = make([]LiquidationAlert, 0)
}

// UpdateConfig 更新配置
func (m *LiquidationRiskMonitor) UpdateConfig(config *AlertConfig) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.config = config
}

// GetConfig 获取当前配置
func (m *LiquidationRiskMonitor) GetConfig() *AlertConfig {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.config
}

// ForceCheck 强制检查指定仓位
func (m *LiquidationRiskMonitor) ForceCheck(symbol string, side Side, markPrice float64) *LiquidationAlert {
	position, ok := m.positionMgr.GetPositionBySide(symbol, side)
	if !ok {
		return nil
	}

	marginInfo := m.calculator.CalculateRealTimeMargin(position, markPrice)
	alert := m.evaluateRisk(position, marginInfo)

	if alert != nil {
		m.triggerAlert(*alert)
	}

	return alert
}

// RiskSummary 风险摘要
type RiskSummary struct {
	TotalPositions    int                `json:"total_positions"`
	AtRiskPositions   int                `json:"at_risk_positions"`
	TotalMargin       float64            `json:"total_margin"`
	TotalUnrealizedPnL float64           `json:"total_unrealized_pnl"`
	AverageMarginLevel float64           `json:"average_margin_level"`
	HighestRisk       *RiskPositionInfo  `json:"highest_risk"`
	AlertCount        int                `json:"alert_count_last_24h"`
}

// RiskPositionInfo 风险仓位信息
type RiskPositionInfo struct {
	Symbol           string  `json:"symbol"`
	Side             Side    `json:"side"`
	MarginLevel      float64 `json:"margin_level"`
	DistanceToLiq    float64 `json:"distance_to_liq"`
	LiquidationPrice float64 `json:"liquidation_price"`
}

// GetRiskSummary 获取风险摘要
func (m *LiquidationRiskMonitor) GetRiskSummary() *RiskSummary {
	positions := m.positionMgr.GetAllPositions()

	summary := &RiskSummary{
		TotalPositions: len(positions),
		HighestRisk:    nil,
	}

	if len(positions) == 0 {
		return summary
	}

	var totalMarginLevel float64
	minMarginLevel := 999.0

	for _, pos := range positions {
		markPrice := pos.MarkPrice
		if markPrice == 0 {
			markPrice = pos.EntryPrice
		}

		info := m.calculator.CalculateRealTimeMargin(pos, markPrice)
		summary.TotalMargin += pos.Margin
		summary.TotalUnrealizedPnL += info.UnrealizedPnL
		totalMarginLevel += info.MarginLevel

		if info.MarginLevel < 1.5 {
			summary.AtRiskPositions++
		}

		if info.MarginLevel < minMarginLevel {
			minMarginLevel = info.MarginLevel
			summary.HighestRisk = &RiskPositionInfo{
				Symbol:           pos.Symbol,
				Side:             pos.Side,
				MarginLevel:      info.MarginLevel,
				DistanceToLiq:    info.DistanceToLiq,
				LiquidationPrice: info.LiquidationPrice,
			}
		}
	}

	summary.AverageMarginLevel = totalMarginLevel / float64(len(positions))

	// 统计最近24小时的预警数量
	recentAlerts := m.GetAlerts(time.Now().Add(-24 * time.Hour))
	summary.AlertCount = len(recentAlerts)

	return summary
}
