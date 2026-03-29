# 运维手册（Runbook）
<!-- AUTO-GENERATED -->

## 部署流程

### 环境准备

```bash
# 1. 确认 PostgreSQL 正在运行
pg_isready -h localhost -p 5432

# 2. 确认 Redis 可达（WSL2 环境）
redis-cli -h 192.168.18.62 ping
# 期望输出：PONG

# 3. 安装依赖
npm install
pip install -r requirements.txt

# 4. 检查环境变量
python verify_trading_config_simple.py
```

### 数据库初始化

```bash
# 首次部署（创建所有表）
npm run init-db

# 迁移指标数据表（升级已有库）
npm run migrate-db

# 测试数据库连接
npm run test-db
```

### 数据获取与更新

```bash
# 从币安 API 获取最新 K 线数据（存入 PostgreSQL）
npm run fetch-db

# 计算并更新技术指标
npm run indicators
```

### 启动主系统

```bash
# Node.js 数据服务
npm start

# Python 完整交易系统（含回测）
python main_trading_system.py

# AI 驱动交易演示（规则版，无需 GPU）
python demo_ai_trading.py
```

### 启动 trading_system（Phase 1–3）

```bash
# 1. 先训练模型（首次使用或每周重训）
python -m training_system.train \
    --db --symbol BTCUSDT --interval 1h \
    --out models/lgbm_btc_1h.txt \
    --trials 30 --train-size 700 --test-size 150

# 2. 启动 paper trading 循环
python -m trading_system.trader

# 3. 切换到 Regime 感知策略（在 trader.py 中修改一行后重启）
# self.strategy = RegimeAwareLGBMStrategy("models/lgbm_btc_1h.txt")
```

## 健康检查

### 数据库健康检查

```bash
# 检查 PostgreSQL 连接
npm run test-db

# 检查表是否存在（使用实际 DB_NAME）
psql -h localhost -U postgres -d binance -c "\dt"
# 期望看到：symbols, trade_calendar, klines, ticker_24hr, order_book, indicator_configs, indicator_values
```

### Redis 健康检查

```bash
# 本机 Redis
redis-cli ping

# WSL2 中的 Redis
wsl -u root redis-cli -h 192.168.18.62 ping

# Python 连接测试
python test_redis_simple.py

# Node.js 连接测试
node test_redis_connection.js
```

### 插件系统健康检查

```python
from plugins.manager import PluginManager
from plugins.reliable_event_bus import ReliableEventBus

event_bus = ReliableEventBus(name="HealthCheck")
event_bus.start()
plugin_manager = PluginManager(event_bus=event_bus)

for name, plugin in plugin_manager.get_all_plugins().items():
    health = plugin.health_check()
    print(f"{name}: {'健康' if health.healthy else '不健康'} - {health.message}")
```

## 常见问题与修复

### 数据库连接失败

**症状**：`ECONNREFUSED` 或 `Connection refused`

```bash
# 检查 PostgreSQL 是否运行
pg_isready -h localhost -p 5432

# 启动 PostgreSQL（Windows 服务）
net start postgresql-x64-14

# 验证密码（默认：见 .env 中的 DB_PASSWORD）
psql -h localhost -U postgres -d binance
```

### Redis 连接失败（WSL2）

**症状**：`Connection timed out` 或 `ECONNREFUSED`

```bash
# 获取 WSL2 IP 地址
wsl hostname -I

# 在 WSL2 中启动 Redis
wsl -u root service redis-server start

# 更新 .env 中的 REDIS_HOST 为 WSL2 IP
REDIS_HOST=<wsl2-ip>
```

### 币安 API 限流

**症状**：HTTP 429 错误或 `Too Many Requests`

- 检查 API 密钥是否正确配置（`.env` 中的 `BINANCE_API_KEY`）
- 降低请求频率，增加请求间隔
- 使用数据库缓存，减少重复 API 调用

### Python 模块找不到

**症状**：`ModuleNotFoundError`

```bash
# 重新安装依赖
pip install -r requirements.txt

# 确认 PyTorch 已安装（强化学习功能）
python -c "import torch; print(torch.__version__)"

# 验证项目结构
python verify_structure.py
```

### 数据泄露警告（ML 回测）

**症状**：回测收益异常高，过拟合

- 确认使用 `TimeSeriesSplit` 而非随机分割
- 检查特征是否使用了未来数据（前向偏差）
- 参考 `models/model_trainer.py` 中的时间序列分割实现

## 回滚流程

### 插件灰度回滚

```python
from plugins.rollout_manager import RolloutManager

rollout_manager = RolloutManager()

# 检查当前发布状态
status = rollout_manager.get_rollout_status("plugin_name")
print(status)

# 执行回滚
rollout_manager.rollback_rollout("canary_plan_name")
```

### 代码回滚

```bash
# 查看最近提交
git log --oneline -10

# 回滚到特定提交（保留工作区修改）
git reset <commit-sha>

# 强制回滚到特定提交（谨慎使用）
git reset --hard <commit-sha>
```

### 数据库回滚

```bash
# 重新初始化数据库（会清空数据，谨慎使用）
# npm run init-db

# 使用 PostgreSQL 备份恢复（推荐）
pg_restore -h localhost -U postgres -d binance backup.dump
```

## 监控与告警

### 关键指标

| 指标 | 正常范围 | 告警阈值 |
|------|----------|----------|
| 单笔仓位 | ≤ 20% 总资金 | > 20% |
| 总仓位 | ≤ 80% 总资金 | > 80% |
| 日亏损 | ≤ 5% 总资金 | > 5% |
| 最大回撤 | ≤ 10% | > 10% |
| API 错误率 | < 1% | > 5% |
| 数据库连接池 | < 80% 使用率 | > 90% |

### EquityMonitor 警报读取

```python
from trading_system.monitor import EquityMonitor

# 每次交易后系统自动输出警报日志
# 日志格式：
# WARNING  风控警报 | 净值=9800.00 回撤=-2.00% 日盈亏=-200.00

# 手动查看当前状态
monitor = trader.monitor
print(monitor.summary())
# {'equity': 9800.0, 'peak': 10000.0, 'drawdown': -0.02, 'daily_pnl': -200.0, 'alert': False}
```

### 风险熔断条件

系统在以下情况会自动暂停交易：

1. 日亏损超过 `5%`（`RiskManager` 熔断）
2. 账户回撤超过 `10%`（`EquityMonitor` 告警）
3. 总仓位超过 `80%`（`MAX_POSITION_SIZE`）
4. 连续亏损 5 笔（`max_loss_streak`）
5. 连续 API 失败超过阈值
6. 市场处于高波动状态（`RegimeAwareLGBMStrategy` 返回 HOLD）

### 告警升级

1. **数据异常**：检查 `npm run fetch-db` 是否正常运行
2. **策略问题**：运行 `python demo_standalone.py` 验证策略逻辑
3. **系统故障**：检查 PostgreSQL、Redis 服务状态
4. **API 限流**：暂停自动化任务，等待限流窗口重置
