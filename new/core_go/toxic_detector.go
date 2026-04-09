package main

import (
	"container/ring"
	"math"
	"sync"
	"time"
)

// ToxicDetector 毒流检测器
type ToxicDetector struct {
	mu               sync.RWMutex
	windowSize       int
	tradeBuffer      *ring.Ring
	tickBuffer       *ring.Ring
	lastToxicScore   float64
	lastToxicSide    MarketSide
	lastUpdateTime   time.Time
	config           ToxicConfig
	history          []ToxicDetection
	detectionCount   int
}

// ToxicConfig 毒流检测配置
type ToxicConfig struct {
	ToxicThresholdHigh   float64
	ToxicThresholdMed    float64
	WindowSize           int
	MinTradesForDetect   int
	VolatilityThreshold  float64
	OFIThreshold         float64
	BurstThreshold       int
}

// DefaultToxicConfig 返回默认配置
func DefaultToxicConfig() ToxicConfig {
	return ToxicConfig{
		ToxicThresholdHigh:   0.8,
		ToxicThresholdMed:    0.6,
		WindowSize:           100,
		MinTradesForDetect:   10,
		VolatilityThreshold:  0.5,
		OFIThreshold:         0.6,
		BurstThreshold:       5,
	}
}

// TradeTick 交易记录
type TradeTick struct {
	Timestamp time.Time
	Side      string  // "buy" or "sell"
	Price     float64
	Quantity  float64
	IsMaker   bool
}

// MarketTick 市场数据
type MarketTick struct {
	Timestamp time.Time
	MidPrice  float64
	BidPrice  float64
	AskPrice  float64
	BidQty    float64
	AskQty    float64
}

// ToxicDetection 毒流检测结果
type ToxicDetection struct {
	Timestamp    time.Time
	ToxicScore   float64
	ToxicSide    MarketSide
	OFI          float64
	Burst        float64
	Volatility   float64
	FlowImbalance float64
}

// NewToxicDetector 创建毒流检测器
func NewToxicDetector(config ToxicConfig) *ToxicDetector {
	return &ToxicDetector{
		windowSize:     config.WindowSize,
		tradeBuffer:    ring.New(config.WindowSize * 2),
		tickBuffer:     ring.New(config.WindowSize),
		config:         config,
		history:        make([]ToxicDetection, 0, 1000),
		lastToxicSide:  SideNeutral,
		lastUpdateTime: time.Now(),
	}
}

// AddTrade 添加交易记录
func (td *ToxicDetector) AddTrade(trade TradeTick) {
	td.mu.Lock()
	defer td.mu.Unlock()

	td.tradeBuffer.Value = trade
	td.tradeBuffer = td.tradeBuffer.Next()
	td.lastUpdateTime = time.Now()
}

// AddMarketTick 添加市场数据
func (td *ToxicDetector) AddMarketTick(tick MarketTick) {
	td.mu.Lock()
	defer td.mu.Unlock()

	td.tickBuffer.Value = tick
	td.tickBuffer = td.tickBuffer.Next()
	td.lastUpdateTime = time.Now()
}

// Detect 执行毒流检测
func (td *ToxicDetector) Detect() ToxicDetection {
	td.mu.Lock()
	defer td.mu.Unlock()

	// 获取窗口数据
	trades := td.getTradesFromBuffer()
	if len(trades) < td.config.MinTradesForDetect {
		return ToxicDetection{
			Timestamp:  time.Now(),
			ToxicScore: 0,
			ToxicSide:  SideNeutral,
		}
	}

	// 1. 计算订单流不平衡 (OFI)
	ofi := td.calculateOFI(trades)

	// 2. 计算成交爆发
	burst := td.calculateBurst(trades)

	// 3. 计算短期波动率
	volatility := td.calculateVolatility()

	// 4. 计算大额成交比例
	largeTradeRatio := td.calculateLargeTradeRatio(trades)

	// 5. 计算买卖压力不平衡
	flowImbalance := td.calculateFlowImbalance(trades)

	// 6. 计算综合毒流分数
	toxicScore := td.calculateToxicScore(ofi, burst, volatility, largeTradeRatio, flowImbalance)

	// 7. 确定毒流方向
	toxicSide := td.determineToxicSide(ofi, flowImbalance)

	detection := ToxicDetection{
		Timestamp:     time.Now(),
		ToxicScore:    toxicScore,
		ToxicSide:     toxicSide,
		OFI:           ofi,
		Burst:         burst,
		Volatility:    volatility,
		FlowImbalance: flowImbalance,
	}

	td.lastToxicScore = toxicScore
	td.lastToxicSide = toxicSide
	td.detectionCount++

	// 保存历史（保持最近1000条）
	td.history = append(td.history, detection)
	if len(td.history) > 1000 {
		td.history = td.history[len(td.history)-1000:]
	}

	return detection
}

