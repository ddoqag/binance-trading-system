package verification

import (
	"context"
	"fmt"
	"math"
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

/*
state_consistency.go - 状态一致性检查器

验证内存状态与交易所状态的一致性。
核心功能：
1. 定期同步检查内存订单状态与交易所状态
2. 检测状态差异（遗漏成交、状态不一致）
3. 仓位一致性验证
4. 自动修复建议
*/

// StateDiff 状态差异
type StateDiff struct {
	OrderID          string
	Field            string
	LocalValue       interface{}
	ExchangeValue    interface{}
	DiffType         DiffType
	Severity         Severity
	DetectedAt       time.Time
	SuggestedAction  string
}

// DiffType 差异类型
type DiffType int

const (
	DiffTypeStatus DiffType = iota      // 状态不一致
	DiffTypeQuantity                    // 数量不一致
	DiffTypePrice                       // 价格不一致
	DiffTypeMissingLocal                // 本地缺失
	DiffTypeMissingExchange             // 交易所缺失
	DiffTypeOrphan                      // 孤儿订单
)

func (d DiffType) String() string {
	switch d {
	case DiffTypeStatus:
		return "status_mismatch"
	case DiffTypeQuantity:
		return "quantity_mismatch"
	case DiffTypePrice:
		return "price_mismatch"
	case DiffTypeMissingLocal:
		return "missing_local"
	case DiffTypeMissingExchange:
		return "missing_exchange"
	case DiffTypeOrphan:
		return "orphan_order"
	default:
		return "unknown"
	}
}

// Severity 严重程度
type Severity int

const (
	SeverityLow Severity = iota      // 轻微
	SeverityMedium                   // 中等
	SeverityHigh                     // 严重
	SeverityCritical                 // 关键
)

func (s Severity) String() string {
	switch s {
	case SeverityLow:
		return "low"
	case SeverityMedium:
		return "medium"
	case SeverityHigh:
		return "high"
	case SeverityCritical:
		return "critical"
	default:
		return "unknown"
	}
}

// LocalOrderState 本地订单状态
type LocalOrderState struct {
	OrderID           string
	Symbol            string
	Side              string
	Price             float64
	Quantity          float64
	FilledQuantity    float64
	Status            string
	CreatedAt         time.Time
	UpdatedAt         time.Time
	ExchangeOrderID   string
}

// ExchangeOrderState 交易所订单状态
type ExchangeOrderState struct {
	OrderID         string
	Symbol          string
	Side            string
	Price           float64
	OrigQty         float64
	ExecutedQty     float64
	Status          string
	Type            string
	TimeInForce     string
	UpdateTime      int64
}

// PositionState 仓位状态
type PositionState struct {
	Symbol        string
	PositionAmt   float64
	EntryPrice    float64
	UnrealizedPnL float64
	MarginType    string
	Leverage      int
}

// StateConsistencyConfig 状态一致性检查配置
type StateConsistencyConfig struct {
	CheckInterval         time.Duration // 检查间隔
	MaxDiffAge            time.Duration // 最大差异保留时间
	AutoFixEnabled        bool          // 自动修复
	PositionTolerance     float64       // 仓位容差
	QuantityTolerance     float64       // 数量容差（百分比）
	PriceTolerance        float64       // 价格容差（基点）
	MaxConcurrentChecks   int           // 最大并发检查数
}

// DefaultStateConsistencyConfig 返回默认配置
func DefaultStateConsistencyConfig() *StateConsistencyConfig {
	return &StateConsistencyConfig{
		CheckInterval:       5 * time.Second,
		MaxDiffAge:          1 * time.Hour,
		AutoFixEnabled:      false, // 默认关闭自动修复
		PositionTolerance:   0.001, // 0.1%
		QuantityTolerance:   0.01,  // 1%
		PriceTolerance:      10.0,  // 10 bps
		MaxConcurrentChecks: 10,
	}
}

// StateConsistencyChecker 状态一致性检查器
type StateConsistencyChecker struct {
	config *StateConsistencyConfig

	// 本地状态存储
	localOrders  map[string]*LocalOrderState
	localPos     map[string]*PositionState
	localMu      sync.RWMutex

	// 交易所状态存储
	exchangeOrders map[string]*ExchangeOrderState
	exchangePos    map[string]*PositionState
	exchangeMu     sync.RWMutex

	// 差异记录
	diffs    []StateDiff
	diffsMu  sync.RWMutex

	// 统计
	checkCount    uint64
	diffCount     uint64
	autoFixCount  uint64

	// 回调
	onDiff        func(diff StateDiff)
	onCritical    func(diff StateDiff)

	// Prometheus 指标
	diffCounter       *prometheus.CounterVec
	consistencyGauge  prometheus.Gauge
	checkLatencyHist  prometheus.Histogram
	orphanOrderGauge  prometheus.Gauge

	// 控制
	stopChan chan struct{}
	wg       sync.WaitGroup
}

// NewStateConsistencyChecker 创建状态一致性检查器
func NewStateConsistencyChecker(config *StateConsistencyConfig, registry *prometheus.Registry) *StateConsistencyChecker {
	if config == nil {
		config = DefaultStateConsistencyConfig()
	}

	sc := &StateConsistencyChecker{
		config:         config,
		localOrders:    make(map[string]*LocalOrderState),
		localPos:       make(map[string]*PositionState),
		exchangeOrders: make(map[string]*ExchangeOrderState),
		exchangePos:    make(map[string]*PositionState),
		diffs:          make([]StateDiff, 0),
		stopChan:       make(chan struct{}),
	}

	// 初始化 Prometheus 指标
	if registry != nil {
		sc.diffCounter = promauto.With(registry).NewCounterVec(
			prometheus.CounterOpts{
				Namespace: "hft",
				Subsystem: "verification",
				Name:      "state_diff_total",
				Help:      "Total number of state inconsistencies detected",
			},
			[]string{"type", "severity"},
		)

		sc.consistencyGauge = promauto.With(registry).NewGauge(
			prometheus.GaugeOpts{
				Namespace: "hft",
				Subsystem: "verification",
				Name:      "state_consistency_ratio",
				Help:      "Ratio of consistent orders (1.0 = fully consistent)",
			},
		)

		sc.checkLatencyHist = promauto.With(registry).NewHistogram(
			prometheus.HistogramOpts{
				Namespace: "hft",
				Subsystem: "verification",
				Name:      "state_check_latency_ms",
				Help:      "State consistency check latency in milliseconds",
				Buckets:   []float64{1, 5, 10, 25, 50, 100, 250, 500},
			},
		)

		sc.orphanOrderGauge = promauto.With(registry).NewGauge(
			prometheus.GaugeOpts{
				Namespace: "hft",
				Subsystem: "verification",
				Name:      "orphan_orders",
				Help:      "Number of orphan orders (local only, not on exchange)",
			},
		)
	}

	return sc
}

// Start 启动检查器
func (sc *StateConsistencyChecker) Start() {
	sc.wg.Add(2)
	go sc.checkLoop()
	go sc.cleanupLoop()
}

// Stop 停止检查器
func (sc *StateConsistencyChecker) Stop() {
	close(sc.stopChan)
	sc.wg.Wait()
}

// checkLoop 定期检查循环
func (sc *StateConsistencyChecker) checkLoop() {
	defer sc.wg.Done()
	ticker := time.NewTicker(sc.config.CheckInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			sc.performCheck()
		case <-sc.stopChan:
			return
		}
	}
}

