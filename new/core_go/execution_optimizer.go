package main

import (
	"fmt"
	"math"
	"sync"
	"time"
)

/*
execution_optimizer.go - Execution Alpha Optimizer

填补从"交易意愿"到"订单参数"的空白，将AI的粗粒度决策
转化为具备执行Alpha的精细化订单参数。

核心优化策略:
1. Microprice Edge - 利用微价格偏移优化挂单位置
2. Queue-Aware Execution - 基于队列位置调整价格积极性
3. Defense Integration - 将防御模式转化为执行参数
4. Urgency-Based Order Type - 动态选择限价/市价/只做市
*/

// ExecutionConfig 执行优化器配置
type ExecutionConfig struct {
	// 微价格参数
	MicroPriceThreshold float64 // 微价格偏移阈值，超过此值视为有edge

	// 队列感知参数
	QueuePositionThreshold float64 // 队列位置阈值，>此值视为靠后
	QueueFrontThreshold    float64 // 队列靠前阈值，<此值视为靠前

	// 积极性阈值
	UrgencyMarketThreshold     float64 // >此值使用市价单
	UrgencyAggressiveThreshold float64 // >此值挂对手盘
	UrgencyPassiveThreshold    float64 // <此值被动挂单

	// 防御模式参数
	AllowAggressiveInToxic  bool    // TOXIC模式下是否允许顺势taker
	ToxicUrgencyBoost       float64 // TOXIC安全侧的urgency提升
	DefensiveUrgencyPenalty float64 // DEFENSIVE模式的urgency惩罚

	// 反转信号参数
	ReversalSignalEnabled       bool    // 是否启用反转信号
	ReversalMinConfidence       float64 // 反转信号最小置信度
	ReversalMinStrength         float64 // 反转信号最小强度
	ReversalUrgencyBoostFactor  float64 // 反转信号urgency提升因子
	ReversalMaxSignalAgeMs      int     // 反转信号最大有效时间
	ReversalReverseOnStrongSignal bool  // 强反转信号时是否反转仓位

	// TTL参数
	TTLNormal    time.Duration
	TTLDefensive time.Duration
	TTLToxic     time.Duration

	// 数量调整
	MaxOrderSizeLimit  float64 // 最大单笔订单大小
	MinOrderSizeLimit  float64 // 最小单笔订单大小
	ToxicSizeReduction float64 // TOXIC模式下数量缩减比例
}

// DefaultExecutionConfig 返回默认配置
func DefaultExecutionConfig() *ExecutionConfig {
	return &ExecutionConfig{
		MicroPriceThreshold:        0.0001, // 1bp
		QueuePositionThreshold:     0.7,    // 队列70%以后视为靠后
		QueueFrontThreshold:        0.2,    // 队列20%以前视为靠前
		UrgencyMarketThreshold:     0.8,    // >0.8使用市价单
		UrgencyAggressiveThreshold: 0.5,    // >0.5挂对手盘
		UrgencyPassiveThreshold:    0.3,    // <0.3被动挂单
		AllowAggressiveInToxic:     true,   // 允许TOXIC顺势taker
		ToxicUrgencyBoost:          0.3,    // TOXIC安全侧+0.3 urgency
		DefensiveUrgencyPenalty:    0.2,    // DEFENSIVE-0.2 urgency
		// 反转信号默认配置
		ReversalSignalEnabled:       true,
		ReversalMinConfidence:       0.6,
		ReversalMinStrength:         0.3,
		ReversalUrgencyBoostFactor:  0.3,
		ReversalMaxSignalAgeMs:      500,
		ReversalReverseOnStrongSignal: true,
		TTLNormal:    5 * time.Second,
		TTLDefensive: 2 * time.Second,
		TTLToxic:     500 * time.Millisecond,
		MaxOrderSizeLimit:  1.0,   // 1 BTC
		MinOrderSizeLimit:  0.001, // 0.001 BTC
		ToxicSizeReduction: 0.5,   // TOXIC模式减半
	}
}

