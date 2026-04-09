@echo off
chcp 65001 >nul
cls

echo ==========================================
echo   LIVE MARGIN TRADING - 现货杠杆实盘
echo ==========================================
echo.
echo [警告] 这是实盘交易模式，使用真实资金！
echo.

REM Try to find project root
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM Check if we're in the right directory
if not exist "core_go\engine.go" (
    echo [ERROR] Cannot find project root directory
    echo Current directory: %CD%
    pause
    exit /b 1
)

echo [INFO] Project root: %CD%
echo.

REM ==========================================
REM 检查环境配置
REM ==========================================
echo [1] 检查环境配置...
echo.

REM 检查 .env 文件
if not exist ".env" (
    echo [ERROR] .env 文件不存在！
    echo 请复制 .env.example 到 .env 并配置API密钥
    pause
    exit /b 1
)

echo     [OK] .env 文件存在

REM 检查 API 密钥（简单检查文件内容）
findstr /C:"BINANCE_API_KEY=" .env >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo     [OK] API Key 配置 detected
) else (
    echo     [WARN] API Key 可能未配置
)

REM 检查杠杆设置
findstr /C:"USE_LEVERAGE=true" .env >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo     [OK] 杠杆交易已启用
) else (
    echo     [WARN] 杠杆交易未在 .env 中启用
)

echo.

REM ==========================================
REM 构建 Go 引擎
REM ==========================================
echo [2] 构建 Go 引擎...
echo.

cd core_go

echo     构建 hft_engine_http.exe (带HTTP API和Prometheus监控)...
go build -o hft_engine_http.exe -tags http_server main_with_http.go

if %ERRORLEVEL% neq 0 (
    echo.
    echo     [ERROR] 构建失败！
    echo     请检查 Go 安装和依赖
    cd ..
    pause
    exit /b 1
)

echo     [OK] 构建成功
cd ..
echo.

REM ==========================================
REM 启动 Go 引擎 (实盘杠杆模式)
REM ==========================================
echo [3] 启动 Go 引擎 - 实盘杠杆模式
echo.
echo     交易对: BTCUSDT
echo     模式: LIVE (实盘)
echo     杠杆: 启用 (Margin)
echo     API端口: 8080
echo     监控端口: 9090
echo.

start "GoEngine-LIVE-MARGIN [8080/9090]" cmd /k "cd /d "%CD%\core_go" && echo [LIVE MARGIN MODE] && hft_engine_http.exe btcusdt live margin || echo [ERROR] Go Engine crashed && pause"

echo     [OK] Go Engine 窗口已打开
echo     等待 5 秒初始化...
timeout /t 5 /nobreak >nul
echo.

REM ==========================================
REM 验证 Go 引擎
REM ==========================================
echo [4] 验证 Go 引擎...
curl -s http://127.0.0.1:8080/api/v1/status >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo     [OK] Go Engine 响应正常
    curl -s http://127.0.0.1:8080/api/v1/status | findstr "\"mode\""
) else (
    echo     [WARN] Go Engine 尚未就绪，可能需要更多时间
)
echo.

REM ==========================================
REM 启动 Python 策略模块
REM ==========================================
echo [5] 启动 Python 策略模块...
echo.

REM 检查 Python
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo     [ERROR] Python 未安装！
    pause
    exit /b 1
)

REM 启动 MVP Trader (实盘模式)
start "Python-MVPTrader [LIVE]" cmd /k "cd /d "%CD%\brain_py" && echo [LIVE MODE] && python mvp_trader_live.py || echo [ERROR] Python crashed && pause"

echo     [OK] Python 策略窗口已打开
echo     等待 3 秒...
timeout /t 3 /nobreak >nul
echo.

REM ==========================================
REM 最终状态
REM ==========================================
echo ==========================================
echo   系统状态 - LIVE MARGIN TRADING
echo ==========================================
echo.

echo 运行服务:
curl -s http://127.0.0.1:8080/api/v1/status >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo   [OK] Go Engine:     http://127.0.0.1:8080 (LIVE MARGIN)
    echo   [OK] Go Metrics:    http://127.0.0.1:9090
) else (
    echo   [WAIT] Go Engine:   启动中...
)

echo   [OK] Python Strategy: brain_py/mvp_trader_live.py
echo.

echo 监控命令:
echo   curl http://127.0.0.1:8080/api/v1/risk/stats
echo   curl http://127.0.0.1:9090/metrics ^| findstr hft_engine
echo.

echo 停止方法:
echo   1. 关闭 Go Engine 窗口
echo   2. 关闭 Python 窗口
echo.

echo ==========================================
echo   实盘杠杆交易已启动！
echo   [警告] 使用真实资金交易
echo ==========================================
echo.

pause