// cleanupLoop 清理循环
func (sc *StateConsistencyChecker) cleanupLoop() {
	defer sc.wg.Done()
	ticker := time.NewTicker(sc.config.MaxDiffAge / 10)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			sc.cleanup()
		case <-sc.stopChan:
			return
		}
	}
}

// cleanup 清理过期差异
func (sc *StateConsistencyChecker) cleanup() {
	cutoff := time.Now().Add(-sc.config.MaxDiffAge)

	sc.diffsMu.Lock()
	newDiffs := make([]StateDiff, 0)
	for _, diff := range sc.diffs {
		if diff.DetectedAt.After(cutoff) {
			newDiffs = append(newDiffs, diff)
		}
	}
	sc.diffs = newDiffs
	sc.diffsMu.Unlock()
}

// UpdateLocalOrder 更新本地订单状态
func (sc *StateConsistencyChecker) UpdateLocalOrder(order *LocalOrderState) {
	sc.localMu.Lock()
	defer sc.localMu.Unlock()

	order.UpdatedAt = time.Now()
	sc.localOrders[order.OrderID] = order
}

// UpdateLocalPosition 更新本地仓位
func (sc *StateConsistencyChecker) UpdateLocalPosition(pos *PositionState) {
	sc.localMu.Lock()
	defer sc.localMu.Unlock()

	sc.localPos[pos.Symbol] = pos
}