// OptimizedOrderParams 优化后的订单参数
type OptimizedOrderParams struct {
	Side      OrderSide   // BUY/SELL
	Type      OrderType   // LIMIT/MARKET/POST_ONLY_LIMIT
	Price     float64     // 价格 (市价单为0)
	Quantity  float64     // 数量
	Urgency   float64     // 0-1，下单积极性
	TTL       time.Duration // 订单生存时间

	// 元数据 (用于调试和归因)
	Metadata OrderMetadata
}

// OrderMetadata 订单元数据
type OrderMetadata struct {
	OriginalUrgency    float64   // 原始AI urgency
	MicroPriceEdge     float64   // 微价格偏移
	QueuePosition      float64   // 队列位置
	DefenseMode        string    // 防御模式
	ToxicScore         float64   // 毒流分数
	OptimizationReason string    // 优化原因
}

// AICommand AI原始决策命令
type AICommand struct {
	Side       OrderSide
	Size       float64
	Price      float64
	Confidence float64 // AI信心度 0-1
	Urgency    float64 // AI urgency 0-1
}

// ExecutionOptimizer 执行优化器
type ExecutionOptimizer struct {
	config     *ExecutionConfig
	defenseMgr *DefenseManager

	// 反转信号检测 (本地Go实现)
	reversalDetector *ReversalDetector

	// 反转信号集成 (从Python模型读取)
	reversalIntegration *ReversalSignalIntegration

	// 市场数据缓存 (由marketDataLoop更新)
	marketData   *MarketSnapshot
	marketDataMu sync.RWMutex
}

// NewExecutionOptimizer 创建执行优化器
func NewExecutionOptimizer(config *ExecutionConfig, defenseMgr *DefenseManager, reversalDetector *ReversalDetector) *ExecutionOptimizer {
	if config == nil {
		config = DefaultExecutionConfig()
	}

	eo := &ExecutionOptimizer{
		config:           config,
		defenseMgr:       defenseMgr,
		reversalDetector: reversalDetector,
		marketData:       &MarketSnapshot{},
	}

	// 初始化反转信号集成 (从Python模型读取)
	if config.ReversalSignalEnabled {
		reversalConfig := &ReversalIntegrationConfig{
			Enabled:               config.ReversalSignalEnabled,
			MinConfidence:         config.ReversalMinConfidence,
			MinSignalStrength:     config.ReversalMinStrength,
			UrgencyBoostFactor:    config.ReversalUrgencyBoostFactor,
			MaxSignalAgeMs:        config.ReversalMaxSignalAgeMs,
			ReverseOnStrongSignal: config.ReversalReverseOnStrongSignal,
		}

		integration, err := NewReversalSignalIntegration("/tmp/hft_reversal_shm", reversalConfig)
		if err != nil {
			// 如果SHM连接失败，记录错误但不阻止执行优化器创建
			// 可以降级为仅使用本地反转检测
			fmt.Printf("Warning: Failed to connect to reversal signal SHM: %v\n", err)
		} else {
			eo.reversalIntegration = integration
		}
	}

	return eo
}

// UpdateMarketData 更新市场数据 (由marketDataLoop调用)
func (eo *ExecutionOptimizer) UpdateMarketData(snapshot *MarketSnapshot) {
	eo.marketDataMu.Lock()
	defer eo.marketDataMu.Unlock()

	*eo.marketData = *snapshot
}

// getMarketData 获取市场数据快照
func (eo *ExecutionOptimizer) getMarketData() *MarketSnapshot {
	eo.marketDataMu.RLock()
	defer eo.marketDataMu.RUnlock()

	// 返回副本
	snapshot := *eo.marketData
	return &snapshot
}

