# Environment Variables

> 环境变量配置参考

---

<!-- AUTO-GENERATED: Environment Variables -->

## Binance API Configuration

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `BINANCE_API_KEY` | Yes* | Binance API Key for trading | `your_api_key_here` |
| `BINANCE_API_SECRET` | Yes* | Binance API Secret for authentication | `your_api_secret_here` |
| `BINANCE_TESTNET_API_KEY` | No | Testnet API Key (for paper trading) | `your_testnet_key` |
| `BINANCE_TESTNET_API_SECRET` | No | Testnet API Secret | `your_testnet_secret` |

\* Not required for local backtesting with `local_trading/` module

---

## Proxy Configuration

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `HTTP_PROXY` | No | HTTP proxy for outgoing connections | `http://127.0.0.1:7897` |
| `HTTPS_PROXY` | No | HTTPS proxy for outgoing connections | `http://127.0.0.1:7897` |

---

## Telegram Bot Configuration (Optional)

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | No | Bot token from @BotFather | `your_bot_token_here` |
| `TELEGRAM_CHAT_ID` | No | Chat ID for notifications | `your_chat_id_here` |

To get your bot token:
1. Talk to @BotFather on Telegram
2. Create a new bot: /newbot
3. Copy the token here

To get your chat ID:
1. Talk to @userinfobot on Telegram
2. It will reply with your ID
3. Or send a message to your bot and visit: `https://api.telegram.org/bot<YourBOTToken>/getUpdates`

---

## Trading Configuration

| Variable | Required | Description | Default | Example |
|----------|----------|-------------|---------|---------|
| `INITIAL_CAPITAL` | No | Initial capital for trading | `10000` | `10000` |
| `MAX_POSITION_SIZE` | No | Maximum total position size (0-1) | `0.8` | `0.8` |
| `MAX_SINGLE_POSITION` | No | Maximum single position size (0-1) | `0.2` | `0.2` |
| `DEFAULT_SYMBOL` | No | Default trading symbol | `BTCUSDT` | `BTCUSDT` |
| `DEFAULT_INTERVAL` | No | Default candle interval | `1h` | `1h` |

---

## Risk Configuration

| Variable | Required | Description | Default | Example |
|----------|----------|-------------|---------|---------|
| `MAX_DAILY_LOSS_PCT` | No | Maximum daily loss percentage | `5.0` | `5.0` |
| `MAX_DRAWDOWN_PCT` | No | Maximum drawdown percentage | `15.0` | `15.0` |
| `KILL_SWITCH_ENABLED` | No | Enable kill switch for risk control | `true` | `true` |

---

## Usage

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your actual values:
   ```bash
   # Required
   BINANCE_API_KEY=your_actual_api_key
   BINANCE_API_SECRET=your_actual_secret
   
   # Optional - adjust as needed
   INITIAL_CAPITAL=50000
   MAX_POSITION_SIZE=0.5
   ```

3. The application will automatically load `.env` at startup.

<!-- END AUTO-GENERATED -->

---

## 本地回测模式

使用 `brain_py/local_trading/` 模块进行离线回测时，**不需要**配置 Binance API 密钥：

```python
from local_trading import LocalTrader, LocalTradingConfig

config = LocalTradingConfig(
    symbol='BTCUSDT',
    initial_capital=10000.0,
    # 无需 API 密钥
)

trader = LocalTrader(config)
trader.load_data(n_ticks=1000)  # 使用合成数据
result = trader.run_backtest()
```

---

*本文档由 Claude Code 自动生成，最后更新: 2026-04-09*