// calculateOFI 计算订单流不平衡
func (td *ToxicDetector) calculateOFI(trades []TradeTick) float64 {
	if len(trades) == 0 {
		return 0
	}

	var buyVolume, sellVolume float64
	for _, trade := range trades {
		if trade.Side == "buy" {
			buyVolume += trade.Quantity
		} else {
			sellVolume += trade.Quantity
		}
	}

	totalVolume := buyVolume + sellVolume
	if totalVolume == 0 {
		return 0
	}

	return (buyVolume - sellVolume) / totalVolume
}

// calculateBurst 计算成交爆发度
func (td *ToxicDetector) calculateBurst(trades []TradeTick) float64 {
	if len(trades) < 2 {
		return 0
	}

	// 计算最近N笔交易的时间间隔
	recentTrades := td.getRecentTrades(trades, 20)
	if len(recentTrades) < 2 {
		return 0
	}

	// 计算平均间隔
	var intervals []time.Duration
	for i := 1; i < len(recentTrades); i++ {
		interval := recentTrades[i].Timestamp.Sub(recentTrades[i-1].Timestamp)
		intervals = append(intervals, interval)
	}

	if len(intervals) == 0 {
		return 0
	}

	// 计算平均间隔
	var totalInterval time.Duration
	for _, iv := range intervals {
		totalInterval += iv
	}
	avgInterval := totalInterval / time.Duration(len(intervals))

	// 根据平均间隔计算爆发度
	if avgInterval < 10*time.Millisecond {
		return 1.0
	} else if avgInterval < 50*time.Millisecond {
		return 0.8
	} else if avgInterval < 100*time.Millisecond {
		return 0.6
	} else if avgInterval < 200*time.Millisecond {
		return 0.4
	} else if avgInterval < 500*time.Millisecond {
		return 0.2
	}

	return 0
}

// calculateVolatility 计算短期波动率
func (td *ToxicDetector) calculateVolatility() float64 {
	prices := td.getPricesFromBuffer()
	if len(prices) < 2 {
		return 0
	}

	// 计算对数收益率
	returns := make([]float64, 0, len(prices)-1)
	for i := 1; i < len(prices); i++ {
		if prices[i-1] > 0 {
			ret := math.Log(prices[i] / prices[i-1])
			returns = append(returns, ret)
		}
	}

	if len(returns) == 0 {
		return 0
	}

	// 计算标准差
	mean := 0.0
	for _, r := range returns {
		mean += r
	}
	mean /= float64(len(returns))

	variance := 0.0
	for _, r := range returns {
		diff := r - mean
		variance += diff * diff
	}
	variance /= float64(len(returns))

	volatility := math.Sqrt(variance) * 100 // 转换为百分比

	// 归一化到0-1
	return math.Min(1.0, volatility*10)
}

// calculateLargeTradeRatio 计算大额成交比例
func (td *ToxicDetector) calculateLargeTradeRatio(trades []TradeTick) float64 {
	if len(trades) == 0 {
		return 0
	}

	// 计算平均成交量
	var avgQty float64
	for _, t := range trades {
		avgQty += t.Quantity
	}
	avgQty /= float64(len(trades))

	// 计算超过平均值2倍的交易比例
	var largeCount int
	for _, t := range trades {
		if t.Quantity > avgQty*2 {
			largeCount++
		}
	}

	return float64(largeCount) / float64(len(trades))
}

