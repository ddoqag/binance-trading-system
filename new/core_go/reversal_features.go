package main

import (
	"math"
	"sync"
	"time"
)

/*
reversal_features.go - Reversal Alpha Model Features

基于「止跌企稳/上涨乏力」量化思路的特征工程实现
包含三大类特征：
1. Pressure Shift (压力反转) - OFI相关指标
2. Price Response (价格响应) - Microprice/收益率/新高新低
3. Liquidity Change (流动性变化) - 挂单簿/吸收流
*/

// ReversalFeatureConfig 反转特征配置
type ReversalFeatureConfig struct {
	// 窗口大小
	OFIWindow          int           // OFI计算窗口 (默认100)
	TrendWindow        int           // 趋势计算窗口 (默认5)
	MomentumWindow     int           // 动量计算窗口 (默认10)
	VolatilityWindow   int           // 波动率窗口 (默认20)
	PriceHistoryWindow int           // 价格历史窗口 (默认100)

	// 阈值参数
	NewLowThresholdMs   int64   // 未创新低阈值 (默认150ms)
	NewHighThresholdMs  int64   // 未创新高阈值 (默认150ms)
	LargeTradeThreshold float64 // 大单阈值 (默认1000.0)

	// 更新间隔
	UpdateInterval time.Duration // 默认50ms
}

// DefaultReversalFeatureConfig 返回默认配置
func DefaultReversalFeatureConfig() *ReversalFeatureConfig {
	return &ReversalFeatureConfig{
		OFIWindow:           100,
		TrendWindow:         5,
		MomentumWindow:      10,
		VolatilityWindow:    20,
		PriceHistoryWindow:  100,
		NewLowThresholdMs:   150,
		NewHighThresholdMs:  150,
		LargeTradeThreshold: 1000.0,
		UpdateInterval:      50 * time.Millisecond,
	}
}

// PressureFeatures 压力反转特征
type PressureFeatures struct {
	// 基础指标
	OFI         float64 // 当前订单流不平衡
	DeltaOFI    float64 // OFI 一阶差分
	AccelOFI    float64 // OFI 二阶差分 (加速度)

	// 趋势指标
	OFITrend    float64 // OFI 线性回归斜率
	OFIMomentum float64 // OFI 动量 (当前-10期前)
	OFIStdDev   float64 // OFI 标准差

	// 比率指标
	OFIRatio      float64 // 当前OFI / 历史最大OFI绝对值
	DeltaOFIRatio float64 // DeltaOFI绝对值 / OFI标准差

	// 原始数据窗口（用于计算）
	ofiHistory []float64
}

// PriceResponseFeatures 价格响应特征
type PriceResponseFeatures struct {
	// Microprice 相关
	MicroPriceDev   float64 // (microPrice - midPrice) / spread
	MicroPriceTrend float64 // microPrice 趋势

	// 价格行为
	Return50ms   float64 // 50ms 收益率
	Return100ms  float64 // 100ms 收益率
	ReturnDecay  float64 // 收益率衰减速率

	// 新高/新低统计
	NoNewLowDuration  int64 // 未创新低持续时间(ms)
	NoNewHighDuration int64 // 未创新高持续时间(ms)

	// 价格弹性
	PriceImpactBuy  float64 // 买单冲击成本
	PriceImpactSell float64 // 卖单冲击成本

	// 波动率
	Volatility20    float64 // 20期波动率
	VolatilityRatio float64 // 短期/长期波动率

	// 内部状态
	lastPrice      float64
	lastUpdateTime int64
	highPrice      float64
	lowPrice       float64
	priceHistory50 []float64
	priceHistory100 []float64
}

