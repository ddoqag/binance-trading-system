# 现货杠杆实盘交易系统完整指南

## 目录
1. [系统概述](#系统概述)
2. [架构设计](#架构设计)
3. [文件结构](#文件结构)
4. [配置说明](#配置说明)
5. [启动流程](#启动流程)
6. [API接口](#api接口)
7. [风控系统](#风控系统)
8. [故障排查](#故障排查)
9. [安全须知](#安全须知)

---

## 系统概述

### 什么是现货杠杆实盘交易系统？

这是一个**工业级高频交易执行系统**，采用 Go + Python 双引擎架构：

- **Go 引擎**: 微秒级延迟，负责订单执行、WebSocket连接、风控、杠杆交易
- **Python 策略**: SAC强化学习、毒流检测、队列优化、点差捕获
- **通信方式**: HTTP API (RESTful接口)

### 核心功能

| 模块 | 功能 | 技术实现 |
|------|------|----------|
| 队列优化 | 永远在队列前30%位置 | SimpleQueueOptimizer |
| 毒流检测 | 马氏距离检测异常流 | ToxicFlowDetector |
| 点差捕获 | Spread ≥ 2 ticks时挂被动单 | SpreadCapture |
| 杠杆交易 | 支持3-10倍杠杆做多/做空 | MarginExecutor |
| 风控系统 | Kill Switch、仓位限制、回撤控制 | RiskManager |
| PnL归因 | 分析盈利来源结构 | PnLAttribution |

---

## 架构设计

### 三层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Python 策略层                             │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │ MVPTrader    │ │ 毒流检测器   │ │ 点差捕获器   │        │
│  │ (决策中枢)   │ │ (防御系统)   │ │ (进攻系统)   │        │
│  └──────────────┘ └──────────────┘ └──────────────┘        │
│  ┌──────────────┐ ┌──────────────┐                          │
│  │ PnL归因      │ │ 约束框架     │                          │
│  │ (分析系统)   │ │ (风控系统)   │                          │
│  └──────────────┘ └──────────────┘                          │
└─────────────────────────────────────────────────────────────┘
                              ↑↓
                    HTTP API (端口8080)
                              ↑↓
┌─────────────────────────────────────────────────────────────┐
│                    Go 执行引擎层                             │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │ WebSocket    │ │ MarginExecutor│ │   风控引擎   │        │
│  │   数据流     │ │  (杠杆执行)   │ │              │        │
│  └──────────────┘ └──────────────┘ └──────────────┘        │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │   订单管理   │ │   仓位跟踪   │ │   熔断器     │        │
│  │              │ │              │ │              │        │
│  └──────────────┘ └──────────────┘ └──────────────┘        │
└─────────────────────────────────────────────────────────────┘
                              ↑↓
                    WebSocket + REST API
                              ↑↓
┌─────────────────────────────────────────────────────────────┐
│                    币安交易所                                │
│              (Spot + Margin 全仓杠杆)                        │
└─────────────────────────────────────────────────────────────┘
```

### 数据流

```
1. Go引擎 ← WebSocket ← 币安订单簿数据
2. Python ← HTTP GET /api/v1/market/book ← Go引擎
3. Python策略决策 → 生成交易信号
4. Python → HTTP POST /api/v1/orders → Go引擎
5. Go引擎 → REST API → 币安交易所
6. 成交回报 → WebSocket → Go引擎 → Python
```

---

## 文件结构

```
D:/binance/new/
│
├── start_live_margin.bat          # 主启动脚本（一键启动）
├── start_paper_trading.bat        # 模拟盘启动脚本
├── .env                           # 环境变量配置（实盘密钥）
├── .env.example                   # 配置模板
│
├── core_go/                       # Go 执行引擎
│   ├── main_with_http.go          # HTTP API入口（实盘模式）
│   ├── engine.go                  # 核心引擎（含API端点）
│   ├── margin_executor.go         # 杠杆交易执行器
│   ├── websocket_manager.go       # WebSocket连接管理
│   ├── risk_manager.go            # 风险管理
│   ├── queue_dynamics.go          # 队列动力学引擎
│   └── leverage/                  # 杠杆模块
│       ├── calculator.go          # 杠杆计算器
│       ├── client.go              # 币安杠杆API客户端
│       └── position.go            # 仓位管理
│
└── brain_py/                      # Python 策略模块
    ├── mvp_trader_live.py         # 实盘交易主程序
    ├── mvp_trader.py              # MVP Trader核心
    ├── run_live_paper_trading.py  # Paper Trading版本
    ├── mvp/                       # MVP核心模块
    │   ├── __init__.py            # 三模块导出
    │   ├── simple_queue_optimizer.py
    │   ├── toxic_flow_detector.py
    │   └── spread_capture.py
    ├── performance/               # 性能分析
    │   └── pnl_attribution.py     # PnL归因
    └── agents/                    # 智能体
        └── constrained_sac.py     # 约束SAC
```

---

## 配置说明

### 1. 环境变量配置 (.env)

```bash
# ============================================
# 币安 API 配置（实盘 - 真实资金）
# ============================================
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here
USE_TESTNET=false

# ============================================
# 交易配置
# ============================================
PAPER_TRADING=false          # 实盘模式（关闭模拟）
USE_LEVERAGE=true            # 启用杠杆交易
INITIAL_CAPITAL=10000        # 初始资金
MAX_POSITION_SIZE=0.3        # 最大总仓位 30%
MAX_SINGLE_POSITION=0.2      # 单笔最大仓位 20%
COMMISSION_RATE=0.001        # 手续费率 0.1%
DEFAULT_SYMBOL=BTCUSDT       # 默认交易对

# ============================================
# 风控参数
# ============================================
MAX_DAILY_LOSS_PCT=5.0       # 日亏损限制 5%
MAX_DRAWDOWN_PCT=15.0        # 最大回撤 15%
KILL_SWITCH_ENABLED=true     # 启用熔断

# ============================================
# 代理配置（中国大陆需要）
# ============================================
HTTPS_PROXY=http://127.0.0.1:7897
HTTP_PROXY=http://127.0.0.1:7897
```

### 2. 配置检查清单

| 配置项 | 实盘要求 | 检查命令 |
|--------|----------|----------|
| PAPER_TRADING | false | `grep PAPER_TRADING .env` |
| USE_LEVERAGE | true | `grep USE_LEVERAGE .env` |
| USE_TESTNET | false | `grep USE_TESTNET .env` |
| API_KEY | 已填写 | `grep BINANCE_API_KEY .env` |

---

## 启动流程

### 方法一：一键启动（推荐）

```bash
cd D:\binance\new
start_live_margin.bat
```

这会打开两个窗口：
1. **GoEngine-LIVE-MARGIN** - Go执行引擎
2. **Python-MVPTrader** - Python策略模块

### 方法二：分步手动启动

**步骤1：启动Go引擎**
```bash
cd D:\binance\new\core_go
go run main_with_http.go btcusdt live margin
```

参数说明：
- `btcusdt` - 交易对
- `live` - 实盘模式（非paper trading）
- `margin` - 启用杠杆交易

**步骤2：启动Python策略**（在另一个终端）
```bash
cd D:\binance\new\brain_py
python mvp_trader_live.py --symbol BTCUSDT --interval 1.0
```

参数说明：
- `--symbol` - 交易对
- `--interval` - Tick间隔（秒）

### 方法三：Paper Trading测试

```bash
cd D:\binance\new
start_paper_trading.bat
```

或手动：
```bash
cd D:\binance\new\core_go
go run main_with_http.go btcusdt paper margin
```

---

## API接口

### Go引擎HTTP API

#### 1. 获取引擎状态
```bash
GET http://127.0.0.1:8080/api/v1/status
```

响应示例：
```json
{
  "symbol": "BTCUSDT",
  "connected": true,
  "stale": false,
  "inventory": 0.05,
  "unrealized_pnl": 12.5,
  "last_decision": "2024-01-15T10:30:00Z",
  "degrade_level": "NORMAL",
  "degrade_status": "healthy"
}
```

#### 2. 获取市场数据（订单簿）
```bash
GET http://127.0.0.1:8080/api/v1/market/book
```

响应示例：
```json
{
  "bids": [[50000.0, 1.5], [49999.5, 2.0]],
  "asks": [[50001.0, 1.2], [50001.5, 3.0]],
  "timestamp": 1705312200000
}
```

#### 3. 获取持仓信息
```bash
GET http://127.0.0.1:8080/api/v1/position
```

响应示例（杠杆）：
```json
{
  "symbol": "BTCUSDT",
  "size": 0.05,
  "entry_price": 50000.0,
  "leverage": 3.0,
  "unrealized": 15.0,
  "liquidation": 35000.0
}
```

#### 4. 获取风控统计
```bash
GET http://127.0.0.1:8080/api/v1/risk/stats
```

响应示例：
```json
{
  "daily_pnl": 45.2,
  "total_trades": 12,
  "win_rate": 0.67,
  "kill_switch_triggered": false,
  "margin_level": 2.5
}
```

#### 5. 发送订单
```bash
POST http://127.0.0.1:8080/api/v1/orders
Content-Type: application/json

{
  "side": "buy",
  "qty": 0.01,
  "price": 50000.0,
  "type": "limit"
}
```

响应示例：
```json
{
  "id": "order_1705312200000",
  "status": "pending",
  "side": "buy",
  "qty": 0.01,
  "price": 50000.0
}
```

---

## 风控系统

### 多层风控架构

```
┌─────────────────────────────────────────┐
│  Layer 4: Kill Switch (紧急熔断)         │
│  - 累计亏损达到阈值立即停止               │
│  - 日亏损超过5%触发                       │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│  Layer 3: 约束框架 (Constraint Layer)    │
│  - 订单频率限制 (每秒最多10单)            │
│  - 撤单率限制 (不超过50%)                 │
│  - 最小间隔时间 (50ms)                    │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│  Layer 2: 毒流检测 (Toxic Flow)          │
│  - 马氏距离异常检测                       │
│  - 阈值0.5，连续5次确认才阻止交易         │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│  Layer 1: 仓位限制 (Position Limit)      │
│  - 单笔仓位不超过20%                      │
│  - 总仓位不超过80%                        │
│  - 杠杆倍数3-10倍                         │
└─────────────────────────────────────────┘
```

### 风控参数配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_order_rate | 10/sec | 每秒最大订单数 |
| max_cancel_ratio | 50% | 最大撤单率 |
| min_rest_time_ms | 50ms | 最小下单间隔 |
| max_position_change | 10% | 单笔最大仓位变化 |
| max_drawdown_pct | 5% | 最大回撤限制 |
| kill_switch_loss | -$50 | 熔断触发亏损 |

### 杠杆风控

```go
// 强平价格计算
LiquidationPrice = EntryPrice * (1 ± 1/Leverage * 0.9)

// 保证金率监控
MarginLevel = TotalAsset / TotalBorrowed
if MarginLevel < 1.25 {  // 125%
    TriggerWarning()
}
```

---

## 故障排查

### 常见问题

#### 1. Go引擎无法启动

**症状**: `go run` 命令报错

**排查步骤**:
```bash
# 检查Go版本
go version

# 检查依赖
cd core_go && go mod tidy

# 检查端口占用
netstat -ano | findstr 8080
netstat -ano | findstr 9090
```

**解决方案**:
- 关闭占用8080/9090端口的程序
- 运行 `go mod tidy` 修复依赖

#### 2. Python无法连接Go引擎

**症状**: "Go引擎未就绪" 或连接超时

**排查步骤**:
```bash
# 测试Go引擎API
curl http://127.0.0.1:8080/api/v1/status

# 检查Go引擎窗口是否有错误
```

**解决方案**:
- 确保Go引擎先启动（等待8秒）
- 检查防火墙设置
- 确认端口8080可用

#### 3. API密钥错误

**症状**: "API连接失败" 或鉴权错误

**排查步骤**:
```bash
# 检查.env文件
cat .env | grep BINANCE_API

# 测试API密钥
python -c "
from binance.client import Client
import os
from dotenv import load_dotenv
load_dotenv('.env')
client = Client(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'))
print(client.get_account())
"
```

**解决方案**:
- 确认使用的是主网密钥（非测试网）
- 检查密钥是否有足够权限（现货交易、杠杆交易）
- 确认IP白名单设置

#### 4. 杠杆交易失败

**症状**: "杠杆账户未开通" 或 "Insufficient margin"

**解决方案**:
- 在币安开通全仓杠杆账户
- 转入资金到杠杆账户
- 检查 `.env` 中 `USE_LEVERAGE=true`

### 日志位置

| 模块 | 日志位置 |
|------|----------|
| Go引擎 | 控制台输出 |
| Python策略 | 控制台输出 + logging |
| 交易记录 | `brain_py/trade_history.json` |
| PnL报告 | 控制台实时输出 |

### 调试模式

**Go引擎调试**:
```bash
cd core_go
go run main_with_http.go btcusdt live margin
```

**Python调试**:
```bash
cd brain_py
python mvp_trader_live.py --symbol BTCUSDT --interval 1.0
```

---

## 安全须知

### ⚠️ 实盘交易警告

1. **资金安全**
   - 首次使用建议先用小资金（$100-500）测试
   - 确保了解杠杆交易的风险
   - 设置合理的止损线

2. **API密钥安全**
   - 不要将API密钥提交到Git
   - 使用IP白名单限制访问
   - 定期更换密钥
   - 仅启用必要的权限（现货交易、杠杆交易）

3. **系统监控**
   - 保持监控窗口可见
   - 关注Kill Switch触发情况
   - 定期检查PnL归因报告

4. **紧急情况处理**
   - 发现异常立即关闭Python窗口（停止策略）
   - 如需紧急平仓，关闭Go引擎窗口
   - 或直接登录币安手动平仓

### 建议测试流程

```
1. Paper Trading测试 (至少1天)
   ↓
2. 小资金实盘测试 ($100, 无杠杆)
   ↓
3. 小资金杠杆测试 ($100, 3x杠杆)
   ↓
4. 逐步增加资金
```

---

## 性能指标

### 延迟指标

| 组件 | 目标延迟 | 实测延迟 |
|------|----------|----------|
| WebSocket数据处理 | <1ms | ~0.5ms |
| 策略决策 | <2ms | ~1.2ms |
| HTTP API调用 | <10ms | ~5ms |
| 订单发送 | <50ms | ~30ms |
| 端到端延迟 | <100ms | ~50ms |

### 吞吐量

- 最大订单频率: 10单/秒
- 建议Tick间隔: 1秒
- 日交易次数: 50-200笔

---

## 附录

### 命令速查表

| 操作 | 命令 |
|------|------|
| 一键启动实盘 | `start_live_margin.bat` |
| 启动模拟盘 | `start_paper_trading.bat` |
| 手动启动Go | `go run main_with_http.go btcusdt live margin` |
| 手动启动Python | `python mvp_trader_live.py` |
| 检查状态 | `curl http://127.0.0.1:8080/api/v1/status` |
| 检查风控 | `curl http://127.0.0.1:8080/api/v1/risk/stats` |

### 配置文件模板

详见 `.env.example` 文件。

### 获取更多帮助

- 查看代码注释: `core_go/engine.go`, `brain_py/mvp_trader_live.py`
- 运行测试: `go test ./...` (Go), `pytest tests/` (Python)
- 查看架构文档: `docs/ARCHITECTURE_OVERVIEW.md`

---

**最后更新**: 2024-01-15  
**版本**: v1.0.0  
**作者**: HFT Engine Team
