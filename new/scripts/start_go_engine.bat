@echo off
chcp 65001 >nul
cls

echo ==========================================
echo   P10 Go Engine Launcher
echo ==========================================
echo.

REM Check if we're in the right directory
if not exist "core_go\engine.go" (
    echo ERROR: Please run this script from the project root directory
    exit /b 1
)

cd core_go

echo [1] Building Go Engine...
go build -o hft_engine_http.exe main_with_http.go

if %ERRORLEVEL% neq 0 (
    echo ERROR: Build failed!
    exit /b 1
)

echo      [OK] Build successful
echo.

REM Set default values
set SYMBOL=btcusdt
set MODE=paper

REM Parse arguments
if not "%~1"=="" set SYMBOL=%~1
if not "%~2"=="" set MODE=%~2

echo [2] Configuration:
echo      Symbol: %SYMBOL%
echo      Mode: %MODE%
echo.

echo [3] Starting Go Engine...
echo      HTTP API: http://localhost:8080
echo      Metrics:  http://localhost:9090/metrics
echo.

hft_engine_http.exe %SYMBOL% %MODE%
