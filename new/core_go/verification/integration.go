package verification

import (
	"context"
	"fmt"
	"log"
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
)

/*
integration.go - 执行层真实性检验套件集成

整合 ShadowMatcher、LatencyTracker、StateConsistencyChecker 三个组件，
提供统一的接口和协调管理。
*/

// VerificationSuiteConfig 验证套件配置
type VerificationSuiteConfig struct {
	ShadowMatcherConfig     *ShadowMatcherConfig
	LatencyTrackerConfig    *LatencyTrackerConfig
	StateConsistencyConfig  *StateConsistencyConfig

	// 集成配置
	AutoStart           bool          // 是否自动启动
	AlertThreshold      float64       // 告警阈值（异常率百分比）
	ReportInterval      time.Duration // 报告间隔
}

// DefaultVerificationSuiteConfig 返回默认配置
func DefaultVerificationSuiteConfig() *VerificationSuiteConfig {
	return &VerificationSuiteConfig{
		ShadowMatcherConfig:    DefaultShadowMatcherConfig(),
		LatencyTrackerConfig:   DefaultLatencyTrackerConfig(),
		StateConsistencyConfig: DefaultStateConsistencyConfig(),
		AutoStart:              true,
		AlertThreshold:         5.0, // 5% 异常率触发告警
		ReportInterval:         60 * time.Second,
	}
}

// VerificationReport 验证报告
type VerificationReport struct {
	Timestamp         time.Time
	ShadowStats       map[string]interface{}
	LatencyStats      map[string]interface{}
	ConsistencyStats  map[string]interface{}
	OverallHealth     HealthStatus
	Recommendations   []string
}

// HealthStatus 健康状态
type HealthStatus int

const (
	HealthUnknown HealthStatus = iota
	HealthHealthy
	HealthDegraded
	HealthUnhealthy
)

func (h HealthStatus) String() string {
	switch h {
	case HealthHealthy:
		return "healthy"
	case HealthDegraded:
		return "degraded"
	case HealthUnhealthy:
		return "unhealthy"
	default:
		return "unknown"
	}
}

// VerificationSuite 验证套件
type VerificationSuite struct {
	config *VerificationSuiteConfig

	// 组件
	ShadowMatcher    *ShadowMatcher
	LatencyTracker   *LatencyTracker
	StateChecker     *StateConsistencyChecker

	// Prometheus 注册表
	registry *prometheus.Registry

	// 告警回调
	onAlert func(level string, message string)

	// 控制
	stopChan chan struct{}
	wg       sync.WaitGroup
	mu       sync.RWMutex
	running  bool
}

// NewVerificationSuite 创建验证套件
func NewVerificationSuite(config *VerificationSuiteConfig, registry *prometheus.Registry) *VerificationSuite {
	if config == nil {
		config = DefaultVerificationSuiteConfig()
	}

	if registry == nil {
		registry = prometheus.NewRegistry()
	}

	vs := &VerificationSuite{
		config:   config,
		registry: registry,
		stopChan: make(chan struct{}),
	}

	// 创建组件
	vs.ShadowMatcher = NewShadowMatcher(config.ShadowMatcherConfig, registry)
	vs.LatencyTracker = NewLatencyTracker(config.LatencyTrackerConfig, registry)
	vs.StateChecker = NewStateConsistencyChecker(config.StateConsistencyConfig, registry)

	// 设置回调
	vs.setupCallbacks()

	return vs
}

// setupCallbacks 设置组件回调
func (vs *VerificationSuite) setupCallbacks() {
	// 影子匹配器异常回调
	vs.ShadowMatcher.SetAnomalyCallback(func(orderID string, quality *FillQuality) {
		log.Printf("[Verification] Shadow match anomaly detected: order=%s, reason=%s, score=%.2f",
			orderID, quality.AnomalyReason, quality.QualityScore)

		if vs.onAlert != nil && quality.QualityScore < 0.3 {
			vs.onAlert("critical", fmt.Sprintf("Fill quality critical: order=%s", orderID))
		}
	})

	// 延迟追踪器异常回调
	vs.LatencyTracker.SetAnomalyCallback(func(measurement *LatencyMeasurement, breakdown *LatencyBreakdown) {
		log.Printf("[Verification] Latency anomaly detected: trace=%s, total=%v, bottleneck=%s",
			measurement.TraceID, breakdown.TotalLatency, breakdown.BottleneckStage)

		if vs.onAlert != nil && breakdown.TotalLatency > 200*time.Millisecond {
			vs.onAlert("critical", fmt.Sprintf("High latency detected: trace=%s, latency=%v",
				measurement.TraceID, breakdown.TotalLatency))
		}
	})

	// 状态一致性严重差异回调
	vs.StateChecker.SetCriticalCallback(func(diff StateDiff) {
		log.Printf("[Verification] Critical state inconsistency: order=%s, type=%s, severity=%s",
			diff.OrderID, diff.DiffType, diff.Severity)

		if vs.onAlert != nil {
			vs.onAlert("critical", fmt.Sprintf("State inconsistency: order=%s, field=%s",
				diff.OrderID, diff.Field))
		}
	})
}

