# P10 Windows 本地联调指南

本文档指导你在 Windows 环境下完成 Go 引擎与 Python P10 的双端联调。

## 系统要求

- Windows 10/11
- Go 1.21+
- Python 3.10+
- PowerShell 或 CMD

## 端口映射

| 服务 | 端口 | 说明 |
|------|------|------|
| Go HTTP API | 8080 | Risk Kernel 数据接口 |
| Go Metrics | 9090 | Prometheus 指标 |
| Python P10 | 8000 | 决策层指标 |

## 快速启动

### 1. 启动 Go 引擎

打开 PowerShell 或 CMD：

```powershell
cd D:\binance\new

# 方式1: 使用批处理脚本
scripts\start_go_engine.bat btcusdt paper

# 方式2: 手动构建运行
cd core_go
go build -o hft_engine_http.exe main_with_http.go
.\hft_engine_http.exe btcusdt paper
```

你应该看到输出：
```
[MAIN] Engine fully started. Press Ctrl+C to stop.
[MAIN] Available endpoints:
       - http://localhost:8080/api/v1/risk/stats
       - http://localhost:8080/api/v1/system/metrics
       - http://localhost:8080/api/v1/status
       - http://localhost:9090/metrics
```

### 2. 验证 Go 端点

另开一个终端：

```powershell
# 测试 Risk Stats
curl http://localhost:8080/api/v1/risk/stats

# 测试 System Metrics
curl http://localhost:8080/api/v1/system/metrics

# 测试 Prometheus Metrics
curl http://localhost:9090/metrics | findstr hft_engine
```

### 3. 运行 Python 联调测试

```powershell
cd D:\binance\new
python integration_go_python.py
```

测试将执行：
1. 端口可用性检查
2. Go API 端点验证
3. Prometheus 指标检查
4. 端到端延迟测量
5. 数据过期场景模拟

### 4. 启动完整 P10 系统

```powershell
cd D:\binance\new

# 方式1: 使用测试脚本
python test_metrics_endpoint.py

# 方式2: 使用完整演示
python hedge_fund_os\demo_integration_test.py --quick
```

## 故障排查

### 问题1: 连接被拒绝

**症状**: `Connection refused` 或 `无法连接`

**解决**:
1. 确认 Go 引擎已启动
2. 检查 Windows 防火墙
3. 尝试使用 `127.0.0.1` 代替 `localhost`

```powershell
# 检查端口占用
netstat -an | findstr 8080
netstat -an | findstr 9090
```

### 问题2: 高延迟 (>100ms)

**症状**: `avg latency > 100ms`

**解决**:
- Windows IPv6 解析问题，改用 `127.0.0.1`
- 检查是否有杀毒软件扫描 HTTP 流量
- 任务管理器中提升进程优先级

### 问题3: 指标不一致

**症状**: Python 和 Go 的 drawdown 数值不一致

**解决**:
- 检查 `GoEngineClient` 的 base_url 是否指向正确端口
- 确认 `PnLSignal.from_dict()` 正确解析了所有字段

## 性能优化 (Windows 特供)

### 提升进程优先级

```powershell
# 找到 Go 引擎进程 PID，然后:
$proc = Get-Process -Name "hft_engine_http"
$proc.PriorityClass = "High"
```

### 禁用 Windows 防火墙 (开发环境)

```powershell
# 以管理员运行
netsh advfirewall set allprofiles state off
```

### 使用 127.0.0.1 避免 IPv6

在配置文件中确保使用 `127.0.0.1` 而非 `localhost`:

```python
# hedge_fund_os/go_client.py
base_url = "http://127.0.0.1:8080"  # 不是 localhost
```

## 验证清单

在部署到云南/柬埔寨前，确认以下检查项：

- [ ] Go 引擎编译成功
- [ ] HTTP API (8080) 可访问
- [ ] Prometheus (9090) 可访问
- [ ] Python P10 (8000) 可访问
- [ ] 端到端延迟 < 50ms
- [ ] 模式切换 (GROWTH→SURVIVAL) 正常工作
- [ ] 决策日志写入 logs/ 目录
- [ ] 指标中包含 `hfos_system_mode`
- [ ] 指标中包含 `hft_engine_memory_usage_bytes`

## 下一步

本地联调通过后：

1. **安装 Prometheus** 抓取两个端点
2. **配置 AlertManager** 推送告警到手机
3. **打包部署文档** 用于云南/柬埔寨服务器
