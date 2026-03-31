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

**目标**: 实现币安 WebSocket 用户数据流监听

**任务细节**:
- [ ] 实现 `user_data_stream.go`
  - 订阅账户更新 (balance, position)
  - 订阅订单更新 (executionReport)
  - 订阅成交更新 (trade)
- [ ] 实现 ListenKey 管理
  - 获取 ListenKey (POST /api/v3/userDataStream)
  - 定时续期 (PUT, 每30分钟)
  - 异常时重新获取
- [ ] 集成到 WebSocket 管理器
  - 支持多路复用 (市场数据 + 用户数据)
  - 独立重连机制

**验收标准**:
```go
// 可以实时接收订单状态变更
ws.SubscribeUserData(func(event *OrderUpdateEvent) {
    orderFSM.HandleEvent(event)
})
```

---

### P5-102: 订单对账机制 (Order Reconciliation)

**目标**: 确保本地订单状态与交易所一致

**任务细节**:
- [ ] 实现 `reconciler.go`
  - 定期查询未成交订单状态 (GET /api/v3/openOrders)
  - 比对本地订单与交易所订单
  - 检测不一致并修复
- [ ] 实现差异检测逻辑
  - 本地有、交易所无 → 订单可能已成交/取消
  - 本地无、交易所有 → 漏单，需要同步
  - 状态不一致 → 以交易所为准更新
- [ ] 集成到主引擎
  - 每 30 秒自动对账
  - 对账失败时告警

**验收标准**:
```go
// 自动检测并修复状态不一致
result := reconciler.Reconcile(ctx)
// result.Mismatches 应该为 0
```

---

### P5-103: 订单恢复 (Order Recovery)

**目标**: 系统崩溃后重建订单状态

**任务细节**:
- [ ] 扩展 WAL 恢复逻辑
  - 从 WAL 重放订单事件
  - 重建订单状态机
  - 恢复仓位信息
- [ ] 实现 `recovery_manager.go`
  - 启动时自动检查上次状态
  - 查询交易所确认存活订单
  - 合并 WAL 记录与交易所状态
- [ ] 实现优雅关闭
  - 关闭前创建 checkpoint
  - 等待所有订单确认

**验收标准**:
```go
// 模拟崩溃后恢复
recoveryManager.Recover(ctx)
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
| Phase 1 | OrderManager | 🚧 进行中 | 60% |
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
