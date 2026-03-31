# P1-103: 风控规则增强 - 完成记录

## 任务概述

实现 HFT 引擎的风控规则增强系统，包括止损/止盈监控、风险等级管理、滑点保护、持仓时间限制等高级风控功能。

## 完成日期

2026-03-31

## 实现内容

### 1. 风控配置模块 (`risk_config.go`)

#### 风险等级类型
| 等级 | 说明 | 特点 |
|------|------|------|
| `RiskLevelConservative` | 保守 | 严格限制，低风险控制 |
| `RiskLevelBalanced` | 平衡 | 中等限制，默认配置 |
| `RiskLevelAggressive` | 激进 | 宽松限制，高风险容忍 |

#### RiskConfig 配置项
```go
type RiskConfig struct {
    // 基础限制
    MaxPosition       float64        // 最大仓位（币的数量）
    MaxSinglePosition float64        // 单笔仓位比例（0.0-1.0）
    MaxTotalPosition  float64        // 总仓位比例（0.0-1.0）
    MaxOrderSize      float64        // 最大订单大小

    // 止损止盈
    StopLossPct       float64        // 止损比例（2%）
    TakeProfitPct     float64        // 止盈比例（5%）
    TrailingStopPct   float64        // 跟踪止损比例（1.5%）
    UseTrailingStop   bool           // 启用跟踪止损

    // 损失限制
    MaxDailyLoss      float64        // 日亏损限制
    MaxDrawdown       float64        // 最大回撤（15%）

    // 速率限制
    MaxOrdersPerMin   int            // 每分钟最大订单数（60）
    MaxOrdersPerHour  int            // 每小时最大订单数（1000）
    MaxOrdersPerDay   int            // 每天最大订单数（5000）

    // 滑点保护
    MaxSlippagePct    float64        // 最大滑点比例（0.1%）
    EnableSlippageCheck bool         // 启用滑点检查

    // 持仓时间
    MaxHoldingTime    time.Duration  // 最大持仓时间（24小时）
    EnableHoldingLimit bool         // 启用持仓时间限制

    // 波动率适应
    EnableVolatilityAdaption bool   // 根据波动率调整参数

    // 风险等级
    RiskLevel         RiskLevelType  // 风险等级预设
}
```

#### 风险等级预设参数
| 参数 | 保守 | 平衡 | 激进 |
|------|------|------|------|
| MaxSinglePosition | 10% | 20% | 30% |
| MaxTotalPosition | 50% | 80% | 100% |
| StopLossPct | 1% | 2% | 3% |
| TakeProfitPct | 3% | 5% | 8% |
| MaxDailyLoss | $5,000 | $10,000 | $20,000 |
| MaxDrawdown | 10% | 15% | 25% |
| MaxOrdersPerMin | 30 | 60 | 120 |
| MaxSlippagePct | 0.05% | 0.1% | 0.2% |
| UseTrailingStop | true | false | false |

### 2. 增强风险管理器 (`risk_enhanced.go`)

#### PositionRisk 持仓风险监控
```go
type PositionRisk struct {
    Symbol       string    // 交易对
    EntryPrice   float64   // 入场价格
    EntryTime    time.Time // 入场时间
    Size         float64   // 持仓大小
    Side         string    // 方向（long/short）
    StopLoss     float64   // 止损价格
    TakeProfit   float64   // 止盈价格
    TrailingStop float64   // 跟踪止损比例
    HighestPrice float64   // 最高价（用于跟踪止损）
    LowestPrice  float64   // 最低价（用于跟踪止损）
}
```

#### 核心功能
| 功能 | 方法 | 说明 |
|------|------|------|
| 止损检查 | `CheckStopLoss()` | 监控价格是否触及止损 |
| 止盈检查 | `CheckTakeProfit()` | 监控价格是否触及止盈 |
| 跟踪止损 | `CheckTrailingStop()` | 动态调整止损价格 |
| 持仓时间 | `GetHoldingTime()` | 计算持仓时长 |
| 滑点检查 | `CheckSlippage()` | 验证执行价格偏差 |

