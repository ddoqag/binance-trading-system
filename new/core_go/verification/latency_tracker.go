package verification

import (
	"context"
	"fmt"
	"math"
	"sync"
	"sync/atomic"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

/*
latency_tracker.go - 延迟测量与归因

测量端到端延迟并定位瓶颈，精度要求 < 1ms。
核心功能：
1. 多阶段延迟测量（下单→确认→成交）
2. 延迟归因分析（网络、交易所、内部处理）
3. 异常延迟检测（>100ms）
4. 延迟分布统计
*/

// LatencyStage 延迟阶段
type LatencyStage int

const (
	StageDecision LatencyStage = iota    // AI决策
	StageSerialization                   // 序列化
	StageSHMWrite                        // 共享内存写入
	StageNetworkSend                     // 网络发送
	StageExchangeProcess                 // 交易所处理
	StageNetworkRecv                     // 网络接收
	StageSHMRead                         // 共享内存读取
	StageDeserialization                 // 反序列化
	StageExecution                       // 执行
)

func (s LatencyStage) String() string {
	switch s {
	case StageDecision:
		return "decision"
	case StageSerialization:
		return "serialization"
	case StageSHMWrite:
		return "shm_write"
	case StageNetworkSend:
		return "network_send"
	case StageExchangeProcess:
		return "exchange_process"
	case StageNetworkRecv:
		return "network_recv"
	case StageSHMRead:
		return "shm_read"
	case StageDeserialization:
		return "deserialization"
	case StageExecution:
		return "execution"
	default:
		return "unknown"
	}
}

// LatencyMeasurement 延迟测量记录
type LatencyMeasurement struct {
	TraceID      string
	StartTime    time.Time
	EndTime      time.Time
	Stages       map[LatencyStage]time.Duration
	TotalLatency time.Duration
	Metadata     map[string]string
}

// LatencyBreakdown 延迟分解
type LatencyBreakdown struct {
	TraceID           string
	InternalLatency   time.Duration // 内部处理延迟
	NetworkLatency    time.Duration // 网络往返延迟
	ExchangeLatency   time.Duration // 交易所处理延迟
	TotalLatency      time.Duration
	BottleneckStage   LatencyStage
	BottleneckPercent float64
	Stages            map[LatencyStage]time.Duration // 各阶段详细延迟
}

// LatencyThreshold 延迟阈值配置
type LatencyThreshold struct {
	WarningThreshold  time.Duration // 警告阈值
	CriticalThreshold time.Duration // 严重阈值
	AnomalyThreshold  time.Duration // 异常阈值（100ms）
}

// LatencyTrackerConfig 延迟追踪器配置
type LatencyTrackerConfig struct {
	MaxMeasurements   int
	RetentionPeriod   time.Duration
	WarningThreshold  time.Duration
	CriticalThreshold time.Duration
	AnomalyThreshold  time.Duration // 默认 100ms
	EnableHistogram   bool
}

// DefaultLatencyTrackerConfig 返回默认配置
func DefaultLatencyTrackerConfig() *LatencyTrackerConfig {
	return &LatencyTrackerConfig{
		MaxMeasurements:   10000,
		RetentionPeriod:   1 * time.Hour,
		WarningThreshold:  10 * time.Millisecond,
		CriticalThreshold: 50 * time.Millisecond,
		AnomalyThreshold:  100 * time.Millisecond, // 异常检测阈值
		EnableHistogram:   true,
	}
}

// LatencyTracker 延迟追踪器
type LatencyTracker struct {
	config *LatencyTrackerConfig

	// 活跃测量（进行中）
	activeMeasurements map[string]*LatencyMeasurement
	activeMu           sync.RWMutex

	// 完成测量
	completedMeasurements []*LatencyMeasurement
	completedMu           sync.RWMutex

	// 统计
	totalMeasurements uint64
	anomalyCount      uint64

	// 异常检测回调
	onAnomaly func(measurement *LatencyMeasurement, breakdown *LatencyBreakdown)

	// Prometheus 指标
	stageLatencyHist  *prometheus.HistogramVec
	totalLatencyHist  prometheus.Histogram
	anomalyCounter    prometheus.Counter
	bottleneckGauge   *prometheus.GaugeVec

	// 控制
	stopChan chan struct{}
	wg       sync.WaitGroup
}

// NewLatencyTracker 创建延迟追踪器
func NewLatencyTracker(config *LatencyTrackerConfig, registry *prometheus.Registry) *LatencyTracker {
	if config == nil {
		config = DefaultLatencyTrackerConfig()
	}

	lt := &LatencyTracker{
		config:                config,
		activeMeasurements:    make(map[string]*LatencyMeasurement),
		completedMeasurements: make([]*LatencyMeasurement, 0, config.MaxMeasurements),
		stopChan:              make(chan struct{}),
	}

	// 初始化 Prometheus 指标
	if registry != nil {
		lt.stageLatencyHist = promauto.With(registry).NewHistogramVec(
			prometheus.HistogramOpts{
				Namespace: "hft",
				Subsystem: "verification",
				Name:      "stage_latency_ms",
				Help:      "Latency by stage in milliseconds",
				Buckets:   []float64{0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 25, 50, 100},
			},
			[]string{"stage"},
		)

		lt.totalLatencyHist = promauto.With(registry).NewHistogram(
			prometheus.HistogramOpts{
				Namespace: "hft",
				Subsystem: "verification",
				Name:      "total_latency_ms",
				Help:      "Total end-to-end latency in milliseconds",
				Buckets:   []float64{0.1, 0.5, 1, 2, 5, 10, 25, 50, 100, 250, 500},
			},
		)

		lt.anomalyCounter = promauto.With(registry).NewCounter(
			prometheus.CounterOpts{
				Namespace: "hft",
				Subsystem: "verification",
				Name:      "latency_anomaly_total",
				Help:      "Total number of latency anomalies detected",
			},
		)

		lt.bottleneckGauge = promauto.With(registry).NewGaugeVec(
			prometheus.GaugeOpts{
				Namespace: "hft",
				Subsystem: "verification",
				Name:      "bottleneck_stage_percent",
				Help:      "Percentage of time spent in bottleneck stage",
			},
			[]string{"stage"},
		)
	}

	return lt
}

// Start 启动延迟追踪器
func (lt *LatencyTracker) Start() {
	lt.wg.Add(1)
	go lt.cleanupLoop()
}

// Stop 停止延迟追踪器
func (lt *LatencyTracker) Stop() {
	close(lt.stopChan)
	lt.wg.Wait()
}

// cleanupLoop 定期清理过期记录
func (lt *LatencyTracker) cleanupLoop() {
	defer lt.wg.Done()
	ticker := time.NewTicker(lt.config.RetentionPeriod / 10)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			lt.cleanup()
		case <-lt.stopChan:
			return
		}
	}
}

