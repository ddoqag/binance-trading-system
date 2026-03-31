# P1-103: 风控规则增强 - 实现计划

## 任务概述

增强 HFT 引擎的风控管理系统，实现多层级的风险控制机制。

## 当前状态

### 已实现风控功能
| 功能 | 状态 | 说明 |
|------|------|------|
| 仓位限制 | ✅ | maxPosition 总仓位限制 |
| 日亏损限制 | ✅ | maxDailyLoss 日亏损上限 |
| 回撤监控 | ✅ | maxDrawdown 最大回撤限制 |
| Kill Switch | ✅ | 紧急停止开关 |
| 订单速率限制 | ✅ | maxOrdersPerMin 每分钟订单数 |
| 订单大小限制 | ✅ | maxOrderSize 单笔订单大小 |

### 配置已定义但未实现
| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| risk.max_single_position | 0.2 | 单笔仓位限制（相对于总资金） |
| risk.max_total_position | 0.8 | 总仓位限制（相对于总资金） |
| risk.stop_loss_pct | 0.02 | 止损比例（2%） |
| risk.take_profit_pct | 0.05 | 止盈比例（5%） |

## 新增风控规则

### 1. 止损/止盈监控 (StopLoss/TakeProfit)
- 实时监控持仓的未实现盈亏
- 触发止损/止盈时自动平仓
- 支持跟踪止损 (Trailing Stop)

### 2. 风险等级管理 (RiskLevel)
- 保守 (Conservative): 低风险偏好
- 平衡 (Balanced): 中等风险
- 激进 (Aggressive): 高风险容忍
- 根据风险等级自动调整所有风控参数

### 3. 价格滑点保护 (Slippage Protection)
- 监控订单执行价格与预期价格的偏差
- 超过阈值时拒绝订单或触发告警

### 4. 持仓时间限制 (Position Holding Limit)
- 限制单笔持仓的最大持有时间
- 超时自动平仓

### 5. 波动率适应 (Volatility Adaptation)
- 根据市场波动率动态调整风控参数
- 高波动时收紧风控，低波动时放宽

### 6. 风险报告与告警 (Risk Reporting)
- 实时风险指标监控
- 风险事件日志记录
- 告警通知机制

## 文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `risk_manager.go` | 修改 | 增强现有风险管理器 |
| `risk_enhanced.go` | 新增 | 增强风控功能实现 |
| `risk_config.go` | 新增 | 风控配置结构体 |
| `risk_test.go` | 新增 | 风控单元测试 |
| `config.go` | 修改 | 添加新风控配置默认值 |

## 数据结构

```go
// RiskConfig 风控配置
type RiskConfig struct {
    // 基础限制
    MaxPosition       float64        // 最大仓位（币的数量）
    MaxSinglePosition float64        // 单笔仓位比例（相对于资金）
    MaxTotalPosition  float64        // 总仓位比例（相对于资金）
    MaxOrderSize      float64        // 最大订单大小

    // 止损止盈
    StopLossPct       float64        // 止损比例
    TakeProfitPct     float64        // 止盈比例
    TrailingStopPct   float64        // 跟踪止损比例

    // 损失限制
    MaxDailyLoss      float64        // 日亏损限制
    MaxDrawdown       float64        // 最大回撤

    // 速率限制
    MaxOrdersPerMin   int            // 每分钟最大订单数
    MaxOrdersPerHour  int            // 每小时最大订单数

    // 滑点保护
    MaxSlippagePct    float64        // 最大滑点比例

    // 持仓时间
    MaxHoldingTime    time.Duration  // 最大持仓时间

    // 风险等级
    RiskLevel         RiskLevelType  // 风险等级
}

// RiskLevelType 风险等级
type RiskLevelType int
const (
    RiskLevelConservative RiskLevelType = iota // 保守
    RiskLevelBalanced                          // 平衡
    RiskLevelAggressive                        // 激进
)

// EnhancedRiskManager 增强风险管理器
type EnhancedRiskManager struct {
    *RiskManager                    // 嵌入基础风险管理器
    config         *RiskConfig      // 风控配置
    positions      map[string]*PositionRisk // 持仓风险监控
    alerts         []RiskAlert      // 风险告警列表
    alertCallback  func(RiskAlert)  // 告警回调
}

// PositionRisk 持仓风险
type PositionRisk struct {
    Symbol        string
    EntryPrice    float64
    EntryTime     time.Time
    Size          float64
    StopLoss      float64
    TakeProfit    float64
    TrailingStop  float64
    HighestPrice  float64  // 用于跟踪止损
}

// RiskAlert 风险告警
type RiskAlert struct {
    Timestamp time.Time
    Level     RiskAlertLevel
    Type      RiskAlertType
    Message   string
    Data      map[string]interface{}
}
```

## 实现步骤

### Phase 1: 基础增强
1. 创建 RiskConfig 结构体和配置加载
2. 扩展 RiskManager 支持配置参数
3. 实现单笔仓位和总仓位比例检查

### Phase 2: 止损止盈
1. 实现 PositionRisk 持仓监控
2. 实现止损/止盈检查逻辑
3. 实现跟踪止损功能

### Phase 3: 风险等级
1. 实现风险等级枚举和参数映射
2. 根据风险等级自动调整参数
3. 支持运行时切换风险等级

### Phase 4: 高级功能
1. 实现滑点保护
2. 实现持仓时间限制
3. 实现波动率适应

### Phase 5: 风险报告
1. 实现风险指标计算
2. 实现告警系统
3. 实现风险报告生成

### Phase 6: 测试
1. 编写单元测试
2. 集成测试
3. 验证所有风控规则

## 验证清单

- [ ] RiskConfig 配置正确加载
- [ ] 单笔仓位限制生效
- [ ] 总仓位比例限制生效
- [ ] 止损/止盈监控正常工作
- [ ] 跟踪止损功能正常
- [ ] 风险等级切换正常
- [ ] 滑点保护生效
- [ ] 持仓时间限制生效
- [ ] 风险告警触发正常
- [ ] 所有单元测试通过
- [ ] 集成测试通过

## 时间估算

| 阶段 | 预计时间 |
|------|----------|
| Phase 1: 基础增强 | 2小时 |
| Phase 2: 止损止盈 | 2小时 |
| Phase 3: 风险等级 | 1.5小时 |
| Phase 4: 高级功能 | 2小时 |
| Phase 5: 风险报告 | 1.5小时 |
| Phase 6: 测试 | 2小时 |
| **总计** | **~11小时** |

## 风险与缓解

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|----------|
| 风控过于严格导致交易受限 | 中 | 中 | 提供配置调整接口，支持动态调整 |
| 止损/止盈误判 | 低 | 高 | 使用价格确认机制，避免瞬间波动触发 |
| 性能影响 | 低 | 中 | 优化检查逻辑，避免频繁计算 |