// UpdateExchangeOrder 更新交易所订单状态
func (sc *StateConsistencyChecker) UpdateExchangeOrder(order *ExchangeOrderState) {
	sc.exchangeMu.Lock()
	defer sc.exchangeMu.Unlock()

	sc.exchangeOrders[order.OrderID] = order
}

// UpdateExchangePosition 更新交易所仓位
func (sc *StateConsistencyChecker) UpdateExchangePosition(pos *PositionState) {
	sc.exchangeMu.Lock()
	defer sc.exchangeMu.Unlock()

	sc.exchangePos[pos.Symbol] = pos
}

// performCheck 执行一致性检查
func (sc *StateConsistencyChecker) performCheck() {
	start := time.Now()

	sc.localMu.RLock()
	localOrders := make(map[string]*LocalOrderState)
	for k, v := range sc.localOrders {
		localOrders[k] = v
	}
	sc.localMu.RUnlock()

	sc.exchangeMu.RLock()
	exchangeOrders := make(map[string]*ExchangeOrderState)
	for k, v := range sc.exchangeOrders {
		exchangeOrders[k] = v
	}
	sc.exchangeMu.RUnlock()

	// 检查订单一致性
	newDiffs := sc.checkOrderConsistency(localOrders, exchangeOrders)

	// 检查仓位一致性
	positionDiffs := sc.checkPositionConsistency()
	newDiffs = append(newDiffs, positionDiffs...)

	// 记录差异
	if len(newDiffs) > 0 {
		sc.diffsMu.Lock()
		sc.diffs = append(sc.diffs, newDiffs...)
		sc.diffsMu.Unlock()

		// 更新统计
		sc.diffCount += uint64(len(newDiffs))

		// 记录指标
		for _, diff := range newDiffs {
			if sc.diffCounter != nil {
				sc.diffCounter.WithLabelValues(diff.DiffType.String(), diff.Severity.String()).Inc()
			}

			// 触发回调
			if sc.onDiff != nil {
				sc.onDiff(diff)
			}
			if diff.Severity == SeverityCritical && sc.onCritical != nil {
				sc.onCritical(diff)
			}
		}
	}

	// 计算一致性比率
	consistentCount := len(localOrders) - len(newDiffs)
	consistencyRatio := 1.0
	if len(localOrders) > 0 {
		consistencyRatio = float64(consistentCount) / float64(len(localOrders))
	}
	if sc.consistencyGauge != nil {
		sc.consistencyGauge.Set(consistencyRatio)
	}

	// 记录检查延迟
	latency := time.Since(start)
	if sc.checkLatencyHist != nil {
		sc.checkLatencyHist.Observe(float64(latency.Milliseconds()))
	}

	// 更新检查计数
	sc.checkCount++
}

