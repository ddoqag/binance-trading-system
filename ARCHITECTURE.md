# 币安量化交易系统 - 架构文档

## 系统架构总览

## 📦 模块架构

```
D:/binance/
├── config/              # 🔧 配置管理
│   ├── __init__.py
│   ├── settings.py     # Python 配置
│   └── config.js       # Node.js 配置
├── indicators/          # 📊 技术指标库
│   ├── __init__.py
│   └── technical.py    # 8 个技术指标
├── factors/             # 🧪 Alpha 因子库（新增）
│   ├── __init__.py
│   ├── momentum.py      # 动量因子
│   ├── mean_reversion.py  # 均值回归因子
│   ├── volatility.py    # 波动率因子
│   └── volume.py      # 成交量因子
├── data/                # 💾 数据模块（新增）
│   ├── __init__.py
│   └── loader.py      # 统一数据加载
├── trading/             # 📈 交易执行
│   ├── __init__.py
│   ├── order.py
│   └── execution.py
├── strategy/            # 🎯 策略模块
│   ├── __init__.py
│   ├── base.py
│   ├── dual_ma.py
│   ├── rsi_strategy.py
│   └── ml_strategy.py
├── risk/                # 🛡️  风险管理
│   ├── __init__.py
│   ├── manager.py
│   ├── position.py
│   └── stop_loss.py
├── models/              # 🤖 机器学习
│   ├── __init__.py
│   ├── features.py
│   ├── predictor.py
│   └── model_trainer.py
├── utils/               # 🔧 工具模块
│   ├── __init__.py
│   ├── helpers.py
│   └── database.py
├── web/                 # 🌐 Web API（新增）
│   ├── __init__.py
│   └── api.py
├── tests/               # 🧪 测试
│   ├── test_*.py
│   └── integration/
└── docs/                # 📚 文档
    └── *.md
```

---

## 🏗️ 核心模块说明

### 1. config/ - 配置管理
**职责**: 统一的配置管理，支持 Python 和 Node.js

| 文件 | 说明 |
|------|------|
| `settings.py` | Python 配置：`DBConfig`, `TradingConfig`, `Settings` |
| `config.js` | Node.js 配置 |
| `.env` | 环境变量（不提交 Git） |

**使用示例**:
```python
from config.settings import get_settings
settings = get_settings()
print(settings.db.host)
```

---

### 2. indicators/ - 技术指标库
**职责**: 提供统一的技术指标计算接口

| 指标 | 函数 | 说明 |
|------|------|------|
| RSI | `rsi(prices, period)` | 相对强弱指数 |
| SMA | `sma(prices, period)` | 简单移动平均 |
| EMA | `ema(prices, period)` | 指数移动平均 |
| MACD | `macd(prices)` | MACD 指标 |
| BBands | `bollinger_bands(prices)` | 布林带 |
| ATR | `atr(high, low, close)` | 平均真实波幅 |
| ROC | `roc(prices, period)` | 变动率 |
| OBV | `obv(close, volume)` | 能量潮 |

**使用示例**:
```python
from indicators import rsi, macd
df['rsi'] = rsi(df['close'], period=14)
```

---

### 3. factors/ - Alpha 因子库（新增）
**职责**: 提供 Alpha 因子计算，参考 docs/13-Alpha因子分类体系.md

| 模块 | 因子 | 说明 |
|------|------|------|
| `momentum.py` | momentum, ema_trend, macd_momentum | 动量因子 |
| `mean_reversion.py` | zscore, bollinger_position | 均值回归因子 |
| `volatility.py` | realized_volatility, atr_normalized | 波动率因子 |
| `volume.py` | volume_anomaly, price_volume_trend | 成交量因子 |

**使用示例**:
```python
from factors import momentum, zscore
df['momentum_20'] = momentum(df['close'], period=20)
df['zscore'] = zscore(df['close'], period=20)
```

---

### 4. data/ - 数据模块（新增）
**职责**: 统一的数据加载接口

| 功能 | 函数 | 说明 |
|------|------|------|
| OHLCV 加载 | `DataLoader.load_ohlcv()` | 加载 K 线数据 |
| CSV 加载 | `load_csv_data()` | 加载 CSV |
| JSON 加载 | `load_json_data()` | 加载 JSON |
| 数据库加载 | `load_from_database()` | 从数据库加载 |

**使用示例**:
```python
from data.loader import DataLoader
loader = DataLoader()
df = loader.load_ohlcv('BTCUSDT', '1h')
```

---

### 5. web/ - Web API（新增）
**职责**: 提供 REST API 接口（可选，需要 FastAPI）

| 端点 | 方法 | 说明 |
|-------|------|------|
| `/` | GET | API 首页 |
| `/api/status` | GET | 系统状态 |
| `/api/market/{symbol}` | GET | 市场数据 |
| `/api/indicators/{symbol}` | GET | 技术指标 |
| `/api/strategy/{name}` | POST | 运行策略 |

**使用示例**:
```bash
# 安装依赖
pip install fastapi uvicorn

# 运行服务
uvicorn web.api:app --reload
```

---

### 6. 其他核心模块

| 模块 | 职责 |
|------|------|
| `trading/` | 订单管理、交易执行 |
| `strategy/` | 策略基类、双均线/RSI/ML 策略 |
| `risk/` | 仓位控制、止损止盈、风险熔断 |
| `models/` | 特征工程、模型训练、价格预测 |
| `utils/` | 日志、数据库连接、工具函数 |

---

## 🔄 数据流程

```
币安 API (Binance API)
    ↓
fetch-market-data.js (Node.js)
    ↓
PostgreSQL / JSON / CSV
    ↓
data/loader.py (统一数据加载)
    ↓
┌─────────────────────────────────────┐
│  特征工程 (models/features.py)   │
│  因子计算 (factors/)            │
│  策略生成 (strategy/)           │
│  风险检查 (risk/)               │
│  交易执行 (trading/)            │
└─────────────────────────────────────┘
    ↓
Web API (web/api.py)
```

---

## 🛠️ 依赖关系

```
config/
    ↓
indicators/ ← factors/
    ↓         ↓
models/     data/
    ↓    ↓
strategy/ ← risk/
    ↓
trading/
    ↓
web/
```

---

## 📝 开发指南

### 添加新技术指标

1. 在 `indicators/technical.py` 添加函数
2. 在 `indicators/__init__.py` 导出
3. 在 `tests/test_indicators.py` 添加测试

### 添加新因子

1. 在 `factors/` 对应模块添加函数
2. 在 `factors/__init__.py` 导出
3. 添加测试

### 添加新策略

1. 继承 `strategy/base.py` 的 `BaseStrategy`
2. 实现 `generate_signals()` 方法
3. 在 `strategy/__init__.py` 导出

---

## 🔐 安全最佳实践

1. **永远不要**将 `.env` 提交到 Git
2. 使用 `config.settings` 读取配置
3. 所有敏感信息通过环境变量管理
4. `.env.example` 只包含模板，不包含真实密码

---

## 🧪 测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定模块测试
pytest tests/test_indicators.py -v
pytest tests/test_config.py -v
pytest tests/test_models_features.py -v

# 运行集成测试
pytest tests/integration/ -v
```

---

## 📚 相关文档

- `docs/REFACTOR_PLAN.md` - 重构计划
- `docs/REFACTOR_SUMMARY.md` - 重构总结
- `docs/TEST_SUMMARY.md` - 测试总结
- `docs/13-Alpha因子分类体系.md` - Alpha 因子设计