// LiquidityFeatures 流动性特征
type LiquidityFeatures struct {
	// 挂单簿不平衡
	BidAskImbalance float64 // (bidSize - askSize) / (bidSize + askSize)
	QueuePosition   float64 // 挂单队列位置

	// 流动性变化
	BidSizeChange float64 // bid挂单量变化率
	AskSizeChange float64 // ask挂单量变化率

	// 价差行为
	Spread       float64
	SpreadChange float64
	SpreadTrend  float64 // 价差趋势

	// 大单统计
	LargeTradeRatio float64 // 大额成交占比
	TradeIntensity  float64 // 成交强度
	AbsorptionFlow  float64 // 吸收流

	// 历史数据
	lastBidSize float64
	lastAskSize float64
	lastSpread  float64
	spreadHistory []float64
	tradesBuffer  []TradeTick
}

// CompositeFeatures 复合特征
type CompositeFeatures struct {
	PressurePriceDivergence float64 // 压力-价格背离: OFI变化方向 vs 价格变化方向
	LiquidityEfficiency     float64 // 流动性-价格效率: 价格变动 / 成交量
	MarketResilience        float64 // 市场韧性: 新高/新低持续时间 + 挂单吸收
	ReversalMomentum        float64 // 反转动量: PriceReturn * (1 - |OFIRatio|)
}

// AllReversalFeatures 所有反转特征聚合
type AllReversalFeatures struct {
	Timestamp   int64
	Pressure    PressureFeatures
	Price       PriceResponseFeatures
	Liquidity   LiquidityFeatures
	Composite   CompositeFeatures
}

// ReversalFeatureEngine 反转特征引擎
type ReversalFeatureEngine struct {
	config *ReversalFeatureConfig

	// 特征状态
	pressure  *PressureFeatures
	price     *PriceResponseFeatures
	liquidity *LiquidityFeatures
	composite CompositeFeatures

	// 线程安全
	mu sync.RWMutex

	// 市场数据引用
	marketData *MarketSnapshot
}

// NewReversalFeatureEngine 创建特征引擎
func NewReversalFeatureEngine(config *ReversalFeatureConfig) *ReversalFeatureEngine {
	if config == nil {
		config = DefaultReversalFeatureConfig()
	}

	return &ReversalFeatureEngine{
		config: config,
		pressure: &PressureFeatures{
			ofiHistory: make([]float64, 0, config.OFIWindow),
		},
		price: &PriceResponseFeatures{
			priceHistory50:  make([]float64, 0, 50),
			priceHistory100: make([]float64, 0, 100),
		},
		liquidity: &LiquidityFeatures{
			spreadHistory: make([]float64, 0, config.VolatilityWindow),
			tradesBuffer:  make([]TradeTick, 0, 100),
		},
	}
}

// UpdateMarketData 更新市场数据并计算特征
func (fe *ReversalFeatureEngine) UpdateMarketData(snapshot *MarketSnapshot) {
	fe.mu.Lock()
	defer fe.mu.Unlock()

	fe.marketData = snapshot

	// 计算各类特征
	fe.updatePressureFeatures(snapshot)
	fe.updatePriceFeatures(snapshot)
	fe.updateLiquidityFeatures(snapshot)
	fe.updateCompositeFeatures()
}

// updatePressureFeatures 更新压力特征
func (fe *ReversalFeatureEngine) updatePressureFeatures(snapshot *MarketSnapshot) {
	p := fe.pressure
	currentOFI := snapshot.OrderFlowImbalance

	// 更新历史
	p.ofiHistory = append(p.ofiHistory, currentOFI)
	if len(p.ofiHistory) > fe.config.OFIWindow {
		p.ofiHistory = p.ofiHistory[1:]
	}

	n := len(p.ofiHistory)
	if n < 3 {
		p.OFI = currentOFI
		return
	}

	// 基础指标
	p.OFI = currentOFI
	p.DeltaOFI = currentOFI - p.ofiHistory[n-2]
	p.AccelOFI = p.DeltaOFI - (p.ofiHistory[n-2] - p.ofiHistory[n-3])

	// 趋势指标
	startIdx := max(0, n-fe.config.TrendWindow)
	p.OFITrend = linearRegressionSlope(p.ofiHistory[startIdx:])

	if n >= fe.config.MomentumWindow {
		p.OFIMomentum = currentOFI - p.ofiHistory[n-fe.config.MomentumWindow]
	}

	p.OFIStdDev = standardDeviation(p.ofiHistory)

	// 比率指标
	maxOFI := maxAbs(p.ofiHistory)
	if maxOFI > 0 {
		p.OFIRatio = currentOFI / maxOFI
	}

	if p.OFIStdDev > 0 {
		p.DeltaOFIRatio = math.Abs(p.DeltaOFI) / p.OFIStdDev
	}
}

