@echo off
echo ==========================================
echo  24-Hour Signal Data Collection
echo ==========================================
echo.
echo Configuration:
echo   Symbol: BTCUSDT
echo   Capital: 1000 USDT
echo   Spot Margin: Enabled (3x Cross)
echo   Duration: 24 hours
echo.
echo Press Ctrl+C to stop early
echo.

python start_data_collection.py ^
    --symbol BTCUSDT ^
    --capital 1000 ^
    --duration 24 ^
    --spot-margin ^
    --margin-mode cross ^
    --max-leverage 3 ^
    --check-interval 5 ^
    --persist-file signal_stats_btc_24h.json

echo.
echo ==========================================
echo  Collection completed!
echo  Run: python check_signal_stats.py
echo ==========================================
pause
