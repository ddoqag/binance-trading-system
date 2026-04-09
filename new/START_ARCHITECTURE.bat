@echo off
chcp 65001 >nul
REM HFT Trading System - Architecture-based Startup Script
REM 基于架构图的系统启动脚本

title HFT Trading System Launcher

echo ============================================================
echo    HFT Trading System - Architecture Launcher
echo    高频交易系统架构启动器
echo ============================================================
echo.

REM Check if running from correct directory
if not exist "core_go\main_default.go" (
    echo [ERROR] Please run this script from the project root directory!
    echo [错误] 请在项目根目录运行此脚本！
    pause
    exit /b 1
)

REM Parse arguments
set "MODE=%~1"
set "SYMBOL=%~2"
if "%MODE%"=="" set "MODE=paper"
if "%SYMBOL%"=="" set "SYMBOL=BTCUSDT"

echo [INFO] Starting mode: %MODE%
echo [INFO] Trading symbol: %SYMBOL%
echo.

REM Check environment
if not exist "logs" mkdir logs
if not exist "data" mkdir data
if not exist "checkpoints" mkdir checkpoints

REM ============================================================================
REM 启动顺序按照架构图分层
REM ============================================================================

if "%MODE%"=="full" goto START_FULL
if "%MODE%"=="new" goto START_NEW_STACK
if "%MODE%"=="legacy" goto START_LEGACY_STACK
goto START_DEFAULT

:START_FULL
echo [PHASE 1] Starting External Systems Dependencies...
echo.

echo [PHASE 2] Starting Legacy Stack Components (黄色)...
start "Data Collection" cmd /k "python start_data_collection.py --symbol %SYMBOL%"
timeout /t 2 >nul

echo [PHASE 3] Starting New Low-Latency Stack (绿色)...
cd core_go
go build -o hft_engine.exe .
if errorlevel 1 (
    echo [ERROR] Go build failed!
    cd ..
    pause
    exit /b 1
)
cd ..
start "Go Core Engine" cmd /k "cd core_go && .\hft_engine.exe %SYMBOL% %MODE%"
timeout /t 3 >nul

echo [PHASE 4] Starting Plugin Layer (粉色)...
goto START_COMPLETE

:START_NEW_STACK
echo [INFO] Starting NEW LOW-LATENCY STACK ONLY (绿色)
echo.
cd core_go
go build -o hft_engine.exe .
if errorlevel 1 (
    echo [ERROR] Go build failed!
    cd ..
    pause
    exit /b 1
)
cd ..
start "Go Core Engine" cmd /k "cd core_go && .\hft_engine.exe %SYMBOL% %MODE%"
timeout /t 3 >nul
start "Python Agent" cmd /k "python brain_py\agent.py"
goto START_COMPLETE

:START_LEGACY_STACK
echo [INFO] Starting LEGACY STACK ONLY (黄色)
echo.
start "Data Collection" cmd /k "python start_data_collection.py --symbol %SYMBOL%"
timeout /t 2 >nul
start "Live Trader" cmd /k "python start_live_trader.py --symbol %SYMBOL%"
goto START_COMPLETE

:START_DEFAULT
echo [INFO] Starting DEFAULT CONFIGURATION (推荐配置)
echo.
cd core_go
go build -o hft_engine.exe .
if errorlevel 1 (
    echo [ERROR] Go build failed!
    cd ..
    pause
    exit /b 1
)
cd ..
start "Go Core Engine" cmd /k "cd core_go && .\hft_engine.exe %SYMBOL% %MODE%"
timeout /t 3 >nul
start "Python Agent" cmd /k "python brain_py\agent.py"
timeout /t 2 >nul
start "Data Collection" cmd /k "python start_data_collection.py --symbol %SYMBOL%"

:START_COMPLETE
echo.
echo ============================================================
echo    [SUCCESS] All components started successfully!
echo ============================================================
echo.
echo Components Status:
echo   [绿色] New Stack:      Go Engine, Python Agent
echo   [黄色] Legacy Stack:   Data Collection
echo   [蓝色] External:       Binance APIs, PostgreSQL
echo   [粉色] Plugins:        Available on demand
echo.
echo Logs location: .\logs\
echo.
pause
