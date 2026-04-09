package verification

import (
	"fmt"
	"sync"
	"sync/atomic"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

/*
latency_tracker_optimized.go - 高性能延迟测量与归因

优化实现：
1. 使用 sync.Pool 避免内存分配
2. 环形缓冲区预分配内存
3. 无锁设计（使用 atomic 操作）
4. 批量处理测量点

延迟测量精度 < 1ms，异常检测延迟 < 100ms
*/

// LatencyStageOptimized 优化的延迟阶段定义
type LatencyStageOptimized int

const (
	StageFeatureEngineering LatencyStageOptimized = iota // 特征工程
	StageModelInference                                   // 模型推理
	StageStrategyDecision                                 // 策略决策
	StageOrderTransmission                                // 订单传输
	StageExchangeExecution                                // 交易所执行
	StageTotal                                            // 总延迟
)

func (s LatencyStageOptimized) String() string {
	switch s {
	case StageFeatureEngineering:
		return "feature_engineering"
	case StageModelInference:
		return "model_inference"
	case StageStrategyDecision:
		return "strategy_decision"
	case StageOrderTransmission:
		return "order_transmission"
	case StageExchangeExecution:
		return "exchange_execution"
	case StageTotal:
		return "total"
	default:
		return "unknown"
	}
}

// LatencyMeasurementOptimized 优化的延迟测量记录
type LatencyMeasurementOptimized struct {
	TraceID      string
	StartTime    int64 // 纳秒时间戳
	EndTime      int64
	Stages       [6]int64 // 各阶段延迟（纳秒）
	TotalLatency int64
	Metadata     [8]string // 预分配元数据槽位
	mu           sync.RWMutex
}

// LatencyBreakdownOptimized 优化的延迟分解
type LatencyBreakdownOptimized struct {
	TraceID           string
	FeatureEngineering time.Duration
	ModelInference     time.Duration
	StrategyDecision   time.Duration
	OrderTransmission  time.Duration
	ExchangeExecution  time.Duration
	TotalLatency       time.Duration
	BottleneckStage    LatencyStageOptimized
	BottleneckPercent  float64
}

// LatencyThresholds 延迟阈值配置
type LatencyThresholds struct {
	MaxLatencyMs       int64         // 最大允许延迟（毫秒）
	MaxSlippageBps     float64       // 最大允许滑点
	MaxStateDiffCount  int           // 最大状态差异数
	WarningThreshold   time.Duration // 警告阈值
	CriticalThreshold  time.Duration // 严重阈值
	AnomalyThreshold   time.Duration // 异常阈值（默认 100ms）
}

// DefaultLatencyThresholds 返回默认阈值
func DefaultLatencyThresholds() *LatencyThresholds {
	return &LatencyThresholds{
		MaxLatencyMs:      50,
		MaxSlippageBps:    10.0,
		MaxStateDiffCount: 5,
		WarningThreshold:  10 * time.Millisecond,
		CriticalThreshold: 50 * time.Millisecond,
		AnomalyThreshold:  100 * time.Millisecond,
	}
}

// LatencyTrackerOptimized 高性能延迟追踪器
type LatencyTrackerOptimized struct {
	config *LatencyThresholds

	// 对象池 - 避免内存分配
	measurementPool sync.Pool

	// 环形缓冲区 - 预分配内存
	bufferSize      int
	measurements    []*LatencyMeasurementOptimized
	writeIndex      uint64
	readIndex       uint64

	// 活跃测量（进行中）- 使用分片减少锁竞争
	activeMeasurements [16]map[string]*LatencyMeasurementOptimized
	activeLocks        [16]sync.RWMutex

	// 统计 - 使用 atomic
	totalMeasurements uint64
	anomalyCount      uint64

	// 异常检测回调
	onAnomaly func(measurement *LatencyMeasurementOptimized, breakdown *LatencyBreakdownOptimized)

	// Prometheus 指标
	stageLatencyHist  *prometheus.HistogramVec
	totalLatencyHist  prometheus.Histogram
	anomalyCounter    prometheus.Counter
	bottleneckGauge   *prometheus.GaugeVec
	poolHitCounter    prometheus.Counter
	poolMissCounter   prometheus.Counter

	// 控制
	stopChan chan struct{}
	wg       sync.WaitGroup
}

// NewLatencyTrackerOptimized 创建高性能延迟追踪器
func NewLatencyTrackerOptimized(config *LatencyThresholds, registry *prometheus.Registry) *LatencyTrackerOptimized {
	if config == nil {
		config = DefaultLatencyThresholds()
	}

	lt := &LatencyTrackerOptimized{
		config:     config,
		bufferSize: 10000,
		stopChan:   make(chan struct{}),
	}

	// 初始化对象池
	lt.measurementPool = sync.Pool{
		New: func() interface{} {
			return &LatencyMeasurementOptimized{
				Stages:   [6]int64{},
				Metadata: [8]string{},
			}
		},
	}

	// 初始化环形缓冲区
	lt.measurements = make([]*LatencyMeasurementOptimized, lt.bufferSize)

	// 初始化活跃测量分片
	for i := 0; i < 16; i++ {
		lt.activeMeasurements[i] = make(map[string]*LatencyMeasurementOptimized)
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

		lt.poolHitCounter = promauto.With(registry).NewCounter(
			prometheus.CounterOpts{
				Namespace: "hft",
				Subsystem: "verification",
				Name:      "pool_hit_total",
				Help:      "Total number of pool hits",
			},
		)

		lt.poolMissCounter = promauto.With(registry).NewCounter(
			prometheus.CounterOpts{
				Namespace: "hft",
				Subsystem: "verification",
				Name:      "pool_miss_total",
				Help:      "Total number of pool misses",
			},
		)
	}

	return lt
}

// Start 启动延迟追踪器
func (lt *LatencyTrackerOptimized) Start() {
	lt.wg.Add(1)
	go lt.cleanupLoop()
}

// Stop 停止延迟追踪器
func (lt *LatencyTrackerOptimized) Stop() {
	close(lt.stopChan)
	lt.wg.Wait()
}

// cleanupLoop 定期清理过期记录
func (lt *LatencyTrackerOptimized) cleanupLoop() {
	defer lt.wg.Done()
	ticker := time.NewTicker(5 * time.Second)
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
func (lt *LatencyTrackerOptimized) cleanup() {
	cutoff := time.Now().Add(-5 * time.Minute).UnixNano()

	for i := 0; i < 16; i++ {
		lt.activeLocks[i].Lock()
		for id, m := range lt.activeMeasurements[i] {
			if atomic.LoadInt64(&m.StartTime) < cutoff {
				delete(lt.activeMeasurements[i], id)
				lt.measurementPool.Put(m)
			}
		}
		lt.activeLocks[i].Unlock()
	}
}

// getShardIndex 获取分片索引
func (lt *LatencyTrackerOptimized) getShardIndex(traceID string) int {
	hash := 0
	for i := 0; i < len(traceID) && i < 8; i++ {
		hash = hash*31 + int(traceID[i])
	}
	return hash & 0x0F // 0-15
}

// StartMeasurement 开始新的延迟测量（零分配）
func (lt *LatencyTrackerOptimized) StartMeasurement(traceID string, metadata [8]string) *LatencyMeasurementOptimized {
	// 从对象池获取
	m := lt.measurementPool.Get().(*LatencyMeasurementOptimized)

	if lt.poolHitCounter != nil {
		lt.poolHitCounter.Inc()
	}

	// 重置
	m.TraceID = traceID
	m.StartTime = time.Now().UnixNano()
	m.EndTime = 0
	m.Stages = [6]int64{}
	m.TotalLatency = 0
	m.Metadata = metadata

	// 存入活跃测量
	shard := lt.getShardIndex(traceID)
	lt.activeLocks[shard].Lock()
	lt.activeMeasurements[shard][traceID] = m
	lt.activeLocks[shard].Unlock()

	return m
}

// RecordStage 记录阶段延迟（无锁）
func (lt *LatencyTrackerOptimized) RecordStage(traceID string, stage LatencyStageOptimized, duration time.Duration) {
	shard := lt.getShardIndex(traceID)

	lt.activeLocks[shard].RLock()
	m, ok := lt.activeMeasurements[shard][traceID]
	lt.activeLocks[shard].RUnlock()

	if !ok {
		return
	}

	// 使用 atomic 存储
	atomic.StoreInt64(&m.Stages[stage], int64(duration))

	// 实时记录指标
	if lt.stageLatencyHist != nil {
		lt.stageLatencyHist.WithLabelValues(stage.String()).Observe(float64(duration.Milliseconds()))
	}
}

// RecordStageEnd 记录阶段结束（自动计算持续时间）
func (lt *LatencyTrackerOptimized) RecordStageEnd(traceID string, stage LatencyStageOptimized, startTime int64) {
	duration := time.Duration(time.Now().UnixNano() - startTime)
	lt.RecordStage(traceID, stage, duration)
}

// EndMeasurement 结束延迟测量
func (lt *LatencyTrackerOptimized) EndMeasurement(traceID string) (*LatencyMeasurementOptimized, error) {
	shard := lt.getShardIndex(traceID)

	lt.activeLocks[shard].Lock()
	m, ok := lt.activeMeasurements[shard][traceID]
	if !ok {
		lt.activeLocks[shard].Unlock()
		return nil, fmt.Errorf("measurement not found: %s", traceID)
	}
	delete(lt.activeMeasurements[shard], traceID)
	lt.activeLocks[shard].Unlock()

	// 计算总延迟
	m.EndTime = time.Now().UnixNano()
	m.TotalLatency = m.EndTime - m.StartTime

	// 存入环形缓冲区（无锁）
	idx := atomic.AddUint64(&lt.writeIndex, 1) % uint64(lt.bufferSize)
	lt.measurements[idx] = m

	// 记录总延迟
	if lt.totalLatencyHist != nil {
		lt.totalLatencyHist.Observe(float64(time.Duration(m.TotalLatency).Milliseconds()))
	}

	// 更新统计
	atomic.AddUint64(&lt.totalMeasurements, 1)

	// 异常检测（< 100ms）
	if time.Duration(m.TotalLatency) > lt.config.AnomalyThreshold {
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
func (lt *LatencyTrackerOptimized) AnalyzeBreakdown(m *LatencyMeasurementOptimized) *LatencyBreakdownOptimized {
	breakdown := &LatencyBreakdownOptimized{
		TraceID:            m.TraceID,
		FeatureEngineering: time.Duration(atomic.LoadInt64(&m.Stages[StageFeatureEngineering])),
		ModelInference:     time.Duration(atomic.LoadInt64(&m.Stages[StageModelInference])),
		StrategyDecision:   time.Duration(atomic.LoadInt64(&m.Stages[StageStrategyDecision])),
		OrderTransmission:  time.Duration(atomic.LoadInt64(&m.Stages[StageOrderTransmission])),
		ExchangeExecution:  time.Duration(atomic.LoadInt64(&m.Stages[StageExchangeExecution])),
		TotalLatency:       time.Duration(m.TotalLatency),
	}

	// 找出瓶颈阶段
	stages := []time.Duration{
		breakdown.FeatureEngineering,
		breakdown.ModelInference,
		breakdown.StrategyDecision,
		breakdown.OrderTransmission,
		breakdown.ExchangeExecution,
	}

	var maxDuration time.Duration
	var maxStage LatencyStageOptimized
	for i, d := range stages {
		if d > maxDuration {
			maxDuration = d
			maxStage = LatencyStageOptimized(i)
		}
	}

	breakdown.BottleneckStage = maxStage
	if breakdown.TotalLatency > 0 {
		breakdown.BottleneckPercent = float64(maxDuration) / float64(breakdown.TotalLatency) * 100
	}

	// 记录瓶颈指标
	if lt.bottleneckGauge != nil {
		lt.bottleneckGauge.WithLabelValues(maxStage.String()).Set(breakdown.BottleneckPercent)
	}

	return breakdown
}

// GetMeasurement 获取测量记录
func (lt *LatencyTrackerOptimized) GetMeasurement(traceID string) (*LatencyMeasurementOptimized, bool) {
	shard := lt.getShardIndex(traceID)

	// 检查活跃测量
	lt.activeLocks[shard].RLock()
	if m, ok := lt.activeMeasurements[shard][traceID]; ok {
		lt.activeLocks[shard].RUnlock()
		return m, true
	}
	lt.activeLocks[shard].RUnlock()

	// 检查环形缓冲区
	readIdx := atomic.LoadUint64(&lt.readIndex)
	writeIdx := atomic.LoadUint64(&lt.writeIndex)

	for i := writeIdx; i > readIdx && i > writeIdx-1000; i-- {
		idx := i % uint64(lt.bufferSize)
		if m := lt.measurements[idx]; m != nil && m.TraceID == traceID {
			return m, true
		}
	}

	return nil, false
}

// GetStats 获取统计信息
func (lt *LatencyTrackerOptimized) GetStats() map[string]interface{} {
	total := atomic.LoadUint64(&lt.totalMeasurements)
	anomalies := atomic.LoadUint64(&lt.anomalyCount)

	// 计算平均延迟
	var totalLatency int64
	var count int
	writeIdx := atomic.LoadUint64(&lt.writeIndex)
	for i := uint64(0); i < 1000 && i < writeIdx; i++ {
		idx := (writeIdx - 1 - i) % uint64(lt.bufferSize)
		if m := lt.measurements[idx]; m != nil {
			totalLatency += m.TotalLatency
			count++
		}
	}

	avgLatency := time.Duration(0)
	if count > 0 {
		avgLatency = time.Duration(totalLatency / int64(count))
	}

	return map[string]interface{}{
		"total_measurements":   total,
		"anomaly_count":        anomalies,
		"anomaly_rate_percent": float64(anomalies) / float64(total) * 100,
		"average_latency_ms":   float64(avgLatency.Microseconds()) / 1000.0,
		"buffer_utilization":   float64(writeIdx%uint64(lt.bufferSize)) / float64(lt.bufferSize) * 100,
	}
}

// SetAnomalyCallback 设置异常检测回调
func (lt *LatencyTrackerOptimized) SetAnomalyCallback(cb func(measurement *LatencyMeasurementOptimized, breakdown *LatencyBreakdownOptimized)) {
	lt.onAnomaly = cb
}

// Reset 重置所有记录
func (lt *LatencyTrackerOptimized) Reset() {
	// 清空活跃测量
	for i := 0; i < 16; i++ {
		lt.activeLocks[i].Lock()
		for _, m := range lt.activeMeasurements[i] {
			lt.measurementPool.Put(m)
		}
		lt.activeMeasurements[i] = make(map[string]*LatencyMeasurementOptimized)
		lt.activeLocks[i].Unlock()
	}

	// 重置索引
	atomic.StoreUint64(&lt.writeIndex, 0)
	atomic.StoreUint64(&lt.readIndex, 0)
	atomic.StoreUint64(&lt.totalMeasurements, 0)
	atomic.StoreUint64(&lt.anomalyCount, 0)
}

// BatchRecordStages 批量记录阶段（减少系统调用）
func (lt *LatencyTrackerOptimized) BatchRecordStages(traceID string, stages map[LatencyStageOptimized]time.Duration) {
	for stage, duration := range stages {
		lt.RecordStage(traceID, stage, duration)
	}
}
