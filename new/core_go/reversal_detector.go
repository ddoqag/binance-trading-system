package main

import (
	"fmt"
	"math"
	"sync"
	"time"
)

/*
reversal_detector.go - Reversal Signal Detector

基于特征工程输出，生成反转交易信号
支持两种反转类型：
- 止跌企稳 (Bottom): 适合买入
- 上涨乏力 (Top): 适合卖出
*/

// ReversalType 反转类型
type ReversalType int

const (
	ReversalTypeNone   ReversalType = iota // 无信号
	ReversalTypeBottom                     // 止跌企稳
	ReversalTypeTop                        // 上涨乏力
)

func (rt ReversalType) String() string {
	switch rt {
	case ReversalTypeBottom:
		return "BOTTOM"
	case ReversalTypeTop:
		return "TOP"
	default:
		return "NONE"
	}
}

// ReversalSignal 反转信号
type ReversalSignal struct {
	Type           ReversalType
	PressureScore  float64   // 压力得分 (0-1)
	PriceScore     float64   // 价格得分 (0-1)
	LiquidityScore float64   // 流动性得分 (0-1)
	CombinedScore  float64   // 综合得分 (0-1)
	Confidence     float64   // 置信度
	Direction      int       // -1=卖出, +1=买入, 0=观望
	Timestamp      int64     // 时间戳
	Reason         string    // 信号原因
}

// ReversalConfig 反转检测器配置
type ReversalConfig struct {
	// 阈值参数
	SignalThreshold    float64 // 信号触发阈值 (默认0.5)
	HighConfidenceThreshold float64 // 高置信度阈值 (默认0.7)
	LowConfidenceThreshold  float64 // 低置信度阈值 (默认0.3)

	// 各特征权重
	PressureWeight   float64 // 压力特征权重 (默认0.4)
	PriceWeight      float64 // 价格特征权重 (默认0.4)
	LiquidityWeight  float64 // 流动性权重 (默认0.2)

	// 时间参数
	MinSignalInterval time.Duration // 最小信号间隔 (默认100ms)
	SignalValidity    time.Duration // 信号有效期 (默认500ms)

	// 趋势确认
	RequireTrendConfirmation bool    // 是否需要趋势确认 (默认true)
	TrendThreshold          float64 // 趋势确认阈值 (默认0.1)

	// 压力反转特定参数
	BottomOFIThreshold    float64 // 止跌时OFI阈值 (默认-0.3)
	BottomDeltaThreshold  float64 // 止跌时DeltaOFI阈值 (默认0.05)
	TopOFIThreshold       float64 // 上涨乏力时OFI阈值 (默认0.3)
	TopDeltaThreshold     float64 // 上涨乏力时DeltaOFI阈值 (默认-0.05)
}

// DefaultReversalConfig 返回默认配置
func DefaultReversalConfig() *ReversalConfig {
	return &ReversalConfig{
		SignalThreshold:           0.5,
		HighConfidenceThreshold:   0.7,
		LowConfidenceThreshold:    0.3,
		PressureWeight:            0.4,
		PriceWeight:               0.4,
		LiquidityWeight:           0.2,
		MinSignalInterval:         100 * time.Millisecond,
		SignalValidity:            500 * time.Millisecond,
		RequireTrendConfirmation:  true,
		TrendThreshold:            0.1,
		BottomOFIThreshold:        -0.3,
		BottomDeltaThreshold:      0.05,
		TopOFIThreshold:           0.3,
		TopDeltaThreshold:         -0.05,
	}
}

// ReversalDetector 反转信号检测器
type ReversalDetector struct {
	config *ReversalConfig
	featureEngine *ReversalFeatureEngine

	// 状态
	lastSignalTime    int64
	lastSignalType    ReversalType
	consecutiveSignals int

	// 统计
	signalCount      int64
	bottomCount      int64
	topCount         int64
	highConfCount    int64

	// 线程安全
	mu sync.RWMutex
}

// NewReversalDetector 创建反转检测器
func NewReversalDetector(config *ReversalConfig, featureEngine *ReversalFeatureEngine) *ReversalDetector {
	if config == nil {
		config = DefaultReversalConfig()
	}

	return &ReversalDetector{
		config:        config,
		featureEngine: featureEngine,
	}
}

