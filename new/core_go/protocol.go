// protocol.go
// Go 端共享内存协议定义
// 对应 shared/protocol.h
//
// 遵循 packing 保证内存布局一致

package main

import (
	"encoding/binary"
	"math"
	"sync/atomic"
	"time"
)

// 魔数和版本
const (
	HFTProtocolMagic   uint32 = 0x48465453 // "HFTS"
	HFTProtocolVersion uint32 = 1
	HFTMaxOrderBookDepth   = 20
	HFTMaxOrders           = 64
	HFTShmSizeDefault      = 64 * 1024 * 1024 // 64MB
)

// 消息类型
const (
	MsgTypeHeartbeat       uint8 = 0
	MsgTypeMarketSnapshot  uint8 = 1
	MsgTypeOrderCommand    uint8 = 2
	MsgTypeOrderStatus     uint8 = 3
	MsgTypeTradeExecution  uint8 = 4
	MsgTypeSyncRequest     uint8 = 5
	MsgTypeSyncResponse    uint8 = 6
)

// PriceLevel 订单簿档位
type PriceLevel struct {
	Price    float64
	Quantity float64
	Orders   uint32
}

// Size of PriceLevel: 8 + 8 + 4 = 20 bytes

// MarketSnapshot 市场快照 (Go -> Python)
type MarketSnapshot struct {
	TimestampNs       uint64
	Sequence          uint64
	BestBid           float64
	BestAsk           float64
	LastPrice         float64
	MicroPrice        float64
	OrderFlowImbalance float64
	TradeImbalance    float64
	BidQueuePosition  float64
	AskQueuePosition  float64
	Spread            float64
	VolatilityEstimate float64
	TradeIntensity    float64
	AdverseScore      float64
	ToxicProbability  float64
	Bids              [HFTMaxOrderBookDepth]PriceLevel
	Asks              [HFTMaxOrderBookDepth]PriceLevel
}

// OrderCommand 订单命令 (Python -> Go)
type OrderCommand struct {
	CommandID       uint64
	TimestampNs     uint64
	OrderType       uint32
	Side            uint32
	Price           float64
	Quantity        float64
	MaxSlippageBPS  float64
	ExpiresAfterMs  uint32
	DryRun          uint8
}

// OrderStatusUpdate 订单状态更新 (Go -> Python)
type OrderStatusUpdate struct {
	OrderID           uint64
	CommandID         uint64
	TimestampNs       uint64
	Side              uint32
	OrderType         uint32
	Status            uint32
	Price             float64
	OriginalQuantity  float64
	FilledQuantity    float64
	RemainingQuantity float64
	AverageFillPrice  float64
	LatencyUs         float64
	IsMaker           uint8
}

// TradeExecution 成交执行 (Go -> Python)
type TradeExecution struct {
	TradeID         uint64
	OrderID         uint64
	TimestampNs     uint64
	Side            uint32
	Price           float64
	Quantity        float64
	Commission      float64
	RealizedPnL     float64
	AdverseSelection float64
	IsMaker         uint8
}

// Heartbeat 心跳
type Heartbeat struct {
	Magic       uint32
	Version     uint32
	TimestampNs uint64
	Sequence    uint32
	GoRunning   uint8
	AIRunning   uint8
}

// AccountInfo 账户信息
type AccountInfo struct {
	TotalBalance      float64
	AvailableBalance  float64
	PositionSize      float64
	EntryPrice        float64
	UnrealizedPnL     float64
	RealizedPnLToday  float64
	TradesToday       uint32
}

// SharedMemoryHeader 共享内存头部
// 位于共享内存起始位置
type SharedMemoryHeader struct {
	Magic               uint32
	Version             uint32
	SizeBytes           uint64
	GoWriteIndex        uint64
	GoReadIndex         uint64
	AIWriteIndex        uint64
	AIReadIndex         uint64
	MessagesSentGo      uint64
	MessagesSentAI      uint64
	MessagesLost       uint64
	LastHeartbeatGoNs   uint64
	LastHeartbeatAiNs   uint64
	LastHeartbeat       Heartbeat
	AccountInfo         AccountInfo
	LastMarketSnapshot MarketSnapshot
}

// MessageBuffer 消息缓冲区头部
type MessageBuffer struct {
	Type uint8
	Size uint32
	Data []byte
}

// GetTimestampNs 获取当前时间纳秒
func GetTimestampNs() uint64 {
	return uint64(time.Now().UnixNano())
}