// checkOrderConsistency 检查订单一致性
func (sc *StateConsistencyChecker) checkOrderConsistency(local map[string]*LocalOrderState, exchange map[string]*ExchangeOrderState) []StateDiff {
	diffs := make([]StateDiff, 0)

	// 检查本地订单是否在交易所存在
	for orderID, localOrder := range local {
		exchangeOrder, exists := exchange[orderID]
		if !exists {
			// 检查是否为最近创建的订单（5秒内）
			if time.Since(localOrder.CreatedAt) > 5*time.Second {
				diffs = append(diffs, StateDiff{
					OrderID:         orderID,
					DiffType:        DiffTypeMissingExchange,
					Severity:        SeverityHigh,
					DetectedAt:      time.Now(),
					SuggestedAction: "Verify order submission or cancel local state",
				})
			}
			continue
		}

		// 检查状态一致性
		if !sc.isStatusConsistent(localOrder.Status, exchangeOrder.Status) {
			diffs = append(diffs, StateDiff{
				OrderID:       orderID,
				Field:         "status",
				LocalValue:    localOrder.Status,
				ExchangeValue: exchangeOrder.Status,
				DiffType:      DiffTypeStatus,
				Severity:      sc.getStatusSeverity(localOrder.Status, exchangeOrder.Status),
				DetectedAt:    time.Now(),
				SuggestedAction: fmt.Sprintf("Update local status from %s to %s", localOrder.Status, exchangeOrder.Status),
			})
		}

		// 检查数量一致性
		if localOrder.FilledQuantity > 0 && exchangeOrder.ExecutedQty > 0 {
			quantityDiff := math.Abs(localOrder.FilledQuantity - exchangeOrder.ExecutedQty)
			quantityDiffPct := quantityDiff / localOrder.Quantity
			if quantityDiffPct > sc.config.QuantityTolerance {
				diffs = append(diffs, StateDiff{
					OrderID:       orderID,
					Field:         "filled_quantity",
					LocalValue:    localOrder.FilledQuantity,
					ExchangeValue: exchangeOrder.ExecutedQty,
					DiffType:      DiffTypeQuantity,
					Severity:      SeverityHigh,
					DetectedAt:    time.Now(),
					SuggestedAction: "Reconcile fill quantities",
				})
			}
		}

		// 检查价格一致性
		if localOrder.Price > 0 && exchangeOrder.Price > 0 {
			priceDiffBps := math.Abs(localOrder.Price-exchangeOrder.Price) / localOrder.Price * 10000
			if priceDiffBps > sc.config.PriceTolerance {
				diffs = append(diffs, StateDiff{
					OrderID:       orderID,
					Field:         "price",
					LocalValue:    localOrder.Price,
					ExchangeValue: exchangeOrder.Price,
					DiffType:      DiffTypePrice,
					Severity:      SeverityMedium,
					DetectedAt:    time.Now(),
					SuggestedAction: "Verify price update",
				})
			}
		}
	}

	// 检查交易所订单是否在本地存在（孤儿订单）
	orphanCount := 0
	for orderID, exchangeOrder := range exchange {
		if _, exists := local[orderID]; !exists {
			orphanCount++
			diffs = append(diffs, StateDiff{
				OrderID:         orderID,
				Field:           "order",
				ExchangeValue:   exchangeOrder.Status,
				DiffType:        DiffTypeOrphan,
				Severity:        SeverityMedium,
				DetectedAt:      time.Now(),
				SuggestedAction: "Import order from exchange or cancel",
			})
		}
	}

	if sc.orphanOrderGauge != nil {
		sc.orphanOrderGauge.Set(float64(orphanCount))
	}

	return diffs
}

// checkPositionConsistency 检查仓位一致性
func (sc *StateConsistencyChecker) checkPositionConsistency() []StateDiff {
	diffs := make([]StateDiff, 0)

	sc.localMu.RLock()
	localPos := make(map[string]*PositionState)
	for k, v := range sc.localPos {
		localPos[k] = v
	}
	sc.localMu.RUnlock()

	sc.exchangeMu.RLock()
	exchangePos := make(map[string]*PositionState)
	for k, v := range sc.exchangePos {
		exchangePos[k] = v
	}
	sc.exchangeMu.RUnlock()

	// 检查仓位一致性
	for symbol, local := range localPos {
		exchange, exists := exchangePos[symbol]
		if !exists {
			if math.Abs(local.PositionAmt) > 0.0001 {
				diffs = append(diffs, StateDiff{
					OrderID:         symbol,
					Field:           "position",
					LocalValue:      local.PositionAmt,
					DiffType:        DiffTypeMissingExchange,
					Severity:        SeverityCritical,
					DetectedAt:      time.Now(),
					SuggestedAction: "Sync position from exchange",
				})
			}
			continue
		}

		// 检查仓位数量
		positionDiff := math.Abs(local.PositionAmt - exchange.PositionAmt)
		if positionDiff > sc.config.PositionTolerance {
			severity := SeverityHigh
			if positionDiff > 0.01 {
				severity = SeverityCritical
			}
			diffs = append(diffs, StateDiff{
				OrderID:         symbol,
				Field:           "position_amount",
				LocalValue:      local.PositionAmt,
				ExchangeValue:   exchange.PositionAmt,
				DiffType:        DiffTypeQuantity,
				Severity:        severity,
				DetectedAt:      time.Now(),
				SuggestedAction: "Reconcile position immediately",
			})
		}
	}

	return diffs
}

