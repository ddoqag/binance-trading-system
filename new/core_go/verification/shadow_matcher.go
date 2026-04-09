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
shadow_matcher.go - 订单影子匹配验证器

对比订单簿状态和实际成交，验证执行层的真实性。
核心功能：
1. 记录预期订单状态（基于本地订单簿）
2. 对比实际成交结果
3. 检测异常成交（价格、数量、时间不匹配）
4. 计算成交质量分数
*/

// OrderState 预期订单状态
type OrderState struct {
	OrderID           string
	Symbol            string
	Side              string
	Price             float64
	Quantity          float64
	ExpectedFillPrice float64
	ExpectedFillTime  time.Time
	QueuePosition     float64 // 队列位置 [0, 1]
	SubmitTime        time.Time
	Status            string // pending, open, filled, cancelled
}

// FillRecord 实际成交记录
type FillRecord struct {
	OrderID      string
	Symbol       string
	Side         string
	Price        float64
	Quantity     float64
	FillTime     time.Time
	Commission   float64
	IsMaker      bool
	LatencyMs    float64
}

// FillQuality 成交质量分析
type FillQuality struct {
	OrderID           string
	PriceDeviation    float64 // 实际成交价格 - 预期价格
	TimeDeviationMs   float64 // 成交时间偏差
	SlippageBPS       float64 // 滑点（基点）
	FillRate          float64 // 成交率
	QualityScore      float64 // 综合质量分数 [0, 1]
	AnomalyDetected   bool
	AnomalyReason     string
}

// ShadowMatcherConfig 影子匹配器配置
type ShadowMatcherConfig struct {
	MaxPriceDeviationBPS float64       // 最大价格偏差（基点）
	MaxTimeDeviationMs   float64       // 最大时间偏差
	MinQualityScore      float64       // 最小质量分数
	CheckInterval        time.Duration // 检查间隔
	RetentionPeriod      time.Duration // 记录保留时间
}

// DefaultShadowMatcherConfig 返回默认配置
func DefaultShadowMatcherConfig() *ShadowMatcherConfig {
	return &ShadowMatcherConfig{
		MaxPriceDeviationBPS: 10.0,        // 10bps
		MaxTimeDeviationMs:   1000.0,      // 1秒
		MinQualityScore:      0.7,         // 70分
		CheckInterval:        100 * time.Millisecond,
		RetentionPeriod:      1 * time.Hour,
	}
}

// ShadowMatcher 订单影子匹配验证器
type ShadowMatcher struct {
	config *ShadowMatcherConfig

	// 状态存储
	expectedOrders map[string]*OrderState
	actualFills    map[string]*FillRecord
	qualityResults map[string]*FillQuality

	// 保护锁
	ordersMu sync.RWMutex
	fillsMu  sync.RWMutex
	qualityMu sync.RWMutex

	// 异常检测回调
	onAnomaly func(orderID string, quality *FillQuality)

	// Prometheus 指标
	mismatchCount      prometheus.Counter
	qualityScoreHist   prometheus.Histogram
	slippageHist       prometheus.Histogram
	latencyDeviationHist prometheus.Histogram

	// 控制
	stopChan chan struct{}
	wg       sync.WaitGroup
}