// MarshalHeader 序列化头部
func (h *SharedMemoryHeader) Marshal(buf []byte) int {
	offset := 0

	// 基础字段
	binary.LittleEndian.PutUint32(buf[offset:], h.Magic)
	offset += 4
	binary.LittleEndian.PutUint32(buf[offset:], h.Version)
	offset += 4
	binary.LittleEndian.PutUint64(buf[offset:], h.SizeBytes)
	offset += 8
	binary.LittleEndian.PutUint64(buf[offset:], atomic.LoadUint64(&h.GoWriteIndex))
	offset += 8
	binary.LittleEndian.PutUint64(buf[offset:], h.GoReadIndex)
	offset += 8
	binary.LittleEndian.PutUint64(buf[offset:], atomic.LoadUint64(&h.AIWriteIndex))
	offset += 8
	binary.LittleEndian.PutUint64(buf[offset:], h.AIReadIndex)
	offset += 8
	binary.LittleEndian.PutUint64(buf[offset:], h.MessagesSentGo)
	offset += 8
	binary.LittleEndian.PutUint64(buf[offset:], h.MessagesSentAI)
	offset += 8
	binary.LittleEndian.PutUint64(buf[offset:], h.MessagesLost)
	offset += 8
	binary.LittleEndian.PutUint64(buf[offset:], h.LastHeartbeatGoNs)
	offset += 8
	binary.LittleEndian.PutUint64(buf[offset:], h.LastHeartbeatAiNs)
	offset += 8

	// 心跳
	offset += h.LastHeartbeat.Marshal(buf[offset:])

	// 账户信息
	offset += h.AccountInfo.Marshal(buf[offset:])

	// 最新市场快照
	offset += h.LastMarketSnapshot.Marshal(buf[offset:])

	return offset
}

// Marshal 序列化心跳
func (h *Heartbeat) Marshal(buf []byte) int {
	offset := 0
	binary.LittleEndian.PutUint32(buf[offset:], h.Magic)
	offset += 4
	binary.LittleEndian.PutUint32(buf[offset:], h.Version)
	offset += 4
	binary.LittleEndian.PutUint64(buf[offset:], h.TimestampNs)
	offset += 8
	binary.LittleEndian.PutUint32(buf[offset:], h.Sequence)
	offset += 4
	buf[offset] = h.GoRunning
	offset += 1
	buf[offset] = h.AIRunning
	offset += 1
	return offset
}

// Marshal 序列化账户信息
func (a *AccountInfo) Marshal(buf []byte) int {
	offset := 0

	bits := math.Float64bits(a.TotalBalance)
	binary.LittleEndian.PutUint64(buf[offset:], bits)
	offset += 8

	bits = math.Float64bits(a.AvailableBalance)
	binary.LittleEndian.PutUint64(buf[offset:], bits)
	offset += 8

	bits = math.Float64bits(a.PositionSize)
	binary.LittleEndian.PutUint64(buf[offset:], bits)
	offset += 8

	bits = math.Float64bits(a.EntryPrice)
	binary.LittleEndian.PutUint64(buf[offset:], bits)
	offset += 8

	bits = math.Float64bits(a.UnrealizedPnL)
	binary.LittleEndian.PutUint64(buf[offset:], bits)
	offset += 8

	bits = math.Float64bits(a.RealizedPnLToday)
	binary.LittleEndian.PutUint64(buf[offset:], bits)
	offset += 8

	binary.LittleEndian.PutUint32(buf[offset:], a.TradesToday)
	offset += 4

	return offset
}

// Marshal 序列化市场快照
func (m *MarketSnapshot) Marshal(buf []byte) int {
	offset := 0

	binary.LittleEndian.PutUint64(buf[offset:], m.TimestampNs)
	offset += 8
	binary.LittleEndian.PutUint64(buf[offset:], m.Sequence)
	offset += 8

	fields := []float64{
		m.BestBid, m.BestAsk, m.LastPrice, m.MicroPrice,
		m.OrderFlowImbalance, m.TradeImbalance,
		m.BidQueuePosition, m.AskQueuePosition,
		m.Spread, m.VolatilityEstimate, m.TradeIntensity,
		m.AdverseScore, m.ToxicProbability,
	}

	for _, f := range fields {
		bits := math.Float64bits(f)
		binary.LittleEndian.PutUint64(buf[offset:], bits)
		offset += 8
	}

	// Bids
	for i := 0; i < HFTMaxOrderBookDepth; i++ {
		offset += m.Bids[i].Marshal(buf[offset:])
	}

	// Asks
	for i := 0; i < HFTMaxOrderBookDepth; i++ {
		offset += m.Asks[i].Marshal(buf[offset:])
	}

	return offset
}

