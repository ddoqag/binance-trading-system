# P10 Trading System - 实盘前检查清单 (Production Checklist)

> ⚠️ **重要**: 在切换到 LIVE 模式之前，必须完成以下所有检查项。

---

## 🔴 Phase 1: 环境检查

### Python 环境
- [ ] Python 版本 >= 3.9
- [ ] 所有依赖已安装: `pip install -r requirements.txt`
- [ ] `hmmlearn` 已安装（可选但推荐）: `conda install -c conda-forge hmmlearn`

### 系统环境
- [ ] Windows 系统已配置 `HTTP_PROXY` 和 `HTTPS_PROXY`（如在中国大陆）
- [ ] 代理端口 7897 可用: `Test-NetConnection -ComputerName 127.0.0.1 -Port 7897`
- [ ] 磁盘空间充足（日志可能增长很快）
- [ ] 系统时间已同步（NTP）

---

## 🟠 Phase 2: 配置检查

### API 密钥
- [ ] Binance API Key 和 Secret 已设置
- [ ] 使用的是 **Testnet** 密钥（paper 模式）
- [ ] API 权限: 只开启 **读取** 和 **交易** 权限，**禁止提现**
- [ ] IP 白名单已配置（如使用）

### 配置文件
```yaml
# config/default.yaml 检查项
trading:
  symbol: "BTCUSDT"          # 确认交易对
  mode: "paper"              # ⚠️ 必须是 paper 或 testnet，不能是 live
  max_position: 0.01         # 最大仓位（BTC）
  
risk:
  daily_loss_limit: -100     # 日亏损限制（USDT）
  max_drawdown: 0.15         # 最大回撤 15%
  kill_switch_enabled: true  # 启用紧急停止

regime_detector:
  enabled: true
  fit_interval_ticks: 1000   # 每 1000 tick 更新模型
  
alert:
  enabled: true
  min_level: "warning"       # 最小告警级别
  # 配置至少一个通知渠道
  dingtalk_webhook: "https://..."
  telegram_bot_token: "xxx"
  telegram_chat_id: "xxx"
```

---

## 🟡 Phase 3: 内存与性能检查

### 内存隔离确认
- [ ] `_train_model_task` 中没有引用外部全局变量
- [ ] 数据库连接池不在子进程中创建
- [ ] 所有传入子进程的参数都是可序列化的（numpy array, int, str）

### 磁盘 IO 节流
- [ ] 历史数据已预加载到内存 `deque(maxlen=5000)`
- [ ] 主循环中没有文件读写操作
- [ ] 日志使用异步写入或缓冲

### 性能基准
运行压力测试并确认：
```bash
python tests/test_regime_detector_pressure.py
```
- [ ] p50 延迟 < 0.5ms
- [ ] p99 延迟 < 1.0ms
- [ ] 成功率 > 99%

---

## 🟢 Phase 4: 异常处理检查

### 告警通知
- [ ] 告警配置已填写（钉钉/飞书/Telegram 至少一个）
- [ ] 测试告警发送成功:
```python
python -c "
import asyncio
from core.alert_notifier import AlertNotifier

async def test():
    notifier = AlertNotifier(
        telegram_bot_token='xxx',
        telegram_chat_id='xxx'
    )
    await notifier.send_alert(
        level='warning',
        title='测试告警',
        message='如果收到这条消息，说明告警配置正确'
    )

asyncio.run(test())
"
```

### 关键异常捕获点
检查以下位置都有异常捕获和告警：
- [ ] `detect_async()` - 推理失败告警
- [ ] `_async_fit()` - 模型训练失败告警
- [ ] `execute_strategy()` - 订单执行失败告警
- [ ] WebSocket 连接断开 - 重连告警

### 优雅关闭
- [ ] `KeyboardInterrupt` (Ctrl+C) 能正确关闭所有资源
- [ ] `detector.shutdown()` 被调用
- [ ] 进程池已关闭，无僵尸进程

---

## 🔵 Phase 5: 模拟盘测试

### Paper Trading 验证
运行至少 24 小时模拟盘：
```bash
python start_trader.py --mode paper --symbol BTCUSDT --duration 86400
```

检查日志：
- [ ] 无异常崩溃
- [ ] 延迟稳定在 < 1ms
- [ ] Regime 切换正常（趋势/震荡/高波动）
- [ ] 订单执行符合预期（paper 模式下模拟成交）

### 关键指标监控
```bash
# 实时监控
tail -f logs/trading.log | grep -E "(ERROR|CRITICAL|latency|regime)"
```

- [ ] 无 ERROR 级别日志
- [ ] 无 CRITICAL 级别日志
- [ ] latency 稳定在 0.3-0.8ms
- [ ] regime 切换频率合理（不过于频繁）

---

## 🟣 Phase 6: 紧急预案

### Kill Switch 测试
- [ ] 手动触发紧急停止: `python scripts/kill_switch.py`
- [ ] 确认所有订单已取消
- [ ] 确认仓位已平仓

### 网络中断恢复
- [ ] 断开网络 30 秒，观察系统行为
- [ ] 恢复网络，确认自动重连
- [ ] 确认数据连续性（无大段空缺）

### 系统崩溃恢复
- [ ] 模拟进程崩溃（`kill -9`）
- [ ] 确认 WAL 日志已写入
- [ ] 重启后能从断点恢复

---

## ⚫ Phase 7: 切换到实盘 (LIVE)

### 最终确认
- [ ] 已完成至少 7 天模拟盘交易
- [ ] 夏普比率 > 0.5（或达到预期）
- [ ] 最大回撤 < 15%
- [ ] 胜率 > 45%（或达到预期）

### 实盘配置
```bash
# 确认使用 live 模式
export BINANCE_API_KEY=your_live_key
export BINANCE_API_SECRET=your_live_secret
export USE_TESTNET=false

# 初始资金建议
INITIAL_CAPITAL=1000  # 先小额测试
```

### 启动命令
```bash
# 建议加上所有保护
python start_trader.py \
    --mode live \
    --symbol BTCUSDT \
    --capital 1000 \
    --max-position 0.001 \
    --enable-kill-switch \
    --alert-level critical
```

---

## 📋 签字确认

在完成以上所有检查项后，由负责人签字：

| 角色 | 姓名 | 日期 | 签字 |
|------|------|------|------|
| 策略负责人 | ______ | ______ | ______ |
| 技术负责人 | ______ | ______ | ______ |
| 风控负责人 | ______ | ______ | ______ |

---

## 🆘 紧急联系

| 问题类型 | 联系人 | 联系方式 |
|----------|--------|----------|
| 技术故障 | ______ | ______ |
| 策略异常 | ______ | ______ |
| 风控事件 | ______ | ______ |

---

**最后更新**: 2026-04-02
**版本**: v1.0
