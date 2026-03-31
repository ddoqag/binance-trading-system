package leverage

import (
	"fmt"
	"sync"
	"time"
)

// PositionManager 仓位管理器 (支持对冲模式)
type PositionManager struct {
	positions map[string]map[Side]*LeveragedPosition // symbol -> side -> position
	mu        sync.RWMutex

	// 默认配置
	defaultLeverage float64
	defaultMode     MarginMode
	positionMode    PositionMode // 仓位模式: 单向/对冲
}

// NewPositionManager 创建仓位管理器
func NewPositionManager() *PositionManager {
	return &PositionManager{
		positions:       make(map[string]map[Side]*LeveragedPosition),
		defaultLeverage: 3.0,
		defaultMode:     ModeIsolated,
		positionMode:    PositionModeOneWay,
	}
}

// SetDefaultConfig 设置默认配置
func (pm *PositionManager) SetDefaultConfig(leverage float64, mode MarginMode) {
	pm.defaultLeverage = leverage
	pm.defaultMode = mode
}

// SetPositionMode 设置仓位模式 (单向/对冲)
func (pm *PositionManager) SetPositionMode(mode PositionMode) {
	pm.mu.Lock()
	defer pm.mu.Unlock()
	pm.positionMode = mode
}

// GetPositionMode 获取仓位模式
func (pm *PositionManager) GetPositionMode() PositionMode {
	pm.mu.RLock()
	defer pm.mu.RUnlock()
	return pm.positionMode
}

// getPositionInternal 内部方法：获取指定方向的仓位 (不加锁)
func (pm *PositionManager) getPositionInternal(symbol string, side Side) *LeveragedPosition {
	if sideMap, ok := pm.positions[symbol]; ok {
		return sideMap[side]
	}
	return nil
}

// OpenPosition 开仓
func (pm *PositionManager) OpenPosition(params OrderParams) (*LeveragedPosition, error) {
	if err := params.Validate(); err != nil {
		return nil, err
	}

	pm.mu.Lock()
	defer pm.mu.Unlock()

	// 获取同方向现有仓位
	existing := pm.getPositionInternal(params.Symbol, params.Side)
	if existing != nil && existing.Status == PositionOpen {
		// 加仓
		return pm.addToPosition(existing, params)
	}

	// 检查反向仓位（单向模式下不能同时持有多空）
	oppositeSide := SideShort
	if params.Side == SideShort {
		oppositeSide = SideLong
	}
	oppositePos := pm.getPositionInternal(params.Symbol, oppositeSide)

	if pm.positionMode == PositionModeOneWay && oppositePos != nil && oppositePos.Status == PositionOpen {
		return nil, fmt.Errorf("cannot open %s position: existing %s position found (one-way mode)",
			params.Side, oppositeSide)
	}

	// 新开仓
	leverage := params.Leverage
	if leverage == 0 {
		leverage = pm.defaultLeverage
	}

	// 计算所需保证金
	notional := params.Size * params.Price
	margin := notional / leverage

	position := &LeveragedPosition{
		Symbol:          params.Symbol,
		Side:            params.Side,
		Size:            params.Size,
		EntryPrice:      params.Price,
		Leverage:        leverage,
		MarginMode:      pm.defaultMode,
		Margin:          margin,
		Status:          PositionOpen,
		MaintenanceRate: 0.005, // 默认0.5%维持保证金率
		CreatedAt:       time.Now(),
		UpdatedAt:       time.Now(),
	}

	// 计算强平价格
	position.calculateLiquidationPrice()

	// 初始化 symbol map 如果不存在
	if pm.positions[params.Symbol] == nil {
		pm.positions[params.Symbol] = make(map[Side]*LeveragedPosition)
	}
	pm.positions[params.Symbol][params.Side] = position

	return position, nil
}