// isStatusConsistent 检查状态是否一致
func (sc *StateConsistencyChecker) isStatusConsistent(local, exchange string) bool {
	// 标准化状态
	local = normalizeStatus(local)
	exchange = normalizeStatus(exchange)

	// 完全匹配
	if local == exchange {
		return true
	}

	// 允许的状态转换
	// 本地 PENDING -> 交易所 NEW
	if local == "pending" && exchange == "new" {
		return true
	}

	// 本地 OPEN -> 交易所 PARTIALLY_FILLED
	if local == "open" && exchange == "partially_filled" {
		return true
	}

	return false
}

// normalizeStatus 标准化状态字符串
func normalizeStatus(status string) string {
	switch status {
	case "PENDING", "pending":
		return "pending"
	case "NEW", "new", "OPEN", "open":
		return "new"
	case "PARTIALLY_FILLED", "partially_filled", "PARTIAL":
		return "partially_filled"
	case "FILLED", "filled":
		return "filled"
	case "CANCELED", "canceled", "CANCELLED":
		return "canceled"
	case "REJECTED", "rejected":
		return "rejected"
	case "EXPIRED", "expired":
		return "expired"
	default:
		return status
	}
}

// getStatusSeverity 获取状态差异的严重程度
func (sc *StateConsistencyChecker) getStatusSeverity(local, exchange string) Severity {
	local = normalizeStatus(local)
	exchange = normalizeStatus(exchange)

	// 本地认为已成交，但交易所未成交
	if local == "filled" && exchange != "filled" {
		return SeverityCritical
	}

	// 本地认为已取消，但交易所仍活跃
	if local == "canceled" && (exchange == "new" || exchange == "partially_filled") {
		return SeverityHigh
	}

	return SeverityMedium
}

// GetDiffs 获取所有差异
func (sc *StateConsistencyChecker) GetDiffs() []StateDiff {
	sc.diffsMu.RLock()
	defer sc.diffsMu.RUnlock()

	result := make([]StateDiff, len(sc.diffs))
	copy(result, sc.diffs)
	return result
}

// GetDiffsBySeverity 按严重程度获取差异
func (sc *StateConsistencyChecker) GetDiffsBySeverity(severity Severity) []StateDiff {
	sc.diffsMu.RLock()
	defer sc.diffsMu.RUnlock()

	result := make([]StateDiff, 0)
	for _, diff := range sc.diffs {
		if diff.Severity == severity {
			result = append(result, diff)
		}
	}
	return result
}

// GetStats 获取统计信息
func (sc *StateConsistencyChecker) GetStats() map[string]interface{} {
	sc.localMu.RLock()
	localOrderCount := len(sc.localOrders)
	localPosCount := len(sc.localPos)
	sc.localMu.RUnlock()

	sc.exchangeMu.RLock()
	exchangeOrderCount := len(sc.exchangeOrders)
	exchangePosCount := len(sc.exchangePos)
	sc.exchangeMu.RUnlock()

	sc.diffsMu.RLock()
	diffCount := len(sc.diffs)
	sc.diffsMu.RUnlock()

	// 按严重程度统计
	severityCounts := make(map[string]int)
	for _, diff := range sc.diffs {
		severityCounts[diff.Severity.String()]++
	}

	return map[string]interface{}{
		"local_orders":      localOrderCount,
		"exchange_orders":   exchangeOrderCount,
		"local_positions":   localPosCount,
		"exchange_positions": exchangePosCount,
		"total_diffs":       diffCount,
		"severity_counts":   severityCounts,
		"check_count":       sc.checkCount,
		"auto_fix_count":    sc.autoFixCount,
	}
}

// SetDiffCallback 设置差异检测回调
func (sc *StateConsistencyChecker) SetDiffCallback(cb func(diff StateDiff)) {
	sc.onDiff = cb
}

// SetCriticalCallback 设置严重差异回调
func (sc *StateConsistencyChecker) SetCriticalCallback(cb func(diff StateDiff)) {
	sc.onCritical = cb
}

// ClearDiffs 清除所有差异记录
func (sc *StateConsistencyChecker) ClearDiffs() {
	sc.diffsMu.Lock()
	sc.diffs = make([]StateDiff, 0)
	sc.diffsMu.Unlock()
}

// TriggerManualCheck 触发手动检查
func (sc *StateConsistencyChecker) TriggerManualCheck(ctx context.Context) error {
	done := make(chan struct{})
	go func() {
		sc.performCheck()
		close(done)
	}()

	select {
	case <-done:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}
