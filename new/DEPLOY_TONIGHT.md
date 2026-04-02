# P10 今晚部署操作手册

## 前提条件确认

打开 PowerShell，依次执行：

```powershell
# 1. 确认当前目录
cd D:\binance\new
pwd

# 2. 确认依赖
pip list | findstr prometheus

# 3. 确认端口可用
netstat -an | findstr "8080\|9090\|8000"
# 应该没有输出（表示端口空闲）
```

---

## 部署步骤

### 步骤 1: 构建 Go 引擎（如未编译）

```powershell
cd core_go
go build -o hft_engine_http.exe main_with_http.go
cd ..
```

**成功标志**: 生成 `core_go\hft_engine_http.exe` 文件

---

### 步骤 2: 启动 Go 引擎

```powershell
# 终端 1
cd core_go
.\hft_engine_http.exe btcusdt paper
```

**验证启动成功**:
- 看到 `[MAIN] Engine fully started`
- 另开终端测试: `curl http://127.0.0.1:8080/api/v1/status`

---

### 步骤 3: 启动 Python P10

```powershell
# 终端 2
cd D:\binance\new
python hedge_fund_os\demo_full.py
```

---

### 步骤 4: 验证指标暴露

```powershell
# 终端 3 - 验证 Go 指标
curl http://127.0.0.1:8080/api/v1/risk/stats
curl http://127.0.0.1:9090/metrics | findstr "hft_engine_"

# 验证 Python 指标
curl http://127.0.0.1:8000/metrics | findstr "hfos_"
```

---

## 观察清单（今晚重点）

### 1. ENS 监控

```powershell
# 每 5 分钟检查一次
while ($true) {
    $ens = curl -s http://127.0.0.1:8000/metrics | findstr "hfos_strategy_ens"
    Write-Host "$(Get-Date -Format 'HH:mm:ss') - ENS: $ens"
    Start-Sleep 300
}
```

**警戒值**:
- ENS > 3.0: ✅ 正常
- ENS 2.0-3.0: ⚠️ 关注
- ENS < 2.0: 🔴 检查策略共振

---

### 2. 延迟监控

```powershell
# 测试延迟
python benchmark_python_core.py

# 预期结果:
# Total Cycle Time: < 2ms (良好)
# P99: < 5ms (优秀)
```

---

### 3. 决策日志检查

```powershell
# 查看最新日志
tail -n 5 logs\decisions\*.jsonl

# 检查是否有错误
findstr "error\|ERROR" logs\decisions\*.jsonl
```

---

## 明日检查项

### 收盘后分析

```powershell
# 统计今日决策次数
(Get-Content logs\decisions\*.jsonl).Count

# 查看模式切换次数
findstr '"target_mode":' logs\decisions\*.jsonl | findstr -v "GROWTH"

# 检查最大回撤
python -c "
import json
max_dd = 0
for line in open('logs/decisions/decisions_20260402.jsonl'):
    d = json.loads(line)
    dd = d.get('risk', {}).get('daily_drawdown', 0)
    max_dd = max(max_dd, dd)
print(f'Max Drawdown: {max_dd:.2%}')
"
```

---

## 紧急处理

### 如果 Go 引擎崩溃

```powershell
# 检查错误日志
type core_go\engine.log

# 重启
cd core_go
.\hft_engine_http.exe btcusdt paper
```

### 如果 Python 报错

```powershell
# 查看 Python 错误
python hedge_fund_os\demo_full.py 2>&1 | tee error.log
```

### 完全重启

```powershell
# 停止所有进程
taskkill /f /im hft_engine_http.exe
taskkill /f /im python.exe

# 重新启动
# 按步骤 1-3 执行
```

---

## 联系支持

如遇到问题：
1. 查看 `docs/WINDOWS_INTEGRATION_GUIDE.md`
2. 检查 Git 提交历史确认文件完整
3. 保存错误日志以便分析

---

**祝今晚 Paper Trading 顺利！** 🚀