// Optimize 核心优化方法
func (eo *ExecutionOptimizer) Optimize(cmd AICommand, inventory float64) (*OptimizedOrderParams, error) {
	// 获取最新市场数据
	market := eo.getMarketData()

	// 基础参数
	params := &OptimizedOrderParams{
		Side:     cmd.Side,
		Quantity: cmd.Size,
		Urgency:  cmd.Urgency,
		Metadata: OrderMetadata{
			OriginalUrgency: cmd.Urgency,
		},
	}

	// === 1. 计算微价格Edge ===
	midPrice := (market.BestBid + market.BestAsk) / 2
	microPriceEdge := market.MicroPrice - midPrice
	params.Metadata.MicroPriceEdge = microPriceEdge

	// === 2. 防御模式策略覆盖 ===
	eo.applyDefensePolicy(params, market)

	// === 3. 队列感知价格计算 ===
	queuePrice, queuePos := eo.calcQueueAwarePrice(params.Side, market)
	params.Metadata.QueuePosition = queuePos

	// === 4. 反转信号集成：根据信号强度调整urgency ===
	eo.applyReversalSignalAdjustment(params)

	// === 5. 综合决策：订单类型、价格、最终Urgency ===
	eo.determineExecutionStrategy(params, microPriceEdge, queuePrice, market)

	// === 5. 数量调整 ===
	eo.adjustQuantity(params, market)

	// === 6. 生成元数据 ===
	params.Metadata.ToxicScore = market.ToxicProbability
	params.Metadata.OptimizationReason = eo.buildOptimizationReason(params)

	// 验证：如果数量被调整为0，表示订单被取消，返回nil但不报错
	// 调用方应该检查 params.Quantity > 0
	if params.Quantity <= 0 {
		return nil, nil // 订单被取消，不是错误
	}

	return params, nil
}

// applyDefensePolicy 应用防御策略
func (eo *ExecutionOptimizer) applyDefensePolicy(p *OptimizedOrderParams, _ *MarketSnapshot) {
	if eo.defenseMgr == nil {
		p.TTL = eo.config.TTLNormal
		p.Metadata.DefenseMode = "NORMAL"
		return
	}

	// 获取防御状态
	fsmState := eo.defenseMgr.GetFSMState()
	mode, _ := fsmState["mode"].(string)
	p.Metadata.DefenseMode = mode

	toxicState := eo.defenseMgr.GetToxicState()
	toxicScore := toxicState.ToxicScore

	switch mode {
	case "TOXIC":
		p.TTL = eo.config.TTLToxic

		// 获取安全侧
		safeSide := eo.getSafeSideFromToxicState(toxicState)

		if p.Side != safeSide {
			// 非安全侧：根据配置决定是否反转或取消
			if eo.config.AllowAggressiveInToxic && toxicScore > 0.9 {
				// 极端毒流：顺势taker
				p.Side = safeSide
				p.Type = TypeMarket
				p.Urgency = 1.0
				p.Price = 0
			} else {
				// 取消订单
				p.Quantity = 0
			}
		} else {
			// 安全侧：提高积极性
			p.Urgency = math.Min(p.Urgency+eo.config.ToxicUrgencyBoost, 1.0)
			// TOXIC模式减少数量
			p.Quantity *= (1 - eo.config.ToxicSizeReduction)
		}

	case "DEFENSIVE":
		p.TTL = eo.config.TTLDefensive
		// 降低积极性
		p.Urgency = math.Max(p.Urgency-eo.config.DefensiveUrgencyPenalty, 0)

	default: // NORMAL
		p.TTL = eo.config.TTLNormal
	}
}

// getSafeSideFromToxicState 从毒流状态获取安全侧
func (eo *ExecutionOptimizer) getSafeSideFromToxicState(toxic ToxicDetection) OrderSide {
	// 买压大 -> 安全侧是卖 (可以吃买盘返佣)
	// 卖压大 -> 安全侧是买
	switch toxic.ToxicSide {
	case SideBuyPressure:
		return SideSell
	case SideSellPressure:
		return SideBuy
	default:
		// 中性：根据当前仓位决定
		return SideBuy // 默认
	}
}

// calcQueueAwarePrice 计算队列感知价格
func (eo *ExecutionOptimizer) calcQueueAwarePrice(side OrderSide, market *MarketSnapshot) (price float64, position float64) {
	var queuePos float64
	var bestPrice, secondBest float64

	if side == SideBuy {
		queuePos = market.BidQueuePosition
		bestPrice = market.BestBid
		// 假设tick size为0.01，实际应从symbol配置获取
		tickSize := 0.01
		secondBest = bestPrice - tickSize
	} else {
		queuePos = market.AskQueuePosition
		bestPrice = market.BestAsk
		tickSize := 0.01
		secondBest = bestPrice + tickSize
	}

	// 队列位置策略
	if queuePos > eo.config.QueuePositionThreshold {
		// 队列靠后：挂更优价格试图获取更好成交价
		price = secondBest
	} else if queuePos < eo.config.QueueFrontThreshold {
		// 队列靠前：直接挂最优价争取立即成交
		price = bestPrice
	} else {
		// 中间位置：挂最优价
		price = bestPrice
	}

	return price, queuePos
}

