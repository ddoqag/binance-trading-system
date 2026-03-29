@echo off
chcp 65001 >nul
echo ==========================================
echo  冠军策略 MA(12,28) - 杠杆全仓双向版
echo ==========================================
echo.
echo 配置:
echo   杠杆: 2x
echo   支持: 做多/做空
echo   止盈: 6%%
echo   止损: 3%%
echo.
echo 按 Ctrl+C 停止交易
echo.
pause

cd /d D:\binance
python live_trading_margin.py

echo.
echo 交易已停止
echo 日志位置: logs/margin_*.log
echo 状态文件: margin_trading_state.json
pause
