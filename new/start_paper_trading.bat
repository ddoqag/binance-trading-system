@echo off
chcp 65001 >nul
REM 启动模拟盘交易 (Paper Trading Mode)

echo ============================================
echo  HFT Paper Trading Mode (模拟盘测试)
echo ============================================
echo.
echo [配置检查]
echo - 模式: Paper Trading (模拟交易，无真实资金风险)
echo - 交易所: Binance Testnet
echo - 初始资金: $10,000 (虚拟)
echo - 手续费: 2bps (Maker费率)
echo - 风控: Kill Switch已启用
echo.

cd /d "D:\binance\new\core_go"

REM 设置环境变量
set PAPER_TRADING=true
set HFT_LOG_LEVEL=info
set MAX_POSITION=0.15
set MAX_TRADES_PER_MIN=3
set MIN_EXPECTED_VALUE_BPS=2.0

echo [启动HFT引擎 - Paper Trading模式]
echo.
go run . --symbol=BTCUSDT --paper-trading --config=paper_trading.json

pause