#### EnhancedRiskManager 增强功能
```go
type EnhancedRiskManager struct {
    *RiskManager                    // 嵌入基础风险管理器
    config         *RiskConfig      // 风控配置
    positions      map[string]*PositionRisk // 持仓监控
    alerts         []RiskAlert      // 风险告警
    alertCallback  func(RiskAlert)  // 告警回调
}
```

#### 告警系统
| 告警类型 | 级别 | 触发条件 |
|----------|------|----------|
| `AlertTypeStopLoss` | Critical | 止损触发 |
| `AlertTypeTakeProfit` | Info | 止盈触发 |
| `AlertTypeTrailingStop` | Warning | 跟踪止损触发 |
| `AlertTypeDrawdown` | Critical | 回撤超限 |
| `AlertTypeDailyLoss` | Critical | 日亏损超限 |
| `AlertTypePositionLimit` | Warning | 仓位限制 |
| `AlertTypeOrderRate` | Warning | 订单速率超限 |
| `AlertTypeSlippage` | Warning | 滑点过大 |
| `AlertTypeHoldingTime` | Warning | 持仓超时 |
| `AlertTypeKillSwitch` | Critical | Kill Switch 激活 |

#### 核心方法
| 方法 | 功能 |
|------|------|
| `RegisterPosition()` | 注册新持仓进行监控 |
| `UpdatePositionPrice()` | 更新持仓价格，检查风控条件 |
| `ClosePosition()` | 关闭持仓监控 |
| `CheckEnhancedCanExecute()` | 增强版执行前检查 |
| `SetRiskLevel()` | 动态切换风险等级 |
| `CheckSlippage()` | 检查价格滑点 |
| `GetAlerts()` | 获取风险告警历史 |

### 3. 配置集成 (`config.go`)

#### 新增配置项
```go
// Risk settings (enhanced)
cm.SetDefault("risk.max_position", 1.0)
cm.SetDefault("risk.max_single_position", 0.2)
cm.SetDefault("risk.max_total_position", 0.8)
cm.SetDefault("risk.stop_loss_pct", 0.02)
cm.SetDefault("risk.take_profit_pct", 0.05)
cm.SetDefault("risk.trailing_stop_pct", 0.015)
cm.SetDefault("risk.use_trailing_stop", false)
cm.SetDefault("risk.max_slippage_pct", 0.001)
cm.SetDefault("risk.enable_slippage_check", true)
cm.SetDefault("risk.enable_holding_limit", false)
cm.SetDefault("risk.max_holding_time_hours", 24)
cm.SetDefault("risk.enable_volatility_adaption", false)
cm.SetDefault("risk.risk_level", "balanced")
cm.SetDefault("risk.max_orders_per_hour", 1000)
cm.SetDefault("risk.max_orders_per_day", 5000)
cm.SetDefault("risk.alert_cooldown_min", 5)
```

#### HFTConfig 集成
```go
func (hc *HFTConfig) RiskConfig() *RiskConfig {
    return RiskConfigFromConfigManager(hc.cm)
}
```

### 4. 测试覆盖 (`risk_test.go`)

