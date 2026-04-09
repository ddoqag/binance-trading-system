// replay_engine.go - 确定性重放系统
//
// 功能:
// - 记录市场数据和系统事件到日志文件
// - 支持按时间戳精确重放
// - 用于调试和回归测试

package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"time"
)

// EventType 事件类型
type EventType string

const (
	EventTypeMarketData EventType = "market_data" // 市场数据
	EventTypeSignal     EventType = "signal"      // 交易信号
	EventTypeOrder      EventType = "order"       // 订单事件
	EventTypePosition   EventType = "position"    // 仓位变化
	EventTypeRisk       EventType = "risk"        // 风控事件
	EventTypeSystem     EventType = "system"      // 系统事件
)

// Event 通用事件接口
type Event interface {
	GetTimestamp() time.Time
	GetType() EventType
	GetSequence() uint64
}

// BaseEvent 基础事件结构
type BaseEvent struct {
	Timestamp time.Time `json:"timestamp"`
	Type      EventType `json:"type"`
	Sequence  uint64    `json:"sequence"`
}

func (e BaseEvent) GetTimestamp() time.Time { return e.Timestamp }
func (e BaseEvent) GetType() EventType      { return e.Type }
func (e BaseEvent) GetSequence() uint64     { return e.Sequence }

// MarketDataEvent 市场数据事件
type MarketDataEvent struct {
	BaseEvent
	Symbol    string  `json:"symbol"`
	BidPrice  float64 `json:"bid_price"`
	AskPrice  float64 `json:"ask_price"`
	BidQty    float64 `json:"bid_qty"`
	AskQty    float64 `json:"ask_qty"`
	TradePrice float64 `json:"trade_price,omitempty"`
	TradeQty  float64 `json:"trade_qty,omitempty"`
	OFI       float64 `json:"ofi,omitempty"`
}

// SignalEvent 信号事件
type SignalEvent struct {
	BaseEvent
	Signal    float64 `json:"signal"`     // -1.0 ~ 1.0
	Strength  float64 `json:"strength"`   // 0.0 ~ 1.0
	Direction string  `json:"direction"`  // "buy", "sell", "hold"
	Reason    string  `json:"reason"`
}

// OrderEvent 订单事件
type OrderEvent struct {
	BaseEvent
	OrderID   string  `json:"order_id"`
	Side      string  `json:"side"`       // "buy", "sell"
	Qty       float64 `json:"qty"`
	Price     float64 `json:"price"`
	OrderType string  `json:"order_type"` // "limit", "market"
}

// PositionEvent 仓位事件
type PositionEvent struct {
	BaseEvent
	PositionSize float64 `json:"position_size"`
	EntryPrice   float64 `json:"entry_price"`
	UnrealizedPnL float64 `json:"unrealized_pnl"`
}

// RiskEvent 风控事件
type RiskEvent struct {
	BaseEvent
	RiskType    string  `json:"risk_type"`
	Level       string  `json:"level"`      // "warning", "critical"
	Description string  `json:"description"`
}

// SystemEvent 系统事件
type SystemEvent struct {
	BaseEvent
	Component string `json:"component"`
	Action    string `json:"action"`
	Status    string `json:"status"`
}

// EventLog 事件日志条目
type EventLog struct {
	Timestamp int64           `json:"ts"`
	Type      EventType       `json:"type"`
	Sequence  uint64          `json:"seq"`
	Data      json.RawMessage `json:"data"`
}

// ReplayEngine 确定性重放引擎
type ReplayEngine struct {
	mu sync.RWMutex

	// 配置
	config ReplayConfig

	// 记录状态
	isRecording bool
	recordFile  *os.File
	recordWriter *bufio.Writer
	sequence    uint64

	// 重放状态
	isReplaying  bool
	events       []EventLog
	currentIndex int
	replaySpeed  float64 // 1.0 = 正常速度, 2.0 = 2倍速, 0.5 = 0.5倍速

	// 回调
	handlers map[EventType][]func(Event)

	// 统计
	stats ReplayStats
}

// ReplayConfig 重放引擎配置
type ReplayConfig struct {
	LogDir      string        // 日志目录
	BufferSize  int           // 缓冲区大小
	MaxFileSize int64         // 最大文件大小 (MB)
	Compression bool          // 是否压缩
}

