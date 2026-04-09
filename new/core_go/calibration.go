package main

import (
	"context"
	"fmt"
	"math"
	"sort"
	"sync"
	"time"
)

// FillRecord 成交记录
type FillRecord struct {
	OrderID       string
	Symbol        string
	Side          string
	QueueRatio    float64
	PredictedRate float64 // 预测的λ
	ActualFillTime *float64 // 实际成交时间(秒), nil表示未成交
	Timestamp     time.Time
	OFI           float64
	SpreadBps     float64
}

// CalibrationMetrics 校准指标
type CalibrationMetrics struct {
	Symbol             string
	CalibrationFactor  float64
	PredictedMedian    float64
	ActualMedian       float64
	MSE                float64
	MAE                float64
	SampleSize         int
	LastUpdated        time.Time
}

// CalibrationEngine 实时成交率校准引擎
type CalibrationEngine struct {
	mu sync.RWMutex

	windowSize       int
	minSamples       int
	smoothingFactor  float64
	maxFactor        float64
	minFactor        float64

	// 按交易对存储成交记录
	fillRecords map[string][]FillRecord

	// 校准系数缓存
	calibrationFactors map[string]float64

	// 校准指标历史
	metricsHistory map[string][]CalibrationMetrics

	// 未成交订单跟踪
	pendingOrders map[string]*FillRecord
}

// NewCalibrationEngine 创建校准引擎
func NewCalibrationEngine() *CalibrationEngine {
	return &CalibrationEngine{
		windowSize:         1000,
		minSamples:         20,
		smoothingFactor:    0.9,
		maxFactor:          5.0,
		minFactor:          0.2,
		fillRecords:        make(map[string][]FillRecord),
		calibrationFactors: make(map[string]float64),
		metricsHistory:     make(map[string][]CalibrationMetrics),
		pendingOrders:      make(map[string]*FillRecord),
	}
}

// RecordPrediction 记录下单时的预测
func (c *CalibrationEngine) RecordPrediction(
	orderID, symbol, side string,
	queueRatio, predictedRate, ofi, spreadBps float64,
) {
	c.mu.Lock()
	defer c.mu.Unlock()

	record := &FillRecord{
		OrderID:       orderID,
		Symbol:        symbol,
		Side:          side,
		QueueRatio:    queueRatio,
		PredictedRate: predictedRate,
		Timestamp:     time.Now(),
		OFI:           ofi,
		SpreadBps:     spreadBps,
	}

	c.pendingOrders[orderID] = record
}

// RecordFill 记录订单成交
func (c *CalibrationEngine) RecordFill(orderID string, fillTime *time.Time) {
	c.mu.Lock()
	defer c.mu.Unlock()

	record, exists := c.pendingOrders[orderID]
	if !exists {
		return
	}
	delete(c.pendingOrders, orderID)

	if fillTime != nil {
		fillDuration := fillTime.Sub(record.Timestamp).Seconds()
		record.ActualFillTime = &fillDuration
	}

	// 存储到对应交易对的历史
	c.fillRecords[record.Symbol] = append(c.fillRecords[record.Symbol], *record)

	// 限制窗口大小
	if len(c.fillRecords[record.Symbol]) > c.windowSize {
		c.fillRecords[record.Symbol] = c.fillRecords[record.Symbol][1:]
	}

	// 触发校准更新
	c.updateCalibration(record.Symbol)
}

// updateCalibration 更新校准系数
func (c *CalibrationEngine) updateCalibration(symbol string) {
	records := c.fillRecords[symbol]

	if len(records) < c.minSamples {
		return
	}

	// 只使用已成交的订单
	var filledRecords []FillRecord
	for _, r := range records {
		if r.ActualFillTime != nil {
			filledRecords = append(filledRecords, r)
		}
	}

	if len(filledRecords) < c.minSamples/2 {
		return
	}

	// 提取预测值和实际值
	predictedRates := make([]float64, len(filledRecords))
	actualRates := make([]float64, len(filledRecords))

	for i, r := range filledRecords {
		predictedRates[i] = r.PredictedRate
		actualRates[i] = 1.0 / *r.ActualFillTime
	}

	// 计算中位数
	predictedMedian := median(predictedRates)
	actualMedian := median(actualRates)

	if predictedMedian < 1e-8 {
		return
	}

	// 计算新的校准系数
	rawFactor := actualMedian / predictedMedian
	rawFactor = math.Max(c.minFactor, math.Min(c.maxFactor, rawFactor))

	// 指数平滑
	oldFactor := c.calibrationFactors[symbol]
	if oldFactor == 0 {
		oldFactor = 1.0
	}
	newFactor := c.smoothingFactor*oldFactor + (1-c.smoothingFactor)*rawFactor
	c.calibrationFactors[symbol] = newFactor

	// 计算误差指标
	calibratedRates := make([]float64, len(predictedRates))
	for i, p := range predictedRates {
		calibratedRates[i] = p * newFactor
	}

	mse := calculateMSE(calibratedRates, actualRates)
	mae := calculateMAE(calibratedRates, actualRates)

	// 保存指标
	metrics := CalibrationMetrics{
		Symbol:            symbol,
		CalibrationFactor: newFactor,
		PredictedMedian:   predictedMedian,
		ActualMedian:      actualMedian,
		MSE:               mse,
		MAE:               mae,
		SampleSize:        len(filledRecords),
		LastUpdated:       time.Now(),
	}

	c.metricsHistory[symbol] = append(c.metricsHistory[symbol], metrics)

	// 限制历史大小
	if len(c.metricsHistory[symbol]) > 100 {
		c.metricsHistory[symbol] = c.metricsHistory[symbol][1:]
	}
}

