@echo off
chcp 65001 >nul
REM Python端Paper Trading启动脚本

echo ============================================
echo  Python Paper Trading Mode
echo ============================================
cd /d "D:\binance\new\brain_py"

set PYTHONIOENCODING=utf-8
set PAPER_TRADING=true

echo.
echo [选项]
echo 1. BTCUSDT (点差极紧，约0.01 bps，建议min-spread=1)
echo 2. ETHUSDT (点差较宽，约2-5 bps，建议min-spread=2)
echo 3. BNBUSDT (点差较宽，适合测试)
echo 4. 回测模式 (使用合成数据)
echo.

set /p choice="选择 (1-4): "

if "%choice%"=="1" (
    echo.
    echo [启动实盘Paper Trading - BTCUSDT]
    echo [参数: min-spread=1 tick (0.01 USD)]
    python run_live_paper_trading.py --symbol=BTCUSDT --min-spread=1 --minutes=30
) else if "%choice%"=="2" (
    echo.
    echo [启动实盘Paper Trading - ETHUSDT]
    echo [参数: min-spread=2 ticks (0.02 USD)]
    python run_live_paper_trading.py --symbol=ETHUSDT --min-spread=2 --minutes=30
) else if "%choice%"=="3" (
    echo.
    echo [启动实盘Paper Trading - BNBUSDT]
    python run_live_paper_trading.py --symbol=BNBUSDT --min-spread=2 --minutes=30
) else if "%choice%"=="4" (
    echo.
    echo [运行MVP Trader回测 (合成数据)]
    python mvp_trader.py --backtest --ticks 5000
) else (
    echo 无效选项，默认启动BTCUSDT
    python run_live_paper_trading.py --symbol=BTCUSDT --min-spread=1 --minutes=30
)

echo.
echo ============================================
pause
