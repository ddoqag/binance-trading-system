@echo off
chcp 65001 >nul
cls

echo ==========================================
echo   P10 Full Benchmark - i9-13900H Test
echo ==========================================
echo.
echo This script will:
echo   1. Check Go Engine status
echo   2. Run performance benchmark
echo   3. Generate latency report
echo.

REM Check if Go Engine is running
echo [1] Checking Go Engine...
curl -s http://127.0.0.1:8080/api/v1/status >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo     [FAIL] Go Engine not running!
    echo.
    echo Please start Go Engine first:
    echo   scripts\start_go_engine.bat btcusdt paper
    echo.
    pause
    exit /b 1
)
echo     [OK] Go Engine is running
echo.

REM Run benchmark
echo [2] Running Performance Benchmark...
echo     Testing 1000 HTTP requests...
echo     This may take 30-60 seconds...
echo.

cd %~dp0\..
python performance_benchmark.py --quick

echo.
echo ==========================================
echo   Benchmark Complete
echo ==========================================
echo.
echo For full benchmark, run:
echo   python performance_benchmark.py
echo.
pause