// updatePriceFeatures 更新价格特征
func (fe *ReversalFeatureEngine) updatePriceFeatures(snapshot *MarketSnapshot) {
	pr := fe.price
	midPrice := (snapshot.BestBid + snapshot.BestAsk) / 2
	spread := snapshot.BestAsk - snapshot.BestBid
	now := time.Now().UnixMilli()

	// Microprice 相关
	if spread > 0 {
		pr.MicroPriceDev = (snapshot.MicroPrice - midPrice) / spread
	}

	// 收益率计算
	if pr.lastPrice > 0 {
		ret := (midPrice - pr.lastPrice) / pr.lastPrice
		pr.priceHistory50 = append(pr.priceHistory50, ret)
		pr.priceHistory100 = append(pr.priceHistory100, ret)

		if len(pr.priceHistory50) > 50 {
			pr.priceHistory50 = pr.priceHistory50[1:]
		}
		if len(pr.priceHistory100) > 100 {
			pr.priceHistory100 = pr.priceHistory100[1:]
		}
	}

	// 计算窗口收益率
	if len(pr.priceHistory50) >= 1 {
		pr.Return50ms = pr.priceHistory50[len(pr.priceHistory50)-1]
	}
	if len(pr.priceHistory100) >= 2 {
		pr.Return100ms = pr.priceHistory50[len(pr.priceHistory50)-1] +
			pr.priceHistory50[len(pr.priceHistory50)-2]
	}

	// 收益率衰减
	if math.Abs(pr.Return100ms) > 1e-10 {
		pr.ReturnDecay = math.Abs(pr.Return50ms) / math.Abs(pr.Return100ms)
	}

	// 新高/新低检测
	if pr.highPrice == 0 || midPrice >= pr.highPrice {
		pr.highPrice = midPrice
		pr.NoNewHighDuration = 0
	} else {
		if pr.lastUpdateTime > 0 {
			pr.NoNewHighDuration += now - pr.lastUpdateTime
		}
	}

	if pr.lowPrice == 0 || midPrice <= pr.lowPrice {
		pr.lowPrice = midPrice
		pr.NoNewLowDuration = 0
	} else {
		if pr.lastUpdateTime > 0 {
			pr.NoNewLowDuration += now - pr.lastUpdateTime
		}
	}

	// 波动率
	if len(pr.priceHistory100) >= fe.config.VolatilityWindow {
		recent := pr.priceHistory100[len(pr.priceHistory100)-fe.config.VolatilityWindow:]
		pr.Volatility20 = standardDeviation(recent)

		if len(pr.priceHistory100) >= fe.config.VolatilityWindow*2 {
			longer := pr.priceHistory100[len(pr.priceHistory100)-fe.config.VolatilityWindow*2:]
			longVol := standardDeviation(longer)
			if longVol > 0 {
				pr.VolatilityRatio = pr.Volatility20 / longVol
			}
		}
	}

	pr.lastPrice = midPrice
	pr.lastUpdateTime = now
}