// calculateFlowImbalance 计算买卖压力不平衡
func (td *ToxicDetector) calculateFlowImbalance(trades []TradeTick) float64 {
	if len(trades) == 0 {
		return 0
	}

	var buyPressure, sellPressure float64
	for _, t := range trades {
		value := t.Price * t.Quantity
		if t.Side == "buy" {
			buyPressure += value
		} else {
			sellPressure += value
		}
	}

	totalPressure := buyPressure + sellPressure
	if totalPressure == 0 {
		return 0
	}

	return (buyPressure - sellPressure) / totalPressure
}

// calculateToxicScore 计算综合毒流分数
func (td *ToxicDetector) calculateToxicScore(ofi, burst, volatility, largeRatio, flowImb float64) float64 {
	// 加权组合
	score := 0.30*math.Abs(ofi) +
		0.25*burst +
		0.20*volatility +
		0.15*largeRatio +
		0.10*math.Abs(flowImb)

	return math.Min(1.0, score)
}

// determineToxicSide 确定毒流方向
func (td *ToxicDetector) determineToxicSide(ofi, flowImbalance float64) MarketSide {
	combined := 0.6*ofi + 0.4*flowImbalance

	if combined > td.config.OFIThreshold {
		return SideBuyPressure
	} else if combined < -td.config.OFIThreshold {
		return SideSellPressure
	}

	return SideNeutral
}

// getTradesFromBuffer 从缓冲区获取交易
func (td *ToxicDetector) getTradesFromBuffer() []TradeTick {
	var trades []TradeTick

	td.tradeBuffer.Do(func(p interface{}) {
		if p != nil {
			if trade, ok := p.(TradeTick); ok {
				trades = append(trades, trade)
			}
		}
	})

	return trades
}

// getPricesFromBuffer 从缓冲区获取价格
func (td *ToxicDetector) getPricesFromBuffer() []float64 {
	var prices []float64

	td.tickBuffer.Do(func(p interface{}) {
		if p != nil {
			if tick, ok := p.(MarketTick); ok {
				prices = append(prices, tick.MidPrice)
			}
		}
	})

	return prices
}

// getRecentTrades 获取最近N笔交易
func (td *ToxicDetector) getRecentTrades(trades []TradeTick, n int) []TradeTick {
	if len(trades) <= n {
		return trades
	}
	return trades[len(trades)-n:]
}

// GetCurrentState 获取当前毒流状态
func (td *ToxicDetector) GetCurrentState() ToxicDetection {
	td.mu.RLock()
	defer td.mu.RUnlock()

	return ToxicDetection{
		Timestamp:  td.lastUpdateTime,
		ToxicScore: td.lastToxicScore,
		ToxicSide:  td.lastToxicSide,
	}
}

// GetHistory 获取检测历史
func (td *ToxicDetector) GetHistory() []ToxicDetection {
	td.mu.RLock()
	defer td.mu.RUnlock()

	history := make([]ToxicDetection, len(td.history))
	copy(history, td.history)
	return history
}

// IsToxic 检查当前是否毒流
func (td *ToxicDetector) IsToxic() bool {
	td.mu.RLock()
	defer td.mu.RUnlock()

	return td.lastToxicScore > td.config.ToxicThresholdHigh
}

// GetDetectionCount 获取检测次数
func (td *ToxicDetector) GetDetectionCount() int {
	td.mu.RLock()
	defer td.mu.RUnlock()

	return td.detectionCount
}

// Reset 重置检测器
func (td *ToxicDetector) Reset() {
	td.mu.Lock()
	defer td.mu.Unlock()

	td.tradeBuffer = ring.New(td.config.WindowSize * 2)
	td.tickBuffer = ring.New(td.config.WindowSize)
	td.lastToxicScore = 0
	td.lastToxicSide = SideNeutral
	td.history = td.history[:0]
	td.detectionCount = 0
}