// NewShadowMatcher 创建影子匹配器
func NewShadowMatcher(config *ShadowMatcherConfig, registry *prometheus.Registry) *ShadowMatcher {
	if config == nil {
		config = DefaultShadowMatcherConfig()
	}

	sm := &ShadowMatcher{
		config:         config,
		expectedOrders: make(map[string]*OrderState),
		actualFills:    make(map[string]*FillRecord),
		qualityResults: make(map[string]*FillQuality),
		stopChan:       make(chan struct{}),
	}

	// 初始化 Prometheus 指标
	if registry != nil {
		sm.mismatchCount = promauto.With(registry).NewCounter(
			prometheus.CounterOpts{
				Namespace: "hft",
				Subsystem: "verification",
				Name:      "shadow_mismatch_total",
				Help:      "Total number of shadow order mismatches",
			},
		)

		sm.qualityScoreHist = promauto.With(registry).NewHistogram(
			prometheus.HistogramOpts{
				Namespace: "hft",
				Subsystem: "verification",
				Name:      "fill_quality_score",
				Help:      "Fill quality score distribution",
				Buckets:   []float64{0.0, 0.2, 0.4, 0.6, 0.7, 0.8, 0.9, 1.0},
			},
		)

		sm.slippageHist = promauto.With(registry).NewHistogram(
			prometheus.HistogramOpts{
				Namespace: "hft",
				Subsystem: "verification",
				Name:      "fill_slippage_bps",
				Help:      "Fill slippage in basis points",
				Buckets:   []float64{-10, -5, -2, -1, 0, 1, 2, 5, 10},
			},
		)

		sm.latencyDeviationHist = promauto.With(registry).NewHistogram(
			prometheus.HistogramOpts{
				Namespace: "hft",
				Subsystem: "verification",
				Name:      "fill_latency_deviation_ms",
				Help:      "Fill latency deviation in milliseconds",
				Buckets:   []float64{0, 1, 5, 10, 25, 50, 100, 250, 500, 1000},
			},
		)
	}

	return sm
}

// Start 启动影子匹配器
func (sm *ShadowMatcher) Start() {
	sm.wg.Add(1)
	go sm.cleanupLoop()
}

// Stop 停止影子匹配器
func (sm *ShadowMatcher) Stop() {
	close(sm.stopChan)
	sm.wg.Wait()
}

// cleanupLoop 定期清理过期记录
func (sm *ShadowMatcher) cleanupLoop() {
	defer sm.wg.Done()
	ticker := time.NewTicker(sm.config.RetentionPeriod / 10)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			sm.cleanup()
		case <-sm.stopChan:
			return
		}
	}
}

// cleanup 清理过期记录
func (sm *ShadowMatcher) cleanup() {
	cutoff := time.Now().Add(-sm.config.RetentionPeriod)

	sm.ordersMu.Lock()
	for id, order := range sm.expectedOrders {
		if order.SubmitTime.Before(cutoff) {
			delete(sm.expectedOrders, id)
		}
	}
	sm.ordersMu.Unlock()

	sm.fillsMu.Lock()
	for id, fill := range sm.actualFills {
		if fill.FillTime.Before(cutoff) {
			delete(sm.actualFills, id)
		}
	}
	sm.fillsMu.Unlock()
}

// RecordExpectedOrder 记录预期订单
func (sm *ShadowMatcher) RecordExpectedOrder(order *OrderState) {
	sm.ordersMu.Lock()
	defer sm.ordersMu.Unlock()

	order.SubmitTime = time.Now()
	order.Status = "pending"
	sm.expectedOrders[order.OrderID] = order
}

// UpdateOrderStatus 更新订单状态
func (sm *ShadowMatcher) UpdateOrderStatus(orderID string, status string) {
	sm.ordersMu.Lock()
	defer sm.ordersMu.Unlock()

	if order, ok := sm.expectedOrders[orderID]; ok {
		order.Status = status
	}
}

// RecordActualFill 记录实际成交
func (sm *ShadowMatcher) RecordActualFill(fill *FillRecord) {
	sm.fillsMu.Lock()
	sm.actualFills[fill.OrderID] = fill
	sm.fillsMu.Unlock()

	// 立即进行质量分析
	quality := sm.analyzeFillQuality(fill)

	sm.qualityMu.Lock()
	sm.qualityResults[fill.OrderID] = quality
	sm.qualityMu.Unlock()

	// 记录指标
	if sm.qualityScoreHist != nil {
		sm.qualityScoreHist.Observe(quality.QualityScore)
	}
	if sm.slippageHist != nil {
		sm.slippageHist.Observe(quality.SlippageBPS)
	}
	if sm.latencyDeviationHist != nil {
		sm.latencyDeviationHist.Observe(quality.TimeDeviationMs)
	}

	// 异常检测
	if quality.AnomalyDetected {
		if sm.mismatchCount != nil {
			sm.mismatchCount.Inc()
		}
		if sm.onAnomaly != nil {
			sm.onAnomaly(fill.OrderID, quality)
		}
	}
}