// ReplayStats 重放统计
type ReplayStats struct {
	EventsRecorded   uint64
	EventsReplayed   uint64
	StartTime        time.Time
	EndTime          time.Time
	Duration         time.Duration
	SkippedEvents    uint64
	ProcessedEvents  uint64
}

// NewReplayEngine 创建重放引擎
func NewReplayEngine(config ReplayConfig) *ReplayEngine {
	if config.BufferSize == 0 {
		config.BufferSize = 4096
	}
	if config.MaxFileSize == 0 {
		config.MaxFileSize = 100 // 100MB
	}

	return &ReplayEngine{
		config:      config,
		handlers:    make(map[EventType][]func(Event)),
		replaySpeed: 1.0,
	}
}

// StartRecording 开始记录
func (re *ReplayEngine) StartRecording(sessionName string) error {
	re.mu.Lock()
	defer re.mu.Unlock()

	if re.isRecording {
		return fmt.Errorf("already recording")
	}

	// 创建日志目录
	if err := os.MkdirAll(re.config.LogDir, 0755); err != nil {
		return fmt.Errorf("failed to create log dir: %w", err)
	}

	// 创建日志文件
	timestamp := time.Now().Format("20060102_150405")
	filename := fmt.Sprintf("%s_%s.log", sessionName, timestamp)
	filepath := filepath.Join(re.config.LogDir, filename)

	file, err := os.Create(filepath)
	if err != nil {
		return fmt.Errorf("failed to create log file: %w", err)
	}

	re.recordFile = file
	re.recordWriter = bufio.NewWriterSize(file, re.config.BufferSize)
	re.isRecording = true
	re.sequence = 0
	re.stats = ReplayStats{StartTime: time.Now()}

	log.Printf("[ReplayEngine] Started recording to %s", filepath)
	return nil
}

// StopRecording 停止记录
func (re *ReplayEngine) StopRecording() error {
	re.mu.Lock()
	defer re.mu.Unlock()

	if !re.isRecording {
		return nil
	}

	// 刷新缓冲区
	if err := re.recordWriter.Flush(); err != nil {
		return fmt.Errorf("failed to flush buffer: %w", err)
	}

	// 关闭文件
	if err := re.recordFile.Close(); err != nil {
		return fmt.Errorf("failed to close file: %w", err)
	}

	re.isRecording = false
	re.stats.EndTime = time.Now()
	re.stats.Duration = re.stats.EndTime.Sub(re.stats.StartTime)

	log.Printf("[ReplayEngine] Stopped recording. Events: %d, Duration: %v",
		re.stats.EventsRecorded, re.stats.Duration)
	return nil
}

// RecordEvent 记录事件
func (re *ReplayEngine) RecordEvent(event Event) error {
	re.mu.Lock()
	defer re.mu.Unlock()

	if !re.isRecording {
		return fmt.Errorf("not recording")
	}

	// 序列化事件数据
	data, err := json.Marshal(event)
	if err != nil {
		return fmt.Errorf("failed to marshal event: %w", err)
	}

	// 创建日志条目
	logEntry := EventLog{
		Timestamp: event.GetTimestamp().UnixNano(),
		Type:      event.GetType(),
		Sequence:  event.GetSequence(),
		Data:      data,
	}

	// 序列化日志条目
	logLine, err := json.Marshal(logEntry)
	if err != nil {
		return fmt.Errorf("failed to marshal log entry: %w", err)
	}

	// 写入文件
	if _, err := re.recordWriter.Write(logLine); err != nil {
		return fmt.Errorf("failed to write log: %w", err)
	}
	if _, err := re.recordWriter.WriteString("\n"); err != nil {
		return fmt.Errorf("failed to write newline: %w", err)
	}

	re.sequence++
	re.stats.EventsRecorded++

	// 定期刷新
	if re.stats.EventsRecorded%1000 == 0 {
		re.recordWriter.Flush()
	}

	return nil
}

