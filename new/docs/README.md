# HFT 延迟队列 RL 系统 - 项目文档

> 本文档目录包含项目所有的架构设计、项目管理和技术文档。

---

## 文档导航

### 📐 架构设计文档

| 文档 | 说明 | 状态 |
|------|------|------|
| [ARCHITECTURE_OVERVIEW.md](./ARCHITECTURE_OVERVIEW.md) | 整合后的系统架构总览 | ✅ 已更新 |
| [总纲.txt](../总纲.txt) | 原始差距分析文档 | 📄 原始 |
| [总纲2.txt](../总纲2.txt) | 核心理念与范式 | 📄 原始 |
| [总纲3.txt](../总纲3.txt) | 架构蓝图与演进 | 📄 原始 |

### 🚀 开发与运维文档

| 文档 | 说明 | 状态 |
|------|------|------|
| [CONTRIBUTING.md](./CONTRIBUTING.md) | 开发环境设置与贡献指南 | ✅ 已创建 |
| [RUNBOOK.md](./RUNBOOK.md) | 部署流程与运维手册 | ✅ 已创建 |

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

<!-- AUTO-GENERATED: Project Status -->
## 项目状态概览

```
当前版本: v4.0 RC (Sprint 2 完成)
目标版本: v5.0 (生产级)

Phase 1: OrderManager        [██████████] 100% ✅
Phase 2: MarketRegimeDetector [██████████] 100% ✅
Phase 3: Self-Evolving Agent  [██████████] 100% ✅
Phase 4: PBT                  [██████████] 100% ✅
Phase 5-9: 高级AI模块          [██████████] 100% ✅
Phase 10-14: 远期目标          [░░░░░░░░░░] 0%

关键成就:
✅ Phases 1-9 全部完成 (9/14 = 64%)
✅ Shared Memory对齐完成
✅ Go Engine构建成功 (8.4MB)
✅ 67+ 项测试全部通过
✅ Binance实盘API集成完成
```
<!-- END AUTO-GENERATED -->

---

<!-- AUTO-GENERATED: Dependencies -->
## 依赖清单

### Python 依赖 (requirements.txt)

| 包 | 版本 | 用途 |
|----|------|------|
| numpy | >=1.24.0 | 数值计算 |
| torch | >=2.0.0 | 深度学习 (SAC/PPO) |
| pyyaml | >=6.0 | 配置解析 |
| hmmlearn | >=0.3.0 | 市场状态检测 (HMM) |
| arch | >=6.0.0 | 波动率建模 (GARCH) |
| scikit-learn | >=1.3.0 | 机器学习工具 |

### Go 依赖 (go.mod)

| 包 | 版本 | 用途 |
|----|------|------|
| gorilla/websocket | v1.5.3 | WebSocket连接 |
| adshao/go-binance/v2 | v2.8.10 | Binance API SDK |
| prometheus/client_golang | v1.23.2 | 监控指标 |
| shopspring/decimal | v1.4.0 | 精确小数计算 |

<!-- END AUTO-GENERATED -->

---

<!-- AUTO-GENERATED: Available Commands -->
## 可用命令参考

### Python 模块

| 命令 | 说明 |
|------|------|
| `python -m brain_py.test_self_evolving` | 运行自进化Meta-Agent测试 (9项) |
| `python -m brain_py.test_pbt` | 运行PBT训练器测试 (9项) |
| `python hft_latency_queue_rl_system_go_python\ \(7\).py` | 运行完整HFT系统 |
| `python end_to_end_test.py` | 运行端到端集成测试 |

### Go 命令

| 命令 | 说明 |
|------|------|
| `go build -o hft_engine.exe .` | 构建Go执行引擎 |
| `go test ./...` | 运行所有Go测试 |
| `go test -v ./... -run Integration` | 运行集成测试 |

### 开发工作流

```bash
# 1. 安装Python依赖
pip install -r brain_py/requirements.txt

# 2. 构建Go引擎
cd core_go && go build -o hft_engine.exe .

# 3. 运行Python测试
cd brain_py && python -m pytest test_self_evolving.py test_pbt.py -v

# 4. 运行Go测试
cd core_go && go test -v ./...

# 5. 运行完整系统
python "hft_latency_queue_rl_system_go_python (7).py"
```

<!-- END AUTO-GENERATED -->

---

## 联系信息

- 项目路径: `D:\binance\new`
- 主代码: `hft_latency_queue_rl_system_go_python (7).py`
- Go引擎: `core_go/hft_engine.exe`

---

*本文档目录由 Claude Code 于 2026-03-30 创建和维护。*
