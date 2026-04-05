# 贡献指南

> HFT 延迟队列 RL 系统开发指南

---

<!-- AUTO-GENERATED: Development Setup -->
## 开发环境设置

### 前置要求

| 工具 | 版本 | 用途 |
|------|------|------|
| Python | 3.10+ | AI层开发 |
| Go | 1.21+ | 执行引擎开发 |
| Git | 2.30+ | 版本控制 |

### 安装步骤

#### 1. 克隆仓库

```bash
git clone <repository-url>
cd new
```

#### 2. Python 环境设置

```bash
# 创建虚拟环境 (推荐)
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
pip install -r brain_py/requirements.txt  # 额外ML依赖
```

#### 3. Go 环境设置

```bash
cd core_go

# 下载依赖
go mod download

# 验证安装
go version
go env GOPATH
```

<!-- END AUTO-GENERATED -->

---

<!-- AUTO-GENERATED: Available Scripts -->
## 可用脚本和命令

### 启动脚本

| 命令 | 描述 | 模式 |
|------|------|------|
| `python start_live_trader.py --symbol BTCUSDT --capital 1000` | 启动实盘/模拟交易者 | 主入口 |
| `python start_live_trader.py --spot-margin --margin-mode cross --max-leverage 3` | 启用现货杠杆交易 | 3x杠杆 |
| `python start_data_collection.py --duration 24` | 24小时信号统计数据收集 | 分析模式 |
| `python start_trader.py --mode paper --symbol BTCUSDT` | 启动交易者 (模拟模式) | 回测 |
| `python start_ab_test.py` | 启动A/B测试框架 | 策略对比 |
| `python start_full_autoresearch_trading.py` | 启动全自动研究交易 | 研究模式 |

### 监控与诊断

| 命令 | 描述 | 用途 |
|------|------|------|
| `python check_signal_stats.py` | 查看信号聚合统计报告 | 阈值优化 |
| `python check_live_stats.py` | 实时检查运行中统计 | 监控 |
| `python stability_monitor.py` | 系统稳定性监控 | 健康检查 |
| `python generate_report.py` | 生成交易报告 | 绩效分析 |
| `python shm_check.py` | 共享内存检查 | 调试 |

### 测试命令

| 命令 | 描述 | 覆盖范围 |
|------|------|----------|
| `python -m pytest brain_py/test_self_evolving.py -v` | 自进化Meta-Agent测试 | 9项测试 |
| `python -m pytest brain_py/test_pbt.py -v` | PBT训练器测试 | 9项测试 |
| `python -m pytest brain_py/ab_testing/test_ab_testing.py -v` | A/B测试框架测试 | 统计检验 |
| `python -m pytest brain_py/tests/test_live_integrator_moe.py -v` | MoE集成测试 | 专家融合 |
| `python -m pytest brain_py/qlib_models/tests/ -v` | Qlib模型测试 | 21项测试 |
| `python tests/test_regime_detector_pressure.py` | RegimeDetector压力测试 | 异步/并发测试 |
| `python tests/test_sharedmemory_benchmark.py` | SharedMemory基准测试 | 序列化性能 |
| `go test ./core_go/... -v` | Go单元测试 | 67+项测试 |
| `python end_to_end_test.py` | 端到端集成测试 | 全流程验证 |
| `python test_ab_simple.py` | 简单A/B测试演示 | 快速验证 |

### 构建命令

| 命令 | 描述 | 输出 |
|------|------|------|
| `go build -o hft_engine.exe ./core_go` | 构建Go执行引擎 | `hft_engine.exe` (8.4MB) |
| `go build -o hft_engine ./core_go` | Linux/Mac构建 | `hft_engine` |

<!-- END AUTO-GENERATED -->

---

<!-- AUTO-GENERATED: Testing Procedures -->
## 测试流程

### 单元测试

```bash
# Python测试
cd brain_py
python -m pytest test_self_evolving.py -v
python -m pytest test_pbt.py -v

# Go测试
cd ../core_go
go test -v ./...
```

### 集成测试

```bash
# 端到端测试
cd ..
python end_to_end_test.py

# 简单E2E测试
python e2e_simple.py
```

### 测试覆盖率要求

| 模块 | 最低覆盖率 | 当前状态 |
|------|-----------|----------|
| brain_py | 80% | ✅ 通过 |
| core_go | 70% | ✅ 通过 |

<!-- END AUTO-GENERATED -->

---

<!-- AUTO-GENERATED: Code Style -->
## 代码规范

### Python

- 遵循 PEP 8 规范
- 使用类型注解
- 最大行长度: 100字符
- 函数文档字符串使用 Google Style

### Go

- 使用 `gofmt` 格式化
- 遵循 Effective Go 指南
- 包名使用小写
- 导出的符号需要注释

### 提交信息格式

```
<type>: <description>

[optional body]
```

类型:
- `feat`: 新功能
- `fix`: 修复
- `refactor`: 重构
- `docs`: 文档
- `test`: 测试
- `chore`: 杂项

<!-- END AUTO-GENERATED -->

---

## PR 提交清单

- [ ] 代码已通过本地测试
- [ ] 新增功能包含测试
- [ ] 文档已更新
- [ ] 提交信息符合规范
- [ ] 无合并冲突

---

*本文档由 Claude Code 自动生成，最后更新: 2026-04-05*