// addToPosition 加仓
func (pm *PositionManager) addToPosition(existing *LeveragedPosition, params OrderParams) (*LeveragedPosition, error) {
	// 计算新的持仓均价
	totalSize := existing.Size + params.Size
	totalValue := existing.Size*existing.EntryPrice + params.Size*params.Price

	existing.EntryPrice = totalValue / totalSize
	existing.Size = totalSize

	// 更新保证金
	notional := existing.Size * existing.EntryPrice
	existing.Margin = notional / existing.Leverage

	// 重新计算强平价格
	existing.calculateLiquidationPrice()
	existing.UpdatedAt = time.Now()

	return existing, nil
}

// ClosePosition 平仓 (单向模式)
func (pm *PositionManager) ClosePosition(symbol string, exitPrice float64) (*LeveragedPosition, error) {
	// 单向模式下，找到该 symbol 的任意持仓
	pm.mu.Lock()
	defer pm.mu.Unlock()

	sideMap, ok := pm.positions[symbol]
	if !ok {
		return nil, fmt.Errorf("no position found for %s", symbol)
	}

	// 找到第一个开仓状态的 position
	for _, position := range sideMap {
		if position != nil && position.Status == PositionOpen {
			return pm.closePositionInternal(position, exitPrice)
		}
	}

	return nil, fmt.Errorf("no open position found for %s", symbol)
}

// ClosePositionBySide 按方向平仓 (对冲模式)
func (pm *PositionManager) ClosePositionBySide(symbol string, side Side, exitPrice float64) (*LeveragedPosition, error) {
	pm.mu.Lock()
	defer pm.mu.Unlock()

	position := pm.getPositionInternal(symbol, side)
	if position == nil || position.Status != PositionOpen {
		return nil, fmt.Errorf("no open %s position found for %s", side, symbol)
	}

	return pm.closePositionInternal(position, exitPrice)
}

// closePositionInternal 内部平仓方法 (需持有锁)
func (pm *PositionManager) closePositionInternal(position *LeveragedPosition, exitPrice float64) (*LeveragedPosition, error) {
	// 计算已实现盈亏
	position.calculateRealizedPnL(exitPrice)
	position.Status = PositionClosed
	now := time.Now()
	position.ClosedAt = &now
	position.UpdatedAt = now

	return position, nil
}

// ReducePosition 减仓 (单向模式)
func (pm *PositionManager) ReducePosition(symbol string, reduceSize float64, exitPrice float64) (*LeveragedPosition, error) {
	pm.mu.Lock()
	defer pm.mu.Unlock()

	sideMap, ok := pm.positions[symbol]
	if !ok {
		return nil, fmt.Errorf("no position found for %s", symbol)
	}

	// 找到第一个开仓状态的 position
	for _, position := range sideMap {
		if position != nil && position.Status == PositionOpen {
			return pm.reducePositionInternal(position, reduceSize, exitPrice)
		}
	}

	return nil, fmt.Errorf("no open position found for %s", symbol)
}

// ReducePositionBySide 按方向减仓 (对冲模式)
func (pm *PositionManager) ReducePositionBySide(symbol string, side Side, reduceSize float64, exitPrice float64) (*LeveragedPosition, error) {
	pm.mu.Lock()
	defer pm.mu.Unlock()

	position := pm.getPositionInternal(symbol, side)
	if position == nil || position.Status != PositionOpen {
		return nil, fmt.Errorf("no open %s position found for %s", side, symbol)
	}

	return pm.reducePositionInternal(position, reduceSize, exitPrice)
}

// reducePositionInternal 内部减仓方法 (需持有锁)
func (pm *PositionManager) reducePositionInternal(position *LeveragedPosition, reduceSize float64, exitPrice float64) (*LeveragedPosition, error) {
	if reduceSize >= position.Size {
		// 全部平仓
		return pm.closePositionInternal(position, exitPrice)
	}

	// 计算部分盈亏
	partialPnL := position.calculatePartialPnL(reduceSize, exitPrice)
	position.RealizedPnL += partialPnL

	// 更新持仓
	position.Size -= reduceSize
	position.Margin = (position.Size * position.EntryPrice) / position.Leverage
	position.calculateLiquidationPrice()
	position.UpdatedAt = time.Now()

	return position, nil
}