// determineExecutionStrategy 确定执行策略
func (eo *ExecutionOptimizer) determineExecutionStrategy(
	p *OptimizedOrderParams,
	microEdge float64,
	queuePrice float64,
	market *MarketSnapshot,
) {
	// 如果已被防御策略设为市价单，直接返回
	if p.Type == TypeMarket {
		return
	}

	// 基于微价格调整urgency
	adjustedUrgency := p.Urgency

	// 微价格与我们同向：增加urgency
	if (p.Side == SideBuy && microEdge > eo.config.MicroPriceThreshold) ||
	   (p.Side == SideSell && microEdge < -eo.config.MicroPriceThreshold) {
		adjustedUrgency += math.Abs(microEdge) * 100 // 放大微价格影响
	} else if (p.Side == SideBuy && microEdge < -eo.config.MicroPriceThreshold) ||
			  (p.Side == SideSell && microEdge > eo.config.MicroPriceThreshold) {
		// 微价格与我们反向：降低urgency
		adjustedUrgency -= math.Abs(microEdge) * 100
	}

	// 限制在0-1范围
	adjustedUrgency = math.Max(0, math.Min(1, adjustedUrgency))
	p.Urgency = adjustedUrgency

	// 根据urgency决定订单类型和价格
	switch {
	case adjustedUrgency >= eo.config.UrgencyMarketThreshold:
		// 高urgency：市价单
		p.Type = TypeMarket
		p.Price = 0

	case adjustedUrgency >= eo.config.UrgencyAggressiveThreshold:
		// 中高urgency：积极限价单（挂对手盘）
		p.Type = TypeLimit
		if p.Side == SideBuy {
			p.Price = market.BestAsk // 买就挂卖一
		} else {
			p.Price = market.BestBid // 卖就挂买一
		}

	case adjustedUrgency >= eo.config.UrgencyPassiveThreshold:
		// 中urgency：标准限价单（挂队列感知价格）
		p.Type = TypeLimit
		p.Price = queuePrice

	default:
		// 低urgency：只做市单（POST_ONLY）
		p.Type = TypeLimit // 实际应使用POST_ONLY标志
		p.Price = queuePrice
	}
}

// GradedExecutionLevel 分级执行级别
type GradedExecutionLevel int

const (
	LevelNone     GradedExecutionLevel = 0 // 无信号
	LevelWeak     GradedExecutionLevel = 1 // 轻度信号 - 微调
	LevelMedium   GradedExecutionLevel = 2 // 中度信号 - 调整积极性和TTL
	LevelStrong   GradedExecutionLevel = 3 // 强烈信号 - 可能反转仓位
)

// GradedExecutionDecision 分级执行决策
type GradedExecutionDecision struct {
	Level           GradedExecutionLevel
	AdjustUrgency   bool
	NewUrgency      float64
	AdjustTTL       bool
	NewTTL          time.Duration
	ReversePosition bool
	AdjustPrice     bool
	PriceOffset     float64 // 价格偏移 (tick)
	Reason          string
}

// applyReversalSignalAdjustment 应用反转信号调整 (分级执行)
func (eo *ExecutionOptimizer) applyReversalSignalAdjustment(p *OptimizedOrderParams) {
	if eo.reversalIntegration == nil || !eo.config.ReversalSignalEnabled {
		return
	}

	// 更新反转信号
	eo.reversalIntegration.Update()

	// 获取最新信号
	signal, timestamp := eo.reversalIntegration.GetLastSignal()
	if signal == nil {
		return
	}

	// 检查信号时效性
	age := time.Since(timestamp)
	if age.Milliseconds() > int64(eo.config.ReversalMaxSignalAgeMs) {
		return
	}

	// 分级决策
	decision := eo.makeGradedDecision(signal, p)

	// 应用决策
	eo.applyGradedDecision(p, decision)
}

