# HFT System Monitor
# 实时监控 Go 引擎和 Python Agent

while ($true) {
    Clear-Host
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "   HFT Trading System Monitor" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    
    # 检查进程
    $engines = Get-Process engine -ErrorAction SilentlyContinue
    $pythons = Get-Process python -ErrorAction SilentlyContinue
    
    Write-Host "[Go Engine]" -ForegroundColor Yellow
    if ($engines) {
        $engines | ForEach-Object {
            Write-Host "  PID: $($_.Id), Memory: $([math]::Round($_.WorkingSet64 / 1MB, 2)) MB, CPU: $($_.CPU)" -ForegroundColor Green
        }
    } else {
        Write-Host "  NOT RUNNING!" -ForegroundColor Red
    }
    
    Write-Host ""
    Write-Host "[Python Processes]" -ForegroundColor Yellow
    if ($pythons) {
        Write-Host "  Count: $($pythons.Count)" -ForegroundColor Green
        $pythons | Select-Object -First 3 | ForEach-Object {
            Write-Host "  PID: $($_.Id), Memory: $([math]::Round($_.WorkingSet64 / 1MB, 2)) MB" -ForegroundColor Gray
        }
    }
    
    Write-Host ""
    Write-Host "[Shared Memory]" -ForegroundColor Yellow
    Get-ChildItem data\hft_trading_shm* -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "  $($_.Name): $([math]::Round($_.Length / 1KB, 2)) KB" -ForegroundColor Green
    }
    
    Write-Host ""
    Write-Host "[Latest Logs]" -ForegroundColor Yellow
    Get-ChildItem logs\*.log -ErrorAction SilentlyContinue | 
        Sort-Object LastWriteTime -Descending | 
        Select-Object -First 3 | 
        ForEach-Object {
            Write-Host "  $($_.Name): $([math]::Round($_.Length / 1KB, 2)) KB" -ForegroundColor Gray
        }
    
    Write-Host ""
    Write-Host "Press Ctrl+C to stop monitoring" -ForegroundColor DarkGray
    
    Start-Sleep -Seconds 2
}
