# HFT System - Project Agents Specification
高频交易延迟队列RL系统 - 开发规范文档

## 1. 项目概述

这是一个**高频交易（HFT）延迟队列强化学习系统**，采用 Go + Python 混合架构：

- **Go 引擎**: 负责微秒级市场数据接收、订单执行、共享内存通信
- **Python Agent**: SAC 强化学习智能体，生成交易决策
- **共享内存**: 零拷贝 IPC，144-byte mmap 协议
- **币安集成**: WebSocket 实时数据流（testnet/mainnet）

## 2. 技术栈

| 组件 | 技术 | 职责 |
|------|------|------|
| 执行引擎 | Go 1.21+ | WebSocket、订单执行、风控、WAL |
| RL 智能体 | Python 3.10+ | SAC 算法、决策生成 |
| 通信 | mmap | 跨语言共享内存（128/144 byte） |
| 数据源 | Binance WebSocket | L2订单簿、成交流 |
| 测试 | pytest + Go test | 单元测试、集成测试、E2E测试 |

## 3. 初始化流程

```bash
# 一键初始化项目
chmod +x init.sh
./init.sh
```

## 4. 开发规范

### 4.1 代码规范
- Go: 遵循 `go fmt` 和 `go vet`，函数小于50行，文件小于800行
- Python: PEP 8，类型注解，函数小于50行
- 错误处理: 所有错误必须显式处理，禁止吞掉错误
- 不可变性: 优先创建新对象，避免修改现有对象

### 4.2 测试规范
- 所有新功能必须有单元测试（覆盖率 > 80%）
- 修改核心组件必须运行 E2E 测试
- 提交前必须确保 `test_system.py` 通过

### 4.3 Git 工作流
```
feat: 新功能
fix: 修复问题
docs: 文档更新
test: 测试相关
refactor: 重构
perf: 性能优化
```

## 5. 关键文件说明

| 文件/目录 | 说明 |
|-----------|------|
| `core_go/` | Go 执行引擎源码 |
| `brain_py/` | Python RL 智能体 |
| `protocol.h` | 共享内存协议定义（128-byte struct） |
| `end_to_end_test.py` | 完整集成测试 |
| `test_system.py` | 系统功能测试 |
| `config/default.yaml` | 默认配置 |

## 6. 常用命令

```bash
# 构建 Go 引擎
cd core_go && go build -o hft_engine.exe .

# 运行端到端测试
python end_to_end_test.py

# 运行系统测试
python test_system.py

# 启动引擎（测试网）
cd core_go && ./hft_engine.exe btcusdt

# 启动 Python Agent
cd brain_py && python agent.py
```

## 7. 架构图

```
┌─────────────────┐     WebSocket      ┌─────────────────┐
│  Binance API    │◄──────────────────►│   Go Engine     │
│  (Testnet)      │                    │  - WS Feed      │
└─────────────────┘                    │  - Matching     │
                                       │  - Executor     │
                                       │  - Risk Mgr     │
                                       └────────┬────────┘
                                                │ mmap
                                                │ 128-byte
                                       ┌────────▼────────┐
                                       │  Shared Memory  │
                                       └────────┬────────┘
                                                │
                                       ┌────────▼────────┐
                                       │  Python Agent   │
                                       │  - SAC RL       │
                                       │  - Decision     │
                                       └─────────────────┘
```

## 8. 注意事项

1. **代理设置**: 中国大陆用户需要设置 HTTP_PROXY/HTTPS_PROXY
2. **测试网端点**: `wss://stream.testnet.binance.vision`（2024年5月更新）
3. **共享内存对齐**: Go 使用 8-byte 对齐，Python 需匹配 struct layout
4. **权限**: Windows 下 mmap 不需要特殊权限，Unix 需要

## 9. 故障排除

| 问题 | 解决方案 |
|------|----------|
| WebSocket 连接超时 | 检查代理设置，尝试测试网 |
| Bad handshake | 确认使用正确的测试网端点 |
| SHM 通信失败 | 检查 struct 大小和对齐（128 bytes） |
| 权限拒绝 | 确保有写入 data/ 目录的权限 |

## 10. 协作规范

- **代码审查**: 所有核心修改需通过 code-reviewer agent
- **测试驱动**: 新功能先用 tdd-guide agent 写测试
- **安全检查**: 涉及交易执行的代码需 security-reviewer 审查
- **文档更新**: 修改 protocol 或 API 需同步更新本文档

---
*Last Updated: 2026-03-30*
