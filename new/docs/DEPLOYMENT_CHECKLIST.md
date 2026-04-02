# P10 Hedge Fund OS - 部署检查清单

## 云南/柬埔寨部署前必读

---

## 📦 硬件要求

| 组件 | 最低配置 | 推荐配置 |
|------|----------|----------|
| CPU | i5-8400 / Ryzen 5 2600 | **i9-13900H** (已验证) |
| RAM | 8GB | 32GB+ |
| 存储 | 100GB SSD | 500GB NVMe |
| 网络 | 10Mbps | 50Mbps+ (低延迟) |
| 系统 | Windows 10 | Windows 11 |

---

## 🚀 快速部署步骤

### 1. 环境准备 (5分钟)

```powershell
# 安装 Go (如果需重新编译)
# https://golang.org/dl/
go version

# 安装 Python
# https://python.org
python --version

# 安装依赖
pip install requests numpy
```

### 2. 冷启动检查 (2分钟)

```powershell
scripts\cold_start_check.bat
```

预期输出:
```
[OK] hft_engine_http.exe found
[OK] Python 3.10.x
[OK] Binance latency: 45ms
[OK] Ports available
[OK] System ready for live trading
```

### 3. 性能验证 (3分钟)

```powershell
scripts\start_go_engine.bat btcusdt paper
# 另开终端
python performance_benchmark.py --quick
```

**关键指标**:
- HTTP Latency Mean: **< 10ms** (目标 < 5ms)
- Mode Switch: **< 100ms**
- Decision Chain: **< 10ms**

### 4. 启动实盘 (Paper Trading)

```powershell
# 方式1: 启动全套
START.bat

# 方式2: 手动
scripts\start_go_engine.bat btcusdt paper
python -m hedge_fund_os.orchestrator
```

---

## 📊 监控验证

启动后验证以下端点:

| 端点 | 命令 | 预期输出 |
|------|------|----------|
| Go API | `curl http://127.0.0.1:8080/api/v1/risk/stats` | JSON with daily_pnl |
| Go Metrics | `curl http://127.0.0.1:9090/metrics` | hft_engine_* metrics |
| Python P10 | `curl http://127.0.0.1:8000/metrics` | hfos_* metrics |

---

## ⚠️ 常见问题

### Q1: 编译失败

**症状**: `go build` 报错

**解决**:
```powershell
cd core_go
go mod tidy
go build -o hft_engine_http.exe main_with_http.go
```

### Q2: 延迟过高 (>50ms)

**症状**: performance_benchmark.py 显示 mean > 50ms

**解决**:
1. 检查是否使用 `127.0.0.1` 而非 `localhost`
2. 关闭 Windows Defender 实时保护
3. 提升进程优先级:
   ```powershell
   $proc = Get-Process -Name "hft_engine_http"
   $proc.PriorityClass = "High"
   ```

### Q3: Binance API 连接超时

**症状**: 网络延迟 > 200ms

**解决**:
- 考虑使用 AWS Tokyo 或 Singapore VPS
- 检查本地网络是否有代理/VPN

---

## 🔐 安全建议

1. **API Key 管理**
   - 使用 Binance Testnet 首次验证
   - 限制 API Key 权限 (仅交易, 不提现)
   - 定期轮换 API Key

2. **资金安全**
   - Paper Trading 模式运行至少 1 周
   - 首次实盘使用 < 10% 资金
   - 设置每日最大亏损限制

3. **日志审计**
   - 定期查看 `logs/decisions/*.jsonl`
   - 监控 `logs/` 目录大小
   - 备份重要日志到云端

---

## 📞 紧急处理

| 情况 | 症状 | 操作 |
|------|------|------|
| 系统无响应 | CPU 100% | Ctrl+C 停止, 检查 logs/error.log |
| 持续亏损 | Drawdown > 10% | 自动进入 SURVIVAL, 人工确认后继续 |
| 网络中断 | Stale Data > 5s | 自动 Shutdown, 检查网络后重启 |
| 误触发 | 频繁模式切换 | 调整 Risk Kernel 阈值 |

---

## ✅ 最终检查清单

部署前确认:

- [ ] 冷启动检查通过
- [ ] 性能基准 < 10ms
- [ ] Paper Trading 模式运行正常
- [ ] 决策日志正常写入
- [ ] Prometheus 指标可访问
- [ ] 手机/邮件告警配置完成
- [ ] API Key 权限正确
- [ ] 资金分配策略已确认
- [ ] 每日最大亏损限制已设置
- [ ] 备份策略已配置

**全部勾选后, 可以开始实盘交易。**

---

## 🎯 成功标准

运行 24 小时后检查:

1. **系统稳定性**: 无崩溃, 无内存泄漏
2. **延迟表现**: P99 < 20ms
3. **风控触发**: 正确进入 SURVIVAL/CRISIS
4. **日志完整性**: 决策日志无缺失
5. **收益曲线**: 回撤 < 5%

---

**祝交易顺利! 🚀**