// updateLiquidityFeatures 更新流动性特征
func (fe *ReversalFeatureEngine) updateLiquidityFeatures(snapshot *MarketSnapshot) {
	l := fe.liquidity

	// 这里需要从订单簿获取数据
	// 简化版本：使用快照中的可用数据
	bidSize := 0.0
	askSize := 0.0

	// 如果有Bids/Asks数组，计算总挂单量
	if len(snapshot.Bids) > 0 {
		for _, level := range snapshot.Bids {
			bidSize += level.Quantity
		}
	}
	if len(snapshot.Asks) > 0 {
		for _, level := range snapshot.Asks {
			askSize += level.Quantity
		}
	}

	totalSize := bidSize + askSize
	if totalSize > 0 {
		l.BidAskImbalance = (bidSize - askSize) / totalSize
	}

	// 流动性变化
	if fe.liquidity.lastBidSize > 0 {
		l.BidSizeChange = (bidSize - fe.liquidity.lastBidSize) / fe.liquidity.lastBidSize
	}
	if fe.liquidity.lastAskSize > 0 {
		l.AskSizeChange = (askSize - fe.liquidity.lastAskSize) / fe.liquidity.lastAskSize
	}

	// 价差行为
	spread := snapshot.BestAsk - snapshot.BestBid
	l.Spread = spread

	if fe.liquidity.lastSpread > 0 {
		l.SpreadChange = spread - fe.liquidity.lastSpread
	}

	l.spreadHistory = append(l.spreadHistory, spread)
	if len(l.spreadHistory) > fe.config.TrendWindow {
		l.spreadHistory = l.spreadHistory[1:]
		l.SpreadTrend = linearRegressionSlope(l.spreadHistory)
	}

	fe.liquidity.lastBidSize = bidSize
	fe.liquidity.lastAskSize = askSize
	fe.liquidity.lastSpread = spread
}

// AddTrade 添加成交数据（用于计算吸收流）
func (fe *ReversalFeatureEngine) AddTrade(trade TradeTick) {
	fe.mu.Lock()
	defer fe.mu.Unlock()

	l := fe.liquidity
	l.tradesBuffer = append(l.tradesBuffer, trade)

	// 保持最近100笔成交
	if len(l.tradesBuffer) > 100 {
		l.tradesBuffer = l.tradesBuffer[1:]
	}

	// 计算大额成交占比
	largeVolume := 0.0
	totalVolume := 0.0
	for _, t := range l.tradesBuffer {
		totalVolume += t.Quantity
		if t.Quantity >= fe.config.LargeTradeThreshold {
			largeVolume += t.Quantity
		}
	}

	if totalVolume > 0 {
		l.LargeTradeRatio = largeVolume / totalVolume
	}

	// 成交强度 (每秒成交量)
	if len(l.tradesBuffer) >= 2 {
		timeSpan := l.tradesBuffer[len(l.tradesBuffer)-1].Timestamp.Sub(l.tradesBuffer[0].Timestamp).Milliseconds()
		if timeSpan > 0 {
			l.TradeIntensity = totalVolume / float64(timeSpan) * 1000 // 转换为每秒
		}
	}
}

// updateCompositeFeatures 更新复合特征
func (fe *ReversalFeatureEngine) updateCompositeFeatures() {
	c := &fe.composite
	p := fe.pressure
	pr := fe.price
	l := fe.liquidity

	// 1. 压力-价格背离
	if p.DeltaOFI != 0 && pr.Return50ms != 0 {
		// 如果OFI增加但价格下跌，或OFI减少但价格上涨，说明有背离
		c.PressurePriceDivergence = -mathSign(p.DeltaOFI) * mathSign(pr.Return50ms)
	}

	// 2. 流动性-价格效率 (简化：价格变动 / 成交强度)
	if l.TradeIntensity > 0 {
		c.LiquidityEfficiency = math.Abs(pr.Return50ms) / l.TradeIntensity
	}

	// 3. 市场韧性
	resilience := 0.0
	if pr.NoNewLowDuration > fe.config.NewLowThresholdMs {
		resilience += float64(pr.NoNewLowDuration) / 300.0 // 归一化到300ms
	}
	if pr.NoNewHighDuration > fe.config.NewHighThresholdMs {
		resilience += float64(pr.NoNewHighDuration) / 300.0
	}
	c.MarketResilience = math.Min(resilience, 1.0)

	// 4. 反转动量
	c.ReversalMomentum = pr.Return50ms * (1 - math.Abs(p.OFIRatio))
}

// GetAllFeatures 获取所有特征的副本
func (fe *ReversalFeatureEngine) GetAllFeatures() *AllReversalFeatures {
	fe.mu.RLock()
	defer fe.mu.RUnlock()

	return &AllReversalFeatures{
		Timestamp: time.Now().UnixNano(),
		Pressure:  *fe.pressure,
		Price:     *fe.price,
		Liquidity: *fe.liquidity,
		Composite: fe.composite,
	}
}

