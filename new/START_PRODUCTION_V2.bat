@echo off
chcp 65001 >nul
cls

echo ==========================================
echo   P10 Hedge Fund OS - Production v2.0
echo   with Strategy Entropy Monitor
echo ==========================================
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo [INFO] Working directory: %CD%
echo.

REM ==========================================
REM Pre-flight Checks
REM ==========================================
echo [1] Pre-flight Checks...
echo.

python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found!
    pause
    exit /b 1
)

REM Check Prometheus client
python -c "import prometheus_client" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [INFO] Installing prometheus-client...
    pip install prometheus-client -q
)
echo [OK] Dependencies ready
echo.

REM ==========================================
REM Build Go Engine if needed
REM ==========================================
echo [2] Building Go Engine...
if not exist "core_go\hft_engine_http.exe" (
    cd core_go
    go build -o hft_engine_http.exe main_with_http.go
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Build failed!
        cd ..
        pause
        exit /b 1
    )
    cd ..
    echo [OK] Build successful
) else (
    echo [OK] Using existing binary
)
echo.

REM ==========================================
REM Start All Services
REM ==========================================
echo [3] Starting P10 System...
echo.

REM Start Go Engine
echo     Starting Go Engine [8080/9090]...
start "[P10-Go] Engine" cmd /k "cd /d "%CD%\core_go" ^&^& echo ====================================== ^&^& echo Go Engine Starting... ^&^& echo ====================================== ^&^& hft_engine_http.exe btcusdt paper ^&^& pause"
timeout /t 3 /nobreak >nul

REM Verify Go Engine
curl -s http://127.0.0.1:8080/api/v1/status >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo     [OK] Go Engine ready
) else (
    echo     [WARN] Go Engine starting...
)

REM Start Python P10 with full features
echo     Starting Python P10 [8000]...
start "[P10-Py] Orchestrator" cmd /k "cd /d "%CD%" ^&^& echo ====================================== ^&^& echo Python P10 Starting... ^&^& echo Features: MetaBrain + RobustRiskParity + EntropyMonitor ^&^& echo ====================================== ^&^& python hedge_fund_os\demo_full.py ^&^& pause"
timeout /t 2 /nobreak >nul

REM Start Strategy Entropy Monitor Dashboard
echo     Starting Entropy Monitor...
start "[P10-Entropy] Monitor" cmd /k "cd /d "%CD%" ^&^& echo ====================================== ^&^& echo Strategy Entropy Monitor ^&^& echo ====================================== ^&^& :loop ^&^& cls ^&^& echo === Strategy Entropy Dashboard === ^&^& echo. ^&^& python -c "from hedge_fund_os.strategy_entropy_monitor import demo_entropy_calculation; demo_entropy_calculation()" 2^>nul ^&^& echo. ^&^& echo Refreshing in 10s... ^&^& timeout /t 10 ^>nul ^&^& goto loop"

REM Start Real-time Metrics Monitor
echo     Starting Metrics Monitor...
start "[P10-Metrics] Real-time" cmd /k "cd /d "%CD%" ^&^& echo ====================================== ^&^& echo Real-time Metrics Monitor ^&^& echo ====================================== ^&^& :loop ^&^& cls ^&^& echo === P10 System Status === ^&^& echo. ^&^& echo [Go Engine] ^&^& curl -s http://127.0.0.1:8080/api/v1/risk/stats 2^>nul ^| python -c "import sys,json; d=json.load(sys.stdin); print(f'  Mode: {d.get(chr(109)+chr(111)+chr(100)+chr(101),chr(78)+chr(65))} | DD: {d.get(chr(100)+chr(97)+chr(105)+chr(108)+chr(121)+chr(95)+chr(100)+chr(114)+chr(97)+chr(119)+chr(100)+chr(111)+chr(119)+chr(110),0):.2%}')" 2^>nul ^&^& echo. ^&^& echo [P10 Metrics] ^&^& curl -s http://127.0.0.1:8000/metrics 2^>nul ^| findstr hfos_system_mode ^&^& curl -s http://127.0.0.1:8000/metrics 2^>nul ^| findstr hfos_daily_drawdown ^&^& echo. ^&^& timeout /t 5 ^>nul ^&^& goto loop"

echo.
echo ==========================================
echo   P10 System Started!
echo ==========================================
echo.
echo Services:
echo   [P10-Go]       Go Engine (HTTP + Prometheus)
echo   [P10-Py]       Python P10 Orchestrator
echo   [P10-Entropy]  Strategy Entropy Dashboard
echo   [P10-Metrics]  Real-time Metrics Monitor
echo.
echo Endpoints:
echo   Go API:        http://127.0.0.1:8080/api/v1/risk/stats
echo   Go Metrics:    http://127.0.0.1:9090/metrics
echo   P10 Metrics:   http://127.0.0.1:8000/metrics
echo.
echo Quick Test:
echo   curl http://127.0.0.1:8080/api/v1/risk/stats
echo   curl http://127.0.0.1:8000/metrics ^| findstr hfos_
echo.
echo Performance Benchmark:
echo   python benchmark_python_core.py
echo.
pause
