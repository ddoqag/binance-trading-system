# Defense FSM 集成指南

## 概述

订单防御状态机（Order Defense FSM）已集成到HFT引擎中，提供三层防御机制保护交易策略免受毒流收割。

## 集成架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                    DefenseIntegratedEngine                          │
├─────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │   HFTEngine  │  │DefenseManager│  │ 集成层        │              │
│  │   (基础引擎)  │  │  (防御核心)   │  │             │              │
│  └──────┬───────┘  └──────┬───────┘  └──────────────┘              │
│         │                 │                                         │
│         ▼                 ▼                                         │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │                 防御回调                                  │      │
│  │  - ModeChange: NORMAL->DEFENSIVE->TOXIC                  │      │
│  │  - CancelOrder: 自动撤单                                  │      │
│  │  - SideControl: 侧边开关                                  │      │
│  └──────────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────┘
```

## 快速开始

### 1. 创建带防御的引擎

```go
package main

import (
    "log"
    "time"
)

func main() {
    // 引擎配置
    engineConfig := DefaultConfig("BTCUSDT")
    engineConfig.PaperTrading = true  // 模拟交易模式
    engineConfig.UseMargin = false    // 不使用杠杆

    // 防御配置
    defenseConfig := DefaultDefenseIntegrationConfig()
    defenseConfig.Enabled = true              // 启用防御
    defenseConfig.AutoCancelOnToxic = true    // 毒流模式自动撤单
    defenseConfig.MaxOrdersInToxicMode = 2    // 毒流模式最大订单数
    defenseConfig.EnableSideControl = true    // 启用侧边控制
    defenseConfig.LogDefenseEvents = true     // 记录防御事件

    // 创建带防御的引擎
    engine, err := NewDefenseIntegratedEngine(engineConfig, defenseConfig)
    if err != nil {
        log.Fatalf("Failed to create engine: %v", err)
    }
    defer engine.Stop()

    // 启动引擎
    if err := engine.Start(); err != nil {
        log.Fatalf("Failed to start engine: %v", err)
    }

    log.Println("Engine started with defense system")

    // 运行一段时间
    time.Sleep(10 * time.Minute)
}
```

### 2. 手动注入市场数据（用于测试）

```go
// 模拟深度更新
engine.OnDepthUpdateWithDefense(65000.0, 65001.0, 0.2)

// 模拟成交数据
engine.OnTradeUpdateWithDefense(65000.5, 0.5, true)
```

### 3. 检查防御状态

```go
status := engine.GetDefenseStatus()
fsmStatus := status["fsm"].(map[string]interface{})
mode := fsmStatus["mode"].(string)
toxicScore := status["toxic"].(ToxicDetection).ToxicScore

log.Printf("Current mode: %s, Toxic score: %.3f", mode, toxicScore)
```

### 4. 检查是否可以下单

```go
// 检查是否允许买单
canBuy, reason := engine.CanPlaceOrder("buy", 0.01)
if !canBuy {
    log.Printf("Buy order blocked: %s", reason)
}

// 检查是否允许卖单
canSell, reason := engine.CanPlaceOrder("sell", 0.01)
if !canSell {
    log.Printf("Sell order blocked: %s", reason)
}
```

## 配置参数

### DefenseIntegrationConfig

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| Enabled | bool | true | 启用防御系统 |
| AutoCancelOnToxic | bool | true | 进入毒流模式时自动撤单 |
| MaxOrdersInToxicMode | int | 2 | 毒流模式允许的最大订单数 |
| EnableSideControl | bool | true | 启用侧边控制 |
| LogDefenseEvents | bool | true | 记录防御事件到日志 |

### 防御模式阈值

```go
// ToxicDetector 配置
toxicConfig := ToxicConfig{
    ToxicThresholdHigh:  0.8,  // >0.8 进入TOXIC模式
    ToxicThresholdMed:   0.6,  // >0.6 进入DEFENSIVE模式
    WindowSize:          100,  // 检测窗口大小
    MinTradesForDetect:  10,   // 最小交易数
}
```

## 防御行为

### NORMAL 模式
- 双边开放
- 允许所有订单
- 正常撤单频率

### DEFENSIVE 模式
- 双边开放
- 减少订单数量
- 增加撤单频率（60%）
- 订单超时：2秒

### TOXIC 模式
- 只开放安全侧
- 限制最大订单数
- 高频撤单（95%）
- 订单超时：500ms

### 侧边控制逻辑

```
Buy Pressure  (买压大)  -> 只开启卖单 (吃买盘返佣)
Sell Pressure (卖压大)  -> 只开启买单 (吃卖盘返佣)
Neutral       (中性)    -> 双边关闭
```

## 毒流检测算法

毒流分数计算：

```
ToxicScore = 0.30 * |OFI| +
             0.25 * Burst +
             0.20 * Volatility +
             0.15 * LargeTradeRatio +
             0.10 * |FlowImbalance|
