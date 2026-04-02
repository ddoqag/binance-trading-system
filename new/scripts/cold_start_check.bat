@echo off
chcp 65001 >nul
cls

echo ==========================================
echo   P10 Cold Start Check - Pre-Flight Verification
echo ==========================================
echo.
echo This script verifies system readiness before live trading
echo.

set FAIL=0

REM 1. Check Go Engine binary
echo [1] Checking Go Engine binary...
if exist "core_go\hft_engine_http.exe" (
    echo     [OK] hft_engine_http.exe found
) else (
    echo     [WARN] hft_engine_http.exe not found
    echo          Run: cd core_go ^&^& go build -o hft_engine_http.exe main_with_http.go
    set FAIL=1
)
echo.

REM 2. Check Python environment
echo [2] Checking Python environment...
python --version >nul 2>&1
if %ERRORLEVEL% equ 0 (
    for /f "tokens=*" %%a in ('python --version') do echo     [OK] %%a
) else (
    echo     [FAIL] Python not found
    set FAIL=1
)
echo.

REM 3. Check network connectivity
echo [3] Checking network connectivity...
echo     Testing Binance API latency...
for /f %%a in ('powershell -Command "(Measure-Command {Invoke-WebRequest -Uri 'https://api.binance.com/api/v3/ping' -TimeoutSec 5 -ErrorAction SilentlyContinue}).TotalMilliseconds"') do set PING=%%a

if %PING%==[] (
    echo     [WARN] Cannot reach Binance API
    echo          Check internet connection
) else (
    if %PING% gtr 100 (
        echo     [WARN] Binance latency: %PING%ms (high)
        echo          Consider closer VPS location
    ) else (
        echo     [OK] Binance latency: %PING%ms
    )
)
echo.

REM 4. Check ports availability
echo [4] Checking port availability...
for %%p in (8080 9090 8000) do (
    netstat -an | findstr ":%%p " | findstr "LISTENING" >nul
    if %ERRORLEVEL% equ 0 (
        echo     [WARN] Port %%p is already in use
    ) else (
        echo     [OK] Port %%p is available
    )
)
echo.

REM 5. Check logs directory
echo [5] Checking logs directory...
if exist "logs" (
    echo     [OK] logs/ directory exists
) else (
    mkdir logs
    echo     [OK] Created logs/ directory
)
echo.

REM 6. Verify configuration
echo [6] Checking configuration files...
if exist "config\default.yaml" (
    echo     [OK] config/default.yaml found
) else (
    echo     [WARN] config/default.yaml not found
)
echo.

REM Summary
echo ==========================================
echo   Check Complete
echo ==========================================
if %FAIL% equ 0 (
    echo.
    echo [PASS] All checks passed. System ready for live trading.
    echo.
    echo Next steps:
    echo   1. scripts\start_go_engine.bat
    echo   2. python performance_benchmark.py
    echo   3. Start trading
) else (
    echo.
    echo [FAIL] Some checks failed. Please fix before proceeding.
)
echo.
pause
