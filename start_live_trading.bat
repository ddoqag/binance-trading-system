@echo off
chcp 65001 >nul
echo ==========================================
echo  冠军策略 MA(12,28) 主网实盘交易启动器
echo ==========================================
echo.
echo 配置:
echo   网络: 主网 (真实资金)
echo   策略: MA(12,28) + SL3%% + TP8%% + RSI(21)
echo   限制: 最大日亏损5%%, 单笔仓位20%%
echo   时长: 14天自动退出
echo.
echo 按 Ctrl+C 停止交易，状态将自动保存
echo.
pause

cd /d D:\binance
python live_trading_production.py

echo.
echo 交易已停止
echo 日志位置: logs/
echo 状态文件: trading_state.json
pause