// makeGradedDecision 制定分级执行决策
func (eo *ExecutionOptimizer) makeGradedDecision(
	signal *ReversalSignalSHM,
	p *OptimizedOrderParams,
) GradedExecutionDecision {
	strength := math.Abs(signal.SignalStrength)
	confidence := signal.Confidence
	signalDirection := signal.GetDirection()
	currentDirection := 1
	if p.Side == SideSell {
		currentDirection = -1
	}

	decision := GradedExecutionDecision{
		Level:         LevelNone,
		AdjustUrgency: false,
		NewUrgency:    p.Urgency,
		AdjustTTL:     false,
		NewTTL:        p.TTL,
	}

	// Level 3: 强烈信号 (strength >= 0.7, confidence >= 0.8)
	if strength >= 0.7 && confidence >= 0.8 {
		decision.Level = LevelStrong

		if signalDirection != currentDirection {
			// 强反转信号，反转仓位
			decision.ReversePosition = true
			decision.Reason = fmt.Sprintf("Strong reversal: strength=%.3f conf=%.2f",
				signal.SignalStrength, confidence)
		} else {
			// 强确认信号，大幅增加积极性
			decision.AdjustUrgency = true
			decision.NewUrgency = math.Min(1.0, p.Urgency+0.4)
			decision.AdjustTTL = true
			decision.NewTTL = 3 * time.Second
			decision.Reason = fmt.Sprintf("Strong confirm: strength=%.3f conf=%.2f",
				signal.SignalStrength, confidence)
		}
		return decision
	}

	// Level 2: 中度信号 (strength >= 0.5, confidence >= 0.7)
	if strength >= 0.5 && confidence >= 0.7 {
		decision.Level = LevelMedium
		decision.AdjustUrgency = true
		decision.AdjustTTL = true

		if signalDirection == currentDirection {
			// 同向信号 - 增加积极性
			decision.NewUrgency = math.Min(1.0, p.Urgency+0.25)
			decision.NewTTL = 4 * time.Second
			decision.Reason = fmt.Sprintf("Medium confirm: strength=%.3f conf=%.2f",
				signal.SignalStrength, confidence)
		} else {
			// 反向信号 - 降低积极性，缩短TTL
			decision.NewUrgency = math.Max(0.0, p.Urgency-0.25)
			decision.NewTTL = 2 * time.Second
			decision.Reason = fmt.Sprintf("Medium reversal: strength=%.3f conf=%.2f",
				signal.SignalStrength, confidence)
		}
		return decision
	}

	// Level 1: 轻度信号 (strength >= 0.3, confidence >= 0.6)
	if strength >= 0.3 && confidence >= 0.6 {
		decision.Level = LevelWeak

		if signalDirection == currentDirection {
			decision.AdjustUrgency = true
			decision.NewUrgency = math.Min(1.0, p.Urgency+0.1)
			decision.AdjustPrice = true
			decision.PriceOffset = -1 // 向更有利价格偏移1个tick
			decision.Reason = fmt.Sprintf("Weak confirm: strength=%.3f conf=%.2f",
				signal.SignalStrength, confidence)
		} else {
			decision.AdjustPrice = true
			decision.PriceOffset = 1 // 向更保守价格偏移1个tick
			decision.Reason = fmt.Sprintf("Weak reversal: strength=%.3f conf=%.2f",
				signal.SignalStrength, confidence)
		}
		return decision
	}

	return decision
}

