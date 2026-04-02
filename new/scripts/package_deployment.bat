@echo off
chcp 65001 >nul
cls

echo ==========================================
echo   P10 Deployment Package Builder
echo ==========================================
echo.

set VERSION=1.0.0
set TIMESTAMP=%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%
set TIMESTAMP=%TIMESTAMP: =0%
set PACKAGE_NAME=p10_deployment_%VERSION%_%TIMESTAMP%.zip

echo Building deployment package: %PACKAGE_NAME%
echo.

REM Create temporary directory
set TEMP_DIR=temp_deploy
if exist %TEMP_DIR% rmdir /s /q %TEMP_DIR%
mkdir %TEMP_DIR%
mkdir %TEMP_DIR%\core_go
mkdir %TEMP_DIR%\hedge_fund_os
mkdir %TEMP_DIR%\scripts
mkdir %TEMP_DIR%\docs
mkdir %TEMP_DIR%\logs
mkdir %TEMP_DIR%\config

echo [1] Copying Go Engine...
copy core_go\hft_engine_http.exe %TEMP_DIR%\core_go\ >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo     [WARN] hft_engine_http.exe not found
    echo          Please build first: cd core_go ^&^& go build
) else (
    echo     [OK] Go Engine copied
)

echo [2] Copying Python P10 Core...
xcopy /s /e /i hedge_fund_os\*.py %TEMP_DIR%\hedge_fund_os\ >nul
echo     [OK] Python modules copied

echo [3] Copying Scripts...
copy scripts\*.bat %TEMP_DIR%\scripts\ >nul
copy scripts\*.ps1 %TEMP_DIR%\scripts\ >nul 2>&1
echo     [OK] Scripts copied

echo [4] Copying Documentation...
copy docs\WINDOWS_INTEGRATION_GUIDE.md %TEMP_DIR%\docs\ >nul
echo     [OK] Documentation copied

echo [5] Copying Config files...
copy config\* %TEMP_DIR%\config\ >nul 2>&1
echo     [OK] Config files copied

echo [6] Creating README...
(
echo # P10 Hedge Fund OS - Deployment Package
echo.
echo Version: %VERSION%
echo Build Date: %date% %time%
echo.
echo ## Quick Start
echo.
echo 1. Run cold start check:
echo    scripts\cold_start_check.bat
echo.
echo 2. Start Go Engine:
echo    scripts\start_go_engine.bat btcusdt paper
echo.
echo 3. Verify performance:
echo    python performance_benchmark.py --quick
echo.
echo 4. Start trading:
echo    python -m hedge_fund_os.orchestrator
echo.
echo ## System Requirements
echo.
echo - Windows 10/11
echo - Go 1.21+ (for rebuilding)
echo - Python 3.10+
echo - 8GB+ RAM
echo - Internet connection
echo.
echo ## Support
echo.
echo See docs/WINDOWS_INTEGRATION_GUIDE.md for troubleshooting
echo.
) > %TEMP_DIR%\README.txt

echo     [OK] README created

echo [7] Creating startup script...
(
echo @echo off
echo echo Starting P10 Hedge Fund OS...
echo echo.
echo start cmd /k "scripts\start_go_engine.bat"
echo timeout /t 3 /nobreak ^>nul
echo start cmd /k "python performance_benchmark.py --quick"
echo.
echo echo All services started. Check the other windows.
echo pause
) > %TEMP_DIR%\START.bat

echo     [OK] Startup script created

echo [8] Building ZIP package...
powershell -Command "Compress-Archive -Path '%TEMP_DIR%\*' -DestinationPath '%PACKAGE_NAME%' -Force"
if %ERRORLEVEL% equ 0 (
    echo     [OK] Package created: %PACKAGE_NAME%
) else (
    echo     [FAIL] Failed to create package
    goto cleanup
)

:cleanup
echo [9] Cleaning up...
rmdir /s /q %TEMP_DIR%
echo     [OK] Cleanup complete

echo.
echo ==========================================
echo   Deployment Package Complete
echo ==========================================
echo.
echo Package: %PACKAGE_NAME%
echo.
echo Contents:
echo   - core_go/hft_engine_http.exe
echo   - hedge_fund_os/*.py
echo   - scripts/*.bat
echo   - docs/
echo   - README.txt
echo   - START.bat
echo.
echo Ready for deployment to Yunnan/Cambodia!
echo.
pause
