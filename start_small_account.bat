@echo off
chcp 65001 >nul
echo ==========================================
echo  冠军策略 MA(12,28) - 小额账户版
echo ==========================================
echo.
echo 配置:
echo   适合资金: $10-100
echo   最小订单: $10
echo   止盈: 6%% (降低，更快落袋)
echo   止损: 3%%
echo   冷却期: 4小时 (亏损后暂停)
echo.
echo 按 Ctrl+C 停止交易
echo.
pause

cd /d D:\binance
python live_trading_small_account.py

echo.
echo 交易已停止
echo 日志位置: logs/small_account_*.log
echo 状态文件: small_account_state.json
pause