```

各组件含义：
- **OFI** (Order Flow Imbalance): 订单流不平衡
- **Burst**: 成交爆发度
- **Volatility**: 短期波动率
- **LargeTradeRatio**: 大额成交比例
- **FlowImbalance**: 买卖压力不平衡

## 订单优先级计算

订单优先级基于以下风险因素：

| 因素 | 权重 | 说明 |
|------|------|------|
| 时间风险 | 25% | 订单在队列中的时间 |
| Alpha风险 | 25% | Alpha信号方向 |
| 队列位置 | 15% | 越靠后风险越高 |
| 毒流暴露 | 20% | 与毒流方向是否相反 |
| 价差风险 | 10% | 当前价差大小 |
| OFI风险 | 5% | 订单流不平衡 |

优先级等级：
- **Critical** (风险 > 0.7) - 立即撤单
- **Normal** (风险 > 0.4) - 优先撤单
- **Safe** (风险 <= 0.4) - 常规处理

## 回调函数

### 模式切换回调

```go
engine.defenseMgr.SetModeChangeCallback(func(from, to MarketMode, reason string) {
    log.Printf("Mode changed: %s -> %s (%s)", from.String(), to.String(), reason)
    
    // 发送警报
    if to == ModeToxic {
        alert.Send("High toxic flow detected!")
    }
})
```

### 撤单回调

```go
engine.defenseMgr.SetCancelCallback(func(orderID, reason string) {
    log.Printf("Cancelling order %s: %s", orderID, reason)
    
    // 实际撤单
    if err := exchange.CancelOrder(orderID); err != nil {
        log.Printf("Failed to cancel: %v", err)
    }
})
```

## 与现有系统集成

### 与风险管理器集成

防御系统与现有的RiskManager并行工作：
- RiskManager: 管理仓位、止损、爆仓风险
- DefenseManager: 管理毒流、订单优先级、侧边控制

### 与降级管理器集成

防御系统与DegradeManager互补：
- DegradeManager: 系统级保护（内存、延迟、错误率）
- DefenseManager: 市场级保护（毒流、价格操纵）

### 与执行器集成

防御系统在执行前检查：
```go
// 在 processDecision 中
if !engine.ProcessDecisionWithDefense() {
    log.Println("Decision blocked by defense system")
    return
}

// 执行订单
err := engine.executeSpotDecision(action, size, price)
```

## 监控指标

### HTTP API 端点

```go
// 获取防御状态
GET /api/v1/defense/status

// 响应示例
{
    "fsm": {
        "mode": "DEFENSIVE",
        "active_orders": 5,
        "mode_changes": 3
    },
    "toxic": {
        "toxic_score": 0.65,
        "toxic_side": "BUY_PRESSURE",
        "ofi": 0.45,
        "volatility": 0.30
    }
}
```

### Prometheus 指标

```
# 毒流分数
defense_toxic_score 0.65

# 当前模式 (0=NORMAL, 1=DEFENSIVE, 2=TOXIC)
defense_current_mode 1

# 撤单统计
defense_cancels_total{type="critical"} 12
defense_cancels_total{type="normal"} 34
defense_cancels_total{type="safe"} 8
```

## 性能优化

### 延迟指标

- 状态切换延迟: < 1ms
- 优先级计算: < 100μs (100个订单)
- 撤单决策: < 50μs
- 毒流检测: < 500μs

### 内存占用

- DefenseManager: ~5MB
- ToxicDetector: ~2MB
- 每100个订单: ~1MB

## 测试

```bash
# 运行防御相关测试
go test -v -run "TestDefense" .

# 运行全部测试
go test -v ./...

# 运行基准测试
go test -bench="BenchmarkDefense" .
```

## 故障排除

### 常见问题

**问题1: 防御系统不触发模式切换**
- 检查市场数据是否正确注入
- 检查ToxicThreshold设置
- 确认冷却期是否已结束

**问题2: 订单被错误拒绝**
- 检查当前模式
- 检查毒流方向
- 查看侧边控制状态

**问题3: 撤单不及时**
- 检查CancelCallback是否正确设置
- 检查交易所API延迟
- 考虑调整MaxOrderAge

### 调试日志

启用详细日志：
```go
defenseConfig.LogDefenseEvents = true
```

日志输出示例：
```
[DEFENSE] Mode transition: NORMAL -> DEFENSIVE (reason: toxic_score_elevated)
[DEFENSE] Cancelling order ord_123: defense_triggered
[DEFENSE] Conditions normalized, resuming normal operations
```

## 生产部署建议

1. **渐进式启用**
   - 先在模拟环境测试
   - 生产环境先启用日志不启用动作
   - 逐步放开自动撤单

2. **参数调优**
   - 根据实际毒流情况调整阈值
   - 监控误杀率
   - 优化冷却期时间

3. **监控告警**
   - 设置TOXIC模式告警
   - 监控撤单频率
   - 跟踪模式切换次数

4. **应急预案**
   - 准备手动禁用防御的开关
   - 记录模式切换历史
   - 保留订单取消日志