// Detect 检测反转信号
func (rd *ReversalDetector) Detect() *ReversalSignal {
	if rd.featureEngine == nil {
		return nil
	}

	rd.mu.Lock()
	defer rd.mu.Unlock()

	now := time.Now().UnixNano()

	// 检查信号间隔
	if now-rd.lastSignalTime < int64(rd.config.MinSignalInterval) {
		return nil
	}

	// 获取特征得分
	pressureScore := rd.featureEngine.GetPressureScore()
	priceScore := rd.featureEngine.GetPriceScore()
	liquidityScore := rd.featureEngine.GetLiquidityScore()
	combinedScore := rd.featureEngine.GetCombinedScore()

	// 获取原始特征用于条件判断
	features := rd.featureEngine.GetAllFeatures()

	// 判断反转类型
	signalType := rd.classifyReversalType(features, pressureScore, priceScore)

	// 如果无信号，返回nil
	if signalType == ReversalTypeNone {
		return nil
	}

	// 检查综合得分是否达到阈值
	if combinedScore < rd.config.SignalThreshold {
		return nil
	}

	// 计算置信度
	confidence := rd.calculateConfidence(features, combinedScore, signalType)

	// 确定方向
	direction := 0
	switch signalType {
	case ReversalTypeBottom:
		direction = 1 // 买入
	case ReversalTypeTop:
		direction = -1 // 卖出
	}

	// 生成原因
	reason := rd.generateSignalReason(features, signalType)

	// 更新统计
	rd.lastSignalTime = now
	rd.lastSignalType = signalType
	rd.signalCount++

	if signalType == ReversalTypeBottom {
		rd.bottomCount++
	} else {
		rd.topCount++
	}

	if confidence >= rd.config.HighConfidenceThreshold {
		rd.highConfCount++
	}

	return &ReversalSignal{
		Type:           signalType,
		PressureScore:  pressureScore,
		PriceScore:     priceScore,
		LiquidityScore: liquidityScore,
		CombinedScore:  combinedScore,
		Confidence:     confidence,
		Direction:      direction,
		Timestamp:      now,
		Reason:         reason,
	}
}

// classifyReversalType 分类反转类型
func (rd *ReversalDetector) classifyReversalType(features *AllReversalFeatures, pressureScore, priceScore float64) ReversalType {
	p := features.Pressure
	pr := features.Price
	c := features.Composite

	// 判断止跌企稳 (BOTTOM)
	// 条件：卖压减弱 + 价格企稳
	isBottom := false
	if p.OFI < rd.config.BottomOFIThreshold && // 负向OFI（卖压）
		p.DeltaOFI > rd.config.BottomDeltaThreshold && // OFI在改善
		pr.NoNewLowDuration > 100 && // 未创新低
		pr.MicroPriceDev > -0.5 { // Microprice不太负面
		isBottom = true
	}

	// 额外的复合特征确认
	if isBottom && rd.config.RequireTrendConfirmation {
		if c.ReversalMomentum < 0 || c.MarketResilience < 0.3 {
			isBottom = false
		}
	}

	// 判断上涨乏力 (TOP)
	// 条件：买压减弱 + 价格停滞
	isTop := false
	if p.OFI > rd.config.TopOFIThreshold && // 正向OFI（买压）
		p.DeltaOFI < rd.config.TopDeltaThreshold && // OFI在减弱
		pr.NoNewHighDuration > 100 && // 未创新高
		pr.MicroPriceDev < 0.5 { // Microprice不太正面
		isTop = true
	}

	// 额外的复合特征确认
	if isTop && rd.config.RequireTrendConfirmation {
		if c.ReversalMomentum > 0 || c.MarketResilience < 0.3 {
			isTop = false
		}
	}

	// 选择得分更高的类型
	if isBottom && isTop {
		if pressureScore > 0.6 {
			return ReversalTypeBottom
		}
		return ReversalTypeTop
	}

	if isBottom {
		return ReversalTypeBottom
	}
	if isTop {
		return ReversalTypeTop
	}

	return ReversalTypeNone
}

// calculateConfidence 计算信号置信度
func (rd *ReversalDetector) calculateConfidence(features *AllReversalFeatures, combinedScore float64, signalType ReversalType) float64 {
	confidence := combinedScore

	p := features.Pressure
	pr := features.Price

	// 基于特征质量调整置信度
	// 1. OFI趋势一致性
	if p.OFITrend > 0 && signalType == ReversalTypeBottom {
		confidence += 0.1
	} else if p.OFITrend < 0 && signalType == ReversalTypeTop {
		confidence += 0.1
	}

	// 2. 价格确认
	if signalType == ReversalTypeBottom {
		if pr.MicroPriceDev > 0 {
			confidence += 0.1
		}
		if pr.NoNewLowDuration > 200 {
			confidence += 0.1
		}
	} else {
		if pr.MicroPriceDev < 0 {
			confidence += 0.1
		}
		if pr.NoNewHighDuration > 200 {
			confidence += 0.1
		}
	}

	// 3. 收益率衰减确认
	if pr.ReturnDecay < 0.7 {
		confidence += 0.05
	}

	// 限制在合理范围
	return math.Min(math.Max(confidence, 0), 1.0)
}

