# ARCHITECTURE_SUMMARY.md 对比分析

## 一、文档对比总览

| 文档 | 行数 | 主要用途 | 侧重点 |
|------|------|----------|--------|
| `docs/ARCHITECTURE_OVERVIEW.md` | 998 | 完整架构设计 | 理论设计 + 实现细节 |
| `CLAUDE.md` | 459 | Claude Code 指引 | 开发命令 + 常用操作 |
| `README.md` | 281 | 项目概览 | 快速开始 + 状态 |
| **ARCHITECTURE_SUMMARY.md (新)** | 362 | 入口流程总结 | 执行流程 + 结构图 |

---

## 二、ARCHITECTURE_SUMMARY.md 的独特价值

### 2.1 与 ARCHITECTURE_OVERVIEW.md 的区别

| 方面 | ARCHITECTURE_OVERVIEW.md | ARCHITECTURE_SUMMARY.md |
|------|--------------------------|------------------------|
| **定位** | 完整设计文档 | 快速参考手册 |
| **内容深度** | 998行详细设计 | 362行精炼总结 |
| **主要读者** | 架构师/核心开发者 | 新成员/运维人员 |
| **核心章节** | ShadowMatcher v3 详细设计 | 入口流程 + 执行循环 |
| **代码示例** | 多(训练框架/数据结构) | 少(流程图为主) |
| **数据流图** | 有(复杂) | 有(简化) |

### 2.2 新增内容（现有文档中分散或未明确）

#### 1. 入口流程完整图示
```
main.go → NewHFTEngine → Start → 三大循环
```
- **来源**: 分散在 `main_default.go`, `engine.go` 中
- **ARCHITECTURE_SUMMARY.md**: 第一次完整串联

#### 2. processDecision 详细流程
```
读取决策 → 降级检查 → 风险检查 → 防御检查 → 执行
```
- **来源**: `engine.go:279-350`
- **ARCHITECTURE_OVERVIEW.md**: 只提 SAC Agent 决策
- **ARCHITECTURE_SUMMARY.md**: 包含降级/风控/防御三层检查

#### 3. 防御系统 FSM 图示
```
NORMAL → DEFENSIVE → TOXIC (带冷却回退)
```
- **来源**: `order_defense_fsm.go`, `DEFENSE_INTEGRATION_GUIDE.md`
- **ARCHITECTURE_OVERVIEW.md**: 未包含（P10 之后新增）
- **ARCHITECTURE_SUMMARY.md**: 完整状态机图

#### 4. 共享内存布局图
```
Offset 0: Header
Offset 64: MarketSnapshot
Offset 4096: AIContext
...
```
- **来源**: `protocol.go`, `shared/protocol.h`
- **ARCHITECTURE_OVERVIEW.md**: 提及 mmap 但未详述布局
- **ARCHITECTURE_SUMMARY.md**: 详细偏移量表

---

## 三、内容覆盖对比

### 3.1 三层架构表示对比

#### ARCHITECTURE_OVERVIEW.md (原)
```
Python AI 大脑层
    ↓↑ mmap + Sequence Lock
Go 执行引擎层 (神经末梢)
    ↓↑ WebSocket + REST API
币安交易所
```

#### ARCHITECTURE_SUMMARY.md (新)
```
┌─ Python AI 层 ─┐    ┌─ Go 引擎层 ─┐    ┌─ 币安 ─┐
│ Meta-Agent     │ ←→ │ HFTEngine   │ ←→ │ 交易所 │
│ MoE            │mmap│ Defense FSM │WS  │        │
│ SAC/PPO        │    │ RiskManager │    │        │
│ Qlib           │    │ Executors   │    │        │
└────────────────┘    └─────────────┘    └────────┘
```

**改进点**:
- 更清晰的模块对应关系
- 明确通信方式 (mmap / WebSocket)
- 突出 Defense FSM 新组件

### 3.2 核心模块对比

| 模块 | ARCHITECTURE_OVERVIEW | ARCHITECTURE_SUMMARY | 差异 |
|------|----------------------|---------------------|------|
| **Meta-Agent** | 有 | 有 | 相同 |
| **MoE 系统** | 有 | 有 | 相同 |
| **SAC Agent** | 有(v3 Hazard) | 有(简化) | SUMMARY 简化为执行优化 |
| **ShadowMatcher** | 详细(v2/v3) | 无 | OVERVIEW 特有 |
| **Defense FSM** | 无 | 详细 | SUMMARY 特有 |
| **WAL/Recovery** | 提及 | 详细 | SUMMARY 补充 |
| **STP** | 无 | 有 | SUMMARY 特有 |

---

## 四、建议使用场景

### 4.1 ARCHITECTURE_OVERVIEW.md
- **何时使用**: 深入理解系统设计，实现新功能
- **目标读者**: 核心开发者，架构师
- **关键章节**: 
  - ShadowMatcher v3 设计
  - SAC + Queue Dynamics 训练框架
  - Level 2.5 撮合引擎原理

### 4.2 ARCHITECTURE_SUMMARY.md
- **何时使用**: 快速了解系统入口和流程
- **目标读者**: 新成员，运维，面试官
- **关键章节**:
  - 入口流程图
  - processDecision 流程
  - 防御系统状态机
  - 共享内存布局

### 4.3 CLAUDE.md
- **何时使用**: 日常开发操作
- **目标读者**: Claude Code 使用者
- **关键章节**:
  - 常用命令
  - 测试方法
  - 项目结构

---

## 五、缺失内容建议

### 5.1 建议添加到 ARCHITECTURE_SUMMARY.md

1. **Python AI 层详细流程**
   - `live_integrator.py` 主循环
   - MoE 融合权重计算
   - SAC 动作解码

2. **训练流程**
   - ShadowMatcher v3 训练数据流
   - 对抗训练流程

3. **部署架构**
   - 生产环境拓扑
   - Docker 容器关系

### 5.2 建议从现有文档同步

| 内容 | 来源文档 | 建议位置 |
|------|----------|----------|
| 毒流检测算法公式 | `DEFENSE_INTEGRATION_GUIDE.md` | 防御系统章节 |
| 模型管理器热更新 | `CLAUDE.md` | 工程加固章节 |
| 监控指标列表 | `MONITORING_SETUP.md` | 可观测性章节 |

---

## 六、总结

### ARCHITECTURE_SUMMARY.md 的核心价值

1. **流程导向**: 从入口到执行的完整流程图
2. **快速参考**: 362行 vs 998行，适合快速查阅
3. **新组件覆盖**: Defense FSM、STP 等 P10 后新增组件
4. **结构清晰**: ASCII 图示多，适合快速理解架构

### 三文档互补关系

```
新成员入门: README.md → ARCHITECTURE_SUMMARY.md → 开发
日常开发:   CLAUDE.md (命令参考)
深度开发:   ARCHITECTURE_OVERVIEW.md (详细设计)
运维排查:   ARCHITECTURE_SUMMARY.md (流程图) + RUNBOOK.md
```

---

*对比分析时间: 2026-04-07*
