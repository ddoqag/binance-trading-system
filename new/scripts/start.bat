@echo off
REM start.bat - HFT Trading System Startup Script for Windows
REM
REM Usage: start.bat [symbol] [mode]
REM   symbol: trading pair (default: btcusdt)
REM   mode: paper|live (default: paper)

setlocal enabledelayedexpansion

set SYMBOL=%~1
if "%SYMBOL%"=="" set SYMBOL=btcusdt

set MODE=%~2
if "%MODE%"=="" set MODE=paper

set SHM_PATH=.\data\hft_trading_shm

echo ============================================
echo   HFT Trading System Startup
echo ============================================
echo Symbol: %SYMBOL%
echo Mode: %MODE%
echo ============================================

REM Clean up previous shared memory
if exist "%SHM_PATH%" (
    echo Cleaning up previous shared memory...
    del /f "%SHM_PATH%" 2>nul
)

REM Create necessary directories
if not exist logs mkdir logs
if not exist data mkdir data
if not exist checkpoints mkdir checkpoints

REM Check for go
where go >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: Go not found in PATH
    exit /b 1
)

REM Check for python
where python >nul 2>nul
if %errorlevel% neq 0 (
    where python3 >nul 2>nul
    if %errorlevel% neq 0 (
        echo Error: Python not found in PATH
        exit /b 1
    ) else (
        set PYTHON=python3
    )
) else (
    set PYTHON=python
)

REM Build Go engine if needed
echo Building Go execution engine...
cd core_go
go build -o engine.exe -ldflags="-s -w" .
if %errorlevel% neq 0 (
    echo Error: Failed to build Go engine
    cd ..
    exit /b 1
)
cd ..

REM Start Go execution engine
echo Starting Go execution engine...
start /b "GoEngine" cmd /c "core_go\engine.exe %SYMBOL% %MODE% > logs\go_engine.log 2>&1"
set GO_PID=%ERRORLEVEL%
echo Go engine started

REM Wait for shared memory
echo Waiting for shared memory initialization...
timeout /t 2 /nobreak >nul

if not exist "%SHM_PATH%" (
    REM Try alternative path
    if not exist ".\data\hft_trading_shm" (
        echo Warning: Shared memory file not found, but continuing...
    )
)

REM Start Python AI brain
echo Starting Python AI brain...
cd brain_py
start /b "PythonAgent" cmd /c "%PYTHON% agent.py > ..\logs\python_agent.log 2>&1"
cd ..
echo Python brain started

echo.
echo ============================================
echo   HFT System Started Successfully
echo ============================================
echo Logs:
echo   Go Engine:    type logs\go_engine.log
echo   Python Agent: type logs\python_agent.log
echo.
echo Press Ctrl+C to stop
echo ============================================

REM Monitor loop
:monitor
    timeout /t 5 /nobreak >nul
    tasklist | findstr "engine.exe" >nul
    if %errorlevel% neq 0 (
        echo ERROR: Go engine has stopped!
        goto cleanup
    )
    tasklist | findstr "python" >nul
    if %errorlevel% neq 0 (
        echo ERROR: Python agent has stopped!
        goto cleanup
    )
goto monitor

:cleanup
echo.
echo Shutting down HFT System...
taskkill /f /im engine.exe 2>nul
taskkill /f /im python.exe 2>nul
taskkill /f /im python3.exe 2>nul
echo Shutdown complete
exit /b 0