// cleanup 清理过期记录
func (lt *LatencyTracker) cleanup() {
	cutoff := time.Now().Add(-lt.config.RetentionPeriod)

	lt.completedMu.Lock()
	newMeasurements := make([]*LatencyMeasurement, 0, len(lt.completedMeasurements))
	for _, m := range lt.completedMeasurements {
		if m.EndTime.After(cutoff) {
			newMeasurements = append(newMeasurements, m)
		}
	}
	lt.completedMeasurements = newMeasurements
	lt.completedMu.Unlock()
}

// StartMeasurement 开始新的延迟测量
func (lt *LatencyTracker) StartMeasurement(traceID string, metadata map[string]string) *LatencyMeasurement {
	m := &LatencyMeasurement{
		TraceID:   traceID,
		StartTime: time.Now(),
		Stages:    make(map[LatencyStage]time.Duration),
		Metadata:  metadata,
	}

	lt.activeMu.Lock()
	lt.activeMeasurements[traceID] = m
	lt.activeMu.Unlock()

	return m
}

// RecordStage 记录阶段延迟
func (lt *LatencyTracker) RecordStage(traceID string, stage LatencyStage, duration time.Duration) {
	lt.activeMu.Lock()
	defer lt.activeMu.Unlock()

	if m, ok := lt.activeMeasurements[traceID]; ok {
		m.Stages[stage] = duration

		// 实时记录指标
		if lt.stageLatencyHist != nil {
			lt.stageLatencyHist.WithLabelValues(stage.String()).Observe(float64(duration.Milliseconds()))
		}
	}
}

// RecordStageEnd 记录阶段结束（自动计算持续时间）
func (lt *LatencyTracker) RecordStageEnd(traceID string, stage LatencyStage, startTime time.Time) {
	duration := time.Since(startTime)
	lt.RecordStage(traceID, stage, duration)
}

