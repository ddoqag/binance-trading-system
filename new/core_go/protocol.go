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
	HFTProtocolMagic       uint32 = 0x48465453 // "HFTS"
	HFTProtocolVersion     uint32 = 1
	HFTMinCompatibleVersion uint32 = 1
	HFTMaxCompatibleVersion uint32 = 1
	HFTMaxOrderBookDepth   = 20
	HFTMaxOrders           = 64
	HFTShmSizeDefault      = 64 * 1024 * 1024 // 64MB
)

// 共享内存布局偏移量
const (
	HFTHeaderOffset     = 0
	HFTAIContextOffset  = 4096
	HFTFeaturesOffset   = 16384
	HFTSignalOffset     = 17024 // 16384 + 640
)

// 结构体大小常量
const (
	HFTPriceLevelSize   = 20
	HFTHeartbeatSize    = 24
	HFTAccountInfoSize  = 56
	HFTAIContextSize    = 64
	HFTHeaderSize       = 1024
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

// AIContext AI决策上下文 (Python -> Go)
type AIContext struct {
	AIPosition        float64
	AIConfidence      float64
	MoEWeight0        float64
	MoEWeight1        float64
	MoEWeight2        float64
	MoEWeight3        float64
	RegimeCode        uint32
	NumActiveExperts  uint32
}

const AIContextOffset = 4096

// FeatureVector 特征向量 (位于 HFTFeaturesOffset)
type FeatureVector struct {
	OFI              float64 // 订单流不平衡 [-1, +1]
	QueueRatio       float64 // 队列位置 [0, 1]
	HazardRate       float64 // 危险率
	AdverseScore     float64 // 逆向选择分数 [-1, +1]
	ToxicProb        float64 // 毒流概率 [0, 1]
	Spread           float64 // 价差
	MicroMomentum    float64 // 微观动量 [-1, +1]
	Volatility       float64 // 波动率
	TradeFlow        float64 // 交易流 [-1, +1]
	Inventory        float64 // 持仓压力 [-1, +1]
	Reserved         [70]float64 // 填充到640 bytes
}

// SignalVector 信号向量 (位于 HFTSignalOffset)
type SignalVector struct {
	ActionDirection  float64 // 动作方向 [-1, +1]
	ActionAggression float64 // 激进度 [0, 1]
	ActionSizeScale  float64 // 大小缩放 [0, 1]
	PositionTarget   float64 // 目标仓位 [-1, +1]
	Confidence       float64 // 置信度 [0, 1]
	RegimeCode       uint32  // 市场状态编码
	ExpertID         uint32  // 专家ID
	Reserved         [26]float64 // 填充到256 bytes
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

// UnmarshalAIContext 反序列化 AI 上下文
func UnmarshalAIContext(buf []byte) (*AIContext, int) {
	ctx := &AIContext{}
	offset := 0

	bits := binary.LittleEndian.Uint64(buf[offset:])
	ctx.AIPosition = math.Float64frombits(bits)
	offset += 8

	bits = binary.LittleEndian.Uint64(buf[offset:])
	ctx.AIConfidence = math.Float64frombits(bits)
	offset += 8

	bits = binary.LittleEndian.Uint64(buf[offset:])
	ctx.MoEWeight0 = math.Float64frombits(bits)
	offset += 8

	bits = binary.LittleEndian.Uint64(buf[offset:])
	ctx.MoEWeight1 = math.Float64frombits(bits)
	offset += 8

	bits = binary.LittleEndian.Uint64(buf[offset:])
	ctx.MoEWeight2 = math.Float64frombits(bits)
	offset += 8

	bits = binary.LittleEndian.Uint64(buf[offset:])
	ctx.MoEWeight3 = math.Float64frombits(bits)
	offset += 8

	ctx.RegimeCode = binary.LittleEndian.Uint32(buf[offset:])
	offset += 4

	ctx.NumActiveExperts = binary.LittleEndian.Uint32(buf[offset:])
	offset += 4

	// skip reserved 8 bytes
	offset += 8

	return ctx, offset
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
	return h.Version >= HFTMinCompatibleVersion && h.Version <= HFTMaxCompatibleVersion
}

// CheckVersion 检查版本是否兼容
func CheckVersion(version uint32) bool {
	return version >= HFTMinCompatibleVersion && version <= HFTMaxCompatibleVersion
}

// NegotiateVersion 协商使用哪个版本
func NegotiateVersion(goVersion, pyVersion uint32) uint32 {
	if goVersion < pyVersion {
		return goVersion
	}
	return pyVersion
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

// ============================================================================
// Reversal Detection SHM Protocol (扩展协议)
// ============================================================================

// Reversal SHM 魔数和版本
const (
	ReversalSHMMagic       uint32 = 0x52455653 // "REVS"
	ReversalSHMVersion     uint32 = 1
	ReversalFeaturesOffset        = 16384
	ReversalFeaturesSize          = 640 // 512 + 128 reason
	ReversalSignalOffset          = 17024 // 16384 + 640
	ReversalSignalSize            = 256
)

// ReversalFeaturesSHM 反转特征结构 (640 bytes)
type ReversalFeaturesSHM struct {
	// Header (24 bytes)
	Magic       uint32
	Version     uint32
	TimestampNs uint64
	Sequence    uint64

	// Price features (64 bytes)
	PriceMomentum1m    float64
	PriceMomentum5m    float64
	PriceMomentum15m   float64
	PriceZScore        float64
	PricePercentile    float64
	PriceVelocity      float64
	PriceAcceleration  float64
	PriceMeanReversion float64

	// Volume features (32 bytes)
	VolumeSurge    float64
	VolumeMomentum float64
	VolumeZScore   float64
	RelativeVolume float64

	// Volatility features (32 bytes)
	VolatilityCurrent float64
	VolatilityRegime  float64
	AtrRatio          float64
	BollingerPosition float64

	// Order flow features (40 bytes)
	OfiSignal       float64
	TradeImbalance  float64
	BidAskPressure  float64
	OrderBookSlope  float64
	MicroPriceDrift float64

	// Microstructure (32 bytes)
	SpreadPercentile float64
	TickPressure     float64
	QueueImbalance   float64
	TradeIntensity   float64

	// Time features (16 bytes)
	TimeOfDay    float64
	DayOfWeek    uint32
	IsMarketOpen uint32
	SessionType  uint32
	_            uint32 // padding

	// Metadata (16 bytes)
	SymbolID  uint32
	Timeframe uint32
	Reserved  uint32
	_         uint32 // padding

	// Reason field (128 bytes)
	Reason [128]byte

	// Padding to 640 bytes (640 - 264 - 128 = 248 bytes)
	_ [248]byte
}

// ReversalSignalSHM 反转信号结构 (256 bytes)
type ReversalSignalSHM struct {
	// Header (24 bytes)
	Magic       uint32
	Version     uint32
	TimestampNs uint64
	Sequence    uint64

	// Signal data (40 bytes)
	SignalStrength float64 // -1.0 to 1.0
	Confidence     float64 // 0.0 to 1.0
	Probability    float64 // 0.0 to 1.0
	ExpectedReturn float64
	TimeHorizonMs  uint32
	_              uint32 // padding

	// Model info (24 bytes)
	ModelVersion       uint32 // 0=LightGBM, 1=NN, 2=Ensemble
	ModelType          uint32
	InferenceLatencyUs uint32
	_                  uint32 // padding
	FeatureTimestampNs uint64

	// Feature importance (64 bytes)
	TopFeature1 float64
	TopFeature2 float64
	TopFeature3 float64
	TopFeature4 float64
	TopFeature5 float64
	TopFeature6 float64
	TopFeature7 float64
	TopFeature8 float64

	// Risk metrics (32 bytes)
	PredictionUncertainty float64
	MarketRegime          uint32 // 0=unknown, 1=trend_up, 2=trend_down, 3=range, 4=high_vol
	_                     uint32 // padding
	RiskScore             float64
	MaxAdverseExcursion   float64

	// Execution advice (24 bytes)
	SuggestedUrgency  float64
	SuggestedTTLMs    uint32
	ExecutionPriority uint32 // 0=normal, 1=high, 2=critical
	ReasonCode        uint32
	_                 uint32 // padding

	// Reason details (48 bytes)
	ReasonDetails [48]byte
}

// ============================================================================
// Verification Metrics SHM (真实性检验)
// ============================================================================

const (
	VerificationSHMMagic        uint32 = 0x54525554 // "TRUT"
	VerificationSHMVersion      uint32 = 1
	VerificationMetricsOffset          = 17252     // ReversalSignalOffset + ReversalSignalSize
	VerificationMetricsSize            = 288

	// Version control
	ProtocolVersionMajor = 1
	ProtocolVersionMinor = 0
	ProtocolVersionPatch = 0
	ProtocolVersionFull  = (ProtocolVersionMajor << 16) | (ProtocolVersionMinor << 8) | ProtocolVersionPatch
)

// Verification flags
const (
	VerificationFlagLatencyOK     uint32 = 0x0001
	VerificationFlagSlippageOK    uint32 = 0x0002
	VerificationFlagConsistencyOK uint32 = 0x0004
	VerificationFlagAnomalyFree   uint32 = 0x0008
	VerificationFlagAllOK         uint32 = 0x000F
)

// VerificationMetricsSHM 真实性检验指标结构 (288 bytes)
type VerificationMetricsSHM struct {
	// Header (16 bytes)
	Magic       uint32
	Version     uint32
	TimestampNs uint64

	// Latency measurements (32 bytes)
	LatencyTotalUs      uint32
	LatencyFeatureUs    uint32
	LatencyInferenceUs  uint32
	LatencyDecisionUs   uint32
	LatencyTransmitUs   uint32
	LatencyExecuteUs    uint32
	_                   [2]uint32 // padding

	// Validation status (16 bytes)
	ValidationFlags   uint32
	AnomalyCount      uint32
	SlippageBps       float32
	ConsistencyScore  float32

	// Extended metrics (64 bytes)
	ExecutionPrice     float64
	PredictedPrice     float64
	PriceError         float64
	PriceErrorStd      float64
	MarketImpactBps    float64
	TimingScore        float64
	QueuePositionError float64
	FillRate           float64

	// Quality metrics (32 bytes)
	SignalToNoise       float32
	PredictionAccuracy  float32
	ModelDriftScore     float32
	DataFreshnessMs     float32
	ConsecutiveErrors   uint32
	RecoveryCount       uint32
	_                   [2]float32 // padding

	// Reserved (128 bytes)
	Reserved [128]byte
}

// ReversalCheckMagic 检查 Reversal SHM 魔数
func ReversalCheckMagic(magic uint32) bool {
	return magic == ReversalSHMMagic
}

// ReversalCheckVersion 检查 Reversal SHM 版本
func ReversalCheckVersion(version uint32) bool {
	return version == ReversalSHMVersion
}

// VerificationCheckMagic 检查 Verification SHM 魔数
func VerificationCheckMagic(magic uint32) bool {
	return magic == VerificationSHMMagic
}

// VerificationCheckVersion 检查 Verification SHM 版本
func VerificationCheckVersion(version uint32) bool {
	return version == VerificationSHMVersion
}

// CheckVersionMajor 检查主版本号
func CheckVersionMajor(version uint32) bool {
	return (version >> 16) == ProtocolVersionMajor
}

// CheckVersionCompat 检查版本兼容性
func CheckVersionCompat(version uint32) bool {
	majorOK := (version >> 16) == ProtocolVersionMajor
	minorOK := ((version >> 8) & 0xFF) <= ProtocolVersionMinor
	return majorOK && minorOK
}

// IsLatencyOK 检查延迟是否正常
func (v *VerificationMetricsSHM) IsLatencyOK() bool {
	return (v.ValidationFlags & VerificationFlagLatencyOK) != 0
}

// IsSlippageOK 检查滑点是否正常
func (v *VerificationMetricsSHM) IsSlippageOK() bool {
	return (v.ValidationFlags & VerificationFlagSlippageOK) != 0
}

// IsConsistencyOK 检查一致性是否正常
func (v *VerificationMetricsSHM) IsConsistencyOK() bool {
	return (v.ValidationFlags & VerificationFlagConsistencyOK) != 0
}

// IsAllOK 检查所有验证是否通过
func (v *VerificationMetricsSHM) IsAllOK() bool {
	return (v.ValidationFlags & VerificationFlagAllOK) == VerificationFlagAllOK
}

// GetReason 获取原因字符串
func (r *ReversalFeaturesSHM) GetReason() string {
	n := 0
	for n < len(r.Reason) && r.Reason[n] != 0 {
		n++
	}
	return string(r.Reason[:n])
}

// GetReasonDetails 获取信号原因详情
func (r *ReversalSignalSHM) GetReasonDetails() string {
	n := 0
	for n < len(r.ReasonDetails) && r.ReasonDetails[n] != 0 {
		n++
	}
	return string(r.ReasonDetails[:n])
}

// GetDirection 获取信号方向: -1 (down), 0 (neutral), 1 (up)
func (r *ReversalSignalSHM) GetDirection() int {
	if r.SignalStrength > 0.3 {
		return 1 // Up reversal expected
	} else if r.SignalStrength < -0.3 {
		return -1 // Down reversal expected
	}
	return 0
}

// IsValid 检查信号是否有效
func (r *ReversalSignalSHM) IsValid(minConfidence, minStrength float64) bool {
	if r.Magic != ReversalSHMMagic {
		return false
	}
	if r.Confidence < minConfidence {
		return false
	}
	if abs(r.SignalStrength) < minStrength {
		return false
	}
	return true
}