// GetPosition 获取仓位 (单向模式)
func (pm *PositionManager) GetPosition(symbol string) (*LeveragedPosition, bool) {
	pm.mu.RLock()
	defer pm.mu.RUnlock()

	sideMap, ok := pm.positions[symbol]
	if !ok {
		return nil, false
	}

	// 找到第一个开仓状态的 position
	for _, pos := range sideMap {
		if pos != nil && pos.Status == PositionOpen {
			return pos, true
		}
	}

	return nil, false
}

// GetPositionBySide 按方向获取仓位 (对冲模式)
func (pm *PositionManager) GetPositionBySide(symbol string, side Side) (*LeveragedPosition, bool) {
	pm.mu.RLock()
	defer pm.mu.RUnlock()

	position := pm.getPositionInternal(symbol, side)
	if position != nil && position.Status == PositionOpen {
		return position, true
	}
	return nil, false
}

// GetBothPositions 获取多空双向仓位 (仅对冲模式)
func (pm *PositionManager) GetBothPositions(symbol string) (longPos, shortPos *LeveragedPosition) {
	pm.mu.RLock()
	defer pm.mu.RUnlock()

	sideMap := pm.positions[symbol]
	if sideMap == nil {
		return nil, nil
	}

	if pos := sideMap[SideLong]; pos != nil && pos.Status == PositionOpen {
		longPos = pos
	}
	if pos := sideMap[SideShort]; pos != nil && pos.Status == PositionOpen {
		shortPos = pos
	}

	return longPos, shortPos
}

// GetAllPositions 获取所有持仓
func (pm *PositionManager) GetAllPositions() []*LeveragedPosition {
	pm.mu.RLock()
	defer pm.mu.RUnlock()

	var positions []*LeveragedPosition
	for _, sideMap := range pm.positions {
		for _, pos := range sideMap {
			if pos != nil && pos.Status == PositionOpen {
				positions = append(positions, pos)
			}
		}
	}
	return positions
}

// GetPositionsBySide 获取指定方向的所有持仓
func (pm *PositionManager) GetPositionsBySide(side Side) []*LeveragedPosition {
	pm.mu.RLock()
	defer pm.mu.RUnlock()

	var positions []*LeveragedPosition
	for _, sideMap := range pm.positions {
		if pos := sideMap[side]; pos != nil && pos.Status == PositionOpen {
			positions = append(positions, pos)
		}
	}
	return positions
}

// GetOpenPositionsCount 获取总持仓数量
func (pm *PositionManager) GetOpenPositionsCount() int {
	pm.mu.RLock()
	defer pm.mu.RUnlock()

	count := 0
	for _, sideMap := range pm.positions {
		for _, pos := range sideMap {
			if pos != nil && pos.Status == PositionOpen {
				count++
			}
		}
	}
	return count
}

// GetOpenPositionsCountBySide 获取指定方向的持仓数量
func (pm *PositionManager) GetOpenPositionsCountBySide(side Side) int {
	pm.mu.RLock()
	defer pm.mu.RUnlock()

	count := 0
	for _, sideMap := range pm.positions {
		if pos := sideMap[side]; pos != nil && pos.Status == PositionOpen {
			count++
		}
	}
	return count
}

// HasPosition 检查是否有持仓
func (pm *PositionManager) HasPosition(symbol string) bool {
	_, ok := pm.GetPosition(symbol)
	return ok
}

// HasPositionBySide 检查是否有指定方向的持仓
func (pm *PositionManager) HasPositionBySide(symbol string, side Side) bool {
	_, ok := pm.GetPositionBySide(symbol, side)
	return ok
}

// HasBothSides 检查是否同时持有多空 (对冲模式)
func (pm *PositionManager) HasBothSides(symbol string) bool {
	longPos, shortPos := pm.GetBothPositions(symbol)
	return longPos != nil && shortPos != nil
}

// GetNetPosition 获取净仓位 (多空抵消后的净值)
func (pm *PositionManager) GetNetPosition(symbol string) float64 {
	longPos, shortPos := pm.GetBothPositions(symbol)

	netSize := 0.0
	if longPos != nil {
		netSize += longPos.Size
	}
	if shortPos != nil {
		netSize -= shortPos.Size
	}
	return netSize
}