// Start 启动验证套件
func (vs *VerificationSuite) Start() error {
	vs.mu.Lock()
	defer vs.mu.Unlock()

	if vs.running {
		return nil
	}

	// 启动组件
	vs.ShadowMatcher.Start()
	vs.LatencyTracker.Start()
	vs.StateChecker.Start()

	// 启动报告循环
	vs.wg.Add(1)
	go vs.reportLoop()

	vs.running = true
	log.Println("[Verification] Suite started")
	return nil
}

// Stop 停止验证套件
func (vs *VerificationSuite) Stop() error {
	vs.mu.Lock()
	if !vs.running {
		vs.mu.Unlock()
		return nil
	}
	vs.running = false
	vs.mu.Unlock()

	close(vs.stopChan)

	// 停止组件
	vs.ShadowMatcher.Stop()
	vs.LatencyTracker.Stop()
	vs.StateChecker.Stop()

	vs.wg.Wait()
	log.Println("[Verification] Suite stopped")
	return nil
}

// reportLoop 报告循环
func (vs *VerificationSuite) reportLoop() {
	defer vs.wg.Done()

	ticker := time.NewTicker(vs.config.ReportInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			report := vs.GenerateReport()
			vs.logReport(report)
		case <-vs.stopChan:
			return
		}
	}
}

// logReport 记录报告
func (vs *VerificationSuite) logReport(report *VerificationReport) {
	log.Printf("[Verification Report] Timestamp: %s, Health: %s",
		report.Timestamp.Format(time.RFC3339), report.OverallHealth)

	// 影子匹配统计
	if shadowStats, ok := report.ShadowStats["anomaly_rate"].(float64); ok {
		log.Printf("[Verification Report] Shadow Matcher - Anomaly Rate: %.2f%%", shadowStats)
	}

	// 延迟统计
	if latencyStats, ok := report.LatencyStats["average_latency_ms"].(float64); ok {
		log.Printf("[Verification Report] Latency Tracker - Avg Latency: %.3f ms", latencyStats)
	}

	// 一致性统计
	if consistencyStats, ok := report.ConsistencyStats["total_diffs"].(int); ok {
		log.Printf("[Verification Report] State Consistency - Diffs: %d", consistencyStats)
	}

	// 建议
	for _, rec := range report.Recommendations {
		log.Printf("[Verification Report] Recommendation: %s", rec)
	}
}

// GenerateReport 生成验证报告
func (vs *VerificationSuite) GenerateReport() *VerificationReport {
	report := &VerificationReport{
		Timestamp:        time.Now(),
		ShadowStats:      vs.ShadowMatcher.GetStats(),
		LatencyStats:     vs.LatencyTracker.GetStats(),
		ConsistencyStats: vs.StateChecker.GetStats(),
		Recommendations:  make([]string, 0),
	}

	// 计算整体健康状态
	report.OverallHealth = vs.calculateOverallHealth(report)

	// 生成建议
	report.Recommendations = vs.generateRecommendations(report)

	return report
}

// calculateOverallHealth 计算整体健康状态
func (vs *VerificationSuite) calculateOverallHealth(report *VerificationReport) HealthStatus {
	health := HealthHealthy

	// 检查影子匹配异常率
	if anomalyRate, ok := report.ShadowStats["anomaly_rate"].(float64); ok {
		if anomalyRate > vs.config.AlertThreshold {
			health = HealthDegraded
		}
		if anomalyRate > vs.config.AlertThreshold*2 {
			health = HealthUnhealthy
		}
	}

	// 检查延迟异常率
	if latencyStats, ok := report.LatencyStats["anomaly_rate_percent"].(float64); ok {
		if latencyStats > vs.config.AlertThreshold {
			if health == HealthHealthy {
				health = HealthDegraded
			}
		}
	}

	// 检查状态一致性
	if consistencyStats, ok := report.ConsistencyStats["total_diffs"].(int); ok {
		if consistencyStats > 0 {
			criticalCount := 0
			if severityCounts, ok := report.ConsistencyStats["severity_counts"].(map[string]int); ok {
				criticalCount = severityCounts["critical"]
			}
			if criticalCount > 0 {
				health = HealthUnhealthy
			} else if health == HealthHealthy {
				health = HealthDegraded
			}
		}
	}

	return health
}