// EndMeasurement 结束延迟测量
func (lt *LatencyTracker) EndMeasurement(traceID string) (*LatencyMeasurement, error) {
	lt.activeMu.Lock()
	m, ok := lt.activeMeasurements[traceID]
	if !ok {
		lt.activeMu.Unlock()
		return nil, fmt.Errorf("measurement not found: %s", traceID)
	}
	delete(lt.activeMeasurements, traceID)
	lt.activeMu.Unlock()

	m.EndTime = time.Now()
	m.TotalLatency = m.EndTime.Sub(m.StartTime)

	// 记录总延迟
	if lt.totalLatencyHist != nil {
		lt.totalLatencyHist.Observe(float64(m.TotalLatency.Milliseconds()))
	}

	// 保存完成测量
	lt.completedMu.Lock()
	lt.completedMeasurements = append(lt.completedMeasurements, m)
	// 限制数量
	if len(lt.completedMeasurements) > lt.config.MaxMeasurements {
		lt.completedMeasurements = lt.completedMeasurements[len(lt.completedMeasurements)-lt.config.MaxMeasurements:]
	}
	lt.completedMu.Unlock()

	// 更新统计
	atomic.AddUint64(&lt.totalMeasurements, 1)

	// 异常检测
	if m.TotalLatency > lt.config.AnomalyThreshold {
		atomic.AddUint64(&lt.anomalyCount, 1)
		if lt.anomalyCounter != nil {
			lt.anomalyCounter.Inc()
		}

		breakdown := lt.AnalyzeBreakdown(m)
		if lt.onAnomaly != nil {
			lt.onAnomaly(m, breakdown)
		}
	}

	return m, nil
}

// AnalyzeBreakdown 分析延迟分解
func (lt *LatencyTracker) AnalyzeBreakdown(m *LatencyMeasurement) *LatencyBreakdown {
	breakdown := &LatencyBreakdown{
		TraceID:      m.TraceID,
		TotalLatency: m.TotalLatency,
	}

	// 计算各阶段延迟
	var internalDuration, networkDuration, exchangeDuration time.Duration

	for stage, duration := range m.Stages {
		switch stage {
		case StageDecision, StageSerialization, StageDeserialization, StageExecution:
			internalDuration += duration
		case StageNetworkSend, StageNetworkRecv:
			networkDuration += duration
		case StageExchangeProcess:
			exchangeDuration += duration
		}
	}

	breakdown.InternalLatency = internalDuration
	breakdown.NetworkLatency = networkDuration
	breakdown.ExchangeLatency = exchangeDuration

	// 找出瓶颈阶段
	var maxDuration time.Duration
	for stage, duration := range m.Stages {
		if duration > maxDuration {
			maxDuration = duration
			breakdown.BottleneckStage = stage
		}
	}

	if breakdown.TotalLatency > 0 {
		breakdown.BottleneckPercent = float64(maxDuration) / float64(breakdown.TotalLatency) * 100
	}

	// 记录瓶颈指标
	if lt.bottleneckGauge != nil {
		lt.bottleneckGauge.WithLabelValues(breakdown.BottleneckStage.String()).Set(breakdown.BottleneckPercent)
	}

	return breakdown
}

// GetMeasurement 获取测量记录
func (lt *LatencyTracker) GetMeasurement(traceID string) (*LatencyMeasurement, bool) {
	// 先检查活跃测量
	lt.activeMu.RLock()
	if m, ok := lt.activeMeasurements[traceID]; ok {
		lt.activeMu.RUnlock()
		result := *m
		return &result, true
	}
	lt.activeMu.RUnlock()

	// 再检查完成测量
	lt.completedMu.RLock()
	defer lt.completedMu.RUnlock()

	for _, m := range lt.completedMeasurements {
		if m.TraceID == traceID {
			result := *m
			return &result, true
		}
	}

	return nil, false
}