// applyGradedDecision 应用分级决策
func (eo *ExecutionOptimizer) applyGradedDecision(
	p *OptimizedOrderParams,
	decision GradedExecutionDecision,
) {
	if decision.Level == LevelNone {
		return
	}

	// 应用urgency调整
	if decision.AdjustUrgency {
		p.Urgency = decision.NewUrgency
	}

	// 应用TTL调整
	if decision.AdjustTTL {
		p.TTL = decision.NewTTL
	}

	// 应用仓位反转
	if decision.ReversePosition {
		if p.Side == SideBuy {
			p.Side = SideSell
		} else {
			p.Side = SideBuy
		}
		p.Metadata.OptimizationReason += " [REVERSAL_FLIP " + decision.Reason + "]"
	}

	// 应用价格调整
	if decision.AdjustPrice && decision.PriceOffset != 0 {
		// 获取tick size (简化处理，实际应从市场数据获取)
		tickSize := 0.01

		if p.Side == SideBuy {
			// 买单：负偏移=更低价格(更有利)，正偏移=更高价格(更保守)
			p.Price -= decision.PriceOffset * tickSize
		} else {
			// 卖单：负偏移=更高价格(更有利)，正偏移=更低价格(更保守)
			p.Price += decision.PriceOffset * tickSize
		}
	}

	// 记录优化原因
	if decision.Reason != "" {
		p.Metadata.OptimizationReason += fmt.Sprintf(" [%s L%d]", decision.Reason, decision.Level)
	}
}

// adjustQuantity 调整订单数量
func (eo *ExecutionOptimizer) adjustQuantity(p *OptimizedOrderParams, market *MarketSnapshot) {
	// 基于订单簿深度调整
	var availableDepth float64
	if p.Side == SideBuy {
		availableDepth = market.Asks[0].Quantity // 卖盘深度
	} else {
		availableDepth = market.Bids[0].Quantity // 买盘深度
	}

	// 如果数量超过深度的一定比例，进行缩减
	maxByDepth := availableDepth * 0.1 // 不超过深度的10%
	if p.Quantity > maxByDepth {
		p.Quantity = maxByDepth
	}

	// 应用最大限制
	if p.Quantity > eo.config.MaxOrderSizeLimit {
		p.Quantity = eo.config.MaxOrderSizeLimit
	}

	// 确保最小数量
	if p.Quantity < eo.config.MinOrderSizeLimit {
		p.Quantity = 0 // 数量太小，取消
	}
}

// buildOptimizationReason 构建优化原因字符串
func (eo *ExecutionOptimizer) buildOptimizationReason(p *OptimizedOrderParams) string {
	reason := fmt.Sprintf(
		"side=%v type=%v price=%.2f qty=%.4f urgency=%.2f ttl=%v | ",
		p.Side, p.Type, p.Price, p.Quantity, p.Urgency, p.TTL,
	)

	reason += fmt.Sprintf(
		"microEdge=%.4f queuePos=%.2f mode=%s",
		p.Metadata.MicroPriceEdge,
		p.Metadata.QueuePosition,
		p.Metadata.DefenseMode,
	)

	// 添加反转信号信息
	if eo.reversalIntegration != nil {
		signal, timestamp := eo.reversalIntegration.GetLastSignal()
		if signal != nil {
			age := time.Since(timestamp).Milliseconds()
			reason += fmt.Sprintf(" | reversal=%.3f conf=%.2f age=%dms",
				signal.SignalStrength, signal.Confidence, age)
		}
	}

	return reason
}

// GetReversalSignalStats 获取反转信号统计
func (eo *ExecutionOptimizer) GetReversalSignalStats() map[string]interface{} {
	if eo.reversalIntegration == nil {
		return map[string]interface{}{"enabled": false}
	}

	stats := eo.reversalIntegration.reader.GetStats()
	stats["enabled"] = true

	signal, timestamp := eo.reversalIntegration.GetLastSignal()
	if signal != nil {
		stats["last_signal"] = map[string]interface{}{
			"strength":      signal.SignalStrength,
			"confidence":    signal.Confidence,
			"probability":   signal.Probability,
			"direction":     signal.GetDirection(),
			"urgency":       signal.Confidence * math.Abs(signal.SignalStrength),
			"timestamp":     timestamp,
			"model_version": signal.ModelVersion,
			"latency_us":    signal.InferenceLatencyUs,
		}
	}

	return stats
}

// Close 清理资源
func (eo *ExecutionOptimizer) Close() error {
	if eo.reversalIntegration != nil {
		return eo.reversalIntegration.Close()
	}
	return nil
}

// GetConfig 获取当前配置
func (eo *ExecutionOptimizer) GetConfig() *ExecutionConfig {
	return eo.config
}

// UpdateConfig 更新配置
func (eo *ExecutionOptimizer) UpdateConfig(config *ExecutionConfig) {
	eo.config = config
}
