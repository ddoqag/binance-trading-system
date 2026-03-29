@echo off
chcp 65001 >nul
echo ==========================================
echo  职业级交易系统 v3.0
echo ==========================================
echo.
echo 集成模块:
echo   [1] 多周期系统  - 1h定向 + 5m精确入场
echo   [2] 订单簿alpha - 买卖失衡 + 大单检测
echo   [3] RL仓位控制  - Q-learning自适应仓位
echo.
echo 配置:
echo   基础仓位: 40%%  RL调整范围: 25%%-125%%
echo   止损: 2.5%%     止盈: 7%%
echo   每日最大亏损: 5%%  总最大回撤: 15%%
echo.
echo 按 Ctrl+C 停止交易
echo.
pause

cd /d D:\binance
python live_trading_pro.py

echo.
echo 交易已停止
echo 日志: logs/pro_*.log
echo 状态: pro_trading_state.json
echo RL Q表: rl_qtable.json
pause
