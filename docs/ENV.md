# 环境变量配置
<!-- AUTO-GENERATED - DO NOT EDIT -->

## 数据库配置

| 变量 | 必填 | 描述 | 默认值 |
|------|------|------|--------|
| `DB_HOST` | Yes | PostgreSQL host | `localhost` |
| `DB_PORT` | Yes | PostgreSQL port | `5432` |
| `DB_NAME` | Yes | Database name | `binance` |
| `DB_USER` | Yes | Database username | `postgres` |
| `DB_PASSWORD` | Yes | Database password | `your_password_here` |

## 交易配置

| 变量 | 必填 | 描述 | 默认值 |
|------|------|------|--------|
| `INITIAL_CAPITAL` | No | Initial capital in USDT | `10000` |
| `MAX_POSITION_SIZE` | No | Maximum position size as a fraction of total capital | `0.8` |
| `MAX_SINGLE_POSITION` | No | Maximum single position size | `0.2` |
| `PAPER_TRADING` | No | Enable paper trading mode | `true` |
| `COMMISSION_RATE` | No | Commission rate per trade | `0.001` |
| `DEFAULT_SYMBOL` | No | Default trading symbol | `BTCUSDT` |
| `DEFAULT_INTERVAL` | No | Default time interval | `1h` |

## 杠杆交易配置

| 变量 | 必填 | 描述 | 默认值 |
|------|------|------|--------|
| `MAX_LEVERAGE` | No | Maximum leverage allowed | `10.0` |
| `MAINTENANCE_MARGIN_RATE` | No | Maintenance margin rate | `0.005` |
| `LEVERAGE_ENABLED` | No | Enable leverage trading | `true` |

## 币安 API 配置（可选）

| 变量 | 必填 | 描述 | 默认值 |
|------|------|------|--------|
| `BINANCE_API_KEY` | No | Binance API key | `your_api_key_here` |
| `BINANCE_API_SECRET` | No | Binance API secret | `your_api_secret_here` |
| `USE_TESTNET` | No | 使用币安测试网（测试网密钥从 https://testnet.binance.vision 获取） | `true` |

## Redis 配置

| 变量 | 必填 | 描述 | 默认值 |
|------|------|------|--------|
| `REDIS_HOST` | No | Redis 服务器地址 (WSL2 使用 192.168.18.62，本机使用 localhost) | `192.168.18.62` |
| `REDIS_PORT` | No | Redis 服务器端口 | `6379` |
| `REDIS_PASSWORD` | No | Redis 密码（未配置则留空） | `` |
| `REDIS_DB` | No | Redis 数据库编号 | `0` |

## 代理配置

| 变量 | 必填 | 描述 | 默认值 |
|------|------|------|--------|
| `HTTPS_PROXY` | No | HTTPS 代理地址（中国大陆访问 Binance API 需要） | `http://127.0.0.1:7897` |
| `HTTP_PROXY` | No | HTTP 代理地址 | `http://127.0.0.1:7897` |

## trading_system（Phase 1-3）

| 变量 | 必填 | 描述 | 默认值 |
|------|------|------|--------|
| `TRADING_MODE` | No | 交易模式：`paper`（模拟）或 `live`（实盘） | `paper` |
| `TRADING_SYMBOL` | No | 交易对 | `BTCUSDT` |
| `TRADING_INTERVAL` | No | K 线时间周期 | `1h` |
| `INITIAL_BALANCE` | No | 初始账户余额（模拟交易） | `10000` |
| `KIMI_API_KEY` | No | Kimi K2 API 密钥（Phase 3 模糊决策层，可选） | `` |
