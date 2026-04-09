# Go端订单防御状态机使用指南

## 概述

订单防御状态机（Order Defense FSM）是一个生产级的订单管理系统，提供三层防御机制：

1. **Normal模式** - 正常交易，双边开放
2. **Defensive模式** - 防御状态，减少暴露，提高撤单频率
3. **Toxic模式** - 毒流状态，只开启安全侧边，高频率撤单

## 核心组件

| 文件 | 组件 | 职责 |
|------|------|------|
| `order_defense_fsm.go` | OrderDefenseFSM | 订单状态机，优先级队列，撤单决策 |
| `toxic_detector.go` | ToxicDetector | 毒流检测，OFI计算，波动率监测 |
| `defense_manager.go` | DefenseManager | 整合管理器，数据摄取，循环控制 |

## 快速开始

### 1. 创建防御管理器

```go
config := DefaultDefenseManagerConfig()
config.UpdateInterval = 50 * time.Millisecond
config.EnableAutoCancel = true

dm := NewDefenseManager(config)
defer dm.Close()
```

### 2. 设置回调函数

```go
// 模式切换回调
dm.SetModeChangeCallback(func(from, to MarketMode, reason string) {
    log.Printf("Mode changed: %s -> %s (%s)", from.String(), to.String(), reason)
})

// 撤单回调
dm.SetCancelCallback(func(orderID, reason string) {
    // 调用交易所API撤单
    exchange.CancelOrder(orderID)
})
```

### 3. 注入市场数据

```go
// 从WebSocket接收成交数据
dm.OnTrade(TradeTick{
    Timestamp: time.Now(),
    Side:      "buy",
    Price:     65000.0,
    Quantity:  0.5,
})

// 从WebSocket接收市场数据
dm.OnMarketTick(MarketTick{
    Timestamp: time.Now(),
    MidPrice:  65000.5,
    BidPrice:  65000.0,
    AskPrice:  65001.0,
})
```

### 4. 添加订单

```go
order := &ManagedOrder{
    ID:            "order_123",
    Symbol:        "BTCUSDT",
    Side:          "buy",
    Price:         65000.0,
    Quantity:      0.01,
    AlphaAtEntry:  0.3,    // 入场时的Alpha信号
    QueuePosition: 0.5,    // 队列位置 (0=队首, 1=队尾)
}

if added, reason := dm.AddOrder(order); !added {
    log.Printf("Order rejected: %s", reason)
}
```

### 5. 更新订单状态

```go
// 从交易所接收成交回报
dm.UpdateOrderStatus("order_123", filledQty, avgPrice)
```

## 状态转换逻辑

```
Normal <-> Defensive <-> Toxic

转换条件：
- Toxic Score > 0.8:   Normal/Defensive -> Toxic
- Toxic Score > 0.6:   Normal -> Defensive
- Volatility > 0.8:    Normal -> Defensive
- 冷却期结束:          Toxic -> Defensive, Defensive -> Normal
```

## 各模式行为

### Normal模式
- 双边开放
- 点差倍数: 1.0x
- 订单最大年龄: 5秒
- 撤单攻击性: 0.2 (20%)

### Defensive模式
- 双边开放
- 点差倍数: 1.5x
- 订单最大年龄: 2秒
- 撤单攻击性: 0.6 (60%)
- 冷却期: 500ms

### Toxic模式
- 只开放安全侧边
- 点差倍数: 2.0x
- 订单最大年龄: 500ms
- 撤单攻击性: 0.95 (95%)
- 冷却期: 2秒

## 订单优先级计算

订单优先级基于以下风险因素：

| 因素 | 权重 | 说明 |
|------|------|------|
| 时间风险 | 25% | 订单在队列中的时间 |
| Alpha风险 | 25% | Alpha信号方向与订单方向是否匹配 |
| 队列位置 | 15% | 越靠后风险越高 |
| 毒流暴露 | 20% | 订单方向与毒流方向是否相反 |
| 价差风险 | 10% | 当前价差大小 |
| OFI风险 | 5% | 订单流不平衡 |

优先级分为：
- **Critical** (风险 > 0.7) - 立即撤单
- **Normal** (风险 > 0.4) - 优先撤单
- **Safe** (风险 <= 0.4) - 常规处理

## 侧边控制策略

在Toxic模式下，根据毒流方向决定开启哪一侧：

```
Buy Pressure  -> 只开启卖单 (吃买盘返佣)
Sell Pressure -> 只开启买单 (吃卖盘返佣)
Neutral       -> 双边关闭
```

## 完整集成示例

```go
package main

import (
    "log"
    "time"
)

func main() {
    // 创建防御管理器
    dm := NewDefenseManager(DefaultDefenseManagerConfig())
    defer dm.Close()

    // 设置回调
    dm.SetCancelCallback(func(orderID, reason string) {
        log.Printf("Cancelling order %s: %s", orderID, reason)
        // exchange.CancelOrder(orderID)
    })

    // 模拟WebSocket数据流
    go func() {
        for {
            // 接收市场数据
            dm.OnMarketTick(MarketTick{
                Timestamp: time.Now(),
                MidPrice:  getMidPrice(),
            })

            // 接收成交数据
            dm.OnTrade(TradeTick{
                Timestamp: time.Now(),
                Side:      getTradeSide(),
                Price:     getTradePrice(),
                Quantity:  getTradeQty(),
            })

            time.Sleep(10 * time.Millisecond)
        }
    }()

    // 提交订单
    order := &ManagedOrder{
        ID:            "test_001",
        Symbol:        "BTCUSDT",
        Side:          "buy",
        Price:         65000.0,
        Quantity:      0.01,
        AlphaAtEntry:  getCurrentAlpha(),
        QueuePosition: estimateQueuePosition(),
    }

    if added, reason := dm.AddOrder(order); added {
        log.Println("Order added successfully")
    } else {
        log.Printf("Order rejected: %s", reason)
    }

    // 监控状态
    for {
        state := dm.GetCurrentState()
        log.Printf("Current mode: %s, Toxic score: %.3f",
            state["fsm"].(map[string]interface{})["mode"],
            state["toxic"].(ToxicDetection).ToxicScore)

        time.Sleep(time.Second)
    }
}
```

## 性能指标

- 状态切换延迟: < 1ms
- 优先级计算: < 100μs (100个订单)
- 撤单决策: < 50μs
- 内存占用: ~10MB (1000个订单)

## 测试

```bash
# 运行FSM测试
go test -v -run TestOrderDefenseFSM .

# 运行优先级队列测试
go test -v -run TestOrderPriorityQueue .

# 运行模式转换测试
go test -v -run TestModeTransition .

# 运行订单拒绝测试
go test -v -run TestOrderRejection .

# 运行所有测试
go test -v .
```

## 注意事项

1. **冷却期**: Toxic模式有2秒冷却期，Defensive模式有500ms冷却期
2. **撤单回调**: 需要在SetCancelCallback中实现实际的交易所撤单逻辑
3. **Alpha信号**: 需要在添加订单时提供准确的AlphaAtEntry值
4. **队列位置**: QueuePosition越接近0表示越靠近队首，风险越低

## 扩展开发

### 自定义毒流检测算法

```go
type CustomToxicDetector struct {
    ToxicDetector
}

func (ctd *CustomToxicDetector) calculateToxicScore(...) float64 {
    // 自定义算法
    return customScore
}
```

### 自定义策略

```go
func getCustomPolicy(mode MarketMode) ExecutionPolicy {
    policy := getDefaultDefensePolicy(mode)
    // 自定义参数
    policy.CancelAggressiveness = 0.8
    return policy
}
```