// analyzeFillQuality 分析成交质量
func (sm *ShadowMatcher) analyzeFillQuality(fill *FillRecord) *FillQuality {
	sm.ordersMu.RLock()
	expected, exists := sm.expectedOrders[fill.OrderID]
	sm.ordersMu.RUnlock()

	if !exists {
		return &FillQuality{
			OrderID:         fill.OrderID,
			AnomalyDetected: true,
			AnomalyReason:   "Order not found in expected orders",
			QualityScore:    0,
		}
	}

	quality := &FillQuality{
		OrderID:         fill.OrderID,
		PriceDeviation:  fill.Price - expected.ExpectedFillPrice,
		TimeDeviationMs: float64(time.Since(expected.ExpectedFillTime).Milliseconds()),
	}

	// 计算滑点（基点）
	if expected.ExpectedFillPrice > 0 {
		quality.SlippageBPS = (fill.Price - expected.ExpectedFillPrice) / expected.ExpectedFillPrice * 10000
	}

	// 计算成交率
	if expected.Quantity > 0 {
		quality.FillRate = fill.Quantity / expected.Quantity
	}

	// 计算综合质量分数
	quality.QualityScore = sm.calculateQualityScore(quality, fill)

	// 异常检测
	quality.AnomalyDetected = sm.detectAnomaly(quality, fill, expected)
	if quality.AnomalyDetected {
		quality.AnomalyReason = sm.buildAnomalyReason(quality)
	}

	return quality
}

// calculateQualityScore 计算综合质量分数
func (sm *ShadowMatcher) calculateQualityScore(quality *FillQuality, fill *FillRecord) float64 {
	score := 1.0

	// 价格偏差惩罚
	priceDeviationAbs := math.Abs(quality.SlippageBPS)
	if priceDeviationAbs > sm.config.MaxPriceDeviationBPS {
		score -= 0.4
	} else if priceDeviationAbs > sm.config.MaxPriceDeviationBPS/2 {
		score -= 0.2
	} else if priceDeviationAbs > sm.config.MaxPriceDeviationBPS/4 {
		score -= 0.1
	}

	// 时间偏差惩罚
	if quality.TimeDeviationMs > sm.config.MaxTimeDeviationMs {
		score -= 0.3
	} else if quality.TimeDeviationMs > sm.config.MaxTimeDeviationMs/2 {
		score -= 0.15
	}

	// 成交率惩罚
	if quality.FillRate < 0.5 {
		score -= 0.2
	} else if quality.FillRate < 0.8 {
		score -= 0.1
	}

	// Maker 奖励
	if fill.IsMaker {
		score += 0.1
	}

	return math.Max(0, math.Min(1, score))
}

// detectAnomaly 检测异常
func (sm *ShadowMatcher) detectAnomaly(quality *FillQuality, fill *FillRecord, expected *OrderState) bool {
	// 价格异常
	if math.Abs(quality.SlippageBPS) > sm.config.MaxPriceDeviationBPS {
		return true
	}

	// 时间异常
	if quality.TimeDeviationMs > sm.config.MaxTimeDeviationMs {
		return true
	}

	// 质量分数异常
	if quality.QualityScore < sm.config.MinQualityScore {
		return true
	}

	// 方向异常（买单成交价高于卖一价，或卖单成交价低于买一价）
	// 这里简化处理，实际应该对比订单簿

	return false
}