// Marshal 序列化价格档位
func (p *PriceLevel) Marshal(buf []byte) int {
	offset := 0

	bits := math.Float64bits(p.Price)
	binary.LittleEndian.PutUint64(buf[offset:], bits)
	offset += 8

	bits = math.Float64bits(p.Quantity)
	binary.LittleEndian.PutUint64(buf[offset:], bits)
	offset += 8

	binary.LittleEndian.PutUint32(buf[offset:], p.Orders)
	offset += 4

	return offset
}

// UnmarshalOrderCommand 反序列化订单命令
func UnmarshalOrderCommand(buf []byte) (*OrderCommand, int) {
	cmd := &OrderCommand{}
	offset := 0

	cmd.CommandID = binary.LittleEndian.Uint64(buf[offset:])
	offset += 8

	cmd.TimestampNs = binary.LittleEndian.Uint64(buf[offset:])
	offset += 8

	cmd.OrderType = binary.LittleEndian.Uint32(buf[offset:])
	offset += 4

	cmd.Side = binary.LittleEndian.Uint32(buf[offset:])
	offset += 4

	bits := binary.LittleEndian.Uint64(buf[offset:])
	cmd.Price = math.Float64frombits(bits)
	offset += 8

	bits = binary.LittleEndian.Uint64(buf[offset:])
	cmd.Quantity = math.Float64frombits(bits)
	offset += 8

	bits = binary.LittleEndian.Uint64(buf[offset:])
	cmd.MaxSlippageBPS = math.Float64frombits(bits)
	offset += 8

	cmd.ExpiresAfterMs = binary.LittleEndian.Uint32(buf[offset:])
	offset += 4

	cmd.DryRun = buf[offset]
	offset += 1

	return cmd, offset
}

// NewSharedMemoryHeader 创建新的头部
func NewSharedMemoryHeader(size uint64) *SharedMemoryHeader {
	return &SharedMemoryHeader{
		Magic:         HFTProtocolMagic,
		Version:       HFTProtocolVersion,
		SizeBytes:     size,
		GoWriteIndex:  0,
		GoReadIndex:   0,
		AIWriteIndex:  0,
		AIReadIndex:   0,
		MessagesSentGo: 0,
		MessagesSentAI: 0,
		MessagesLost:  0,
		LastHeartbeat: Heartbeat{
			Magic:       HFTProtocolMagic,
			Version:     HFTProtocolVersion,
			TimestampNs: GetTimestampNs(),
			Sequence:    0,
			GoRunning:   1,
			AIRunning:   0,
		},
	}
}

// VerifyMagic 验证魔数
func (h *SharedMemoryHeader) VerifyMagic() bool {
	return h.Magic == HFTProtocolMagic
}

// VerifyVersion 验证版本
func (h *SharedMemoryHeader) VerifyVersion() bool {
	return h.Version == HFTProtocolVersion
}

// UpdateGoHeartbeat 更新Go端心跳
func (h *SharedMemoryHeader) UpdateGoHeartbeat(seq uint32) {
	h.LastHeartbeatGoNs = GetTimestampNs()
	h.LastHeartbeat.TimestampNs = h.LastHeartbeatGoNs
	h.LastHeartbeat.Sequence = seq
	h.LastHeartbeat.GoRunning = 1
}

// CheckAIHeartbeat 检查AI端心跳是否存活
func (h *SharedMemoryHeader) CheckAIHeartbeat(timeoutNs uint64) bool {
	now := GetTimestampNs()
	return now - h.LastHeartbeatAiNs < timeoutNs
}

// IncrementGoWriteIndex 递增Go写索引
func (h *SharedMemoryHeader) IncrementGoWriteIndex(n int) {
	atomic.AddUint64(&h.GoWriteIndex, uint64(n))
}

// IncrementAIWriteIndex 递增AI写索引
func (h *SharedMemoryHeader) IncrementAIWriteIndex(n int) {
	atomic.AddUint64(&h.AIWriteIndex, uint64(n))
}
