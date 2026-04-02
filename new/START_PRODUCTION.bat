@echo off
chcp 65001 >nul
cls

echo ==========================================
echo   P10 Hedge Fund OS - Production Start
echo ==========================================
echo.

REM Save current directory and change to project root
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo [INFO] Working directory: %CD%
echo.

REM ==========================================
REM STEP 1: Pre-flight Checks
REM ==========================================
echo [1] Pre-flight Checks...
echo.

REM Check Python
echo     Checking Python...
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo     [ERROR] Python not found!
    pause
    exit /b 1
)
python --version
echo.

REM Check Go
echo     Checking Go...
go version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo     [WARN] Go not found - cannot rebuild if needed
)

REM Create necessary directories
echo     Creating directories...
if not exist "logs" mkdir logs
if not exist "logs\decisions" mkdir logs\decisions
if not exist "checkpoints" mkdir checkpoints
echo     [OK] Directories ready
echo.

REM ==========================================
REM STEP 2: Build Go Engine
REM ==========================================
echo [2] Building Go Engine (Enhanced with HTTP + Metrics)...
echo.

cd core_go

REM Check if we have the enhanced version
if not exist "main_with_http.go" (
    echo     [ERROR] main_with_http.go not found!
    echo     Please ensure you have the complete P10 codebase.
    cd ..
    pause
    exit /b 1
)

echo     Compiling hft_engine_http.exe...
go build -o hft_engine_http.exe main_with_http.go

if %ERRORLEVEL% neq 0 (
    echo.
    echo     [ERROR] Build failed!
    echo     Attempting to fix...
    go mod tidy
    go build -o hft_engine_http.exe main_with_http.go
    
    if %ERRORLEVEL% neq 0 (
        echo     [FATAL] Cannot build Go engine
        cd ..
        pause
        exit /b 1
    )
)

cd ..
echo     [OK] Go Engine built successfully
echo.

REM ==========================================
REM STEP 3: Start Go Engine
REM ==========================================
echo [3] Starting Go Engine with Full Monitoring...
echo.
echo     Services:
echo       - HTTP API:      http://127.0.0.1:8080/api/v1/risk/stats
echo       - System Metrics: http://127.0.0.1:8080/api/v1/system/metrics
echo       - Engine Status: http://127.0.0.1:8080/api/v1/status
echo       - Prometheus:    http://127.0.0.1:9090/metrics
echo.

start "[P10-Go] Engine [8080/9090]" cmd /k "cd /d "%CD%\core_go" ^&^& echo ====================================== ^&^& echo   P10 Go Engine ^&^& echo ====================================== ^&^& echo Symbol: BTCUSDT (Paper Trading) ^&^& echo Ports: 8080 (API), 9090 (Metrics) ^&^& echo. ^&^& hft_engine_http.exe btcusdt paper ^&^& echo. ^&^& echo [ERROR] Engine stopped unexpectedly ^&^& pause"

echo     [OK] Go Engine started in new window
echo.
echo     Waiting 5 seconds for initialization...
timeout /t 5 /nobreak >nul

REM Verify Go Engine
curl -s http://127.0.0.1:8080/api/v1/status >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo     [OK] Go Engine responding on port 8080
) else (
    echo     [WARN] Go Engine starting up (may need more time)
)
echo.

REM ==========================================
REM STEP 4: Start Python P10 with Real Metrics
REM ==========================================
echo [4] Starting Python P10 with Prometheus Metrics...
echo.
echo     Service:
echo       - P10 Metrics:   http://127.0.0.1:8000/metrics
echo.

start "[P10-Py] Orchestrator [8000]" cmd /k "cd /d "%CD%" ^&^& echo ====================================== ^&^& echo   P10 Python Orchestrator ^&^& echo ====================================== ^&^& echo Port: 8000 (Metrics) ^&^& echo. ^&^& python hedge_fund_os\demo_monitoring.py ^&^& echo. ^&^& echo [ERROR] Python stopped unexpectedly ^&^& pause"

echo     [OK] Python Orchestrator started in new window
echo.
echo     Waiting 3 seconds...
timeout /t 3 /nobreak >nul

REM ==========================================
REM STEP 5: Start Real-time Monitoring
REM ==========================================
echo [5] Starting Real-time Metrics Monitor...
echo.

start "[P10-Monitor] Real-time" cmd /k "cd /d "%CD%" ^&^& echo ====================================== ^&^& echo   P10 Real-time Monitor ^&^& echo ====================================== ^&^& echo Press Ctrl+C to stop monitoring ^&^& echo. ^&^& :loop ^&^& cls ^&^& echo === P10 System Status === ^&^& echo. ^&^& echo --- Go Engine (8080) --- ^&^& curl -s http://127.0.0.1:8080/api/v1/risk/stats 2^>nul ^&^& echo. ^&^& echo --- P10 Metrics (8000) --- ^&^& curl -s http://127.0.0.1:8000/metrics 2^>nul ^| findstr hfos_system_mode ^&^& curl -s http://127.0.0.1:8000/metrics 2^>nul ^| findstr hfos_daily_drawdown ^&^& echo. ^&^& timeout /t 5 ^>nul ^&^& goto loop"

echo     [OK] Real-time monitor started
echo.

REM ==========================================
REM STEP 6: Final Verification
REM ==========================================
echo [6] System Verification...
echo.

echo     Testing endpoints...

REM Test Go API
curl -s http://127.0.0.1:8080/api/v1/risk/stats >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo     [OK] Go API:        http://127.0.0.1:8080/api/v1/risk/stats
) else (
    echo     [WAIT] Go API:      Starting...
)

REM Test Go Metrics
curl -s http://127.0.0.1:9090/metrics >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo     [OK] Go Metrics:    http://127.0.0.1:9090/metrics
) else (
    echo     [WAIT] Go Metrics:  Starting...
)

REM Test Python P10
curl -s http://127.0.0.1:8000/metrics >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo     [OK] P10 Metrics:   http://127.0.0.1:8000/metrics
) else (
    echo     [WAIT] P10 Metrics: Starting...
)

echo.

REM ==========================================
REM STEP 7: Display Summary
REM ==========================================
echo ==========================================
echo   P10 Production System Started!
echo ==========================================
echo.
echo Active Windows:
echo   [P10-Go]      Go Engine (HTTP + Prometheus)
echo   [P10-Py]      Python Orchestrator
echo   [P10-Monitor] Real-time status monitor
echo.
echo Service Endpoints:
echo   Go API:       http://127.0.0.1:8080/api/v1/risk/stats
echo   Go System:    http://127.0.0.1:8080/api/v1/system/metrics
echo   Go Status:    http://127.0.0.1:8080/api/v1/status
echo   Go Prometheus:http://127.0.0.1:9090/metrics
echo   P10 Metrics:  http://127.0.0.1:8000/metrics
echo.
echo Verification Commands:
echo   curl http://127.0.0.1:8080/api/v1/risk/stats
echo   curl http://127.0.0.1:9090/metrics ^| findstr hft_engine
echo   curl http://127.0.0.1:8000/metrics ^| findstr hfos_
echo.
echo Decision Logs:
echo   logs/decisions/*.jsonl
echo.
echo To Stop:
echo   Close all [P10-*] windows or press Ctrl+C in each
echo.
echo ==========================================

pause