| 测试 | 描述 | 状态 |
|------|------|------|
| TestRiskLevelType_String | 风险等级字符串表示 | ✅ |
| TestDefaultRiskConfig | 默认配置 | ✅ |
| TestRiskConfig_Validate | 配置验证 | ✅ |
| TestRiskConfig_ApplyRiskLevel | 风险等级预设 | ✅ |
| TestRiskConfig_GetRiskMultiplier | 风险乘数 | ✅ |
| TestNewPositionRisk | 持仓风险创建 | ✅ |
| TestNewPositionRisk_Short | 做空持仓 | ✅ |
| TestPositionRisk_UpdatePrice | 价格更新 | ✅ |
| TestPositionRisk_CheckStopLoss | 止损检查 | ✅ |
| TestPositionRisk_CheckTakeProfit | 止盈检查 | ✅ |
| TestPositionRisk_CheckTrailingStop | 跟踪止损 | ✅ |
| TestPositionRisk_GetHoldingTime | 持仓时间 | ✅ |
| TestNewEnhancedRiskManager | 管理器创建 | ✅ |
| TestEnhancedRiskManager_RegisterPosition | 持仓注册 | ✅ |
| TestEnhancedRiskManager_UpdatePositionPrice | 价格更新 | ✅ |
| TestEnhancedRiskManager_CheckEnhancedCanExecute | 执行检查 | ✅ |
| TestEnhancedRiskManager_SetRiskLevel | 风险等级切换 | ✅ |
| TestEnhancedRiskManager_CheckSlippage | 滑点检查 | ✅ |
| TestRiskAlert_String | 告警字符串 | ✅ |
| TestAlertLevel_String | 告警级别 | ✅ |
| TestAlertType_String | 告警类型 | ✅ |
| TestEnhancedRiskManager_GetAlerts | 告警获取 | ✅ |
| TestEnhancedRiskManager_ClosePosition | 持仓关闭 | ✅ |
| TestRiskConfigFromConfigManager | 配置加载 | ✅ |
| TestHFTConfig_RiskConfig | HFT配置 | ✅ |
| TestEnhancedRiskManager_RateLimits | 速率限制 | ✅ |

**测试数量**: 25 项

## 使用方法

### 基础使用
```go
// 创建风控配置
config := DefaultRiskConfig()
config.RiskLevel = RiskLevelConservative

// 创建增强风险管理器
erm := NewEnhancedRiskManager(config, 100000.0) // $100k capital

// 设置告警回调
erm.SetAlertCallback(func(alert RiskAlert) {
    log.Printf("[RISK ALERT] %s", alert.String())
})
```

### 持仓监控
```go
// 注册持仓
erm.RegisterPosition("BTCUSDT", 50000.0, 1.0, "long")

// 更新价格（自动检查止损/止盈）
alert := erm.UpdatePositionPrice("BTCUSDT", currentPrice)
if alert != nil {
    // 处理告警，如自动平仓
}

// 关闭持仓
erm.ClosePosition("BTCUSDT")
```

### 执行前检查
```go
canExecute, reason := erm.CheckEnhancedCanExecute(
    "BTCUSDT",      // symbol
    ActionJoinBid,  // action
    0.01,           // size
    50000.0,        // price
    0.0,            // current position
)

if !canExecute {
    log.Printf("Order rejected: %s", reason)
}
```

### 动态调整风险等级
```go
// 市场波动加剧时切换到保守模式
erm.SetRiskLevel(RiskLevelConservative)

// 市场稳定时切换回平衡模式
erm.SetRiskLevel(RiskLevelBalanced)
```

### 从配置加载
```go
// 从 ConfigManager 加载
hftConfig := NewHFTConfig(cm)
riskConfig := hftConfig.RiskConfig()

// 创建风险管理器
erm := NewEnhancedRiskManager(riskConfig, 100000.0)
```

## 验证清单

- [x] `risk_config.go` 编译通过
- [x] `risk_enhanced.go` 编译通过
- [x] 25 项单元测试覆盖
- [x] 风险等级预设正确应用
- [x] 止损/止盈监控正常工作
- [x] 跟踪止损功能实现
- [x] 滑点保护机制
- [x] 持仓时间限制
- [x] 告警系统
- [x] 配置集成完成

## 架构影响

### 无破坏性变更
- `RiskManager` 保持向后兼容
- `EnhancedRiskManager` 嵌入 `RiskManager` 扩展功能
- 所有现有代码无需修改

### 新增功能
- 多层次风险控制体系
- 实时监控与告警
- 动态风险等级调整
- 完整的风控配置管理

## 后续工作

- **P1-104**: 自成交防护 (未开始)
- 实盘风控参数调优
- 风控事件持久化存储

## 备注

P1-103 风控规则增强已完成，提供：
- **三层风险等级**: 保守、平衡、激进
- **完整止损体系**: 固定止损、止盈、跟踪止损
- **多维度限制**: 仓位、速率、滑点、持仓时间
- **实时告警系统**: 分级告警，支持回调
- **配置化管理**: 与 ConfigManager 集成，支持热重载