// UpdateMarkPrice 更新标记价格（用于计算未实现盈亏）
func (pm *PositionManager) UpdateMarkPrice(symbol string, markPrice float64) {
	pm.mu.Lock()
	defer pm.mu.Unlock()

	sideMap := pm.positions[symbol]
	if sideMap == nil {
		return
	}

	for _, position := range sideMap {
		if position != nil && position.Status == PositionOpen {
			position.UnrealizedPnL = position.calculateUnrealizedPnL(markPrice)
			position.UpdatedAt = time.Now()
		}
	}
}

// GetPositionSummary 获取仓位摘要 (单向模式)
func (pm *PositionManager) GetPositionSummary(symbol string, markPrice float64) (*PositionSummary, error) {
	pm.mu.RLock()
	defer pm.mu.RUnlock()

	sideMap, ok := pm.positions[symbol]
	if !ok {
		return nil, fmt.Errorf("position not found for %s", symbol)
	}

	// 找到第一个 position
	for _, position := range sideMap {
		if position != nil {
			return pm.getPositionSummaryInternal(position, markPrice), nil
		}
	}

	return nil, fmt.Errorf("position not found for %s", symbol)
}

// GetPositionSummaryBySide 按方向获取仓位摘要
func (pm *PositionManager) GetPositionSummaryBySide(symbol string, side Side, markPrice float64) (*PositionSummary, error) {
	pm.mu.RLock()
	defer pm.mu.RUnlock()

	position := pm.getPositionInternal(symbol, side)
	if position == nil {
		return nil, fmt.Errorf("position not found for %s %s", side, symbol)
	}

	return pm.getPositionSummaryInternal(position, markPrice), nil
}

// getPositionSummaryInternal 内部方法
func (pm *PositionManager) getPositionSummaryInternal(position *LeveragedPosition, markPrice float64) *PositionSummary {
	unrealizedPnL := position.calculateUnrealizedPnL(markPrice)
	unrealizedPnLPct := 0.0
	if position.Margin > 0 {
		unrealizedPnLPct = unrealizedPnL / position.Margin * 100
	}

	return &PositionSummary{
		Symbol:           position.Symbol,
		Side:             position.Side,
		Size:             position.Size,
		EntryPrice:       position.EntryPrice,
		MarkPrice:        markPrice,
		Leverage:         position.Leverage,
		MarginMode:       position.MarginMode,
		UnrealizedPnL:    unrealizedPnL,
		UnrealizedPnLPct: unrealizedPnLPct,
		LiquidationPrice: position.LiquidationPrice,
	}
}

// CheckLiquidation 检查是否触发强平 (单向模式)
func (pm *PositionManager) CheckLiquidation(symbol string, markPrice float64) (bool, error) {
	pm.mu.RLock()
	defer pm.mu.RUnlock()

	sideMap, ok := pm.positions[symbol]
	if !ok {
		return false, fmt.Errorf("no position found for %s", symbol)
	}

	for _, position := range sideMap {
		if position != nil && position.Status == PositionOpen {
			if position.Side == SideLong {
				return markPrice <= position.LiquidationPrice, nil
			}
			return markPrice >= position.LiquidationPrice, nil
		}
	}

	return false, fmt.Errorf("no open position found for %s", symbol)
}

// CheckLiquidationBySide 按方向检查强平
func (pm *PositionManager) CheckLiquidationBySide(symbol string, side Side, markPrice float64) (bool, error) {
	pm.mu.RLock()
	defer pm.mu.RUnlock()

	position := pm.getPositionInternal(symbol, side)
	if position == nil || position.Status != PositionOpen {
		return false, fmt.Errorf("no open %s position found for %s", side, symbol)
	}

	if position.Side == SideLong {
		return markPrice <= position.LiquidationPrice, nil
	}
	return markPrice >= position.LiquidationPrice, nil
}

