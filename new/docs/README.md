# HFT 延迟队列 RL 系统 - 项目文档

> 本文档目录包含项目所有的架构设计、项目管理和技术文档。

---

## 文档导航

### 📐 架构设计文档

| 文档 | 说明 | 状态 |
|------|------|------|
| [ARCHITECTURE_OVERVIEW.md](./ARCHITECTURE_OVERVIEW.md) | 整合后的系统架构总览 | ✅ 已创建 |
| [总纲.txt](../总纲.txt) | 原始差距分析文档 | 📄 原始 |
| [总纲2.txt](../总纲2.txt) | 核心理念与范式 | 📄 原始 |
| [总纲3.txt](../总纲3.txt) | 架构蓝图与演进 | 📄 原始 |

### 📋 项目管理文档

| 文档 | 说明 | 状态 |
|------|------|------|
| [PROJECT_UPGRADE_PLAN.md](./PROJECT_UPGRADE_PLAN.md) | v2.5 → v5.0 升级计划 | ✅ 已创建 |
| [project_management/TASK_TRACKING.md](./project_management/TASK_TRACKING.md) | 任务跟踪表 | ✅ 已创建 |
| [project_management/DECISION_RECORDS.md](./project_management/DECISION_RECORDS.md) | 架构决策记录 | ✅ 已创建 |
| [project_management/REQUIREMENTS_SPEC.md](./project_management/REQUIREMENTS_SPEC.md) | 需求规格说明书 | ✅ 已创建 |
| [project_management/MEETING_TEMPLATE.md](./project_management/MEETING_TEMPLATE.md) | 会议纪要模板 | ✅ 已创建 |

### 💻 技术参考文档

| 文档 | 说明 | 状态 |
|------|------|------|
| [新文件5.txt](../新文件5.txt) | 概率引擎设计 | 📄 原始 |
| [新文件6.txt](../新文件6.txt) | RL训练框架 | 📄 原始 |
| [新文件6-1.txt](../新文件6-1.txt) | PPO稳定训练 | 📄 原始 |
| [新文件7.txt](../新文件7.txt) | Meta-Agent与MoE | 📄 原始 |
| [新文件8.txt](../新文件8.txt) | 订单流Alpha | 📄 原始 |
| [新文件9.txt](../新文件9.txt) | 执行与部署 | 📄 原始 |
| [新文件10.txt](../新文件10.txt) | 完整系统集成 | 📄 原始 |

---

## 快速开始

### 1. 了解项目架构

阅读 [ARCHITECTURE_OVERVIEW.md](./ARCHITECTURE_OVERVIEW.md) 获取系统全貌。

### 2. 查看升级计划

阅读 [PROJECT_UPGRADE_PLAN.md](./PROJECT_UPGRADE_PLAN.md) 了解从v2.5到v5.0的演进路径。

### 3. 跟踪任务进度

查看 [project_management/TASK_TRACKING.md](./project_management/TASK_TRACKING.md) 了解当前迭代状态。

### 4. 查看决策记录

查看 [project_management/DECISION_RECORDS.md](./project_management/DECISION_RECORDS.md) 了解关键决策背景。

---

## 文档更新指南

### 何时更新

- **ARCHITECTURE_OVERVIEW.md**: 架构变更、新组件添加
- **PROJECT_UPGRADE_PLAN.md**: 里程碑调整、任务重新分配
- **TASK_TRACKING.md**: 每日任务状态更新
- **DECISION_RECORDS.md**: 新的关键决策

### 更新流程

1. 在原始设计文档（总纲/新文件X.txt）中记录想法
2. 整合更新到 ARCHITECTURE_OVERVIEW.md
3. 同步更新 PROJECT_UPGRADE_PLAN.md 中的相关Phase
4. 更新 TASK_TRACKING.md 中的任务状态

---

## 项目状态概览

```
当前版本: v2.5 (原型)
目标版本: v5.0 (生产级)

Phase 1: 强化执行层 [████████░░] 80% (基础完成，待实盘)
Phase 2: 丰富决策层 [░░░░░░░░░░] 0%
Phase 3: 增加杠杆交易 [░░░░░░░░░░] 0%
Phase 4: 生产级功能 [░░░░░░░░░░] 0%

关键成就:
✅ Shared Memory对齐完成
✅ Go Engine构建成功 (8.4MB)
⚠️  PyTorch依赖待安装
⚠️  实盘API接入待开发
```

---

## 联系信息

- 项目路径: `D:\binance\new`
- 主代码: `hft_latency_queue_rl_system_go_python (7).py`
- Go引擎: `core_go/hft_engine.exe`

---

*本文档目录由 Claude Code 于 2026-03-30 创建和维护。*