// GetCalibrationFactor 获取校准系数
func (c *CalibrationEngine) GetCalibrationFactor(symbol string) float64 {
	c.mu.RLock()
	defer c.mu.RUnlock()

	factor := c.calibrationFactors[symbol]
	if factor == 0 {
		return 1.0
	}
	return factor
}

// GetCalibratedRate 校准危险率
func (c *CalibrationEngine) GetCalibratedRate(rawRate float64, symbol string) float64 {
	factor := c.GetCalibrationFactor(symbol)
	calibrated := rawRate * factor

	// 硬边界保护
	calibrated = math.Max(calibrated, 0.001)
	calibrated = math.Min(calibrated, 10.0)

	return calibrated
}

// GetCalibrationReport 获取校准报告
func (c *CalibrationEngine) GetCalibrationReport(symbol string) map[string]interface{} {
	c.mu.RLock()
	defer c.mu.RUnlock()

	records := c.fillRecords[symbol]
	if len(records) == 0 {
		return map[string]interface{}{
			"error": fmt.Sprintf("No data for %s", symbol),
		}
	}

	filled := 0
	for _, r := range records {
		if r.ActualFillTime != nil {
			filled++
		}
	}

	report := map[string]interface{}{
		"symbol":             symbol,
		"total_orders":       len(records),
		"filled_orders":      filled,
		"fill_rate":          float64(filled) / float64(len(records)),
		"calibration_factor": c.calibrationFactors[symbol],
	}

	if history, ok := c.metricsHistory[symbol]; ok && len(history) > 0 {
		latest := history[len(history)-1]
		report["latest_metrics"] = map[string]interface{}{
			"mse":             latest.MSE,
			"mae":             latest.MAE,
			"predicted_median": latest.PredictedMedian,
			"actual_median":   latest.ActualMedian,
			"sample_size":     latest.SampleSize,
		}
	}

	return report
}

// IsCalibrationReliable 判断校准是否可靠
func (c *CalibrationEngine) IsCalibrationReliable(symbol string) bool {
	c.mu.RLock()
	defer c.mu.RUnlock()

	history := c.metricsHistory[symbol]
	if len(history) == 0 {
		return false
	}

	latest := history[len(history)-1]

	// 样本数检查
	if latest.SampleSize < c.minSamples {
		return false
	}

	// 误差检查（MAE不应超过预测中位数的50%）
	if latest.MAE > latest.PredictedMedian*0.5 {
		return false
	}

	return true
}

// Reset 重置校准数据
func (c *CalibrationEngine) Reset(symbol string) {
	c.mu.Lock()
	defer c.mu.Unlock()

	if symbol == "" {
		c.fillRecords = make(map[string][]FillRecord)
		c.calibrationFactors = make(map[string]float64)
		c.metricsHistory = make(map[string][]CalibrationMetrics)
		c.pendingOrders = make(map[string]*FillRecord)
	} else {
		delete(c.fillRecords, symbol)
		delete(c.calibrationFactors, symbol)
		delete(c.metricsHistory, symbol)
	}
}

// Helper functions

func median(values []float64) float64 {
	if len(values) == 0 {
		return 0
	}

	sorted := make([]float64, len(values))
	copy(sorted, values)
	sort.Float64s(sorted)

	n := len(sorted)
	if n%2 == 0 {
		return (sorted[n/2-1] + sorted[n/2]) / 2
	}
	return sorted[n/2]
}

func calculateMSE(predicted, actual []float64) float64 {
	if len(predicted) != len(actual) || len(predicted) == 0 {
		return 0
	}

	var sum float64
	for i := range predicted {
		diff := predicted[i] - actual[i]
		sum += diff * diff
	}
	return sum / float64(len(predicted))
}

func calculateMAE(predicted, actual []float64) float64 {
	if len(predicted) != len(actual) || len(predicted) == 0 {
		return 0
	}

	var sum float64
	for i := range predicted {
		sum += math.Abs(predicted[i] - actual[i])
	}
	return sum / float64(len(predicted))
}

// CalibrationService 校准服务（用于集成到引擎）
type CalibrationService struct {
	engine *CalibrationEngine
}

// NewCalibrationService 创建校准服务
func NewCalibrationService() *CalibrationService {
	return &CalibrationService{
		engine: NewCalibrationEngine(),
	}
}

// Start 启动校准服务
func (s *CalibrationService) Start(ctx context.Context) error {
	// 可以在这里启动定期清理任务
	return nil
}

// Stop 停止校准服务
func (s *CalibrationService) Stop() error {
	return nil
}

// RecordOrder 记录订单预测
func (s *CalibrationService) RecordOrder(
	orderID, symbol, side string,
	queueRatio, predictedRate, ofi, spreadBps float64,
) {
	s.engine.RecordPrediction(orderID, symbol, side, queueRatio, predictedRate, ofi, spreadBps)
}

// RecordFill 记录订单成交
func (s *CalibrationService) RecordFill(orderID string, fillTime *time.Time) {
	s.engine.RecordFill(orderID, fillTime)
}

// GetCalibratedHazardRate 获取校准后的危险率
func (s *CalibrationService) GetCalibratedHazardRate(rawRate float64, symbol string) float64 {
	return s.engine.GetCalibratedRate(rawRate, symbol)
}

// GetReport 获取校准报告
func (s *CalibrationService) GetReport(symbol string) map[string]interface{} {
	return s.engine.GetCalibrationReport(symbol)
}

// IsReliable 检查校准是否可靠
func (s *CalibrationService) IsReliable(symbol string) bool {
	return s.engine.IsCalibrationReliable(symbol)
}
