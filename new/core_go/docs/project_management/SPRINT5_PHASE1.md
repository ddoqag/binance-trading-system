# Sprint 5 Phase 1: OrderManager 订单生命周期管理

## 概述

基于 14 阶段演进路线图，Sprint 5 聚焦 **Phase 1: OrderManager**，实现完整的 WebSocket 订单生命周期管理，为实盘交易打下基础。

---

## 当前状态

### 已完成基础

| 组件 | 文件 | 状态 |
|------|------|------|
| 订单状态机 | `order_fsm.go` | ✅ 基础状态定义 |
| WebSocket 管理器 | `websocket_manager.go` | ✅ 连接管理 |
| 订单执行器 | `executor.go` | ✅ 模拟执行 |
| 杠杆执行器 | `margin_executor.go` | ✅ 杠杆支持 |
| WAL 日志 | `wal.go` | ✅ 批量异步写入 |

### 缺失功能

| 功能 | 优先级 | 说明 |
|------|--------|------|
| WebSocket 用户数据流 | P0 | 监听订单/成交推送 |
| 订单对账机制 | P0 | 本地与交易所状态同步 |
| 订单恢复 | P1 | 崩溃后重建订单状态 |
| 订单超时处理 | P1 | 未成交订单自动取消 |

---

## Sprint 5 任务清单

### P5-101: WebSocket 用户数据流 (User Data Stream)

**状态**: ✅ 已完成

**实现文件**: `user_data_stream.go` (294 lines)

**实现内容**:
- ✅ `UserDataStreamManager` 结构
  - 订单 FSM 注册/注销 (`RegisterOrderFSM` / `UnregisterOrderFSM`)
  - 事件处理器设置 (`SetHandlers`)
  - 自动重连机制 (`connectionManager`)
- ✅ ListenKey 管理 (复用 `LiveAPIClient`)
  - 自动续期 (30分钟间隔)
  - 异常时指数退避重连 (5s → 60s)
- ✅ 事件路由
  - 订单更新 → OrderFSM 状态转换
  - 余额更新 → 用户回调
  - Binance 状态映射到 OrderState

**关键代码**:
```go
manager := NewUserDataStreamManager(client, nil)
manager.RegisterOrderFSM(orderID, fsm)
manager.SetHandlers(
    func(update *OrderUpdate) { /* handle order */ },
    func(update *BalanceUpdate) { /* handle balance */ },
    func(err error) { /* handle error */ },
)
manager.Start() // 自动重连，后台运行
```

**提交**: `17152f1`

---

### P5-102: 订单对账机制 (Order Reconciliation)

**状态**: ✅ 已完成

**实现文件**: `reconciler.go` (544 lines)

**实现内容**:
- ✅ `Reconciler` 结构
  - 定时对账 (默认 30s)
  - 手动对账 (`ForceReconcile`)
  - 自动修复模式 (`autoRepair`)
  - 统计指标 (`ReconcilerStats`)
- ✅ 差异检测
  - 状态不匹配 (`OrderMismatch`)
  - 漏单检测 (`MissingOrder`)
  - 孤儿订单 (`OrphanOrder`)
- ✅ 自动修复
  - 状态同步：以交易所为准
  - 漏单导入：自动添加到本地
  - 孤儿订单：查询交易所确认状态
- ✅ 集成
  - 与 `OrderExecutor` 集成
  - 使用 `LiveAPIClient` 查询
  - WAL 记录所有修复操作

**关键代码**:
```go
reconciler := NewReconciler(executor, client, wal, nil)
reconciler.Start() // 后台定时对账

// 手动对账
result, _ := reconciler.ForceReconcile(ctx)
// result.Mismatches, result.Missing, result.Orphans
```

**提交**: `e2cd4ce`

**验收标准**:
```go
// 自动检测并修复状态不一致
result := reconciler.Reconcile(ctx)
// result.Mismatches 应该为 0
```

---

### P5-103: 订单恢复 (Order Recovery)

**状态**: ✅ 已完成

**实现文件**: `recovery_manager.go` (613 lines)