// LiquidatePosition 强制平仓 (单向模式)
func (pm *PositionManager) LiquidatePosition(symbol string, markPrice float64) (*LeveragedPosition, error) {
	pm.mu.Lock()
	defer pm.mu.Unlock()

	sideMap, ok := pm.positions[symbol]
	if !ok {
		return nil, fmt.Errorf("no position found for %s", symbol)
	}

	for _, position := range sideMap {
		if position != nil && position.Status == PositionOpen {
			return pm.liquidatePositionInternal(position, markPrice)
		}
	}

	return nil, fmt.Errorf("no open position found for %s", symbol)
}

// LiquidatePositionBySide 按方向强制平仓
func (pm *PositionManager) LiquidatePositionBySide(symbol string, side Side, markPrice float64) (*LeveragedPosition, error) {
	pm.mu.Lock()
	defer pm.mu.Unlock()

	position := pm.getPositionInternal(symbol, side)
	if position == nil || position.Status != PositionOpen {
		return nil, fmt.Errorf("no open %s position found for %s", side, symbol)
	}

	return pm.liquidatePositionInternal(position, markPrice)
}

// liquidatePositionInternal 内部强平方法
func (pm *PositionManager) liquidatePositionInternal(position *LeveragedPosition, markPrice float64) (*LeveragedPosition, error) {
	position.calculateRealizedPnL(markPrice)
	position.Status = PositionLiquidating
	now := time.Now()
	position.ClosedAt = &now
	position.UpdatedAt = now
	return position, nil
}

// calculateLiquidationPrice 计算强平价格
func (p *LeveragedPosition) calculateLiquidationPrice() {
	if p.Size == 0 || p.EntryPrice == 0 {
		p.LiquidationPrice = 0
		return
	}

	maintenanceMargin := p.MaintenanceRate

	if p.Side == SideLong {
		// 多头强平价格 = 入场价 * (1 - 1/杠杆 + 维持保证金率)
		p.LiquidationPrice = p.EntryPrice * (1 - 1/p.Leverage + maintenanceMargin)
	} else {
		// 空头强平价格 = 入场价 * (1 + 1/杠杆 - 维持保证金率)
		p.LiquidationPrice = p.EntryPrice * (1 + 1/p.Leverage - maintenanceMargin)
	}
}

// calculateUnrealizedPnL 计算未实现盈亏
func (p *LeveragedPosition) calculateUnrealizedPnL(markPrice float64) float64 {
	if p.Side == SideLong {
		return (markPrice - p.EntryPrice) * p.Size
	}
	return (p.EntryPrice - markPrice) * p.Size
}

// calculateRealizedPnL 计算已实现盈亏
func (p *LeveragedPosition) calculateRealizedPnL(exitPrice float64) {
	if p.Side == SideLong {
		p.RealizedPnL = (exitPrice - p.EntryPrice) * p.Size
	} else {
		p.RealizedPnL = (p.EntryPrice - exitPrice) * p.Size
	}
}

// calculatePartialPnL 计算部分盈亏
func (p *LeveragedPosition) calculatePartialPnL(reduceSize float64, exitPrice float64) float64 {
	if p.Side == SideLong {
		return (exitPrice - p.EntryPrice) * reduceSize
	}
	return (p.EntryPrice - exitPrice) * reduceSize
}

// GetPnLResult 获取盈亏结果
func (p *LeveragedPosition) GetPnLResult(markPrice float64) *PnLResult {
	unrealizedPnL := p.calculateUnrealizedPnL(markPrice)
	unrealizedPnLPct := 0.0
	roe := 0.0

	if p.Margin > 0 {
		unrealizedPnLPct = unrealizedPnL / p.Margin * 100
		roe = unrealizedPnL / p.Margin
	}

	realizedPnLPct := 0.0
	if p.Margin > 0 {
		realizedPnLPct = p.RealizedPnL / p.Margin * 100
	}

	return &PnLResult{
		UnrealizedPnL:    unrealizedPnL,
		UnrealizedPnLPct: unrealizedPnLPct,
		RealizedPnL:      p.RealizedPnL,
		RealizedPnLPct:   realizedPnLPct,
		ROE:              roe,
	}
}
