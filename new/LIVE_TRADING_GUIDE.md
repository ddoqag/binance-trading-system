# 实盘测试指南 (Live Trading Guide)

## 阶段一：模拟盘测试 (Paper Trading) - 必需

### 1.1 启动命令
```bash
# Windows
cd D:\binance\new\core_go
start_paper_trading.bat

# 或手动启动
go run . --symbol=BTCUSDT --paper-trading --metrics-port=2112
```

### 1.2 监控指标
```bash
# 查看实时指标
curl http://localhost:2112/metrics

# 检查系统状态
curl http://localhost:8080/api/v1/status
```

### 1.3 测试清单
- [ ] 引擎启动无错误
- [ ] WebSocket连接稳定
- [ ] 订单生成正常（查看日志中的[PAPER]标记）
- [ ] 风控系统响应正常
- [ ] 运行至少24小时无异常

### 1.4 预期结果
- 交易频率：3-5笔/小时
- 手续费：2bps（Maker）
- 日收益：0.1-0.3%（目标）

---

## 阶段二：小资金实盘 ($100-500) - 推荐

### 2.1 启动前检查
```bash
# 1. 确认API密钥有效
python -c "from binance.client import Client; c = Client(); print(c.ping())"

# 2. 检查账户余额
python -c "
from binance.client import Client
import os
client = Client(
    os.getenv('BINANCE_API_KEY'),
    os.getenv('BINANCE_API_SECRET')
)
account = client.get_account()
usdt = [a for a in account['balances'] if a['asset'] == 'USDT'][0]
print(f'USDT Balance: {usdt[\"free\"]}')
"
```

### 2.2 启动实盘
```bash
# 修改配置文件：关闭paper trading
cd D:\binance\new\core_go
# 编辑 config.json: "paper_trading": false

# 启动（生产模式）
go run . --symbol=BTCUSDT --config=live.json
```

### 2.3 风险控制参数
```json
{
  "paper_trading": false,
  "max_position": 0.15,
  "max_trades_per_min": 3,
  "min_expected_value_bps": 2.0,
  "kill_switch_enabled": true,
  "max_daily_loss_pct": 2.0,
  "max_drawdown_pct": 5.0
}
```

---

## 阶段三：监控与维护

### 3.1 Telegram通知（可选）
```bash
# 设置环境变量
set TELEGRAM_BOT_TOKEN=your_token
set TELEGRAM_CHAT_ID=your_chat_id
```

### 3.2 关键监控指标
| 指标 | 正常范围 | 告警阈值 |
|------|----------|----------|
| 延迟 | <10ms | >50ms |
| 错误率 | <0.1% | >1% |
| 日亏损 | <2% | >5% (Kill Switch) |
| 交易频率 | 3-5笔/小时 | >10笔/小时 |

### 3.3 紧急停止
```bash
# 方法1：HTTP API
curl -X POST http://localhost:8080/api/v1/emergency-stop

# 方法2：直接终止进程
Ctrl+C 或 kill -TERM <pid>
```

---

## 故障排除

### 问题1: WebSocket断开
**解决**: 系统会自动重连，如频繁断开检查网络或代理设置

### 问题2: 订单被拒绝
**解决**: 检查 `POST_ONLY` 订单是否价格 crossed，调整 tick_size

### 问题3: 内存过高
**解决**: 调整日志级别，限制历史数据存储

---

## 收益预期

| 阶段 | 资金 | 周期 | 目标收益 | 风险 |
|------|------|------|----------|------|
| Paper | $10k虚拟 | 1-3天 | 验证稳定性 | 无 |
| 小资金 | $100-500 | 1周 | 0.5-1% /天 | 低 |
| 中等 | $1k-5k | 1月 | 0.3-0.8% /天 | 中 |
| 全仓 | $10k+ | 持续 | 0.2-0.5% /天 | 高 |

---

**警告**: 实盘交易有风险，建议先用模拟盘验证至少24小时。