// LoadRecording 加载记录文件
func (re *ReplayEngine) LoadRecording(filepath string) error {
	re.mu.Lock()
	defer re.mu.Unlock()

	file, err := os.Open(filepath)
	if err != nil {
		return fmt.Errorf("failed to open file: %w", err)
	}
	defer file.Close()

	re.events = make([]EventLog, 0)
	scanner := bufio.NewScanner(file)

	for scanner.Scan() {
		var logEntry EventLog
		if err := json.Unmarshal(scanner.Bytes(), &logEntry); err != nil {
			log.Printf("[ReplayEngine] Failed to unmarshal line: %v", err)
			continue
		}
		re.events = append(re.events, logEntry)
	}

	if err := scanner.Err(); err != nil {
		return fmt.Errorf("failed to scan file: %w", err)
	}

	// 按时间戳排序
	sort.Slice(re.events, func(i, j int) bool {
		return re.events[i].Timestamp < re.events[j].Timestamp
	})

	re.currentIndex = 0
	log.Printf("[ReplayEngine] Loaded %d events from %s", len(re.events), filepath)
	return nil
}

// StartReplay 开始重放
func (re *ReplayEngine) StartReplay(speed float64) error {
	re.mu.Lock()
	defer re.mu.Unlock()

	if re.isReplaying {
		return fmt.Errorf("already replaying")
	}

	if len(re.events) == 0 {
		return fmt.Errorf("no events loaded")
	}

	re.isReplaying = true
	re.replaySpeed = speed
	re.currentIndex = 0
	re.stats = ReplayStats{
		StartTime: time.Now(),
	}

	log.Printf("[ReplayEngine] Starting replay with speed %.2fx, events: %d", speed, len(re.events))

	// 启动重放循环
	go re.replayLoop()

	return nil
}

// StopReplay 停止重放
func (re *ReplayEngine) StopReplay() {
	re.mu.Lock()
	defer re.mu.Unlock()

	re.isReplaying = false
	re.stats.EndTime = time.Now()
	re.stats.Duration = re.stats.EndTime.Sub(re.stats.StartTime)

	log.Printf("[ReplayEngine] Stopped replay. Events: %d/%d, Duration: %v",
		re.stats.EventsReplayed, len(re.events), re.stats.Duration)
}

// replayLoop 重放循环
func (re *ReplayEngine) replayLoop() {
	if len(re.events) == 0 {
		return
	}

	startTime := time.Now()
	firstEventTime := time.Unix(0, re.events[0].Timestamp)

	for re.isReplaying && re.currentIndex < len(re.events) {
		event := re.events[re.currentIndex]
		eventTime := time.Unix(0, event.Timestamp)

		// 计算等待时间
		timeDiff := eventTime.Sub(firstEventTime)
		waitDuration := time.Duration(float64(timeDiff) / re.replaySpeed)
		targetTime := startTime.Add(waitDuration)

		// 等待直到目标时间
		now := time.Now()
		if targetTime.After(now) {
			time.Sleep(targetTime.Sub(now))
		}

		// 处理事件
		re.processEvent(event)

		re.mu.Lock()
		re.currentIndex++
		re.stats.EventsReplayed++
		re.mu.Unlock()
	}

	re.StopReplay()
}

// processEvent 处理单个事件
func (re *ReplayEngine) processEvent(logEntry EventLog) {
	// 反序列化事件
	var event Event
	switch logEntry.Type {
	case EventTypeMarketData:
		var e MarketDataEvent
		if err := json.Unmarshal(logEntry.Data, &e); err == nil {
			event = e
		}
	case EventTypeSignal:
		var e SignalEvent
		if err := json.Unmarshal(logEntry.Data, &e); err == nil {
			event = e
		}
	case EventTypeOrder:
		var e OrderEvent
		if err := json.Unmarshal(logEntry.Data, &e); err == nil {
			event = e
		}
	case EventTypePosition:
		var e PositionEvent
		if err := json.Unmarshal(logEntry.Data, &e); err == nil {
			event = e
		}
	case EventTypeRisk:
		var e RiskEvent
		if err := json.Unmarshal(logEntry.Data, &e); err == nil {
			event = e
		}
	case EventTypeSystem:
		var e SystemEvent
		if err := json.Unmarshal(logEntry.Data, &e); err == nil {
			event = e
		}
	}

	if event == nil {
		re.mu.Lock()
		re.stats.SkippedEvents++
		re.mu.Unlock()
		return
	}

	// 调用处理器
	re.mu.RLock()
	handlers := re.handlers[logEntry.Type]
	re.mu.RUnlock()

	for _, handler := range handlers {
		handler(event)
	}

	re.mu.Lock()
	re.stats.ProcessedEvents++
	re.mu.Unlock()
}