// generateRecommendations 生成建议
func (vs *VerificationSuite) generateRecommendations(report *VerificationReport) []string {
	recommendations := make([]string, 0)

	// 基于影子匹配的建议
	if anomalyRate, ok := report.ShadowStats["anomaly_rate"].(float64); ok {
		if anomalyRate > 10 {
			recommendations = append(recommendations,
				"High fill anomaly rate detected. Review execution parameters and market conditions.")
		}
	}

	// 基于延迟的建议
	if latencyStats, ok := report.LatencyStats["average_latency_ms"].(float64); ok {
		if latencyStats > 50 {
			recommendations = append(recommendations,
				"High average latency detected. Consider optimizing network path or reducing processing stages.")
		}
	}

	// 基于状态一致性的建议
	if consistencyStats, ok := report.ConsistencyStats["total_diffs"].(int); ok {
		if consistencyStats > 5 {
			recommendations = append(recommendations,
				"State inconsistencies detected. Recommend immediate reconciliation with exchange.")
		}
	}

	return recommendations
}

// SetAlertCallback 设置告警回调
func (vs *VerificationSuite) SetAlertCallback(cb func(level string, message string)) {
	vs.onAlert = cb
}

// GetRegistry 获取 Prometheus 注册表
func (vs *VerificationSuite) GetRegistry() *prometheus.Registry {
	return vs.registry
}

// IsRunning 检查是否运行中
func (vs *VerificationSuite) IsRunning() bool {
	vs.mu.RLock()
	defer vs.mu.RUnlock()
	return vs.running
}

// VerifyOrder 验证订单（完整流程）
func (vs *VerificationSuite) VerifyOrder(ctx context.Context, orderID string, timeout time.Duration) (*VerificationResult, error) {
	result := &VerificationResult{
		OrderID:   orderID,
		Timestamp: time.Now(),
	}

	// 1. 检查影子匹配
	if quality, ok := vs.ShadowMatcher.GetFillQuality(orderID); ok {
		result.FillQuality = quality
		result.ShadowMatchOK = !quality.AnomalyDetected
	}

	// 2. 等待延迟测量
	if measurement, err := vs.LatencyTracker.WaitForMeasurement(ctx, orderID, timeout); err == nil {
		result.Latency = measurement
		result.LatencyOK = measurement.TotalLatency < vs.config.LatencyTrackerConfig.AnomalyThreshold
	}

	// 3. 检查状态一致性
	diffs := vs.StateChecker.GetDiffs()
	for _, diff := range diffs {
		if diff.OrderID == orderID {
			result.StateDiffs = append(result.StateDiffs, diff)
			if diff.Severity == SeverityCritical {
				result.StateConsistencyOK = false
			}
		}
	}

	// 计算整体结果
	result.Success = result.ShadowMatchOK && result.LatencyOK && result.StateConsistencyOK

	return result, nil
}

// VerificationResult 验证结果
type VerificationResult struct {
	OrderID            string
	Timestamp          time.Time
	FillQuality        *FillQuality
	Latency            *LatencyMeasurement
	StateDiffs         []StateDiff
	ShadowMatchOK      bool
	LatencyOK          bool
	StateConsistencyOK bool
	Success            bool
}

// TriggerManualCheck 触发手动检查
func (vs *VerificationSuite) TriggerManualCheck(ctx context.Context) (*VerificationReport, error) {
	// 触发状态一致性检查
	if err := vs.StateChecker.TriggerManualCheck(ctx); err != nil {
		return nil, fmt.Errorf("state check failed: %w", err)
	}

	// 生成报告
	return vs.GenerateReport(), nil
}

// Reset 重置所有组件
func (vs *VerificationSuite) Reset() {
	vs.ShadowMatcher = NewShadowMatcher(vs.config.ShadowMatcherConfig, vs.registry)
	vs.LatencyTracker.Reset()
	vs.StateChecker.ClearDiffs()

	vs.setupCallbacks()
}
