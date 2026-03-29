@echo off
chcp 65001 >nul
echo ==========================================
echo  Pro Trading System v4.0
echo  Multi-Strategy + RL Allocation
echo ==========================================
echo.
echo Strategies:
echo   - DualMA: Trend following
echo   - RSI: Mean reversion
echo   - OB_Micro: Order book signals
echo.
echo RL Allocation:
echo   - Dynamic strategy weighting
echo   - Performance feedback loop
echo.
echo Press Ctrl+C to stop
echo.
pause

cd /d D:\binance
python live_trading_pro_v2.py --paper

echo.
echo Trading stopped
echo Logs: logs/pro_v2_*.log
echo State: pro_v2_state.json
echo RL Q-table: rl_strategy_qtable.json
pause