// RegisterHandler 注册事件处理器
func (re *ReplayEngine) RegisterHandler(eventType EventType, handler func(Event)) {
	re.mu.Lock()
	defer re.mu.Unlock()

	re.handlers[eventType] = append(re.handlers[eventType], handler)
}

// GetStats 获取统计信息
func (re *ReplayEngine) GetStats() ReplayStats {
	re.mu.RLock()
	defer re.mu.RUnlock()

	return re.stats
}

// IsRecording 是否正在记录
func (re *ReplayEngine) IsRecording() bool {
	re.mu.RLock()
	defer re.mu.RUnlock()

	return re.isRecording
}

// IsReplaying 是否正在重放
func (re *ReplayEngine) IsReplaying() bool {
	re.mu.RLock()
	defer re.mu.RUnlock()

	return re.isReplaying
}

// Seek 跳转到指定时间
func (re *ReplayEngine) Seek(targetTime time.Time) error {
	re.mu.Lock()
	defer re.mu.Unlock()

	if re.isReplaying {
		return fmt.Errorf("cannot seek while replaying")
	}

	targetNano := targetTime.UnixNano()

	// 二分查找
	idx := sort.Search(len(re.events), func(i int) bool {
		return re.events[i].Timestamp >= targetNano
	})

	re.currentIndex = idx
	log.Printf("[ReplayEngine] Seeked to index %d (time: %v)", idx, targetTime)
	return nil
}

// ListRecordings 列出所有记录文件
func (re *ReplayEngine) ListRecordings() ([]string, error) {
	entries, err := os.ReadDir(re.config.LogDir)
	if err != nil {
		return nil, fmt.Errorf("failed to read log dir: %w", err)
	}

	var files []string
	for _, entry := range entries {
		if !entry.IsDir() && filepath.Ext(entry.Name()) == ".log" {
			files = append(files, entry.Name())
		}
	}

	return files, nil
}

// CreateMarketDataEvent 创建市场数据事件
func CreateMarketDataEvent(symbol string, bid, ask, bidQty, askQty float64) MarketDataEvent {
	return MarketDataEvent{
		BaseEvent: BaseEvent{
			Timestamp: time.Now(),
			Type:      EventTypeMarketData,
		},
		Symbol:   symbol,
		BidPrice: bid,
		AskPrice: ask,
		BidQty:   bidQty,
		AskQty:   askQty,
	}
}

// CreateSignalEvent 创建信号事件
func CreateSignalEvent(signal, strength float64, direction, reason string) SignalEvent {
	return SignalEvent{
		BaseEvent: BaseEvent{
			Timestamp: time.Now(),
			Type:      EventTypeSignal,
		},
		Signal:    signal,
		Strength:  strength,
		Direction: direction,
		Reason:    reason,
	}
}

// CreateOrderEvent 创建订单事件
func CreateOrderEvent(orderID, side string, qty, price float64, orderType string) OrderEvent {
	return OrderEvent{
		BaseEvent: BaseEvent{
			Timestamp: time.Now(),
			Type:      EventTypeOrder,
		},
		OrderID:   orderID,
		Side:      side,
		Qty:       qty,
		Price:     price,
		OrderType: orderType,
	}
}

// CreatePositionEvent 创建仓位事件
func CreatePositionEvent(positionSize, entryPrice, unrealizedPnL float64) PositionEvent {
	return PositionEvent{
		BaseEvent: BaseEvent{
			Timestamp: time.Now(),
			Type:      EventTypePosition,
		},
		PositionSize:  positionSize,
		EntryPrice:    entryPrice,
		UnrealizedPnL: unrealizedPnL,
	}
}

// CreateRiskEvent 创建风控事件
func CreateRiskEvent(riskType, level, description string) RiskEvent {
	return RiskEvent{
		BaseEvent: BaseEvent{
			Timestamp: time.Now(),
			Type:      EventTypeRisk,
		},
		RiskType:    riskType,
		Level:       level,
		Description: description,
	}
}

// CreateSystemEvent 创建系统事件
func CreateSystemEvent(component, action, status string) SystemEvent {
	return SystemEvent{
		BaseEvent: BaseEvent{
			Timestamp: time.Now(),
			Type:      EventTypeSystem,
		},
		Component: component,
		Action:    action,
		Status:    status,
	}
}

// Test main function
func main_replay() {
	fmt.Println("ReplayEngine test - this is a library, import and use in your application")
}