**实现内容**:
- ✅ `OrderRecoveryManager` 结构
  - 启动时自动恢复 (`Recover`)
  - 三种恢复策略：checkpoint → WAL → exchange
  - 自动 checkpoint 创建 (默认 5 分钟间隔)
- ✅ Checkpoint 系统
  - JSON 格式状态快照
  - 自动清理旧 checkpoint (保留最近 10 个)
  - 优雅关闭时创建最终 checkpoint
- ✅ 状态验证
  - 恢复后与交易所对比验证
  - 记录验证统计

**关键代码**:
```go
recoveryManager := NewOrderRecoveryManager(executor, client, wal, nil)
recoveryManager.Start() // 后台自动创建 checkpoint

// 系统启动时恢复
result, _ := recoveryManager.Recover(ctx)
// result.Method: "checkpoint" | "wal" | "exchange"
// result.OrdersRecovered: 恢复的订单数量
```

**提交**: `d3e8360`

**验收标准**:
```go
// 模拟崩溃后恢复
result := recoveryManager.Recover(ctx)
// result.Success == true
// 所有存活订单状态正确恢复
```

---

### P5-104: 订单超时处理

**目标**: 未成交订单自动管理

**任务细节**:
- [ ] 实现超时检测
  - 限价单超时 (默认 5 分钟)
  - 部分成交超时处理
- [ ] 实现自动取消策略
  - 超时自动撤单
  - 可配置超时时间
  - 撤单失败时重试
- [ ] 集成到订单状态机
  - Timeout 事件处理
  - 超时统计记录

---

## 14 阶段路线图进度

| 阶段 | 名称 | 当前状态 | 进度 |
|------|------|----------|------|
| Phase 1 | OrderManager | 🚧 进行中 | 75% |
| Phase 2 | MarketRegimeDetector | ✅ 已完成 | 100% |
| Phase 3 | Self-Evolving Meta-Agent | ❌ 未开始 | 0% |
| Phase 4 | PBT | ❌ 未开始 | 0% |
| Phase 5 | Auto-Strategy Synthesis | ❌ 未开始 | 0% |
| Phase 6 | Self-Play Trading | ❌ 未开始 | 0% |
| Phase 7 | Real→Sim→Real | ❌ 未开始 | 0% |
| Phase 8 | World Model | ❌ 未开始 | 0% |
| Phase 9 | Agent Civilization | ❌ 未开始 | 0% |
| Phase 10 | Autonomous Hedge Fund OS | ❌ 未开始 | 0% |
| Phase 11 | Multi-Fund AI Economy | ❌ 未开始 | 0% |
| Phase 12 | Control Plane | ❌ 未开始 | 0% |
| Phase 13 | SM-FRE | ❌ 未开始 | 0% |
| Phase 14 | Financial Singularity | ❌ 未开始 | 0% |

---

## 依赖关系

```
P5-101 (User Data Stream)
    ↓
P5-102 (Reconciliation)
    ↓
P5-103 (Recovery)
    ↓
P5-104 (Timeout)
```

---

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| WebSocket 延迟导致状态滞后 | 高 | 结合 REST API 对账 |
| 对账频率过高触发限流 | 中 | 智能对账 (仅检查未成交) |
| 恢复时订单已成交 | 高 | 查询交易所最终状态为准 |

---

## 时间估算

| 任务 | 预估工时 |
|------|----------|
| P5-101 | 2 天 |
| P5-102 | 2 天 |
| P5-103 | 1.5 天 |
| P5-104 | 1 天 |
| **总计** | **6.5 天** |

---

## 相关文件

```
core_go/
├── order_fsm.go              # 订单状态机 (已存在)
├── websocket_manager.go      # WebSocket 管理 (已存在)
├── wal.go                    # WAL 日志 (已存在)
├── user_data_stream.go       # P5-101 新建
├── reconciler.go             # P5-102 新建
├── recovery_manager.go       # P5-103 新建
└── docs/project_management/
    ├── SPRINT5_PHASE1.md     # 本文档
    └── TASK_TRACKING.md      # 任务跟踪
```

---

**创建日期**: 2026-03-31
**目标完成**: 2026-04-07
**负责人**: Trading System Team
