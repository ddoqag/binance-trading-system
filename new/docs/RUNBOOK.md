# 运维手册

> HFT 延迟队列 RL 系统运维指南

---

<!-- AUTO-GENERATED: Deployment Procedures -->
## 部署流程

### 生产环境部署

#### 1. 预部署检查

```bash
# 验证Go引擎构建
cd core_go
go build -o hft_engine.exe .
ls -lh hft_engine.exe  # 应约为8.4MB

# 验证Python环境
python -c "import brain_py; print('OK')"

# 运行测试套件
go test ./...
python -m pytest brain_py/test_*.py -v
```

#### 2. 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑必要配置
vim .env
```

必需配置项:
- `BINANCE_API_KEY`
- `BINANCE_API_SECRET`
- `RISK_MAX_POSITION`
- `LOG_LEVEL`

#### 3. 启动服务

```bash
# 方式1: 启动交易者 (推荐)
python start_live_trader.py --symbol BTCUSDT --capital 1000

# 方式2: 启用现货杠杆交易 (3x Cross)
python start_live_trader.py --symbol BTCUSDT --capital 1000 \
    --spot-margin --margin-mode cross --max-leverage 3

# 方式3: 24小时信号统计数据收集
python start_data_collection.py --symbol BTCUSDT --capital 1000 \
    --spot-margin --margin-mode cross --max-leverage 3 --duration 24

# 方式4: 使用Go引擎 + Python Agent
cd core_go
./hft_engine.exe &
cd ../brain_py
python agent.py
```

<!-- END AUTO-GENERATED -->

---

<!-- AUTO-GENERATED: Health Checks -->
## 健康检查

### 系统状态检查

```bash
# 检查共享内存
cd ..
python shm_check.py

# 检查WebSocket连接
curl -s http://localhost:8080/health

# 查看信号统计（运行中）
python check_live_stats.py

# 生成详细统计报告
python check_signal_stats.py

# 查看日志
tail -f logs/hft_engine.log
tail -f logs/agent.log
```

### 关键指标

| 指标 | 正常范围 | 告警阈值 |
|------|----------|----------|
| 检测延迟 | < 1ms | > 2ms |
| 延迟 | < 10ms | > 50ms |
| WebSocket重连次数 | 0-1/小时 | > 5/小时 |
| 订单成功率 | > 99% | < 95% |
| 内存使用 | < 500MB | > 1GB |
| HMM训练成功率 | > 95% | < 90% |

### 监控端点

| 端点 | 说明 |
|------|------|
| `/health` | 基础健康检查 |
| `/metrics` | Prometheus指标 |
| `/status` | 详细系统状态 |

<!-- END AUTO-GENERATED -->

---

<!-- AUTO-GENERATED: Common Issues -->
## 常见问题及修复

### 问题1: WebSocket连接断开

**症状**: 日志显示 "WebSocket disconnected"

**修复**:
```bash
# 检查网络连接
ping stream.binance.com

# 重启WebSocket管理器
# 系统会自动重连，如持续失败:
python -c "from core_go.websocket_manager import *; reconnect()"
```

### 问题2: 共享内存访问失败

**症状**: "mmap: cannot allocate memory"

**修复**:
```bash
# 清理现有共享内存
python shm_check.py --cleanup

# 重启服务
pkill hft_engine
./hft_engine.exe
```

### 问题3: 订单被拒绝

**症状**: "Order rejected: insufficient balance"

**修复**:
```bash
# 检查账户余额
python -c "from core_go.live_api_client import *; check_balance()"

# 检查风险配置
cat config/risk_config.yaml
```

### 问题4: RegimeDetector 高延迟

**症状**: 市场状态检测延迟 > 2ms

**修复**:
1. 检查是否使用 `detect_async()` 而非 `detect()`
2. 检查后台训练是否阻塞 (查看 `_fit_in_progress`)
3. 减少 HMM 状态数或特征窗口
4. 启用 fallback 模式

```python
# 检查性能统计
detector = MarketRegimeDetector()
stats = detector.get_performance_stats()
print(f"P99: {stats['detection_latency_ms']['p99']:.2f}ms")
```

### 问题5: 高延迟

**症状**: 延迟持续 > 50ms

**修复**:
1. 检查服务器位置 (应靠近币安服务器)
2. 检查网络质量
3. 降低策略复杂度
4. 启用降级模式

```bash
# 启用降级模式
curl -X POST http://localhost:8080/degrade/enable
```

<!-- END AUTO-GENERATED -->

---

<!-- AUTO-GENERATED: Rollback Procedures -->
## 回滚流程

### 快速回滚

```bash
# 1. 停止当前服务
pkill hft_engine
pkill python

# 2. 切换到上一个版本
git checkout HEAD~1

# 3. 重新构建
cd core_go
go build -o hft_engine.exe .

# 4. 启动服务
./hft_engine.exe
```

### 数据库回滚

```bash
# 如果有WAL日志，可以恢复状态
python -c "from core_go.wal import *; recover_from_wal()"
```

<!-- END AUTO-GENERATED -->

---

<!-- AUTO-GENERATED: Alerting -->
## 告警与升级

### 告警级别

| 级别 | 触发条件 | 响应时间 |
|------|----------|----------|
| P0 (Critical) | 订单执行失败 / 资金风险 | 立即 |
| P1 (High) | WebSocket断开 / 高延迟 | 5分钟 |
| P2 (Medium) | 内存使用高 | 30分钟 |
| P3 (Low) | 测试失败 | 下次迭代 |

### 升级路径

1. **L1**: 自动恢复 (系统内置)
2. **L2**: 人工介入 (运维团队)
3. **L3**: 开发团队介入
4. **L4**: 紧急停机

### 紧急停机

```bash
# 立即停止所有交易
pkill -9 hft_engine

# 取消所有未成交订单
python -c "from core_go.live_api_client import *; cancel_all_orders()"

# 检查账户状态
python -c "from core_go.live_api_client import *; get_account_status()"
```

<!-- END AUTO-GENERATED -->

---

## 联系信息

- 项目负责人: Claude
- 项目路径: `D:\binance\new`
- 文档更新: 通过 `/update-docs` 命令

---

*本文档由 Claude Code 自动生成，最后更新: 2026-04-05*