// GetPressureScore 计算压力得分 (0-1)
func (fe *ReversalFeatureEngine) GetPressureScore() float64 {
	fe.mu.RLock()
	defer fe.mu.RUnlock()

	p := fe.pressure
	score := 0.0

	// 条件1: OFI < 0 && DeltaOFI > 0 (卖压减弱)
	if p.OFI < 0 && p.DeltaOFI > 0 {
		score += 1.0
	}

	// 条件2: 加速度为正
	if p.AccelOFI > 0 {
		score += 0.5
	}

	// 条件3: 趋势反转
	if p.OFITrend > 0.1 {
		score += 0.5
	}

	return math.Min(score, 1.0)
}

// GetPriceScore 计算价格得分 (0-1)
func (fe *ReversalFeatureEngine) GetPriceScore() float64 {
	fe.mu.RLock()
	defer fe.mu.RUnlock()

	pr := fe.price
	score := 0.0

	// 1. Microprice 抗跌
	if pr.MicroPriceDev >= 0 {
		score += 1.0
	} else if pr.MicroPriceDev > -0.5 {
		score += 0.5
	}

	// 2. 未创新低持续时间
	if pr.NoNewLowDuration > fe.config.NewLowThresholdMs {
		durationScore := math.Min(float64(pr.NoNewLowDuration)/300.0, 1.0)
		score += durationScore
	}

	// 3. 收益率衰减
	if math.Abs(pr.Return50ms) < math.Abs(pr.Return100ms)*0.7 {
		score += 0.5
	}

	return math.Min(score, 1.0)
}

// GetLiquidityScore 计算流动性得分 (0-1)
func (fe *ReversalFeatureEngine) GetLiquidityScore() float64 {
	fe.mu.RLock()
	defer fe.mu.RUnlock()

	l := fe.liquidity
	score := 0.0

	// 1. 流动性改善 (价差缩小)
	if l.SpreadChange < 0 {
		score += 1.0
	}

	// 2. 大单吸收
	if l.AbsorptionFlow > 0 {
		score += 0.5
	}

	// 3. 流动性平衡
	if math.Abs(l.BidAskImbalance) < 0.3 {
		score += 0.5
	}

	return math.Min(score, 1.0)
}

// GetCombinedScore 计算综合得分
func (fe *ReversalFeatureEngine) GetCombinedScore() float64 {
	pressureScore := fe.GetPressureScore()
	priceScore := fe.GetPriceScore()
	liquidityScore := fe.GetLiquidityScore()

	return 0.4*pressureScore + 0.4*priceScore + 0.2*liquidityScore
}

// 辅助函数

func linearRegressionSlope(data []float64) float64 {
	n := float64(len(data))
	if n < 2 {
		return 0
	}

	var sumX, sumY, sumXY, sumX2 float64
	for i, y := range data {
		x := float64(i)
		sumX += x
		sumY += y
		sumXY += x * y
		sumX2 += x * x
	}

	denominator := n*sumX2 - sumX*sumX
	if math.Abs(denominator) < 1e-10 {
		return 0
	}

	return (n*sumXY - sumX*sumY) / denominator
}

func standardDeviation(data []float64) float64 {
	n := len(data)
	if n < 2 {
		return 0
	}

	var sum, sumSq float64
	for _, x := range data {
		sum += x
		sumSq += x * x
	}

	mean := sum / float64(n)
	variance := sumSq/float64(n) - mean*mean

	if variance < 0 {
		variance = 0
	}

	return math.Sqrt(variance)
}

func maxAbs(data []float64) float64 {
	maxVal := 0.0
	for _, x := range data {
		if math.Abs(x) > maxVal {
			maxVal = math.Abs(x)
		}
	}
	return maxVal
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func mathSign(x float64) float64 {
	if x > 0 {
		return 1
	} else if x < 0 {
		return -1
	}
	return 0
}