// generateSignalReason 生成信号原因
func (rd *ReversalDetector) generateSignalReason(features *AllReversalFeatures, signalType ReversalType) string {
	p := features.Pressure
	pr := features.Price

	var reasons []string

	if signalType == ReversalTypeBottom {
		reasons = append(reasons, "止跌企稳信号")
		if p.OFI < 0 && p.DeltaOFI > 0 {
			reasons = append(reasons, fmt.Sprintf("卖压减弱(OFI:%.3f→%.3f)", p.OFI-p.DeltaOFI, p.OFI))
		}
		if pr.NoNewLowDuration > 100 {
			reasons = append(reasons, fmt.Sprintf("未创新低%dms", pr.NoNewLowDuration))
		}
		if pr.MicroPriceDev > -0.3 {
			reasons = append(reasons, fmt.Sprintf("Microprice企稳(%.3f)", pr.MicroPriceDev))
		}
	} else {
		reasons = append(reasons, "上涨乏力信号")
		if p.OFI > 0 && p.DeltaOFI < 0 {
			reasons = append(reasons, fmt.Sprintf("买压减弱(OFI:%.3f→%.3f)", p.OFI-p.DeltaOFI, p.OFI))
		}
		if pr.NoNewHighDuration > 100 {
			reasons = append(reasons, fmt.Sprintf("未创新高%dms", pr.NoNewHighDuration))
		}
		if pr.MicroPriceDev < 0.3 {
			reasons = append(reasons, fmt.Sprintf("Microprice转弱(%.3f)", pr.MicroPriceDev))
		}
	}

	// 组合原因
	result := reasons[0]
	if len(reasons) > 1 {
		result += ": " + reasons[1]
	}
	for i := 2; i < len(reasons); i++ {
		result += ", " + reasons[i]
	}

	return result
}

// GetSignalStrength 获取信号强度 (-1.0 到 +1.0)
// 正值表示买入信号强度，负值表示卖出信号强度
func (rd *ReversalDetector) GetSignalStrength() float64 {
	signal := rd.Detect()
	if signal == nil {
		return 0
	}

	return float64(signal.Direction) * signal.Confidence
}

// IsSignalValid 检查信号是否仍然有效
func (rd *ReversalDetector) IsSignalValid(signal *ReversalSignal) bool {
	if signal == nil {
		return false
	}

	now := time.Now().UnixNano()
	elapsed := time.Duration(now - signal.Timestamp)

	return elapsed < rd.config.SignalValidity
}

// GetStats 获取检测器统计
func (rd *ReversalDetector) GetStats() map[string]interface{} {
	rd.mu.RLock()
	defer rd.mu.RUnlock()

	return map[string]interface{}{
		"total_signals":       rd.signalCount,
		"bottom_signals":      rd.bottomCount,
		"top_signals":         rd.topCount,
		"high_confidence":     rd.highConfCount,
		"last_signal_time":    rd.lastSignalTime,
		"last_signal_type":    rd.lastSignalType.String(),
		"consecutive_signals": rd.consecutiveSignals,
	}
}

// ResetStats 重置统计
func (rd *ReversalDetector) ResetStats() {
	rd.mu.Lock()
	defer rd.mu.Unlock()

	rd.signalCount = 0
	rd.bottomCount = 0
	rd.topCount = 0
	rd.highConfCount = 0
	rd.consecutiveSignals = 0
}

// UpdateConfig 更新配置
func (rd *ReversalDetector) UpdateConfig(config *ReversalConfig) {
	rd.mu.Lock()
	defer rd.mu.Unlock()

	rd.config = config
}

// ReversalSignalProcessor 信号处理器接口
type ReversalSignalProcessor interface {
	ProcessSignal(signal *ReversalSignal) error
}

// ReversalSignalFilter 信号过滤器
type ReversalSignalFilter struct {
	minConfidence      float64
	allowedTypes       []ReversalType
	maxSignalsPerSecond int

	// 内部状态
	signalHistory []int64
	mu            sync.Mutex
}

// NewReversalSignalFilter 创建信号过滤器
func NewReversalSignalFilter(minConfidence float64, allowedTypes []ReversalType, maxPerSec int) *ReversalSignalFilter {
	return &ReversalSignalFilter{
		minConfidence:       minConfidence,
		allowedTypes:        allowedTypes,
		maxSignalsPerSecond: maxPerSec,
		signalHistory:       make([]int64, 0),
	}
}

// Filter 过滤信号
func (f *ReversalSignalFilter) Filter(signal *ReversalSignal) bool {
	if signal == nil {
		return false
	}

	f.mu.Lock()
	defer f.mu.Unlock()

	// 检查置信度
	if signal.Confidence < f.minConfidence {
		return false
	}

	// 检查类型
	typeAllowed := false
	for _, t := range f.allowedTypes {
		if t == signal.Type {
			typeAllowed = true
			break
		}
	}
	if !typeAllowed {
		return false
	}

	// 检查频率限制
	now := time.Now().UnixNano()
	oneSecondAgo := now - int64(time.Second)

	// 清理旧记录
	newHistory := make([]int64, 0)
	for _, ts := range f.signalHistory {
		if ts > oneSecondAgo {
			newHistory = append(newHistory, ts)
		}
	}
	f.signalHistory = newHistory

	// 检查是否超过限制
	if len(f.signalHistory) >= f.maxSignalsPerSecond {
		return false
	}

	// 记录本次信号
	f.signalHistory = append(f.signalHistory, now)

	return true
}