// GetStats 获取统计信息
func (lt *LatencyTracker) GetStats() map[string]interface{} {
	total := atomic.LoadUint64(&lt.totalMeasurements)
	anomalies := atomic.LoadUint64(&lt.anomalyCount)

	lt.completedMu.RLock()
	measurementCount := len(lt.completedMeasurements)
	lt.completedMu.RUnlock()

	// 计算延迟分布
	var totalLatency time.Duration
	var minLatency, maxLatency time.Duration
	stageStats := make(map[string][]time.Duration)

	lt.completedMu.RLock()
	for i, m := range lt.completedMeasurements {
		totalLatency += m.TotalLatency
		if i == 0 || m.TotalLatency < minLatency {
			minLatency = m.TotalLatency
		}
		if m.TotalLatency > maxLatency {
			maxLatency = m.TotalLatency
		}

		for stage, duration := range m.Stages {
			stageName := stage.String()
			stageStats[stageName] = append(stageStats[stageName], duration)
		}
	}
	lt.completedMu.RUnlock()

	avgLatency := time.Duration(0)
	if measurementCount > 0 {
		avgLatency = totalLatency / time.Duration(measurementCount)
	}

	// 计算各阶段统计
	stageAvg := make(map[string]time.Duration)
	for stage, durations := range stageStats {
		var sum time.Duration
		for _, d := range durations {
			sum += d
		}
		if len(durations) > 0 {
			stageAvg[stage] = sum / time.Duration(len(durations))
		}
	}

	return map[string]interface{}{
		"total_measurements":    total,
		"stored_measurements":   measurementCount,
		"anomaly_count":         anomalies,
		"anomaly_rate_percent":  float64(anomalies) / float64(total) * 100,
		"average_latency_ms":    float64(avgLatency.Microseconds()) / 1000.0,
		"min_latency_ms":        float64(minLatency.Microseconds()) / 1000.0,
		"max_latency_ms":        float64(maxLatency.Microseconds()) / 1000.0,
		"stage_averages_ms":     stageAvg,
	}
}

// GetAnomalies 获取异常记录
func (lt *LatencyTracker) GetAnomalies(limit int) []*LatencyMeasurement {
	lt.completedMu.RLock()
	defer lt.completedMu.RUnlock()

	anomalies := make([]*LatencyMeasurement, 0)
	for i := len(lt.completedMeasurements) - 1; i >= 0 && len(anomalies) < limit; i-- {
		m := lt.completedMeasurements[i]
		if m.TotalLatency > lt.config.AnomalyThreshold {
			result := *m
			anomalies = append(anomalies, &result)
		}
	}
	return anomalies
}

// SetAnomalyCallback 设置异常检测回调
func (lt *LatencyTracker) SetAnomalyCallback(cb func(measurement *LatencyMeasurement, breakdown *LatencyBreakdown)) {
	lt.onAnomaly = cb
}

// WaitForMeasurement 等待测量完成
func (lt *LatencyTracker) WaitForMeasurement(ctx context.Context, traceID string, timeout time.Duration) (*LatencyMeasurement, error) {
	deadline := time.Now().Add(timeout)

	for time.Now().Before(deadline) {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		default:
		}

		// 检查是否已完成
		lt.completedMu.RLock()
		for _, m := range lt.completedMeasurements {
			if m.TraceID == traceID {
				lt.completedMu.RUnlock()
				result := *m
				return &result, nil
			}
		}
		lt.completedMu.RUnlock()

		time.Sleep(1 * time.Millisecond)
	}

	return nil, fmt.Errorf("timeout waiting for measurement: %s", traceID)
}

// GetPercentiles 获取延迟百分位数
func (lt *LatencyTracker) GetPercentiles() map[string]float64 {
	lt.completedMu.RLock()
	defer lt.completedMu.RUnlock()

	if len(lt.completedMeasurements) == 0 {
		return map[string]float64{
			"p50": 0,
			"p90": 0,
			"p95": 0,
			"p99": 0,
		}
	}

	// 收集所有延迟
	latencies := make([]float64, len(lt.completedMeasurements))
	for i, m := range lt.completedMeasurements {
		latencies[i] = float64(m.TotalLatency.Microseconds()) / 1000.0 // 转换为毫秒
	}

	return map[string]float64{
		"p50": percentile(latencies, 0.50),
		"p90": percentile(latencies, 0.90),
		"p95": percentile(latencies, 0.95),
		"p99": percentile(latencies, 0.99),
	}
}

// percentile 计算百分位数
func percentile(sorted []float64, p float64) float64 {
	if len(sorted) == 0 {
		return 0
	}

	// 简单实现，实际应该用更高效的算法
	index := int(math.Ceil(float64(len(sorted)) * p))
	if index >= len(sorted) {
		index = len(sorted) - 1
	}
	return sorted[index]
}

// Reset 重置所有记录
func (lt *LatencyTracker) Reset() {
	lt.activeMu.Lock()
	lt.activeMeasurements = make(map[string]*LatencyMeasurement)
	lt.activeMu.Unlock()

	lt.completedMu.Lock()
	lt.completedMeasurements = make([]*LatencyMeasurement, 0, lt.config.MaxMeasurements)
	lt.completedMu.Unlock()

	atomic.StoreUint64(&lt.totalMeasurements, 0)
	atomic.StoreUint64(&lt.anomalyCount, 0)
}
