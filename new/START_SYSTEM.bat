@echo off
chcp 65001 >nul
cls

echo ==========================================
echo   P10 Hedge Fund OS - System Launcher
echo ==========================================
echo.

REM Try to find project root by looking for core_go directory
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM Check if we're in the right directory (look for core_go\engine.go)
if not exist "core_go\engine.go" (
    echo [ERROR] Cannot find project root directory
echo.
    echo Please ensure you run this script from the project root:
    echo   D:\binance\new\START_SYSTEM.bat
echo.
    echo Current directory: %CD%
    echo.
    pause
    exit /b 1
)

echo [INFO] Project root: %CD%
echo.

REM ==========================================
REM STEP 1: Cold Start Check
REM ==========================================
echo [1] Running Cold Start Check...
echo.

echo     Checking Go Engine binary...
if exist "core_go\hft_engine_http.exe" (
    echo     [OK] hft_engine_http.exe found
) else (
    echo     [INFO] hft_engine_http.exe not found, will build
)

echo     Checking Python...
python --version >nul 2>&1
if %ERRORLEVEL% equ 0 (
    for /f "tokens=*" %%a in ('python --version') do echo     [OK] %%a
) else (
    echo     [ERROR] Python not found! Please install Python 3.10+
    pause
    exit /b 1
)

echo     Checking logs directory...
if not exist "logs" mkdir logs
echo     [OK] logs/ directory ready
echo.

REM ==========================================
REM STEP 2: Build Go Engine (if needed)
REM ==========================================
echo [2] Checking Go Engine build...

if not exist "core_go\hft_engine_http.exe" (
    echo     Building Go Engine...
    echo     This may take 30-60 seconds...
    echo.
    
    cd core_go
    go build -o hft_engine_http.exe main_with_http.go
    
    if %ERRORLEVEL% neq 0 (
        echo.
        echo     [ERROR] Build failed!
        echo     Please check:
        echo       1. Go is installed: go version
echo       2. Run: go mod tidy
echo       3. Check for compilation errors
echo.
        cd ..
        pause
        exit /b 1
    )
    
    cd ..
    echo     [OK] Build successful
) else (
    echo     [OK] Using existing binary
)
echo.

REM ==========================================
REM STEP 3: Start Go Engine
REM ==========================================
echo [3] Starting Go Engine...
echo     Symbol: BTCUSDT (Paper Trading)
echo     Ports: 8080 (API), 9090 (Metrics)
echo.

start "P10-GoEngine [8080/9090]" cmd /k "cd /d "%CD%\core_go" && echo Starting Go Engine... && hft_engine_http.exe btcusdt paper || echo [ERROR] Go Engine crashed && pause"

echo     [OK] Go Engine window opened
echo     Waiting 5 seconds for initialization...
timeout /t 5 /nobreak >nul
echo.

REM ==========================================
REM STEP 4: Verify Go Engine
REM ==========================================
echo [4] Verifying Go Engine...
curl -s http://127.0.0.1:8080/api/v1/status >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo     [OK] Go Engine responding on port 8080
) else (
    echo     [WARN] Go Engine not responding yet
echo     May need a few more seconds...
)
echo.

REM ==========================================
REM STEP 5: Start Python P10
REM ==========================================
echo [5] Starting Python P10 Orchestrator...
echo     Port: 8000 (P10 Metrics)
echo.

start "P10-Python [8000]" cmd /k "cd /d "%CD%" && echo Starting Python P10... && python hedge_fund_os\demo_full.py || echo [ERROR] Python crashed && pause"

echo     [OK] Python window opened
echo     Waiting 3 seconds...
timeout /t 3 /nobreak >nul
echo.

REM ==========================================
REM STEP 6: Final Status
REM ==========================================
echo ==========================================
echo   P10 System Status
echo ==========================================
echo.

echo Running Services:
curl -s http://127.0.0.1:8080/api/v1/status >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo   [OK] Go Engine:      http://127.0.0.1:8080
echo   [OK] Go Metrics:     http://127.0.0.1:9090
) else (
    echo   [WAIT] Go Engine:    Starting...
)

echo   [OK] Python P10:     http://127.0.0.1:8000
echo.

echo Quick Verification Commands:
echo   curl http://127.0.0.1:8080/api/v1/risk/stats
echo   curl http://127.0.0.1:9090/metrics ^| findstr hft_engine
echo   curl http://127.0.0.1:8000/metrics ^| findstr hfos_
echo.

echo Logs Location:
echo   %CD%\logs\
echo.

echo To Stop:
echo   1. Close the "P10-GoEngine" window
echo   2. Close the "P10-Python" window
echo.

echo ==========================================
echo   P10 Hedge Fund OS is Running!
echo ==========================================
echo.

pause