// buildAnomalyReason 构建异常原因
func (sm *ShadowMatcher) buildAnomalyReason(quality *FillQuality) string {
	reasons := []string{}

	if math.Abs(quality.SlippageBPS) > sm.config.MaxPriceDeviationBPS {
		reasons = append(reasons, fmt.Sprintf("Price slippage too high: %.2f bps", quality.SlippageBPS))
	}

	if quality.TimeDeviationMs > sm.config.MaxTimeDeviationMs {
		reasons = append(reasons, fmt.Sprintf("Fill time too slow: %.2f ms", quality.TimeDeviationMs))
	}

	if quality.QualityScore < sm.config.MinQualityScore {
		reasons = append(reasons, fmt.Sprintf("Quality score too low: %.2f", quality.QualityScore))
	}

	if len(reasons) == 0 {
		return "Unknown anomaly"
	}

	result := reasons[0]
	for i := 1; i < len(reasons); i++ {
		result += "; " + reasons[i]
	}
	return result
}

// GetFillQuality 获取成交质量
func (sm *ShadowMatcher) GetFillQuality(orderID string) (*FillQuality, bool) {
	sm.qualityMu.RLock()
	defer sm.qualityMu.RUnlock()

	quality, ok := sm.qualityResults[orderID]
	if !ok {
		return nil, false
	}

	// 返回副本
	result := *quality
	return &result, true
}

// GetAllAnomalies 获取所有异常
func (sm *ShadowMatcher) GetAllAnomalies() []*FillQuality {
	sm.qualityMu.RLock()
	defer sm.qualityMu.RUnlock()

	anomalies := make([]*FillQuality, 0)
	for _, quality := range sm.qualityResults {
		if quality.AnomalyDetected {
			// 返回副本
			q := *quality
			anomalies = append(anomalies, &q)
		}
	}
	return anomalies
}

// GetStats 获取统计信息
func (sm *ShadowMatcher) GetStats() map[string]interface{} {
	sm.ordersMu.RLock()
	orderCount := len(sm.expectedOrders)
	sm.ordersMu.RUnlock()

	sm.fillsMu.RLock()
	fillCount := len(sm.actualFills)
	sm.fillsMu.RUnlock()

	sm.qualityMu.RLock()
	anomalyCount := 0
	var totalQuality float64
	for _, q := range sm.qualityResults {
		if q.AnomalyDetected {
			anomalyCount++
		}
		totalQuality += q.QualityScore
	}
	qualityCount := len(sm.qualityResults)
	sm.qualityMu.RUnlock()

	avgQuality := 0.0
	if qualityCount > 0 {
		avgQuality = totalQuality / float64(qualityCount)
	}

	return map[string]interface{}{
		"expected_orders":   orderCount,
		"actual_fills":      fillCount,
		"quality_analyzed":  qualityCount,
		"anomalies":         anomalyCount,
		"anomaly_rate":      float64(anomalyCount) / float64(qualityCount) * 100,
		"average_quality":   avgQuality,
	}
}

// SetAnomalyCallback 设置异常检测回调
func (sm *ShadowMatcher) SetAnomalyCallback(cb func(orderID string, quality *FillQuality)) {
	sm.onAnomaly = cb
}

// VerifyOrderFill 验证订单成交（同步接口）
func (sm *ShadowMatcher) VerifyOrderFill(ctx context.Context, orderID string, timeout time.Duration) (*FillQuality, error) {
	deadline := time.Now().Add(timeout)

	for time.Now().Before(deadline) {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		default:
		}

		// 检查是否已有成交记录
		sm.fillsMu.RLock()
		fill, hasFill := sm.actualFills[orderID]
		sm.fillsMu.RUnlock()

		if hasFill {
			sm.qualityMu.RLock()
			quality, hasQuality := sm.qualityResults[orderID]
			sm.qualityMu.RUnlock()

			if hasQuality {
				result := *quality
				return &result, nil
			}

			// 如果没有质量分析，现场计算
			return sm.analyzeFillQuality(fill), nil
		}

		time.Sleep(10 * time.Millisecond)
	}

	return nil, fmt.Errorf("timeout waiting for fill: %s", orderID)
}
